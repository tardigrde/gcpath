import pytest
from unittest.mock import patch, MagicMock
from google.api_core import exceptions
from gcpath.core import (
    Folder,
    OrganizationNode,
    Hierarchy,
    Project,
    ResourceNotFoundError,
)
from google.cloud import resourcemanager_v3


def test_folder_path_simple():
    # Setup
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )
    org_node = OrganizationNode(organization=org_proto)

    # Hierarchy: Org -> F1 -> F2
    f1 = Folder(
        name="folders/1",
        display_name="f1",
        ancestors=["folders/1", "organizations/123"],
        organization=org_node,
    )
    f2 = Folder(
        name="folders/2",
        display_name="f2",
        ancestors=["folders/2", "folders/1", "organizations/123"],
        organization=org_node,
    )

    org_node.folders["folders/1"] = f1
    org_node.folders["folders/2"] = f2

    # Check paths
    assert f1.path == "//example.com/f1"
    assert f2.path == "//example.com/f1/f2"


def test_folder_is_path_match():
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )
    org_node = OrganizationNode(organization=org_proto)

    # Hierarchy: Org -> F1 -> F2
    f1 = Folder(
        name="folders/1",
        display_name="f1",
        ancestors=["folders/1", "organizations/123"],
        organization=org_node,
    )
    f2 = Folder(
        name="folders/2",
        display_name="f2",
        ancestors=["folders/2", "folders/1", "organizations/123"],
        organization=org_node,
    )

    org_node.folders["folders/1"] = f1
    org_node.folders["folders/2"] = f2

    # Test Matches
    assert f1.is_path_match(["f1"]) is True
    assert f2.is_path_match(["f1", "f2"]) is True

    # Test Non-Matches
    assert f1.is_path_match(["f2"]) is False
    assert f2.is_path_match(["f1"]) is False  # path too short
    assert f2.is_path_match(["f1", "f3"]) is False  # mismatch name


def test_get_resource_name():
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )
    org_node = OrganizationNode(organization=org_proto)

    f1 = Folder(
        name="folders/1",
        display_name="f1",
        ancestors=["folders/1", "organizations/123"],
        organization=org_node,
    )
    org_node.folders["folders/1"] = f1

    assert org_node.get_resource_name("/") == "organizations/123"
    assert org_node.get_resource_name("/f1") == "folders/1"

    with pytest.raises(ValueError, match="No folder found"):
        org_node.get_resource_name("/f2")


def test_hierarchy_get_resource_name_full_path():
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )
    org_node = OrganizationNode(organization=org_proto)
    f1 = Folder(
        name="folders/1",
        display_name="f1",
        ancestors=["folders/1", "organizations/123"],
        organization=org_node,
    )
    org_node.folders["folders/1"] = f1

    h = Hierarchy([org_node], [])

    assert h.get_resource_name("//example.com/f1") == "folders/1"
    assert h.get_resource_name("//example.com") == "organizations/123"


def test_hierarchy_get_path_by_resource_name():
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )
    org_node = OrganizationNode(organization=org_proto)
    f1 = Folder(
        name="folders/1",
        display_name="f1",
        ancestors=["folders/1", "organizations/123"],
        organization=org_node,
    )
    org_node.folders["folders/1"] = f1

    p1 = Project(
        name="projects/p1",
        project_id="p1",
        display_name="Project 1",
        parent="folders/1",
        organization=org_node,
        folder=f1,
    )

    h = Hierarchy([org_node], [p1])

    assert h.get_path_by_resource_name("folders/1") == "//example.com/f1"
    assert h.get_path_by_resource_name("organizations/123") == "//example.com"
    assert h.get_path_by_resource_name("projects/p1") == "//example.com/f1/Project%201"


def test_organizationless_project_path():
    p1 = Project(
        name="projects/p1",
        project_id="p1",
        display_name="Project 1",
        parent="organizations/0",
        organization=None,
        folder=None,
    )
    assert p1.path == "//_/Project%201"

    h = Hierarchy([], [p1])
    assert h.get_resource_name("//_/Project%201") == "projects/p1"


@patch("gcpath.core.resourcemanager_v3")
def test_resolve_ancestry_project(mock_rm):
    # Setup Mocks
    # Access classes from the mocked module
    p_client = mock_rm.ProjectsClient.return_value
    f_client = mock_rm.FoldersClient.return_value
    o_client = mock_rm.OrganizationsClient.return_value

    # Project -> Folder -> Org
    # projects/p1 (Project 1) -> folders/f1 (Folder 1) -> organizations/123 (Example Org)

    # 1. Get Project
    mock_proj = MagicMock()
    mock_proj.display_name = "Project 1"
    mock_proj.parent = "folders/f1"
    p_client.get_project.return_value = mock_proj

    # 2. Get Folder
    mock_folder = MagicMock()
    mock_folder.display_name = "Folder 1"
    mock_folder.parent = "organizations/123"
    f_client.get_folder.return_value = mock_folder

    # 3. Get Org
    mock_org = MagicMock()
    mock_org.display_name = "Example Org"
    o_client.get_organization.return_value = mock_org

    # Execute
    path = Hierarchy.resolve_ancestry("projects/p1")

    # Verify
    assert path == "//Example%20Org/Folder%201/Project%201"

    p_client.get_project.assert_called_with(name="projects/p1")
    f_client.get_folder.assert_called_with(name="folders/f1")
    o_client.get_organization.assert_called_with(name="organizations/123")


@patch("gcpath.core.resourcemanager_v3")
def test_resolve_ancestry_organization(mock_rm):
    o_client = mock_rm.OrganizationsClient.return_value
    mock_org = MagicMock()
    mock_org.display_name = "Example Org"
    o_client.get_organization.return_value = mock_org

    path = Hierarchy.resolve_ancestry("organizations/123")
    assert path == "//Example%20Org"


@patch("gcpath.core.resourcemanager_v3")
def test_resolve_ancestry_not_found(mock_rm):
    p_client = mock_rm.ProjectsClient.return_value
    p_client.get_project.side_effect = exceptions.NotFound("Project not found")

    with pytest.raises(ResourceNotFoundError, match="Resource not found"):
        Hierarchy.resolve_ancestry("projects/nonexistent")


@patch("gcpath.core.resourcemanager_v3")
def test_resolve_ancestry_permission_denied(mock_rm):
    p_client = mock_rm.ProjectsClient.return_value
    p_client.get_project.side_effect = exceptions.PermissionDenied("Access denied")

    with pytest.raises(ResourceNotFoundError, match="Permission denied"):
        Hierarchy.resolve_ancestry("projects/restricted")


@patch("gcpath.core.resourcemanager_v3")
def test_resolve_ancestry_organizationless(mock_rm):
    p_client = mock_rm.ProjectsClient.return_value

    # Project with no parent (or parent not org/folder)
    mock_proj = MagicMock()
    mock_proj.display_name = "Standalone"
    mock_proj.parent = ""  # Or potentially None or arbitrary string
    p_client.get_project.return_value = mock_proj

    path = Hierarchy.resolve_ancestry("projects/standalone")
    assert path == "//_/Standalone"


@patch("gcpath.core.resourcemanager_v3")
def test_hierarchy_load_rm(mock_rm):
    # Mock Org
    org_client = mock_rm.OrganizationsClient.return_value
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="org"
    )
    org_client.search_organizations.return_value = [org_proto]

    # Mock Folder Client
    f_client = mock_rm.FoldersClient.return_value
    f_proto = resourcemanager_v3.Folder(name="folders/1", display_name="f1")
    f_client.list_folders.return_value = [f_proto]
    # To stop recursion
    f_client.list_folders.side_effect = [[f_proto], []]

    # Mock Project Client
    p_client = mock_rm.ProjectsClient.return_value
    p_proto = resourcemanager_v3.Project(
        name="projects/p1", project_id="p1", display_name="P1", parent="folders/1"
    )
    p_client.search_projects.return_value = [p_proto]

    h = Hierarchy.load(via_resource_manager=True)
    assert len(h.organizations) == 1
    assert "folders/1" in h.organizations[0].folders
    assert len(h.projects) == 1
    assert h.projects[0].folder is not None
    assert h.projects[0].folder.name == "folders/1"


@patch("gcpath.core.resourcemanager_v3")
def test_hierarchy_load_permission_denied(mock_rm):
    org_client = mock_rm.OrganizationsClient.return_value
    org_client.search_organizations.side_effect = exceptions.PermissionDenied("denied")

    h = Hierarchy.load()
    assert len(h.organizations) == 0


def test_path_parsing_errors():
    from gcpath.core import GCPathError

    with pytest.raises(GCPathError, match="Path must start with //"):
        Hierarchy._parse_path("invalid")
    with pytest.raises(GCPathError, match="Path must contain an organization name"):
        Hierarchy._parse_path("//")


def test_organization_node_paths():
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="org"
    )
    node = OrganizationNode(organization=org_proto)
    f1 = Folder(
        name="folders/1",
        display_name="f1",
        ancestors=["folders/1", "organizations/123"],
        organization=node,
    )
    node.folders["folders/1"] = f1
    assert node.paths() == ["//org/f1"]


def test_organization_node_get_resource_name_multiple_matches():
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="org"
    )
    node = OrganizationNode(organization=org_proto)
    # This is hard to trigger with current is_path_match but let's try if possible or just mock
    f1 = MagicMock(spec=Folder)
    f1.is_path_match.return_value = True
    f2 = MagicMock(spec=Folder)
    f2.is_path_match.return_value = True
    node.folders = {"f1": f1, "f2": f2}
    with pytest.raises(ResourceNotFoundError, match="Multiple folders found"):
        node.get_resource_name("/path")


def test_hierarchy_get_path_errors():
    h = Hierarchy([], [])
    with pytest.raises(
        ResourceNotFoundError, match="Organization 'organizations/123' not found"
    ):
        h.get_path_by_resource_name("organizations/123")
    with pytest.raises(ResourceNotFoundError, match="Folder 'folders/1' not found"):
        h.get_path_by_resource_name("folders/1")
    with pytest.raises(ResourceNotFoundError, match="Project 'projects/p1' not found"):
        h.get_path_by_resource_name("projects/p1")
    with pytest.raises(ResourceNotFoundError, match="Unsupported resource name"):
        h.get_path_by_resource_name("invalid/123")


@patch("gcpath.core.resourcemanager_v3")
@patch("gcpath.core.asset_v1")
def test_hierarchy_load_asset_api(mock_asset, mock_rm):
    # Mock Org
    org_client = mock_rm.OrganizationsClient.return_value
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="org"
    )
    org_client.search_organizations.return_value = [org_proto]

    # Mock Asset API for folders
    asset_client = mock_asset.AssetServiceClient.return_value
    mock_row = MagicMock()
    mock_row.__iter__.return_value = iter(
        [
            ("name", "//cloudresourcemanager.googleapis.com/folders/1"),
            (
                "f",
                [
                    {"v": "//cloudresourcemanager.googleapis.com/folders/1"},
                    {"v": "f1"},
                    {
                        "v": [
                            "//cloudresourcemanager.googleapis.com/folders/1",
                            "//cloudresourcemanager.googleapis.com/organizations/123",
                        ]
                    },
                ],
            ),
        ]
    )
    # Simplified row mock that dict(row) can handle
    row_data = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/folders/1"},
            {"v": "f1"},
            {"v": [{"v": "folders/1"}, {"v": "organizations/123"}]},
        ]
    }

    # Actually mocking it properly is hard because of the row structure.
    # Let's use a simpler approach for the mock to avoid dict(row) failure
    mock_resp = MagicMock()
    mock_resp.query_result.rows = [row_data]
    asset_client.query_assets.return_value = mock_resp

    # Load
    h = Hierarchy.load(via_resource_manager=False)
    assert len(h.organizations) == 1
    assert "folders/1" in h.organizations[0].folders
