"""
GCP Resource loading utilities.

This module handles loading resources from GCP via Resource Manager and Asset APIs.
"""

import logging
from typing import List, Optional

from google.cloud import resourcemanager_v3, asset_v1  # type: ignore
from google.api_core import exceptions

from gcpath.parsers import (
    parse_folder_row,
    parse_project_row,
    build_folder_ancestors,
)

logger = logging.getLogger(__name__)


def build_folder_sql_query(
    parent_filter: Optional[str] = None, ancestors_filter: Optional[str] = None
) -> str:
    """Build SQL query for loading folders from Asset API.

    Args:
        parent_filter: Only load folders directly under this parent
        ancestors_filter: Only load folders with this resource in their ancestors

    Returns:
        SQL query string for Asset API
    """
    base_query = (
        "SELECT name, resource.data.displayName, resource.data.parent, ancestors "
        "FROM `cloudresourcemanager_googleapis_com_Folder` "
        "WHERE resource.data.lifecycleState = 'ACTIVE'"
    )

    if parent_filter:
        # Scoped query: only direct children of the specified parent
        return f"{base_query} AND resource.data.parent = '{parent_filter}'"
    elif ancestors_filter:
        # Recursive query: all descendants of the specified ancestor
        # Use IN UNNEST() for array membership check in BigQuery SQL
        # Exclude the ancestor folder itself from results
        return (
            f"{base_query} "
            f"AND '{ancestors_filter}' IN UNNEST(ancestors) "
            f"AND name != '//cloudresourcemanager.googleapis.com/{ancestors_filter}'"
        )
    else:
        # Unscoped query: all folders under the org
        return base_query


def build_project_sql_query(
    parent_filter: Optional[str] = None, ancestors_filter: Optional[str] = None
) -> str:
    """Build SQL query for loading projects from Asset API.

    Args:
        parent_filter: Only load projects directly under this parent
        ancestors_filter: Only load projects with this resource in their ancestors

    Returns:
        SQL query string for Asset API
    """
    base_query = (
        "SELECT name, resource.data.projectNumber, resource.data.projectId, "
        "resource.data.parent, ancestors "
        "FROM `cloudresourcemanager_googleapis_com_Project` "
        "WHERE resource.data.lifecycleState = 'ACTIVE'"
    )

    if parent_filter:
        # Scoped query: only direct children of the specified parent
        # Note: parent is a STRUCT with 'type' and 'id' fields
        parent_id = parent_filter.split("/")[-1]
        return f"{base_query} AND resource.data.parent.id = '{parent_id}'"
    elif ancestors_filter:
        # Recursive query: all descendants of the specified ancestor
        # Use IN UNNEST() for array membership check in BigQuery SQL
        return f"{base_query} AND '{ancestors_filter}' IN UNNEST(ancestors)"
    else:
        # Unscoped query: all projects under the org
        return base_query


def load_folders_rm(node, org_name: str):
    """Load folders using Resource Manager API (recursive calls).

    Args:
        node: OrganizationNode to load folders into
        org_name: Organization resource name for ancestry

    Note: This function uses recursive API calls and is slower than Asset API.
          Prefer load_folders_asset() for better performance.
    """
    folders_client = resourcemanager_v3.FoldersClient()

    def recurse(parent_name: str, ancestors: List[str]):
        request = resourcemanager_v3.ListFoldersRequest(parent=parent_name)
        try:
            page = folders_client.list_folders(request=request)
            logger.debug(f"GCP API: list_folders() returned for {parent_name}")

            # Import Folder class locally to avoid circular dependency
            from gcpath.core import Folder

            for folder_proto in page:
                # ancestors list includes: [folder.Name, parent..., OrgName]
                new_ancestors = [folder_proto.name] + ancestors

                f = Folder(
                    name=folder_proto.name,
                    display_name=folder_proto.display_name,
                    ancestors=new_ancestors,
                    organization=node,
                    parent=parent_name,  # The parent we're listing under
                )
                node.folders[f.name] = f
                recurse(f.name, new_ancestors)
        except exceptions.PermissionDenied:
            logger.warning(f"Permission denied listing folders for {parent_name}")

    # Start recursion with Org
    # ancestors initially just the Org
    recurse(org_name, [org_name])


def fix_folder_ancestors(node):
    """Fix folder ancestors by traversing parent chain.

    Args:
        node: OrganizationNode containing folders to fix

    Note: This is needed because Asset API returns empty ancestors for full
          recursive loads. We build the full chain by traversing parents.
    """
    for folder in list(node.folders.values()):
        # Only fix if this folder has a folder parent and ancestors seem incomplete
        if not folder.parent.startswith("folders/"):
            continue

        # Build full ancestor chain by traversing parents
        ancestors = [folder.name]
        current_parent = folder.parent
        visited = {folder.name}  # Prevent infinite loops

        while current_parent and current_parent.startswith("folders/"):
            if current_parent in visited:
                logger.warning(f"Circular parent reference detected for {folder.name}")
                break
            visited.add(current_parent)
            ancestors.append(current_parent)

            # Look up the parent to continue the chain
            if current_parent in node.folders:
                parent_folder = node.folders[current_parent]
                current_parent = parent_folder.parent
            else:
                # Parent not in folders, stop here
                break

        # Add org at the end
        if not ancestors[-1].startswith("organizations/"):
            ancestors.append(node.organization.name)

        # Update if the ancestors changed
        if ancestors != folder.ancestors:
            folder.ancestors = ancestors
            logger.debug(
                f"Fixed ancestors for {folder.name} ({folder.display_name}): {ancestors}"
            )


def load_scope_folder(node, scope_resource: str):
    """Load a specific scope folder separately (for recursive scoped loads).

    Args:
        node: OrganizationNode to add folder to
        scope_resource: Folder resource name to load

    Note: When doing recursive scoped load, the scope folder itself is excluded
          from results. We need to load it separately so projects can find their
          parent folder.
    """
    if scope_resource in node.folders:
        # Already loaded
        return

    logger.debug(
        f"Recursive scoped load: loading scope folder {scope_resource} separately"
    )

    try:
        folders_client = resourcemanager_v3.FoldersClient()
        folder_proto = folders_client.get_folder(name=scope_resource)

        # Import Folder class locally to avoid circular dependency
        from gcpath.core import Folder

        # Build ancestors by traversing parent chain
        ancestors_chain = [folder_proto.name]
        current_parent = folder_proto.parent

        while current_parent and current_parent.startswith("folders/"):
            ancestors_chain.append(current_parent)
            # Check if parent is already loaded
            if current_parent in node.folders:
                # Use the loaded parent's ancestors
                loaded_folder = node.folders[current_parent]
                # Add remaining ancestors from parent (excluding the parent itself)
                ancestors_chain.extend(
                    [
                        a
                        for a in loaded_folder.ancestors
                        if a != current_parent and a not in ancestors_chain
                    ]
                )
                break
            else:
                # Fetch the parent folder
                try:
                    parent_proto = folders_client.get_folder(name=current_parent)
                    current_parent = parent_proto.parent
                except Exception:
                    break

        # Add organization at the end
        if not ancestors_chain or ancestors_chain[-1] != node.organization.name:
            ancestors_chain.append(node.organization.name)

        folder_obj = Folder(
            name=folder_proto.name,
            display_name=folder_proto.display_name,
            ancestors=ancestors_chain,
            organization=node,
            parent=folder_proto.parent,
        )
        node.folders[folder_proto.name] = folder_obj
        logger.debug(
            f"Added scope folder {scope_resource} with ancestors {ancestors_chain}"
        )
    except Exception as e:
        logger.warning(f"Could not load scope folder {scope_resource}: {e}")


def load_folders_asset(
    node, parent_filter: Optional[str] = None, ancestors_filter: Optional[str] = None
):
    """Load folders from Asset API.

    Args:
        node: OrganizationNode to load folders into
        parent_filter: Only load folders directly under this parent
        ancestors_filter: Only load folders with this resource in their ancestors

    Note: parent_filter and ancestors_filter are mutually exclusive.
          If neither is provided, loads ALL folders under the org.
    """
    asset_client = asset_v1.AssetServiceClient()

    # Build SQL query
    statement = build_folder_sql_query(parent_filter, ancestors_filter)

    logger.debug(f"Folders query: {statement}")
    query_request = asset_v1.QueryAssetsRequest(
        parent=node.organization.name,
        statement=statement,
    )

    response = asset_client.query_assets(request=query_request)
    logger.debug(
        f"GCP API: query_assets(folders) returned for {node.organization.name}"
    )

    # Iterate directly over the response (pagination is handled automatically)
    if not response.query_result or not response.query_result.rows:
        logger.debug("No folder rows returned from Asset API")
        return

    # Import Folder class locally to avoid circular dependency
    from gcpath.core import Folder

    for row in response.query_result.rows:
        try:
            # Parse the folder row using parsers module
            folder_data = parse_folder_row(row)

            # Get the parent - either from the API response or from parent_filter
            folder_parent = (
                folder_data["parent"]
                if folder_data["parent"]
                else (parent_filter if parent_filter else node.organization.name)
            )

            # Build complete ancestor chain
            ancestors = build_folder_ancestors(
                folder_data["name"],
                folder_data["ancestors"],
                folder_parent,
                node.folders,
                node.organization.name,
            )

            f = Folder(
                name=folder_data["name"],
                display_name=folder_data["display_name"],
                ancestors=ancestors,
                organization=node,
                parent=folder_parent,
            )
            node.folders[f.name] = f

        except (ValueError, KeyError) as e:
            logger.warning(f"Error parsing folder row: {e}")
            continue

    # Second pass: fix up ancestors for all folders by traversing parent chain
    fix_folder_ancestors(node)


def load_projects_asset(
    node, parent_filter: Optional[str] = None, ancestors_filter: Optional[str] = None
):
    """Load projects from Asset API.

    Args:
        node: OrganizationNode to associate projects with
        parent_filter: Only load projects directly under this parent
        ancestors_filter: Only load projects with this resource in their ancestors

    Returns:
        List of Project objects

    Note: parent_filter and ancestors_filter are mutually exclusive.
          If neither is provided, loads ALL projects under the org.
    """
    from gcpath.core import Project

    asset_client = asset_v1.AssetServiceClient()
    projects: List[Project] = []

    # Build SQL query
    statement = build_project_sql_query(parent_filter, ancestors_filter)

    logger.debug(f"Projects query: {statement}")
    query_request = asset_v1.QueryAssetsRequest(
        parent=node.organization.name,
        statement=statement,
    )

    try:
        response = asset_client.query_assets(request=query_request)
        logger.debug(
            f"GCP API: query_assets(projects) returned for {node.organization.name}"
        )

        # Iterate directly over the response
        if not response.query_result or not response.query_result.rows:
            logger.debug("No project rows returned from Asset API")
            logger.debug(f"Query result: {response.query_result}")
            return projects

        # Import Project class locally to avoid circular dependency
        from gcpath.core import Project

        for row in response.query_result.rows:
            try:
                # Parse the project row using parsers module
                project_data = parse_project_row(row)

                # Determine parent - prefer from API, then ancestors, then fallback
                if project_data["parent"]:
                    parent_res = project_data["parent"]
                elif not project_data["ancestors"]:
                    # No ancestors and no parent from API - use parent_filter if set, otherwise org
                    parent_res = (
                        parent_filter if parent_filter else node.organization.name
                    )
                elif (
                    project_data["ancestors"]
                    and project_data["ancestors"][0] == project_data["name"]
                ):
                    parent_res = (
                        project_data["ancestors"][1]
                        if len(project_data["ancestors"]) > 1
                        else (
                            parent_filter if parent_filter else node.organization.name
                        )
                    )
                else:
                    parent_res = (
                        project_data["ancestors"][0]
                        if project_data["ancestors"]
                        else (
                            parent_filter if parent_filter else node.organization.name
                        )
                    )

                parent_folder = None
                if parent_res.startswith("folders/"):
                    parent_folder = node.folders.get(parent_res)

                proj = Project(
                    name=project_data["name"],
                    project_id=project_data["project_id"],
                    display_name=project_data["display_name"],
                    parent=parent_res,
                    organization=node,
                    folder=parent_folder,
                )
                logger.debug(
                    f"Added project {project_data['project_id']} to hierarchy "
                    f"from Asset API (parent: {parent_res})"
                )
                projects.append(proj)

            except (ValueError, KeyError) as e:
                logger.warning(f"Error parsing project row: {e}")
                continue

    except Exception as e:
        logger.error(f"Error querying projects via Asset API: {e}")

    return projects


def load_organizationless_projects(existing_project_names: set):
    """Load organizationless projects using Resource Manager API.

    Args:
        existing_project_names: Set of project names already loaded

    Returns:
        List of Project objects for organizationless projects

    Note: Asset API queries require a parent (like organization).
          To find organizationless projects, we always fallback to Resource
          Manager search_projects API.
    """
    projects = []
    project_client = resourcemanager_v3.ProjectsClient()

    logger.debug(
        f"Falling back to search_projects() to find organizationless projects. "
        f"Already have {len(existing_project_names)} projects"
    )

    # Import Project class locally to avoid circular dependency
    from gcpath.core import Project

    try:
        projects_pager = project_client.search_projects(
            request=resourcemanager_v3.SearchProjectsRequest()
        )
        logger.debug("GCP API: search_projects() fallback returned successfully")

        for p_proto in projects_pager:
            if p_proto.name in existing_project_names:
                logger.debug(f"Project {p_proto.project_id} already loaded, skipping")
                continue

            # A project is organizationless if it's not under an organization or folder
            is_orgless = not p_proto.parent.startswith(
                "organizations/"
            ) and not p_proto.parent.startswith("folders/")

            if is_orgless:
                logger.debug(f"Found organizationless project: {p_proto.project_id}")
                proj = Project(
                    name=p_proto.name,
                    project_id=p_proto.project_id,
                    display_name=p_proto.display_name or p_proto.project_id,
                    parent=p_proto.parent,
                    organization=None,
                    folder=None,
                )
                projects.append(proj)

    except exceptions.PermissionDenied:
        logger.warning("Permission denied searching organizationless projects")
    except Exception as e:
        logger.error(f"Error searching organizationless projects: {e}")

    return projects
