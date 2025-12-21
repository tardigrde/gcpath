
import pytest
from unittest.mock import MagicMock, patch
from gcpath.core import Hierarchy, OrganizationNode, Folder, Project
from google.cloud import resourcemanager_v3, asset_v1

@pytest.fixture
def mock_org():
    return resourcemanager_v3.Organization(name="organizations/123", display_name="example.com")

@pytest.fixture
def mock_org_node(mock_org):
    return OrganizationNode(organization=mock_org)

def test_clean_asset_name():
    from gcpath.core import _clean_asset_name
    assert _clean_asset_name("//cloudresourcemanager.googleapis.com/folders/123") == "folders/123"
    assert _clean_asset_name("folders/123") == "folders/123"

@patch("google.cloud.asset_v1.AssetServiceClient")
@patch("google.cloud.asset_v1.QueryAssetsRequest")
def test_load_folders_asset(mock_q_req, mock_asset_client_cls, mock_org_node):
    mock_client = mock_asset_client_cls.return_value
    mock_q_req.Statement.return_value = MagicMock()
    
    # Mocking the response structure: { f: [ {v: name}, {v: displayName}, {v: [ {v: a1}, {v: a2} ] } ] }
    def create_row(name, display_name, ancestors):
        row = MagicMock()
        f_field = MagicMock()
        
        name_val = MagicMock()
        name_val.struct_value.fields = {"v": MagicMock(string_value=name)}
        
        dn_val = MagicMock()
        dn_val.struct_value.fields = {"v": MagicMock(string_value=display_name)}
        
        anc_vals = []
        for anc in ancestors:
            av = MagicMock()
            av.struct_value.fields = {"v": MagicMock(string_value=anc)}
            anc_vals.append(av)
            
        anc_list = MagicMock()
        anc_list.struct_value.fields = {"v": MagicMock(list_value=MagicMock(values=anc_vals))}
        
        f_field.list_value.values = [name_val, dn_val, anc_list]
        row.fields = {"f": f_field}
        return row

    mock_page = MagicMock()
    mock_page.query_result.rows = [
        create_row("//cloudresourcemanager.googleapis.com/folders/1", "f1", ["//cloudresourcemanager.googleapis.com/organizations/123"])
    ]
    mock_client.query_assets.return_value.pages = [mock_page]

    Hierarchy._load_folders_asset(mock_org_node)
    
    assert "folders/1" in mock_org_node.folders
    folder = mock_org_node.folders["folders/1"]
    assert folder.display_name == "f1"
    # Verify prepending logic: [self, org]
    assert folder.ancestors == ["folders/1", "organizations/123"]

@patch("google.cloud.asset_v1.AssetServiceClient")
@patch("google.cloud.asset_v1.QueryAssetsRequest")
def test_load_projects_asset(mock_q_req, mock_asset_client_cls, mock_org_node):
    mock_client = mock_asset_client_cls.return_value
    mock_q_req.Statement.return_value = MagicMock()
    
    # Mock row for SELECT name(0), projectNumber(1), projectId(2), displayName(3), ancestors(4)
    def create_project_row(name, p_num, p_id, display_name, ancestors):
        row = MagicMock()
        f_field = MagicMock()
        
        v_name = MagicMock(); v_name.struct_value.fields = {"v": MagicMock(string_value=name)}
        v_num = MagicMock(); v_num.struct_value.fields = {"v": MagicMock(string_value=p_num)}
        v_id = MagicMock(); v_id.struct_value.fields = {"v": MagicMock(string_value=p_id)}
        v_dn = MagicMock(); v_dn.struct_value.fields = {"v": MagicMock(string_value=display_name)}
        
        anc_vals = []
        for anc in ancestors:
            av = MagicMock(); av.struct_value.fields = {"v": MagicMock(string_value=anc)}
            anc_vals.append(av)
        v_anc = MagicMock(); v_anc.struct_value.fields = {"v": MagicMock(list_value=MagicMock(values=anc_vals))}
        
        f_field.list_value.values = [v_name, v_num, v_id, v_dn, v_anc]
        row.fields = {"f": f_field}
        return row

    mock_page = MagicMock()
    mock_page.query_result.rows = [
        create_project_row("//cloudresourcemanager.googleapis.com/projects/p1", "123", "p1-id", "P1", ["//cloudresourcemanager.googleapis.com/folders/f1", "organizations/123"])
    ]
    mock_client.query_assets.return_value.pages = [mock_page]

    # Pre-populate a folder to test parent resolution
    mock_org_node.folders["folders/f1"] = Folder(name="folders/f1", display_name="f1", ancestors=["folders/f1", "organizations/123"], organization=mock_org_node)

    projects = Hierarchy._load_projects_asset(mock_org_node)
    
    assert len(projects) == 1
    p = projects[0]
    assert p.name == "projects/p1"
    assert p.display_name == "P1"
    assert p.parent == "folders/f1"
    assert p.folder is not None
    assert p.folder.name == "folders/f1"

@patch("google.cloud.resourcemanager_v3.OrganizationsClient")
@patch("google.cloud.resourcemanager_v3.ProjectsClient")
@patch("gcpath.core.Hierarchy._load_folders_asset")
@patch("gcpath.core.Hierarchy._load_projects_asset")
def test_hierarchy_load_orgless_always(mock_load_projects_asset, mock_load_folders_asset, mock_proj_cls, mock_org_cls, mock_org):
    # Mock Orgs
    mock_org_client = mock_org_cls.return_value
    mock_org_client.search_organizations.return_value = [mock_org]
    
    # Mock Asset Projects (Project under Org)
    p_org = Project(name="projects/p-org", project_id="p-org", display_name="P Org", parent="organizations/123", organization=None, folder=None)
    mock_load_projects_asset.return_value = [p_org]
    
    # Mock RM search_projects (Includes Orgless)
    mock_proj_client = mock_proj_cls.return_value
    p_proto_org = MagicMock(); p_proto_org.name = "projects/p-org"; p_proto_org.parent = "organizations/123"
    p_proto_orgless = MagicMock(); p_proto_orgless.name = "projects/p-orgless"; p_proto_orgless.parent = "external-parent/0"; p_proto_orgless.project_id = "p-orgless"; p_proto_orgless.display_name = "P Orgless"
    
    mock_proj_client.search_projects.return_value = [p_proto_org, p_proto_orgless]
    
    # Load via Asset API mode
    h = Hierarchy.load(via_resource_manager=False)
    
    assert len(h.organizations) == 1
    # Should have 2 projects: one from asset, one orgless from search_projects
    assert len(h.projects) == 2
    project_names = {p.name for p in h.projects}
    assert "projects/p-org" in project_names
    assert "projects/p-orgless" in project_names
