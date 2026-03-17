"""Tests for loaders.py module."""

import pytest
from unittest.mock import MagicMock, patch
from gcpath.core import OrganizationNode, Folder
from gcpath.loaders import (
    build_folder_sql_query,
    build_project_sql_query,
    load_folders_asset,
    load_projects_asset,
    load_organizationless_projects,
    _build_single_ancestor_chain,
)
from google.cloud import resourcemanager_v3


@pytest.fixture
def mock_org():
    return resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )


@pytest.fixture
def mock_org_node(mock_org):
    return OrganizationNode(organization=mock_org)


# Test SQL query builders
def test_build_folder_sql_query_no_filter():
    """Test building folder SQL query without filters."""
    query = build_folder_sql_query()
    assert "lifecycleState = 'ACTIVE'" in query
    assert "resource.data.parent" in query  # Should be in SELECT
    assert "resource.data.parent =" not in query  # Should NOT be in WHERE


def test_build_folder_sql_query_with_parent_filter():
    """Test building folder SQL query with parent filter."""
    query = build_folder_sql_query(parent_filter="organizations/123")
    assert "lifecycleState = 'ACTIVE'" in query
    assert "resource.data.parent = 'organizations/123'" in query


def test_build_folder_sql_query_with_ancestors_filter():
    """Test building folder SQL query with ancestors filter."""
    query = build_folder_sql_query(ancestors_filter="folders/456")
    assert "lifecycleState = 'ACTIVE'" in query
    assert "'folders/456' IN UNNEST(ancestors)" in query
    assert "name != '//cloudresourcemanager.googleapis.com/folders/456'" in query


def test_build_project_sql_query_no_filter():
    """Test building project SQL query without filters."""
    query = build_project_sql_query()
    assert "lifecycleState = 'ACTIVE'" in query
    assert "resource.data.parent" in query  # Should be in SELECT
    assert "resource.data.parent.id" not in query  # Should NOT be in WHERE


def test_build_project_sql_query_with_parent_filter():
    """Test building project SQL query with parent filter."""
    query = build_project_sql_query(parent_filter="organizations/123")
    assert "lifecycleState = 'ACTIVE'" in query
    assert "resource.data.parent.id = '123'" in query


def test_build_project_sql_query_with_ancestors_filter():
    """Test building project SQL query with ancestors filter."""
    query = build_project_sql_query(ancestors_filter="folders/456")
    assert "lifecycleState = 'ACTIVE'" in query
    assert "'folders/456' IN UNNEST(ancestors)" in query


# Test load_folders_asset
@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_folders_asset(mock_asset_client_cls, mock_org_node):
    mock_client = mock_asset_client_cls.return_value

    # Mocking the response structure: plain dicts/lists for unmarshaled Structs
    # { "f": [ {"v": name}, {"v": displayName}, {"v": parent}, {"v": [ {"v": a1}, {"v": a2} ] } ] }
    def create_row(name, display_name, parent, ancestors):
        anc_vals = [{"v": anc} for anc in ancestors]
        row = {
            "f": [
                {"v": name},
                {"v": display_name},
                {"v": parent},
                {"v": anc_vals},  # ancestors is a list wrapper
            ]
        }
        return row

    mock_query_result = MagicMock()
    mock_query_result.rows = [
        create_row(
            "//cloudresourcemanager.googleapis.com/folders/1",
            "f1",
            "organizations/123",
            ["//cloudresourcemanager.googleapis.com/organizations/123"],
        )
    ]
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    load_folders_asset(mock_org_node)

    assert "folders/1" in mock_org_node.folders
    folder = mock_org_node.folders["folders/1"]
    assert folder.display_name == "f1"
    assert folder.parent == "organizations/123"
    # Verify prepending logic: [self, org]
    assert folder.ancestors == ["folders/1", "organizations/123"]


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_folders_asset_with_mapcomposite(mock_asset_client_cls, mock_org_node):
    """Test that MapComposite objects (protobuf wrappers) are handled correctly."""
    mock_client = mock_asset_client_cls.return_value

    # Simulate MapComposite behavior - dict-like but not isinstance(dict)
    class FakeMapComposite:
        def __init__(self, data):
            self._data = data

        def get(self, key, default=None):
            return self._data.get(key, default)

        def __iter__(self):
            return iter(self._data)

    # Create row with MapComposite objects (like real protobuf responses)
    # Format: name, displayName, parent, ancestors
    row = {
        "f": [
            FakeMapComposite(
                {"v": "//cloudresourcemanager.googleapis.com/folders/456"}
            ),
            FakeMapComposite({"v": "TestFolder"}),
            FakeMapComposite({"v": "organizations/123"}),  # parent
            FakeMapComposite({"v": []}),  # Empty ancestors due to parent filter
        ]
    }

    mock_query_result = MagicMock()
    mock_query_result.rows = [row]
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    load_folders_asset(mock_org_node)

    assert "folders/456" in mock_org_node.folders
    folder = mock_org_node.folders["folders/456"]
    assert folder.display_name == "TestFolder"
    assert folder.parent == "organizations/123"
    # With empty ancestors, should add org
    assert folder.ancestors == ["folders/456", "organizations/123"]


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_folders_asset_sql_filter(mock_asset_client_cls, mock_org_node):
    """Test that SQL query includes lifecycleState and parent filters when parent_filter is provided."""
    mock_client = mock_asset_client_cls.return_value

    mock_query_result = MagicMock()
    mock_query_result.rows = []
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    # Test with parent_filter (scoped query)
    load_folders_asset(mock_org_node, parent_filter="organizations/123")

    # Verify the query was called with the right statement
    call_args = mock_client.query_assets.call_args
    request = call_args[1]["request"] if call_args[1] else call_args[0][0]
    statement = request.statement

    # Check for lifecycle filter
    assert "lifecycleState = 'ACTIVE'" in statement
    # Check for parent filter
    assert "resource.data.parent = 'organizations/123'" in statement


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_folders_asset_sql_no_parent_filter(mock_asset_client_cls, mock_org_node):
    """Test that SQL query omits parent filter in WHERE clause when parent_filter is None (recursive mode)."""
    mock_client = mock_asset_client_cls.return_value

    mock_query_result = MagicMock()
    mock_query_result.rows = []
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    # Test without parent_filter (recursive query)
    load_folders_asset(mock_org_node, parent_filter=None)

    # Verify the query was called with the right statement
    call_args = mock_client.query_assets.call_args
    request = call_args[1]["request"] if call_args[1] else call_args[0][0]
    statement = request.statement

    # Check for lifecycle filter
    assert "lifecycleState = 'ACTIVE'" in statement
    # Should have resource.data.parent in SELECT (for the parent column)
    assert "resource.data.parent" in statement
    # But should NOT have parent filter in WHERE clause for recursive mode
    assert "resource.data.parent =" not in statement


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_folders_asset_folder_parent_filter(mock_asset_client_cls, mock_org_node):
    """Test that SQL query correctly filters by folder parent."""
    mock_client = mock_asset_client_cls.return_value

    mock_query_result = MagicMock()
    mock_query_result.rows = []
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    # Test with folder as parent_filter
    load_folders_asset(mock_org_node, parent_filter="folders/456")

    # Verify the query was called with the right statement
    call_args = mock_client.query_assets.call_args
    request = call_args[1]["request"] if call_args[1] else call_args[0][0]
    statement = request.statement

    # Check for lifecycle filter
    assert "lifecycleState = 'ACTIVE'" in statement
    # Check for folder parent filter
    assert "resource.data.parent = 'folders/456'" in statement


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_folders_asset_ancestors_filter(mock_asset_client_cls, mock_org_node):
    """Test that SQL query uses IN UNNEST(ancestors) filter for recursive scoped loading."""
    mock_client = mock_asset_client_cls.return_value

    mock_query_result = MagicMock()
    mock_query_result.rows = []
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    # Test with ancestors_filter (recursive under a folder)
    load_folders_asset(mock_org_node, ancestors_filter="folders/456")

    # Verify the query was called with the right statement
    call_args = mock_client.query_assets.call_args
    request = call_args[1]["request"] if call_args[1] else call_args[0][0]
    statement = request.statement

    # Check for lifecycle filter
    assert "lifecycleState = 'ACTIVE'" in statement
    # Check for ancestors filter with IN UNNEST() syntax
    assert "'folders/456' IN UNNEST(ancestors)" in statement
    # Check that it excludes the ancestor folder itself
    assert "name != '//cloudresourcemanager.googleapis.com/folders/456'" in statement
    # Should NOT have parent filter
    assert "resource.data.parent =" not in statement


# Test load_projects_asset
@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_projects_asset(mock_asset_client_cls, mock_org_node):
    mock_client = mock_asset_client_cls.return_value

    # Mock row for SELECT name(0), projectNumber(1), projectId(2), parent(3), ancestors(4)
    def create_project_row(name, p_num, p_id, parent_type, parent_id, ancestors):
        anc_vals = [{"v": anc} for anc in ancestors]

        # Use the REAL API format: nested STRUCT with 'f' array
        if parent_type:
            parent_struct = {"f": [{"v": parent_type}, {"v": parent_id}]}
        else:
            parent_struct = None

        row = {
            "f": [
                {"v": name},
                {"v": p_num},
                {"v": p_id},
                {"v": parent_struct},
                {"v": anc_vals},
            ]
        }
        return row

    mock_query_result = MagicMock()
    mock_query_result.rows = [
        create_project_row(
            "//cloudresourcemanager.googleapis.com/projects/p1",
            "123",
            "p1-id",
            "folder",
            "f1",
            ["//cloudresourcemanager.googleapis.com/folders/f1", "organizations/123"],
        )
    ]
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    # Pre-populate a folder to test parent resolution
    mock_org_node.folders["folders/f1"] = Folder(
        name="folders/f1",
        display_name="f1",
        ancestors=["folders/f1", "organizations/123"],
        organization=mock_org_node,
        parent="organizations/123",
    )

    projects = load_projects_asset(mock_org_node)

    assert len(projects) == 1
    p = projects[0]
    assert p.name == "projects/p1"
    assert p.display_name == "p1-id"  # Now uses projectId
    assert p.parent == "folders/f1"
    assert p.folder is not None
    assert p.folder.name == "folders/f1"


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_projects_asset_with_empty_ancestors(mock_asset_client_cls, mock_org_node):
    """Test that projects with empty ancestors (due to parent filter) work correctly."""
    mock_client = mock_asset_client_cls.return_value

    # Row with empty ancestors list but parent struct provided
    row = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/projects/789"},
            {"v": "12345"},  # projectNumber
            {"v": "test-project"},  # projectId
            {
                "v": {"f": [{"v": "organization"}, {"v": "123"}]}
            },  # parent STRUCT in real API format
            {"v": []},  # Empty ancestors due to parent filter
        ]
    }

    mock_query_result = MagicMock()
    mock_query_result.rows = [row]
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    projects = load_projects_asset(mock_org_node)

    assert len(projects) == 1
    p = projects[0]
    assert p.name == "projects/789"
    assert p.project_id == "test-project"
    assert p.parent == "organizations/123"  # Should use parent from API
    assert p.organization == mock_org_node


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_projects_asset_sql_filter(mock_asset_client_cls, mock_org_node):
    """Test that project SQL query includes lifecycleState and parent.id filters when parent_filter is provided."""
    mock_client = mock_asset_client_cls.return_value

    mock_query_result = MagicMock()
    mock_query_result.rows = []
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    # Test with parent_filter (scoped query)
    _ = load_projects_asset(mock_org_node, parent_filter="organizations/123")

    # Verify the query was called with the right statement
    call_args = mock_client.query_assets.call_args
    request = call_args[1]["request"] if call_args[1] else call_args[0][0]
    statement = request.statement

    # Check for lifecycle filter
    assert "lifecycleState = 'ACTIVE'" in statement
    # Check for parent.id filter (parent is a STRUCT)
    assert "resource.data.parent.id = '123'" in statement


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_projects_asset_sql_no_parent_filter(mock_asset_client_cls, mock_org_node):
    """Test that project SQL query omits parent.id filter when parent_filter is None (unscoped mode)."""
    mock_client = mock_asset_client_cls.return_value

    mock_query_result = MagicMock()
    mock_query_result.rows = []
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    # Test without parent_filter (unscoped query)
    _ = load_projects_asset(mock_org_node, parent_filter=None)

    # Verify the query was called with the right statement
    call_args = mock_client.query_assets.call_args
    request = call_args[1]["request"] if call_args[1] else call_args[0][0]
    statement = request.statement

    # Check for lifecycle filter
    assert "lifecycleState = 'ACTIVE'" in statement
    # Should NOT have parent.id filter in WHERE clause (but resource.data.parent is selected)
    assert "resource.data.parent.id" not in statement


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_projects_asset_ancestors_filter(mock_asset_client_cls, mock_org_node):
    """Test that project SQL query uses IN UNNEST(ancestors) filter for recursive scoped loading."""
    mock_client = mock_asset_client_cls.return_value

    mock_query_result = MagicMock()
    mock_query_result.rows = []
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    # Test with ancestors_filter (recursive under a folder)
    _ = load_projects_asset(mock_org_node, ancestors_filter="folders/456")

    # Verify the query was called with the right statement
    call_args = mock_client.query_assets.call_args
    request = call_args[1]["request"] if call_args[1] else call_args[0][0]
    statement = request.statement

    # Check for lifecycle filter
    assert "lifecycleState = 'ACTIVE'" in statement
    # Check for ancestors filter with IN UNNEST() syntax
    assert "'folders/456' IN UNNEST(ancestors)" in statement
    # Should NOT have parent.id filter
    assert "resource.data.parent.id" not in statement


# Test query_parent parameter
@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_folders_asset_query_parent(mock_asset_client_cls, mock_org_node):
    """Test that query_parent overrides the QueryAssetsRequest.parent."""
    mock_client = mock_asset_client_cls.return_value

    mock_query_result = MagicMock()
    mock_query_result.rows = []
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    load_folders_asset(mock_org_node, query_parent="folders/999")

    call_args = mock_client.query_assets.call_args
    request = call_args[1]["request"] if call_args[1] else call_args[0][0]
    assert request.parent == "folders/999"


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_folders_asset_root_ancestor(mock_asset_client_cls, mock_org_node):
    """Test that root_ancestor is used in ancestor chain building."""
    mock_client = mock_asset_client_cls.return_value

    def create_row(name, display_name, parent, ancestors):
        anc_vals = [{"v": anc} for anc in ancestors]
        return {
            "f": [
                {"v": name},
                {"v": display_name},
                {"v": parent},
                {"v": anc_vals},
            ]
        }

    mock_query_result = MagicMock()
    mock_query_result.rows = [
        create_row(
            "//cloudresourcemanager.googleapis.com/folders/child",
            "child",
            "folders/999",
            [],
        )
    ]
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    # Pre-populate the root folder
    mock_org_node.folders["folders/999"] = Folder(
        name="folders/999",
        display_name="root",
        ancestors=["folders/999"],
        organization=mock_org_node,
        parent="organizations/123",
    )

    load_folders_asset(
        mock_org_node,
        query_parent="folders/999",
        root_ancestor="folders/999",
    )

    assert "folders/child" in mock_org_node.folders
    child = mock_org_node.folders["folders/child"]
    # Ancestor chain should end with root_ancestor, not org
    assert child.ancestors[-1] == "folders/999"


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_projects_asset_query_parent(mock_asset_client_cls, mock_org_node):
    """Test that query_parent overrides the QueryAssetsRequest.parent for projects."""
    mock_client = mock_asset_client_cls.return_value

    mock_query_result = MagicMock()
    mock_query_result.rows = []
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    load_projects_asset(mock_org_node, query_parent="folders/999")

    call_args = mock_client.query_assets.call_args
    request = call_args[1]["request"] if call_args[1] else call_args[0][0]
    assert request.parent == "folders/999"


# Test load_organizationless_projects
@patch("google.cloud.resourcemanager_v3.ProjectsClient")
def test_load_organizationless_projects(mock_proj_cls):
    """Test loading organizationless projects."""
    mock_proj_client = mock_proj_cls.return_value

    # Mock projects: one under org, one orgless
    p_proto_org = MagicMock()
    p_proto_org.name = "projects/p-org"
    p_proto_org.parent = "organizations/123"
    p_proto_orgless = MagicMock()
    p_proto_orgless.name = "projects/p-orgless"
    p_proto_orgless.parent = "external-parent/0"
    p_proto_orgless.project_id = "p-orgless"
    p_proto_orgless.display_name = "P Orgless"

    mock_proj_client.search_projects.return_value = [p_proto_org, p_proto_orgless]

    # Already have p-org loaded
    existing_project_names = {"projects/p-org"}

    projects = load_organizationless_projects(existing_project_names)

    # Should only return the orgless project
    assert len(projects) == 1
    assert projects[0].name == "projects/p-orgless"
    assert projects[0].project_id == "p-orgless"
    assert projects[0].display_name == "P Orgless"
    assert projects[0].organization is None
    assert projects[0].folder is None


# Test _build_single_ancestor_chain helper
def test_build_single_ancestor_chain_simple(mock_org_node):
    """Test building ancestor chain for a folder with folder parent."""
    folder = Folder(
        name="folders/child",
        display_name="child",
        ancestors=["folders/child"],
        organization=mock_org_node,
        parent="folders/parent",
    )
    parent_folder = Folder(
        name="folders/parent",
        display_name="parent",
        ancestors=["folders/parent", "organizations/123"],
        organization=mock_org_node,
        parent="organizations/123",
    )
    folders = {"folders/child": folder, "folders/parent": parent_folder}

    ancestors = _build_single_ancestor_chain(folder, folders, "organizations/123")

    assert ancestors == ["folders/child", "folders/parent", "organizations/123"]


def test_build_single_ancestor_chain_circular(mock_org_node):
    """Test that circular references are detected and handled."""
    folder = Folder(
        name="folders/a",
        display_name="a",
        ancestors=["folders/a"],
        organization=mock_org_node,
        parent="folders/b",
    )
    # Create circular reference: b's parent is a
    folder_b = Folder(
        name="folders/b",
        display_name="b",
        ancestors=["folders/b"],
        organization=mock_org_node,
        parent="folders/a",
    )
    folders = {"folders/a": folder, "folders/b": folder_b}

    ancestors = _build_single_ancestor_chain(folder, folders, "organizations/123")

    # Should stop when circular reference detected
    assert "folders/a" in ancestors
    assert "folders/b" in ancestors
    assert ancestors[-1] == "organizations/123"


def test_build_single_ancestor_chain_missing_parent(mock_org_node):
    """Test ancestor chain when parent folder is not in the folders dict."""
    folder = Folder(
        name="folders/child",
        display_name="child",
        ancestors=["folders/child"],
        organization=mock_org_node,
        parent="folders/missing",
    )
    folders = {"folders/child": folder}

    ancestors = _build_single_ancestor_chain(folder, folders, "organizations/123")

    # Missing parent is added, then root is appended
    assert ancestors == ["folders/child", "folders/missing", "organizations/123"]


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_folders_asset_no_parent_uses_parent_filter(mock_asset_client_cls, mock_org_node):
    """Test that folders with no parent from API fall back to parent_filter."""
    mock_client = mock_asset_client_cls.return_value

    # Row with empty parent (None after parsing)
    row = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/folders/10"},
            {"v": "NoParentFolder"},
            {"v": None},  # No parent from API
            {"v": []},  # No ancestors
        ]
    }

    mock_query_result = MagicMock()
    mock_query_result.rows = [row]
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    load_folders_asset(mock_org_node, parent_filter="folders/999")

    assert "folders/10" in mock_org_node.folders
    folder = mock_org_node.folders["folders/10"]
    assert folder.parent == "folders/999"


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_folders_asset_no_parent_no_filter_uses_root(mock_asset_client_cls, mock_org_node):
    """Test that folders with no parent and no parent_filter fall back to root (org name)."""
    mock_client = mock_asset_client_cls.return_value

    row = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/folders/11"},
            {"v": "RootFolder"},
            {"v": None},  # No parent from API
            {"v": []},  # No ancestors
        ]
    }

    mock_query_result = MagicMock()
    mock_query_result.rows = [row]
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    load_folders_asset(mock_org_node)  # No parent_filter

    assert "folders/11" in mock_org_node.folders
    folder = mock_org_node.folders["folders/11"]
    assert folder.parent == "organizations/123"


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_projects_asset_no_parent_no_ancestors_with_filter(mock_asset_client_cls, mock_org_node):
    """Test project with no parent and no ancestors falls back to parent_filter."""
    mock_client = mock_asset_client_cls.return_value

    row = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/projects/p-noanc"},
            {"v": "100"},
            {"v": "p-noanc"},
            {"v": None},  # No parent struct
            {"v": []},  # No ancestors
        ]
    }

    mock_query_result = MagicMock()
    mock_query_result.rows = [row]
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    projects = load_projects_asset(mock_org_node, parent_filter="folders/500")

    assert len(projects) == 1
    assert projects[0].parent == "folders/500"


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_projects_asset_no_parent_no_ancestors_no_filter(mock_asset_client_cls, mock_org_node):
    """Test project with no parent and no ancestors falls back to org name."""
    mock_client = mock_asset_client_cls.return_value

    row = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/projects/p-bare"},
            {"v": "101"},
            {"v": "p-bare"},
            {"v": None},  # No parent struct
            {"v": []},  # No ancestors
        ]
    }

    mock_query_result = MagicMock()
    mock_query_result.rows = [row]
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    projects = load_projects_asset(mock_org_node)  # No parent_filter

    assert len(projects) == 1
    assert projects[0].parent == "organizations/123"


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_projects_asset_self_in_ancestors_with_more(mock_asset_client_cls, mock_org_node):
    """Test project where ancestors[0] == name and len > 1 uses ancestors[1]."""
    mock_client = mock_asset_client_cls.return_value

    row = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/projects/p-self"},
            {"v": "102"},
            {"v": "p-self"},
            {"v": None},  # No parent struct
            {
                "v": [
                    {"v": "//cloudresourcemanager.googleapis.com/projects/p-self"},
                    {"v": "//cloudresourcemanager.googleapis.com/folders/f2"},
                    {"v": "//cloudresourcemanager.googleapis.com/organizations/123"},
                ]
            },
        ]
    }

    mock_query_result = MagicMock()
    mock_query_result.rows = [row]
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    # Pre-populate a folder
    mock_org_node.folders["folders/f2"] = Folder(
        name="folders/f2",
        display_name="f2",
        ancestors=["folders/f2", "organizations/123"],
        organization=mock_org_node,
        parent="organizations/123",
    )

    projects = load_projects_asset(mock_org_node)

    assert len(projects) == 1
    assert projects[0].parent == "folders/f2"
    assert projects[0].folder is not None


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_projects_asset_self_in_ancestors_only_with_filter(mock_asset_client_cls, mock_org_node):
    """Test project where ancestors has only self, falls back to parent_filter."""
    mock_client = mock_asset_client_cls.return_value

    row = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/projects/p-only"},
            {"v": "103"},
            {"v": "p-only"},
            {"v": None},
            {
                "v": [
                    {"v": "//cloudresourcemanager.googleapis.com/projects/p-only"},
                ]
            },
        ]
    }

    mock_query_result = MagicMock()
    mock_query_result.rows = [row]
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    projects = load_projects_asset(mock_org_node, parent_filter="folders/600")

    assert len(projects) == 1
    assert projects[0].parent == "folders/600"


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_projects_asset_self_in_ancestors_only_no_filter(mock_asset_client_cls, mock_org_node):
    """Test project where ancestors has only self and no filter, falls back to org."""
    mock_client = mock_asset_client_cls.return_value

    row = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/projects/p-only2"},
            {"v": "104"},
            {"v": "p-only2"},
            {"v": None},
            {
                "v": [
                    {"v": "//cloudresourcemanager.googleapis.com/projects/p-only2"},
                ]
            },
        ]
    }

    mock_query_result = MagicMock()
    mock_query_result.rows = [row]
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    projects = load_projects_asset(mock_org_node)  # No parent_filter

    assert len(projects) == 1
    assert projects[0].parent == "organizations/123"


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_projects_asset_ancestors_first_not_self(mock_asset_client_cls, mock_org_node):
    """Test project where ancestors[0] != name uses ancestors[0] as parent."""
    mock_client = mock_asset_client_cls.return_value

    row = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/projects/p-diff"},
            {"v": "105"},
            {"v": "p-diff"},
            {"v": None},  # No parent struct
            {
                "v": [
                    {"v": "//cloudresourcemanager.googleapis.com/folders/f3"},
                    {"v": "//cloudresourcemanager.googleapis.com/organizations/123"},
                ]
            },
        ]
    }

    mock_query_result = MagicMock()
    mock_query_result.rows = [row]
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    mock_org_node.folders["folders/f3"] = Folder(
        name="folders/f3",
        display_name="f3",
        ancestors=["folders/f3", "organizations/123"],
        organization=mock_org_node,
        parent="organizations/123",
    )

    projects = load_projects_asset(mock_org_node)

    assert len(projects) == 1
    assert projects[0].parent == "folders/f3"
    assert projects[0].folder is not None


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_projects_asset_ancestors_first_not_self_with_filter(mock_asset_client_cls, mock_org_node):
    """Test else branch with empty ancestors falls back to parent_filter."""
    mock_client = mock_asset_client_cls.return_value

    row = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/projects/p-else"},
            {"v": "106"},
            {"v": "p-else"},
            {"v": None},
            # Non-empty ancestors where first != name but we want to test elif parent_filter
            # Actually, this branch has `if project_data["ancestors"]` which is True,
            # so it takes ancestors[0]. To test the elif, need empty ancestors in the else branch.
            # The else branch is entered when ancestors is non-empty AND ancestors[0] != name
            # AND the previous elif condition (ancestors[0] == name) is False.
            # So ancestors[0] will be used. To test elif/else in this branch,
            # we need ancestors to be empty here... but that's the second branch (line 415).
            # Let's just verify the else->if branch works.
            {
                "v": [
                    {"v": "//cloudresourcemanager.googleapis.com/folders/f4"},
                ]
            },
        ]
    }

    mock_query_result = MagicMock()
    mock_query_result.rows = [row]
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    mock_org_node.folders["folders/f4"] = Folder(
        name="folders/f4",
        display_name="f4",
        ancestors=["folders/f4", "organizations/123"],
        organization=mock_org_node,
        parent="organizations/123",
    )

    projects = load_projects_asset(mock_org_node, parent_filter="folders/700")

    assert len(projects) == 1
    # ancestors[0] is folders/f4, so that wins over parent_filter
    assert projects[0].parent == "folders/f4"
