"""Tests for parsers.py module."""

import pytest
from gcpath.parsers import (
    clean_asset_name,
    extract_value,
    extract_list_values,
    parse_parent_struct,
    validate_row_structure,
    parse_project_row,
    parse_folder_row,
    build_folder_ancestors,
)


# Test clean_asset_name
def test_clean_asset_name():
    """Test that Asset API prefix is correctly stripped."""
    assert (
        clean_asset_name("//cloudresourcemanager.googleapis.com/folders/123")
        == "folders/123"
    )
    assert clean_asset_name("folders/123") == "folders/123"
    assert (
        clean_asset_name("//cloudresourcemanager.googleapis.com/projects/456")
        == "projects/456"
    )


# Test extract_value
def test_extract_value_with_mapcomposite():
    """Test extracting value from MapComposite-like object."""

    # Simulate MapComposite behavior
    class FakeMapComposite:
        def __init__(self, value):
            self._value = value

        def get(self, key, default=None):
            if key == "v":
                return self._value
            return default

    obj = FakeMapComposite("test_value")
    assert extract_value(obj) == "test_value"


def test_extract_value_with_dict():
    """Test extracting value from dict."""
    obj = {"v": "test_value"}
    assert extract_value(obj) == "test_value"


def test_extract_value_with_plain_value():
    """Test extracting value from plain object."""
    assert extract_value("plain_value") == "plain_value"
    assert extract_value(123) == 123


# Test extract_list_values
def test_extract_list_values():
    """Test extracting list of ancestors."""
    ancestors_wrapper = [
        {"v": "//cloudresourcemanager.googleapis.com/folders/1"},
        {"v": "//cloudresourcemanager.googleapis.com/organizations/123"},
    ]
    result = extract_list_values(ancestors_wrapper)
    assert result == ["folders/1", "organizations/123"]


def test_extract_list_values_empty():
    """Test extracting empty ancestor list."""
    assert extract_list_values([]) == []
    assert extract_list_values(None) == []


# Test parse_parent_struct
def test_parse_parent_struct_nested_format():
    """Test parsing parent STRUCT in nested format."""
    # Nested format: {"v": {"f": [{"v": "folder"}, {"v": "123"}]}}
    parent_col = {"v": {"f": [{"v": "folder"}, {"v": "123"}]}}
    result = parse_parent_struct(parent_col)
    assert result == "folders/123"


def test_parse_parent_struct_organization():
    """Test parsing parent STRUCT for organization."""
    parent_col = {"v": {"f": [{"v": "organization"}, {"v": "789"}]}}
    result = parse_parent_struct(parent_col)
    assert result == "organizations/789"


def test_parse_parent_struct_empty():
    """Test parsing empty parent STRUCT."""
    assert parse_parent_struct({"v": None}) is None
    assert parse_parent_struct({"v": {}}) is None
    assert parse_parent_struct(None) is None


def test_parse_parent_struct_with_mapcomposite():
    """Test parsing parent STRUCT with MapComposite objects."""

    # Simulate MapComposite behavior
    class FakeMapComposite:
        def __init__(self, data):
            self._data = data

        def get(self, key, default=None):
            return self._data.get(key, default)

        def keys(self):
            return self._data.keys()

        def __getitem__(self, key):
            return self._data[key]

    # Create nested MapComposite structure
    parent_col = FakeMapComposite(
        {
            "v": FakeMapComposite(
                {
                    "f": [
                        FakeMapComposite({"v": "folder"}),
                        FakeMapComposite({"v": "999"}),
                    ]
                }
            )
        }
    )

    result = parse_parent_struct(parent_col)
    assert result == "folders/999"


# Test validate_row_structure
def test_validate_row_structure_valid():
    """Test validating valid row structure."""
    row = {"f": [1, 2, 3, 4]}
    assert validate_row_structure(row, 4, "test") is True


def test_validate_row_structure_missing_f():
    """Test validating row without 'f' field."""
    row = {"data": [1, 2, 3]}
    assert validate_row_structure(row, 4, "test") is False


def test_validate_row_structure_too_few_columns():
    """Test validating row with too few columns."""
    row = {"f": [1, 2]}
    assert validate_row_structure(row, 4, "test") is False


# Test parse_project_row
def test_parse_project_row():
    """Test parsing a project row."""
    row = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/projects/789"},
            {"v": "12345"},  # projectNumber
            {"v": "test-project"},  # projectId
            {"v": {"f": [{"v": "folder"}, {"v": "456"}]}},  # parent STRUCT
            {"v": [{"v": "folders/456"}, {"v": "organizations/123"}]},  # ancestors
        ]
    }

    result = parse_project_row(row)
    assert result["name"] == "projects/789"
    assert result["project_id"] == "test-project"
    assert result["display_name"] == "test-project"
    assert result["parent"] == "folders/456"
    assert result["ancestors"] == ["folders/456", "organizations/123"]


def test_parse_project_row_with_empty_ancestors():
    """Test parsing project row with empty ancestors (parent filter case)."""
    row = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/projects/789"},
            {"v": "12345"},
            {"v": "test-project"},
            {"v": {"f": [{"v": "organization"}, {"v": "123"}]}},
            {"v": []},  # Empty ancestors
        ]
    }

    result = parse_project_row(row)
    assert result["name"] == "projects/789"
    assert result["parent"] == "organizations/123"
    assert result["ancestors"] == []


def test_parse_project_row_invalid_structure():
    """Test parsing project row with invalid structure."""
    row = {"f": [1, 2]}  # Too few columns
    with pytest.raises(ValueError, match="Invalid project row structure"):
        parse_project_row(row)


# Test parse_folder_row
def test_parse_folder_row():
    """Test parsing a folder row."""
    row = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/folders/456"},
            {"v": "Test Folder"},
            {"v": "folders/123"},
            {
                "v": [
                    {"v": "folders/456"},
                    {"v": "folders/123"},
                    {"v": "organizations/123"},
                ]
            },
        ]
    }

    result = parse_folder_row(row)
    assert result["name"] == "folders/456"
    assert result["display_name"] == "Test Folder"
    assert result["parent"] == "folders/123"
    assert result["ancestors"] == ["folders/456", "folders/123", "organizations/123"]


def test_parse_folder_row_no_parent():
    """Test parsing folder row with no parent."""
    row = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/folders/1"},
            {"v": "Root Folder"},
            {"v": None},  # No parent
            {"v": [{"v": "folders/1"}, {"v": "organizations/123"}]},
        ]
    }

    result = parse_folder_row(row)
    assert result["name"] == "folders/1"
    assert result["parent"] is None


def test_parse_folder_row_missing_display_name():
    """Test parsing folder row with missing display name."""
    row = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/folders/456"},
            {"v": None},  # Missing display name
            {"v": "folders/123"},
            {"v": []},
        ]
    }

    with pytest.raises(ValueError, match="Missing name or display_name"):
        parse_folder_row(row)


def test_parse_folder_row_invalid_structure():
    """Test parsing folder row with invalid structure."""
    row = {"f": [1, 2]}  # Too few columns
    with pytest.raises(ValueError, match="Invalid folder row structure"):
        parse_folder_row(row)


# Test build_folder_ancestors
def test_build_folder_ancestors_with_complete_ancestors():
    """Test building ancestors when ancestors list is complete."""
    name = "folders/456"
    raw_ancestors = ["folders/456", "folders/123", "organizations/123"]
    parent = "folders/123"
    loaded_folders = {}
    org_name = "organizations/123"

    result = build_folder_ancestors(
        name, raw_ancestors, parent, loaded_folders, org_name
    )
    assert result == ["folders/456", "folders/123", "organizations/123"]


def test_build_folder_ancestors_empty_list():
    """Test building ancestors when ancestors list is empty."""
    name = "folders/456"
    raw_ancestors = []
    parent = "folders/123"

    # Mock loaded folders
    class MockFolder:
        def __init__(self, ancestors):
            self.ancestors = ancestors

    loaded_folders = {"folders/123": MockFolder(["folders/123", "organizations/123"])}
    org_name = "organizations/123"

    result = build_folder_ancestors(
        name, raw_ancestors, parent, loaded_folders, org_name
    )
    assert name in result
    assert "folders/123" in result
    assert org_name in result


def test_build_folder_ancestors_missing_self():
    """Test building ancestors when self is missing from ancestors list."""
    name = "folders/456"
    raw_ancestors = ["folders/123", "organizations/123"]
    parent = "folders/123"
    loaded_folders = {}
    org_name = "organizations/123"

    result = build_folder_ancestors(
        name, raw_ancestors, parent, loaded_folders, org_name
    )
    # Should prepend self
    assert result[0] == "folders/456"
    assert "folders/123" in result
    assert org_name in result


def test_build_folder_ancestors_org_parent():
    """Test building ancestors when parent is organization."""
    name = "folders/1"
    raw_ancestors = []
    parent = "organizations/123"
    loaded_folders = {}
    org_name = "organizations/123"

    result = build_folder_ancestors(
        name, raw_ancestors, parent, loaded_folders, org_name
    )
    assert result == ["folders/1", "organizations/123"]
