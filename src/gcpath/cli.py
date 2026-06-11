import fnmatch
import shutil
import typer
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict, Union
from urllib.parse import unquote
from typing_extensions import Annotated
from rich import print as rprint
from google.api_core import exceptions as gcp_exceptions

from gcpath.core import (
    Hierarchy,
    aggregate_metadata,
    path_escape,
    Project,
    GCPathError,
    OrganizationNode,
    Folder,
)
from gcpath.formatters import (
    filter_direct_children,
    build_items_list,
    sort_resources,
    format_tree_label,
    build_tree_view,
    build_diagram,
    console_url,
)
from gcpath.serializers import (
    resource_type as get_resource_type,
    serialize_ls,
    serialize_tree,
    serialize_name_results,
    serialize_path_results,
    serialize_ancestors,
    serialize_open_results,
    dump_json,
    dump_yaml,
    toon_ls,
    toon_name,
    toon_path,
    toon_ancestors,
    toon_find,
    toon_stats,
    toon_cache_status,
    toon_config,
    toon_confirmed,
    toon_encode,
    toon_open,
    toon_labels,
    toon_tags,
    toon_summary,
    toon_audit,
    _ALL_LS_FIELDS,
)
from gcpath.audit import run_audit, summarize_severities
from gcpath.errors import describe_error, is_unexpected
from gcpath.toon import format_age, toon_error
from gcpath.hooks import (
    install_hooks,
    uninstall_hooks,
    get_hook_status,
    run_session_start,
)
from typing import Any, Callable, Tuple
from gcpath.cache import (
    read_cache,
    write_cache,
    clear_cache,
    get_cache_info,
    read_cache_raw,
    CACHE_FILE,
)
from gcpath.config import (
    get_entrypoint,
    set_entrypoint,
    clear_entrypoint,
    read_config,
    CONFIG_FILE,
)

_RESOURCE_PREFIX_PROJECTS = "projects/"
_RESOURCE_PREFIX_FOLDERS = "folders/"
_RESOURCE_PREFIX_ORGS = "organizations/"
_RESOURCE_PREFIXES = (
    _RESOURCE_PREFIX_ORGS,
    _RESOURCE_PREFIX_FOLDERS,
    _RESOURCE_PREFIX_PROJECTS,
)
_REFRESH_HELP = "Force a refresh of the cache from the GCP API"
_VALID_TYPE_FILTERS = ("folder", "project", "organization")
_VALID_FORMATS = ("toon", "json", "yaml", "rich")
_RICH_HEADER_STYLE = "bold magenta"
_SCOPE_ALL_ORGS = "all organizations"
_NAME_PATTERN_MAX_LEN = 200

logger = logging.getLogger(__name__)


def _display_bin_path(path: str) -> str:
    home = str(Path.home())
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


def _validate_type_filter(resource_type: Optional[str]) -> None:
    if resource_type is not None and resource_type not in _VALID_TYPE_FILTERS:
        print(toon_error(f"Invalid type '{resource_type}'. Must be one of: {', '.join(_VALID_TYPE_FILTERS)}"))
        raise typer.Exit(code=1)


def _matches_type(
    obj: Union[OrganizationNode, Folder, Project], type_filter: str
) -> bool:
    return get_resource_type(obj) == type_filter


def _parse_label_filter(label_str: str) -> tuple:
    if "=" not in label_str:
        return (label_str, None)
    key, _, value = label_str.partition("=")
    return (key, value)


def _matches_metadata(
    obj: Union[OrganizationNode, Folder, Project],
    filters: List[str],
    attr: str,
) -> bool:
    if not filters:
        return True
    metadata = getattr(obj, attr, {})
    for f in filters:
        key, value = _parse_label_filter(f)
        if value is None:
            if key not in metadata:
                return False
        elif metadata.get(key) != value:
            return False
    return True


@dataclass
class _ScopeResult:
    target_resource_name: Optional[str]
    target_org_name: Optional[str]
    filter_orgs: Optional[List[str]]


def _resolve_scope(
    resource: Optional[str],
    entrypoint: Optional[str],
) -> _ScopeResult:
    """Resolve resource/entrypoint into scope parameters for hierarchy loading.

    Returns target_resource_name, target_org_name, and filter_orgs.
    """
    effective_resource = resource or entrypoint
    target_resource_name = None
    target_org_name = None

    if effective_resource and any(
        effective_resource.startswith(p) for p in _RESOURCE_PREFIXES
    ):
        target_resource_name = effective_resource
        try:
            target_path = Hierarchy.resolve_ancestry(effective_resource)
            if target_path.startswith("//"):
                path_parts = target_path[2:].split("/")
                if path_parts:
                    target_org_name = unquote(path_parts[0])
        except (gcp_exceptions.PermissionDenied, gcp_exceptions.NotFound, GCPathError):
            pass

    if not resource and entrypoint and target_org_name:
        filter_orgs = None
    else:
        filter_orgs = [target_org_name] if target_org_name else None

    return _ScopeResult(
        target_resource_name=target_resource_name,
        target_org_name=target_org_name,
        filter_orgs=filter_orgs,
    )


app = typer.Typer(
    name="gcpath",
    help="Google Cloud Platform resource hierarchy utility",
    add_completion=False,
    invoke_without_command=True,
)
cache_app = typer.Typer(help="Manage the local resource cache.")
app.add_typer(cache_app, name="cache")
config_app = typer.Typer(help="Manage gcpath configuration.")
app.add_typer(config_app, name="config")
hook_app = typer.Typer(help="Manage agent session hooks.")
app.add_typer(hook_app, name="hook")

def _get_dumper(output_format: str) -> Optional[Callable[[Any], str]]:
    if output_format == "json":
        return dump_json
    if output_format == "yaml":
        return dump_yaml
    return None


def _output_toon(data_or_str: Any) -> None:
    if isinstance(data_or_str, str):
        print(data_or_str)
    else:
        print(toon_encode(data_or_str))


def handle_error(e: Exception) -> None:
    message, help_lines = describe_error(e)
    print(toon_error(message, help_lines or None))
    if is_unexpected(e):
        logging.exception("Unexpected error occurred")
    raise typer.Exit(code=1)


@app.callback()
def main(
    ctx: typer.Context,
    use_asset_api: bool = typer.Option(
        True,
        "--use-asset-api/--no-use-asset-api",
        "-u/-U",
        help="Use Cloud Asset API to load folders (faster) or Resource Manager (slower)",
    ),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
    entrypoint: Optional[str] = typer.Option(
        None,
        "--entrypoint",
        "-e",
        help="Default resource to scope commands to (e.g., folders/123). Overrides config.",
    ),
    output_format: str = typer.Option(
        "toon",
        "--format",
        help=f"Output format: {', '.join(_VALID_FORMATS)}",
    ),
) -> None:
    """gcpath - Google Cloud Platform resource hierarchy utility"""
    if output_format not in _VALID_FORMATS:
        print(toon_error(f"Invalid format '{output_format}'. Must be one of: {', '.join(_VALID_FORMATS)}"))
        raise typer.Exit(code=1)

    ctx.ensure_object(dict)
    ctx.obj["use_asset_api"] = use_asset_api
    ctx.obj["entrypoint"] = entrypoint or get_entrypoint()
    ctx.obj["output_format"] = output_format

    if debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.ERROR)

    logging.getLogger("urllib3").setLevel(logging.WARNING)

    if ctx.invoked_subcommand is None:
        _show_home(ctx)


def _show_home(_ctx: typer.Context) -> None:
    """Content-first home view (AXI Principle 8)."""
    gcpath_bin = _display_bin_path(shutil.which("gcpath") or "gcpath")
    info = get_cache_info()

    if not info.exists or not info.fresh:
        if info.exists:
            age = (
                f" ({format_age(info.age_seconds)} ago)"
                if info.age_seconds is not None
                else ""
            )
            cache_state = f"stale{age}"
            help_lines = [
                "Run `gcpath cache refresh` to reload from GCP",
                "Run `gcpath ls` to load and list resources",
            ]
        else:
            cache_state = "empty"
            help_lines = [
                "Run `gcpath ls` to load and list resources",
                "Run `gcpath hook install` to enable ambient context",
            ]
        dashboard: Dict[str, Any] = {
            "bin": gcpath_bin,
            "description": "Query GCP resource hierarchy paths",
            "cache": cache_state,
        }
        print(toon_encode(dashboard))
        print(toon_encode({"help": help_lines}))
        raise typer.Exit()

    age_str = format_age(info.age_seconds) if info.age_seconds else "unknown"

    org_rows = []
    raw_data = read_cache_raw()
    if raw_data:
        for org_data in raw_data.get("organizations", []):
            org_info = org_data.get("organization", {})
            name = org_info.get("display_name", "unknown")
            folder_count = len(org_data.get("folders", {}))
            project_count = len(org_data.get("projects", []))
            org_rows.append({
                "name": name,
                "folders": folder_count,
                "projects": project_count,
            })

    dashboard = {
        "bin": gcpath_bin,
        "description": "Query GCP resource hierarchy paths",
        "cache": f"fresh ({age_str} ago)",
    }
    if org_rows:
        dashboard["organizations"] = org_rows

    help_lines = [
        "Run `gcpath ls` to list root-level resources",
        "Run `gcpath ls -R` for recursive listing",
        "Run `gcpath find <pattern>` to search by name",
    ]
    print(toon_encode(dashboard))
    print(toon_encode({"help": help_lines}))
    raise typer.Exit()


@cache_app.command("clear")
def cache_clear(ctx: typer.Context) -> None:
    """Clear the local resource cache."""
    fmt = ctx.obj.get("output_format", "toon")
    if clear_cache():
        msg = f"Cache cleared at {CACHE_FILE}"
        if fmt == "rich":
            rprint(f"[green]{msg}[/green]")
        else:
            print(toon_confirmed(msg))
    else:
        msg = f"No cache file to clear at {CACHE_FILE}"
        if fmt == "rich":
            rprint(f"[yellow]{msg}[/yellow]")
        else:
            print(toon_confirmed(msg))


@cache_app.command("refresh")
def cache_refresh(ctx: typer.Context) -> None:
    """Re-load the hierarchy from GCP and rewrite the cache."""
    fmt = ctx.obj.get("output_format", "toon")
    try:
        ep = ctx.obj.get("entrypoint")
        _load_hierarchy(
            ctx,
            scope_resource=ep if ep else None,
            recursive=True,
            force_refresh=True,
            include_labels=True,
            include_tags=True,
        )
        info = get_cache_info()
        if not info.exists:
            print(toon_error(
                "Cache refresh failed: cache file was not written",
                [f"Check write permissions for {CACHE_FILE}"],
            ))
            raise typer.Exit(code=1)
        msg = (
            f"Cache refreshed: {info.org_count} organizations, "
            f"{info.folder_count} folders, {info.project_count} projects"
        )
        if fmt == "rich":
            rprint(f"[green]{msg}[/green]")
        else:
            print(toon_confirmed(msg))
    except typer.Exit:
        raise
    except Exception as e:
        handle_error(e)


def _cache_status_rich(info: Any) -> None:
    """Render cache status as a Rich table."""
    from rich.table import Table
    from rich.console import Console
    console = Console()
    if not info.exists:
        rprint(f"[yellow]No cache file found at {CACHE_FILE}[/yellow]")
        return
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Status", "[green]Fresh[/green]" if info.fresh else "[yellow]Stale[/yellow]")
    if info.age_seconds is not None:
        table.add_row("Age", format_age(info.age_seconds))
    if info.size_bytes is not None:
        size_kb = info.size_bytes / 1024
        size_str = f"{size_kb / 1024:.1f} MB" if size_kb >= 1024 else f"{size_kb:.1f} KB"
        table.add_row("Size", size_str)
    if info.version is not None:
        table.add_row("Version", str(info.version))
    if info.scope is not None:
        table.add_row("Scope", info.scope)
    table.add_row("Organizations", str(info.org_count))
    table.add_row("Folders", str(info.folder_count))
    table.add_row("Projects", str(info.project_count))
    table.add_row("Location", str(CACHE_FILE))
    console.print(table)


@cache_app.command("status")
def cache_status(ctx: typer.Context) -> None:
    """Show cache status information."""
    fmt = ctx.obj.get("output_format", "toon")
    info = get_cache_info()

    if fmt == "rich":
        _cache_status_rich(info)
        return

    print(toon_cache_status(
        exists=info.exists,
        fresh=info.fresh,
        age_seconds=info.age_seconds,
        size_bytes=info.size_bytes,
        version=info.version,
        scope=info.scope,
        org_count=info.org_count,
        folder_count=info.folder_count,
        project_count=info.project_count,
        location=str(CACHE_FILE),
    ))


@config_app.command("set-entrypoint")
def config_set_entrypoint(
    ctx: typer.Context,
    resource: Annotated[
        str,
        typer.Argument(
            help="Resource name to use as default entrypoint (e.g., folders/123)."
        ),
    ],
) -> None:
    """Set the default entrypoint resource."""
    fmt = ctx.obj.get("output_format", "toon")
    try:
        set_entrypoint(resource)
        msg = f"Entrypoint set to {resource}"
        if fmt == "rich":
            rprint(f"[green]{msg}[/green]")
        else:
            print(toon_confirmed(msg))
    except ValueError as e:
        if fmt == "rich":
            rprint(f"[red]Error:[/red] {e}")
        else:
            print(toon_error(str(e)))
        raise typer.Exit(code=1)


@config_app.command("show")
def config_show(ctx: typer.Context) -> None:
    """Show current configuration."""
    fmt = ctx.obj.get("output_format", "toon")
    config = read_config()

    if fmt == "rich":
        from rich.table import Table
        from rich.console import Console
        console = Console()
        if not config:
            rprint("[yellow]No configuration set.[/yellow]")
            rprint(f"[dim]Config file: {CONFIG_FILE}[/dim]")
            return
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Key", style="bold")
        table.add_column("Value")
        for key, value in config.items():
            table.add_row(key, str(value))
        table.add_row("location", str(CONFIG_FILE))
        console.print(table)
        return

    print(toon_config(config, str(CONFIG_FILE)))


@config_app.command("clear-entrypoint")
def config_clear_entrypoint(ctx: typer.Context) -> None:
    """Remove the default entrypoint."""
    fmt = ctx.obj.get("output_format", "toon")
    clear_entrypoint()
    msg = "Entrypoint cleared"
    if fmt == "rich":
        rprint(f"[green]{msg}[/green]")
    else:
        print(toon_confirmed(msg))


def _clean_resolve_path(path: str) -> str:
    if "_unknown_org_" in path:
        parts = path.split("/")
        cleaned = []
        for part in parts:
            if "_unknown_org_" in part:
                continue
            cleaned.append(part)
        result = "/".join(cleaned)
        if not result.startswith("//"):
            result = "//" + result.lstrip("/")
        return result
    return path


def _try_read_cache(
    cache_scope: Optional[str],
    filter_orgs: Optional[List[str]],
) -> Optional[Hierarchy]:
    cached_hierarchy = read_cache(scope=cache_scope)
    if cached_hierarchy is None:
        return None

    if filter_orgs:
        cached_hierarchy.organizations = [
            o
            for o in cached_hierarchy.organizations
            if o.organization.display_name in filter_orgs
        ]
    return cached_hierarchy


def _load_hierarchy(
    ctx: typer.Context,
    scope_resource: Optional[str],
    recursive: bool,
    force_refresh: bool,
    filter_orgs: Optional[List[str]] = None,
    include_labels: bool = False,
    include_tags: bool = False,
) -> Hierarchy:
    entrypoint = ctx.obj.get("entrypoint")

    is_cacheable = (scope_resource is None) or (
        entrypoint is not None and scope_resource == entrypoint
    )
    cache_scope = scope_resource if is_cacheable and scope_resource else None

    if is_cacheable and not force_refresh:
        cached = _try_read_cache(cache_scope, filter_orgs)
        if cached is not None:
            info = get_cache_info()
            if info.age_seconds is not None:
                logger.debug(f"Using cached data ({format_age(info.age_seconds)} ago). Use -F to refresh.")
            return cached

    effective_recursive = True if is_cacheable else recursive

    hierarchy = Hierarchy.load(
        display_names=filter_orgs,
        via_resource_manager=not ctx.obj["use_asset_api"],
        scope_resource=scope_resource,
        recursive=effective_recursive,
        include_labels=include_labels,
        include_tags=include_tags,
    )

    if is_cacheable:
        write_cache(hierarchy, scope=cache_scope)

    return hierarchy


@dataclass
class _HierarchyCommandContext:
    hierarchy: Hierarchy
    nodes_to_process: List[Union[OrganizationNode, Folder]]
    projects_by_parent: Dict[str, List[Project]]
    target_resource_name: Optional[str]
    target_path: Optional[str]


@dataclass
class _ParsedResource:
    target_resource_name: Optional[str]
    target_org_name: Optional[str]
    target_path: Optional[str]


def _parse_resource_arg(effective_resource: str, command_name: str) -> _ParsedResource:
    if effective_resource.startswith(_RESOURCE_PREFIX_PROJECTS):
        print(toon_error(
            f"'{command_name}' command does not support starting from a project (projects are leaf nodes)."
        ))
        raise typer.Exit(code=1)

    target_org_name = None
    target_resource_name = None
    target_path = None

    try:
        target_path = _clean_resolve_path(
            Hierarchy.resolve_ancestry(effective_resource)
        )
        if target_path.startswith("//"):
            path_parts = target_path[2:].split("/")
            if path_parts:
                target_org_name = unquote(path_parts[0])

        if effective_resource.startswith(
            (_RESOURCE_PREFIX_FOLDERS, _RESOURCE_PREFIX_ORGS)
        ):
            target_resource_name = effective_resource
    except (gcp_exceptions.PermissionDenied, gcp_exceptions.NotFound, GCPathError):
        if effective_resource.startswith("//"):
            target_path = effective_resource
        else:
            raise

    return _ParsedResource(target_resource_name, target_org_name, target_path)


def _find_target_nodes(
    hierarchy: Hierarchy,
    target_resource_name: str,
    target_path: Optional[str],
) -> List[Union[OrganizationNode, Folder]]:
    if target_resource_name.startswith(_RESOURCE_PREFIX_ORGS):
        for o in hierarchy.organizations:
            if o.organization.name == target_resource_name:
                return [o]
        return []

    for o in hierarchy.organizations:
        if target_resource_name in o.folders:
            return [o.folders[target_resource_name]]

    if not target_path or not hierarchy.organizations:
        return []

    path_parts = target_path[2:].split("/") if target_path.startswith("//") else []
    display_name = path_parts[-1] if path_parts else target_resource_name.split("/")[-1]

    org_node = hierarchy.organizations[0]
    synthetic_folder = Folder(
        name=target_resource_name,
        display_name=display_name,
        ancestors=[target_resource_name, org_node.organization.name],
        organization=org_node,
        parent=org_node.organization.name,
    )
    org_node.folders[target_resource_name] = synthetic_folder
    return [synthetic_folder]


def _prepare_hierarchy_command(
    ctx: typer.Context,
    command_name: str,
    resource: Optional[str],
    force_refresh: bool,
    include_labels: bool = False,
    include_tags: bool = False,
) -> Optional[_HierarchyCommandContext]:
    ep = ctx.obj.get("entrypoint")
    effective_resource = resource or ep

    parsed = _ParsedResource(None, None, None)
    if effective_resource:
        parsed = _parse_resource_arg(effective_resource, command_name)

    if not resource and ep and parsed.target_org_name:
        filter_orgs = None
    else:
        filter_orgs = [parsed.target_org_name] if parsed.target_org_name else None

    hierarchy = _load_hierarchy(
        ctx,
        scope_resource=parsed.target_resource_name,
        recursive=True,
        force_refresh=force_refresh,
        filter_orgs=filter_orgs,
        include_labels=include_labels,
        include_tags=include_tags,
    )

    if parsed.target_resource_name:
        nodes_to_process = _find_target_nodes(
            hierarchy,
            parsed.target_resource_name,
            parsed.target_path,
        )
        if not nodes_to_process:
            print(toon_error(f"Target resource '{parsed.target_resource_name}' not found."))
            raise typer.Exit(code=1)
    else:
        nodes_to_process = list(hierarchy.organizations)

    projects_by_parent: Dict[str, List[Project]] = {}
    for proj in hierarchy.projects:
        projects_by_parent.setdefault(proj.parent, []).append(proj)

    return _HierarchyCommandContext(
        hierarchy=hierarchy,
        nodes_to_process=nodes_to_process,
        projects_by_parent=projects_by_parent,
        target_resource_name=parsed.target_resource_name,
        target_path=parsed.target_path,
    )


def _handle_empty_hierarchy(fmt: str) -> None:
    if fmt in ("json", "yaml"):
        dumper = _get_dumper(fmt)
        if dumper:
            print(dumper([]))
        return

    if fmt == "rich":
        import google.auth
        account_msg = ""
        try:
            credentials, _ = google.auth.default()
            if hasattr(credentials, "account") and credentials.account:
                if credentials.account.endswith("@gmail.com"):
                    account_msg = f" (Account: {credentials.account})"
        except Exception:
            pass
        rprint(
            f"[yellow]No organizations or projects found accessible to your account{account_msg}.[/yellow]"
        )
        if not account_msg:
            rprint(
                "[dim]Hint: You might not have access to any organizations. "
                "Projects without organizations are shown with //_ prefix.[/dim]"
            )
        return

    print(toon_error(
        "No organizations or projects found accessible to your account",
        ["Projects without organizations are shown with //_ prefix"],
    ))


def _resolve_target_path_prefix(target_resource_name: Optional[str]) -> str:
    if not target_resource_name:
        return ""
    try:
        return _clean_resolve_path(Hierarchy.resolve_ancestry(target_resource_name))
    except (GCPathError, gcp_exceptions.GoogleAPICallError) as e:
        logger.warning(f"Could not resolve target path: {e}")
        return ""


def _get_resource_name(obj: Union[OrganizationNode, Folder, Project]) -> str:
    if isinstance(obj, OrganizationNode):
        return obj.organization.name
    return obj.name


def _apply_ls_filters(
    items: list,
    resource_type: Optional[str],
    label_filters: Optional[List[str]],
    tag_filters: Optional[List[str]],
) -> list:
    if resource_type:
        items = [(p, obj) for p, obj in items if _matches_type(obj, resource_type)]
    if label_filters:
        items = [
            (p, obj)
            for p, obj in items
            if _matches_metadata(obj, label_filters, "labels")
        ]
    if tag_filters:
        items = [
            (p, obj) for p, obj in items if _matches_metadata(obj, tag_filters, "tags")
        ]
    return items


def _apply_depth_limit(
    items: list,
    level: Optional[int],
    recursive: bool,
    target_path_prefix: str,
) -> list:
    if level is None or not recursive:
        return items
    base_segments = len(target_path_prefix.split("/")) - 3 if target_path_prefix else 0
    return [
        (p, obj) for p, obj in items if len(p.split("/")) - 3 - base_segments <= level
    ]


def _build_ls_items(
    hierarchy: Hierarchy,
    target_resource_name: Optional[str],
    target_path_prefix: str,
    recursive: bool,
    resource_type: Optional[str],
    label_filters: Optional[List[str]],
    tag_filters: Optional[List[str]],
    level: Optional[int],
) -> Tuple[list, int]:
    """Build ls items and return (filtered_items, total_before_filtering)."""
    current_folders, current_projects = filter_direct_children(
        hierarchy, target_resource_name
    )
    items = build_items_list(
        hierarchy,
        current_folders,
        current_projects,
        target_path_prefix,
        target_resource_name,
        recursive,
    )
    items = sort_resources(items)
    total_in_scope = len(items)
    items = _apply_ls_filters(items, resource_type, label_filters, tag_filters)
    items = _apply_depth_limit(items, level, recursive, target_path_prefix)
    return items, total_in_scope


def _ls_help_lines(recursive: bool) -> List[str]:
    lines = []
    if not recursive:
        lines.append("Run `gcpath ls <resource> -R` for nested listing")
    else:
        lines.append("Run `gcpath ls <resource>` for direct children only")
    lines.append("Run `gcpath find <pattern>` to search by name")
    return lines


def _format_metadata(obj: Union[OrganizationNode, Folder, Project], attr: str) -> str:
    metadata = getattr(obj, attr, {})
    if not metadata:
        return ""
    return ", ".join(f"{k}={v}" for k, v in sorted(metadata.items()))


def _display_ls_rich(
    items: list,
    show_labels: bool,
    show_tags: bool,
) -> None:
    from rich.table import Table
    from rich.console import Console
    console = Console()

    table = Table(
        show_header=True, header_style=_RICH_HEADER_STYLE, box=None, padding=(0, 1)
    )
    table.add_column("Path", overflow="fold")
    table.add_column("Type", overflow="fold")
    table.add_column("Display Name", overflow="fold")
    table.add_column("Resource Name", overflow="fold")
    if show_labels:
        table.add_column("Labels", overflow="fold")
    if show_tags:
        table.add_column("Tags", overflow="fold")

    for path, obj in items:
        row = [path, get_resource_type(obj)]
        if isinstance(obj, OrganizationNode):
            row.append(obj.organization.display_name)
        else:
            row.append(obj.display_name)
        row.append(_get_resource_name(obj))
        if show_labels:
            row.append(_format_metadata(obj, "labels"))
        if show_tags:
            row.append(_format_metadata(obj, "tags"))
        table.add_row(*row)

    console.print(table)


def _parse_fields(fields_str: Optional[str]) -> Optional[Tuple[str, ...]]:
    if not fields_str:
        return None
    fields = tuple(f.strip() for f in fields_str.split(","))
    for f in fields:
        if f not in _ALL_LS_FIELDS:
            print(toon_error(f"Unknown field '{f}'. Available fields: {', '.join(_ALL_LS_FIELDS)}"))
            raise typer.Exit(code=1)
    return fields


@app.command()
def ls(
    ctx: typer.Context,
    resource: Annotated[
        Optional[str],
        typer.Argument(
            help="Resource name (e.g. folders/123) or path to list children from."
        ),
    ] = None,
    recursive: bool = typer.Option(
        False, "--recursive", "-R", help="List resources recursively"
    ),
    resource_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter by resource type: folder, project, organization",
    ),
    level: Optional[int] = typer.Option(
        None, "--level", "-L", help="Max depth for recursive listing (requires -R)"
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        "-F",
        help=_REFRESH_HELP,
    ),
    show_labels: bool = typer.Option(
        False, "--show-labels", help="Display GCP labels on resources"
    ),
    show_tags: bool = typer.Option(
        False, "--show-tags", help="Display GCP resource tags"
    ),
    label_filters: Optional[List[str]] = typer.Option(
        None, "--label", help="Filter by label (key=value). Repeatable, ANDed together"
    ),
    tag_filters: Optional[List[str]] = typer.Option(
        None, "--tag", help="Filter by tag (key=value). Repeatable, ANDed together"
    ),
    fields: Optional[str] = typer.Option(
        None, "--fields", help=f"Comma-separated fields to show: {', '.join(_ALL_LS_FIELDS)}"
    ),
    full: bool = typer.Option(
        False, "--full", help="Show all labels/tags without truncation"
    ),
) -> None:
    """List folders and projects. Defaults to the root organization."""
    try:
        _validate_type_filter(resource_type)

        parsed_fields = _parse_fields(fields)
        needs_labels = parsed_fields is not None and "labels" in parsed_fields
        needs_tags = parsed_fields is not None and "tags" in parsed_fields
        include_labels = show_labels or bool(label_filters) or needs_labels
        include_tags = show_tags or bool(tag_filters) or needs_tags

        ep = ctx.obj.get("entrypoint")
        scope = _resolve_scope(resource, ep)
        target_resource_name = scope.target_resource_name

        hierarchy = _load_hierarchy(
            ctx,
            scope_resource=target_resource_name,
            recursive=recursive,
            force_refresh=force_refresh,
            filter_orgs=scope.filter_orgs,
            include_labels=include_labels,
            include_tags=include_tags,
        )

        fmt = ctx.obj.get("output_format", "toon")

        if not hierarchy.organizations and not hierarchy.projects:
            _handle_empty_hierarchy(fmt)
            return

        if target_resource_name and target_resource_name.startswith(
            _RESOURCE_PREFIX_PROJECTS
        ):
            return

        target_path_prefix = _resolve_target_path_prefix(target_resource_name)

        items, total = _build_ls_items(
            hierarchy,
            target_resource_name,
            target_path_prefix,
            recursive,
            resource_type,
            label_filters,
            tag_filters,
            level,
        )

        if fmt == "rich":
            _display_ls_rich(items, show_labels, show_tags)
            return

        if fmt in ("json", "yaml"):
            dumper = _get_dumper(fmt)
            if dumper:
                print(dumper(serialize_ls(items)))
            return

        help_lines = _ls_help_lines(recursive)
        print(toon_ls(items, total, fields=parsed_fields, full=full, help_lines=help_lines))

    except Exception as e:
        handle_error(e)


def _get_orgless_projects(hctx: _HierarchyCommandContext) -> Optional[List[Project]]:
    if hctx.target_resource_name:
        return None
    orgless = [p for p in hctx.hierarchy.projects if not p.organization]
    return orgless or None


def _tree_root_label(
    node: Union[OrganizationNode, Folder],
    is_targeted: Optional[str],
) -> tuple[str, str]:
    if isinstance(node, OrganizationNode):
        safe_path = f"//{path_escape(node.organization.display_name)}"
        color = "cyan" if is_targeted else "magenta"
        return f"[bold {color}]{safe_path}[/bold {color}]", node.organization.name
    return f"[bold cyan]{node.path}[/bold cyan]", node.name


def _add_orgless_tree_nodes(
    root_tree,
    orgless_projects: Optional[List[Project]],
    resource_type: Optional[str],
    level: Optional[int],
    show_ids: bool,
    show_labels: bool,
    show_tags: bool,
) -> None:
    if not orgless_projects or resource_type == "folder":
        return
    orgless_node = root_tree.add("[bold yellow](organizationless)[/bold yellow]")
    if level is not None and level < 1:
        return
    for p in sorted(orgless_projects, key=lambda x: x.display_name):
        orgless_node.add(format_tree_label(p, show_ids, show_labels, show_tags))


@app.command()
def tree(
    ctx: typer.Context,
    resource: Annotated[
        Optional[str],
        typer.Argument(
            help="Resource name (e.g. folders/123) or path to start tree from."
        ),
    ] = None,
    level: int = typer.Option(
        None,
        "--level",
        "-L",
        help="Max display depth of the tree (no limit by default)",
    ),
    show_ids: bool = typer.Option(
        False, "--ids", "-i", help="Show resource names in the tree"
    ),
    resource_type: Optional[str] = typer.Option(
        None, "--type", "-t", help="Filter by resource type: folder, project"
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        "-F",
        help=_REFRESH_HELP,
    ),
    show_labels: bool = typer.Option(
        False, "--show-labels", help="Display GCP labels on resources"
    ),
    show_tags: bool = typer.Option(
        False, "--show-tags", help="Display GCP resource tags"
    ),
    label_filters: Optional[List[str]] = typer.Option(
        None, "--label", help="Filter by label (key=value). Repeatable, ANDed together"
    ),
    tag_filters: Optional[List[str]] = typer.Option(
        None, "--tag", help="Filter by tag (key=value). Repeatable, ANDed together"
    ),
) -> None:
    """Display the resource hierarchy in a tree format (human-oriented).

    Agents: use `gcpath ls -R` for structured output instead.
    """
    from rich.tree import Tree

    try:
        _validate_type_filter(resource_type)

        include_labels = show_labels or bool(label_filters)
        include_tags = show_tags or bool(tag_filters)

        hctx = _prepare_hierarchy_command(
            ctx,
            "tree",
            resource,
            force_refresh,
            include_labels=include_labels,
            include_tags=include_tags,
        )
        if hctx is None:
            return

        orgless_projects = _get_orgless_projects(hctx)
        fmt = ctx.obj.get("output_format", "toon")

        if fmt in ("json", "yaml"):
            dumper = _get_dumper(fmt)
            if dumper:
                data = serialize_tree(
                    hctx.nodes_to_process,
                    hctx.projects_by_parent,
                    level,
                    orgless_projects,
                    type_filter=resource_type,
                )
                print(dumper(data))
            return

        root_tree = Tree(
            "[bold cyan]Query Result[/bold cyan]"
            if hctx.target_resource_name
            else "[bold cyan]GCP Hierarchy[/bold cyan]"
        )

        for node in hctx.nodes_to_process:
            label, node_id = _tree_root_label(node, hctx.target_resource_name)
            if show_ids:
                label += f" [dim]({node_id})[/dim]"

            node_tree = root_tree.add(label)
            build_tree_view(
                node_tree,
                node,
                hctx.hierarchy,
                hctx.projects_by_parent,
                level,
                0,
                show_ids,
                type_filter=resource_type,
                show_labels=show_labels,
                show_tags=show_tags,
            )

        _add_orgless_tree_nodes(
            root_tree,
            orgless_projects,
            resource_type,
            level,
            show_ids,
            show_labels,
            show_tags,
        )

        from rich.console import Console
        Console().print(root_tree)

    except Exception as e:
        handle_error(e)


@app.command()
def diagram(
    ctx: typer.Context,
    resource: Annotated[
        Optional[str],
        typer.Argument(
            help="Resource name (e.g. folders/123) or path to generate diagram from."
        ),
    ] = None,
    diagram_format: str = typer.Option(
        "mermaid",
        "--diagram-format",
        "-d",
        help="Diagram output format: mermaid or d2",
    ),
    level: int = typer.Option(
        None,
        "--level",
        "-L",
        help="Max display depth of the diagram (no limit by default)",
    ),
    show_ids: bool = typer.Option(
        False, "--ids", "-i", help="Show resource names in node labels"
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Write diagram to a file instead of stdout"
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        "-F",
        help=_REFRESH_HELP,
    ),
) -> None:
    """Generate a Mermaid or D2 diagram of the resource hierarchy."""
    try:
        if diagram_format not in ("mermaid", "d2"):
            print(toon_error(f"Unsupported diagram format '{diagram_format}'. Use 'mermaid' or 'd2'."))
            raise typer.Exit(code=1)

        hctx = _prepare_hierarchy_command(
            ctx, "diagram", resource, force_refresh
        )
        if hctx is None:
            return

        orgless_projects = None
        if not hctx.target_resource_name:
            orgless = [p for p in hctx.hierarchy.projects if not p.organization]
            if orgless:
                orgless_projects = orgless

        diagram_output = build_diagram(
            hctx.nodes_to_process,
            hctx.hierarchy,
            hctx.projects_by_parent,
            fmt=diagram_format,
            level=level,
            show_ids=show_ids,
            orgless_projects=orgless_projects,
        )

        if output:
            with open(output, "w", encoding="utf-8") as f:
                f.write(diagram_output + "\n")
            output_fmt = ctx.obj.get("output_format", "toon")
            if output_fmt == "rich":
                rprint(f"[green]Diagram written to {output}[/green]")
            else:
                print(toon_confirmed(f"Diagram written to {output}"))
        else:
            print(diagram_output)

    except Exception as e:
        handle_error(e)


def _validate_stats_resource(effective_resource: Optional[str]) -> Optional[str]:
    """Validate and return the target resource name for stats command."""
    if not effective_resource:
        return None
    if effective_resource.startswith("projects/"):
        print(toon_error("'stats' command does not support starting from a project."))
        raise typer.Exit(code=1)
    if any(effective_resource.startswith(p) for p in [_RESOURCE_PREFIX_ORGS, _RESOURCE_PREFIX_FOLDERS]):
        return effective_resource
    print(toon_error(
        f"Invalid resource format '{effective_resource}'. Expected 'organizations/...' or 'folders/...'."
    ))
    raise typer.Exit(code=1)


def _stats_rich(
    scope_label: str, org_count: int, folder_count: int, project_count: int,
    target_resource_name: Optional[str],
) -> None:
    """Render stats as a Rich table."""
    from rich.table import Table
    from rich.console import Console
    from rich.markup import escape
    console = Console()
    rprint(f"[bold]Scope:[/bold] {escape(scope_label)}")
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Resource", style="bold")
    table.add_column("Count", justify="right")
    if not target_resource_name or target_resource_name.startswith(_RESOURCE_PREFIX_ORGS):
        table.add_row("Organizations", str(org_count))
    table.add_row("Folders", str(folder_count))
    table.add_row("Projects", str(project_count))
    console.print(table)


@app.command()
def stats(
    ctx: typer.Context,
    resource: Annotated[
        Optional[str],
        typer.Argument(
            help="Resource name (e.g. folders/123 or organizations/456) to scope statistics to."
        ),
    ] = None,
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        "-F",
        help=_REFRESH_HELP,
    ),
) -> None:
    """Show statistics about folders and projects in a scope."""
    try:
        ep = ctx.obj.get("entrypoint")
        target_resource_name = _validate_stats_resource(resource or ep)

        hierarchy = _load_hierarchy(
            ctx,
            scope_resource=target_resource_name,
            recursive=True,
            force_refresh=force_refresh,
        )

        folder_count = len(hierarchy.folders)
        project_count = len(hierarchy.projects)
        org_count = len(hierarchy.organizations)
        scope_label = target_resource_name or _SCOPE_ALL_ORGS

        fmt = ctx.obj.get("output_format", "toon")

        if fmt == "rich":
            _stats_rich(scope_label, org_count, folder_count, project_count, target_resource_name)
            return

        if fmt in ("json", "yaml"):
            dumper = _get_dumper(fmt)
            if dumper:
                print(dumper({"scope": scope_label, "organizations": org_count, "folders": folder_count, "projects": project_count}))
            return

        help_lines = ["Run `gcpath stats` for all-organization statistics"] if target_resource_name else []
        print(toon_stats(
            scope=scope_label,
            organizations=org_count,
            folders=folder_count,
            projects=project_count,
            help_lines=help_lines or None,
        ))

    except Exception as e:
        handle_error(e)


@app.command(name="summary")
def summary_command(
    ctx: typer.Context,
    resource: Annotated[
        Optional[str],
        typer.Argument(
            help="Resource to scope the summary to (e.g. organizations/123 or folders/456)."
        ),
    ] = None,
    top: int = typer.Option(
        5, "--top", help="How many top label/tag keys to include"
    ),
    force_refresh: bool = typer.Option(
        False, "--force-refresh", "-F", help=_REFRESH_HELP
    ),
) -> None:
    """One-shot snapshot of the hierarchy: counts, depth, top labels/tags."""
    try:
        ep = ctx.obj.get("entrypoint")
        scope = _resolve_scope(resource, ep)

        hierarchy = _load_hierarchy(
            ctx,
            scope_resource=scope.target_resource_name,
            recursive=True,
            force_refresh=force_refresh,
            filter_orgs=scope.filter_orgs,
            include_labels=True,
            include_tags=True,
        )

        data = hierarchy.summary(top_n=top)
        data["scope"] = scope.target_resource_name or _SCOPE_ALL_ORGS

        fmt = ctx.obj.get("output_format", "toon")
        if fmt in ("json", "yaml"):
            dumper = _get_dumper(fmt)
            if dumper:
                print(dumper(data))
            return

        if fmt == "rich":
            _render_summary_rich(data)
            return

        help_lines = [
            "Run `gcpath stats <scope>` for raw counts",
            "Run `gcpath labels --top 10` for full label breakdown",
        ]
        print(toon_summary(data, help_lines=help_lines))

    except Exception as e:
        handle_error(e)


def _render_summary_rich(data: Dict[str, Any]) -> None:
    from rich.table import Table
    from rich.console import Console

    console = Console()
    rprint(f"[bold]Scope:[/bold] {data['scope']}")
    counts = Table(show_header=False, box=None, padding=(0, 1))
    counts.add_column("Key", style="bold")
    counts.add_column("Value", justify="right")
    counts.add_row("Organizations", str(data["org_count"]))
    counts.add_row("Folders", str(data["folder_count"]))
    counts.add_row("Projects", str(data["project_count"]))
    counts.add_row("Max depth", str(data["max_depth"]))
    console.print(counts)
    if data["top_label_keys"]:
        rprint("[bold]Top label keys:[/bold]")
        for row in data["top_label_keys"]:
            rprint(f"  {row['key']}: {row['count']}")
    if data["top_tag_keys"]:
        rprint("[bold]Top tag keys:[/bold]")
        for row in data["top_tag_keys"]:
            rprint(f"  {row['key']}: {row['count']}")


_VALID_AUDIT_SEVERITIES = ("info", "warn", "error")
_VALID_AUDIT_CHECKS = (
    "orphan_project",
    "synthetic_org",
    "missing_required_label",
    "duplicate_display_name",
    "name_pattern_violation",
)


@app.command(name="audit")
def audit_command(
    ctx: typer.Context,
    resource: Annotated[
        Optional[str],
        typer.Argument(help="Resource to scope the audit (e.g. folders/123)"),
    ] = None,
    require_labels: Optional[str] = typer.Option(
        None,
        "--require-labels",
        help="Comma-separated list of label keys that every folder/project must have",
    ),
    name_pattern: Optional[str] = typer.Option(
        None,
        "--name-pattern",
        help="Regex that every display_name must fullmatch",
    ),
    severity: str = typer.Option(
        "info",
        "--severity",
        help=f"Minimum severity to report: {', '.join(_VALID_AUDIT_SEVERITIES)}",
    ),
    checks: Optional[str] = typer.Option(
        None,
        "--check",
        help=f"Comma-separated subset of checks: {', '.join(_VALID_AUDIT_CHECKS)}",
    ),
    exit_zero: bool = typer.Option(
        False,
        "--exit-zero",
        help="Always exit 0 (default: exit 1 on warn/error)",
    ),
    force_refresh: bool = typer.Option(
        False, "--force-refresh", "-F", help=_REFRESH_HELP
    ),
) -> None:
    """Run governance checks against the loaded hierarchy."""
    try:
        if severity not in _VALID_AUDIT_SEVERITIES:
            print(toon_error(
                f"Invalid severity '{severity}'. Must be one of: "
                + ", ".join(_VALID_AUDIT_SEVERITIES)
            ))
            raise typer.Exit(code=1)

        required_label_keys = _parse_required_labels(require_labels)
        check_subset = _parse_audit_check_subset(checks)
        _validate_audit_check_inputs(
            check_subset, required_label_keys, name_pattern
        )

        ep = ctx.obj.get("entrypoint")
        scope = _resolve_scope(resource, ep)

        hierarchy = _load_hierarchy(
            ctx,
            scope_resource=scope.target_resource_name,
            recursive=True,
            force_refresh=force_refresh,
            filter_orgs=scope.filter_orgs,
            include_labels=bool(required_label_keys),
        )

        issues = run_audit(
            hierarchy,
            require_labels=required_label_keys,
            name_pattern=name_pattern,
            checks=check_subset,
            severity=severity,
        )
        sev_counts = summarize_severities(issues)

        scope_label = scope.target_resource_name or _SCOPE_ALL_ORGS
        _render_audit(ctx, issues, sev_counts, scope_label)

        if not exit_zero and (sev_counts.get("error", 0) or sev_counts.get("warn", 0)):
            raise typer.Exit(code=1)

    except typer.Exit:
        raise
    except Exception as e:
        handle_error(e)


def _parse_required_labels(require_labels: Optional[str]) -> Optional[List[str]]:
    if not require_labels:
        return None
    return [k.strip() for k in require_labels.split(",") if k.strip()] or None


def _parse_audit_check_subset(checks: Optional[str]) -> Optional[List[str]]:
    if not checks:
        return None
    subset = [c.strip() for c in checks.split(",") if c.strip()]
    for c in subset:
        if c not in _VALID_AUDIT_CHECKS:
            print(toon_error(
                f"Unknown check '{c}'. Available: "
                + ", ".join(_VALID_AUDIT_CHECKS)
            ))
            raise typer.Exit(code=1)
    return subset


def _validate_audit_check_inputs(
    check_subset: Optional[List[str]],
    required_label_keys: Optional[List[str]],
    name_pattern: Optional[str],
) -> None:
    """Reject combinations that would silently disable a requested check."""
    if check_subset and "missing_required_label" in check_subset and not required_label_keys:
        print(toon_error(
            "--require-labels is required when running the missing_required_label check"
        ))
        raise typer.Exit(code=1)
    if check_subset and "name_pattern_violation" in check_subset and not name_pattern:
        print(toon_error(
            "--name-pattern is required when running the name_pattern_violation check"
        ))
        raise typer.Exit(code=1)
    if name_pattern is not None and len(name_pattern) > _NAME_PATTERN_MAX_LEN:
        print(toon_error(
            f"--name-pattern is too long ({len(name_pattern)} chars, "
            f"max {_NAME_PATTERN_MAX_LEN}); rejected to limit ReDoS risk"
        ))
        raise typer.Exit(code=1)


def _render_audit(
    ctx: typer.Context,
    issues: List[Dict[str, Any]],
    sev_counts: Dict[str, int],
    scope_label: str,
) -> None:
    fmt = ctx.obj.get("output_format", "toon")
    if fmt in ("json", "yaml"):
        dumper = _get_dumper(fmt)
        if dumper:
            print(dumper({
                "scope": scope_label,
                "severity_counts": sev_counts,
                "issues": issues,
            }))
        return
    if fmt == "rich":
        _render_audit_rich(issues)
        return
    help_lines = [
        "Run `gcpath ls --label <K>=<V>` to inspect resources by label",
        "Run `gcpath open <path>` to jump to an offending resource",
    ]
    print(toon_audit(issues, sev_counts, help_lines=help_lines))


def _render_audit_rich(issues: List[Dict[str, Any]]) -> None:
    from rich.table import Table
    from rich.console import Console

    console = Console()
    if not issues:
        rprint("[green]No audit issues found.[/green]")
        return
    table = Table(
        show_header=True,
        header_style=_RICH_HEADER_STYLE,
        box=None,
        padding=(0, 1),
    )
    table.add_column("Severity")
    table.add_column("Check")
    table.add_column("Path", overflow="fold")
    table.add_column("Type")
    table.add_column("Details", overflow="fold")
    color_map = {"error": "red", "warn": "yellow", "info": "cyan"}
    for issue in issues:
        color = color_map.get(issue["severity"], "white")
        table.add_row(
            f"[{color}]{issue['severity']}[/{color}]",
            issue["check"],
            issue["path"],
            issue["type"],
            issue["details"],
        )
    console.print(table)


@app.command(name="name")
def get_resource_name(
    ctx: typer.Context,
    paths: Annotated[
        List[str], typer.Argument(help="Paths to resolve, e.g. //example.com/folder")
    ],
    id_only: bool = typer.Option(
        False, "--id", help="Print only the resource ID number"
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        "-F",
        help=_REFRESH_HELP,
    ),
) -> None:
    """Get Google Cloud Platform resource name by path."""
    try:
        ep = ctx.obj.get("entrypoint")
        scope = ep if ep else None
        logger.debug(f"name: resolving paths={paths}, scope={scope}")
        hierarchy = _load_hierarchy(
            ctx,
            scope_resource=scope,
            recursive=True,
            force_refresh=force_refresh,
        )

        logger.debug("name: hierarchy loaded successfully")

        fmt = ctx.obj.get("output_format", "toon")
        results: List[tuple[str, str]] = []
        for path in paths:
            logger.debug(f"name command: resolving path {path}")
            res_name = hierarchy.get_resource_name(path)
            logger.debug(f"name command: resolved {path} to {res_name}")
            results.append((path, res_name))

        if fmt in ("json", "yaml"):
            dumper = _get_dumper(fmt)
            if dumper:
                print(dumper(serialize_name_results(results, id_only)))
            return

        if fmt == "rich":
            for _path, res_name in results:
                if id_only:
                    res_name = res_name.split("/")[-1]
                print(res_name)
            return

        print(toon_name(results, id_only))

    except Exception as e:
        handle_error(e)


def _find_loaded_org(
    hierarchy: Hierarchy, res_name: str
) -> Optional[OrganizationNode]:
    for org in hierarchy.organizations:
        if org.organization.name == res_name:
            return org
    return None


def _find_loaded_folder(
    hierarchy: Hierarchy, res_name: str
) -> Optional[Folder]:
    for org in hierarchy.organizations:
        if res_name in org.folders:
            return org.folders[res_name]
    return None


def _find_loaded_project(
    hierarchy: Hierarchy, res_name: str
) -> Optional[Project]:
    for proj in hierarchy.projects:
        if proj.name == res_name:
            return proj
    return None


def _resolve_path_to_object(
    hierarchy: Hierarchy, path: str
) -> Union[OrganizationNode, Folder, Project]:
    """Resolve a gcpath path to the underlying resource object."""
    res_name = hierarchy.get_resource_name(path)
    if res_name.startswith(_RESOURCE_PREFIX_ORGS):
        org = _find_loaded_org(hierarchy, res_name)
        if org is not None:
            return org
        raise GCPathError(f"Organization '{res_name}' not found in loaded hierarchy")
    if res_name.startswith(_RESOURCE_PREFIX_FOLDERS):
        folder = _find_loaded_folder(hierarchy, res_name)
        if folder is not None:
            return folder
        raise GCPathError(f"Folder '{res_name}' not found in loaded hierarchy")
    if res_name.startswith(_RESOURCE_PREFIX_PROJECTS):
        project = _find_loaded_project(hierarchy, res_name)
        if project is not None:
            return project
        raise GCPathError(f"Project '{res_name}' not found in loaded hierarchy")
    raise GCPathError(f"Unsupported resource name '{res_name}'")


@app.command(name="open")
def open_resource(
    ctx: typer.Context,
    paths: Annotated[
        List[str],
        typer.Argument(help="Paths to open in the GCP Console, e.g. //example.com/folder"),
    ],
    browser: bool = typer.Option(
        False,
        "--browser/--print",
        help="Open the URL in a browser instead of printing it",
    ),
    force_refresh: bool = typer.Option(
        False, "--force-refresh", "-F", help=_REFRESH_HELP
    ),
) -> None:
    """Print or open the GCP Cloud Console URL for one or more paths."""
    try:
        ep = ctx.obj.get("entrypoint")
        scope = ep if ep else None
        hierarchy = _load_hierarchy(
            ctx,
            scope_resource=scope,
            recursive=True,
            force_refresh=force_refresh,
        )

        results = _resolve_open_paths(hierarchy, paths)

        if browser:
            _handle_browser_open(ctx, results)
            return

        _render_open_results(ctx, results)

    except Exception as e:
        handle_error(e)


def _resolve_open_paths(
    hierarchy: Hierarchy, paths: List[str]
) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    for path in paths:
        try:
            item = _resolve_path_to_object(hierarchy, path)
            url = console_url(item)
            resource_name = (
                item.organization.name
                if isinstance(item, OrganizationNode)
                else item.name
            )
            results.append({"path": path, "resource_name": resource_name, "url": url})
        except GCPathError as e:
            if len(paths) > 1:
                results.append({"path": path, "resource_name": "", "url": "", "error": str(e)})
            else:
                raise
    return results


def _handle_browser_open(
    ctx: typer.Context, results: List[Dict[str, str]]
) -> None:
    import webbrowser

    opened = 0
    for row in results:
        url = row.get("url") or ""
        if not url:
            continue
        try:
            if webbrowser.open(url):
                opened += 1
        except webbrowser.Error as e:
            logger.warning(f"webbrowser.open failed for {url}: {e}")

    if opened == 0 and results:
        help_lines = [
            "No browser available; URL printed below.",
            "Re-run without --browser to print only.",
        ]
        _print_open_payload(ctx, results, help_lines)
        return

    # Always surface error rows so partial-success doesn't swallow failures.
    error_rows = [r for r in results if r.get("error")]
    if error_rows:
        _print_open_payload(
            ctx, error_rows, ["Some paths could not be resolved"]
        )


def _render_open_results(
    ctx: typer.Context, results: List[Dict[str, str]]
) -> None:
    fmt = ctx.obj.get("output_format", "toon")
    if fmt in ("json", "yaml"):
        dumper = _get_dumper(fmt)
        if dumper:
            print(dumper(serialize_open_results(results)))
        return
    if fmt == "rich":
        for row in results:
            if row.get("url"):
                print(row["url"])
            elif row.get("error"):
                rprint(f"[red]{row['path']}: {row['error']}[/red]")
        return
    help_lines = ["Run `gcpath open <path> --browser` to open in your default browser"]
    print(toon_open(results, help_lines=help_lines))


def _print_open_payload(
    ctx: typer.Context,
    results: List[Dict[str, str]],
    help_lines: List[str],
) -> None:
    fmt = ctx.obj.get("output_format", "toon")
    if fmt in ("json", "yaml"):
        dumper = _get_dumper(fmt)
        if dumper:
            print(dumper(serialize_open_results(results)))
        return
    print(toon_open(results, help_lines=help_lines))


@app.command(name="path")
def get_path_command(
    ctx: typer.Context,
    resource_names: Annotated[
        List[str], typer.Argument(help="Resource names to resolve, e.g. folders/123")
    ],
) -> None:
    """Get path of a resource name."""
    try:
        logger.debug(f"path: resolving resource_names={resource_names}")
        fmt = ctx.obj.get("output_format", "toon")
        results: List[tuple[str, str]] = []

        for name in resource_names:
            try:
                p = Hierarchy.resolve_ancestry(name)
                logger.debug(f"path: resolved {name} to {p}")
                results.append((name, p))
            except (gcp_exceptions.NotFound, gcp_exceptions.PermissionDenied, GCPathError) as e:
                if len(resource_names) > 1:
                    print(toon_error(f"Error resolving {name}: {e}"))
                else:
                    raise

        if fmt in ("json", "yaml"):
            dumper = _get_dumper(fmt)
            if dumper:
                print(dumper(serialize_path_results(results)))
            return

        if fmt == "rich":
            for _name, resolved_path in results:
                print(resolved_path)
            return

        print(toon_path(results))

    except Exception as e:
        handle_error(e)


def _get_resource_display_name(
    item: Union[OrganizationNode, Folder, Project],
) -> str:
    if isinstance(item, OrganizationNode):
        return item.organization.display_name
    return item.display_name


def _get_resource_path(item: Union[OrganizationNode, Folder, Project]) -> str:
    if isinstance(item, OrganizationNode):
        return f"//{path_escape(item.organization.display_name)}"
    return item.path


def _search_hierarchy(
    hierarchy: Hierarchy,
    pattern: str,
    type_filter: Optional[str],
) -> List[tuple[str, Union[OrganizationNode, Folder, Project]]]:
    lower_pattern = pattern.lower()

    candidates: List[Union[OrganizationNode, Folder, Project]] = []
    if not type_filter or type_filter == "organization":
        candidates.extend(hierarchy.organizations)
    if not type_filter or type_filter == "folder":
        candidates.extend(hierarchy.folders)
    if not type_filter or type_filter == "project":
        candidates.extend(hierarchy.projects)

    return [
        (_get_resource_path(item), item)
        for item in candidates
        if fnmatch.fnmatch(_get_resource_display_name(item).lower(), lower_pattern)
    ]


@app.command()
def find(
    ctx: typer.Context,
    pattern: Annotated[
        str, typer.Argument(help="Name pattern to search (glob syntax: *, ?)")
    ],
    resource: Annotated[
        Optional[str],
        typer.Argument(help="Resource to scope search within (e.g. folders/123)"),
    ] = None,
    resource_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter by resource type: folder, project, organization",
    ),
    force_refresh: bool = typer.Option(
        False, "--force-refresh", "-F", help=_REFRESH_HELP
    ),
    label_filters: Optional[List[str]] = typer.Option(
        None, "--label", help="Filter by label (key=value). Repeatable, ANDed together"
    ),
    tag_filters: Optional[List[str]] = typer.Option(
        None, "--tag", help="Filter by tag (key=value). Repeatable, ANDed together"
    ),
    fields: Optional[str] = typer.Option(
        None, "--fields", help=f"Comma-separated fields to show: {', '.join(_ALL_LS_FIELDS)}"
    ),
    full: bool = typer.Option(
        False, "--full", help="Show all labels/tags without truncation"
    ),
) -> None:
    """Search for resources by display name pattern (glob syntax)."""
    try:
        _validate_type_filter(resource_type)

        parsed_fields = _parse_fields(fields)
        needs_labels = parsed_fields is not None and "labels" in parsed_fields
        needs_tags = parsed_fields is not None and "tags" in parsed_fields
        include_labels = bool(label_filters) or needs_labels
        include_tags = bool(tag_filters) or needs_tags

        ep = ctx.obj.get("entrypoint")
        scope = _resolve_scope(resource, ep)

        hierarchy = _load_hierarchy(
            ctx,
            scope_resource=scope.target_resource_name,
            recursive=True,
            force_refresh=force_refresh,
            filter_orgs=scope.filter_orgs,
            include_labels=include_labels,
            include_tags=include_tags,
        )

        all_matches = sort_resources(_search_hierarchy(hierarchy, pattern, resource_type))
        total_searched = len(all_matches)

        items = all_matches
        if label_filters:
            items = [
                (p, obj)
                for p, obj in items
                if _matches_metadata(obj, label_filters, "labels")
            ]
        if tag_filters:
            items = [
                (p, obj)
                for p, obj in items
                if _matches_metadata(obj, tag_filters, "tags")
            ]

        fmt = ctx.obj.get("output_format", "toon")

        if fmt in ("json", "yaml"):
            dumper = _get_dumper(fmt)
            if dumper:
                print(dumper(serialize_ls(items)))
            return

        if fmt == "rich":
            if not items:
                rprint(f"[yellow]No resources matching '{pattern}' found.[/yellow]")
                return
            _display_ls_rich(items, show_labels=False, show_tags=False)
            return

        help_lines = (
            ["Run `gcpath ls <path>` for details on a resource"]
            if items
            else None
        )
        print(toon_find(items, pattern, total_searched=total_searched, fields=parsed_fields, full=full, help_lines=help_lines))

    except Exception as e:
        handle_error(e)


def _run_metadata_aggregation(
    ctx: typer.Context,
    *,
    resource: Optional[str],
    attr: str,
    key_filter: Optional[str],
    top: Optional[int],
    force_refresh: bool,
) -> None:
    """Shared implementation for `gcpath labels` and `gcpath tags`."""
    ep = ctx.obj.get("entrypoint")
    scope = _resolve_scope(resource, ep)
    include_labels = attr == "labels"
    include_tags = attr == "tags"

    hierarchy = _load_hierarchy(
        ctx,
        scope_resource=scope.target_resource_name,
        recursive=True,
        force_refresh=force_refresh,
        filter_orgs=scope.filter_orgs,
        include_labels=include_labels,
        include_tags=include_tags,
    )

    items: List[Union[Folder, Project]] = list(hierarchy.folders) + list(
        hierarchy.projects
    )
    rows, total = aggregate_metadata(items, attr, key_filter=key_filter)

    if top is not None and top > 0:
        rows = rows[:top]

    fmt = ctx.obj.get("output_format", "toon")
    if fmt in ("json", "yaml"):
        dumper = _get_dumper(fmt)
        if dumper:
            print(dumper({"count": len(rows), "scanned": total, attr: rows}))
        return

    if fmt == "rich":
        from rich.table import Table
        from rich.console import Console

        console = Console()
        if not rows:
            rprint(f"[yellow]No {attr} found in scope.[/yellow]")
            return
        table = Table(
            show_header=True, header_style=_RICH_HEADER_STYLE, box=None, padding=(0, 1)
        )
        table.add_column("Key")
        table.add_column("Value")
        table.add_column("Count", justify="right")
        table.add_column("Examples", overflow="fold")
        for row in rows:
            table.add_row(
                row["key"], row["value"], str(row["count"]), row["examples"]
            )
        console.print(table)
        return

    help_lines = [
        f"Run `gcpath ls --{attr[:-1]} <key>=<value>` to filter resources",
        f"Run `gcpath {attr} --top 10` to limit results",
    ]
    if attr == "labels":
        print(toon_labels(rows, total_resources=total, help_lines=help_lines))
    else:
        print(toon_tags(rows, total_resources=total, help_lines=help_lines))


@app.command(name="labels")
def labels_command(
    ctx: typer.Context,
    resource: Annotated[
        Optional[str],
        typer.Argument(help="Resource to scope aggregation within (e.g. folders/123)"),
    ] = None,
    key: Optional[str] = typer.Option(
        None, "--key", help="Show only entries with this label key"
    ),
    top: Optional[int] = typer.Option(
        None, "--top", help="Limit to the top N most frequent entries"
    ),
    force_refresh: bool = typer.Option(
        False, "--force-refresh", "-F", help=_REFRESH_HELP
    ),
) -> None:
    """Aggregate GCP labels across folders and projects with counts."""
    try:
        _run_metadata_aggregation(
            ctx,
            resource=resource,
            attr="labels",
            key_filter=key,
            top=top,
            force_refresh=force_refresh,
        )
    except Exception as e:
        handle_error(e)


@app.command(name="tags")
def tags_command(
    ctx: typer.Context,
    resource: Annotated[
        Optional[str],
        typer.Argument(help="Resource to scope aggregation within (e.g. folders/123)"),
    ] = None,
    key: Optional[str] = typer.Option(
        None, "--key", help="Show only entries with this tag key"
    ),
    top: Optional[int] = typer.Option(
        None, "--top", help="Limit to the top N most frequent entries"
    ),
    force_refresh: bool = typer.Option(
        False, "--force-refresh", "-F", help=_REFRESH_HELP
    ),
) -> None:
    """Aggregate GCP resource tags across folders and projects with counts."""
    try:
        _run_metadata_aggregation(
            ctx,
            resource=resource,
            attr="tags",
            key_filter=key,
            top=top,
            force_refresh=force_refresh,
        )
    except Exception as e:
        handle_error(e)


@app.command()
def ancestors(
    ctx: typer.Context,
    resource_name: Annotated[
        str, typer.Argument(help="Resource name (e.g., folders/123, projects/my-proj)")
    ],
) -> None:
    """Show the full ancestry chain from a resource up to the org root."""
    try:
        if not any(resource_name.startswith(p) for p in _RESOURCE_PREFIXES):
            print(toon_error(
                f"Invalid resource format '{resource_name}'. Expected 'organizations/...', 'folders/...', or 'projects/...'."
            ))
            raise typer.Exit(code=1)

        chain = Hierarchy.resolve_ancestry_chain(resource_name)

        fmt = ctx.obj.get("output_format", "toon")

        if fmt in ("json", "yaml"):
            dumper = _get_dumper(fmt)
            if dumper:
                print(dumper(serialize_ancestors(chain)))
            return

        if fmt == "rich":
            from rich.table import Table
            from rich.console import Console
            console = Console()
            table = Table(
                show_header=True, header_style=_RICH_HEADER_STYLE, box=None, padding=(0, 1)
            )
            table.add_column("Resource Name", overflow="fold")
            table.add_column("Display Name", overflow="fold")
            table.add_column("Type", overflow="fold")
            for name, display_name, rtype in chain:
                table.add_row(name, display_name, rtype)
            console.print(table)
            return

        print(toon_ancestors(
            chain,
            help_lines=["Run `gcpath ls <resource>` to list children"],
        ))

    except Exception as e:
        handle_error(e)


_VALID_MCP_TRANSPORTS = ("stdio", "sse")


@app.command(name="mcp")
def mcp_command(
    ctx: typer.Context,
    transport: str = typer.Option(
        "stdio",
        "--transport",
        help=f"MCP transport: {', '.join(_VALID_MCP_TRANSPORTS)}",
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="Host for SSE transport"),
    port: int = typer.Option(8765, "--port", help="Port for SSE transport"),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        help="Optional resource scope to load on first call (e.g. folders/123)",
    ),
) -> None:
    """Run gcpath as an MCP server so AI agents can query the hierarchy.

    Install the optional dependency first: pip install gcpath\\[mcp].
    Default transport is stdio (used by Claude Desktop/Code).
    """
    try:
        if transport not in _VALID_MCP_TRANSPORTS:
            print(toon_error(
                f"Invalid transport '{transport}'. Use one of: "
                + ", ".join(_VALID_MCP_TRANSPORTS)
            ))
            raise typer.Exit(code=1)

        # `mcp_server` is import-safe; it only imports the optional `mcp`
        # package inside `build_server`. A missing extra surfaces from
        # `run_server` as `GCPathError` and is rendered by `handle_error`.
        from gcpath.mcp_server import run_server

        use_asset_api = ctx.obj.get("use_asset_api", True)
        effective_scope = scope or ctx.obj.get("entrypoint")

        run_server(
            transport=transport,
            host=host,
            port=port,
            use_asset_api=use_asset_api,
            scope=effective_scope,
        )

    except typer.Exit:
        raise
    except Exception as e:
        handle_error(e)


@hook_app.command("install")
def hook_install(ctx: typer.Context) -> None:
    """Self-install session hooks for Claude Code and Codex (idempotent)."""
    fmt = ctx.obj.get("output_format", "toon")
    results = install_hooks()

    if fmt == "rich":
        for target, changed in results.items():
            if changed:
                rprint(f"[green]Installed hook for {target}[/green]")
            else:
                rprint(f"[dim]Hook already installed for {target}[/dim]")
        return

    print(toon_confirmed(
        "Hooks installed: "
        + ", ".join(f"{t}={'updated' if c else 'already installed'}" for t, c in results.items())
    ))


@hook_app.command("uninstall")
def hook_uninstall(ctx: typer.Context) -> None:
    """Remove session hooks from Claude Code and Codex."""
    fmt = ctx.obj.get("output_format", "toon")
    results = uninstall_hooks()

    if fmt == "rich":
        for target, changed in results.items():
            if changed:
                rprint(f"[green]Removed hook from {target}[/green]")
            else:
                rprint(f"[dim]No hook found for {target}[/dim]")
        return

    print(toon_confirmed(
        "Hooks uninstalled: "
        + ", ".join(f"{t}={'removed' if c else 'not found'}" for t, c in results.items())
    ))


@hook_app.command("run")
def hook_run() -> None:
    """Output session-start dashboard (called by hooks)."""
    print(run_session_start())


@hook_app.command("status")
def hook_status(ctx: typer.Context) -> None:
    """Show hook installation status."""
    fmt = ctx.obj.get("output_format", "toon")
    status = get_hook_status()

    if fmt == "rich":
        for target, info in status.items():
            installed = info["installed"]
            path_ok = info["path_ok"]
            loc = info["location"]
            if installed and path_ok:
                rprint(f"[green]{target}[/green]: installed ({loc})")
            elif installed and not path_ok:
                rprint(f"[yellow]{target}[/yellow]: installed (path needs repair) ({loc})")
            else:
                rprint(f"[dim]{target}[/dim]: not installed ({loc})")
        return

    print(toon_encode(status))


def run() -> None:
    app()


if __name__ == "__main__":
    app()
