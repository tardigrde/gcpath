"""
Tests for the cache module.
"""

from unittest.mock import patch

import pytest
from gcpath.cache import (
    _hierarchy_to_dict,
    _dict_to_hierarchy,
    read_cache,
    write_cache,
    clear_cache,
)
from gcpath.core import Hierarchy, OrganizationNode, Folder, Project


@pytest.fixture
def mock_hierarchy():
    """Returns a mock Hierarchy object for testing."""

    class MockOrg:
        def __init__(self, name, display_name):
            self.name = name
            self.display_name = display_name

    org1 = OrganizationNode(
        organization=MockOrg("organizations/123", "example.com"),
    )
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

    return Hierarchy(organizations=[org1], projects=[project1])


def test_hierarchy_to_dict(mock_hierarchy):
    """Test serialization of Hierarchy to dictionary."""
    hierarchy_dict = _hierarchy_to_dict(mock_hierarchy)
    assert "organizations" in hierarchy_dict
    assert "projects" in hierarchy_dict
    assert len(hierarchy_dict["organizations"]) == 1
    assert len(hierarchy_dict["projects"]) == 1
    assert (
        hierarchy_dict["organizations"][0]["organization"]["name"] == "organizations/123"
    )
    assert hierarchy_dict["projects"][0]["name"] == "projects/789"


def test_dict_to_hierarchy(mock_hierarchy):
    """Test deserialization of dictionary to Hierarchy."""
    hierarchy_dict = _hierarchy_to_dict(mock_hierarchy)
    new_hierarchy = _dict_to_hierarchy(hierarchy_dict)
    assert isinstance(new_hierarchy, Hierarchy)
    assert len(new_hierarchy.organizations) == 1
    assert len(new_hierarchy.projects) == 1
    assert (
        new_hierarchy.organizations[0].organization.name
        == mock_hierarchy.organizations[0].organization.name
    )
    assert new_hierarchy.projects[0].name == mock_hierarchy.projects[0].name


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
    mock_json_load.return_value = {
        "organizations": [
            {
                "organization": {
                    "name": "organizations/123",
                    "display_name": "example.com",
                },
                "folders": {},
            }
        ],
        "projects": [],
    }
    hierarchy = read_cache()
    assert isinstance(hierarchy, Hierarchy)
    assert len(hierarchy.organizations) == 1


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


@patch("gcpath.cache.CACHE_FILE")
def test_clear_cache_exists(mock_cache_file):
    """Test clearing the cache when the file exists."""
    mock_cache_file.exists.return_value = True
    assert clear_cache() is True
    mock_cache_file.unlink.assert_called_once()


@patch("gcpath.cache.CACHE_FILE")
def test_clear_cache_not_exists(mock_cache_file):
    """Test clearing the cache when the file does not exist."""
    mock_cache_file.exists.return_value = False
    clear_cache()
    mock_cache_file.unlink.assert_not_called()
