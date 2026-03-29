import fnmatch
import typer
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Union
from urllib.parse import unquote
from typing_extensions import Annotated
from rich.console import Console
from rich import print as rprint
from rich.markup import escape
from google.api_core import exceptions as gcp_exceptions


from gcpath.core import (
    Hierarchy,
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
)
from gcpath.serializers import (
    resource_type as get_resource_type,
    serialize_ls,
    serialize_tree,
    serialize_name_results,
    serialize_path_results,
    serialize_ancestors,
    dump_json,
    dump_yaml,
)
from typing import Any, Callable
from gcpath.cache import (
    read_cache,
    write_cache,
    clear_cache,
    get_cache_info,
    CACHE_FILE,
)
from gcpath.config import (
    get_entrypoint,
    set_entrypoint,
    clear_entrypoint,
    read_config,
    CONFIG_FILE,
)
from rich.table import Table

# Resource name prefixes
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

logger = logging.getLogger(__name__)


def _validate_type_filter(resource_type: Optional[str]) -> None:
    """Validate --type filter value."""
    if resource_type is not None and resource_type not in _VALID_TYPE_FILTERS:
        error_console.print(
            f"[red]Error:[/red] Invalid type '{resource_type}'. "
            f"Must be one of: {', '.join(_VALID_TYPE_FILTERS)}"
        )
        raise typer.Exit(code=1)


def _matches_type(
    obj: Union[OrganizationNode, Folder, Project], type_filter: str
) -> bool:
    """Check if a resource matches the given type filter."""
    return get_resource_type(obj) == type_filter


def _parse_label_filter(label_str: str) -> tuple:
    """Parse a label filter string 'key=value' into (key, value) tuple."""
    if "=" not in label_str:
        return (label_str, None)
    key, _, value = label_str.partition("=")
    return (key, value)


def _matches_metadata(
    obj: Union[OrganizationNode, Folder, Project],
    filters: List[str],
    attr: str,
) -> bool:
    """Check if a resource matches ALL filters (ANDed) for a given metadata attribute."""
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


def _format_metadata(obj: Union[OrganizationNode, Folder, Project], attr: str) -> str:
    """Format a metadata dict attribute as comma-separated key=value string."""
    metadata = getattr(obj, attr, {})
    if not metadata:
        return ""
    return ", ".join(f"{k}={v}" for k, v in sorted(metadata.items()))


@dataclass
class _ScopeResult:
    """Result of resolving a resource scope argument."""

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

    # Skip org filtering when using entrypoint without explicit resource
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
)
cache_app = typer.Typer(help="Manage the local resource cache.")
app.add_typer(cache_app, name="cache")
config_app = typer.Typer(help="Manage gcpath configuration.")
app.add_typer(config_app, name="config")
console = Console()
error_console = Console(stderr=True)


def _get_dumper(output_format: str) -> Optional[Callable[[Any], str]]:
    """Return the appropriate dumper for the given output format, or None for text."""
    if output_format == "json":
        return dump_json
    if output_format == "yaml":
        return dump_yaml
    return None


def handle_error(e: Exception) -> None:
    """Central error handler for CLI."""
    if isinstance(e, GCPathError):
        error_console.print(f"[red]Error:[/red] {e}")
    elif isinstance(e, gcp_exceptions.PermissionDenied):
        error_console.print(
            "[red]Permission Denied:[/red] Ensure you have the required permissions and are authenticated."
        )
        error_console.print(
            "[dim]Hint: Run 'gcloud auth application-default login'[/dim]"
        )
    elif isinstance(e, gcp_exceptions.ServiceUnavailable):
        error_console.print(
            "[red]Service Unavailable:[/red] The GCP API is currently unreachable."
        )
    elif isinstance(e, Exception):
        error_console.print(f"[red]Unexpected Error:[/red] {e}")
        logging.exception("Unexpected error occurred")
    raise typer.Exit(code=1)


def _format_age(seconds: float) -> str:
    """Format age in seconds to a human-readable string."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


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
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output in JSON format",
    ),
    yaml_output: bool = typer.Option(
        False,
        "--yaml",
        help="Output in YAML format",
    ),
) -> None:
    """
    gcpath - Google Cloud Platform resource hierarchy utility
    """
    if json_output and yaml_output:
        error_console.print(
            "[red]Error:[/red] --json and --yaml are mutually exclusive."
        )
        raise typer.Exit(code=1)

    ctx.ensure_object(dict)
    ctx.obj["use_asset_api"] = use_asset_api
    ctx.obj["entrypoint"] = entrypoint or get_entrypoint()

    if json_output:
        ctx.obj["output_format"] = "json"
    elif yaml_output:
        ctx.obj["output_format"] = "yaml"
    else:
        ctx.obj["output_format"] = "text"

    if debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.ERROR)

    # Always suppress urllib3 debug logs
    logging.getLogger("urllib3").setLevel(logging.WARNING)


@cache_app.command("clear")
def cache_clear() -> None:
    """Clear the local resource cache."""
    if clear_cache():
        rprint(f"[green]Cache cleared successfully at {CACHE_FILE}[/green]")
    else:
        rprint(f"[yellow]No cache file to clear at {CACHE_FILE}[/yellow]")


@cache_app.command("status")
def cache_status() -> None:
    """Show cache status information."""
    info = get_cache_info()

    if not info.exists:
        rprint(f"[yellow]No cache file found at {CACHE_FILE}[/yellow]")
        return

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Key", style="bold")
    table.add_column("Value")

    if info.fresh:
        table.add_row("Status", "[green]Fresh[/green]")
    else:
        table.add_row("Status", "[yellow]Stale[/yellow]")

    if info.age_seconds is not None:
        table.add_row("Age", _format_age(info.age_seconds))

    if info.size_bytes is not None:
        size_kb = info.size_bytes / 1024
        if size_kb >= 1024:
            table.add_row("Size", f"{size_kb / 1024:.1f} MB")
        else:
            table.add_row("Size", f"{size_kb:.1f} KB")

    if info.version is not None:
        table.add_row("Version", str(info.version))

    if info.scope is not None:
        table.add_row("Scope", info.scope)

    table.add_row("Organizations", str(info.org_count))
    table.add_row("Folders", str(info.folder_count))
    table.add_row("Projects", str(info.project_count))
    table.add_row("Location", str(CACHE_FILE))

    console.print(table)


@config_app.command("set-entrypoint")
def config_set_entrypoint(
    resource: Annotated[
        str,
        typer.Argument(
            help="Resource name to use as default entrypoint (e.g., folders/123)."
        ),
    ],
) -> None:
    """Set the default entrypoint resource."""
    try:
        set_entrypoint(resource)
        rprint(f"[green]Entrypoint set to {resource}[/green]")
    except ValueError as e:
        rprint(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)


@config_app.command("show")
def config_show() -> None:
    """Show current configuration."""
    config = read_config()
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


@config_app.command("clear-entrypoint")
def config_clear_entrypoint() -> None:
    """Remove the default entrypoint."""
    clear_entrypoint()
    rprint("[green]Entrypoint cleared.[/green]")


def _clean_resolve_path(path: str) -> str:
    """Clean up a resolved path that may contain _unknown_org_ segments."""
    if "_unknown_org_" in path:
        # Strip //_unknown_org_(organizations/ID) prefix, keep rest
        # e.g., "//_unknown_org_(organizations/123)/Folder/Sub" -> "//Folder/Sub"
        parts = path.split("/")
        # Find the _unknown_org_ segment and skip it
        cleaned = []
        for part in parts:
            if "_unknown_org_" in part:
                continue
            cleaned.append(part)
        # Rebuild: starts with // so cleaned[0] and [1] are empty strings
        result = "/".join(cleaned)
        if not result.startswith("//"):
            result = "//" + result.lstrip("/")
        return result
    return path


def _try_read_cache(
    cache_scope: Optional[str],
    filter_orgs: Optional[List[str]],
) -> Optional[Hierarchy]:
    """Try to read hierarchy from cache, applying org filter if needed.

    Returns None if cache is not available.
    """
    cached_hierarchy = read_cache(scope=cache_scope)
    if cached_hierarchy is None:
        return None

    info = get_cache_info()
    age_str = _format_age(info.age_seconds) if info.age_seconds else "unknown"
    error_console.print(
        f"[dim]Using cached data ({age_str} ago). Use -F to refresh.[/dim]"
    )

    # Apply org filter to cached data
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
    """Helper to load hierarchy with cache orchestration.

    Cache is used for unscoped loads and entrypoint-scoped loads.
    One-off queries (scope_resource set but != entrypoint) are not cached.
    Cacheable loads always use recursive=True so the cache contains complete data.
    """
    entrypoint = ctx.obj.get("entrypoint")

    # Cacheable: unscoped OR scope matches entrypoint
    is_cacheable = (scope_resource is None) or (
        entrypoint is not None and scope_resource == entrypoint
    )
    cache_scope = scope_resource if is_cacheable and scope_resource else None

    if is_cacheable and not force_refresh:
        cached = _try_read_cache(cache_scope, filter_orgs)
        if cached is not None:
            return cached

    # Always recursive for cacheable loads (complete data for all commands)
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
    """Shared context produced by _prepare_hierarchy_command."""

    hierarchy: Hierarchy
    nodes_to_process: List[Union[OrganizationNode, Folder]]
    projects_by_parent: Dict[str, List[Project]]
    target_resource_name: Optional[str]
    target_path: Optional[str]


@dataclass
class _ParsedResource:
    """Result of parsing a resource argument for tree-like commands."""

    target_resource_name: Optional[str]
    target_org_name: Optional[str]
    target_path: Optional[str]


def _parse_resource_arg(effective_resource: str, command_name: str) -> _ParsedResource:
    """Parse a resource argument, resolving its path and org name.

    Raises typer.Exit(code=1) if the resource is a project.
    """
    if effective_resource.startswith(_RESOURCE_PREFIX_PROJECTS):
        rprint(
            f"[red]Error:[/red] '{command_name}' command does not support starting "
            "from a project (projects are leaf nodes)."
        )
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
    except Exception:
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
    """Find nodes matching target_resource_name in the hierarchy.

    Creates a synthetic folder if the target folder is not found but the
    hierarchy has organizations.
    """
    if target_resource_name.startswith(_RESOURCE_PREFIX_ORGS):
        for o in hierarchy.organizations:
            if o.organization.name == target_resource_name:
                return [o]
        return []

    # Folder lookup
    for o in hierarchy.organizations:
        if target_resource_name in o.folders:
            return [o.folders[target_resource_name]]

    # Create synthetic folder from resolved path
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
    level: Optional[int],
    yes: bool,
    force_refresh: bool,
    include_labels: bool = False,
    include_tags: bool = False,
) -> Optional[_HierarchyCommandContext]:
    """Shared setup for tree-like commands (tree, diagram).

    Returns None if the user declines the confirmation prompt.
    Raises typer.Exit(code=1) for invalid or not-found resources.
    """
    ep = ctx.obj.get("entrypoint")
    effective_resource = resource or ep

    # Prompt user for potentially long loads (only when truly unscoped)
    if not yes and effective_resource is None:
        cache_info = get_cache_info()
        if not cache_info.fresh and (level is None or level >= 4):
            if not typer.confirm(
                "This will load all folders and projects in the hierarchy, "
                "which may take a long time. Continue?"
            ):
                return None

    # Parse resource argument
    parsed = _ParsedResource(None, None, None)
    if effective_resource:
        parsed = _parse_resource_arg(effective_resource, command_name)

    # Skip org filtering when using entrypoint without explicit resource
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

    # Build nodes_to_process
    if parsed.target_resource_name:
        nodes_to_process = _find_target_nodes(
            hierarchy,
            parsed.target_resource_name,
            parsed.target_path,
        )
        if not nodes_to_process:
            rprint(
                f"[red]Error:[/red] Target resource '{parsed.target_resource_name}' not found."
            )
            raise typer.Exit(code=1)
    else:
        nodes_to_process = list(hierarchy.organizations)

    # Build projects_by_parent mapping
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


def _handle_empty_hierarchy(dumper) -> None:
    """Display message when no organizations or projects are found."""
    if dumper:
        print(dumper([]))
        return

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


def _resolve_target_path_prefix(target_resource_name: Optional[str]) -> str:
    """Resolve the display path prefix for a target resource."""
    if not target_resource_name:
        return ""
    try:
        return _clean_resolve_path(Hierarchy.resolve_ancestry(target_resource_name))
    except Exception as e:
        logger.warning(f"Could not resolve target path: {e}")
        return ""


def _get_resource_name(obj: Union[OrganizationNode, Folder, Project]) -> str:
    """Get the resource name string for any resource type."""
    if isinstance(obj, OrganizationNode):
        return obj.organization.name
    return obj.name


def _apply_ls_filters(
    items: list,
    resource_type: Optional[str],
    label_filters: Optional[List[str]],
    tag_filters: Optional[List[str]],
) -> list:
    """Apply type, label, and tag filters to items list."""
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
    """Apply depth limit for recursive listing."""
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
) -> list:
    """Build, filter, and sort the items list for ls output."""
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
    items = _apply_ls_filters(items, resource_type, label_filters, tag_filters)
    items = _apply_depth_limit(items, level, recursive, target_path_prefix)
    return items


def _display_ls_items(
    items: list,
    long: bool,
    show_labels: bool,
    show_tags: bool,
) -> None:
    """Display ls items in either long or short format."""
    if not long:
        for path, _ in items:
            print(path)
        return

    table = Table(
        show_header=True, header_style="bold magenta", box=None, padding=(0, 1)
    )
    table.add_column("Path", overflow="fold")
    table.add_column("Resource Name", overflow="fold")
    if show_labels:
        table.add_column("Labels", overflow="fold")
    if show_tags:
        table.add_column("Tags", overflow="fold")

    for path, obj in items:
        row = [path, _get_resource_name(obj)]
        if show_labels:
            row.append(_format_metadata(obj, "labels"))
        if show_tags:
            row.append(_format_metadata(obj, "tags"))
        table.add_row(*row)

    console.print(table)


@app.command()
def ls(
    ctx: typer.Context,
    resource: Annotated[
        Optional[str],
        typer.Argument(
            help="Resource name (e.g. folders/123) or path to list children from."
        ),
    ] = None,
    long: bool = typer.Option(
        False, "--long", "-l", help="Show resource IDs and numbers (for projects)"
    ),
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
) -> None:
    """
    List folders and projects. Defaults to the root organization.
    """
    try:
        _validate_type_filter(resource_type)

        # Implicitly enable label/tag fetching when filters are specified
        include_labels = show_labels or bool(label_filters)
        include_tags = show_tags or bool(tag_filters)

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

        dumper = _get_dumper(ctx.obj.get("output_format", "text"))

        if not hierarchy.organizations and not hierarchy.projects:
            _handle_empty_hierarchy(dumper)
            return

        if target_resource_name and target_resource_name.startswith(
            _RESOURCE_PREFIX_PROJECTS
        ):
            return

        target_path_prefix = _resolve_target_path_prefix(target_resource_name)

        items = _build_ls_items(
            hierarchy,
            target_resource_name,
            target_path_prefix,
            recursive,
            resource_type,
            label_filters,
            tag_filters,
            level,
        )

        if dumper:
            print(dumper(serialize_ls(items)))
            return

        _display_ls_items(items, long, show_labels, show_tags)

    except Exception as e:
        handle_error(e)


def _get_orgless_projects(hctx: _HierarchyCommandContext) -> Optional[List[Project]]:
    """Get organizationless projects if not targeting a specific resource."""
    if hctx.target_resource_name:
        return None
    orgless = [p for p in hctx.hierarchy.projects if not p.organization]
    return orgless or None


def _tree_root_label(
    node: Union[OrganizationNode, Folder],
    is_targeted: Optional[str],
) -> tuple[str, str]:
    """Build root tree label and node_id for a tree node."""
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
    """Add organizationless projects section to tree."""
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
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts"),
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
    """
    Display the resource hierarchy in a tree format.
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
            level,
            yes,
            force_refresh,
            include_labels=include_labels,
            include_tags=include_tags,
        )
        if hctx is None:
            return

        orgless_projects = _get_orgless_projects(hctx)

        dumper = _get_dumper(ctx.obj.get("output_format", "text"))
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

        console.print(root_tree)

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
    fmt: str = typer.Option(
        "mermaid",
        "--format",
        "-f",
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
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts"),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        "-F",
        help=_REFRESH_HELP,
    ),
) -> None:
    """
    Generate a Mermaid or D2 diagram of the resource hierarchy.
    """
    try:
        if fmt not in ("mermaid", "d2"):
            rprint(
                f"[red]Error:[/red] Unsupported format '{fmt}'. Use 'mermaid' or 'd2'."
            )
            raise typer.Exit(code=1)

        hctx = _prepare_hierarchy_command(
            ctx, "diagram", resource, level, yes, force_refresh
        )
        if hctx is None:
            return

        # Collect organizationless projects
        orgless_projects = None
        if not hctx.target_resource_name:
            orgless = [p for p in hctx.hierarchy.projects if not p.organization]
            if orgless:
                orgless_projects = orgless

        diagram_output = build_diagram(
            hctx.nodes_to_process,
            hctx.hierarchy,
            hctx.projects_by_parent,
            fmt=fmt,
            level=level,
            show_ids=show_ids,
            orgless_projects=orgless_projects,
        )

        if output:
            with open(output, "w", encoding="utf-8") as f:
                f.write(diagram_output + "\n")
            rprint(f"[green]Diagram written to {output}[/green]")
        else:
            print(diagram_output)

    except Exception as e:
        handle_error(e)


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
        help="Force a refresh of the cache from the GCP API",
    ),
) -> None:
    """
    Show statistics about folders and projects in a scope.
    """
    try:
        ep = ctx.obj.get("entrypoint")
        effective_resource = resource or ep

        target_resource_name = None
        if effective_resource:
            if effective_resource.startswith("projects/"):
                rprint(
                    "[red]Error:[/red] 'stats' command does not support starting from a project."
                )
                raise typer.Exit(code=1)
            elif any(
                effective_resource.startswith(p)
                for p in [_RESOURCE_PREFIX_ORGS, _RESOURCE_PREFIX_FOLDERS]
            ):
                target_resource_name = effective_resource
            else:
                rprint(
                    f"[red]Error:[/red] Invalid resource format '{escape(effective_resource)}'. "
                    f"Expected 'organizations/...' or 'folders/...'."
                )
                raise typer.Exit(code=1)

        hierarchy = _load_hierarchy(
            ctx,
            scope_resource=target_resource_name,
            recursive=True,
            force_refresh=force_refresh,
        )

        folder_count = len(hierarchy.folders)
        project_count = len(hierarchy.projects)

        scope_label = target_resource_name or "all organizations"
        rprint(f"[bold]Scope:[/bold] {escape(scope_label)}")

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Resource", style="bold")
        table.add_column("Count", justify="right")

        if not target_resource_name or target_resource_name.startswith(
            _RESOURCE_PREFIX_ORGS
        ):
            table.add_row("Organizations", str(len(hierarchy.organizations)))
        table.add_row("Folders", str(folder_count))
        table.add_row("Projects", str(project_count))

        console.print(table)

    except Exception as e:
        handle_error(e)


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
    """
    Get Google Cloud Platform resource name by path.
    """
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

        dumper = _get_dumper(ctx.obj.get("output_format", "text"))
        results: List[tuple[str, str]] = []
        for path in paths:
            logger.debug(f"name command: resolving path {path}")
            res_name = hierarchy.get_resource_name(path)
            logger.debug(f"name command: resolved {path} to {res_name}")
            results.append((path, res_name))

        if dumper:
            print(dumper(serialize_name_results(results, id_only)))
        else:
            for _path, res_name in results:
                if id_only:
                    res_name = res_name.split("/")[-1]
                print(res_name)

    except Exception as e:
        handle_error(e)


@app.command(name="path")
def get_path_command(
    ctx: typer.Context,
    resource_names: Annotated[
        List[str], typer.Argument(help="Resource names to resolve, e.g. folders/123")
    ],
) -> None:
    """
    Get path of a resource name.
    """
    try:
        logger.debug(f"path: resolving resource_names={resource_names}")
        dumper = _get_dumper(ctx.obj.get("output_format", "text"))
        results: List[tuple[str, str]] = []

        for name in resource_names:
            try:
                # Use optimized recursive lookup instead of full hierarchy load
                p = Hierarchy.resolve_ancestry(name)
                logger.debug(f"path: resolved {name} to {p}")
                results.append((name, p))
            except Exception as e:
                if len(resource_names) > 1:
                    error_console.print(f"[red]Error resolving {name}: {e}[/red]")
                else:
                    raise e

        if dumper:
            print(dumper(serialize_path_results(results)))
        else:
            for _name, resolved_path in results:
                print(resolved_path)

    except Exception as e:
        handle_error(e)


def _get_resource_display_name(
    item: Union[OrganizationNode, Folder, Project],
) -> str:
    """Get display name for any resource type."""
    if isinstance(item, OrganizationNode):
        return item.organization.display_name
    return item.display_name


def _get_resource_path(item: Union[OrganizationNode, Folder, Project]) -> str:
    """Get display path for any resource type."""
    if isinstance(item, OrganizationNode):
        return f"//{path_escape(item.organization.display_name)}"
    return item.path


def _search_hierarchy(
    hierarchy: Hierarchy,
    pattern: str,
    type_filter: Optional[str],
) -> List[tuple[str, Union[OrganizationNode, Folder, Project]]]:
    """Search hierarchy resources by display name pattern and optional type filter."""
    lower_pattern = pattern.lower()

    # Build flat list of (resource, type_name) to search
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
) -> None:
    """
    Search for resources by display name pattern (glob syntax).
    """
    try:
        _validate_type_filter(resource_type)

        include_labels = bool(label_filters)
        include_tags = bool(tag_filters)

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

        items = sort_resources(_search_hierarchy(hierarchy, pattern, resource_type))

        # Apply label/tag filters
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

        dumper = _get_dumper(ctx.obj.get("output_format", "text"))
        if dumper:
            print(dumper(serialize_ls(items)))
            return

        if not items:
            rprint(f"[yellow]No resources matching '{pattern}' found.[/yellow]")
            return

        for path, _ in items:
            print(path)

    except Exception as e:
        handle_error(e)


@app.command()
def ancestors(
    ctx: typer.Context,
    resource_name: Annotated[
        str, typer.Argument(help="Resource name (e.g., folders/123, projects/my-proj)")
    ],
) -> None:
    """
    Show the full ancestry chain from a resource up to the org root.
    """
    try:
        if not any(resource_name.startswith(p) for p in _RESOURCE_PREFIXES):
            error_console.print(
                f"[red]Error:[/red] Invalid resource format '{resource_name}'. "
                f"Expected 'organizations/...', 'folders/...', or 'projects/...'."
            )
            raise typer.Exit(code=1)

        chain = Hierarchy.resolve_ancestry_chain(resource_name)

        dumper = _get_dumper(ctx.obj.get("output_format", "text"))
        if dumper:
            print(dumper(serialize_ancestors(chain)))
            return

        table = Table(
            show_header=True, header_style="bold magenta", box=None, padding=(0, 1)
        )
        table.add_column("Resource Name", overflow="fold")
        table.add_column("Display Name", overflow="fold")
        table.add_column("Type", overflow="fold")

        for name, display_name, rtype in chain:
            table.add_row(name, display_name, rtype)

        console.print(table)

    except Exception as e:
        handle_error(e)


def run() -> None:
    app()


if __name__ == "__main__":
    app()
