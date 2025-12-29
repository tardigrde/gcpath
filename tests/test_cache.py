"""
Tests for the cache module.
"""

import json
from unittest.mock import patch
from pathlib import Path

import pytest
from google.cloud import resourcemanager_v3

from gcpath.cache import (
    _hierarchy_to_dict,
    _dict_to_hierarchy,
    read_cache,
    write_cache,
    clear_cache,
    CACHE_VERSION,
)
from gcpath.core import Hierarchy, OrganizationNode, Folder, Project

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_CACHE_FILE = FIXTURES_DIR / "sample_cache_v1.json"


@pytest.fixture
def mock_hierarchy():
    """Returns a mock Hierarchy object for testing."""
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )
    org1 = OrganizationNode(organization=org_proto)

    folder1 = Folder(
        name="folders/456",
        display_name="Engineering",
        ancestors=["folders/456", "organizations/123"],
        parent="organizations/123",
        organization=org1,
    )
    org1.folders["folders/456"] = folder1

    project1 = Project(
        name="projects/789",
        project_id="test-project",
        display_name="Test Project",
        parent="folders/456",
        organization=org1,
        folder=folder1,
    )

    # Organizationless project
    project2 = Project(
        name="projects/000",
        project_id="orphan",
        display_name="Orphan",
        parent="organizations/0",
        organization=None,
        folder=None,
    )

    return Hierarchy(organizations=[org1], projects=[project1, project2])


def test_hierarchy_to_dict(mock_hierarchy):
    """Test serialization of Hierarchy to dictionary."""
    hierarchy_dict = _hierarchy_to_dict(mock_hierarchy)

    assert hierarchy_dict["version"] == CACHE_VERSION
    assert "timestamp" in hierarchy_dict
    assert len(hierarchy_dict["organizations"]) == 1
    assert len(hierarchy_dict["organizationless_projects"]) == 1

    org_data = hierarchy_dict["organizations"][0]
    assert org_data["organization"]["name"] == "organizations/123"
    assert len(org_data["folders"]) == 1
    assert len(org_data["projects"]) == 1
    assert org_data["projects"][0]["name"] == "projects/789"


def test_dict_to_hierarchy(mock_hierarchy):
    """Test deserialization of dictionary to Hierarchy."""
    hierarchy_dict = _hierarchy_to_dict(mock_hierarchy)
    new_hierarchy = _dict_to_hierarchy(hierarchy_dict)

    assert isinstance(new_hierarchy, Hierarchy)
    assert len(new_hierarchy.organizations) == 1
    # Check org proto type
    assert isinstance(
        new_hierarchy.organizations[0].organization, resourcemanager_v3.Organization
    )
    assert new_hierarchy.organizations[0].organization.name == "organizations/123"

    assert len(new_hierarchy.projects) == 2

    # Verify relationships
    p1 = next(p for p in new_hierarchy.projects if p.name == "projects/789")
    assert p1.organization is not None
    assert p1.organization.organization.name == "organizations/123"
    assert p1.folder is not None
    assert p1.folder.name == "folders/456"

    p2 = next(p for p in new_hierarchy.projects if p.name == "projects/000")
    assert p2.organization is None


def test_dict_to_hierarchy_version_mismatch():
    """Test that version mismatch returns None."""
    data = {"version": 9999, "organizations": []}
    assert _dict_to_hierarchy(data) is None


def test_load_from_fixture():
    """Test loading from the sample JSON fixture file."""
    with open(SAMPLE_CACHE_FILE, "r") as f:
        data = json.load(f)

    hierarchy = _dict_to_hierarchy(data)
    assert hierarchy is not None
    assert len(hierarchy.organizations) == 1
    assert len(hierarchy.projects) == 2


@patch("gcpath.cache.CACHE_FILE")
def test_read_cache_not_found(mock_cache_file):
    """Test read_cache when the cache file does not exist."""
    mock_cache_file.exists.return_value = False
    assert read_cache() is None


@patch("gcpath.cache.CACHE_FILE")
@patch("builtins.open")
@patch("json.load")
def test_read_cache_success(mock_json_load, mock_open, mock_cache_file):
    """Test successful reading of the cache."""
    mock_cache_file.exists.return_value = True
    # Return a minimal valid structure
    mock_json_load.return_value = {
        "version": CACHE_VERSION,
        "organizations": [],
        "organizationless_projects": [],
    }

    hierarchy = read_cache()
    assert isinstance(hierarchy, Hierarchy)


@patch("gcpath.cache.CACHE_DIR")
@patch("gcpath.cache.CACHE_FILE")
@patch("builtins.open")
@patch("json.dump")
def test_write_cache(
    mock_json_dump, mock_open, mock_cache_file, mock_cache_dir, mock_hierarchy
):
    """Test writing to the cache file."""
    write_cache(mock_hierarchy)
    mock_cache_dir.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_open.assert_called_once_with(mock_cache_file, "w")
    mock_json_dump.assert_called_once()

    # Verify the structure passed to json.dump has version
    args, _ = mock_json_dump.call_args
    data = args[0]
    assert data["version"] == CACHE_VERSION


@patch("gcpath.cache.CACHE_FILE")
def test_clear_cache_exists(mock_cache_file):
    """Test clearing the cache when the file exists."""
    mock_cache_file.exists.return_value = True
    assert clear_cache() is True
    mock_cache_file.unlink.assert_called_once()
