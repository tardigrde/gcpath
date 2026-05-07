"""MCP (Model Context Protocol) server exposing gcpath as tools for agents.

This module is optional. The `mcp` package is only required if you actually
run `gcpath mcp` — install it with `pip install gcpath[mcp]` or
`uv sync --extra mcp`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from gcpath.audit import run_audit, summarize_severities
from gcpath.cli import _aggregate_metadata
from gcpath.core import (
    Folder,
    GCPathError,
    Hierarchy,
    OrganizationNode,
    Project,
)
from gcpath.formatters import console_url

logger = logging.getLogger(__name__)


_HIERARCHY_CACHE: Dict[str, Hierarchy] = {}


def _cache_key(use_asset_api: bool, scope: Optional[str]) -> str:
    return f"{int(use_asset_api)}::{scope or '_root_'}"


def _get_hierarchy(
    *,
    use_asset_api: bool = True,
    scope: Optional[str] = None,
    include_labels: bool = True,
    include_tags: bool = True,
    refresh: bool = False,
) -> Hierarchy:
    """Load (or reuse a cached) Hierarchy for the current process."""
    key = _cache_key(use_asset_api, scope)
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


def _resolve_to_object(
    hierarchy: Hierarchy, path: str
) -> Any:
    res_name = hierarchy.get_resource_name(path)
    if res_name.startswith("organizations/"):
        for org in hierarchy.organizations:
            if org.organization.name == res_name:
                return org
    elif res_name.startswith("folders/"):
        for org in hierarchy.organizations:
            if res_name in org.folders:
                return org.folders[res_name]
    elif res_name.startswith("projects/"):
        for proj in hierarchy.projects:
            if proj.name == res_name:
                return proj
    raise GCPathError(f"Resource '{res_name}' not loaded in current hierarchy")


def _serialize_resource(item: Any) -> Dict[str, Any]:
    if isinstance(item, OrganizationNode):
        return {
            "type": "organization",
            "resource_name": item.organization.name,
            "display_name": item.organization.display_name,
            "path": f"//{item.organization.display_name}",
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


def build_server(
    *,
    use_asset_api: bool = True,
    scope: Optional[str] = None,
):
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

    @server.tool()
    def path_to_name(paths: List[str]) -> List[Dict[str, str]]:
        """Resolve human paths (e.g. //example.com/eng) to GCP resource names."""
        h = _get_hierarchy(use_asset_api=use_asset_api, scope=scope)
        out: List[Dict[str, str]] = []
        for p in paths:
            try:
                out.append({"path": p, "resource_name": h.get_resource_name(p)})
            except GCPathError as e:
                out.append({"path": p, "error": str(e)})
        return out

    @server.tool()
    def name_to_path(resource_names: List[str]) -> List[Dict[str, str]]:
        """Resolve GCP resource names (e.g. folders/123) to human paths."""
        out: List[Dict[str, str]] = []
        for n in resource_names:
            try:
                out.append({"resource_name": n, "path": Hierarchy.resolve_ancestry(n)})
            except GCPathError as e:
                out.append({"resource_name": n, "error": str(e)})
        return out

    @server.tool()
    def list_resources(
        resource_scope: Optional[str] = None,
        recursive: bool = False,
    ) -> List[Dict[str, Any]]:
        """List folders and projects in the hierarchy. Optional scope (e.g. folders/123)."""
        h = _get_hierarchy(use_asset_api=use_asset_api, scope=resource_scope or scope)
        results: List[Dict[str, Any]] = []
        if not resource_scope:
            for org in h.organizations:
                results.append(_serialize_resource(org))
        for f in h.folders:
            if recursive or (resource_scope and f.parent == resource_scope):
                results.append(_serialize_resource(f))
            elif not resource_scope and f.parent.startswith("organizations/"):
                results.append(_serialize_resource(f))
        for p in h.projects:
            if recursive or (resource_scope and p.parent == resource_scope):
                results.append(_serialize_resource(p))
            elif not resource_scope:
                results.append(_serialize_resource(p))
        return results

    @server.tool()
    def find_resources(
        pattern: str,
        type_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Glob-search resources by display name (e.g. '*-prod')."""
        import fnmatch

        h = _get_hierarchy(use_asset_api=use_asset_api, scope=scope)
        candidates: List[Any] = []
        if not type_filter or type_filter == "organization":
            candidates.extend(h.organizations)
        if not type_filter or type_filter == "folder":
            candidates.extend(h.folders)
        if not type_filter or type_filter == "project":
            candidates.extend(h.projects)
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

    @server.tool()
    def get_ancestors(resource_name: str) -> List[Dict[str, str]]:
        """Return ancestry chain for a resource name from root to leaf."""
        chain = Hierarchy.resolve_ancestry_chain(resource_name)
        return [
            {"resource_name": rn, "display_name": dn, "type": t}
            for rn, dn, t in chain
        ]

    @server.tool()
    def get_summary(resource_scope: Optional[str] = None) -> Dict[str, Any]:
        """Compact summary: counts, depth, top labels/tags, deepest paths."""
        h = _get_hierarchy(use_asset_api=use_asset_api, scope=resource_scope or scope)
        return h.summary()

    @server.tool()
    def get_labels(
        resource_scope: Optional[str] = None,
        key: Optional[str] = None,
        top: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Aggregate labels across the hierarchy with counts."""
        h = _get_hierarchy(use_asset_api=use_asset_api, scope=resource_scope or scope)
        items = list(h.folders) + list(h.projects)
        rows, total = _aggregate_metadata(items, "labels", key_filter=key)
        if top:
            rows = rows[:top]
        return {"count": len(rows), "scanned": total, "labels": rows}

    @server.tool()
    def get_tags(
        resource_scope: Optional[str] = None,
        key: Optional[str] = None,
        top: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Aggregate resource tags across the hierarchy with counts."""
        h = _get_hierarchy(use_asset_api=use_asset_api, scope=resource_scope or scope)
        items = list(h.folders) + list(h.projects)
        rows, total = _aggregate_metadata(items, "tags", key_filter=key)
        if top:
            rows = rows[:top]
        return {"count": len(rows), "scanned": total, "tags": rows}

    @server.tool()
    def get_console_url(paths: List[str]) -> List[Dict[str, str]]:
        """Build GCP Cloud Console URLs for one or more paths."""
        h = _get_hierarchy(use_asset_api=use_asset_api, scope=scope)
        out: List[Dict[str, str]] = []
        for p in paths:
            try:
                obj = _resolve_to_object(h, p)
                out.append({"path": p, "url": console_url(obj)})
            except GCPathError as e:
                out.append({"path": p, "error": str(e)})
        return out

    @server.tool()
    def audit_hierarchy(
        resource_scope: Optional[str] = None,
        require_labels: Optional[List[str]] = None,
        name_pattern: Optional[str] = None,
        severity: str = "info",
    ) -> Dict[str, Any]:
        """Run governance audit checks on the hierarchy."""
        h = _get_hierarchy(use_asset_api=use_asset_api, scope=resource_scope or scope)
        issues = run_audit(
            h,
            require_labels=require_labels,
            name_pattern=name_pattern,
            severity=severity,
        )
        return {
            "severity_counts": summarize_severities(issues),
            "issues": issues,
        }

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
