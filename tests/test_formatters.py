"""Tests for formatters.py module."""

import pytest
from unittest.mock import MagicMock
from gcpath.core import OrganizationNode, Folder, Project
from gcpath.formatters import (
    filter_direct_children,
    get_display_path,
    build_items_list,
    sort_resources,
    format_tree_label,
    build_tree_view,
    build_diagram,
    _sanitize_node_id,
    _get_node_label,
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


@pytest.fixture
def mock_folder(mock_org_node):
    return Folder(
        name="folders/456",
        display_name="TestFolder",
        ancestors=["folders/456", "organizations/123"],
        organization=mock_org_node,
        parent="organizations/123",
    )


@pytest.fixture
def mock_project(mock_org_node):
    return Project(
        name="projects/789",
        project_id="test-project",
        display_name="TestProject",
        parent="folders/456",
        organization=mock_org_node,
        folder=None,
    )


@pytest.fixture
def mock_hierarchy(mock_org_node, mock_folder, mock_project):
    """Create a mock hierarchy with org, folder, and project."""
    mock_org_node.folders = {"folders/456": mock_folder}

    hierarchy = MagicMock()
    hierarchy.organizations = [mock_org_node]
    hierarchy.folders = [mock_folder]
    hierarchy.projects = [mock_project]

    return hierarchy


# Test filter_direct_children
def test_filter_direct_children_org_level(mock_hierarchy, mock_folder, mock_project):
    """Test filtering at organization level."""
    # Update mocks to match org-level filtering
    mock_project.parent = "organizations/123"
    mock_project.organization = mock_hierarchy.organizations[0]

    folders, projects = filter_direct_children(mock_hierarchy, None)

    # Folder with parent=organizations/123 should be included
    assert len(folders) == 1
    assert folders[0].name == "folders/456"

    # Project with parent=organizations/123 should be included
    assert len(projects) == 1
    assert projects[0].name == "projects/789"


def test_filter_direct_children_folder_level(mock_hierarchy, mock_project):
    """Test filtering at folder level."""
    folders, projects = filter_direct_children(mock_hierarchy, "folders/456")

    # No folders with parent=folders/456
    assert len(folders) == 0

    # Project with parent=folders/456 should be included
    assert len(projects) == 1
    assert projects[0].name == "projects/789"


def test_filter_direct_children_organizationless(mock_org_node):
    """Test that organizationless projects are included at org level."""
    hierarchy = MagicMock()
    hierarchy.organizations = [mock_org_node]
    hierarchy.folders = []

    orgless_project = Project(
        name="projects/orgless",
        project_id="orgless",
        display_name="Orgless",
        parent="external/0",
        organization=None,
        folder=None,
    )
    hierarchy.projects = [orgless_project]

    folders, projects = filter_direct_children(hierarchy, None)

    assert len(projects) == 1
    assert projects[0].name == "projects/orgless"


# Test get_display_path
def test_get_display_path_org(mock_org_node):
    """Test display path for organization."""
    path = get_display_path(mock_org_node)
    assert path == "//example.com"


def test_get_display_path_folder(mock_folder):
    """Test display path for folder."""
    # The path property is computed from organization and ancestors
    path = get_display_path(mock_folder)
    # Should return the computed path
    assert path == mock_folder.path


def test_get_display_path_folder_with_prefix(mock_folder):
    """Test display path for folder with target prefix (non-recursive direct child)."""
    path = get_display_path(
        mock_folder,
        target_path_prefix="//example.com/Parent",
        target_resource_name="folders/parent",
        is_direct_child=True,
        recursive=False,
    )
    assert path == "//example.com/Parent/TestFolder"


def test_get_display_path_project(mock_project):
    """Test display path for project."""
    # The path property is computed from organization and parent
    path = get_display_path(mock_project)
    # Should return the computed path
    assert path == mock_project.path


# Test build_items_list
def test_build_items_list_non_recursive(mock_hierarchy):
    """Test building items list for non-recursive mode."""
    folders, projects = filter_direct_children(mock_hierarchy, "folders/456")

    items = build_items_list(
        mock_hierarchy,
        folders,
        projects,
        target_path_prefix="//example.com/TestFolder",
        target_resource_name="folders/456",
        recursive=False,
    )

    # Should have 1 project
    assert len(items) == 1
    assert items[0][1].name == "projects/789"


def test_build_items_list_recursive(mock_hierarchy):
    """Test building items list for recursive mode."""
    items = build_items_list(
        mock_hierarchy,
        [],
        [],
        target_path_prefix="",
        target_resource_name="organizations/123",
        recursive=True,
    )

    # Should have all folders and projects
    assert len(items) == 2  # 1 folder + 1 project


def test_build_items_list_org_level_with_orgs(mock_hierarchy):
    """Test building items list at org level includes organizations."""
    folders, projects = filter_direct_children(mock_hierarchy, None)

    # Note: paths are computed properties, not set directly
    items = build_items_list(
        mock_hierarchy,
        folders,
        projects,
        target_path_prefix="",
        target_resource_name=None,
        recursive=False,
    )

    # Should have org + folders + projects
    assert len(items) >= 1  # At least the org


# Test sort_resources
def test_sort_resources():
    """Test sorting resources by path."""
    items = [
        ("//example.com/zebra", None),
        ("//example.com/alpha", None),
        ("//example.com/beta", None),
    ]

    sorted_items = sort_resources(items)

    assert sorted_items[0][0] == "//example.com/alpha"
    assert sorted_items[1][0] == "//example.com/beta"
    assert sorted_items[2][0] == "//example.com/zebra"


# Test format_tree_label
def test_format_tree_label_folder(mock_folder):
    """Test formatting folder label without IDs."""
    label = format_tree_label(mock_folder, show_ids=False)
    assert "TestFolder" in label
    assert "folders/456" not in label


def test_format_tree_label_folder_with_ids(mock_folder):
    """Test formatting folder label with IDs."""
    label = format_tree_label(mock_folder, show_ids=True)
    assert "TestFolder" in label
    assert "folders/456" in label


def test_format_tree_label_project(mock_project):
    """Test formatting project label without IDs."""
    label = format_tree_label(mock_project, show_ids=False)
    assert "TestProject" in label
    assert "projects/789" not in label


def test_format_tree_label_project_with_ids(mock_project):
    """Test formatting project label with IDs."""
    label = format_tree_label(mock_project, show_ids=True)
    assert "TestProject" in label
    assert "projects/789" in label


# Test build_tree_view
def test_build_tree_view_simple(
    mock_org_node, mock_folder, mock_project, mock_hierarchy
):
    """Test building a simple tree view."""
    from rich.tree import Tree

    # Setup folders in org
    mock_org_node.folders = {"folders/456": mock_folder}

    # Create projects_by_parent mapping
    projects_by_parent = {"folders/456": [mock_project]}

    # Create root tree node
    root = Tree("Test")

    # Build tree view
    build_tree_view(
        root,
        mock_org_node,
        mock_hierarchy,
        projects_by_parent,
        level=None,
        current_depth=0,
        show_ids=False,
    )

    # Verify tree was built (has children)
    assert len(root.children) > 0


def test_build_tree_view_with_level_limit(mock_org_node, mock_hierarchy):
    """Test building tree view with depth limit."""
    from rich.tree import Tree

    projects_by_parent = {}
    root = Tree("Test")

    # Build with level=0 (should not add any children)
    build_tree_view(
        root,
        mock_org_node,
        mock_hierarchy,
        projects_by_parent,
        level=0,
        current_depth=0,
        show_ids=False,
    )

    # With level=0, no children should be added
    assert len(root.children) == 0


# Test diagram helpers
def test_sanitize_node_id():
    """Test node ID sanitization."""
    assert _sanitize_node_id("organizations/123") == "organizations_123"
    assert _sanitize_node_id("folders/456") == "folders_456"
    assert _sanitize_node_id("projects/my-project") == "projects_my_project"
    assert _sanitize_node_id("organizations/example.com") == "organizations_example_com"


def test_get_node_label_org(mock_org_node):
    """Test node label for organization."""
    label = _get_node_label(mock_org_node)
    assert label == "//example.com"


def test_get_node_label_org_with_ids(mock_org_node):
    """Test node label for organization with IDs."""
    label = _get_node_label(mock_org_node, show_ids=True)
    assert "//example.com" in label
    assert "organizations/123" in label


def test_get_node_label_folder(mock_folder):
    """Test node label for folder."""
    label = _get_node_label(mock_folder)
    assert label == "TestFolder"


def test_get_node_label_folder_with_ids(mock_folder):
    """Test node label for folder with IDs."""
    label = _get_node_label(mock_folder, show_ids=True)
    assert "TestFolder" in label
    assert "folders/456" in label


def test_get_node_label_project(mock_project):
    """Test node label for project."""
    label = _get_node_label(mock_project)
    assert label == "TestProject"


def test_get_node_label_project_with_ids(mock_project):
    """Test node label for project with IDs."""
    label = _get_node_label(mock_project, show_ids=True)
    assert "TestProject" in label
    assert "projects/789" in label


# Test Mermaid diagram generation
def test_build_diagram_mermaid(mock_org_node, mock_folder, mock_project, mock_hierarchy):
    """Test Mermaid diagram generation."""
    mock_org_node.folders = {"folders/456": mock_folder}
    projects_by_parent = {"folders/456": [mock_project]}

    result = build_diagram(
        [mock_org_node],
        mock_hierarchy,
        projects_by_parent,
        fmt="mermaid",
    )

    assert result.startswith("graph TD")
    assert "organizations_123" in result
    assert "folders_456" in result
    assert "projects_789" in result
    assert "-->" in result
    assert "example.com" in result
    assert "TestFolder" in result
    assert "TestProject" in result


def test_build_diagram_d2(mock_org_node, mock_folder, mock_project, mock_hierarchy):
    """Test D2 diagram generation."""
    mock_org_node.folders = {"folders/456": mock_folder}
    projects_by_parent = {"folders/456": [mock_project]}

    result = build_diagram(
        [mock_org_node],
        mock_hierarchy,
        projects_by_parent,
        fmt="d2",
    )

    assert "graph TD" not in result
    assert "organizations_123" in result
    assert "folders_456" in result
    assert "projects_789" in result
    assert "->" in result
    assert "example.com" in result
    assert "TestFolder" in result
    assert "TestProject" in result


def test_build_diagram_with_ids(mock_org_node, mock_folder, mock_project, mock_hierarchy):
    """Test diagram generation with resource IDs in labels."""
    mock_org_node.folders = {"folders/456": mock_folder}
    projects_by_parent = {"folders/456": [mock_project]}

    result = build_diagram(
        [mock_org_node],
        mock_hierarchy,
        projects_by_parent,
        fmt="mermaid",
        show_ids=True,
    )

    assert "(organizations/123)" in result
    assert "(folders/456)" in result
    assert "(projects/789)" in result


def test_build_diagram_with_level_limit(
    mock_org_node, mock_folder, mock_project, mock_hierarchy
):
    """Test diagram generation with depth limit."""
    mock_org_node.folders = {"folders/456": mock_folder}
    projects_by_parent = {"folders/456": [mock_project]}

    # Level 0 should only include the root node
    result = build_diagram(
        [mock_org_node],
        mock_hierarchy,
        projects_by_parent,
        fmt="mermaid",
        level=0,
    )

    assert "organizations_123" in result
    # Children should not appear
    assert "folders_456" not in result
    assert "projects_789" not in result


def test_build_diagram_orgless_projects(mock_org_node, mock_hierarchy):
    """Test diagram includes organizationless projects."""
    mock_org_node.folders = {}

    orgless_project = Project(
        name="projects/orgless",
        project_id="orgless",
        display_name="Orgless",
        parent="external/0",
        organization=None,
        folder=None,
    )

    result = build_diagram(
        [mock_org_node],
        mock_hierarchy,
        {},
        fmt="mermaid",
        orgless_projects=[orgless_project],
    )

    assert "organizationless" in result
    assert "projects_orgless" in result
    assert "Orgless" in result


def test_build_diagram_unsupported_format(mock_org_node, mock_hierarchy):
    """Test that unsupported format raises ValueError."""
    with pytest.raises(ValueError, match="Unsupported diagram format"):
        build_diagram(
            [mock_org_node],
            mock_hierarchy,
            {},
            fmt="graphviz",
        )


def test_build_diagram_folder_root(mock_org_node, mock_folder, mock_project, mock_hierarchy):
    """Test diagram generation with a folder as root node."""
    mock_org_node.folders = {"folders/456": mock_folder}
    projects_by_parent = {"folders/456": [mock_project]}

    result = build_diagram(
        [mock_folder],
        mock_hierarchy,
        projects_by_parent,
        fmt="d2",
    )

    assert "folders_456" in result
    assert "TestFolder" in result
    assert "projects_789" in result
    assert "TestProject" in result
