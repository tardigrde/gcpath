import typer
import logging
from typing import Optional, List, Dict, Union
from typing_extensions import Annotated
from rich.console import Console
from rich import print as rprint
from google.api_core import exceptions as gcp_exceptions


from gcpath.core import Hierarchy, path_escape, Project, GCPathError, OrganizationNode, Folder
from rich.table import Table

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
        error_console.print("[dim]Hint: Run 'gcloud auth application-default login'[/dim]")
    elif isinstance(e, gcp_exceptions.ServiceUnavailable):
        error_console.print("[red]Service Unavailable:[/red] The GCP API is currently unreachable.")
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


@app.command()
def ls(
    ctx: typer.Context,
    resource: Annotated[
        Optional[str],
        typer.Argument(help="Resource name (e.g. folders/123) or path to list children from."),
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
            if any(resource.startswith(p) for p in ["organizations/", "folders/", "projects/"]):
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
        hierarchy = Hierarchy.load(
            display_names=filter_orgs, 
            via_resource_manager=not ctx.obj["use_asset_api"]
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
        if target_resource_name:
            if target_resource_name.startswith("projects/"):
                # projects don't have children in this context
                return
            
            # Find the starting point
            current_folders = []
            current_projects = []
            
            if target_resource_name.startswith("organizations/"):
                for org in hierarchy.organizations:
                    if org.organization.name == target_resource_name:
                        # Top-level folders and projects of this org
                        current_folders = [f for f in org.folders.values() if len(f.ancestors) == 2]
                        current_projects = [p for p in hierarchy.projects if p.parent == target_resource_name]
                        break
            elif target_resource_name.startswith("folders/"):
                for org in hierarchy.organizations:
                    if target_resource_name in org.folders:
                        # Direct children of this folder
                        current_folders = [f for f in org.folders.values() if len(f.ancestors) > 1 and f.ancestors[1] == target_resource_name]
                        current_projects = [p for p in hierarchy.projects if p.parent == target_resource_name]
                        break
        else:
            # Default: list all organizations and projects directly under them
            current_folders = []
            current_projects = []
            for org in hierarchy.organizations:
                current_folders.extend([f for f in org.folders.values() if len(f.ancestors) == 2])
                current_projects.extend([p for p in hierarchy.projects if p.organization and p.parent == org.organization.name])
            
            # Add organizationless projects at the top level
            current_projects.extend([p for p in hierarchy.projects if not p.organization])

        # Prepare items for display
        items: List[tuple[str, Union[OrganizationNode, Folder, Project]]] = []
        if recursive:
            # Recursive listing - simplified approach: list everything under the target
            if target_resource_name:
                # Find all descendants
                if target_resource_name.startswith("organizations/"):
                    for org in hierarchy.organizations:
                        if org.organization.name == target_resource_name:
                            items.append((f"//{path_escape(org.organization.display_name)}", org))
                            for f in org.folders.values():
                                items.append((f.path, f))
                            for p in hierarchy.projects:
                                if p.organization and p.organization.organization.name == target_resource_name:
                                    items.append((p.path, p))
                elif target_resource_name.startswith("folders/"):
                    for org in hierarchy.organizations:
                        if target_resource_name in org.folders:
                            target_f = org.folders[target_resource_name]
                            items.append((target_f.path, target_f))
                            for f in org.folders.values():
                                if target_resource_name in f.ancestors and f.name != target_resource_name:
                                    items.append((f.path, f))
                            for p in hierarchy.projects:
                                if p.folder and target_resource_name in [a for a in p.folder.ancestors]:
                                    items.append((p.path, p))
            else:
                # Full recursive list
                for org in hierarchy.organizations:
                    items.append((f"//{path_escape(org.organization.display_name)}", org))
                    for f in org.folders.values():
                        items.append((f.path, f))
                for p in hierarchy.projects:
                    items.append((p.path, p))
        else:
            # Non-recursive
            if not target_resource_name:
                for org in hierarchy.organizations:
                    items.append((f"//{path_escape(org.organization.display_name)}", org))
            
            for f in current_folders:
                items.append((f.path, f))
            for p in current_projects:
                items.append((p.path, p))

        # Sort items
        items.sort(key=lambda x: x[0])

        if long:
            table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 1))
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
                    res_num = obj.name.split("/")[-1] if obj.name.startswith("projects/") else ""
                
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
        typer.Argument(help="Resource name (e.g. folders/123) or path to start tree from."),
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
            level = 3

        target_org_name = None
        target_resource_name = None
        target_path = None

        if resource:
            if resource.startswith("projects/"):
                 rprint("[red]Error:[/red] 'tree' command does not support starting from a project (projects are leaf nodes).")
                 raise typer.Exit(code=1)

            try:
                target_path = Hierarchy.resolve_ancestry(resource)
                if target_path.startswith("//"):
                    path_parts = target_path[2:].split("/")
                    if path_parts:
                        from urllib.parse import unquote
                        target_org_name = unquote(path_parts[0])
                
                if resource.startswith("folders/") or resource.startswith("organizations/"):
                    target_resource_name = resource
            except Exception:
                if resource.startswith("//"):
                    target_path = resource
                else:
                    raise

        filter_orgs = [target_org_name] if target_org_name else None
        hierarchy = Hierarchy.load(
            display_names=filter_orgs, 
            via_resource_manager=not ctx.obj["use_asset_api"]
        )
        
        nodes_to_process: List[Union[OrganizationNode, Folder]] = []
        if target_resource_name:
            if target_resource_name.startswith("organizations/"):
                 for o in hierarchy.organizations:
                     if o.organization.name == target_resource_name:
                         nodes_to_process = [o]
                         break
            elif target_resource_name.startswith("folders/"):
                 for o in hierarchy.organizations:
                     if target_resource_name in o.folders:
                         nodes_to_process = [o.folders[target_resource_name]]
                         break
            
            if not nodes_to_process:
                rprint(f"[red]Error:[/red] Target resource '{target_resource_name}' not found.")
                raise typer.Exit(code=1)
        else:
            nodes_to_process = list(hierarchy.organizations)

        root_tree = Tree("[bold cyan]Query Result[/bold cyan]" if target_resource_name else "[bold cyan]GCP Hierarchy[/bold cyan]")

        def build_tree(tree_node, current_node, current_depth):
            if level is not None and current_depth >= level:
                return

            parent_name = current_node.name if hasattr(current_node, "name") else current_node.organization.name
            
            # Projects
            children_projects = projects_by_parent.get(parent_name, [])
            children_projects.sort(key=lambda x: x.display_name)
            
            # Folders
            children_folders = []
            org_node_ref = current_node if isinstance(current_node, OrganizationNode) else current_node.organization
            
            if org_node_ref:
                for f in org_node_ref.folders.values():
                     if len(f.ancestors) > 1 and f.ancestors[1] == parent_name:
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
        if not target_resource_name and any(not p.organization for p in hierarchy.projects):
            orgless_node = root_tree.add("[bold yellow](organizationless)[/bold yellow]")
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
        hierarchy = Hierarchy.load(
            display_names=None, 
            via_resource_manager=not ctx.obj["use_asset_api"]
        )

        for path in paths:
            res_name = hierarchy.get_resource_name(path)
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
        for name in resource_names:
            try:
                # Use optimized recursive lookup instead of full hierarchy load
                p = Hierarchy.resolve_ancestry(name)
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
