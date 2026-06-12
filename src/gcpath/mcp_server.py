"""MCP (Model Context Protocol) server exposing gcpath as tools for agents.

This module is optional. The `mcp` package is only required if you actually
run `gcpath mcp` — install it with `pip install gcpath[mcp]` or
`uv sync --extra mcp`.
"""

from __future__ import annotations

import fnmatch
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

from gcpath.audit import run_audit, summarize_severities
from gcpath.core import (
    Folder,
    GCPathError,
    Hierarchy,
    OrganizationNode,
    Project,
    aggregate_metadata,
    path_escape,
)
from gcpath.formatters import console_url

logger = logging.getLogger(__name__)


_HIERARCHY_CACHE: Dict[str, Hierarchy] = {}

_PREFIX_ORGS = "organizations/"
_PREFIX_FOLDERS = "folders/"
_PREFIX_PROJECTS = "projects/"

# Caps caller-supplied regex length to bound worst-case backtracking time.
_NAME_PATTERN_MAX_LEN = 200


def _cache_key(
    use_asset_api: bool,
    scope: Optional[str],
    include_labels: bool,
    include_tags: bool,
) -> str:
    return (
        f"{int(use_asset_api)}::{int(include_labels)}::"
        f"{int(include_tags)}::{scope or '_root_'}"
    )


def _get_hierarchy(
    *,
    use_asset_api: bool = True,
    scope: Optional[str] = None,
    include_labels: bool = True,
    include_tags: bool = True,
    refresh: bool = False,
) -> Hierarchy:
    """Load (or reuse a cached) Hierarchy for the current process."""
    key = _cache_key(use_asset_api, scope, include_labels, include_tags)
    if not refresh and key in _HIERARCHY_CACHE:
        return _HIERARCHY_CACHE[key]
    hierarchy = Hierarchy.load(
        via_resource_manager=not use_asset_api,
        scope_resource=scope,
        recursive=True,
        include_labels=include_labels,
        include_tags=include_tags,
    )
    _HIERARCHY_CACHE[key] = hierarchy
    return hierarchy


def _find_org(hierarchy: Hierarchy, res_name: str) -> Optional[OrganizationNode]:
    for org in hierarchy.organizations:
        if org.organization.name == res_name:
            return org
    return None


def _find_folder(hierarchy: Hierarchy, res_name: str) -> Optional[Folder]:
    for org in hierarchy.organizations:
        if res_name in org.folders:
            return org.folders[res_name]
    return None


def _find_project(hierarchy: Hierarchy, res_name: str) -> Optional[Project]:
    for proj in hierarchy.projects:
        if proj.name == res_name:
            return proj
    return None


def _resolve_to_object(hierarchy: Hierarchy, path: str) -> Any:
    res_name = hierarchy.get_resource_name(path)
    if res_name.startswith(_PREFIX_ORGS):
        obj: Any = _find_org(hierarchy, res_name)
    elif res_name.startswith(_PREFIX_FOLDERS):
        obj = _find_folder(hierarchy, res_name)
    elif res_name.startswith(_PREFIX_PROJECTS):
        obj = _find_project(hierarchy, res_name)
    else:
        obj = None
    if obj is None:
        raise GCPathError(f"Resource '{res_name}' not loaded in current hierarchy")
    return obj


def _serialize_resource(item: Any) -> Dict[str, Any]:
    if isinstance(item, OrganizationNode):
        return {
            "type": "organization",
            "resource_name": item.organization.name,
            "display_name": item.organization.display_name,
            "path": f"//{path_escape(item.organization.display_name)}",
        }
    if isinstance(item, Folder):
        return {
            "type": "folder",
            "resource_name": item.name,
            "display_name": item.display_name,
            "path": item.path,
            "parent": item.parent,
            "labels": dict(item.labels or {}),
            "tags": dict(item.tags or {}),
        }
    if isinstance(item, Project):
        return {
            "type": "project",
            "resource_name": item.name,
            "project_id": item.project_id,
            "display_name": item.display_name,
            "path": item.path,
            "parent": item.parent,
            "labels": dict(item.labels or {}),
            "tags": dict(item.tags or {}),
        }
    return {"type": "unknown", "value": str(item)}


def _path_to_name_impl(hierarchy: Hierarchy, paths: List[str]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for p in paths:
        try:
            out.append({"path": p, "resource_name": hierarchy.get_resource_name(p)})
        except GCPathError as e:
            out.append({"path": p, "error": str(e)})
    return out


def _name_to_path_impl(
    hierarchy: Hierarchy, resource_names: List[str]
) -> List[Dict[str, str]]:
    """Resolve names against the cached hierarchy when possible.

    Falls back to the live `Hierarchy.resolve_ancestry` GCP call only when the
    resource isn't in the loaded scope, so common queries stay O(1) in memory.
    """
    out: List[Dict[str, str]] = []
    for n in resource_names:
        try:
            path = _name_from_loaded(hierarchy, n)
            if path is None:
                path = Hierarchy.resolve_ancestry(n)
            out.append({"resource_name": n, "path": path})
        except GCPathError as e:
            out.append({"resource_name": n, "error": str(e)})
    return out


def _name_from_loaded(hierarchy: Hierarchy, res_name: str) -> Optional[str]:
    if res_name.startswith(_PREFIX_ORGS):
        org = _find_org(hierarchy, res_name)
        if org is not None:
            return f"//{path_escape(org.organization.display_name)}"
    elif res_name.startswith(_PREFIX_FOLDERS):
        folder = _find_folder(hierarchy, res_name)
        if folder is not None:
            return folder.path
    elif res_name.startswith(_PREFIX_PROJECTS):
        project = _find_project(hierarchy, res_name)
        if project is not None:
            return project.path
    return None


def _list_resources_impl(
    hierarchy: Hierarchy,
    effective_scope: Optional[str],
    recursive: bool,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    if not effective_scope:
        for org in hierarchy.organizations:
            results.append(_serialize_resource(org))
    for f in hierarchy.folders:
        if _include_in_listing(f.parent, effective_scope, recursive):
            results.append(_serialize_resource(f))
    for p in hierarchy.projects:
        if _include_in_listing(p.parent, effective_scope, recursive):
            results.append(_serialize_resource(p))
    return results


def _include_in_listing(
    parent: str, effective_scope: Optional[str], recursive: bool
) -> bool:
    if recursive:
        return True
    if effective_scope:
        return parent == effective_scope
    return parent.startswith(_PREFIX_ORGS)


def _find_resources_impl(
    hierarchy: Hierarchy, pattern: str, type_filter: Optional[str]
) -> List[Dict[str, Any]]:
    candidates: List[Any] = []
    if not type_filter or type_filter == "organization":
        candidates.extend(hierarchy.organizations)
    if not type_filter or type_filter == "folder":
        candidates.extend(hierarchy.folders)
    if not type_filter or type_filter == "project":
        candidates.extend(hierarchy.projects)
    lower = pattern.lower()
    out: List[Dict[str, Any]] = []
    for c in candidates:
        name = (
            c.organization.display_name
            if isinstance(c, OrganizationNode)
            else c.display_name
        )
        if fnmatch.fnmatch(name.lower(), lower):
            out.append(_serialize_resource(c))
    return out


def _aggregate_impl(
    hierarchy: Hierarchy,
    attr: str,
    key: Optional[str],
    top: Optional[int],
) -> Dict[str, Any]:
    items = list(hierarchy.folders) + list(hierarchy.projects)
    rows, total = aggregate_metadata(items, attr, key_filter=key)
    # Distinguish "no limit" (None) from "top=0 → empty list" (truthy check
    # would treat both as equivalent and ignore top=0).
    if top is not None:
        rows = rows[:top]
    return {"count": len(rows), "scanned": total, attr: rows}


def _audit_impl(
    hierarchy: Hierarchy,
    *,
    require_labels: Optional[List[str]],
    name_pattern: Optional[str],
    severity: str,
) -> Dict[str, Any]:
    if name_pattern is not None and len(name_pattern) > _NAME_PATTERN_MAX_LEN:
        raise GCPathError(
            f"name_pattern too long ({len(name_pattern)} chars, "
            f"max {_NAME_PATTERN_MAX_LEN}); rejected to limit ReDoS risk"
        )
    issues = run_audit(
        hierarchy,
        require_labels=require_labels,
        name_pattern=name_pattern,
        severity=severity,
    )
    return {
        "severity_counts": summarize_severities(issues),
        "issues": issues,
    }


def _console_url_impl(hierarchy: Hierarchy, paths: List[str]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for p in paths:
        try:
            obj = _resolve_to_object(hierarchy, p)
            out.append({"path": p, "url": console_url(obj)})
        except GCPathError as e:
            out.append({"path": p, "error": str(e)})
    return out


def build_server(
    *,
    use_asset_api: bool = True,
    scope: Optional[str] = None,
) -> "FastMCP":
    """Construct a FastMCP server with all gcpath tools registered.

    Imports `mcp` lazily so the rest of the package works without it installed.
    """
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore[import-not-found]
    except ImportError as e:
        raise GCPathError(
            "MCP support requires the `mcp` extra. "
            "Install with: pip install 'gcpath[mcp]' or uv sync --extra mcp"
        ) from e

    server = FastMCP("gcpath")

    def _hier(resource_scope: Optional[str] = None) -> Hierarchy:
        return _get_hierarchy(
            use_asset_api=use_asset_api, scope=resource_scope or scope
        )

    @server.tool()
    def path_to_name(paths: List[str]) -> List[Dict[str, str]]:
        """Resolve human paths (e.g. //example.com/eng) to GCP resource names."""
        return _path_to_name_impl(_hier(), paths)

    @server.tool()
    def name_to_path(resource_names: List[str]) -> List[Dict[str, str]]:
        """Resolve GCP resource names (e.g. folders/123) to human paths."""
        return _name_to_path_impl(_hier(), resource_names)

    @server.tool()
    def list_resources(
        resource_scope: Optional[str] = None,
        recursive: bool = False,
    ) -> List[Dict[str, Any]]:
        """List folders and projects in the hierarchy. Optional scope (e.g. folders/123)."""
        effective = resource_scope or scope
        return _list_resources_impl(_hier(resource_scope), effective, recursive)

    @server.tool()
    def find_resources(
        pattern: str,
        type_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Glob-search resources by display name (e.g. '*-prod')."""
        return _find_resources_impl(_hier(), pattern, type_filter)

    @server.tool()
    def get_ancestors(resource_name: str) -> List[Dict[str, str]]:
        """Return ancestry chain for a resource name from root to leaf."""
        chain = Hierarchy.resolve_ancestry_chain(resource_name)
        return [
            {"resource_name": rn, "display_name": dn, "type": t} for rn, dn, t in chain
        ]

    @server.tool()
    def get_summary(resource_scope: Optional[str] = None) -> Dict[str, Any]:
        """Compact summary: counts, depth, top labels/tags, deepest paths."""
        return _hier(resource_scope).summary()

    @server.tool()
    def get_labels(
        resource_scope: Optional[str] = None,
        key: Optional[str] = None,
        top: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Aggregate labels across the hierarchy with counts."""
        return _aggregate_impl(_hier(resource_scope), "labels", key, top)

    @server.tool()
    def get_tags(
        resource_scope: Optional[str] = None,
        key: Optional[str] = None,
        top: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Aggregate resource tags across the hierarchy with counts."""
        return _aggregate_impl(_hier(resource_scope), "tags", key, top)

    @server.tool()
    def get_console_url(paths: List[str]) -> List[Dict[str, str]]:
        """Build GCP Cloud Console URLs for one or more paths."""
        return _console_url_impl(_hier(), paths)

    @server.tool()
    def audit_hierarchy(
        resource_scope: Optional[str] = None,
        require_labels: Optional[List[str]] = None,
        name_pattern: Optional[str] = None,
        severity: str = "info",
    ) -> Dict[str, Any]:
        """Run governance audit checks on the hierarchy.

        ``name_pattern`` is treated as caller-supplied and is length-capped to
        bound worst-case regex backtracking.
        """
        return _audit_impl(
            _hier(resource_scope),
            require_labels=require_labels,
            name_pattern=name_pattern,
            severity=severity,
        )

    return server


def run_server(
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    use_asset_api: bool = True,
    scope: Optional[str] = None,
) -> None:
    """Run the gcpath MCP server in the given transport mode."""
    server = build_server(use_asset_api=use_asset_api, scope=scope)

    if transport == "stdio":
        server.run()
        return

    if transport == "sse":
        try:
            server.settings.host = host
            server.settings.port = port
        except AttributeError:
            logger.debug("FastMCP settings.host/port not configurable on this version")
        server.run(transport="sse")
        return

    raise GCPathError(f"Unsupported MCP transport '{transport}' (use stdio or sse)")
