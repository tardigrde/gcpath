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


@patch("gcpath.loaders.resourcemanager_v3")
@patch("gcpath.core.resourcemanager_v3")
def test_hierarchy_load_rm(mock_core_rm, mock_loaders_rm):
    # Use the same mock for both core and loaders
    mock_rm = mock_core_rm
    mock_loaders_rm.FoldersClient = mock_rm.FoldersClient

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


@patch("gcpath.loaders.resourcemanager_v3")
@patch("gcpath.loaders.asset_v1")
@patch("gcpath.core.resourcemanager_v3")
def test_hierarchy_load_asset_api(mock_core_rm, mock_loaders_asset, mock_loaders_rm):
    # Use the same mocks for both core and loaders
    mock_asset = mock_loaders_asset
    mock_rm = mock_core_rm
    mock_loaders_rm.ProjectsClient = mock_rm.ProjectsClient

    # Mock Org
    org_client = mock_rm.OrganizationsClient.return_value
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="org"
    )
    org_client.search_organizations.return_value = [org_proto]

    # Mock Asset API for folders
    asset_client = mock_asset.AssetServiceClient.return_value
    # Simplified row mock that dict(row) can handle
    # Format: name, displayName, parent, ancestors
    row_data = {
        "f": [
            {"v": "//cloudresourcemanager.googleapis.com/folders/1"},
            {"v": "f1"},
            {"v": "organizations/123"},  # parent
            {"v": [{"v": "folders/1"}, {"v": "organizations/123"}]},  # ancestors
        ]
    }

    # Actually mocking it properly is hard because of the row structure.
    # Let's use a simpler approach for the mock to avoid dict(row) failure
    mock_resp = MagicMock()
    mock_resp.query_result.rows = [row_data]
    asset_client.query_assets.return_value = mock_resp

    # Mock search_projects to return empty for organizationless projects
    mock_rm.ProjectsClient.return_value.search_projects.return_value = []

    # Load
    h = Hierarchy.load(via_resource_manager=False)
    assert len(h.organizations) == 1
    assert "folders/1" in h.organizations[0].folders


@patch("gcpath.loaders.resourcemanager_v3")
@patch("gcpath.loaders.asset_v1")
@patch("gcpath.core.resourcemanager_v3")
def test_load_from_folder_scope_with_org_access(
    mock_core_rm, mock_loaders_asset, mock_loaders_rm
):
    """Folder-scoped loading when org is accessible creates real org node."""
    mock_rm = mock_core_rm
    mock_loaders_rm.FoldersClient = mock_rm.FoldersClient
    mock_loaders_rm.ProjectsClient = mock_rm.ProjectsClient

    # Let the real Organization class through for construction
    mock_rm.Organization = resourcemanager_v3.Organization

    # search_organizations returns empty (triggers fallback)
    org_client = mock_rm.OrganizationsClient.return_value
    org_client.search_organizations.return_value = []

    # get_folder for entrypoint
    folders_client = mock_rm.FoldersClient.return_value
    mock_folder = MagicMock()
    mock_folder.name = "folders/100"
    mock_folder.display_name = "Team Folder"
    mock_folder.parent = "organizations/123"
    folders_client.get_folder.return_value = mock_folder

    # get_organization succeeds (user has access)
    mock_org = MagicMock()
    mock_org.name = "organizations/123"
    mock_org.display_name = "Example Org"
    org_client.get_organization.return_value = mock_org

    # Asset API returns empty (no children)
    asset_client = mock_loaders_asset.AssetServiceClient.return_value
    mock_resp = MagicMock()
    mock_resp.query_result.rows = []
    asset_client.query_assets.return_value = mock_resp

    # search_projects returns empty for organizationless
    mock_rm.ProjectsClient.return_value.search_projects.return_value = []

    h = Hierarchy.load(
        via_resource_manager=False,
        scope_resource="folders/100",
    )

    assert len(h.organizations) == 1
    assert h.organizations[0].organization.name == "organizations/123"
    assert h.organizations[0].organization.display_name == "Example Org"
    assert "folders/100" in h.organizations[0].folders


@patch("gcpath.loaders.resourcemanager_v3")
@patch("gcpath.loaders.asset_v1")
@patch("gcpath.core.resourcemanager_v3")
def test_load_from_folder_scope_no_org_access(
    mock_core_rm, mock_loaders_asset, mock_loaders_rm
):
    """Folder-scoped loading when org is NOT accessible uses synthetic org."""
    from gcpath.core import SYNTHETIC_ORG_NAME

    mock_rm = mock_core_rm
    mock_loaders_rm.FoldersClient = mock_rm.FoldersClient
    mock_loaders_rm.ProjectsClient = mock_rm.ProjectsClient

    # Let the real Organization class through for construction
    mock_rm.Organization = resourcemanager_v3.Organization

    # search_organizations returns empty (triggers fallback)
    org_client = mock_rm.OrganizationsClient.return_value
    org_client.search_organizations.return_value = []

    # get_folder for entrypoint
    folders_client = mock_rm.FoldersClient.return_value
    mock_folder = MagicMock()
    mock_folder.name = "folders/100"
    mock_folder.display_name = "Team Folder"
    mock_folder.parent = "organizations/123"
    folders_client.get_folder.return_value = mock_folder

    # get_organization raises PermissionDenied
    org_client.get_organization.side_effect = exceptions.PermissionDenied("denied")

    # Asset API returns empty
    asset_client = mock_loaders_asset.AssetServiceClient.return_value
    mock_resp = MagicMock()
    mock_resp.query_result.rows = []
    asset_client.query_assets.return_value = mock_resp

    # search_projects returns empty for organizationless
    mock_rm.ProjectsClient.return_value.search_projects.return_value = []

    h = Hierarchy.load(
        via_resource_manager=False,
        scope_resource="folders/100",
    )

    assert len(h.organizations) == 1
    assert h.organizations[0].organization.name == SYNTHETIC_ORG_NAME
    assert h.organizations[0].organization.display_name == "Team Folder"
    assert "folders/100" in h.organizations[0].folders
    # Entrypoint folder ancestors should be just itself
    assert h.organizations[0].folders["folders/100"].ancestors == ["folders/100"]


@patch("gcpath.core.resourcemanager_v3")
def test_folder_scope_fallback_not_triggered_without_folder(mock_rm):
    """Fallback should NOT trigger when scope_resource is not a folder."""
    org_client = mock_rm.OrganizationsClient.return_value
    org_client.search_organizations.return_value = []

    project_client = mock_rm.ProjectsClient.return_value
    project_client.search_projects.return_value = []

    # No scope_resource => no fallback, just empty hierarchy
    h = Hierarchy.load(via_resource_manager=True)
    assert len(h.organizations) == 0

    # Organization scope => no fallback
    h = Hierarchy.load(via_resource_manager=True, scope_resource="organizations/123")
    assert len(h.organizations) == 0


def test_find_orgless_project_found():
    """Test _find_orgless_project helper finds organizationless projects."""
    orgless_project = Project(
        name="projects/orgless",
        project_id="orgless",
        display_name="Orgless",
        parent="external/0",
        organization=None,
        folder=None,
    )
    h = Hierarchy([], [orgless_project])

    result = h._find_orgless_project("//_/Orgless")
    assert result == "projects/orgless"


def test_find_orgless_project_not_found():
    """Test _find_orgless_project helper raises error when not found."""
    h = Hierarchy([], [])

    with pytest.raises(
        ResourceNotFoundError, match="not found in organizationless scope"
    ):
        h._find_orgless_project("//_/NonExistent")


def test_find_orgless_project_skips_org_projects():
    """Test _find_orgless_project helper ignores projects with an organization."""
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )
    org_node = OrganizationNode(organization=org_proto)

    org_project = Project(
        name="projects/org-project",
        project_id="org-project",
        display_name="OrgProject",
        parent="organizations/123",
        organization=org_node,
        folder=None,
    )
    h = Hierarchy([org_node], [org_project])

    # Should not find org project via _find_orgless_project
    with pytest.raises(ResourceNotFoundError):
        h._find_orgless_project("//example.com/OrgProject")


# --- resolve_ancestry_chain tests ---


@patch("gcpath.core.resourcemanager_v3")
def test_resolve_ancestry_chain_project(mock_rm):
    """Test ancestry chain for a project under folder under org."""
    p_client = mock_rm.ProjectsClient.return_value
    f_client = mock_rm.FoldersClient.return_value
    o_client = mock_rm.OrganizationsClient.return_value

    mock_proj = MagicMock()
    mock_proj.display_name = "Project 1"
    mock_proj.project_id = "p1"
    mock_proj.parent = "folders/f1"
    p_client.get_project.return_value = mock_proj

    mock_folder = MagicMock()
    mock_folder.display_name = "Folder 1"
    mock_folder.parent = "organizations/123"
    f_client.get_folder.return_value = mock_folder

    mock_org = MagicMock()
    mock_org.display_name = "Example Org"
    o_client.get_organization.return_value = mock_org

    chain = Hierarchy.resolve_ancestry_chain("projects/p1")

    assert len(chain) == 3
    assert chain[0] == ("organizations/123", "Example Org", "organization")
    assert chain[1] == ("folders/f1", "Folder 1", "folder")
    assert chain[2] == ("projects/p1", "Project 1", "project")


@patch("gcpath.core.resourcemanager_v3")
def test_resolve_ancestry_chain_org(mock_rm):
    """Test ancestry chain for an organization."""
    o_client = mock_rm.OrganizationsClient.return_value
    mock_org = MagicMock()
    mock_org.display_name = "Example Org"
    o_client.get_organization.return_value = mock_org

    chain = Hierarchy.resolve_ancestry_chain("organizations/123")

    assert len(chain) == 1
    assert chain[0] == ("organizations/123", "Example Org", "organization")


@patch("gcpath.core.resourcemanager_v3")
def test_resolve_ancestry_chain_not_found(mock_rm):
    """Test ancestry chain raises error for not found resources."""
    p_client = mock_rm.ProjectsClient.return_value
    p_client.get_project.side_effect = exceptions.NotFound("not found")

    with pytest.raises(ResourceNotFoundError, match="Resource not found"):
        Hierarchy.resolve_ancestry_chain("projects/nonexistent")


@patch("gcpath.core.resourcemanager_v3")
def test_resolve_ancestry_chain_permission_denied(mock_rm):
    """Test ancestry chain uses graceful fallback for permission denied."""
    p_client = mock_rm.ProjectsClient.return_value
    p_client.get_project.side_effect = exceptions.PermissionDenied("denied")

    chain = Hierarchy.resolve_ancestry_chain("projects/restricted")
    assert len(chain) == 1
    assert chain[0] == ("projects/restricted", "projects/restricted", "project")


def _build_summary_hierarchy():
    org_proto = resourcemanager_v3.Organization(
        name="organizations/77", display_name="acme.example"
    )
    org_node = OrganizationNode(organization=org_proto)

    f1 = Folder(
        name="folders/100",
        display_name="eng",
        ancestors=["folders/100", "organizations/77"],
        organization=org_node,
        parent="organizations/77",
        labels={"team": "eng", "tier": "prod"},
    )
    f2 = Folder(
        name="folders/200",
        display_name="ops",
        ancestors=["folders/200", "organizations/77"],
        organization=org_node,
        parent="organizations/77",
        labels={"team": "ops"},
    )
    f3 = Folder(
        name="folders/300",
        display_name="backend",
        ancestors=["folders/300", "folders/100", "organizations/77"],
        organization=org_node,
        parent="folders/100",
        labels={"team": "eng"},
    )
    org_node.folders["folders/100"] = f1
    org_node.folders["folders/200"] = f2
    org_node.folders["folders/300"] = f3

    p1 = Project(
        name="projects/p1",
        project_id="p1",
        display_name="p1",
        parent="folders/300",
        organization=org_node,
        folder=f3,
        labels={"team": "eng"},
        tags={"env": "prod"},
    )

    return Hierarchy([org_node], [p1])


def test_summary_basic_counts():
    h = _build_summary_hierarchy()
    summary = h.summary()
    assert summary["org_count"] == 1
    assert summary["folder_count"] == 3
    assert summary["project_count"] == 1


def test_summary_max_depth():
    h = _build_summary_hierarchy()
    summary = h.summary()
    # Projects must be considered: p1 lives under folders/300 (folder depth 2),
    # so its depth is 3 and dominates the folder-only max of 2.
    assert summary["max_depth"] == 3


def test_summary_top_label_keys_ordering():
    h = _build_summary_hierarchy()
    summary = h.summary(top_n=5)
    keys = [r["key"] for r in summary["top_label_keys"]]
    assert keys[0] == "team"
    counts = {r["key"]: r["count"] for r in summary["top_label_keys"]}
    assert counts["team"] == 4


def test_summary_excludes_synthetic_org():
    from gcpath.core import SYNTHETIC_ORG_NAME

    synth_proto = resourcemanager_v3.Organization(
        name=SYNTHETIC_ORG_NAME, display_name="root_folder"
    )
    real_proto = resourcemanager_v3.Organization(
        name="organizations/77", display_name="acme.example"
    )
    synth = OrganizationNode(organization=synth_proto)
    real = OrganizationNode(organization=real_proto)
    h = Hierarchy([synth, real], [])
    summary = h.summary()
    assert summary["org_count"] == 1
    assert summary["orgs"][0]["display_name"] == "acme.example"


def test_summary_excludes_synthetic_org_descendants_from_global_metrics():
    """folder_count, project_count, max_depth, top keys, and deepest_paths
    must ignore synthetic-org descendants — otherwise the snapshot is
    skewed by data that isn't really "in" any user-visible org.
    """
    from gcpath.core import SYNTHETIC_ORG_NAME

    synth_proto = resourcemanager_v3.Organization(
        name=SYNTHETIC_ORG_NAME, display_name="root_folder"
    )
    real_proto = resourcemanager_v3.Organization(
        name="organizations/77", display_name="acme"
    )
    synth = OrganizationNode(organization=synth_proto)
    real = OrganizationNode(organization=real_proto)

    real_folder = Folder(
        name="folders/100",
        display_name="real",
        ancestors=["folders/100", "organizations/77"],
        organization=real,
        parent="organizations/77",
        labels={"team": "real"},
    )
    real.folders["folders/100"] = real_folder

    synth_folder = Folder(
        name="folders/999",
        display_name="under_synth",
        ancestors=["folders/999"],
        organization=synth,
        parent=SYNTHETIC_ORG_NAME,
        labels={"team": "synth"},
    )
    synth.folders["folders/999"] = synth_folder

    real_project = Project(
        name="projects/real-1",
        project_id="real-1",
        display_name="real-1",
        parent="folders/100",
        organization=real,
        folder=real_folder,
    )
    synth_project = Project(
        name="projects/synth-1",
        project_id="synth-1",
        display_name="synth-1",
        parent="folders/999",
        organization=synth,
        folder=synth_folder,
    )

    h = Hierarchy([synth, real], [real_project, synth_project])
    summary = h.summary()
    assert summary["org_count"] == 1
    assert summary["folder_count"] == 1
    assert summary["project_count"] == 1
    label_keys = [r["key"] for r in summary["top_label_keys"]]
    # Both folders set "team" but only the real one should be counted.
    assert label_keys.count("team") <= 1
    # No synth-1 path should leak into deepest_paths.
    assert all("synth-1" not in p for p in summary["deepest_paths"])


def test_summary_deepest_paths_sorted():
    h = _build_summary_hierarchy()
    summary = h.summary(deepest_n=3)
    assert summary["deepest_paths"]
    assert summary["deepest_paths"][0].count("/") >= summary["deepest_paths"][-1].count(
        "/"
    )


@patch("gcpath.core.resourcemanager_v3")
def test_hierarchy_load_propagates_service_unavailable(mock_rm):
    """Transient org-search failures raise instead of yielding an empty hierarchy."""
    org_client = mock_rm.OrganizationsClient.return_value
    org_client.search_organizations.side_effect = exceptions.ServiceUnavailable(
        "failed to connect to all addresses"
    )

    with pytest.raises(exceptions.ServiceUnavailable):
        Hierarchy.load()


def test_has_resource():
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )
    org_node = OrganizationNode(organization=org_proto)
    folder = Folder(
        name="folders/1",
        display_name="f1",
        ancestors=["folders/1", "organizations/123"],
        organization=org_node,
        parent="organizations/123",
    )
    org_node.folders["folders/1"] = folder
    project = Project(
        name="projects/p1",
        project_id="p1",
        display_name="P1",
        parent="folders/1",
        organization=org_node,
        folder=folder,
    )
    h = Hierarchy([org_node], [project])

    assert h.has_resource("organizations/123")
    assert h.has_resource("folders/1")
    assert h.has_resource("projects/p1")
    assert not h.has_resource("folders/999")
