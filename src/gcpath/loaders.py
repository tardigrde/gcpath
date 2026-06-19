"""
GCP Resource loading utilities.

This module handles loading resources from GCP via Resource Manager and Asset APIs.
"""

import logging
import re
import urllib.parse
from typing import Dict, List, Optional

from google.cloud import resourcemanager_v3, asset_v1  # type: ignore
from google.api_core import exceptions

from gcpath.parsers import (
    parse_folder_row,
    parse_project_row,
    build_folder_ancestors,
)

logger = logging.getLogger(__name__)

_FOLDER_PREFIX = "folders/"
_MISSING_STRUCT_FIELD_MARKER = "does not exist in STRUCT"
_RESOURCE_FILTER_RE = re.compile(r"^(organizations|folders)/[A-Za-z0-9_-]+$")


def _sql_resource_literal(resource: str) -> str:
    """Validate and quote a resource name for Asset API SQL."""
    if not _RESOURCE_FILTER_RE.fullmatch(resource):
        raise ValueError(f"Invalid resource filter '{resource}'")
    return resource.replace("'", "''")


def _query_assets_with_labels_fallback(
    asset_client,
    api_parent: str,
    build_query,
    include_labels: bool,
):
    """Run an Asset API query, retrying without labels if the schema lacks them.

    The Asset API derives its STRUCT schema from the data in scope: when no
    resource carries labels, selecting ``resource.data.labels`` fails with
    ``400 Field name labels does not exist in STRUCT<...>``.

    Args:
        asset_client: AssetServiceClient instance
        api_parent: Parent resource for QueryAssetsRequest
        build_query: Callable accepting ``include_labels`` and returning SQL
        include_labels: Whether to attempt fetching labels

    Returns:
        Tuple of (query response, effective include_labels after fallback)
    """
    statement = build_query(include_labels=include_labels)
    logger.debug(f"Asset query: {statement}")
    request = asset_v1.QueryAssetsRequest(parent=api_parent, statement=statement)
    try:
        return asset_client.query_assets(request=request), include_labels
    except exceptions.InvalidArgument as e:
        if not include_labels or _MISSING_STRUCT_FIELD_MARKER not in str(e):
            raise
        logger.warning(
            "Asset API schema has no labels field in this scope; "
            "retrying query without labels"
        )
        statement = build_query(include_labels=False)
        request = asset_v1.QueryAssetsRequest(parent=api_parent, statement=statement)
        return asset_client.query_assets(request=request), False


def build_folder_sql_query(
    parent_filter: Optional[str] = None,
    ancestors_filter: Optional[str] = None,
    include_labels: bool = False,
) -> str:
    """Build SQL query for loading folders from Asset API.

    Args:
        parent_filter: Only load folders directly under this parent
        ancestors_filter: Only load folders with this resource in their ancestors
        include_labels: If True, include resource.data.labels in SELECT

    Returns:
        SQL query string for Asset API
    """
    labels_col = ", resource.data.labels" if include_labels else ""
    base_query = (
        f"SELECT name, resource.data.displayName, resource.data.parent, ancestors{labels_col} "
        "FROM `cloudresourcemanager_googleapis_com_Folder` "
        "WHERE resource.data.lifecycleState = 'ACTIVE'"
    )

    if parent_filter:
        parent_filter = _sql_resource_literal(parent_filter)
        # Scoped query: only direct children of the specified parent
        return f"{base_query} AND resource.data.parent = '{parent_filter}'"
    elif ancestors_filter:
        ancestors_filter = _sql_resource_literal(ancestors_filter)
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
    parent_filter: Optional[str] = None,
    ancestors_filter: Optional[str] = None,
    include_labels: bool = False,
) -> str:
    """Build SQL query for loading projects from Asset API.

    Args:
        parent_filter: Only load projects directly under this parent
        ancestors_filter: Only load projects with this resource in their ancestors
        include_labels: If True, include resource.data.labels in SELECT

    Returns:
        SQL query string for Asset API
    """
    labels_col = ", resource.data.labels" if include_labels else ""
    base_query = (
        "SELECT name, resource.data.projectNumber, resource.data.projectId, "
        f"resource.data.parent, ancestors{labels_col} "
        "FROM `cloudresourcemanager_googleapis_com_Project` "
        "WHERE resource.data.lifecycleState = 'ACTIVE'"
    )

    if parent_filter:
        parent_filter = _sql_resource_literal(parent_filter)
        # Scoped query: only direct children of the specified parent
        # Note: parent is a STRUCT with 'type' and 'id' fields
        parent_id = parent_filter.split("/")[-1]
        return f"{base_query} AND resource.data.parent.id = '{parent_id}'"
    elif ancestors_filter:
        ancestors_filter = _sql_resource_literal(ancestors_filter)
        # Recursive query: all descendants of the specified ancestor
        # Use IN UNNEST() for array membership check in BigQuery SQL
        return f"{base_query} AND '{ancestors_filter}' IN UNNEST(ancestors)"
    else:
        # Unscoped query: all projects under the org
        return base_query


def load_folders_rm(node, root_parent: str, recursive: bool = True):
    """Load folders using Resource Manager API (recursive calls).

    Args:
        node: OrganizationNode to load folders into
        root_parent: Root resource name to start recursion from
                     (e.g., 'organizations/123' or 'folders/456')

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
                if recursive:
                    recurse(f.name, new_ancestors)
        except exceptions.PermissionDenied:
            logger.warning(f"Permission denied listing folders for {parent_name}")

    # Start recursion from root_parent
    recurse(root_parent, [root_parent])


def _build_single_ancestor_chain(folder, folders: Dict, root: str) -> List[str]:
    """Build the complete ancestor chain for a single folder.

    Args:
        folder: The folder to build ancestors for
        folders: Dict of all folders by name
        root: Root ancestor to append at the end

    Returns:
        List of ancestor resource names from folder to root
    """
    ancestors = [folder.name]
    current_parent = folder.parent
    visited = {folder.name}  # Prevent infinite loops

    while current_parent and current_parent.startswith(_FOLDER_PREFIX):
        if current_parent in visited:
            logger.warning(f"Circular parent reference detected for {folder.name}")
            break
        visited.add(current_parent)
        ancestors.append(current_parent)

        # Look up the parent to continue the chain
        if current_parent in folders:
            parent_folder = folders[current_parent]
            current_parent = parent_folder.parent
        else:
            # Parent not in folders, stop here
            break

    # Add root at the end
    if not ancestors[-1].startswith("organizations/") and ancestors[-1] != root:
        ancestors.append(root)

    return ancestors


def fix_folder_ancestors(node, root_ancestor: Optional[str] = None):
    """Fix folder ancestors by traversing parent chain.

    Args:
        node: OrganizationNode containing folders to fix
        root_ancestor: Override for the root ancestor appended to chains.
                       Defaults to node.organization.name.

    Note: This is needed because Asset API returns empty ancestors for full
          recursive loads. We build the full chain by traversing parents.
    """
    root = root_ancestor or node.organization.name
    for folder in node.folders.values():
        # Only fix if this folder has a folder parent and ancestors seem incomplete
        if not folder.parent.startswith(_FOLDER_PREFIX):
            continue

        ancestors = _build_single_ancestor_chain(folder, node.folders, root)

        # Update if the ancestors changed
        if ancestors != folder.ancestors:
            folder.ancestors = ancestors
            logger.debug(
                f"Fixed ancestors for {folder.name} ({folder.display_name}): {ancestors}"
            )


def load_scope_folder(node, scope_resource: str, root_ancestor: Optional[str] = None):
    """Load a specific scope folder separately (for recursive scoped loads).

    Args:
        node: OrganizationNode to add folder to
        scope_resource: Folder resource name to load
        root_ancestor: Override for the root ancestor appended to ancestor chains.
                       Defaults to node.organization.name.

    Note: When doing recursive scoped load, the scope folder itself is excluded
          from results. We need to load it separately so projects can find their
          parent folder.
    """
    if scope_resource in node.folders:
        # Already loaded
        return

    root = root_ancestor or node.organization.name

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
        display_chain = [folder_proto.display_name]
        current_parent = folder_proto.parent
        path_override = None

        while current_parent and current_parent.startswith(_FOLDER_PREFIX):
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
                escaped_leaf = urllib.parse.quote(folder_proto.display_name, safe="")
                path_override = f"{loaded_folder.path}/{escaped_leaf}"
                break
            else:
                # Fetch the parent folder
                try:
                    parent_proto = folders_client.get_folder(name=current_parent)
                    display_chain.append(parent_proto.display_name)
                    current_parent = parent_proto.parent
                except Exception:
                    break

        # Add root at the end
        if not ancestors_chain or ancestors_chain[-1] != root:
            ancestors_chain.append(root)
        if path_override is None and root.startswith("organizations/"):
            escaped_org = urllib.parse.quote(node.organization.display_name, safe="")
            escaped_segments = [
                urllib.parse.quote(segment, safe="")
                for segment in reversed(display_chain)
            ]
            path_override = "//" + "/".join([escaped_org, *escaped_segments])

        folder_obj = Folder(
            name=folder_proto.name,
            display_name=folder_proto.display_name,
            ancestors=ancestors_chain,
            organization=node,
            parent=folder_proto.parent,
            path_override=path_override,
        )
        node.folders[folder_proto.name] = folder_obj
        logger.debug(
            f"Added scope folder {scope_resource} with ancestors {ancestors_chain}"
        )
    except Exception as e:
        logger.warning(f"Could not load scope folder {scope_resource}: {e}")


def load_folders_asset(
    node,
    parent_filter: Optional[str] = None,
    ancestors_filter: Optional[str] = None,
    query_parent: Optional[str] = None,
    root_ancestor: Optional[str] = None,
    include_labels: bool = False,
):
    """Load folders from Asset API.

    Args:
        node: OrganizationNode to load folders into
        parent_filter: Only load folders directly under this parent
        ancestors_filter: Only load folders with this resource in their ancestors
        query_parent: Override for QueryAssetsRequest.parent (e.g., a folder).
                      Defaults to node.organization.name.
        root_ancestor: Override for the root ancestor in ancestor chains.
                       Defaults to node.organization.name.
        include_labels: If True, fetch labels for each folder.

    Note: parent_filter and ancestors_filter are mutually exclusive.
          If neither is provided, loads ALL folders under the org.
    """
    asset_client = asset_v1.AssetServiceClient()
    api_parent = query_parent or node.organization.name
    root = root_ancestor or node.organization.name

    response, has_labels = _query_assets_with_labels_fallback(
        asset_client,
        api_parent,
        lambda include_labels: build_folder_sql_query(
            parent_filter, ancestors_filter, include_labels=include_labels
        ),
        include_labels,
    )
    logger.debug(f"GCP API: query_assets(folders) returned for {api_parent}")

    # Iterate directly over the response (pagination is handled automatically)
    if not response.query_result or not response.query_result.rows:
        logger.debug("No folder rows returned from Asset API")
        return

    # Import Folder class locally to avoid circular dependency
    from gcpath.core import Folder

    for row in response.query_result.rows:
        try:
            # Parse the folder row using parsers module
            folder_data = parse_folder_row(row, has_labels=has_labels)

            # Get the parent - either from the API response or from parent_filter
            if folder_data["parent"]:
                folder_parent = folder_data["parent"]
            elif parent_filter:
                folder_parent = parent_filter
            else:
                folder_parent = root

            # Build complete ancestor chain
            ancestors = build_folder_ancestors(
                folder_data["name"],
                folder_data["ancestors"],
                folder_parent,
                node.folders,
                root,
            )

            f = Folder(
                name=folder_data["name"],
                display_name=folder_data["display_name"],
                ancestors=ancestors,
                organization=node,
                parent=folder_parent,
                labels=folder_data.get("labels", {}),
            )
            node.folders[f.name] = f

        except (ValueError, KeyError) as e:
            logger.warning(f"Error parsing folder row: {e}")
            continue

    # Second pass: fix up ancestors for all folders by traversing parent chain
    fix_folder_ancestors(node, root_ancestor=root)


def _resolve_project_parent(
    project_data: dict,
    parent_filter: Optional[str],
    fallback_parent: str,
) -> str:
    """Determine the parent resource name for a project from Asset API data.

    Priority: explicit parent > ancestors > parent_filter > org fallback.
    """
    if project_data["parent"]:
        return project_data["parent"]

    ancestors = project_data["ancestors"]
    if not ancestors:
        return parent_filter or fallback_parent

    # If first ancestor is the project itself, use second ancestor as parent
    if ancestors[0] == project_data["name"]:
        if len(ancestors) > 1:
            return ancestors[1]
        return parent_filter or fallback_parent

    return ancestors[0]


def load_projects_asset(
    node,
    parent_filter: Optional[str] = None,
    ancestors_filter: Optional[str] = None,
    query_parent: Optional[str] = None,
    include_labels: bool = False,
):
    """Load projects from Asset API.

    Args:
        node: OrganizationNode to associate projects with
        parent_filter: Only load projects directly under this parent
        ancestors_filter: Only load projects with this resource in their ancestors
        query_parent: Override for QueryAssetsRequest.parent (e.g., a folder).
                      Defaults to node.organization.name.
        include_labels: If True, fetch labels for each project.

    Returns:
        List of Project objects

    Note: parent_filter and ancestors_filter are mutually exclusive.
          If neither is provided, loads ALL projects under the org.
    """
    from gcpath.core import Project

    asset_client = asset_v1.AssetServiceClient()
    api_parent = query_parent or node.organization.name
    projects: List[Project] = []

    response, has_labels = _query_assets_with_labels_fallback(
        asset_client,
        api_parent,
        lambda include_labels: build_project_sql_query(
            parent_filter, ancestors_filter, include_labels=include_labels
        ),
        include_labels,
    )
    logger.debug(f"GCP API: query_assets(projects) returned for {api_parent}")

    if not response.query_result or not response.query_result.rows:
        logger.debug("No project rows returned from Asset API")
        return projects

    for row in response.query_result.rows:
        try:
            project_data = parse_project_row(row, has_labels=has_labels)
            parent_res = _resolve_project_parent(
                project_data,
                parent_filter,
                node.organization.name,
            )
            parent_folder = (
                node.folders.get(parent_res)
                if parent_res.startswith(_FOLDER_PREFIX)
                else None
            )

            proj = Project(
                name=project_data["name"],
                project_id=project_data["project_id"],
                display_name=project_data["display_name"],
                parent=parent_res,
                organization=node,
                folder=parent_folder,
                labels=project_data.get("labels", {}),
            )
            logger.debug(
                f"Added project {project_data['project_id']} to hierarchy "
                f"from Asset API (parent: {parent_res})"
            )
            projects.append(proj)

        except (ValueError, KeyError) as e:
            logger.warning(f"Error parsing project row: {e}")
            continue

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
            ) and not p_proto.parent.startswith(_FOLDER_PREFIX)

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

    return projects


def _parse_tag_binding_row(row) -> Optional[tuple]:
    """Parse a single TagBinding row from Asset API.

    Returns (parent_resource_name, tag_key, tag_value) or None on error.
    """
    from gcpath.parsers import extract_value, clean_asset_name

    try:
        row_dict = dict(row)
        f_list = row_dict.get("f", [])
        if len(f_list) < 4:
            return None

        parent_val = extract_value(f_list[1])
        tag_key = extract_value(f_list[2])
        tag_value = extract_value(f_list[3])

        if not parent_val or not tag_key or not tag_value:
            return None

        parent_name = clean_asset_name(str(parent_val))
        return (parent_name, str(tag_key), str(tag_value))
    except (TypeError, AttributeError, KeyError) as e:
        logger.warning(f"Error parsing tag binding row: {e}")
        return None


def load_tags_asset(parent: str) -> Dict[str, Dict[str, str]]:
    """Load tag bindings from Asset API.

    Queries the TagBinding asset type to get all tag bindings for resources
    under the given parent scope.

    Args:
        parent: The scope to query (e.g., 'organizations/123' or 'folders/456')

    Returns:
        Dict mapping resource names to their tags: {resource_name: {tag_key: tag_value}}
    """
    asset_client = asset_v1.AssetServiceClient()
    tags_map: Dict[str, Dict[str, str]] = {}

    statement = (
        "SELECT name, resource.data.parent, resource.data.tagKey, resource.data.tagValue "
        "FROM `cloudresourcemanager_googleapis_com_TagBinding`"
    )

    logger.debug(f"Tags query: {statement}")
    query_request = asset_v1.QueryAssetsRequest(
        parent=parent,
        statement=statement,
    )

    try:
        response = asset_client.query_assets(request=query_request)
        logger.debug(f"GCP API: query_assets(tags) returned for {parent}")

        if not response.query_result or not response.query_result.rows:
            logger.debug("No tag binding rows returned from Asset API")
            return tags_map

        for row in response.query_result.rows:
            parsed = _parse_tag_binding_row(row)
            if parsed:
                parent_name, tag_key, tag_value = parsed
                if parent_name not in tags_map:
                    tags_map[parent_name] = {}
                tags_map[parent_name][tag_key] = tag_value

    except exceptions.PermissionDenied:
        logger.warning("Permission denied querying tag bindings")
    except Exception as e:
        logger.error(f"Error querying tag bindings via Asset API: {e}")

    return tags_map


def apply_tags(hierarchy, tags_map: Dict[str, Dict[str, str]]) -> None:
    """Apply tag bindings to resources in a hierarchy.

    Args:
        hierarchy: Hierarchy object to update
        tags_map: Dict mapping resource names to their tags
    """
    for folder in hierarchy.folders:
        if folder.name in tags_map:
            folder.tags = tags_map[folder.name]
    for project in hierarchy.projects:
        if project.name in tags_map:
            project.tags = tags_map[project.name]
