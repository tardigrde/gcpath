"""
Display formatting utilities for gcpath CLI.

This module handles path formatting, resource filtering, tree visualization,
and diagram generation (Mermaid, D2).
"""

from typing import List, Dict, Tuple, Union, Optional, Any
from gcpath.core import OrganizationNode, Folder, Project, path_escape


def filter_direct_children(
    hierarchy, target_resource_name: Optional[str] = None
) -> Tuple[List[Folder], List[Project]]:
    """Filter hierarchy to get direct children of a target resource.

    Args:
        hierarchy: The loaded Hierarchy object
        target_resource_name: Resource name to get children of (or None for org-level)

    Returns:
        Tuple of (folders, projects) that are direct children
    """
    current_folders = []
    current_projects = []

    if target_resource_name:
        # Find direct children of the target resource
        for f in hierarchy.folders:
            if f.parent == target_resource_name:
                current_folders.append(f)
        for p in hierarchy.projects:
            if p.parent == target_resource_name:
                current_projects.append(p)
    else:
        # No target: show org-level resources
        for org in hierarchy.organizations:
            for f in org.folders.values():
                if f.parent == org.organization.name:
                    current_folders.append(f)
        for p in hierarchy.projects:
            if p.organization and p.parent == p.organization.organization.name:
                current_projects.append(p)
        # Add organizationless projects
        current_projects.extend([p for p in hierarchy.projects if not p.organization])

    return current_folders, current_projects


def get_display_path(
    item: Union[OrganizationNode, Folder, Project],
    target_path_prefix: str = "",
    target_resource_name: Optional[str] = None,
    is_direct_child: bool = False,
    recursive: bool = False,
) -> str:
    """Build display path for an item.

    Args:
        item: The resource to get path for
        target_path_prefix: Path prefix when targeting a specific resource
        target_resource_name: Resource name being targeted
        is_direct_child: Whether this item is a direct child of the target
        recursive: Whether in recursive mode

    Returns:
        Formatted path string for display
    """
    if isinstance(item, OrganizationNode):
        return f"//{path_escape(item.organization.display_name)}"
    elif isinstance(item, Folder):
        # For non-recursive mode with direct children, use target prefix
        # For recursive mode, always use the computed path from hierarchy
        if (
            target_path_prefix
            and target_resource_name
            and is_direct_child
            and not recursive
        ):
            return f"{target_path_prefix}/{path_escape(item.display_name)}"
        return item.path
    elif isinstance(item, Project):
        # For non-recursive mode with direct children, use target prefix
        # For recursive mode, always use the computed path from hierarchy
        if (
            target_path_prefix
            and target_resource_name
            and is_direct_child
            and not recursive
        ):
            return f"{target_path_prefix}/{path_escape(item.display_name)}"
        return item.path
    return ""


def build_items_list(
    hierarchy,
    current_folders: List[Folder],
    current_projects: List[Project],
    target_path_prefix: str = "",
    target_resource_name: Optional[str] = None,
    recursive: bool = False,
) -> List[Tuple[str, Union[OrganizationNode, Folder, Project]]]:
    """Build list of items for display with their paths.

    Args:
        hierarchy: The loaded Hierarchy object
        current_folders: Folders to display (direct children)
        current_projects: Projects to display (direct children)
        target_path_prefix: Path prefix when targeting a specific resource
        target_resource_name: Resource name being targeted
        recursive: Whether in recursive mode

    Returns:
        List of (path, resource) tuples
    """
    items: List[Tuple[str, Union[OrganizationNode, Folder, Project]]] = []

    if recursive:
        # Recursive listing - list everything under the target
        if target_resource_name:
            # All loaded folders and projects are descendants
            for f in hierarchy.folders:
                items.append(
                    (
                        get_display_path(
                            f,
                            target_path_prefix,
                            target_resource_name,
                            is_direct_child=False,
                            recursive=True,
                        ),
                        f,
                    )
                )
            for p in hierarchy.projects:
                items.append(
                    (
                        get_display_path(
                            p,
                            target_path_prefix,
                            target_resource_name,
                            is_direct_child=False,
                            recursive=True,
                        ),
                        p,
                    )
                )
        else:
            # Full recursive list
            for org in hierarchy.organizations:
                items.append(
                    (
                        get_display_path(
                            org,
                            target_path_prefix,
                            target_resource_name,
                            is_direct_child=False,
                            recursive=True,
                        ),
                        org,
                    )
                )
                for f in org.folders.values():
                    items.append(
                        (
                            get_display_path(
                                f,
                                target_path_prefix,
                                target_resource_name,
                                is_direct_child=False,
                                recursive=True,
                            ),
                            f,
                        )
                    )
            for p in hierarchy.projects:
                items.append(
                    (
                        get_display_path(
                            p,
                            target_path_prefix,
                            target_resource_name,
                            is_direct_child=False,
                            recursive=True,
                        ),
                        p,
                    )
                )
    else:
        # Non-recursive - only direct children
        if not target_resource_name:
            for org in hierarchy.organizations:
                items.append(
                    (
                        get_display_path(
                            org,
                            target_path_prefix,
                            target_resource_name,
                            is_direct_child=False,
                            recursive=False,
                        ),
                        org,
                    )
                )

        for f in current_folders:
            items.append(
                (
                    get_display_path(
                        f,
                        target_path_prefix,
                        target_resource_name,
                        is_direct_child=True,
                        recursive=False,
                    ),
                    f,
                )
            )
        for p in current_projects:
            items.append(
                (
                    get_display_path(
                        p,
                        target_path_prefix,
                        target_resource_name,
                        is_direct_child=True,
                        recursive=False,
                    ),
                    p,
                )
            )

    return items


def sort_resources(items: List[Tuple[str, Any]]) -> List[Tuple[str, Any]]:
    """Sort resources by path.

    Args:
        items: List of (path, resource) tuples

    Returns:
        Sorted list of (path, resource) tuples
    """
    return sorted(items, key=lambda x: x[0])


def format_tree_label(item: Union[Folder, Project], show_ids: bool = False) -> str:
    """Format label for tree display.

    Args:
        item: The resource to format
        show_ids: Whether to include resource IDs

    Returns:
        Formatted label string with rich markup
    """
    if isinstance(item, Folder):
        label = f"[bold blue]{item.display_name}[/bold blue]"
        if show_ids:
            label += f" [dim]({item.name})[/dim]"
        return label
    elif isinstance(item, Project):
        label = f"[green]{item.display_name}[/green]"
        if show_ids:
            label += f" [dim]({item.name})[/dim]"
        return label
    return ""


def build_tree_view(
    tree_node,
    current_node: Union[OrganizationNode, Folder],
    hierarchy,
    projects_by_parent: Dict[str, List[Project]],
    level: Optional[int] = None,
    current_depth: int = 0,
    show_ids: bool = False,
):
    """Recursively build tree view of resources.

    Args:
        tree_node: Rich Tree node to add children to
        current_node: Current resource node being processed
        hierarchy: The loaded Hierarchy object
        projects_by_parent: Dict mapping parent names to project lists
        level: Maximum depth to display (None for unlimited)
        current_depth: Current depth in the tree
        show_ids: Whether to show resource IDs
    """
    if level is not None and current_depth >= level:
        return

    parent_name = (
        current_node.name
        if hasattr(current_node, "name")
        else current_node.organization.name
    )

    # Projects
    children_projects = projects_by_parent.get(parent_name, [])
    children_projects.sort(key=lambda x: x.display_name)

    # Folders - find direct children using the parent field
    children_folders = []
    org_node_ref = (
        current_node
        if isinstance(current_node, OrganizationNode)
        else current_node.organization
    )

    if org_node_ref:
        for f in org_node_ref.folders.values():
            # Use the parent field to find direct children
            if f.parent == parent_name:
                children_folders.append(f)

    children_folders.sort(key=lambda x: x.display_name)

    for f in children_folders:
        label = format_tree_label(f, show_ids)
        sub_node = tree_node.add(label)
        build_tree_view(
            sub_node,
            f,
            hierarchy,
            projects_by_parent,
            level,
            current_depth + 1,
            show_ids,
        )

    for p in children_projects:
        label = format_tree_label(p, show_ids)
        tree_node.add(label)


# --- Diagram generation (Mermaid / D2) ---


def _sanitize_node_id(resource_name: str) -> str:
    """Convert a GCP resource name to a valid diagram node ID.

    Both Mermaid and D2 work best with simple alphanumeric + underscore IDs.
    """
    return resource_name.replace("/", "_").replace(".", "_").replace("-", "_")


def _get_node_label(
    item: Union[OrganizationNode, Folder, Project], show_ids: bool = False
) -> str:
    """Get display label for a diagram node."""
    if isinstance(item, OrganizationNode):
        label = f"//{path_escape(item.organization.display_name)}"
        if show_ids:
            label += f" ({item.organization.name})"
    elif isinstance(item, Folder):
        label = item.display_name
        if show_ids:
            label += f" ({item.name})"
    elif isinstance(item, Project):
        label = item.display_name
        if show_ids:
            label += f" ({item.name})"
    else:
        label = str(item)
    return label


def _collect_diagram_edges(
    parent_id: str,
    current_node: Union[OrganizationNode, Folder],
    hierarchy: Any,
    projects_by_parent: Dict[str, List[Project]],
    edges: List[Tuple[str, str]],
    labels: Dict[str, str],
    level: Optional[int] = None,
    current_depth: int = 0,
    show_ids: bool = False,
) -> None:
    """Recursively collect edges and node labels from the hierarchy."""
    if level is not None and current_depth >= level:
        return

    parent_name = (
        current_node.name
        if hasattr(current_node, "name") and not isinstance(current_node, OrganizationNode)
        else current_node.organization.name
        if isinstance(current_node, OrganizationNode)
        else ""
    )

    # Find child folders
    children_folders: List[Folder] = []
    org_node_ref = (
        current_node
        if isinstance(current_node, OrganizationNode)
        else current_node.organization
    )

    if org_node_ref:
        for f in org_node_ref.folders.values():
            if f.parent == parent_name:
                children_folders.append(f)

    children_folders.sort(key=lambda x: x.display_name)

    # Find child projects
    children_projects = sorted(
        projects_by_parent.get(parent_name, []), key=lambda x: x.display_name
    )

    for f in children_folders:
        child_id = _sanitize_node_id(f.name)
        labels[child_id] = _get_node_label(f, show_ids)
        edges.append((parent_id, child_id))
        _collect_diagram_edges(
            child_id,
            f,
            hierarchy,
            projects_by_parent,
            edges,
            labels,
            level,
            current_depth + 1,
            show_ids,
        )

    for p in children_projects:
        child_id = _sanitize_node_id(p.name)
        labels[child_id] = _get_node_label(p, show_ids)
        edges.append((parent_id, child_id))


def _format_mermaid(labels: Dict[str, str], edges: List[Tuple[str, str]]) -> str:
    """Format collected nodes and edges as a Mermaid flowchart."""
    lines = ["graph TD"]
    for node_id, label in labels.items():
        safe_label = label.replace('"', '#quot;')
        lines.append(f'    {node_id}["{safe_label}"]')
    for parent_id, child_id in edges:
        lines.append(f"    {parent_id} --> {child_id}")
    return "\n".join(lines)


def _format_d2(labels: Dict[str, str], edges: List[Tuple[str, str]]) -> str:
    """Format collected nodes and edges as a D2 diagram."""
    lines: List[str] = []
    for node_id, label in labels.items():
        lines.append(f'{node_id}: "{label}"')
    for parent_id, child_id in edges:
        lines.append(f"{parent_id} -> {child_id}")
    return "\n".join(lines)


def build_diagram(
    nodes_to_process: List[Union[OrganizationNode, Folder]],
    hierarchy: Any,
    projects_by_parent: Dict[str, List[Project]],
    fmt: str = "mermaid",
    level: Optional[int] = None,
    show_ids: bool = False,
    orgless_projects: Optional[List[Project]] = None,
) -> str:
    """Build a diagram string from hierarchy data.

    Args:
        nodes_to_process: Root nodes (organizations or folders) to include.
        hierarchy: The loaded Hierarchy object.
        projects_by_parent: Dict mapping parent resource names to project lists.
        fmt: Output format, either "mermaid" or "d2".
        level: Maximum depth to include (None for unlimited).
        show_ids: Whether to include resource IDs in labels.
        orgless_projects: Organizationless projects to include.

    Returns:
        Diagram source string in the requested format.
    """
    edges: List[Tuple[str, str]] = []
    # Use dict to preserve insertion order (Python 3.7+)
    labels: Dict[str, str] = {}

    for node in nodes_to_process:
        if isinstance(node, OrganizationNode):
            node_id = _sanitize_node_id(node.organization.name)
        else:
            node_id = _sanitize_node_id(node.name)

        labels[node_id] = _get_node_label(node, show_ids)
        _collect_diagram_edges(
            node_id,
            node,
            hierarchy,
            projects_by_parent,
            edges,
            labels,
            level,
            0,
            show_ids,
        )

    # Organizationless projects
    if orgless_projects:
        orgless_id = "organizationless"
        labels[orgless_id] = "(organizationless)"
        for p in sorted(orgless_projects, key=lambda x: x.display_name):
            child_id = _sanitize_node_id(p.name)
            labels[child_id] = _get_node_label(p, show_ids)
            edges.append((orgless_id, child_id))

    if fmt == "mermaid":
        return _format_mermaid(labels, edges)
    elif fmt == "d2":
        return _format_d2(labels, edges)
    else:
        raise ValueError(f"Unsupported diagram format: {fmt}")
