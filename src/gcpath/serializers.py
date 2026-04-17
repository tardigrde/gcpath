"""Structured output serialization for gcpath CLI.

Converts internal data structures to plain dicts suitable for
JSON, YAML, or TOON output.
"""

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import yaml

from gcpath.core import Folder, OrganizationNode, Project, path_escape
from gcpath.toon import (
    toon_encode,
    toon_object,
    toon_table,
    toon_empty,
    with_help,
    format_age,
)


def resource_type(item: Union[OrganizationNode, Folder, Project]) -> str:
    if isinstance(item, OrganizationNode):
        return "organization"
    elif isinstance(item, Folder):
        return "folder"
    elif isinstance(item, Project):
        return "project"
    return "unknown"


_DEFAULT_LS_FIELDS = ("path", "type", "display_name")
_PROJECT_LS_FIELDS = ("path", "type", "display_name", "project_id")

_ALL_LS_FIELDS = (
    "path",
    "type",
    "display_name",
    "resource_name",
    "project_id",
    "labels",
    "tags",
)


def _default_fields_for_items(
    items: List[Tuple[str, Union[OrganizationNode, Folder, Project]]],
) -> Tuple[str, ...]:
    has_projects = any(isinstance(obj, Project) for _, obj in items)
    return _PROJECT_LS_FIELDS if has_projects else _DEFAULT_LS_FIELDS


def _truncate_metadata(
    metadata: Dict[str, str], limit: int = 5, full: bool = False
) -> Dict[str, str]:
    if full or len(metadata) <= limit:
        return metadata
    shown = dict(sorted(metadata.items())[:limit])
    remaining = len(metadata) - limit
    shown["..."] = f"{remaining} more (use --full to see all)"
    return shown


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
        if item.labels:
            d["labels"] = item.labels
        if item.tags:
            d["tags"] = item.tags
    elif isinstance(item, Project):
        d["resource_name"] = item.name
        d["display_name"] = item.display_name
        d["project_id"] = item.project_id
        if item.labels:
            d["labels"] = item.labels
        if item.tags:
            d["tags"] = item.tags

    return d


def _serialize_resource_fields(
    path: str,
    item: Union[OrganizationNode, Folder, Project],
    fields: Sequence[str],
    full: bool = False,
) -> Dict[str, Any]:
    full_resource = serialize_resource(path, item)
    result: Dict[str, Any] = {}
    for f in fields:
        val = full_resource.get(f, "")
        if f in ("labels", "tags") and isinstance(val, dict):
            val = _truncate_metadata(val, full=full)
        result[f] = val
    return result


def serialize_ls(
    items: List[Tuple[str, Union[OrganizationNode, Folder, Project]]],
) -> List[Dict[str, Any]]:
    return [serialize_resource(path, item) for path, item in items]


def toon_ls(
    items: List[Tuple[str, Union[OrganizationNode, Folder, Project]]],
    total_in_scope: int,
    fields: Optional[Sequence[str]] = None,
    full: bool = False,
    help_lines: Optional[List[str]] = None,
) -> str:
    if not items:
        empty_data: Dict[str, Any] = {
            "count": f"0 of {total_in_scope} total",
            "resources": [],
        }
        return with_help(toon_encode(empty_data), help_lines)

    effective_fields = tuple(fields) if fields else _default_fields_for_items(items)
    rows = [
        _serialize_resource_fields(p, obj, effective_fields, full=full)
        for p, obj in items
    ]
    data: Dict[str, Any] = {"count": f"{len(items)} of {total_in_scope} total"}
    data["resources"] = rows
    output = toon_encode(data)
    return with_help(output, help_lines)


def toon_name(
    results: List[Tuple[str, str]], id_only: bool = False
) -> str:
    if len(results) == 1:
        path, res_name = results[0]
        if id_only:
            return toon_object({"path": path, "resource_id": res_name.split("/")[-1]})
        return toon_object({"path": path, "resource_name": res_name})

    rows = []
    for path, res_name in results:
        if id_only:
            rows.append({"path": path, "resource_id": res_name.split("/")[-1]})
        else:
            rows.append({"path": path, "resource_name": res_name})
    return toon_table("results", rows, ("path", "resource_id" if id_only else "resource_name"))


def toon_path(
    results: List[Tuple[str, str]],
) -> str:
    if len(results) == 1:
        name, path = results[0]
        return toon_object({"resource_name": name, "path": path})

    rows = [{"resource_name": n, "path": p} for n, p in results]
    return toon_table("results", rows, ("resource_name", "path"))


def toon_ancestors(
    chain: List[Tuple[str, str, str]],
    help_lines: Optional[List[str]] = None,
) -> str:
    rows = [
        {"resource_name": name, "display_name": dn, "type": t}
        for name, dn, t in chain
    ]
    output = toon_table("ancestors", rows, ("resource_name", "display_name", "type"))
    return with_help(output, help_lines)


def toon_find(
    items: List[Tuple[str, Union[OrganizationNode, Folder, Project]]],
    pattern: str,
    total_searched: int = 0,
    fields: Optional[Sequence[str]] = None,
    full: bool = False,
    help_lines: Optional[List[str]] = None,
) -> str:
    if not items:
        empty_help = help_lines or [
            f"Run `gcpath find '{pattern}'` with a broader pattern"
        ]
        return toon_empty("resources", f"matching '{pattern}' found", empty_help)

    effective_fields = tuple(fields) if fields else _default_fields_for_items(items)
    rows = [
        _serialize_resource_fields(p, obj, effective_fields, full=full)
        for p, obj in items
    ]
    data: Dict[str, Any] = {"count": f"{len(items)} of {total_searched} searched"}
    data["resources"] = rows
    output = toon_encode(data)
    return with_help(output, help_lines)


def toon_stats(
    scope: str,
    organizations: int = 0,
    folders: int = 0,
    projects: int = 0,
    help_lines: Optional[List[str]] = None,
) -> str:
    data: Dict[str, Any] = {
        "scope": scope,
        "organizations": organizations,
        "folders": folders,
        "projects": projects,
    }
    output = toon_encode(data)
    return with_help(output, help_lines)


def toon_cache_status(
    exists: bool,
    fresh: bool,
    age_seconds: Optional[float] = None,
    size_bytes: Optional[int] = None,
    version: Optional[int] = None,
    scope: Optional[str] = None,
    org_count: int = 0,
    folder_count: int = 0,
    project_count: int = 0,
    location: str = "",
) -> str:
    if not exists:
        return toon_object({"cache": "empty", "location": location})

    data: Dict[str, Any] = {
        "cache": "fresh" if fresh else "stale",
    }
    if age_seconds is not None:
        data["age"] = format_age(age_seconds)
    if size_bytes is not None:
        size_kb = size_bytes / 1024
        data["size"] = (
            f"{size_kb / 1024:.1f} MB" if size_kb >= 1024 else f"{size_kb:.1f} KB"
        )
    if version is not None:
        data["version"] = version
    if scope is not None:
        data["scope"] = scope
    data["organizations"] = org_count
    data["folders"] = folder_count
    data["projects"] = project_count
    data["location"] = location
    return toon_object(data)


def toon_config(config: Dict[str, Any], location: str) -> str:
    if not config:
        return toon_object({"config": "empty", "location": location})
    data = dict(config)
    data["location"] = location
    return toon_object(data)


def toon_confirmed(message: str) -> str:
    return toon_object({"status": "ok", "message": message})


def _node_to_dict(node: Union[OrganizationNode, Folder]) -> Tuple[str, Dict[str, Any]]:
    if isinstance(node, OrganizationNode):
        return node.organization.name, {
            "path": f"//{path_escape(node.organization.display_name)}",
            "resource_name": node.organization.name,
            "display_name": node.organization.display_name,
            "type": "organization",
        }
    return node.name, {
        "path": node.path,
        "resource_name": node.name,
        "display_name": node.display_name,
        "type": "folder",
    }


def _get_child_folders(
    node: Union[OrganizationNode, Folder], parent_name: str
) -> List[Folder]:
    org_ref = node if isinstance(node, OrganizationNode) else node.organization
    if not org_ref:
        return []
    children = [f for f in org_ref.folders.values() if f.parent == parent_name]
    children.sort(key=lambda x: x.display_name)
    return children


def serialize_tree_node(
    node: Union[OrganizationNode, Folder],
    projects_by_parent: Dict[str, List[Project]],
    level: Optional[int] = None,
    current_depth: int = 0,
    type_filter: Optional[str] = None,
) -> Dict[str, Any]:
    parent_name, d = _node_to_dict(node)

    if level is not None and current_depth >= level:
        d["children"] = []
        return d

    children: List[Dict[str, Any]] = []

    for f in _get_child_folders(node, parent_name):
        sub = serialize_tree_node(
            f, projects_by_parent, level, current_depth + 1, type_filter
        )
        if type_filter == "project":
            children.extend(sub.get("children", []))
        else:
            children.append(sub)

    if type_filter != "folder":
        for p in sorted(
            projects_by_parent.get(parent_name, []), key=lambda x: x.display_name
        ):
            children.append(serialize_resource(p.path, p))

    d["children"] = children
    return d


def serialize_tree(
    nodes_to_process: List[Union[OrganizationNode, Folder]],
    projects_by_parent: Dict[str, List[Project]],
    level: Optional[int] = None,
    orgless_projects: Optional[List[Project]] = None,
    type_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    result = []
    for node in nodes_to_process:
        result.append(
            serialize_tree_node(
                node, projects_by_parent, level, type_filter=type_filter
            )
        )

    if orgless_projects and type_filter != "folder":
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


def serialize_ancestors(
    chain: List[Tuple[str, str, str]],
) -> List[Dict[str, str]]:
    return [
        {"resource_name": name, "display_name": dn, "type": t} for name, dn, t in chain
    ]


def serialize_name_results(
    results: List[Tuple[str, str]], id_only: bool = False
) -> List[Dict[str, str]]:
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
    return [{"resource_name": name, "path": path} for name, path in results]


def dump_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def dump_yaml(data: Any) -> str:
    return yaml.dump(
        data, default_flow_style=False, allow_unicode=True, sort_keys=False
    )
