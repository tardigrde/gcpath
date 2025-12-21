
import pytest
from typer.testing import CliRunner
from unittest.mock import patch
from gcpath.cli import app
from gcpath.core import Folder, OrganizationNode, Hierarchy, Project
from google.cloud import resourcemanager_v3

runner = CliRunner()

@pytest.fixture
def mock_hierarchy():
    org_proto = resourcemanager_v3.Organization(name="organizations/123", display_name="example.com")
    org_node = OrganizationNode(organization=org_proto)
    f1 = Folder(name="folders/1", display_name="f1", ancestors=["folders/1", "organizations/123"], organization=org_node)
    org_node.folders["folders/1"] = f1
    return Hierarchy([org_node], [])

@patch("gcpath.core.Hierarchy.load")
def test_ls_command(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "//example.com/f1" in result.stdout

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

@patch("gcpath.core.Hierarchy.load")
def test_path_command(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["path", "folders/1"])
    assert result.exit_code == 0
    assert "//example.com/f1" in result.stdout

@patch("gcpath.core.Hierarchy.load")
def test_ls_shows_projects(mock_load, mock_hierarchy):
    p1 = Project(name="projects/p1", project_id="p1", display_name="Project 1", parent="folders/1", organization=mock_hierarchy.organizations[0], folder=mock_hierarchy.organizations[0].folders["folders/1"])
    mock_hierarchy.projects.append(p1)
    mock_load.return_value = mock_hierarchy
    
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "//example.com/f1/Project%201" in result.stdout

@patch("gcpath.core.Hierarchy.load")
def test_ls_no_resources_message(mock_load):
    h = Hierarchy([], [])
    mock_load.return_value = h
    
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert "No organizations or projects found" in result.stdout

@patch("gcpath.core.Hierarchy.load")
def test_ls_long_format(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["ls", "-l"])
    assert result.exit_code == 0
    assert "//example.com/f1" in result.stdout
    assert "folders/1" in result.stdout

@patch("gcpath.core.Hierarchy.load")
def test_tree_command(mock_load, mock_hierarchy):
    mock_load.return_value = mock_hierarchy
    result = runner.invoke(app, ["tree"])
    assert result.exit_code == 0
    assert "example.com" in result.stdout
    assert "f1" in result.stdout
