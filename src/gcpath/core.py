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
    ) -> "Hierarchy":
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
                    cls._load_folders_asset(node)
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
                org_projects = cls._load_projects_asset(org_node)
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
                    )
                    node.folders[f.name] = f
                    recurse(f.name, new_ancestors)
            except exceptions.PermissionDenied:
                logger.warning(f"Permission denied listing folders for {parent_name}")

        # Start recursion with Org
        # ancestors initially just the Org
        recurse(node.organization.name, [node.organization.name])

    @staticmethod
    def _load_folders_asset(node: OrganizationNode):
        asset_client = asset_v1.AssetServiceClient()
        # "SELECT name, resource.data.displayName, ancestors FROM `cloudresourcemanager_googleapis_com_Folder`"

        statement = "SELECT name, resource.data.displayName, ancestors FROM `cloudresourcemanager_googleapis_com_Folder`"
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
            # 0: name, 1: displayName, 2: ancestors
            # IMPORTANT: The google-cloud-asset library returns MapComposite objects
            # which behave like dicts. Do NOT access .fields on them.
            row_dict = dict(row)
            if "f" not in row_dict:
                continue

            # row_dict["f"] is a list of values
            f_list = row_dict["f"]
            if len(f_list) < 3:
                logger.warning(
                    f"Unexpected number of columns in Asset API row: {len(f_list)}"
                )
                continue

            # Accessing struct values directly
            try:
                name_col = f_list[0]
                dn_col = f_list[1]
                anc_col = f_list[2]

                # Check if it's a dict with 'v' or just potential direct value
                name_val = name_col.get("v") if isinstance(name_col, dict) else name_col
                display_name = dn_col.get("v") if isinstance(dn_col, dict) else dn_col
                ancestors_wrapper = (
                    anc_col.get("v") if isinstance(anc_col, dict) else anc_col
                )

                # Ancestors might be a list wrapper
                raw_ancestors_uncleaned = (
                    ancestors_wrapper if isinstance(ancestors_wrapper, list) else []
                )

            except (IndexError, AttributeError, TypeError) as e:
                logger.warning(f"Error parsing Asset API folder row: {e}")
                continue

            if not name_val or not display_name:
                logger.debug("Skipping folder row with missing name or display_name")
                continue

            name = _clean_asset_name(str(name_val))
            raw_ancestors = [
                _clean_asset_name(
                    str(item.get("v") if isinstance(item, dict) else item)
                )
                for item in raw_ancestors_uncleaned
            ]

            logger.debug(
                f"Parsed folder from Asset API: name={name}, display_name={display_name}"
            )

            # Ensure consistency with _load_folders_rm structure: [self, parent, ..., org]
            if not raw_ancestors or raw_ancestors[0] != name:
                ancestors = [name] + raw_ancestors
            else:
                ancestors = raw_ancestors

            f = Folder(
                name=name,
                display_name=display_name,
                ancestors=ancestors,
                organization=node,
            )
            node.folders[f.name] = f

    @staticmethod
    def _load_projects_asset(node: OrganizationNode) -> List[Project]:
        asset_client = asset_v1.AssetServiceClient()
        projects: List[Project] = []
        # Query Projects
        # Note: displayName is not in resource.data for Projects in Asset API query results
        # We'll use projectId as the display name fallback
        statement = "SELECT name, resource.data.projectNumber, resource.data.projectId, ancestors FROM `cloudresourcemanager_googleapis_com_Project`"
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
                return projects

            for row in response.query_result.rows:
                try:
                    row_dict = dict(row)
                    if "f" not in row_dict:
                        continue

                    f_list = row_dict["f"]
                    if len(f_list) < 4:
                        logger.warning(
                            f"Unexpected number of columns in Asset API project row: {len(f_list)}"
                        )
                        continue

                    # 0: name, 1: projectNumber, 2: projectId, 3: ancestors
                    name_col = f_list[0]
                    # num_col = f_list[1] # unused
                    id_col = f_list[2]
                    anc_col = f_list[3]

                    name_val = (
                        name_col.get("v") if isinstance(name_col, dict) else name_col
                    )
                    project_id = id_col.get("v") if isinstance(id_col, dict) else id_col
                    display_name = project_id  # Use projectId as displayName

                    ancestors_wrapper = (
                        anc_col.get("v") if isinstance(anc_col, dict) else anc_col
                    )
                    raw_ancestors_uncleaned = (
                        ancestors_wrapper if isinstance(ancestors_wrapper, list) else []
                    )

                    name = _clean_asset_name(str(name_val))
                    raw_ancestors = [
                        _clean_asset_name(
                            str(item.get("v") if isinstance(item, dict) else item)
                        )
                        for item in raw_ancestors_uncleaned
                    ]

                    logger.debug(
                        f"Parsed project from Asset API: project_id={project_id}, name={name}"
                    )

                except (IndexError, AttributeError, TypeError) as e:
                    logger.warning(f"Error parsing Asset API project row: {e}")
                    continue

                try:
                    # For projects, we want the first ancestor that is NOT the project itself.
                    # Typically raw_ancestors[0] is the parent, but if it's the project itself, pick [1].
                    if not raw_ancestors:
                        # Should not happen for a valid project
                        continue
                    elif raw_ancestors and raw_ancestors[0] == name:
                        parent_res = (
                            raw_ancestors[1]
                            if len(raw_ancestors) > 1
                            else node.organization.name
                        )
                    else:
                        parent_res = (
                            raw_ancestors[0]
                            if raw_ancestors
                            else node.organization.name
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
