import pytest
from unittest.mock import patch, MagicMock
from google.api_core import exceptions
from gcpath.core import Folder, OrganizationNode, Hierarchy, Project, ResourceNotFoundError
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
    mock_proj.parent = "" # Or potentially None or arbitrary string
    p_client.get_project.return_value = mock_proj
    
    path = Hierarchy.resolve_ancestry("projects/standalone")
    assert path == "//_/Standalone"
