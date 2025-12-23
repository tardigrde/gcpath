"""gcpath - Google Cloud Platform resource hierarchy utility."""

from gcpath.core import (
    Hierarchy,
    OrganizationNode,
    Folder,
    Project,
    GCPathError,
    ResourceNotFoundError,
    PathParsingError,
    path_escape,
)
from gcpath.cli import run
from gcpath.loaders import (
    load_folders_rm,
    load_folders_asset,
    load_projects_asset,
    load_organizationless_projects,
)
from gcpath.parsers import (
    parse_project_row,
    parse_folder_row,
    clean_asset_name,
)
from gcpath.formatters import (
    get_display_path,
    build_tree_view,
    filter_direct_children,
)

__all__ = [
    # Core data structures
    "Hierarchy",
    "OrganizationNode",
    "Folder",
    "Project",
    # Exceptions
    "GCPathError",
    "ResourceNotFoundError",
    "PathParsingError",
    # Utilities
    "path_escape",
    # CLI
    "run",
    # Loaders
    "load_folders_rm",
    "load_folders_asset",
    "load_projects_asset",
    "load_organizationless_projects",
    # Parsers
    "parse_project_row",
    "parse_folder_row",
    "clean_asset_name",
    # Formatters
    "get_display_path",
    "build_tree_view",
    "filter_direct_children",
]
