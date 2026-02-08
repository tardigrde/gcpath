"""
Cache management for gcpath.

This module handles reading from and writing to the cache file.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, Dict, List

from google.cloud import resourcemanager_v3  # type: ignore

from gcpath.core import Hierarchy, OrganizationNode, Folder, Project

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".gcpath"
CACHE_FILE = CACHE_DIR / "cache.json"
CACHE_VERSION = 1
DEFAULT_CACHE_TTL_HOURS = 72


@dataclass
class CacheInfo:
    """Metadata about the cache state."""

    exists: bool
    fresh: bool
    age_seconds: Optional[float]
    size_bytes: Optional[int]
    version: Optional[int]
    org_count: int
    folder_count: int
    project_count: int


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


def read_cache_raw() -> Optional[Dict[str, Any]]:
    """Reads the raw JSON data from the cache file without deserializing to Hierarchy."""
    if not CACHE_FILE.exists():
        logger.debug("Cache file not found.")
        return None

    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
        logger.debug("Successfully loaded raw data from cache file.")
        return data
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Could not read cache file due to an error: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while reading cache: {e}")
        return None


def is_cache_fresh(
    data: Dict[str, Any], ttl_hours: float = DEFAULT_CACHE_TTL_HOURS
) -> bool:
    """Checks if the cache data is within the TTL."""
    timestamp_str = data.get("timestamp")
    if not timestamp_str:
        return False

    try:
        cached_time = datetime.fromisoformat(timestamp_str)
        age_seconds = (datetime.now(timezone.utc) - cached_time).total_seconds()
        return age_seconds < ttl_hours * 3600
    except (ValueError, TypeError):
        return False


def read_cache(ttl_hours: float = DEFAULT_CACHE_TTL_HOURS) -> Optional[Hierarchy]:
    """Reads the hierarchy from the cache file. Returns None if stale or missing."""
    data = read_cache_raw()
    if data is None:
        return None

    if not is_cache_fresh(data, ttl_hours):
        logger.debug("Cache is stale, ignoring.")
        return None

    return _dict_to_hierarchy(data)


def get_cache_info(
    ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
) -> CacheInfo:
    """Inspects cache state without full deserialization."""
    if not CACHE_FILE.exists():
        return CacheInfo(
            exists=False,
            fresh=False,
            age_seconds=None,
            size_bytes=None,
            version=None,
            org_count=0,
            folder_count=0,
            project_count=0,
        )

    try:
        size_bytes = CACHE_FILE.stat().st_size
        data = read_cache_raw()
        if data is None:
            return CacheInfo(
                exists=True,
                fresh=False,
                age_seconds=None,
                size_bytes=size_bytes,
                version=None,
                org_count=0,
                folder_count=0,
                project_count=0,
            )

        fresh = is_cache_fresh(data, ttl_hours)

        age_seconds: Optional[float] = None
        timestamp_str = data.get("timestamp")
        if timestamp_str:
            try:
                cached_time = datetime.fromisoformat(timestamp_str)
                age_seconds = (
                    datetime.now(timezone.utc) - cached_time
                ).total_seconds()
            except (ValueError, TypeError):
                pass

        # Count resources without full deserialization
        orgs = data.get("organizations", [])
        org_count = len(orgs)
        folder_count = sum(len(org.get("folders", {})) for org in orgs)
        project_count = sum(len(org.get("projects", [])) for org in orgs) + len(
            data.get("organizationless_projects", [])
        )

        return CacheInfo(
            exists=True,
            fresh=fresh,
            age_seconds=age_seconds,
            size_bytes=size_bytes,
            version=data.get("version"),
            org_count=org_count,
            folder_count=folder_count,
            project_count=project_count,
        )
    except Exception:
        return CacheInfo(
            exists=True,
            fresh=False,
            age_seconds=None,
            size_bytes=None,
            version=None,
            org_count=0,
            folder_count=0,
            project_count=0,
        )


def write_cache(hierarchy: Hierarchy) -> None:
    """Writes the hierarchy to the cache file."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data = _hierarchy_to_dict(hierarchy)
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Successfully wrote hierarchy to cache file: {CACHE_FILE}")
    except Exception as e:
        logger.error(f"Failed to write to cache file: {e}")


def clear_cache() -> bool:
    """Deletes the cache file."""
    try:
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
            logger.debug(f"Successfully deleted cache file: {CACHE_FILE}")
            return True
    except Exception as e:
        logger.error(f"Failed to delete cache file: {e}")
    return False
