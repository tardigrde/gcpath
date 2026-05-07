"""
Display formatting utilities for gcpath CLI.

This module handles path formatting, resource filtering, tree visualization,
and diagram generation (Mermaid, D2).
"""

from typing import List, Dict, Tuple, Union, Optional, Any
from gcpath.core import (
    OrganizationNode,
    Folder,
    Project,
    SYNTHETIC_ORG_NAME,
    path_escape,
    Hierarchy,
    GCPathError,
)


_CONSOLE_BASE = "https://console.cloud.google.com"


def console_url(item: Union[OrganizationNode, Folder, Project]) -> str:
    """Build a GCP Cloud Console URL for a hierarchy resource.

    Raises GCPathError for organizationless projects or synthetic-org folders
    (these have no stable console URL).
    """
    if isinstance(item, OrganizationNode):
        org_name = item.organization.name
        if org_name == SYNTHETIC_ORG_NAME:
            raise GCPathError(
                "Synthetic organization has no GCP Console URL"
            )
        org_id = org_name.split("/", 1)[-1]
        return f"{_CONSOLE_BASE}/welcome?organizationId={org_id}"

    if isinstance(item, Folder):
        org_name = item.organization.organization.name
        if org_name == SYNTHETIC_ORG_NAME:
            raise GCPathError(
                "Folder under synthetic organization has no GCP Console URL"
            )
        folder_id = item.name.split("/", 1)[-1]
        return f"{_CONSOLE_BASE}/welcome?folder={folder_id}"

    if isinstance(item, Project):
        if item.organization is None and item.folder is None:
            raise GCPathError(
                f"Organizationless project '{item.project_id}' has no console URL via gcpath"
            )
        return f"{_CONSOLE_BASE}/welcome?project={item.project_id}"

    raise GCPathError(f"Cannot build console URL for {type(item).__name__}")


def _children_of_target(
    hierarchy: Hierarchy, target: str
) -> Tuple[List[Folder], List[Project]]:
    """Return folders and projects whose parent matches the target resource."""
    folders = [f for f in hierarchy.folders if f.parent == target]
    projects = [p for p in hierarchy.projects if p.parent == target]
    return folders, projects


def _org_level_children(
    hierarchy: Hierarchy,
) -> Tuple[List[Folder], List[Project]]:
    """Return org-level folders and projects (including organizationless)."""
    org_names = {org.organization.name for org in hierarchy.organizations}
    folders = [
        f
        for org in hierarchy.organizations
        for f in org.folders.values()
        if f.parent == org.organization.name
    ]
    projects = [
        p
        for p in hierarchy.projects
        if (p.organization and p.parent in org_names) or not p.organization
    ]
    return folders, projects


def filter_direct_children(
    hierarchy: Hierarchy, target_resource_name: Optional[str] = None
) -> Tuple[List[Folder], List[Project]]:
    """Filter hierarchy to get direct children of a target resource.

    Args:
        hierarchy: The loaded Hierarchy object
        target_resource_name: Resource name to get children of (or None for org-level)

    Returns:
        Tuple of (folders, projects) that are direct children
    """
    if target_resource_name:
        return _children_of_target(hierarchy, target_resource_name)
    return _org_level_children(hierarchy)


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
    elif isinstance(item, (Folder, Project)):
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


def _collect_recursive_items(
    hierarchy: Hierarchy,
    target_path_prefix: str,
    target_resource_name: Optional[str],
) -> List[Tuple[str, Union[OrganizationNode, Folder, Project]]]:
    """Collect all items for recursive listing."""

    def _path(item, is_direct=False):
        return get_display_path(
            item, target_path_prefix, target_resource_name, is_direct, True
        )

    items: List[Tuple[str, Union[OrganizationNode, Folder, Project]]] = []
    if target_resource_name:
        items.extend((_path(f), f) for f in hierarchy.folders)
        items.extend((_path(p), p) for p in hierarchy.projects)
    else:
        for org in hierarchy.organizations:
            items.append((_path(org), org))
            items.extend((_path(f), f) for f in org.folders.values())
        items.extend((_path(p), p) for p in hierarchy.projects)
    return items


def _collect_nonrecursive_items(
    hierarchy: Hierarchy,
    current_folders: List[Folder],
    current_projects: List[Project],
    target_path_prefix: str,
    target_resource_name: Optional[str],
) -> List[Tuple[str, Union[OrganizationNode, Folder, Project]]]:
    """Collect items for non-recursive (direct children) listing."""

    def _path(item, is_direct=False):
        return get_display_path(
            item, target_path_prefix, target_resource_name, is_direct, False
        )

    items: List[Tuple[str, Union[OrganizationNode, Folder, Project]]] = []
    if not target_resource_name:
        items.extend((_path(org), org) for org in hierarchy.organizations)
    items.extend((_path(f, True), f) for f in current_folders)
    items.extend((_path(p, True), p) for p in current_projects)
    return items


def build_items_list(
    hierarchy: Hierarchy,
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
    if recursive:
        return _collect_recursive_items(
            hierarchy, target_path_prefix, target_resource_name
        )
    return _collect_nonrecursive_items(
        hierarchy,
        current_folders,
        current_projects,
        target_path_prefix,
        target_resource_name,
    )


def sort_resources(items: List[Tuple[str, Any]]) -> List[Tuple[str, Any]]:
    """Sort resources by path.

    Args:
        items: List of (path, resource) tuples

    Returns:
        Sorted list of (path, resource) tuples
    """
    return sorted(items, key=lambda x: x[0])


def _format_metadata_suffix(
    item: Union[Folder, Project],
    show_labels: bool = False,
    show_tags: bool = False,
) -> str:
    """Build a Rich markup suffix for labels and tags."""
    parts = []
    if show_labels and hasattr(item, "labels") and item.labels:
        label_str = ", ".join(f"{k}={v}" for k, v in sorted(item.labels.items()))
        parts.append(f"[dim]labels: {label_str}[/dim]")
    if show_tags and hasattr(item, "tags") and item.tags:
        tag_str = ", ".join(f"{k}={v}" for k, v in sorted(item.tags.items()))
        parts.append(f"[dim]tags: {tag_str}[/dim]")
    if not parts:
        return ""
    return " [" + " | ".join(parts) + "]"


def format_tree_label(
    item: Union[Folder, Project],
    show_ids: bool = False,
    show_labels: bool = False,
    show_tags: bool = False,
) -> str:
    """Format label for tree display.

    Args:
        item: The resource to format
        show_ids: Whether to include resource IDs
        show_labels: Whether to include GCP labels
        show_tags: Whether to include GCP tags

    Returns:
        Formatted label string with rich markup
    """
    if isinstance(item, Folder):
        label = f"[bold blue]{item.display_name}[/bold blue]"
        if show_ids:
            label += f" [dim]({item.name})[/dim]"
        label += _format_metadata_suffix(item, show_labels, show_tags)
        return label
    elif isinstance(item, Project):
        label = f"[green]{item.display_name}[/green]"
        if show_ids:
            label += f" [dim]({item.name})[/dim]"
        label += _format_metadata_suffix(item, show_labels, show_tags)
        return label
    return ""


def _get_node_parent_name(node: Union[OrganizationNode, Folder]) -> str:
    """Get the resource name used as parent key for a node."""
    if isinstance(node, OrganizationNode):
        return node.organization.name
    return node.name


def _get_child_folders(
    node: Union[OrganizationNode, Folder], parent_name: str
) -> List[Folder]:
    """Get sorted direct child folders of a node."""
    org_node_ref = node if isinstance(node, OrganizationNode) else node.organization
    if not org_node_ref:
        return []
    children = [f for f in org_node_ref.folders.values() if f.parent == parent_name]
    children.sort(key=lambda x: x.display_name)
    return children


def build_tree_view(
    tree_node,
    current_node: Union[OrganizationNode, Folder],
    hierarchy: Hierarchy,
    projects_by_parent: Dict[str, List[Project]],
    level: Optional[int] = None,
    current_depth: int = 0,
    show_ids: bool = False,
    type_filter: Optional[str] = None,
    show_labels: bool = False,
    show_tags: bool = False,
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
        type_filter: If set, only show resources of this type ("folder" or "project").
                     Folders are always recursed into to find matching descendants.
        show_labels: Whether to display GCP labels
        show_tags: Whether to display GCP tags
    """
    if level is not None and current_depth >= level:
        return

    parent_name = _get_node_parent_name(current_node)
    recurse_args = (
        hierarchy,
        projects_by_parent,
        level,
        current_depth + 1,
        show_ids,
        type_filter,
        show_labels,
        show_tags,
    )

    for f in _get_child_folders(current_node, parent_name):
        if type_filter == "project":
            build_tree_view(tree_node, f, *recurse_args)
        else:
            sub_node = tree_node.add(
                format_tree_label(f, show_ids, show_labels, show_tags)
            )
            build_tree_view(sub_node, f, *recurse_args)

    if type_filter != "folder":
        children_projects = sorted(
            projects_by_parent.get(parent_name, []), key=lambda x: x.display_name
        )
        for p in children_projects:
            tree_node.add(format_tree_label(p, show_ids, show_labels, show_tags))


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
    elif isinstance(item, (Folder, Project)):
        label = item.display_name
        if show_ids:
            label += f" ({item.name})"
    else:
        label = str(item)
    return label


def _collect_diagram_edges(
    parent_id: str,
    current_node: Union[OrganizationNode, Folder],
    hierarchy: Hierarchy,
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

    if isinstance(current_node, OrganizationNode):
        parent_name = current_node.organization.name
    else:
        parent_name = current_node.name

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
        safe_label = label.replace('"', "#quot;")
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
    hierarchy: Hierarchy,
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
