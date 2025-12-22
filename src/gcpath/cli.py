import typer
import logging
from typing import Optional, List, Dict, Union
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
from rich.table import Table

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="gcpath",
    help="Google Cloud Platform resource hierarchy utility",
    add_completion=False,
)
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
) -> None:
    """
    gcpath - Google Cloud Platform resource hierarchy utility
    """
    ctx.ensure_object(dict)
    ctx.obj["use_asset_api"] = use_asset_api

    if debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.ERROR)
    
    # Always suppress urllib3 debug logs
    logging.getLogger("urllib3").setLevel(logging.WARNING)


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
) -> None:
    """
    List folders and projects. Defaults to the root organization.
    """
    try:
        target_org_name = None
        target_resource_name = None

        if resource:
            # Check if it's already a GCP resource name
            if any(
                resource.startswith(p)
                for p in ["organizations/", "folders/", "projects/"]
            ):
                target_resource_name = resource
                try:
                    target_path = Hierarchy.resolve_ancestry(resource)
                    if target_path.startswith("//"):
                        path_parts = target_path[2:].split("/")
                        if path_parts:
                            from urllib.parse import unquote

                            target_org_name = unquote(path_parts[0])
                except Exception:
                    pass
            # If it's a path, we'd need to resolve it back to resource name
            # For simplicity, we mostly support resource names or defaults to org load
            elif resource.startswith("//"):
                # Handle path to name resolution if needed, but SPEC emphasizes resource name args
                pass

        filter_orgs = [target_org_name] if target_org_name else None
        logger.debug(
            f"ls: loading hierarchy for resource='{resource}', filter_orgs={filter_orgs}, recursive={recursive}"
        )
        
        # Determine scope_resource for API-level filtering
        # If targeting a specific resource, pass it as scope_resource
        # so the API only returns direct children (or all descendants if recursive)
        scope_resource = target_resource_name if target_resource_name else None
        
        hierarchy = Hierarchy.load(
            display_names=filter_orgs,
            via_resource_manager=not ctx.obj["use_asset_api"],
            scope_resource=scope_resource,
            recursive=recursive,
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
                target_path_prefix = Hierarchy.resolve_ancestry(target_resource_name)
                logger.debug(f"ls: target path prefix: {target_path_prefix}")
            except Exception as e:
                logger.warning(f"Could not resolve target path: {e}")

        # Filter folders and projects to show
        # For Asset API mode, the hierarchy is pre-filtered, but we still need to filter
        # to only direct children for non-recursive mode
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
            current_projects.extend(
                [p for p in hierarchy.projects if not p.organization]
            )

        # Helper function to build path for display
        def get_display_path(item: Union[OrganizationNode, Folder, Project], is_direct_child: bool = False) -> str:
            if isinstance(item, OrganizationNode):
                return f"//{path_escape(item.organization.display_name)}"
            elif isinstance(item, Folder):
                # For non-recursive mode with direct children, use target prefix
                # For recursive mode, always use the computed path from hierarchy
                if target_path_prefix and target_resource_name and is_direct_child and not recursive:
                    return f"{target_path_prefix}/{path_escape(item.display_name)}"
                return item.path
            elif isinstance(item, Project):
                # For non-recursive mode with direct children, use target prefix
                # For recursive mode, always use the computed path from hierarchy
                if target_path_prefix and target_resource_name and is_direct_child and not recursive:
                    return f"{target_path_prefix}/{path_escape(item.display_name)}"
                return item.path
            return ""

        # Prepare items for display
        items: List[tuple[str, Union[OrganizationNode, Folder, Project]]] = []
        if recursive:
            # Recursive listing - list everything under the target
            # Since we loaded with recursive=True, all descendants are in the hierarchy
            if target_resource_name:
                # All loaded folders and projects are descendants
                # Use item.path for recursive mode (not is_direct_child logic)
                for f in hierarchy.folders:
                    items.append((get_display_path(f, is_direct_child=False), f))
                for p in hierarchy.projects:
                    items.append((get_display_path(p, is_direct_child=False), p))
            else:
                # Full recursive list
                for org in hierarchy.organizations:
                    items.append((get_display_path(org, is_direct_child=False), org))
                    for f in org.folders.values():
                        items.append((get_display_path(f, is_direct_child=False), f))
                for p in hierarchy.projects:
                    items.append((get_display_path(p, is_direct_child=False), p))
        else:
            # Non-recursive - only direct children
            if not target_resource_name:
                for org in hierarchy.organizations:
                    items.append((get_display_path(org, is_direct_child=False), org))

            for f in current_folders:
                items.append((get_display_path(f, is_direct_child=True), f))
            for p in current_projects:
                items.append((get_display_path(p, is_direct_child=True), p))

        # Sort items
        items.sort(key=lambda x: x[0])

        logger.debug(f"ls: found {len(items)} items to display")

        if long:
            table = Table(
                show_header=True, header_style="bold magenta", box=None, padding=(0, 1)
            )
            table.add_column("Path", width=35)
            table.add_column("ID", width=15)
            table.add_column("NAME", width=15)
            table.add_column("NUMBER", width=15)

            for path, obj in items:
                res_id = ""
                res_name = ""
                res_num = ""

                if isinstance(obj, OrganizationNode):
                    res_id = obj.organization.name.split("/")[-1]
                    res_name = obj.organization.display_name
                elif isinstance(obj, Folder):
                    res_id = obj.name.split("/")[-1]
                    res_name = obj.display_name
                elif isinstance(obj, Project):
                    res_id = obj.project_id
                    res_name = obj.display_name
                    res_num = (
                        obj.name.split("/")[-1]
                        if obj.name.startswith("projects/")
                        else ""
                    )

                table.add_row(path, res_id, res_name, res_num)

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
        None, "--level", "-L", help="Max display depth of the tree"
    ),
    show_ids: bool = typer.Option(
        False, "--ids", "-i", help="Show resource names in the tree"
    ),
) -> None:
    """
    Display the resource hierarchy in a tree format.
    """
    from rich.tree import Tree

    try:
        # Enforce SPEC max depth
        if level is not None and level > 3:
            error_console.print(
                f"[red]Error:[/red] Maximum tree depth is 3. Requested level {level} exceeds the limit."
            )
            raise typer.Exit(code=1)

        target_org_name = None
        target_resource_name = None
        target_path = None

        if resource:
            logger.debug(f"tree command: processing resource argument {resource}")
            if resource.startswith("projects/"):
                rprint(
                    "[red]Error:[/red] 'tree' command does not support starting from a project (projects are leaf nodes)."
                )
                raise typer.Exit(code=1)

            try:
                target_path = Hierarchy.resolve_ancestry(resource)
                if target_path.startswith("//"):
                    path_parts = target_path[2:].split("/")
                    if path_parts:
                        from urllib.parse import unquote

                        target_org_name = unquote(path_parts[0])

                if resource.startswith("folders/") or resource.startswith(
                    "organizations/"
                ):
                    target_resource_name = resource
            except Exception:
                if resource.startswith("//"):
                    target_path = resource
                else:
                    raise

        filter_orgs = [target_org_name] if target_org_name else None
        logger.debug(
            f"tree: loading hierarchy for resource='{resource}', filter_orgs={filter_orgs}"
        )
        
        # Tree always needs recursive loading to show the full subtree
        hierarchy = Hierarchy.load(
            display_names=filter_orgs,
            via_resource_manager=not ctx.obj["use_asset_api"],
            scope_resource=target_resource_name,
            recursive=True,  # Tree always needs full subtree
        )
        logger.debug(
            f"tree: hierarchy loaded with {len(hierarchy.organizations)} orgs, {len(hierarchy.projects)} projects, {len(hierarchy.folders)} folders"
        )

        nodes_to_process: List[Union[OrganizationNode, Folder]] = []
        if target_resource_name:
            logger.debug(
                f"tree command: looking for target resource {target_resource_name}"
            )
            if target_resource_name.startswith("organizations/"):
                for o in hierarchy.organizations:
                    if o.organization.name == target_resource_name:
                        logger.debug("tree command: found target organization")
                        nodes_to_process = [o]
                        break
            elif target_resource_name.startswith("folders/"):
                # When using ancestors_filter, the scope folder itself is not in the loaded hierarchy.
                # We need to create a synthetic folder node for display purposes.
                for o in hierarchy.organizations:
                    if target_resource_name in o.folders:
                        logger.debug(
                            "tree command: found target folder in organization"
                        )
                        nodes_to_process = [o.folders[target_resource_name]]
                        break
                
                # If not found in loaded hierarchy, create a synthetic folder from resolved path
                if not nodes_to_process and target_path and hierarchy.organizations:
                    logger.debug("tree command: creating synthetic folder node for scope")
                    # Extract display name from the resolved path
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
                    # Add to org's folders so build_tree can find children
                    org_node.folders[target_resource_name] = synthetic_folder
                    nodes_to_process = [synthetic_folder]
                    logger.debug(f"tree command: created synthetic folder {synthetic_folder.name}")

            if not nodes_to_process:
                logger.warning(
                    f"tree command: target resource '{target_resource_name}' not found"
                )
                rprint(
                    f"[red]Error:[/red] Target resource '{target_resource_name}' not found."
                )
                raise typer.Exit(code=1)
        else:
            logger.debug(
                f"tree command: processing all {len(hierarchy.organizations)} organizations"
            )
            nodes_to_process = list(hierarchy.organizations)

        root_tree = Tree(
            "[bold cyan]Query Result[/bold cyan]"
            if target_resource_name
            else "[bold cyan]GCP Hierarchy[/bold cyan]"
        )

        def build_tree(tree_node, current_node, current_depth):
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
                label = f"[bold blue]{f.display_name}[/bold blue]"
                if show_ids:
                    label += f" [dim]({f.name})[/dim]"
                sub_node = tree_node.add(label)
                build_tree(sub_node, f, current_depth + 1)

            for p in children_projects:
                label = f"[green]{p.display_name}[/green]"
                if show_ids:
                    label += f" [dim]({p.name})[/dim]"
                tree_node.add(label)

        projects_by_parent: Dict[str, List[Project]] = {}
        for proj in hierarchy.projects:
            projects_by_parent.setdefault(proj.parent, []).append(proj)

        for node in nodes_to_process:
            if isinstance(node, OrganizationNode):
                node_id = node.organization.name
                if target_resource_name:
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
            build_tree(node_tree, node, 0)

        # Organizationless projects
        if not target_resource_name and any(
            not p.organization for p in hierarchy.projects
        ):
            orgless_node = root_tree.add(
                "[bold yellow](organizationless)[/bold yellow]"
            )
            if level is None or level >= 1:
                orgless_projs = [p for p in hierarchy.projects if not p.organization]
                orgless_projs.sort(key=lambda x: x.display_name)
                for p in orgless_projs:
                    label = f"[green]{p.display_name}[/green]"
                    if show_ids:
                        label += f" [dim]({p.name})[/dim]"
                    orgless_node.add(label)

        console.print(root_tree)

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
) -> None:
    """
    Get Google Cloud Platform resource name by path.
    """
    try:
        logger.debug(f"name: resolving paths={paths}")
        hierarchy = Hierarchy.load(
            display_names=None,
            via_resource_manager=not ctx.obj["use_asset_api"],
            recursive=True  # Load all folders including nested ones for path resolution
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
