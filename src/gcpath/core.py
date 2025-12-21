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
            page_result = org_client.search_organizations(
                request=resourcemanager_v3.SearchOrganizationsRequest()
            )
            for org in page_result:
                if display_names and org.display_name not in display_names:
                    continue

                node = OrganizationNode(organization=org)
                org_nodes.append(node)

                if via_resource_manager:
                    cls._load_folders_rm(node)
                else:
                    cls._load_folders_asset(node)
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
                all_projects.extend(cls._load_projects_asset(org_node))

            # Asset API Query REQUIRES a parent (like organization).
            # To find organizationless projects, we always fallback to Resource Manager search_projects.
            existing_project_names = {p.name for p in all_projects}
            try:
                projects_pager = project_client.search_projects(
                    request=resourcemanager_v3.SearchProjectsRequest()
                )
                for p_proto in projects_pager:
                    if p_proto.name in existing_project_names:
                        continue

                    # A project is organizationless if it's not under an organization or folder.
                    is_orgless = not p_proto.parent.startswith(
                        "organizations/"
                    ) and not p_proto.parent.startswith("folders/")

                    if is_orgless:
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
            query=asset_v1.QueryAssetsRequest.Statement(statement=statement),
        )

        response = asset_client.query_assets(request=query_request)

        for page in response.pages:
            if not page.query_result or not page.query_result.rows:
                continue

            for row in page.query_result.rows:
                # The Asset API SQL results are returned in a Struct where the values
                # are in a list named 'f', similar to BigQuery JSON output.
                # 0: name, 1: displayName, 2: ancestors

                row_dict = dict(row.fields)
                if "f" not in row_dict:
                    continue

                try:
                    f_list = row_dict["f"].list_value.values
                    if len(f_list) < 3:
                        logger.warning(f"Unexpected number of columns in Asset API row: {len(f_list)}")
                        continue

                    name_val = f_list[0].struct_value.fields["v"].string_value
                    display_name = f_list[1].struct_value.fields["v"].string_value
                    ancestors_val = f_list[2].struct_value.fields["v"].list_value.values

                    if not name_val or not display_name:
                        continue

                    name = _clean_asset_name(name_val)
                    raw_ancestors = [_clean_asset_name(item.struct_value.fields["v"].string_value) for item in ancestors_val]

                    # Ensure consistency with _load_folders_rm structure: [self, parent, ..., org]
                    if not raw_ancestors or raw_ancestors[0] != name:
                        ancestors = [name] + raw_ancestors
                    else:
                        ancestors = raw_ancestors

                    f = Folder(
                        name=name,
                        display_name=display_name,
                        ancestors=ancestors,
                        organization=node
                    )
                    node.folders[f.name] = f
                except (AttributeError, KeyError, IndexError) as e:
                    logger.warning(f"Failed to parse Asset API row: {e}")
                    continue

    @staticmethod
    def _load_projects_asset(node: OrganizationNode) -> List[Project]:
        asset_client = asset_v1.AssetServiceClient()
        projects = []
        # Query Projects
        statement = "SELECT name, resource.data.projectNumber, resource.data.projectId, resource.data.displayName, ancestors FROM `cloudresourcemanager_googleapis_com_Project`"
        query_request = asset_v1.QueryAssetsRequest(
            parent=node.organization.name,
            query=asset_v1.QueryAssetsRequest.Statement(statement=statement),
        )

        try:
            response = asset_client.query_assets(request=query_request)
            for page in response.pages:
                if not page.query_result or not page.query_result.rows:
                    continue

                for row in page.query_result.rows:
                    row_dict = dict(row.fields)
                    if "f" not in row_dict:
                        continue

                    f_list = row_dict["f"].list_value.values
                    if len(f_list) < 5:
                        logger.warning(
                            f"Unexpected number of columns in Asset API project row: {len(f_list)}"
                        )
                        continue

                    # 0: name, 1: projectNumber, 2: projectId, 3: displayName, 4: ancestors
                    name_val = f_list[0].struct_value.fields["v"].string_value
                    project_id = f_list[2].struct_value.fields["v"].string_value
                    display_name = (
                        f_list[3].struct_value.fields["v"].string_value or project_id
                    )
                    ancestors_val = f_list[4].struct_value.fields["v"].list_value.values

                    name = _clean_asset_name(name_val)
                    raw_ancestors = [
                        _clean_asset_name(item.struct_value.fields["v"].string_value)
                        for item in ancestors_val
                    ]

                    # For projects, we want the first ancestor that is NOT the project itself.
                    # Typically raw_ancestors[0] is the parent, but if it's the project itself, pick [1].
                    if raw_ancestors and raw_ancestors[0] == name:
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
                        project_id=project_id,
                        display_name=display_name,
                        parent=parent_res,
                        organization=node,
                        folder=parent_folder,
                    )
                    projects.append(proj)
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
            raise PathParsingError("Path must contain an organization name (e.g., //example.com)")

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
            raise ResourceNotFoundError(f"Project path '{path}' not found in organizationless scope")

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
