"""Structured output serialization for gcpath CLI.

Converts internal data structures to plain dicts suitable for JSON/YAML output.
"""

import json
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from gcpath.core import Folder, OrganizationNode, Project, path_escape


def resource_type(item: Union[OrganizationNode, Folder, Project]) -> str:
    """Return the type string for a resource."""
    if isinstance(item, OrganizationNode):
        return "organization"
    elif isinstance(item, Folder):
        return "folder"
    elif isinstance(item, Project):
        return "project"
    return "unknown"


def serialize_resource(
    path: str, item: Union[OrganizationNode, Folder, Project]
) -> Dict[str, Any]:
    """Serialize a single resource to a dict."""
    d: Dict[str, Any] = {
        "path": path,
        "type": resource_type(item),
    }

    if isinstance(item, OrganizationNode):
        d["resource_name"] = item.organization.name
        d["display_name"] = item.organization.display_name
    elif isinstance(item, Folder):
        d["resource_name"] = item.name
        d["display_name"] = item.display_name
    elif isinstance(item, Project):
        d["resource_name"] = item.name
        d["display_name"] = item.display_name
        d["project_id"] = item.project_id

    return d


def serialize_ls(
    items: List[Tuple[str, Union[OrganizationNode, Folder, Project]]],
) -> List[Dict[str, Any]]:
    """Serialize ls output to a list of dicts."""
    return [serialize_resource(path, item) for path, item in items]


def serialize_tree_node(
    node: Union[OrganizationNode, Folder],
    projects_by_parent: Dict[str, List[Project]],
    level: Optional[int] = None,
    current_depth: int = 0,
) -> Dict[str, Any]:
    """Recursively serialize a tree node to a dict with children."""
    if isinstance(node, OrganizationNode):
        parent_name = node.organization.name
        d: Dict[str, Any] = {
            "path": f"//{path_escape(node.organization.display_name)}",
            "resource_name": node.organization.name,
            "display_name": node.organization.display_name,
            "type": "organization",
        }
    else:
        parent_name = node.name
        d = {
            "path": node.path,
            "resource_name": node.name,
            "display_name": node.display_name,
            "type": "folder",
        }

    if level is not None and current_depth >= level:
        d["children"] = []
        return d

    children: List[Dict[str, Any]] = []

    # Child folders
    org_node_ref = (
        node if isinstance(node, OrganizationNode) else node.organization
    )
    children_folders: List[Folder] = []
    if org_node_ref:
        for f in org_node_ref.folders.values():
            if f.parent == parent_name:
                children_folders.append(f)
    children_folders.sort(key=lambda x: x.display_name)

    for f in children_folders:
        children.append(
            serialize_tree_node(
                f, projects_by_parent, level, current_depth + 1
            )
        )

    # Child projects
    children_projects = sorted(
        projects_by_parent.get(parent_name, []), key=lambda x: x.display_name
    )
    for p in children_projects:
        children.append(serialize_resource(p.path, p))

    d["children"] = children
    return d


def serialize_tree(
    nodes_to_process: List[Union[OrganizationNode, Folder]],
    projects_by_parent: Dict[str, List[Project]],
    level: Optional[int] = None,
    orgless_projects: Optional[List[Project]] = None,
) -> List[Dict[str, Any]]:
    """Top-level tree serialization."""
    result = []
    for node in nodes_to_process:
        result.append(
            serialize_tree_node(node, projects_by_parent, level)
        )

    if orgless_projects:
        orgless_children = []
        for p in sorted(orgless_projects, key=lambda x: x.display_name):
            orgless_children.append(serialize_resource(p.path, p))
        result.append(
            {
                "display_name": "(organizationless)",
                "type": "organizationless",
                "children": orgless_children,
            }
        )

    return result


def serialize_name_results(
    results: List[Tuple[str, str]], id_only: bool = False
) -> List[Dict[str, str]]:
    """Serialize name command results."""
    out = []
    for path, res_name in results:
        if id_only:
            out.append({"path": path, "resource_id": res_name.split("/")[-1]})
        else:
            out.append({"path": path, "resource_name": res_name})
    return out


def serialize_path_results(
    results: List[Tuple[str, str]],
) -> List[Dict[str, str]]:
    """Serialize path command results."""
    return [{"resource_name": name, "path": path} for name, path in results]


def dump_json(data: Any) -> str:
    """Serialize data to JSON string."""
    return json.dumps(data, indent=2, ensure_ascii=False)


def dump_yaml(data: Any) -> str:
    """Serialize data to YAML string."""
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
