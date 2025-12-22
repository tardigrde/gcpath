import logging
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from google.cloud import resourcemanager_v3, asset_v1  # type: ignore
from google.api_core import exceptions

# We use a logger but don't configure it here.
# Configuration should happen at the application entry point.
logger = logging.getLogger(__name__)


class GCPathError(Exception):
    """Base exception for gcpath."""

    pass


class ResourceNotFoundError(GCPathError, ValueError):
    """Raised when a resource is not found."""

    pass


class PathParsingError(GCPathError, ValueError):
    """Raised when a path cannot be parsed."""

    pass


def path_escape(display_name: str) -> str:
    """Escape display names for use in paths."""
    return urllib.parse.quote(display_name, safe="")


def _clean_asset_name(name: str) -> str:
    """Strips the Asset API prefix from resource names."""
    prefix = "//cloudresourcemanager.googleapis.com/"
    if name.startswith(prefix):
        return name[len(prefix) :]
    return name


@dataclass
class OrganizationNode:
    organization: resourcemanager_v3.Organization
    folders: Dict[str, "Folder"] = field(default_factory=dict)

    def paths(self) -> List[str]:
        return [f.path for f in self.folders.values()]

    def get_resource_name(self, path: str) -> str:
        # path e.g. / or /a/b
        clean_path = path.strip("/")
        if not clean_path:
            return self.organization.name

        parts = clean_path.split("/")
        matches = []
        for folder in self.folders.values():
            if folder.is_path_match(parts):
                matches.append(folder)

        if len(matches) == 0:
            raise ResourceNotFoundError(
                f"No folder found with path '{path}' in '{self.organization.display_name}'"
            )
        if len(matches) > 1:
            raise ResourceNotFoundError(
                f"Multiple folders found with path '{path}' in '{self.organization.display_name}'"
            )

        return matches[0].name


@dataclass
class Folder:
    name: str
    display_name: str
    ancestors: List[str]
    organization: "OrganizationNode"
    parent: str = ""  # Parent resource name (e.g., 'organizations/123' or 'folders/456')

    def is_path_match(self, path_parts: List[str]) -> bool:
        # path matching logic
        if len(path_parts) + 1 != len(self.ancestors):
            return False

        # Determine ancestors to check against path.
        for i, part in enumerate(path_parts):
            ancestor_resource_name = self.ancestors[len(path_parts) - i - 1]
            folder = self.organization.folders.get(ancestor_resource_name)
            if not folder:
                return False

            if folder.display_name != part:
                return False

        return True

    @property
    def path(self) -> str:
        # Reconstruct path
        path_str = "//" + path_escape(self.organization.organization.display_name)

        # We iterate from Top to Bottom: [Leaf, Parent, ..., Org]
        if len(self.ancestors) >= 2:
            for i in range(len(self.ancestors) - 2, -1, -1):
                res_name = self.ancestors[i]
                parent = self.organization.folders.get(res_name)
                if parent:
                    path_str += "/" + path_escape(parent.display_name)
                else:
                    logger.warning(f"Ancestor {res_name} not found in folders map")
        return path_str


@dataclass
class Project:
    name: str
    project_id: str
    display_name: str
    parent: str
    organization: Optional["OrganizationNode"]
    folder: Optional[Folder]

    @property
    def path(self) -> str:
        if self.folder:
            return f"{self.folder.path}/{path_escape(self.display_name)}"
        if self.organization:
            return f"//{path_escape(self.organization.organization.display_name)}/{path_escape(self.display_name)}"
        # Organizationless project
        return f"//_/{path_escape(self.display_name)}"


class Hierarchy:
    def __init__(self, organizations: List[OrganizationNode], projects: List[Project]):
        self.organizations = organizations
        self.projects = projects

        # Build lookup maps for O(1) resource name resolution
        self._orgs_by_name: Dict[str, OrganizationNode] = {
            o.organization.name: o for o in organizations
        }
        self._folders_by_name: Dict[str, Folder] = {}
        for org in organizations:
            self._folders_by_name.update(org.folders)

        # Public list of all folders for convenience
        self.folders = list(self._folders_by_name.values())

        self._projects_by_name: Dict[str, Project] = {p.name: p for p in projects}

    @classmethod
    def load(
        cls,
        ctx_ignored=None,
        display_names: Optional[List[str]] = None,
        via_resource_manager: bool = True,
        scope_resource: Optional[str] = None,
        recursive: bool = False,
    ) -> "Hierarchy":
        """Load the GCP resource hierarchy.
        
        Args:
            ctx_ignored: Unused, for backward compatibility.
            display_names: Filter to only load these organization display names.
            via_resource_manager: If True, use Resource Manager API. If False, use Asset API.
            scope_resource: If provided, only load direct children of this resource
                           (e.g., 'organizations/123' or 'folders/456').
                           If None, defaults to loading from organization level.
            recursive: If True, load all descendants. If False, only load direct children.
                      Only applies when via_resource_manager=False (Asset API mode).
        """
        org_client = resourcemanager_v3.OrganizationsClient()
        project_client = resourcemanager_v3.ProjectsClient()

        # Load Orgs
        org_nodes = []
        try:
            logger.debug(
                f"Calling search_organizations() with display_names filter: {display_names}"
            )
            page_result = org_client.search_organizations(
                request=resourcemanager_v3.SearchOrganizationsRequest()
            )
            logger.debug("search_organizations() returned successfully")
            for org in page_result:
                if display_names and org.display_name not in display_names:
                    logger.debug(
                        f"Skipping organization '{org.display_name}' (not in filter)"
                    )
                    continue

                logger.debug(
                    f"Processing organization: {org.display_name} (name: {org.name})"
                )
                node = OrganizationNode(organization=org)
                org_nodes.append(node)

                if via_resource_manager:
                    cls._load_folders_rm(node)
                else:
                    # Determine filters for Asset API based on scope_resource and recursive
                    folder_parent_filter = None
                    folder_ancestors_filter = None
                    
                    if scope_resource:
                        if recursive:
                            # Load all descendants of the scope_resource
                            folder_ancestors_filter = scope_resource
                        else:
                            # Load only direct children of the scope_resource
                            folder_parent_filter = scope_resource
                    elif not recursive:
                        # Default non-recursive: load only direct children of the org
                        folder_parent_filter = node.organization.name
                    # else: recursive without scope = load everything (no filter)
                    
                    cls._load_folders_asset(node, parent_filter=folder_parent_filter, ancestors_filter=folder_ancestors_filter)

                    # When doing recursive scoped load, the scope folder itself is excluded from results
                    # We need to load it separately so projects can find their parent folder
                    if scope_resource and scope_resource.startswith("folders/") and recursive:
                        if scope_resource not in node.folders:
                            logger.debug(f"Recursive scoped load: loading scope folder {scope_resource} separately")
                            try:
                                folders_client = resourcemanager_v3.FoldersClient()
                                folder_proto = folders_client.get_folder(name=scope_resource)

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
                                        ancestors_chain.extend([a for a in loaded_folder.ancestors if a != current_parent and a not in ancestors_chain])
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
                                logger.debug(f"Added scope folder {scope_resource} with ancestors {ancestors_chain}")
                            except Exception as e:
                                logger.warning(f"Could not load scope folder {scope_resource}: {e}")

                logger.debug(
                    f"Loaded {len(node.folders)} folders for org {node.organization.display_name}"
                )
        except exceptions.PermissionDenied:
            logger.warning("Permission denied searching organizations")
        except Exception as e:
            logger.error(f"Error searching organizations: {e}")

        # Load Projects
        all_projects = []
        if via_resource_manager:
            try:
                # search_projects() lists all projects the user has access to
                projects_pager = project_client.search_projects(
                    request=resourcemanager_v3.SearchProjectsRequest()
                )
                logger.debug("GCP API: search_projects() returned successfully")
                for p_proto in projects_pager:
                    # Find parent
                    parent_org = None
                    parent_folder = None

                    if p_proto.parent.startswith("organizations/"):
                        parent_org = next(
                            (
                                o
                                for o in org_nodes
                                if o.organization.name == p_proto.parent
                            ),
                            None,
                        )
                    elif p_proto.parent.startswith("folders/"):
                        for o in org_nodes:
                            if p_proto.parent in o.folders:
                                parent_folder = o.folders[p_proto.parent]
                                parent_org = o
                                break

                    proj = Project(
                        name=p_proto.name,
                        project_id=p_proto.project_id,
                        display_name=p_proto.display_name or p_proto.project_id,
                        parent=p_proto.parent,
                        organization=parent_org,
                        folder=parent_folder,
                    )
                    all_projects.append(proj)
            except exceptions.PermissionDenied:
                logger.warning("Permission denied searching projects")
            except Exception as e:
                logger.error(f"Error searching projects: {e}")
        else:
            # Asset API mode
            for org_node in org_nodes:
                # Determine filters for projects based on scope_resource and recursive
                project_parent_filter = None
                project_ancestors_filter = None
                
                if scope_resource:
                    if recursive:
                        # Load all descendants of the scope_resource
                        project_ancestors_filter = scope_resource
                    else:
                        # Load only direct children of the scope_resource
                        project_parent_filter = scope_resource
                elif not recursive:
                    # Default non-recursive: load only direct children of the org
                    project_parent_filter = org_node.organization.name
                # else: recursive without scope = load everything (no filter)
                
                org_projects = cls._load_projects_asset(org_node, parent_filter=project_parent_filter, ancestors_filter=project_ancestors_filter)
                all_projects.extend(org_projects)

            # Asset API Query REQUIRES a parent (like organization).
            # To find organizationless projects, we always fallback to Resource Manager search_projects.
            existing_project_names = {p.name for p in all_projects}
            logger.debug(
                f"Falling back to search_projects() to find organizationless projects. Already have {len(existing_project_names)} projects"
            )
            try:
                projects_pager = project_client.search_projects(
                    request=resourcemanager_v3.SearchProjectsRequest()
                )
                logger.debug(
                    "GCP API: search_projects() fallback returned successfully"
                )
                for p_proto in projects_pager:
                    if p_proto.name in existing_project_names:
                        logger.debug(
                            f"Project {p_proto.project_id} already loaded, skipping"
                        )
                        continue

                    # A project is organizationless if it's not under an organization or folder.
                    is_orgless = not p_proto.parent.startswith(
                        "organizations/"
                    ) and not p_proto.parent.startswith("folders/")

                    if is_orgless:
                        logger.debug(
                            f"Found organizationless project: {p_proto.project_id}"
                        )
                        proj = Project(
                            name=p_proto.name,
                            project_id=p_proto.project_id,
                            display_name=p_proto.display_name or p_proto.project_id,
                            parent=p_proto.parent,
                            organization=None,
                            folder=None,
                        )
                        all_projects.append(proj)
            except exceptions.PermissionDenied:
                logger.warning("Permission denied searching organizationless projects")
            except Exception as e:
                logger.error(f"Error searching organizationless projects: {e}")

        return cls(organizations=org_nodes, projects=all_projects)

    @staticmethod
    def _load_folders_rm(node: OrganizationNode):
        folders_client = resourcemanager_v3.FoldersClient()

        def recurse(parent_name: str, ancestors: List[str]):
            request = resourcemanager_v3.ListFoldersRequest(parent=parent_name)
            try:
                page = folders_client.list_folders(request=request)
                logger.debug(f"GCP API: list_folders() returned for {parent_name}")
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
        recurse(node.organization.name, [node.organization.name])

    @staticmethod
    def _load_folders_asset(node: OrganizationNode, parent_filter: Optional[str] = None, ancestors_filter: Optional[str] = None):
        """Load folders from Asset API.
        
        Args:
            node: The organization node to load folders into.
            parent_filter: If provided, only load folders directly under this parent
                          (e.g., 'organizations/123' or 'folders/456').
            ancestors_filter: If provided, only load folders that have this resource
                             in their ancestors (all descendants recursively).
            
        Note: parent_filter and ancestors_filter are mutually exclusive.
              If neither is provided, loads ALL folders under the org.
        """
        asset_client = asset_v1.AssetServiceClient()
        
        # Build SQL query - always filter by lifecycle state
        # Include resource.data.parent to get the parent resource name
        base_query = "SELECT name, resource.data.displayName, resource.data.parent, ancestors FROM `cloudresourcemanager_googleapis_com_Folder` WHERE resource.data.lifecycleState = 'ACTIVE'"
        
        if parent_filter:
            # Scoped query: only direct children of the specified parent
            statement = f"{base_query} AND resource.data.parent = '{parent_filter}'"
        elif ancestors_filter:
            # Recursive query: all descendants of the specified ancestor
            # Use IN UNNEST() for array membership check in BigQuery SQL
            # Exclude the ancestor folder itself from results
            statement = f"{base_query} AND '{ancestors_filter}' IN UNNEST(ancestors) AND name != '//cloudresourcemanager.googleapis.com/{ancestors_filter}'"
        else:
            # Unscoped query: all folders under the org
            statement = base_query
        
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

        for row in response.query_result.rows:
            # The Asset API SQL results are returned in a Struct where the values
            # are in a list named 'f', similar to BigQuery JSON output.
            # 0: name, 1: displayName, 2: parent, 3: ancestors
            # IMPORTANT: The google-cloud-asset library returns MapComposite objects
            # which behave like dicts. Do NOT access .fields on them.
            row_dict = dict(row)
            if "f" not in row_dict:
                continue

            # row_dict["f"] is a list of values
            f_list = row_dict["f"]
            if len(f_list) < 4:
                logger.warning(
                    f"Unexpected number of columns in Asset API row: {len(f_list)}"
                )
                continue

            # Accessing struct values directly
            try:
                name_col = f_list[0]
                dn_col = f_list[1]
                parent_col = f_list[2]
                anc_col = f_list[3]

                # Extract values from MapComposite/dict-like objects
                # MapComposite behaves like a dict but isn't a dict instance
                name_val = name_col.get("v") if hasattr(name_col, "get") else name_col
                display_name = dn_col.get("v") if hasattr(dn_col, "get") else dn_col
                parent_val = parent_col.get("v") if hasattr(parent_col, "get") else parent_col
                ancestors_wrapper = (
                    anc_col.get("v") if hasattr(anc_col, "get") else anc_col
                )

                # Ancestors might be a list wrapper
                raw_ancestors_uncleaned = (
                    ancestors_wrapper if isinstance(ancestors_wrapper, list) else []
                )
                logger.debug(f"Found folder. Name: {name_val}, Display Name: {display_name}, Parent: {parent_val}, Ancestors: {raw_ancestors_uncleaned}")

            except (IndexError, AttributeError, TypeError) as e:
                logger.warning(f"Error parsing Asset API folder row: {e}")
                continue

            if not name_val or not display_name:
                logger.debug("Skipping folder row with missing name or display_name")
                continue

            name = _clean_asset_name(str(name_val))
            
            # Get the parent - either from the API response or from parent_filter
            folder_parent = str(parent_val) if parent_val else (parent_filter if parent_filter else node.organization.name)
            
            raw_ancestors = [
                _clean_asset_name(
                    str(item.get("v") if hasattr(item, "get") else item)
                )
                for item in raw_ancestors_uncleaned
            ]

            logger.debug(
                f"Parsed folder from Asset API: name={name}, display_name={display_name}, parent={folder_parent}"
            )

            # Ensure consistency with _load_folders_rm structure: [self, parent, ..., org]
            if not raw_ancestors or raw_ancestors[0] != name:
                ancestors = [name] + raw_ancestors
            else:
                ancestors = raw_ancestors

            # If we filtered by parent or have empty ancestors, build the full chain
            if not ancestors or (len(ancestors) == 1 and ancestors[0] == name):
                # Build full ancestor chain by traversing parents
                ancestors = [name]
                current_parent = folder_parent

                # Traverse up the parent chain
                while current_parent and current_parent.startswith("folders/"):
                    ancestors.append(current_parent)
                    # Check if this parent is already in node.folders
                    if current_parent in node.folders:
                        parent_folder = node.folders[current_parent]
                        # Add remaining ancestors from the parent (excluding duplicates)
                        for anc in parent_folder.ancestors:
                            if anc != current_parent and anc not in ancestors:
                                ancestors.append(anc)
                        break
                    else:
                        # Parent not loaded yet, will need to continue in next pass
                        # For now, just add org at the end
                        ancestors.append(node.organization.name)
                        break

                # If we didn't find any folders in the chain, add org
                if len(ancestors) == 1 or (len(ancestors) > 1 and not ancestors[-1].startswith("organizations/")):
                    ancestors.append(node.organization.name)

            f = Folder(
                name=name,
                display_name=display_name,
                ancestors=ancestors,
                organization=node,
                parent=folder_parent,
            )
            node.folders[f.name] = f

        # Second pass: fix up ancestors for all folders by traversing parent chain
        # This is needed because Asset API returns empty ancestors for full recursive loads
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
                logger.debug(f"Fixed ancestors for {folder.name} ({folder.display_name}): {ancestors}")

    @staticmethod
    def _load_projects_asset(node: OrganizationNode, parent_filter: Optional[str] = None, ancestors_filter: Optional[str] = None) -> List[Project]:
        """Load projects from Asset API.
        
        Args:
            node: The organization node to associate projects with.
            parent_filter: If provided, only load projects directly under this parent
                          (e.g., 'organizations/123' or 'folders/456').
            ancestors_filter: If provided, only load projects that have this resource
                             in their ancestors (all descendants recursively).
            
        Note: parent_filter and ancestors_filter are mutually exclusive.
              If neither is provided, loads ALL projects under the org.
        """
        asset_client = asset_v1.AssetServiceClient()
        projects: List[Project] = []
        
        # Build SQL query - always filter by lifecycle state
        # Include resource.data.parent to get parent info when ancestors is empty
        base_query = "SELECT name, resource.data.projectNumber, resource.data.projectId, resource.data.parent, ancestors FROM `cloudresourcemanager_googleapis_com_Project` WHERE resource.data.lifecycleState = 'ACTIVE'"
        
        if parent_filter:
            # Scoped query: only direct children of the specified parent
            # Note: parent is a STRUCT with 'type' and 'id' fields
            parent_id = parent_filter.split('/')[-1]
            statement = f"{base_query} AND resource.data.parent.id = '{parent_id}'"
        elif ancestors_filter:
            # Recursive query: all descendants of the specified ancestor
            # Use IN UNNEST() for array membership check in BigQuery SQL
            statement = f"{base_query} AND '{ancestors_filter}' IN UNNEST(ancestors)"
        else:
            # Unscoped query: all projects under the org
            statement = base_query
        
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

            for row in response.query_result.rows:
                try:
                    row_dict = dict(row)
                    if "f" not in row_dict:
                        continue

                    f_list = row_dict["f"]
                    if len(f_list) < 5:
                        logger.warning(
                            f"Unexpected number of columns in Asset API project row: {len(f_list)}"
                        )
                        continue

                    # 0: name, 1: projectNumber, 2: projectId, 3: parent (STRUCT), 4: ancestors
                    name_col = f_list[0]
                    # num_col = f_list[1] # unused
                    id_col = f_list[2]
                    parent_col = f_list[3]
                    anc_col = f_list[4]

                    # Extract values from MapComposite/dict-like objects
                    name_val = (
                        name_col.get("v") if hasattr(name_col, "get") else name_col
                    )
                    project_id = id_col.get("v") if hasattr(id_col, "get") else id_col
                    display_name = project_id  # Use projectId as displayName
                    
                    # Parent is a STRUCT with 'type' and 'id' fields
                    # The STRUCT is wrapped in {"v": {"f": [{"v": type}, {"v": id}]}} format
                    parent_struct_raw = parent_col.get("v") if hasattr(parent_col, "get") else parent_col
                    parent_from_api = None

                    if parent_struct_raw:
                        # Convert MapComposite to dict for easier access
                        parent_dict = dict(parent_struct_raw) if hasattr(parent_struct_raw, "keys") else {}

                        # Handle nested STRUCT format from Asset API: {"f": [{"v": type}, {"v": id}]}
                        # Note: parent_dict["f"] can be a list, RepeatedComposite, or similar iterable
                        if "f" in parent_dict and hasattr(parent_dict["f"], "__len__") and len(parent_dict["f"]) >= 2:
                            struct_fields = parent_dict["f"]

                            # Handle both dict and MapComposite objects in the list
                            type_field = struct_fields[0]
                            id_field = struct_fields[1]

                            # Extract 'v' value, handling MapComposite or dict
                            if hasattr(type_field, "get"):
                                type_val = type_field.get("v")
                            elif isinstance(type_field, dict):
                                type_val = type_field.get("v")
                            else:
                                type_val = type_field

                            if hasattr(id_field, "get"):
                                id_val = id_field.get("v")
                            elif isinstance(id_field, dict):
                                id_val = id_field.get("v")
                            else:
                                id_val = id_field

                            if type_val and id_val:
                                parent_type_plural = f"{type_val}s" if not type_val.endswith("s") else type_val
                                parent_from_api = f"{parent_type_plural}/{id_val}"
                                logger.debug(f"Project {project_id} parsed parent from nested format: {parent_from_api}")
                        # Also try direct access for simpler formats (for backwards compatibility with tests)
                        elif "type" in parent_dict and "id" in parent_dict:
                            parent_type = parent_dict["type"]
                            parent_id_val = parent_dict["id"]
                            if parent_type and parent_id_val:
                                parent_type_plural = f"{parent_type}s" if not parent_type.endswith("s") else parent_type
                                parent_from_api = f"{parent_type_plural}/{parent_id_val}"
                                logger.debug(f"Project {project_id} parsed parent from simple format: {parent_from_api}")

                    ancestors_wrapper = (
                        anc_col.get("v") if hasattr(anc_col, "get") else anc_col
                    )
                    raw_ancestors_uncleaned = (
                        ancestors_wrapper if isinstance(ancestors_wrapper, list) else []
                    )

                    name = _clean_asset_name(str(name_val))
                    raw_ancestors = [
                        _clean_asset_name(
                            str(item.get("v") if hasattr(item, "get") else item)
                        )
                        for item in raw_ancestors_uncleaned
                    ]

                    logger.debug(
                        f"Parsed project from Asset API: project_id={project_id}, name={name}, parent_from_api={parent_from_api}, ancestors={raw_ancestors}"
                    )

                except (IndexError, AttributeError, TypeError) as e:
                    logger.warning(f"Error parsing Asset API project row: {e}")
                    continue

                try:
                    # Determine parent - prefer parent_from_api, then ancestors, then fallback
                    if parent_from_api:
                        parent_res = parent_from_api
                    elif not raw_ancestors:
                        # No ancestors and no parent from API - use parent_filter if set, otherwise org
                        parent_res = parent_filter if parent_filter else node.organization.name
                    elif raw_ancestors[0] == name:
                        parent_res = (
                            raw_ancestors[1]
                            if len(raw_ancestors) > 1
                            else (parent_filter if parent_filter else node.organization.name)
                        )
                    else:
                        parent_res = (
                            raw_ancestors[0]
                            if raw_ancestors
                            else (parent_filter if parent_filter else node.organization.name)
                        )

                    parent_folder = None
                    if parent_res.startswith("folders/"):
                        parent_folder = node.folders.get(parent_res)

                    proj = Project(
                        name=name,
                        project_id=str(project_id),
                        display_name=str(display_name),
                        parent=parent_res,
                        organization=node,
                        folder=parent_folder,
                    )
                    logger.debug(
                        f"Added project {project_id} to hierarchy from Asset API (parent: {parent_res})"
                    )
                    projects.append(proj)
                except (IndexError, AttributeError, TypeError) as e:
                    logger.warning(f"Error processing project {name}: {e}")
                    continue
        except Exception as e:
            logger.error(f"Error querying projects via Asset API: {e}")

        return projects

    @staticmethod
    def _parse_path(path: str) -> tuple[str, str]:
        """Parse //org_name/path format without being fragile to urlparse semantics."""
        if not path.startswith("//"):
            raise PathParsingError("Path must start with //")

        trimmed = path[2:]
        if not trimmed:
            raise PathParsingError(
                "Path must contain an organization name (e.g., //example.com)"
            )

        parts = trimmed.split("/", 1)
        org_name = parts[0]
        resource_path = "/" + parts[1] if len(parts) > 1 else "/"
        return org_name, resource_path

    def get_resource_name(self, path: str) -> str:
        org_name, resource_path = self._parse_path(path)

        # Reserved for organizationless scope
        if org_name == "_":
            # Search in organizationless projects
            for proj in self.projects:
                if not proj.organization and proj.path == path:
                    return proj.name
            raise ResourceNotFoundError(
                f"Project path '{path}' not found in organizationless scope"
            )

        org_node = next(
            (o for o in self.organizations if o.organization.display_name == org_name),
            None,
        )
        if not org_node:
            raise ResourceNotFoundError(f"Organization '{org_name}' not found")

        if resource_path == "/":
            return org_node.organization.name

        try:
            return org_node.get_resource_name(resource_path)
        except ResourceNotFoundError:
            # Maybe it's a project at the end of the path?
            for proj in self.projects:
                if proj.organization == org_node and proj.path == path:
                    return proj.name
            raise

    def get_path_by_resource_name(self, resource_name: str) -> str:
        if resource_name.startswith("organizations/"):
            org = self._orgs_by_name.get(resource_name)
            if org:
                return "//" + path_escape(org.organization.display_name)
            raise ResourceNotFoundError(f"Organization '{resource_name}' not found")

        if resource_name.startswith("folders/"):
            folder = self._folders_by_name.get(resource_name)
            if folder:
                return folder.path
            raise ResourceNotFoundError(f"Folder '{resource_name}' not found")

        if resource_name.startswith("projects/"):
            proj = self._projects_by_name.get(resource_name)
            if proj:
                return proj.path
            raise ResourceNotFoundError(f"Project '{resource_name}' not found")

        raise ResourceNotFoundError(f"Unsupported resource name '{resource_name}'")

    @staticmethod
    def resolve_ancestry(resource_name: str) -> str:
        """
        Resolves the path for a given resource name by traversing up the hierarchy.
        This avoids loading the entire hierarchy.
        """
        folders_client = resourcemanager_v3.FoldersClient()
        projects_client = resourcemanager_v3.ProjectsClient()
        org_client = resourcemanager_v3.OrganizationsClient()

        segments: List[str] = []
        current_resource_name = resource_name

        # First, allow organizations/ID directly
        if current_resource_name.startswith("organizations/"):
            try:
                org = org_client.get_organization(name=current_resource_name)
                logger.debug(
                    f"GCP API: get_organization({current_resource_name}) returned"
                )
                return "//" + path_escape(org.display_name)
            except exceptions.PermissionDenied:
                logger.warning(
                    f"Permission denied accessing organization {current_resource_name}"
                )
                return f"//_unknown_org_({current_resource_name})"  # Fallback
            except Exception as e:
                logger.error(
                    f"Error fetching organization {current_resource_name}: {e}"
                )
                raise

        # Helper to fetch display name and parent
        def get_resource_info(name: str):
            if name.startswith("projects/"):
                try:
                    p = projects_client.get_project(name=name)
                    logger.debug(f"GCP API: get_project({name}) returned")
                    # Project display_name is optional, fallback to projectId
                    d_name = p.display_name or p.project_id
                    return d_name, p.parent
                except exceptions.PermissionDenied:
                    # If we can't see the project, we can't resolve its path
                    raise ResourceNotFoundError(
                        f"Permission denied accessing project {name}"
                    )

            elif name.startswith("folders/"):
                try:
                    f = folders_client.get_folder(name=name)
                    logger.debug(f"GCP API: get_folder({name}) returned")
                    return f.display_name, f.parent
                except exceptions.PermissionDenied:
                    raise ResourceNotFoundError(
                        f"Permission denied accessing folder {name}"
                    )

            elif name.startswith("organizations/"):
                try:
                    o = org_client.get_organization(name=name)
                    logger.debug(f"GCP API: get_organization({name}) returned")
                    return o.display_name, None
                except exceptions.PermissionDenied:
                    # This might happen at the top of the chain
                    return f"_unknown_org_({name})", None

            raise ResourceNotFoundError(f"Unknown resource type: {name}")

        # Traverse up
        while current_resource_name:
            try:
                display_name, parent = get_resource_info(current_resource_name)
                # We build the path relevant to the resource itself,
                # but we need to handle the root (Org).
                # If it's an organization, it becomes the prefix //Org
                if current_resource_name.startswith("organizations/"):
                    # We reached the top
                    path_prefix = "//" + path_escape(display_name)
                    # Prepend prefix to existing segments
                    full_path = path_prefix + (
                        ("/" + "/".join(segments)) if segments else ""
                    )
                    return full_path

                # If it's a project or folder, add to segments
                # Note: We are traversing UP, so we are collecting child -> parent
                # We insert at the beginning of the list later or just reverse.
                # Actually simpler: append to a list and reverse at the end?
                # But we build segments usually as [Folder, Subfolder, Resource]
                # Here we get Resource, then Parent (Folder), etc.
                segments.insert(0, path_escape(display_name))

                # Check for organizationless project
                if not parent:
                    # Missing parent usually implies Organizationless (or error)
                    # If we are at a project and it has no parent or parent is not org/folder
                    # (though get_resource_info handles standard types)
                    return "//_/" + "/".join(segments)

                current_resource_name = parent

            except exceptions.NotFound:
                raise ResourceNotFoundError(
                    f"Resource not found: {current_resource_name}"
                )
            except Exception:
                raise

        return "//?/" + "/".join(segments)  # Should not be reached ideally
