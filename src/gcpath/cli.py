import typer
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Union
from urllib.parse import unquote
from typing_extensions import Annotated
from rich.console import Console
from rich import print as rprint
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

logger = logging.getLogger(__name__)

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
) -> None:
    """
    gcpath - Google Cloud Platform resource hierarchy utility
    """
    ctx.ensure_object(dict)
    ctx.obj["use_asset_api"] = use_asset_api
    ctx.obj["entrypoint"] = entrypoint or get_entrypoint()

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


def _load_hierarchy(
    ctx: typer.Context,
    scope_resource: Optional[str],
    recursive: bool,
    force_refresh: bool,
    filter_orgs: Optional[List[str]] = None,
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
        cached_hierarchy = read_cache(scope=cache_scope)
        if cached_hierarchy is not None:
            info = get_cache_info()
            age_str = _format_age(info.age_seconds) if info.age_seconds else "unknown"
            rprint(f"[dim]Using cached data ({age_str} ago). Use -F to refresh.[/dim]")

            # Apply org filter to cached data
            if filter_orgs:
                cached_hierarchy.organizations = [
                    o
                    for o in cached_hierarchy.organizations
                    if o.organization.display_name in filter_orgs
                ]
            return cached_hierarchy

    # Always recursive for cacheable loads (complete data for all commands)
    effective_recursive = True if is_cacheable else recursive

    hierarchy = Hierarchy.load(
        display_names=filter_orgs,
        via_resource_manager=not ctx.obj["use_asset_api"],
        scope_resource=scope_resource,
        recursive=effective_recursive,
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


def _prepare_hierarchy_command(
    ctx: typer.Context,
    command_name: str,
    resource: Optional[str],
    level: Optional[int],
    yes: bool,
    force_refresh: bool,
) -> Optional[_HierarchyCommandContext]:
    """Shared setup for tree-like commands (tree, diagram).

    Handles confirmation prompting, resource argument parsing, hierarchy loading,
    nodes_to_process construction (including synthetic folders), and
    projects_by_parent building.

    Returns None if the user declines the confirmation prompt.
    Raises typer.Exit(code=1) for invalid or not-found resources.
    """
    # Inject entrypoint when no explicit resource is given
    ep = ctx.obj.get("entrypoint")
    effective_resource = resource or ep

    # Prompt user for potentially long loads (only when truly unscoped)
    if not yes and effective_resource is None:
        cache_info = get_cache_info()
        if not cache_info.fresh and (level is None or level >= 4):
            confirm = typer.confirm(
                "This will load all folders and projects in the hierarchy, "
                "which may take a long time. Continue?"
            )
            if not confirm:
                return None

    # Parse resource argument
    target_org_name = None
    target_resource_name = None
    target_path = None

    if effective_resource:
        logger.debug(f"{command_name} command: processing resource argument {effective_resource}")
        if effective_resource.startswith("projects/"):
            rprint(
                f"[red]Error:[/red] '{command_name}' command does not support starting "
                "from a project (projects are leaf nodes)."
            )
            raise typer.Exit(code=1)

        try:
            target_path = _clean_resolve_path(
                Hierarchy.resolve_ancestry(effective_resource)
            )
            if target_path.startswith("//"):
                path_parts = target_path[2:].split("/")
                if path_parts:
                    target_org_name = unquote(path_parts[0])

            if effective_resource.startswith("folders/") or effective_resource.startswith(
                "organizations/"
            ):
                target_resource_name = effective_resource
        except Exception:
            if effective_resource.startswith("//"):
                target_path = effective_resource
            else:
                raise

    # Skip org filtering when using entrypoint without explicit resource
    if not resource and ep and target_org_name:
        filter_orgs = None
    else:
        filter_orgs = [target_org_name] if target_org_name else None
    logger.debug(
        f"{command_name}: loading hierarchy for resource='{resource}', filter_orgs={filter_orgs}"
    )

    hierarchy = _load_hierarchy(
        ctx,
        scope_resource=target_resource_name,
        recursive=True,
        force_refresh=force_refresh,
        filter_orgs=filter_orgs,
    )

    logger.debug(
        f"{command_name}: hierarchy loaded with {len(hierarchy.organizations)} orgs, "
        f"{len(hierarchy.projects)} projects, {len(hierarchy.folders)} folders"
    )

    # Build nodes_to_process
    nodes_to_process: List[Union[OrganizationNode, Folder]] = []
    if target_resource_name:
        logger.debug(
            f"{command_name} command: looking for target resource {target_resource_name}"
        )
        if target_resource_name.startswith("organizations/"):
            for o in hierarchy.organizations:
                if o.organization.name == target_resource_name:
                    logger.debug(f"{command_name} command: found target organization")
                    nodes_to_process = [o]
                    break
        elif target_resource_name.startswith("folders/"):
            for o in hierarchy.organizations:
                if target_resource_name in o.folders:
                    logger.debug(
                        f"{command_name} command: found target folder in organization"
                    )
                    nodes_to_process = [o.folders[target_resource_name]]
                    break

            # If not found in loaded hierarchy, create a synthetic folder from resolved path
            if not nodes_to_process and target_path and hierarchy.organizations:
                logger.debug(
                    f"{command_name} command: creating synthetic folder node for scope"
                )
                path_parts = (
                    target_path[2:].split("/")
                    if target_path.startswith("//")
                    else []
                )
                display_name = (
                    path_parts[-1]
                    if path_parts
                    else target_resource_name.split("/")[-1]
                )

                org_node = hierarchy.organizations[0]
                synthetic_folder = Folder(
                    name=target_resource_name,
                    display_name=display_name,
                    ancestors=[target_resource_name, org_node.organization.name],
                    organization=org_node,
                    parent=org_node.organization.name,
                )
                org_node.folders[target_resource_name] = synthetic_folder
                nodes_to_process = [synthetic_folder]
                logger.debug(
                    f"{command_name} command: created synthetic folder {synthetic_folder.name}"
                )

        if not nodes_to_process:
            logger.warning(
                f"{command_name} command: target resource '{target_resource_name}' not found"
            )
            rprint(
                f"[red]Error:[/red] Target resource '{target_resource_name}' not found."
            )
            raise typer.Exit(code=1)
    else:
        logger.debug(
            f"{command_name} command: processing all {len(hierarchy.organizations)} organizations"
        )
        nodes_to_process = list(hierarchy.organizations)

    # Build projects_by_parent mapping
    projects_by_parent: Dict[str, List[Project]] = {}
    for proj in hierarchy.projects:
        projects_by_parent.setdefault(proj.parent, []).append(proj)

    return _HierarchyCommandContext(
        hierarchy=hierarchy,
        nodes_to_process=nodes_to_process,
        projects_by_parent=projects_by_parent,
        target_resource_name=target_resource_name,
        target_path=target_path,
    )


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
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        "-F",
        help="Force a refresh of the cache from the GCP API",
    ),
) -> None:
    """
    List folders and projects. Defaults to the root organization.
    """
    try:
        target_org_name = None
        target_resource_name = None

        # Inject entrypoint when no explicit resource is given
        ep = ctx.obj.get("entrypoint")
        effective_resource = resource or ep

        if effective_resource:
            # Check if it's already a GCP resource name
            if any(
                effective_resource.startswith(p)
                for p in ["organizations/", "folders/", "projects/"]
            ):
                target_resource_name = effective_resource
                try:
                    target_path = Hierarchy.resolve_ancestry(effective_resource)
                    if target_path.startswith("//"):
                        path_parts = target_path[2:].split("/")
                        if path_parts:
                            target_org_name = unquote(path_parts[0])
                except Exception:
                    pass
            # If it's a path, we'd need to resolve it back to resource name
            # For simplicity, we mostly support resource names or defaults to org load
            elif effective_resource.startswith("//"):
                # Handle path to name resolution if needed, but SPEC emphasizes resource name args
                pass

        # Skip org filtering when using entrypoint without explicit resource
        # (org may be inaccessible for folder admins)
        if not resource and ep and target_org_name:
            filter_orgs = None
        else:
            filter_orgs = [target_org_name] if target_org_name else None
        logger.debug(
            f"ls: loading hierarchy for resource='{resource}', filter_orgs={filter_orgs}, recursive={recursive}"
        )

        # Determine scope_resource for API-level filtering
        # If targeting a specific resource, pass it as scope_resource
        # so the API only returns direct children (or all descendants if recursive)
        scope_resource = target_resource_name if target_resource_name else None

        hierarchy = _load_hierarchy(
            ctx,
            scope_resource=scope_resource,
            recursive=recursive,
            force_refresh=force_refresh,
            filter_orgs=filter_orgs,
        )

        logger.debug(
            f"ls: hierarchy loaded with {len(hierarchy.organizations)} orgs, {len(hierarchy.projects)} projects, {len(hierarchy.folders)} folders"
        )

        if not hierarchy.organizations and not hierarchy.projects:
            # Check if it looks like a personal account
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
                    "[dim]Hint: You might not have access to any organizations. Projects without organizations are shown with //_ prefix.[/dim]"
                )
            return

        # If a specific resource was targeted, we list its children
        # Get the target path prefix for proper path display
        target_path_prefix = ""
        if target_resource_name:
            logger.debug(
                f"ls command: targeting specific resource {target_resource_name}"
            )
            if target_resource_name.startswith("projects/"):
                # projects don't have children in this context
                return

            # Get the full path for the target resource to use as prefix
            try:
                target_path_prefix = _clean_resolve_path(
                    Hierarchy.resolve_ancestry(target_resource_name)
                )
                logger.debug(f"ls: target path prefix: {target_path_prefix}")
            except Exception as e:
                logger.warning(f"Could not resolve target path: {e}")

        # Filter to get direct children
        current_folders, current_projects = filter_direct_children(
            hierarchy, target_resource_name
        )

        # Build items list for display
        items = build_items_list(
            hierarchy,
            current_folders,
            current_projects,
            target_path_prefix,
            target_resource_name,
            recursive,
        )

        # Sort items by path
        items = sort_resources(items)

        logger.debug(f"ls: found {len(items)} items to display")

        if long:
            table = Table(
                show_header=True, header_style="bold magenta", box=None, padding=(0, 1)
            )
            table.add_column("Path", overflow="fold")
            table.add_column("Resource Name", overflow="fold")

            for path, obj in items:
                resource_name = ""

                if isinstance(obj, OrganizationNode):
                    resource_name = obj.organization.name
                elif isinstance(obj, Folder):
                    resource_name = obj.name
                elif isinstance(obj, Project):
                    resource_name = obj.name

                table.add_row(path, resource_name)

            console.print(table)
        else:
            for path, _ in items:
                print(path)

    except Exception as e:
        handle_error(e)


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
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts"),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        "-F",
        help="Force a refresh of the cache from the GCP API",
    ),
) -> None:
    """
    Display the resource hierarchy in a tree format.
    """
    from rich.tree import Tree

    try:
        hctx = _prepare_hierarchy_command(
            ctx, "tree", resource, level, yes, force_refresh
        )
        if hctx is None:
            return

        root_tree = Tree(
            "[bold cyan]Query Result[/bold cyan]"
            if hctx.target_resource_name
            else "[bold cyan]GCP Hierarchy[/bold cyan]"
        )

        # Add root nodes to tree
        for node in hctx.nodes_to_process:
            if isinstance(node, OrganizationNode):
                node_id = node.organization.name
                if hctx.target_resource_name:
                    safe_path = f"//{path_escape(node.organization.display_name)}"
                    label = f"[bold cyan]{safe_path}[/bold cyan]"
                else:
                    label = f"[bold magenta]//{path_escape(node.organization.display_name)}[/bold magenta]"
            else:
                node_id = node.name
                label = f"[bold cyan]{node.path}[/bold cyan]"

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
            )

        # Organizationless projects
        if not hctx.target_resource_name and any(
            not p.organization for p in hctx.hierarchy.projects
        ):
            orgless_node = root_tree.add(
                "[bold yellow](organizationless)[/bold yellow]"
            )
            if level is None or level >= 1:
                orgless_projs = [
                    p for p in hctx.hierarchy.projects if not p.organization
                ]
                orgless_projs.sort(key=lambda x: x.display_name)
                for p in orgless_projs:
                    label = format_tree_label(p, show_ids)
                    orgless_node.add(label)

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
        help="Force a refresh of the cache from the GCP API",
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
        help="Force a refresh of the cache from the GCP API",
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

        for path in paths:
            logger.debug(f"name command: resolving path {path}")
            res_name = hierarchy.get_resource_name(path)
            logger.debug(f"name command: resolved {path} to {res_name}")
            if id_only:
                parts = res_name.split("/")
                res_name = parts[-1]
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
        for name in resource_names:
            try:
                # Use optimized recursive lookup instead of full hierarchy load
                p = Hierarchy.resolve_ancestry(name)
                logger.debug(f"path: resolved {name} to {p}")
                print(p)
            except Exception as e:
                # If one fails, log it but continue processing others?
                # Or just print error. CLI usually expects one output per line.
                # Let's print error to stderr and continue if multiple requested
                if len(resource_names) > 1:
                    error_console.print(f"[red]Error resolving {name}: {e}[/red]")
                else:
                    raise e

    except Exception as e:
        handle_error(e)


def run() -> None:
    app()


if __name__ == "__main__":
    app()
