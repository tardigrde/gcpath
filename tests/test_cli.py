import json

import pytest
import yaml
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock
from conftest import make_test_hierarchy
from gcpath.cli import app
from gcpath.core import OrganizationNode, Hierarchy, Project, GCPathError
from gcpath.cache import CacheInfo
from google.cloud import resourcemanager_v3

runner = CliRunner()


@pytest.fixture(autouse=True)
def mock_read_cache():
    with patch("gcpath.cli.read_cache", return_value=None) as m:
        yield m


@pytest.fixture(autouse=True)
def mock_get_cache_info_home():
    with patch("gcpath.cli.get_cache_info", return_value=CacheInfo(
        exists=False, fresh=False, age_seconds=None, size_bytes=None,
        version=None, org_count=0, folder_count=0, project_count=0,
    )) as m:
        yield m


@patch("gcpath.core.Hierarchy.load")
def test_ls_command(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "//example.com" in result.stdout


@patch("gcpath.core.Hierarchy.load")
@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_ls_positional_resource(mock_resolve, mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    mock_resolve.return_value = "//example.com/f1"

    result = runner.invoke(app, ["ls", "folders/1"])
    assert result.exit_code == 0
    assert "//example.com/f1" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_recursive(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls", "-R"])
    assert result.exit_code == 0
    assert "//example.com" in result.stdout
    assert "//example.com/f1" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_default_toon_format(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "count:" in result.stdout
    assert "resources" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_rich_format(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["--format", "rich", "ls"])
    assert result.exit_code == 0
    assert "Path" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_tree_command(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["tree"])
    assert result.exit_code == 0
    assert "example.com" in result.stdout
    assert "f1" in result.stdout
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
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["tree", "-L", "5"])
    assert result.exit_code == 0


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
    assert result.exception is None


@patch("gcpath.core.Hierarchy.load")
def test_stats_command(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "folders" in result.stdout.lower()
    assert "projects" in result.stdout.lower()


@patch("gcpath.core.Hierarchy.load")
def test_stats_command_scoped_org(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["stats", "organizations/123"])
    assert result.exit_code == 0
    assert "organizations/123" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_stats_command_scoped_folder(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["stats", "folders/1"])
    assert result.exit_code == 0
    assert "folders/1" in result.stdout


def test_stats_project_scope_error():
    result = runner.invoke(app, ["stats", "projects/123"])
    assert result.exit_code == 1


def test_stats_invalid_scope_error():
    result = runner.invoke(app, ["stats", "invalid/scope"])
    assert result.exit_code == 1
    assert "Invalid resource format" in result.output


def test_handle_error_gcpath_error():
    from gcpath.cli import handle_error
    import typer

    with pytest.raises(typer.Exit):
        handle_error(GCPathError("test error"))


@patch("gcpath.core.Hierarchy.load")
def test_debug_flag(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["--debug", "ls"])
    assert result.exit_code == 0


@patch("gcpath.core.Hierarchy.load")
def test_ls_gmail_account(mock_load):
    mock_creds = MagicMock()
    mock_creds.account = "user@gmail.com"

    with patch("google.auth.default", return_value=(mock_creds, "project")):
        mock_load.return_value = Hierarchy([], [])
        result = runner.invoke(app, ["ls"])
        assert "No organizations or projects found" in result.stdout


@patch("gcpath.core.Hierarchy.load")
@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_ls_recursive_folder(mock_resolve, mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    mock_resolve.return_value = "//example.com/f1"

    result = runner.invoke(app, ["ls", "-R", "folders/1"])
    assert result.exit_code == 0
    assert "//example.com/f1" in result.stdout


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
    mock_clear_cache.return_value = True
    result = runner.invoke(app, ["cache", "clear"])
    assert result.exit_code == 0
    mock_clear_cache.assert_called_once()


@patch("gcpath.cli.get_cache_info")
def test_cache_status(mock_get_cache_info):
    mock_get_cache_info.return_value = CacheInfo(
        exists=True,
        fresh=True,
        age_seconds=300.0,
        size_bytes=2048,
        version=1,
        org_count=2,
        folder_count=10,
        project_count=25,
    )
    result = runner.invoke(app, ["cache", "status"])
    assert result.exit_code == 0
    assert "fresh" in result.stdout.lower()
    assert "2.0 KB" in result.stdout


@patch("gcpath.cli.get_cache_info")
def test_cache_status_no_cache(mock_get_cache_info):
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
    assert "empty" in result.stdout.lower()


@patch("gcpath.core.Hierarchy.load")
def test_diagram_mermaid_default(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["diagram"])
    assert result.exit_code == 0
    assert "graph TD" in result.stdout
    assert "organizations_123" in result.stdout
    assert "example.com" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_diagram_d2(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["diagram", "--diagram-format", "d2"])
    assert result.exit_code == 0
    assert "graph TD" not in result.stdout
    assert "organizations_123" in result.stdout
    assert "->" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_diagram_with_ids(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["diagram", "--ids"])
    assert result.exit_code == 0
    assert "(organizations/123)" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_diagram_with_level(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["diagram", "-L", "1"])
    assert result.exit_code == 0
    assert "f1" in result.stdout
    assert "f11" not in result.stdout


@patch("gcpath.core.Hierarchy.load")
@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_diagram_scoped(mock_resolve, mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    mock_resolve.return_value = "//example.com/f1"
    result = runner.invoke(app, ["diagram", "folders/1"])
    assert result.exit_code == 0
    assert "folders_1" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_diagram_output_file(mock_load, mock_hierarchy, tmp_path):
    mock_load.return_value = mock_hierarchy
    out_file = tmp_path / "test.mmd"
    result = runner.invoke(app, ["diagram", "-o", str(out_file)])
    assert result.exit_code == 0
    assert out_file.exists()
    content = out_file.read_text()
    assert "graph TD" in content


@patch("gcpath.core.Hierarchy.load")
def test_diagram_includes_orgless(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["diagram"])
    assert result.exit_code == 0
    assert "organizationless" in result.stdout
    assert "Standalone" in result.stdout


def test_diagram_invalid_format():
    result = runner.invoke(app, ["diagram", "--diagram-format", "svg"])
    assert result.exit_code == 1


@patch("gcpath.cli.set_entrypoint")
def test_config_set_entrypoint(mock_set):
    result = runner.invoke(app, ["config", "set-entrypoint", "folders/123"])
    assert result.exit_code == 0
    mock_set.assert_called_once_with("folders/123")
    assert "Entrypoint set" in result.stdout


@patch("gcpath.cli.set_entrypoint", side_effect=ValueError("must start with"))
def test_config_set_entrypoint_invalid(mock_set):
    result = runner.invoke(app, ["config", "set-entrypoint", "projects/bad"])
    assert result.exit_code == 1


@patch("gcpath.cli.read_config", return_value={"entrypoint": "folders/123"})
def test_config_show(mock_read):
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "folders/123" in result.stdout


@patch("gcpath.cli.read_config", return_value={})
def test_config_show_empty(mock_read):
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "empty" in result.stdout.lower()


@patch("gcpath.cli.clear_entrypoint")
def test_config_clear_entrypoint(mock_clear):
    result = runner.invoke(app, ["config", "clear-entrypoint"])
    assert result.exit_code == 0
    assert "cleared" in result.stdout.lower()
    mock_clear.assert_called_once()


@patch("gcpath.cli.get_entrypoint", return_value="folders/100")
@patch("gcpath.core.Hierarchy.load")
@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_ls_with_entrypoint(mock_resolve, mock_load, mock_get_ep, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    mock_resolve.return_value = "//example.com/f1"

    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    mock_load.assert_called_once()
    call_kwargs = mock_load.call_args
    assert call_kwargs[1]["scope_resource"] == "folders/100"


@patch("gcpath.cli.get_entrypoint", return_value="folders/100")
@patch("gcpath.core.Hierarchy.load")
@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_ls_explicit_resource_overrides_entrypoint(
    mock_resolve, mock_load, mock_get_ep, mock_hierarchy
):
    mock_load.return_value = mock_hierarchy
    mock_resolve.return_value = "//example.com/f1"

    result = runner.invoke(app, ["ls", "folders/1"])
    assert result.exit_code == 0
    mock_load.assert_called_once()
    call_kwargs = mock_load.call_args
    assert call_kwargs[1]["scope_resource"] == "folders/1"


@patch("gcpath.cli.get_entrypoint", return_value="folders/100")
@patch("gcpath.core.Hierarchy.load")
@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_entrypoint_flag_overrides_config(
    mock_resolve, mock_load, mock_get_ep, mock_hierarchy
):
    mock_load.return_value = mock_hierarchy
    mock_resolve.return_value = "//example.com/f1"

    result = runner.invoke(app, ["--entrypoint", "folders/200", "ls"])
    assert result.exit_code == 0
    mock_load.assert_called_once()
    call_kwargs = mock_load.call_args
    assert call_kwargs[1]["scope_resource"] == "folders/200"


@patch("gcpath.cli.get_entrypoint", return_value="folders/100")
@patch("gcpath.core.Hierarchy.load")
@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_tree_with_entrypoint(mock_resolve, mock_load, mock_get_ep, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    mock_resolve.return_value = "//example.com/f1"

    result = runner.invoke(app, ["tree"])
    assert result.exit_code == 0
    mock_load.assert_called_once()
    call_kwargs = mock_load.call_args
    assert call_kwargs[1]["scope_resource"] == "folders/100"


@patch("gcpath.cli.get_entrypoint", return_value="folders/100")
@patch("gcpath.core.Hierarchy.load")
def test_name_with_entrypoint(mock_load, mock_get_ep, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["name", "//example.com/f1"])
    assert result.exit_code == 0
    mock_load.assert_called_once()
    call_kwargs = mock_load.call_args
    assert call_kwargs[1]["scope_resource"] == "folders/100"


@patch("gcpath.cli.get_entrypoint", return_value="folders/100")
@patch("gcpath.cli.write_cache")
@patch("gcpath.core.Hierarchy.load")
@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_ls_entrypoint_uses_cache(
    mock_resolve, mock_load, mock_write, mock_get_ep, mock_hierarchy, mock_read_cache
):
    mock_read_cache.return_value = mock_hierarchy
    mock_resolve.return_value = "//example.com/f1"

    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    mock_read_cache.assert_called_with(scope="folders/100")
    mock_load.assert_not_called()


@patch("gcpath.cli.get_entrypoint", return_value="folders/100")
@patch("gcpath.cli.write_cache")
@patch("gcpath.core.Hierarchy.load")
@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_ls_entrypoint_writes_cache(
    mock_resolve, mock_load, mock_write, mock_get_ep, mock_hierarchy, mock_read_cache
):
    mock_read_cache.return_value = None
    mock_load.return_value = mock_hierarchy
    mock_resolve.return_value = "//example.com/f1"

    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    mock_write.assert_called_once_with(mock_hierarchy, scope="folders/100")


@patch("gcpath.cli.get_entrypoint", return_value="folders/100")
@patch("gcpath.cli.write_cache")
@patch("gcpath.core.Hierarchy.load")
@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_ls_entrypoint_loads_recursively(
    mock_resolve, mock_load, mock_write, mock_get_ep, mock_hierarchy, mock_read_cache
):
    mock_read_cache.return_value = None
    mock_load.return_value = mock_hierarchy
    mock_resolve.return_value = "//example.com/f1"

    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    mock_load.assert_called_once()
    call_kwargs = mock_load.call_args[1]
    assert call_kwargs["recursive"] is True


@patch("gcpath.cli.get_entrypoint", return_value="folders/100")
@patch("gcpath.cli.write_cache")
@patch("gcpath.core.Hierarchy.load")
@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_ls_explicit_resource_not_cached(
    mock_resolve, mock_load, mock_write, mock_get_ep, mock_hierarchy, mock_read_cache
):
    mock_read_cache.return_value = None
    mock_load.return_value = mock_hierarchy
    mock_resolve.return_value = "//example.com/f1"

    result = runner.invoke(app, ["ls", "folders/999"])
    assert result.exit_code == 0
    mock_write.assert_not_called()


@patch("gcpath.cli.get_cache_info")
def test_cache_status_shows_scope(mock_get_cache_info):
    mock_get_cache_info.return_value = CacheInfo(
        exists=True,
        fresh=True,
        age_seconds=300.0,
        size_bytes=2048,
        version=1,
        org_count=1,
        folder_count=5,
        project_count=10,
        scope="folders/100",
    )
    result = runner.invoke(app, ["cache", "status"])
    assert result.exit_code == 0
    assert "folders/100" in result.stdout


@patch("gcpath.cli.read_cache")
@patch("gcpath.cli.get_cache_info")
def test_try_read_cache_returns_none_on_miss(mock_get_info, mock_read_cache):
    from gcpath.cli import _try_read_cache

    mock_read_cache.return_value = None
    result = _try_read_cache(None, None)
    assert result is None


@patch("gcpath.cli.read_cache")
@patch("gcpath.cli.get_cache_info")
def test_try_read_cache_applies_org_filter(mock_get_info, mock_read_cache):
    from gcpath.cli import _try_read_cache

    org1 = resourcemanager_v3.Organization(
        name="organizations/1", display_name="org1.com"
    )
    org2 = resourcemanager_v3.Organization(
        name="organizations/2", display_name="org2.com"
    )
    node1 = OrganizationNode(organization=org1)
    node2 = OrganizationNode(organization=org2)
    mock_hierarchy = Hierarchy([node1, node2], [])

    mock_read_cache.return_value = mock_hierarchy
    mock_get_info.return_value = CacheInfo(
        exists=True, fresh=True, age_seconds=60.0, size_bytes=100,
        version=1, org_count=2, folder_count=0, project_count=0,
    )

    result = _try_read_cache(None, ["org1.com"])
    assert len(result.organizations) == 1
    assert result.organizations[0].organization.display_name == "org1.com"


def test_format_json_output():
    result = runner.invoke(app, ["--format", "json", "ls"])
    assert result.exit_code != 2
    assert "No such option" not in result.output


def test_format_invalid():
    result = runner.invoke(app, ["--format", "xml", "ls"])
    assert result.exit_code == 1
    assert "Invalid format" in result.output


@patch("gcpath.core.Hierarchy.load")
def test_ls_json_output(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["--format", "json", "ls"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert len(data) > 0
    assert all("path" in item for item in data)
    assert all("type" in item for item in data)


@patch("gcpath.core.Hierarchy.load")
def test_ls_yaml_output(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["--format", "yaml", "ls"])
    assert result.exit_code == 0
    data = yaml.safe_load(result.stdout)
    assert isinstance(data, list)
    assert len(data) > 0
    assert all("path" in item for item in data)


@patch("gcpath.core.Hierarchy.load")
def test_ls_json_no_data(mock_load):
    mock_load.return_value = Hierarchy([], [])
    result = runner.invoke(app, ["--format", "json", "ls"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data == []


@patch("gcpath.core.Hierarchy.load")
def test_tree_json_output(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["--format", "json", "tree"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert len(data) >= 1
    org_node = data[0]
    assert org_node["type"] == "organization"
    assert "children" in org_node


@patch("gcpath.core.Hierarchy.load")
def test_tree_yaml_output(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["--format", "yaml", "tree"])
    assert result.exit_code == 0
    data = yaml.safe_load(result.stdout)
    assert isinstance(data, list)
    assert data[0]["type"] == "organization"
    assert "children" in data[0]


@patch("gcpath.core.Hierarchy.load")
def test_name_json_output(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["--format", "json", "name", "//example.com/f1"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert data[0]["path"] == "//example.com/f1"
    assert data[0]["resource_name"] == "folders/1"


@patch("gcpath.core.Hierarchy.load")
def test_name_json_id_only(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["--format", "json", "name", "--id", "//example.com/f1"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "resource_id" in data[0]
    assert data[0]["resource_id"] == "1"


@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_path_json_output(mock_resolve):
    mock_resolve.return_value = "//example.com/f1"
    result = runner.invoke(app, ["--format", "json", "path", "folders/1"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert data[0]["resource_name"] == "folders/1"
    assert data[0]["path"] == "//example.com/f1"


@patch("gcpath.core.Hierarchy.load")
def test_json_output_no_rich_markup(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["--format", "json", "ls"])
    assert result.exit_code == 0
    assert "[dim]" not in result.stdout
    assert "[bold" not in result.stdout
    assert "[green]" not in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_type_folder(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls", "--type", "folder", "-R"])
    assert result.exit_code == 0
    assert "f1" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_type_project(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls", "--type", "project", "-R"])
    assert result.exit_code == 0
    assert "Project" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_type_organization(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls", "--type", "organization"])
    assert result.exit_code == 0
    assert "//example.com" in result.stdout  # lgtm[py/incomplete-url-substring-sanitization]


def test_ls_type_invalid():
    result = runner.invoke(app, ["ls", "--type", "invalid"])
    assert result.exit_code == 1
    assert "Invalid type" in result.output


@patch("gcpath.core.Hierarchy.load")
def test_tree_type_folder(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["tree", "--type", "folder"])
    assert result.exit_code == 0
    assert "f1" in result.stdout
    assert "Project 1" not in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_tree_type_project(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["tree", "--type", "project"])
    assert result.exit_code == 0
    assert "Project 1" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_type_folder_json(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["--format", "json", "ls", "--type", "folder", "-R"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert all(item["type"] == "folder" for item in data)


@patch("gcpath.core.Hierarchy.load")
def test_ls_recursive_with_level(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls", "-R", "-L", "1"])
    assert result.exit_code == 0
    assert "//example.com" in result.stdout
    assert "//example.com/f1" in result.stdout
    assert "//example.com/f1/f11" not in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_recursive_with_level_2(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls", "-R", "-L", "2"])
    assert result.exit_code == 0
    assert "//example.com/f1" in result.stdout
    assert "//example.com/f1/f11" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_find_command(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["find", "f*"])
    assert result.exit_code == 0
    assert "f1" in result.stdout
    assert "f11" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_find_command_exact(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["find", "f1"])
    assert result.exit_code == 0
    assert "f1" in result.stdout
    assert "f11" not in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_find_type_filter(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["find", "--type", "project", "*"])
    assert result.exit_code == 0
    assert "Project" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_find_no_match(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["find", "nonexistent-xyz"])
    assert result.exit_code == 0
    assert "0" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_find_json_output(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["--format", "json", "find", "f*"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert len(data) >= 2


@patch("gcpath.core.Hierarchy.load")
def test_find_case_insensitive(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["find", "PROJECT*"])
    assert result.exit_code == 0
    assert "Project" in result.stdout


def test_find_type_invalid():
    result = runner.invoke(app, ["find", "--type", "invalid", "*"])
    assert result.exit_code == 1
    assert "Invalid type" in result.output


@patch("gcpath.core.Hierarchy.resolve_ancestry_chain")
def test_ancestors_command(mock_chain):
    mock_chain.return_value = [
        ("organizations/123", "example.com", "organization"),
        ("folders/456", "engineering", "folder"),
        ("projects/p1", "my-project", "project"),
    ]
    result = runner.invoke(app, ["ancestors", "projects/p1"])
    assert result.exit_code == 0
    assert "organizations/123" in result.stdout
    assert "example.com" in result.stdout  # lgtm[py/incomplete-url-substring-sanitization]
    assert "folders/456" in result.stdout


@patch("gcpath.core.Hierarchy.resolve_ancestry_chain")
def test_ancestors_json(mock_chain):
    mock_chain.return_value = [
        ("organizations/123", "example.com", "organization"),
        ("folders/456", "engineering", "folder"),
    ]
    result = runner.invoke(app, ["--format", "json", "ancestors", "folders/456"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert len(data) == 2
    assert data[0]["resource_name"] == "organizations/123"
    assert data[0]["type"] == "organization"


def test_ancestors_invalid_resource():
    result = runner.invoke(app, ["ancestors", "invalid/123"])
    assert result.exit_code == 1
    assert "Invalid resource format" in result.output


@patch("gcpath.core.Hierarchy.load")
def test_ls_show_labels_rich(mock_load):
    hierarchy = make_test_hierarchy()
    f1 = hierarchy.organizations[0].folders["folders/1"]
    f1.labels = {"env": "prod"}
    mock_load.return_value = hierarchy

    result = runner.invoke(app, ["--format", "rich", "ls", "--show-labels"])
    assert result.exit_code == 0
    assert "Labels" in result.stdout
    assert "env=prod" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_label_filter(mock_load):
    hierarchy = make_test_hierarchy()
    f1 = hierarchy.organizations[0].folders["folders/1"]
    f1.labels = {"env": "prod"}
    f11 = hierarchy.organizations[0].folders["folders/11"]
    f11.labels = {"env": "dev"}
    mock_load.return_value = hierarchy

    result = runner.invoke(app, ["ls", "-R", "--label", "env=prod"])
    assert result.exit_code == 0
    assert "f1" in result.stdout
    assert "f11" not in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_label_filter_key_only(mock_load):
    hierarchy = make_test_hierarchy()
    f1 = hierarchy.organizations[0].folders["folders/1"]
    f1.labels = {"env": "prod"}
    f11 = hierarchy.organizations[0].folders["folders/11"]
    f11.labels = {}
    mock_load.return_value = hierarchy

    result = runner.invoke(app, ["ls", "-R", "--label", "env"])
    assert result.exit_code == 0
    assert "f1" in result.stdout
    assert "f11" not in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_json_with_labels(mock_load):
    hierarchy = make_test_hierarchy()
    f1 = hierarchy.organizations[0].folders["folders/1"]
    f1.labels = {"env": "prod"}
    mock_load.return_value = hierarchy

    result = runner.invoke(app, ["--format", "json", "ls", "-R", "--show-labels"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    labeled = [item for item in data if item.get("labels")]
    assert len(labeled) >= 1
    assert labeled[0]["labels"] == {"env": "prod"}


@patch("gcpath.core.Hierarchy.load")
def test_find_with_label_filter(mock_load):
    hierarchy = make_test_hierarchy()
    f1 = hierarchy.organizations[0].folders["folders/1"]
    f1.labels = {"env": "prod"}
    f11 = hierarchy.organizations[0].folders["folders/11"]
    f11.labels = {}
    mock_load.return_value = hierarchy

    result = runner.invoke(app, ["find", "f*", "--label", "env=prod"])
    assert result.exit_code == 0
    assert "f1" in result.stdout
    assert "f11" not in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_fields_flag(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls", "--fields", "path,type"])
    assert result.exit_code == 0
    assert "path" in result.stdout
    assert "type" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_ls_fields_invalid(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls", "--fields", "path,invalid_field"])
    assert result.exit_code == 1


@patch("gcpath.core.Hierarchy.load")
def test_ls_full_flag(mock_load):
    hierarchy = make_test_hierarchy()
    f1 = hierarchy.organizations[0].folders["folders/1"]
    f1.labels = {f"key{i}": f"val{i}" for i in range(8)}
    mock_load.return_value = hierarchy

    result = runner.invoke(app, ["ls", "--fields", "path,type,labels", "--full"])
    assert result.exit_code == 0


@patch("gcpath.core.Hierarchy.load")
def test_home_view_no_cache(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "bin:" in result.stdout
    assert "description:" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_hook_status(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["hook", "status"])
    assert result.exit_code == 0


@patch("gcpath.core.Hierarchy.load")
def test_toon_ls_has_count(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "count:" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_toon_ls_has_help(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "help" in result.stdout.lower()


@patch("gcpath.core.Hierarchy.load")
def test_toon_stats_output(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "scope:" in result.stdout
    assert "folders:" in result.stdout
    assert "projects:" in result.stdout


@patch("gcpath.core.Hierarchy.load")
def test_toon_name_single(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["name", "//example.com/f1"])
    assert result.exit_code == 0
    assert "resource_name:" in result.stdout
    assert "folders/1" in result.stdout


@patch("gcpath.cli.Hierarchy.resolve_ancestry")
def test_toon_path_single(mock_resolve):
    mock_resolve.return_value = "//example.com/f1"
    result = runner.invoke(app, ["path", "folders/1"])
    assert result.exit_code == 0
    assert "path:" in result.stdout
    assert "//example.com/f1" in result.stdout


# --- Coverage for new features ---


def test_invalid_format_flag():
    result = runner.invoke(app, ["--format", "invalid", "ls"])
    assert result.exit_code == 1
    assert "Invalid format" in result.stdout


@patch("gcpath.cli.get_cache_info")
@patch("gcpath.cli.read_cache_raw")
def test_home_view_with_fresh_cache(mock_raw, mock_info):
    mock_info.return_value = MagicMock(
        exists=True, fresh=True, age_seconds=120.0,
        size_bytes=1024, version=1, org_count=1, folder_count=5, project_count=10,
    )
    mock_raw.return_value = {
        "organizations": [
            {
                "organization": {"display_name": "example.com"},
                "folders": {"folders/1": {}, "folders/2": {}},
                "projects": [{}],
            }
        ]
    }
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "description:" in result.stdout
    assert "cache:" in result.stdout


@patch("gcpath.cli.install_hooks", return_value={"claude": True, "codex": False})
def test_hook_install(mock_install):
    result = runner.invoke(app, ["hook", "install"])
    assert result.exit_code == 0
    mock_install.assert_called_once()
    assert "installed" in result.stdout


@patch("gcpath.cli.install_hooks", return_value={"claude": True})
def test_hook_install_rich(mock_install):
    result = runner.invoke(app, ["--format", "rich", "hook", "install"])
    assert result.exit_code == 0
    mock_install.assert_called_once()


@patch("gcpath.cli.uninstall_hooks", return_value={"claude": True, "codex": False})
def test_hook_uninstall(mock_uninstall):
    result = runner.invoke(app, ["hook", "uninstall"])
    assert result.exit_code == 0
    mock_uninstall.assert_called_once()
    assert "uninstalled" in result.stdout


@patch("gcpath.cli.uninstall_hooks", return_value={"claude": False})
def test_hook_uninstall_rich(mock_uninstall):
    result = runner.invoke(app, ["--format", "rich", "hook", "uninstall"])
    assert result.exit_code == 0
    mock_uninstall.assert_called_once()


@patch("gcpath.cli.run_session_start", return_value="session dashboard output")
def test_hook_run(mock_run):
    result = runner.invoke(app, ["hook", "run"])
    assert result.exit_code == 0
    mock_run.assert_called_once()
    assert "session dashboard output" in result.stdout


@patch("gcpath.cli.get_hook_status", return_value={
    "claude": {"installed": True, "path_ok": True, "location": "~/.claude/settings.json"},
    "codex": {"installed": False, "path_ok": False, "location": "~/.codex/hooks.json"},
})
def test_hook_status_rich(mock_status):
    result = runner.invoke(app, ["--format", "rich", "hook", "status"])
    assert result.exit_code == 0
    mock_status.assert_called_once()


@patch("gcpath.cli.get_hook_status", return_value={
    "claude": {"installed": True, "path_ok": False, "location": "~/.claude/settings.json"},
})
def test_hook_status_path_not_ok(mock_status):
    result = runner.invoke(app, ["--format", "rich", "hook", "status"])
    assert result.exit_code == 0


@patch("gcpath.cli.clear_cache", return_value=True)
def test_cache_clear_rich(mock_clear):
    result = runner.invoke(app, ["--format", "rich", "cache", "clear"])
    assert result.exit_code == 0
    mock_clear.assert_called_once()


@patch("gcpath.cli.clear_cache", return_value=False)
def test_cache_clear_no_file(mock_clear):
    result = runner.invoke(app, ["cache", "clear"])
    assert result.exit_code == 0


@patch("gcpath.cli.clear_cache", return_value=False)
def test_cache_clear_no_file_rich(mock_clear):
    result = runner.invoke(app, ["--format", "rich", "cache", "clear"])
    assert result.exit_code == 0


@patch("gcpath.cli.get_cache_info")
def test_cache_status_rich(mock_info):
    mock_info.return_value = CacheInfo(
        exists=True, fresh=True, age_seconds=60.0, size_bytes=4096,
        version=1, org_count=1, folder_count=3, project_count=5,
    )
    result = runner.invoke(app, ["--format", "rich", "cache", "status"])
    assert result.exit_code == 0


@patch("gcpath.cli.get_cache_info")
def test_cache_status_rich_no_cache(mock_info):
    mock_info.return_value = CacheInfo(
        exists=False, fresh=False, age_seconds=None, size_bytes=None,
        version=None, org_count=0, folder_count=0, project_count=0,
    )
    result = runner.invoke(app, ["--format", "rich", "cache", "status"])
    assert result.exit_code == 0


@patch("gcpath.cli.read_config", return_value={"entrypoint": "folders/123"})
def test_config_show_rich(mock_read):
    result = runner.invoke(app, ["--format", "rich", "config", "show"])
    assert result.exit_code == 0
    mock_read.assert_called_once()


@patch("gcpath.cli.read_config", return_value={})
def test_config_show_empty_rich(mock_read):
    result = runner.invoke(app, ["--format", "rich", "config", "show"])
    assert result.exit_code == 0


@patch("gcpath.cli.clear_entrypoint")
def test_config_clear_entrypoint_rich(mock_clear):
    result = runner.invoke(app, ["--format", "rich", "config", "clear-entrypoint"])
    assert result.exit_code == 0
    mock_clear.assert_called_once()


@patch("gcpath.cli.set_entrypoint")
def test_config_set_entrypoint_rich(mock_set):
    result = runner.invoke(app, ["--format", "rich", "config", "set-entrypoint", "folders/123"])
    assert result.exit_code == 0
    mock_set.assert_called_once_with("folders/123")


@patch("gcpath.cli.set_entrypoint", side_effect=ValueError("bad"))
def test_config_set_entrypoint_invalid_rich(mock_set):
    result = runner.invoke(app, ["--format", "rich", "config", "set-entrypoint", "invalid"])
    assert result.exit_code == 1


@patch("gcpath.core.Hierarchy.resolve_ancestry_chain")
def test_ancestors_rich(mock_chain):
    mock_chain.return_value = [
        ("organizations/123", "example.com", "organization"),
        ("folders/456", "eng", "folder"),
    ]
    result = runner.invoke(app, ["--format", "rich", "ancestors", "folders/456"])
    assert result.exit_code == 0
    mock_chain.assert_called_once()


@patch("gcpath.core.Hierarchy.resolve_ancestry_chain")
def test_ancestors_yaml(mock_chain):
    mock_chain.return_value = [
        ("organizations/123", "example.com", "organization"),
    ]
    result = runner.invoke(app, ["--format", "yaml", "ancestors", "organizations/123"])
    assert result.exit_code == 0
    data = yaml.safe_load(result.stdout)
    assert data[0]["resource_name"] == "organizations/123"


@patch("gcpath.core.Hierarchy.load")
def test_find_rich_format(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["--format", "rich", "find", "f*"])
    assert result.exit_code == 0
