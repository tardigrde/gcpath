import typer
import logging
from typing import Optional, List, Dict
from typing_extensions import Annotated
from rich.console import Console
from rich import print as rprint
from google.api_core import exceptions as gcp_exceptions

from gcpath.core import Hierarchy, path_escape, Project, GCPathError

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
    organizations: Annotated[
        Optional[List[str]],
        typer.Argument(help="Organization display names to filter (optional)"),
    ] = None,
    long: bool = typer.Option(
        False, "--long", "-l", help="Show resource names along with paths"
    ),
    recursive: bool = typer.Option(
        True, "--recursive/--no-recursive", "-R/-r", help="List resources recursively"
    ),
) -> None:
    """
    List all folders and projects in your organizations.
    """
    try:
        hierarchy = Hierarchy.load(
            display_names=organizations, 
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

        items = []
        for org in hierarchy.organizations:
            if recursive:
                # Add org itself
                items.append(
                    (
                        f"//{path_escape(org.organization.display_name)}",
                        org.organization.name,
                    )
                )
                for folder in org.folders.values():
                    items.append((folder.path, folder.name))
            else:
                # Only top level
                items.append(
                    (
                        f"//{path_escape(org.organization.display_name)}",
                        org.organization.name,
                    )
                )

        for proj in hierarchy.projects:
            if recursive or not proj.folder:
                items.append((proj.path, proj.name))

        # Sort items for consistent output
        items.sort(key=lambda x: x[0])

        for path, res_name in items:
            if long:
                print(f"{path:<60} {res_name}")
            else:
                print(path)

    except Exception as e:
        handle_error(e)


@app.command()
def tree(
    ctx: typer.Context,
    organizations: Annotated[
        Optional[List[str]],
        typer.Argument(help="Organization display names to filter (optional)"),
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
        hierarchy = Hierarchy.load(
            display_names=organizations, 
            via_resource_manager=not ctx.obj["use_asset_api"]
        )

        root_tree = Tree("[bold cyan]GCP Hierarchy[/bold cyan]")

        # Group projects by parent
        projects_by_parent: Dict[str, List[Project]] = {}
        for proj in hierarchy.projects:
            projects_by_parent.setdefault(proj.parent, []).append(proj)

        def add_folders(tree_node, org_node, parent_name, current_depth):
            if level is not None and current_depth > level:
                return

            subfolders = []
            for f in org_node.folders.values():
                if len(f.ancestors) == 1 and parent_name == org_node.organization.name:
                    subfolders.append(f)
                elif len(f.ancestors) > 1 and f.ancestors[1] == parent_name:
                    subfolders.append(f)

            subfolders.sort(key=lambda x: x.display_name)

            for f in subfolders:
                label = f"[bold blue]{f.display_name}[/bold blue]"
                if show_ids:
                    label += f" [dim]({f.name})[/dim]"
                sub_node = tree_node.add(label)

                # Add projects in this folder
                add_projects(sub_node, f.name, current_depth + 1)

                # Recurse
                add_folders(sub_node, org_node, f.name, current_depth + 1)

        def add_projects(tree_node, parent_name, current_depth):
            if level is not None and current_depth > level:
                return
            projs = projects_by_parent.get(parent_name, [])
            projs.sort(key=lambda x: x.display_name)
            for p in projs:
                label = f"[green]{p.display_name}[/green]"
                if show_ids:
                    label += f" [dim]({p.name})[/dim]"
                tree_node.add(label)

        # Add Organizations
        for org in hierarchy.organizations:
            label = f"[bold magenta]{org.organization.display_name}[/bold magenta]"
            if show_ids:
                label += f" [dim]({org.organization.name})[/dim]"
            org_tree = root_tree.add(label)

            add_projects(org_tree, org.organization.name, 1)
            add_folders(org_tree, org, org.organization.name, 1)

        # Add Organizationless projects
        if any(not p.organization for p in hierarchy.projects):
            orgless_node = root_tree.add(
                "[bold yellow](organizationless)[/bold yellow]"
            )
            for p in hierarchy.projects:
                if not p.organization:
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
