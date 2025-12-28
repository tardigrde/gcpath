"""
Cache management for gcpath.

This module handles reading from and writing to the cache file.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Any, Dict, List

from gcpath.core import Hierarchy, OrganizationNode, Folder, Project

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".gcpath"
CACHE_FILE = CACHE_DIR / "cache.json"


class SimpleOrg:
    """A duck-typed object to replace the non-serializable Organization proto."""

    def __init__(self, name: str, display_name: str):
        self.name = name
        self.display_name = display_name


def _hierarchy_to_dict(hierarchy: Hierarchy) -> Dict[str, Any]:
    """Serializes the Hierarchy object to a dictionary."""
    organizations_data = []
    for org_node in hierarchy.organizations:
        org_proto_data = {
            "name": org_node.organization.name,
            "display_name": org_node.organization.display_name,
        }
        folders_data = {
            name: {
                "name": folder.name,
                "display_name": folder.display_name,
                "ancestors": folder.ancestors,
                "parent": folder.parent,
            }
            for name, folder in org_node.folders.items()
        }
        organizations_data.append(
            {"organization": org_proto_data, "folders": folders_data}
        )

    projects_data = []
    for project in hierarchy.projects:
        projects_data.append(
            {
                "name": project.name,
                "project_id": project.project_id,
                "display_name": project.display_name,
                "parent": project.parent,
                "organization_name": project.organization.organization.name
                if project.organization
                else None,
                "folder_name": project.folder.name if project.folder else None,
            }
        )

    return {"organizations": organizations_data, "projects": projects_data}


def _dict_to_hierarchy(data: Dict[str, Any]) -> Hierarchy:
    """Deserializes a dictionary to a Hierarchy object."""
    org_nodes: List[OrganizationNode] = []
    org_map: Dict[str, OrganizationNode] = {}

    for org_data in data.get("organizations", []):
        org_proto_data = org_data["organization"]
        org_proto = SimpleOrg(
            name=org_proto_data["name"], display_name=org_proto_data["display_name"]
        )
        node = OrganizationNode(organization=org_proto)
        org_nodes.append(node)
        org_map[node.organization.name] = node

    for i, org_data in enumerate(data.get("organizations", [])):
        org_node = org_nodes[i]
        for folder_name, folder_data in org_data.get("folders", {}).items():
            folder = Folder(
                name=folder_data["name"],
                display_name=folder_data["display_name"],
                ancestors=folder_data["ancestors"],
                parent=folder_data["parent"],
                organization=org_node,
            )
            org_node.folders[folder_name] = folder

    projects: List[Project] = []
    all_folders: Dict[str, Folder] = {}
    for org_node in org_nodes:
        all_folders.update(org_node.folders)

    for project_data in data.get("projects", []):
        org_name = project_data.get("organization_name")
        folder_name = project_data.get("folder_name")
        parent_org = org_map.get(org_name) if org_name else None
        parent_folder = all_folders.get(folder_name) if folder_name else None

        project = Project(
            name=project_data["name"],
            project_id=project_data["project_id"],
            display_name=project_data["display_name"],
            parent=project_data["parent"],
            organization=parent_org,
            folder=parent_folder,
        )
        projects.append(project)

    return Hierarchy(organizations=org_nodes, projects=projects)


def read_cache() -> Optional[Hierarchy]:
    """Reads the hierarchy from the cache file."""
    if not CACHE_FILE.exists():
        logger.debug("Cache file not found.")
        return None

    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
        logger.debug("Successfully loaded data from cache file.")
        return _dict_to_hierarchy(data)
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Could not read cache file due to an error: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while reading cache: {e}")
        return None


def write_cache(hierarchy: Hierarchy):
    """Writes the hierarchy to the cache file."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data = _hierarchy_to_dict(hierarchy)
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Successfully wrote hierarchy to cache file: {CACHE_FILE}")
    except Exception as e:
        logger.error(f"Failed to write to cache file: {e}")


def clear_cache():
    """Deletes the cache file."""
    try:
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
            logger.debug(f"Successfully deleted cache file: {CACHE_FILE}")
            return True
    except Exception as e:
        logger.error(f"Failed to delete cache file: {e}")
    return False
