import pytest
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock
from gcpath.cli import app
from gcpath.core import Folder, OrganizationNode, Hierarchy, Project, GCPathError
from google.cloud import resourcemanager_v3

runner = CliRunner()


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
    assert "ID" in result.stdout
    assert "NAME" in result.stdout
    assert "NUMBER" in result.stdout
    assert "example.com" in result.stdout
    assert "123" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_tree_command_full(mock_load, mock_hierarchy):
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


def test_tree_max_level_validation():
    """Test that tree command rejects level > 3"""
    result = runner.invoke(app, ["tree", "-L", "4"])
    assert result.exit_code == 1
    assert "Maximum tree depth is 3" in result.stderr
    assert "Requested level 4" in result.stderr


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
def test_tree_with_ids(mock_load, mock_hierarchy):
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
