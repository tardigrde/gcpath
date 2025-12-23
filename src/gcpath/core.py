import logging
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from google.cloud import resourcemanager_v3  # type: ignore
from google.api_core import exceptions

from gcpath.loaders import (
    load_folders_rm,
    load_folders_asset,
    load_projects_asset,
    load_scope_folder,
    load_organizationless_projects,
)

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
    parent: str = (
        ""  # Parent resource name (e.g., 'organizations/123' or 'folders/456')
    )

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
        display_names: Optional[List[str]] = None,
        via_resource_manager: bool = True,
        scope_resource: Optional[str] = None,
        recursive: bool = False,
    ) -> "Hierarchy":
        """Load the GCP resource hierarchy.

        Args:
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

        # Load Organizations
        org_nodes = cls._load_organizations(
            org_client, display_names, via_resource_manager, scope_resource, recursive
        )

        # Load Projects
        all_projects = cls._load_all_projects(
            project_client, org_nodes, via_resource_manager, scope_resource, recursive
        )

        return cls(organizations=org_nodes, projects=all_projects)

    @classmethod
    def _load_organizations(
        cls,
        org_client,
        display_names: Optional[List[str]],
        via_resource_manager: bool,
        scope_resource: Optional[str],
        recursive: bool,
    ) -> List[OrganizationNode]:
        """Load organizations and their folders."""
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

                # Load folders for this organization
                cls._load_folders_for_org(
                    node, via_resource_manager, scope_resource, recursive
                )

                logger.debug(
                    f"Loaded {len(node.folders)} folders for org {node.organization.display_name}"
                )

        except exceptions.PermissionDenied:
            logger.warning("Permission denied searching organizations")
        except Exception as e:
            logger.error(f"Error searching organizations: {e}")

        return org_nodes

    @classmethod
    def _load_folders_for_org(
        cls,
        node: OrganizationNode,
        via_resource_manager: bool,
        scope_resource: Optional[str],
        recursive: bool,
    ):
        """Load folders for a single organization."""
        if via_resource_manager:
            load_folders_rm(node, node.organization.name)
        else:
            # Determine filters for Asset API based on scope_resource and recursive
            folder_parent_filter = None
            folder_ancestors_filter = None

            if scope_resource:
                if recursive:
                    folder_ancestors_filter = scope_resource
                else:
                    folder_parent_filter = scope_resource
            elif not recursive:
                folder_parent_filter = node.organization.name

            load_folders_asset(
                node,
                parent_filter=folder_parent_filter,
                ancestors_filter=folder_ancestors_filter,
            )

            # Load scope folder separately if needed (for recursive scoped loads)
            if scope_resource and scope_resource.startswith("folders/") and recursive:
                load_scope_folder(node, scope_resource)

    @classmethod
    def _load_all_projects(
        cls,
        project_client,
        org_nodes: List[OrganizationNode],
        via_resource_manager: bool,
        scope_resource: Optional[str],
        recursive: bool,
    ) -> List[Project]:
        """Load all projects across all organizations."""
        all_projects = []

        if via_resource_manager:
            all_projects = cls._load_projects_rm(project_client, org_nodes)
        else:
            # Asset API mode
            all_projects = cls._load_projects_asset_all_orgs(
                org_nodes, scope_resource, recursive
            )

            # Load organizationless projects
            existing_project_names = {p.name for p in all_projects}
            orgless_projects = load_organizationless_projects(existing_project_names)
            all_projects.extend(orgless_projects)

        return all_projects

    @classmethod
    def _load_projects_rm(
        cls, project_client, org_nodes: List[OrganizationNode]
    ) -> List[Project]:
        """Load projects using Resource Manager API."""
        all_projects = []
        try:
            projects_pager = project_client.search_projects(
                request=resourcemanager_v3.SearchProjectsRequest()
            )
            logger.debug("GCP API: search_projects() returned successfully")

            for p_proto in projects_pager:
                # Find parent organization and folder
                parent_org = None
                parent_folder = None

                if p_proto.parent.startswith("organizations/"):
                    parent_org = next(
                        (o for o in org_nodes if o.organization.name == p_proto.parent),
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

        return all_projects

    @classmethod
    def _load_projects_asset_all_orgs(
        cls,
        org_nodes: List[OrganizationNode],
        scope_resource: Optional[str],
        recursive: bool,
    ) -> List[Project]:
        """Load projects for all organizations using Asset API."""
        all_projects = []

        for org_node in org_nodes:
            # Determine filters for projects
            project_parent_filter = None
            project_ancestors_filter = None

            if scope_resource:
                if recursive:
                    project_ancestors_filter = scope_resource
                else:
                    project_parent_filter = scope_resource
            elif not recursive:
                project_parent_filter = org_node.organization.name

            org_projects = load_projects_asset(
                org_node,
                parent_filter=project_parent_filter,
                ancestors_filter=project_ancestors_filter,
            )
            all_projects.extend(org_projects)

        return all_projects

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
