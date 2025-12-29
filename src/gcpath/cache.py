"""
Cache management for gcpath.

This module handles reading from and writing to the cache file.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, Dict, List

from google.cloud import resourcemanager_v3  # type: ignore

from gcpath.core import Hierarchy, OrganizationNode, Folder, Project

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".gcpath"
CACHE_FILE = CACHE_DIR / "cache.json"
CACHE_VERSION = 1


def _hierarchy_to_dict(hierarchy: Hierarchy) -> Dict[str, Any]:
    """Serializes the Hierarchy object to a dictionary."""
    organizations_data = []

    # Map projects to their organizations for nested storage
    org_projects: Dict[str, List[Dict[str, Any]]] = {}
    orgless_projects_data: List[Dict[str, Any]] = []

    for project in hierarchy.projects:
        project_data = {
            "name": project.name,
            "project_id": project.project_id,
            "display_name": project.display_name,
            "parent": project.parent,
            "folder_name": project.folder.name if project.folder else None,
        }

        if project.organization:
            org_name = project.organization.organization.name
            if org_name not in org_projects:
                org_projects[org_name] = []
            org_projects[org_name].append(project_data)
        else:
            orgless_projects_data.append(project_data)

    for org_node in hierarchy.organizations:
        org_name = org_node.organization.name
        org_proto_data = {
            "name": org_name,
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
            {
                "organization": org_proto_data,
                "folders": folders_data,
                "projects": org_projects.get(org_name, []),
            }
        )

    return {
        "version": CACHE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "organizations": organizations_data,
        "organizationless_projects": orgless_projects_data,
    }


def _dict_to_hierarchy(data: Dict[str, Any]) -> Optional[Hierarchy]:
    """Deserializes a dictionary to a Hierarchy object."""
    if data.get("version") != CACHE_VERSION:
        logger.warning(
            f"Cache version mismatch (expected {CACHE_VERSION}, got {data.get('version')}). Ignoring cache."
        )
        return None

    org_nodes: List[OrganizationNode] = []
    projects: List[Project] = []

    # We explicitly recreate the protobuf object.
    # Note: resourcemanager_v3.Organization is a specialized Map/Message class.
    # We can instantiate it with kwargs matching the fields.

    for org_data in data.get("organizations", []):
        org_info = org_data["organization"]
        # Reconstruct Organization protobuf
        org_proto = resourcemanager_v3.Organization(
            name=org_info["name"], display_name=org_info["display_name"]
        )

        node = OrganizationNode(organization=org_proto)
        org_nodes.append(node)

        # Reconstruct Folders
        for folder_name, folder_data in org_data.get("folders", {}).items():
            folder = Folder(
                name=folder_data["name"],
                display_name=folder_data["display_name"],
                ancestors=folder_data["ancestors"],
                parent=folder_data["parent"],
                organization=node,
            )
            node.folders[folder_name] = folder

        # Reconstruct Projects for this Org
        for p_data in org_data.get("projects", []):
            folder_name = p_data.get("folder_name")
            parent_folder = node.folders.get(folder_name) if folder_name else None

            project = Project(
                name=p_data["name"],
                project_id=p_data["project_id"],
                display_name=p_data["display_name"],
                parent=p_data["parent"],
                organization=node,
                folder=parent_folder,
            )
            projects.append(project)

    # Reconstruct Organizationless Projects
    for p_data in data.get("organizationless_projects", []):
        project = Project(
            name=p_data["name"],
            project_id=p_data["project_id"],
            display_name=p_data["display_name"],
            parent=p_data["parent"],
            organization=None,
            folder=None,
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
