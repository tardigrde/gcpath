"""Unit tests for gcpath.mcp_server tool implementations.

These exercise the pure helper functions used by each MCP tool so we have
coverage of the actual logic without needing to spin up a FastMCP transport.
"""

from unittest.mock import patch

import pytest
from conftest import make_test_hierarchy
from google.cloud import resourcemanager_v3

from gcpath.core import (
    Folder,
    GCPathError,
    Hierarchy,
    OrganizationNode,
    Project,
    SYNTHETIC_ORG_NAME,
)
from gcpath.mcp_server import (
    _aggregate_impl,
    _audit_impl,
    _cache_key,
    _console_url_impl,
    _find_resources_impl,
    _list_resources_impl,
    _name_to_path_impl,
    _path_to_name_impl,
    _resolve_to_object,
    _resolve_server_scope,
    _serialize_resource,
)


# ---- helpers ----


def _hierarchy_with_metadata():
    h = make_test_hierarchy()
    h.folders[0].labels = {"team": "platform", "tier": "prod"}
    h.folders[1].labels = {"team": "platform"}
    h.projects[0].labels = {"team": "platform", "owner": "alice"}
    h.projects[0].tags = {"env": "prod"}
    return h


# ---- _cache_key ----


def test_cache_key_distinguishes_metadata_flags():
    base = _cache_key(True, None, True, True)
    no_labels = _cache_key(True, None, False, True)
    no_tags = _cache_key(True, None, True, False)
    rm_mode = _cache_key(False, None, True, True)
    scoped = _cache_key(True, "folders/1", True, True)
    assert len({base, no_labels, no_tags, rm_mode, scoped}) == 5


# ---- _get_hierarchy caching ----


def test_get_hierarchy_caches_per_metadata_flag_combo():
    import gcpath.mcp_server as mcp_mod

    mcp_mod._HIERARCHY_CACHE.clear()
    with (
        patch.object(mcp_mod, "read_cache", return_value=None),
        patch.object(mcp_mod, "write_cache"),
        patch.object(Hierarchy, "load") as mock_load,
    ):
        mock_load.side_effect = [
            make_test_hierarchy(),
            make_test_hierarchy(),
        ]
        mcp_mod._get_hierarchy(use_asset_api=True, scope=None, include_labels=True)
        # Same key — must hit cache, no extra load.
        mcp_mod._get_hierarchy(use_asset_api=True, scope=None, include_labels=True)
        # Different include_labels — must re-load (different cache key).
        mcp_mod._get_hierarchy(use_asset_api=True, scope=None, include_labels=False)
        assert mock_load.call_count == 2
    mcp_mod._HIERARCHY_CACHE.clear()


def test_get_hierarchy_uses_disk_cache_before_live_load():
    import gcpath.mcp_server as mcp_mod

    mcp_mod._HIERARCHY_CACHE.clear()
    cached = make_test_hierarchy()
    with (
        patch.object(mcp_mod, "read_cache", return_value=cached) as mock_read,
        patch.object(mcp_mod, "write_cache") as mock_write,
        patch.object(Hierarchy, "load") as mock_load,
    ):
        result = mcp_mod._get_hierarchy(use_asset_api=True, scope=None)

    assert result is cached
    mock_read.assert_called_once()
    mock_load.assert_not_called()
    mock_write.assert_not_called()
    mcp_mod._HIERARCHY_CACHE.clear()


def test_get_hierarchy_refresh_loads_and_writes_disk_cache():
    import gcpath.mcp_server as mcp_mod

    mcp_mod._HIERARCHY_CACHE.clear()
    loaded = make_test_hierarchy()
    with (
        patch.object(mcp_mod, "read_cache") as mock_read,
        patch.object(mcp_mod, "write_cache") as mock_write,
        patch.object(Hierarchy, "load", return_value=loaded) as mock_load,
    ):
        result = mcp_mod._get_hierarchy(
            use_asset_api=False,
            scope="folders/1",
            refresh=True,
            include_labels=True,
            include_tags=False,
        )

    assert result is loaded
    mock_read.assert_not_called()
    mock_load.assert_called_once()
    mock_write.assert_called_once_with(
        loaded,
        scope="folders/1",
        via_resource_manager=True,
        include_labels=True,
        include_tags=False,
    )
    mcp_mod._HIERARCHY_CACHE.clear()


def test_resolve_server_scope_rejects_resource_outside_server_scope():
    with patch.object(
        Hierarchy,
        "resolve_ancestry_chain",
        return_value=[("organizations/2", "other", "organization")],
    ):
        with pytest.raises(GCPathError):
            _resolve_server_scope("folders/999", "folders/1")


def test_resolve_server_scope_allows_descendant_scope():
    with patch.object(
        Hierarchy,
        "resolve_ancestry_chain",
        return_value=[
            ("organizations/1", "org", "organization"),
            ("folders/1", "root", "folder"),
            ("folders/2", "child", "folder"),
        ],
    ):
        assert _resolve_server_scope("folders/2", "folders/1") == "folders/2"


# ---- _list_resources_impl ----


def test_list_resources_root_only_includes_org_level_projects():
    h = make_test_hierarchy()
    rows = _list_resources_impl(h, effective_scope=None, recursive=False)
    types = [r["type"] for r in rows]
    # Mock hierarchy: 1 org, root folder f1 directly under org, p1 nested under
    # f1. Without scope and non-recursive we should see the org and root-level
    # folder but NOT the nested project p1.
    assert types.count("organization") == 1
    paths = [r["path"] for r in rows if r["type"] == "folder"]
    assert any(p == "//example.com/f1" for p in paths)
    project_paths = [r["path"] for r in rows if r["type"] == "project"]
    # p1 lives under folders/1 (not directly under org), so it must be excluded.
    assert "//example.com/f1/Project%201" not in project_paths


def test_list_resources_scoped_returns_direct_children_only():
    h = make_test_hierarchy()
    rows = _list_resources_impl(h, effective_scope="folders/1", recursive=False)
    folder_names = [r["resource_name"] for r in rows if r["type"] == "folder"]
    project_names = [r["resource_name"] for r in rows if r["type"] == "project"]
    assert "folders/11" in folder_names
    assert "projects/p1" in project_names
    # Org row should NOT appear when a scope is provided.
    assert all(r["type"] != "organization" for r in rows)


def test_list_resources_recursive_returns_everything():
    h = make_test_hierarchy()
    rows = _list_resources_impl(h, effective_scope="folders/1", recursive=True)
    types = [r["type"] for r in rows]
    assert "folder" in types
    assert "project" in types


# ---- _path_to_name_impl / _name_to_path_impl ----


def test_path_to_name_resolves_loaded_paths():
    h = make_test_hierarchy()
    out = _path_to_name_impl(h, ["//example.com/f1"])
    assert out == [{"path": "//example.com/f1", "resource_name": "folders/1"}]


def test_path_to_name_collects_errors():
    h = make_test_hierarchy()
    out = _path_to_name_impl(h, ["//missing/x"])
    assert "error" in out[0]


def test_name_to_path_uses_cached_hierarchy_for_known_resources():
    h = make_test_hierarchy()
    with patch.object(Hierarchy, "resolve_ancestry") as mock_live:
        out = _name_to_path_impl(h, ["folders/1", "projects/p1"])
    assert mock_live.call_count == 0  # Loaded resources never hit live API.
    paths = {row["resource_name"]: row["path"] for row in out}
    assert paths["folders/1"] == "//example.com/f1"
    assert paths["projects/p1"] == "//example.com/f1/Project%201"


def test_name_to_path_falls_back_to_live_for_unknown():
    h = make_test_hierarchy()
    with patch.object(
        Hierarchy, "resolve_ancestry", return_value="//other.com/x"
    ) as mock_live:
        out = _name_to_path_impl(h, ["folders/9999"])
    assert mock_live.call_count == 1
    assert out[0]["path"] == "//other.com/x"


# ---- _find_resources_impl ----


def test_find_resources_glob_match():
    h = make_test_hierarchy()
    out = _find_resources_impl(h, "f*", type_filter="folder")
    names = sorted(r["display_name"] for r in out)
    assert names == ["f1", "f11"]


def test_find_resources_type_filter_project():
    h = make_test_hierarchy()
    out = _find_resources_impl(h, "*", type_filter="project")
    assert all(r["type"] == "project" for r in out)


# ---- _resolve_to_object ----


def test_resolve_to_object_org():
    h = make_test_hierarchy()
    obj = _resolve_to_object(h, "//example.com")
    assert isinstance(obj, OrganizationNode)


def test_resolve_to_object_unknown_path_raises():
    h = make_test_hierarchy()
    with pytest.raises(GCPathError):
        _resolve_to_object(h, "//does/not/exist")


# ---- _console_url_impl ----


def test_console_url_impl_returns_url_for_folder():
    h = make_test_hierarchy()
    out = _console_url_impl(h, ["//example.com/f1"])
    assert "url" in out[0]
    assert out[0]["url"].startswith("https://console.cloud.google.com/")


def test_console_url_impl_collects_errors_for_orgless():
    h = make_test_hierarchy()
    out = _console_url_impl(h, ["//_/Standalone"])
    assert "error" in out[0]


# ---- _aggregate_impl ----


def test_aggregate_impl_labels_basic():
    h = _hierarchy_with_metadata()
    result = _aggregate_impl(h, "labels", key=None, top=None)
    assert result["scanned"] == len(h.folders) + len(h.projects)
    keys = {row["key"] for row in result["labels"]}
    assert "team" in keys


def test_aggregate_impl_labels_key_filter_and_top():
    h = _hierarchy_with_metadata()
    result = _aggregate_impl(h, "labels", key="team", top=1)
    assert all(row["key"] == "team" for row in result["labels"])
    assert len(result["labels"]) <= 1


def test_aggregate_impl_top_zero_returns_empty_list():
    """`top=0` must mean "no rows" and not be silently treated as None."""
    h = _hierarchy_with_metadata()
    result = _aggregate_impl(h, "labels", key=None, top=0)
    assert result["labels"] == []
    # `scanned` should still reflect the number of items scanned, not the
    # number of rows after slicing.
    assert result["scanned"] == len(h.folders) + len(h.projects)


def test_serialize_resource_org_path_is_url_escaped():
    """OrganizationNode paths must be url-encoded for round-trip parity."""
    org_proto = resourcemanager_v3.Organization(
        name="organizations/9", display_name="acme corp"
    )
    out = _serialize_resource(OrganizationNode(organization=org_proto))
    assert out["path"] == "//acme%20corp"


def test_name_to_path_for_org_returns_escaped_path():
    org_proto = resourcemanager_v3.Organization(
        name="organizations/9", display_name="acme corp"
    )
    org = OrganizationNode(organization=org_proto)
    h = Hierarchy([org], [])
    out = _name_to_path_impl(h, ["organizations/9"])
    assert out[0]["path"] == "//acme%20corp"


# ---- _audit_impl ----


def test_audit_impl_returns_severity_counts_and_issues():
    h = make_test_hierarchy()
    result = _audit_impl(h, require_labels=None, name_pattern=None, severity="info")
    assert "severity_counts" in result
    assert "issues" in result
    assert any(i["check"] == "orphan_project" for i in result["issues"])


def test_audit_impl_rejects_oversized_name_pattern():
    h = make_test_hierarchy()
    huge = "a" * 500
    with pytest.raises(GCPathError):
        _audit_impl(h, require_labels=None, name_pattern=huge, severity="info")


# ---- synthetic-org regressions ----


def test_serialize_resource_unknown_falls_back():
    out = _serialize_resource(object())
    assert out["type"] == "unknown"


def test_audit_impl_flags_synthetic_org_projects():
    synth_proto = resourcemanager_v3.Organization(
        name=SYNTHETIC_ORG_NAME, display_name="root_folder"
    )
    real_proto = resourcemanager_v3.Organization(
        name="organizations/77", display_name="acme"
    )
    synth = OrganizationNode(organization=synth_proto)
    real = OrganizationNode(organization=real_proto)
    f = Folder(
        name="folders/9",
        display_name="under_synth",
        ancestors=["folders/9"],
        organization=synth,
        parent=SYNTHETIC_ORG_NAME,
    )
    synth.folders["folders/9"] = f
    p = Project(
        name="projects/under_synth",
        project_id="under_synth",
        display_name="under_synth_proj",
        parent=SYNTHETIC_ORG_NAME,
        organization=synth,
        folder=None,
    )
    h = Hierarchy([synth, real], [p])
    result = _audit_impl(h, require_labels=None, name_pattern=None, severity="info")
    types = [i["type"] for i in result["issues"] if i["check"] == "synthetic_org"]
    assert "folder" in types
    assert "project" in types


# ---- build_server smoke ----


def test_build_server_raises_when_mcp_extra_missing():
    import sys
    import gcpath.mcp_server as mcp_mod

    sys.modules.pop("mcp.server.fastmcp", None)
    with patch.dict(sys.modules, {"mcp.server.fastmcp": None}):
        with pytest.raises(GCPathError):
            mcp_mod.build_server()


def test_build_server_succeeds_when_mcp_available():
    import gcpath.mcp_server as mcp_mod

    pytest.importorskip("mcp.server.fastmcp")
    server = mcp_mod.build_server()
    assert server is not None


def test_build_server_registers_each_tool_callback():
    """Smoke-call every registered MCP tool to lock in the registration.

    Bodies are tiny passthroughs to ``_*_impl`` helpers (already unit-tested),
    but invoking each via ``call_tool`` ensures registration and arg-binding
    keep working.
    """
    import asyncio

    pytest.importorskip("mcp.server.fastmcp")
    import gcpath.mcp_server as mcp_mod

    h = make_test_hierarchy()
    mcp_mod._HIERARCHY_CACHE.clear()

    async def _exercise():
        with (
            patch.object(mcp_mod, "read_cache", return_value=None),
            patch.object(mcp_mod, "write_cache"),
            patch.object(Hierarchy, "load", return_value=h),
        ):
            server = mcp_mod.build_server()
            await server.call_tool("path_to_name", {"paths": ["//example.com/f1"]})
            await server.call_tool(
                "list_resources", {"resource_scope": None, "recursive": False}
            )
            await server.call_tool("find_resources", {"pattern": "f*"})
            await server.call_tool("get_summary", {})
            await server.call_tool("get_labels", {})
            await server.call_tool("get_tags", {})
            await server.call_tool("get_console_url", {"paths": ["//example.com/f1"]})
            await server.call_tool("audit_hierarchy", {})
            await server.call_tool("refresh_hierarchy", {})
            with patch.object(Hierarchy, "resolve_ancestry_chain", return_value=[]):
                await server.call_tool("get_ancestors", {"resource_name": "folders/1"})
            with patch.object(
                Hierarchy, "resolve_ancestry", return_value="//example.com/f1"
            ):
                await server.call_tool(
                    "name_to_path", {"resource_names": ["folders/1"]}
                )

    asyncio.run(_exercise())
    mcp_mod._HIERARCHY_CACHE.clear()
