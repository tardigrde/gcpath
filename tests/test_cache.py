"""
Tests for the cache module.
"""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from pathlib import Path

import pytest
from google.cloud import resourcemanager_v3

from gcpath.cache import (
    _hierarchy_to_dict,
    _dict_to_hierarchy,
    read_cache,
    read_cache_raw,
    write_cache,
    clear_cache,
    is_cache_fresh,
    get_cache_info,
    CACHE_VERSION,
    DEFAULT_CACHE_TTL_HOURS,
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
    """Test successful reading of the cache with fresh timestamp."""
    mock_cache_file.exists.return_value = True
    # Return a minimal valid structure with fresh timestamp
    mock_json_load.return_value = {
        "version": CACHE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
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


def test_is_cache_fresh_within_ttl():
    """Test that cache is fresh within TTL."""
    data = {
        "version": CACHE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    assert is_cache_fresh(data, DEFAULT_CACHE_TTL_HOURS) is True


def test_is_cache_fresh_expired():
    """Test that cache is stale when beyond TTL."""
    old_time = datetime.now(timezone.utc) - timedelta(hours=5)
    data = {
        "version": CACHE_VERSION,
        "timestamp": old_time.isoformat(),
    }
    assert is_cache_fresh(data, DEFAULT_CACHE_TTL_HOURS) is False


def test_is_cache_fresh_no_timestamp():
    """Test that cache without timestamp is not fresh."""
    data = {"version": CACHE_VERSION}
    assert is_cache_fresh(data) is False


def test_is_cache_fresh_invalid_timestamp():
    """Test that cache with invalid timestamp is not fresh."""
    data = {
        "version": CACHE_VERSION,
        "timestamp": "invalid-timestamp",
    }
    assert is_cache_fresh(data) is False


@patch("gcpath.cache.CACHE_FILE")
@patch("builtins.open")
@patch("json.load")
def test_read_cache_stale(mock_json_load, mock_open, mock_cache_file):
    """Test that read_cache returns None for stale cache."""
    mock_cache_file.exists.return_value = True
    old_time = datetime.now(timezone.utc) - timedelta(hours=5)
    mock_json_load.return_value = {
        "version": CACHE_VERSION,
        "timestamp": old_time.isoformat(),
        "organizations": [],
        "organizationless_projects": [],
    }

    hierarchy = read_cache()
    assert hierarchy is None


@patch("gcpath.cache.CACHE_FILE")
@patch("builtins.open")
@patch("json.load")
def test_read_cache_raw_success(mock_json_load, mock_open, mock_cache_file):
    """Test successful reading of raw cache data."""
    mock_cache_file.exists.return_value = True
    test_data = {
        "version": CACHE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "organizations": [],
        "organizationless_projects": [],
    }
    mock_json_load.return_value = test_data

    data = read_cache_raw()
    assert data == test_data


@patch("gcpath.cache.CACHE_FILE")
def test_get_cache_info_not_exists(mock_cache_file):
    """Test get_cache_info when cache file does not exist."""
    mock_cache_file.exists.return_value = False

    info = get_cache_info()
    assert info.exists is False
    assert info.fresh is False
    assert info.age_seconds is None
    assert info.size_bytes is None
    assert info.version is None
    assert info.org_count == 0


@patch("gcpath.cache.CACHE_FILE")
def test_get_cache_info_fresh(mock_cache_file):
    """Test get_cache_info for fresh cache."""
    mock_cache_file.exists.return_value = True
    mock_cache_file.stat.return_value.st_size = 1024

    test_data = {
        "version": CACHE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "organizations": [
            {
                "organization": {"name": "organizations/123", "display_name": "org1"},
                "folders": {
                    "folders/1": {
                        "name": "folders/1",
                        "display_name": "f1",
                        "ancestors": ["folders/1", "organizations/123"],
                        "parent": "organizations/123",
                    }
                },
                "projects": [
                    {
                        "name": "projects/p1",
                        "project_id": "p1",
                        "display_name": "P1",
                        "parent": "organizations/123",
                        "folder_name": None,
                    }
                ],
            }
        ],
        "organizationless_projects": [],
    }

    with patch("gcpath.cache.read_cache_raw", return_value=test_data):
        info = get_cache_info()

    assert info.exists is True
    assert info.fresh is True
    assert info.age_seconds is not None
    assert info.size_bytes == 1024
    assert info.version == CACHE_VERSION
    assert info.org_count == 1
    assert info.folder_count == 1
    assert info.project_count == 1


@patch("gcpath.cache.CACHE_FILE")
def test_get_cache_info_stale(mock_cache_file):
    """Test get_cache_info for stale cache."""
    mock_cache_file.exists.return_value = True
    mock_cache_file.stat.return_value.st_size = 512

    old_time = datetime.now(timezone.utc) - timedelta(hours=5)
    test_data = {
        "version": CACHE_VERSION,
        "timestamp": old_time.isoformat(),
        "organizations": [],
        "organizationless_projects": [],
    }

    with patch("gcpath.cache.read_cache_raw", return_value=test_data):
        info = get_cache_info()

    assert info.exists is True
    assert info.fresh is False
    assert info.age_seconds is not None
    assert info.size_bytes == 512
