import pytest
from unittest.mock import MagicMock, patch
from gcpath.core import Hierarchy, OrganizationNode, Folder, Project
from google.cloud import resourcemanager_v3


@pytest.fixture
def mock_org():
    return resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )


@pytest.fixture
def mock_org_node(mock_org):
    return OrganizationNode(organization=mock_org)


def test_clean_asset_name():
    from gcpath.core import _clean_asset_name

    assert (
        _clean_asset_name("//cloudresourcemanager.googleapis.com/folders/123")
        == "folders/123"
    )
    assert _clean_asset_name("folders/123") == "folders/123"


@patch("google.cloud.asset_v1.AssetServiceClient")
@patch("google.cloud.asset_v1.QueryAssetsRequest")
def test_load_folders_asset(mock_q_req, mock_asset_client_cls, mock_org_node):
    mock_client = mock_asset_client_cls.return_value
    mock_q_req.Statement.return_value = MagicMock()

    # Mocking the response structure: plain dicts/lists for unmarshaled Structs
    # { "f": [ {"v": name}, {"v": displayName}, {"v": parent}, {"v": [ {"v": a1}, {"v": a2} ] } ] }
    def create_row(name, display_name, parent, ancestors):
        anc_vals = [{"v": anc} for anc in ancestors]

        # Row is a dict representing the struct
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

    Hierarchy._load_folders_asset(mock_org_node)

    assert "folders/1" in mock_org_node.folders
    folder = mock_org_node.folders["folders/1"]
    assert folder.display_name == "f1"
    assert folder.parent == "organizations/123"
    # Verify prepending logic: [self, org]
    assert folder.ancestors == ["folders/1", "organizations/123"]


@patch("google.cloud.asset_v1.AssetServiceClient")
@patch("google.cloud.asset_v1.QueryAssetsRequest")
def test_load_projects_asset(mock_q_req, mock_asset_client_cls, mock_org_node):
    mock_client = mock_asset_client_cls.return_value
    mock_q_req.Statement.return_value = MagicMock()

    # Mock row for SELECT name(0), projectNumber(1), projectId(2), parent(3), ancestors(4)
    def create_project_row(name, p_num, p_id, parent_type, parent_id, ancestors):
        anc_vals = [{"v": anc} for anc in ancestors]

        # Use the REAL API format: nested STRUCT with 'f' array
        if parent_type:
            parent_struct = {
                "f": [
                    {"v": parent_type},
                    {"v": parent_id}
                ]
            }
        else:
            parent_struct = None

        row = {
            "f": [
                {"v": name},
                {"v": p_num},
                {"v": p_id},
                {"v": parent_struct},
                {"v": anc_vals}
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

    projects = Hierarchy._load_projects_asset(mock_org_node)

    assert len(projects) == 1
    p = projects[0]
    assert p.name == "projects/p1"
    assert p.display_name == "p1-id"  # Now uses projectId
    assert p.parent == "folders/f1"
    assert p.folder is not None
    assert p.folder.name == "folders/f1"


@patch("google.cloud.resourcemanager_v3.OrganizationsClient")
@patch("google.cloud.resourcemanager_v3.ProjectsClient")
@patch("gcpath.core.Hierarchy._load_folders_asset")
@patch("gcpath.core.Hierarchy._load_projects_asset")
def test_hierarchy_load_orgless_always(
    mock_load_projects_asset,
    mock_load_folders_asset,
    mock_proj_cls,
    mock_org_cls,
    mock_org,
):
    # Mock Orgs
    mock_org_client = mock_org_cls.return_value
    mock_org_client.search_organizations.return_value = [mock_org]

    # Mock Asset Projects (Project under Org)
    p_org = Project(
        name="projects/p-org",
        project_id="p-org",
        display_name="P Org",
        parent="organizations/123",
        organization=None,
        folder=None,
    )
    mock_load_projects_asset.return_value = [p_org]

    # Mock RM search_projects (Includes Orgless)
    mock_proj_client = mock_proj_cls.return_value
    p_proto_org = MagicMock()
    p_proto_org.name = "projects/p-org"
    p_proto_org.parent = "organizations/123"
    p_proto_orgless = MagicMock()
    p_proto_orgless.name = "projects/p-orgless"
    p_proto_orgless.parent = "external-parent/0"
    p_proto_orgless.project_id = "p-orgless"
    p_proto_orgless.display_name = "P Orgless"

    mock_proj_client.search_projects.return_value = [p_proto_org, p_proto_orgless]

    # Load via Asset API mode
    h = Hierarchy.load(via_resource_manager=False)

    assert len(h.organizations) == 1
    # Should have 2 projects: one from asset, one orgless from search_projects
    assert len(h.projects) == 2
    project_names = {p.name for p in h.projects}
    assert "projects/p-org" in project_names
    assert "projects/p-orgless" in project_names


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

    Hierarchy._load_folders_asset(mock_org_node)

    assert "folders/456" in mock_org_node.folders
    folder = mock_org_node.folders["folders/456"]
    assert folder.display_name == "TestFolder"
    assert folder.parent == "organizations/123"
    # With empty ancestors, should add org
    assert folder.ancestors == ["folders/456", "organizations/123"]


@patch("google.cloud.asset_v1.AssetServiceClient")
def test_load_projects_asset_with_empty_ancestors(
    mock_asset_client_cls, mock_org_node
):
    """Test that projects with empty ancestors (due to parent filter) work correctly."""
    mock_client = mock_asset_client_cls.return_value

    # Row with empty ancestors list but parent struct provided
    row = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/projects/789"},
            {"v": "12345"},  # projectNumber
            {"v": "test-project"},  # projectId
            {
                "v": {
                    "f": [
                        {"v": "organization"},
                        {"v": "123"}
                    ]
                }
            },  # parent STRUCT in real API format
            {"v": []},  # Empty ancestors due to parent filter
        ]
    }

    mock_query_result = MagicMock()
    mock_query_result.rows = [row]
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    projects = Hierarchy._load_projects_asset(mock_org_node)

    assert len(projects) == 1
    p = projects[0]
    assert p.name == "projects/789"
    assert p.project_id == "test-project"
    assert p.parent == "organizations/123"  # Should use parent from API
    assert p.organization == mock_org_node


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
    Hierarchy._load_folders_asset(mock_org_node, parent_filter="organizations/123")

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
    Hierarchy._load_folders_asset(mock_org_node, parent_filter=None)

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
def test_load_projects_asset_sql_filter(mock_asset_client_cls, mock_org_node):
    """Test that project SQL query includes lifecycleState and parent.id filters when parent_filter is provided."""
    mock_client = mock_asset_client_cls.return_value

    mock_query_result = MagicMock()
    mock_query_result.rows = []
    mock_response = MagicMock()
    mock_response.query_result = mock_query_result
    mock_client.query_assets.return_value = mock_response

    # Test with parent_filter (scoped query)
    _ = Hierarchy._load_projects_asset(mock_org_node, parent_filter="organizations/123")

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
    _ = Hierarchy._load_projects_asset(mock_org_node, parent_filter=None)

    # Verify the query was called with the right statement
    call_args = mock_client.query_assets.call_args
    request = call_args[1]["request"] if call_args[1] else call_args[0][0]
    statement = request.statement

    # Check for lifecycle filter
    assert "lifecycleState = 'ACTIVE'" in statement
    # Should NOT have parent.id filter in WHERE clause (but resource.data.parent is selected)
    assert "resource.data.parent.id" not in statement


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
    Hierarchy._load_folders_asset(mock_org_node, parent_filter="folders/456")

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
    Hierarchy._load_folders_asset(mock_org_node, ancestors_filter="folders/456")

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
    _ = Hierarchy._load_projects_asset(mock_org_node, ancestors_filter="folders/456")

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
