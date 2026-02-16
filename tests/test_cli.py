import pytest
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock
from gcpath.cli import app
from gcpath.core import Folder, OrganizationNode, Hierarchy, Project, GCPathError
from gcpath.cache import CacheInfo
from google.cloud import resourcemanager_v3

runner = CliRunner()


@pytest.fixture(autouse=True)
def mock_read_cache():
    """Prevent tests from hitting the real cache file."""
    with patch("gcpath.cli.read_cache", return_value=None):
        yield


@pytest.fixture
def mock_hierarchy():
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )
    org_node = OrganizationNode(organization=org_proto)

    # F1 (depth 1)
    f1 = Folder(
        name="folders/1",
        display_name="f1",
        ancestors=["folders/1", "organizations/123"],
        organization=org_node,
        parent="organizations/123",
    )
    # F11 (depth 2)
    f11 = Folder(
        name="folders/11",
        display_name="f11",
        ancestors=["folders/11", "folders/1", "organizations/123"],
        organization=org_node,
        parent="folders/1",
    )

    org_node.folders["folders/1"] = f1
    org_node.folders["folders/11"] = f11

    # Projects
    p1 = Project(
        name="projects/p1",
        project_id="p1",
        display_name="Project 1",
        parent="folders/1",
        organization=org_node,
        folder=f1,
    )

    # Orgless Project
    orgless_p = Project(
        name="projects/standalone",
        project_id="standalone",
        display_name="Standalone",
        parent="organizations/0",
        organization=None,
        folder=None,
    )

    return Hierarchy([org_node], [p1, orgless_p])


@patch("gcpath.core.Hierarchy.load")
def test_ls_command(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    # Top level orgs and orgless projects by default
    assert "//example.com" in result.stdout
    assert "//_/Standalone" in result.stdout


@patch("gcpath.core.Hierarchy.load")
@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_ls_positional_resource(mock_resolve, mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    mock_resolve.return_value = "//example.com/f1"

    # List folder/1 children
    result = runner.invoke(app, ["ls", "folders/1"])
    assert result.exit_code == 0
    # Child of folders/1 is Project 1 and folders/11 (depth 2)
    assert "//example.com/f1/f11" in result.stdout
    assert "//example.com/f1/Project%201" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_recursive(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls", "-R"])
    assert result.exit_code == 0
    assert "//example.com" in result.stdout
    assert "//example.com/f1" in result.stdout
    assert "//example.com/f1/f11" in result.stdout
    assert "//example.com/f1/Project%201" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_long_format(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls", "-l"])
    assert result.exit_code == 0
    assert "Path" in result.stdout
    assert "Resource Name" in result.stdout
    assert "example.com" in result.stdout
    assert "organizations/123" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_long_format_shows_org_resource_names(mock_load, mock_hierarchy):
    """Verify organization resource names appear in long format"""
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls", "-l"])
    assert result.exit_code == 0
    assert "organizations/123" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_long_format_shows_folder_resource_names(mock_load, mock_hierarchy):
    """Verify folder resource names appear in long format"""
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls", "-l", "organizations/123"])
    assert result.exit_code == 0
    assert "folders/1" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_long_format_shows_project_resource_names(mock_load, mock_hierarchy):
    """Verify project resource names appear in long format"""
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls", "-l", "folders/1"])
    assert result.exit_code == 0
    assert "projects/p1" in result.stdout


@patch("gcpath.core.Hierarchy.load")
@patch("typer.confirm")
def test_tree_command_full(mock_confirm, mock_load, mock_hierarchy):
    mock_confirm.return_value = True  # User confirms the prompt
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["tree"])
    assert result.exit_code == 0
    assert "example.com" in result.stdout
    assert "f1" in result.stdout
    assert "f11" in result.stdout
    assert "(organizationless)" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_tree_depth_limit(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["tree", "-L", "1"])
    assert result.exit_code == 0
    assert "f1" in result.stdout
    assert "f11" not in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_tree_accepts_level_greater_than_3(mock_load, mock_hierarchy):
    """Test that tree command accepts level > 3 (no more artificial limit)"""
    mock_load.return_value = mock_hierarchy
    # Use -y to skip the prompt that would trigger for level >= 4
    result = runner.invoke(app, ["tree", "-L", "5", "-y"])
    assert result.exit_code == 0


@patch("gcpath.cli.get_cache_info")
@patch("gcpath.core.Hierarchy.load")
@patch("typer.confirm")
def test_tree_prompts_on_unlimited_load(
    mock_confirm, mock_load, mock_cache_info, mock_hierarchy
):
    """Test that tree prompts when loading full org tree without limit"""
    mock_cache_info.return_value = CacheInfo(
        exists=False, fresh=False, age_seconds=None, size_bytes=None,
        version=None, org_count=0, folder_count=0, project_count=0
    )
    mock_confirm.return_value = True
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["tree"])
    assert mock_confirm.called
    assert result.exit_code == 0


@patch("gcpath.cli.get_cache_info")
@patch("gcpath.core.Hierarchy.load")
@patch("typer.confirm")
def test_tree_prompts_on_large_level(
    mock_confirm, mock_load, mock_cache_info, mock_hierarchy
):
    """Test that tree prompts when level >= 4"""
    mock_cache_info.return_value = CacheInfo(
        exists=False, fresh=False, age_seconds=None, size_bytes=None,
        version=None, org_count=0, folder_count=0, project_count=0
    )
    mock_confirm.return_value = True
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["tree", "-L", "4"])
    assert mock_confirm.called
    assert result.exit_code == 0


@patch("gcpath.core.Hierarchy.load")
@patch("typer.confirm")
def test_tree_yes_flag_skips_prompt(mock_confirm, mock_load, mock_hierarchy):
    """Test that --yes skips prompt"""
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["tree", "-y"])
    assert not mock_confirm.called
    assert result.exit_code == 0


@patch("gcpath.core.Hierarchy.load")
@patch("gcpath.cli.Hierarchy.resolve_ancestry")
@patch("typer.confirm")
def test_tree_scoped_load_no_prompt(
    mock_confirm, mock_resolve, mock_load, mock_hierarchy
):
    """Test that scoped loads don't prompt"""
    mock_load.return_value = mock_hierarchy
    mock_resolve.return_value = "//example.com/f1"
    result = runner.invoke(app, ["tree", "folders/1"])
    assert not mock_confirm.called
    assert result.exit_code == 0


@patch("gcpath.core.Hierarchy.load")
@patch("typer.confirm")
def test_tree_user_declines_prompt(mock_confirm, mock_load, mock_hierarchy):
    """Test that declining prompt exits cleanly"""
    mock_confirm.return_value = False
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["tree"])
    assert result.exit_code == 0  # Clean exit


@patch("gcpath.core.Hierarchy.load")
@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_tree_positional_resource(mock_resolve, mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    mock_resolve.return_value = "//example.com/f1"
    result = runner.invoke(app, ["tree", "folders/1"])
    assert result.exit_code == 0
    assert "//example.com/f1" in result.stdout
    assert "f11" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_name_command(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["name", "//example.com/f1"])
    assert result.exit_code == 0
    assert "folders/1" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_name_command_id_only(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["name", "--id", "//example.com/f1"])
    assert result.exit_code == 0
    assert "1" in result.stdout
    assert "folders" not in result.stdout


@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_path_command(mock_resolve):
    mock_resolve.return_value = "//example.com/f1"
    result = runner.invoke(app, ["path", "folders/1"])
    assert result.exit_code == 0
    assert "//example.com/f1" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_no_resources_message(mock_load):
    h = Hierarchy([], [])
    mock_load.return_value = h
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    # No organizations or projects message check
    # Depending on implementation it might print something or just empty list now with organizations/projects structure
    # My current implementation of ls doesn't have the specific "No resources found" msg anymore, it just prints what it finds.
    # But let's verify it doesn't crash.
    pass


def test_handle_error_gcpath_error():
    from gcpath.cli import handle_error
    import typer

    with pytest.raises(typer.Exit):
        handle_error(GCPathError("test error"))


@patch("gcpath.cli.Hierarchy.load")
def test_debug_flag(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["--debug", "ls"])
    assert result.exit_code == 0


@patch("gcpath.core.Hierarchy.load")
def test_ls_gmail_account(mock_load):
    # Mock google.auth.default to return a gmail account
    mock_creds = MagicMock()
    mock_creds.account = "user@gmail.com"

    with patch("google.auth.default", return_value=(mock_creds, "project")):
        mock_load.return_value = Hierarchy([], [])
        result = runner.invoke(app, ["ls"])
        assert (
            "No organizations or projects found accessible to your account"
            in result.stdout
        )
        assert "user@gmail.com" in result.stdout


@patch("gcpath.core.Hierarchy.load")
@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_ls_recursive_folder(mock_resolve, mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    mock_resolve.return_value = "//example.com/f1"

    result = runner.invoke(app, ["ls", "-R", "folders/1"])
    assert result.exit_code == 0
    assert "//example.com/f1" in result.stdout
    assert "//example.com/f1/f11" in result.stdout


def test_handle_error_permission_denied():
    from google.api_core import exceptions as gcp_exceptions
    from gcpath.cli import handle_error
    import typer

    with pytest.raises(typer.Exit):
        handle_error(gcp_exceptions.PermissionDenied("denied"))


def test_handle_error_service_unavailable():
    from google.api_core import exceptions as gcp_exceptions
    from gcpath.cli import handle_error
    import typer

    with pytest.raises(typer.Exit):
        handle_error(gcp_exceptions.ServiceUnavailable("unavailable"))


@patch("gcpath.core.Hierarchy.load")
@patch("typer.confirm")
def test_tree_with_ids(mock_confirm, mock_load, mock_hierarchy):
    mock_confirm.return_value = True  # User confirms the prompt
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["tree", "--ids"])
    assert result.exit_code == 0
    assert "(organizations/123)" in result.stdout
    assert "(folders/1)" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_name_organizationless_project(mock_load):
    # Setup hierarchy with an orgless project
    p1 = Project(
        name="projects/965192208715",
        project_id="main-dev-levente-001",
        display_name="main-dev-levente-001",
        parent="organizations/0",
        organization=None,
        folder=None,
    )
    mock_load.return_value = Hierarchy([], [p1])

    result = runner.invoke(app, ["name", "//_/main-dev-levente-001"])
    assert result.exit_code == 0
    assert "projects/965192208715" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_name_multiple_paths(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["name", "//example.com", "//example.com/f1"])
    assert result.exit_code == 0
    assert "organizations/123" in result.stdout
    assert "folders/1" in result.stdout


@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_path_multiple_resources(mock_resolve):
    mock_resolve.side_effect = ["//path1", "//path2"]
    result = runner.invoke(app, ["path", "folders/1", "folders/2"])
    assert result.exit_code == 0
    assert "//path1" in result.stdout
    assert "//path2" in result.stdout


@patch("gcpath.cli.clear_cache")
def test_cache_clear(mock_clear_cache):
    """Test cache clear subcommand"""
    mock_clear_cache.return_value = True
    result = runner.invoke(app, ["cache", "clear"])
    assert result.exit_code == 0
    mock_clear_cache.assert_called_once()


@patch("gcpath.cli.get_cache_info")
def test_cache_status(mock_get_cache_info):
    """Test cache status subcommand with fresh cache"""
    mock_get_cache_info.return_value = CacheInfo(
        exists=True,
        fresh=True,
        age_seconds=300.0,  # 5 minutes ago
        size_bytes=2048,
        version=1,
        org_count=2,
        folder_count=10,
        project_count=25,
    )
    result = runner.invoke(app, ["cache", "status"])
    assert result.exit_code == 0
    assert "Fresh" in result.stdout or "5m" in result.stdout
    assert "2.0 KB" in result.stdout  # 2048 bytes = 2.0 KB
    assert "2" in result.stdout  # org count
    assert "10" in result.stdout  # folder count
    assert "25" in result.stdout  # project count


@patch("gcpath.cli.get_cache_info")
def test_cache_status_no_cache(mock_get_cache_info):
    """Test cache status subcommand when no cache exists"""
    mock_get_cache_info.return_value = CacheInfo(
        exists=False,
        fresh=False,
        age_seconds=None,
        size_bytes=None,
        version=None,
        org_count=0,
        folder_count=0,
        project_count=0,
    )
    result = runner.invoke(app, ["cache", "status"])
    assert result.exit_code == 0
    assert "No cache" in result.stdout or "Does not exist" in result.stdout


# --- Diagram command tests ---


@patch("gcpath.core.Hierarchy.load")
@patch("typer.confirm")
def test_diagram_mermaid_default(mock_confirm, mock_load, mock_hierarchy):
    """Test diagram command produces Mermaid output by default."""
    mock_confirm.return_value = True
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["diagram"])
    assert result.exit_code == 0
    assert "graph TD" in result.stdout
    assert "organizations_123" in result.stdout
    assert "example.com" in result.stdout


@patch("gcpath.core.Hierarchy.load")
@patch("typer.confirm")
def test_diagram_d2(mock_confirm, mock_load, mock_hierarchy):
    """Test diagram command with D2 format."""
    mock_confirm.return_value = True
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["diagram", "--format", "d2"])
    assert result.exit_code == 0
    assert "graph TD" not in result.stdout
    assert "organizations_123" in result.stdout
    assert "->" in result.stdout


@patch("gcpath.core.Hierarchy.load")
@patch("typer.confirm")
def test_diagram_with_ids(mock_confirm, mock_load, mock_hierarchy):
    """Test diagram command with resource IDs."""
    mock_confirm.return_value = True
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["diagram", "--ids"])
    assert result.exit_code == 0
    assert "(organizations/123)" in result.stdout


@patch("gcpath.core.Hierarchy.load")
@patch("typer.confirm")
def test_diagram_with_level(mock_confirm, mock_load, mock_hierarchy):
    """Test diagram with depth limit."""
    mock_confirm.return_value = True
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["diagram", "-L", "1"])
    assert result.exit_code == 0
    assert "f1" in result.stdout
    # f11 is at depth 2, should not appear
    assert "f11" not in result.stdout


@patch("gcpath.core.Hierarchy.load")
@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_diagram_scoped(mock_resolve, mock_load, mock_hierarchy):
    """Test diagram with scoped resource."""
    mock_load.return_value = mock_hierarchy
    mock_resolve.return_value = "//example.com/f1"
    result = runner.invoke(app, ["diagram", "folders/1"])
    assert result.exit_code == 0
    assert "folders_1" in result.stdout


@patch("gcpath.core.Hierarchy.load")
@patch("typer.confirm")
def test_diagram_output_file(mock_confirm, mock_load, mock_hierarchy, tmp_path):
    """Test diagram output to file."""
    mock_confirm.return_value = True
    mock_load.return_value = mock_hierarchy
    out_file = tmp_path / "test.mmd"
    result = runner.invoke(app, ["diagram", "-o", str(out_file)])
    assert result.exit_code == 0
    assert out_file.exists()
    content = out_file.read_text()
    assert "graph TD" in content


@patch("gcpath.core.Hierarchy.load")
@patch("typer.confirm")
def test_diagram_includes_orgless(mock_confirm, mock_load, mock_hierarchy):
    """Test that diagram includes organizationless projects."""
    mock_confirm.return_value = True
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["diagram"])
    assert result.exit_code == 0
    assert "organizationless" in result.stdout
    assert "Standalone" in result.stdout


def test_diagram_invalid_format():
    """Test diagram command rejects invalid format."""
    result = runner.invoke(app, ["diagram", "--format", "svg", "-y"])
    assert result.exit_code == 1


@patch("gcpath.core.Hierarchy.load")
def test_diagram_yes_flag_skips_prompt(mock_load, mock_hierarchy):
    """Test that --yes skips prompt."""
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["diagram", "-y"])
    assert result.exit_code == 0
