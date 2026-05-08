import logging
import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from google.cloud import resourcemanager_v3  # type: ignore
from google.api_core import exceptions

from gcpath.loaders import (
    load_folders_rm,
    load_folders_asset,
    load_projects_asset,
    load_scope_folder,
    load_organizationless_projects,
    load_tags_asset,
    apply_tags,
)

# We use a logger but don't configure it here.
# Configuration should happen at the application entry point.
logger = logging.getLogger(__name__)

SYNTHETIC_ORG_NAME = "organizations/_folder_root"

# Resource name prefixes
_PREFIX_ORGS = "organizations/"
_PREFIX_FOLDERS = "folders/"
_PREFIX_PROJECTS = "projects/"


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


def aggregate_metadata(
    items: List[Union["Folder", "Project"]],
    attr: str,
    *,
    key_filter: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Aggregate label/tag occurrences across folders/projects.

    Pure data helper shared by the CLI and the MCP server. Returns a list of
    rows ``{"key", "value", "count", "examples"}`` and the number of items
    scanned.
    """
    counts: Dict[Tuple[str, str], int] = {}
    examples: Dict[Tuple[str, str], List[str]] = {}

    for obj in items:
        metadata: Dict[str, str] = getattr(obj, attr, {}) or {}
        for k, v in metadata.items():
            if key_filter is not None and k != key_filter:
                continue
            kv = (k, v)
            counts[kv] = counts.get(kv, 0) + 1
            ex_list = examples.setdefault(kv, [])
            if len(ex_list) < 3:
                ex_list.append(getattr(obj, "path", "") or obj.name)

    rows: List[Dict[str, Any]] = []
    for (k, v), c in counts.items():
        ex = examples.get((k, v), [])
        suffix = ""
        if c > len(ex):
            suffix = f" (+{c - len(ex)} more)"
        rows.append({
            "key": k,
            "value": v,
            "count": c,
            "examples": ", ".join(ex) + suffix,
        })
    rows.sort(key=lambda r: (-r["count"], r["key"], r["value"]))
    return rows, len(items)


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
    labels: Dict[str, str] = field(default_factory=dict)
    tags: Dict[str, str] = field(default_factory=dict)

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
    labels: Dict[str, str] = field(default_factory=dict)
    tags: Dict[str, str] = field(default_factory=dict)

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
        include_labels: bool = False,
        include_tags: bool = False,
    ) -> "Hierarchy":
        """Load the GCP resource hierarchy from GCP APIs.

        Args:
            display_names: Filter to only load these organization display names.
            via_resource_manager: If True, use Resource Manager API. If False, use Asset API.
            scope_resource: If provided, only load direct children of this resource
                           (e.g., 'organizations/123' or 'folders/456').
                           If None, defaults to loading from organization level.
            recursive: If True, load all descendants. If False, only load direct children.
                      Only applies when via_resource_manager=False (Asset API mode).
            include_labels: If True, fetch GCP labels for folders and projects.
            include_tags: If True, fetch GCP resource tag bindings.
        """
        logger.debug("Loading hierarchy from GCP API.")
        org_client = resourcemanager_v3.OrganizationsClient()
        project_client = resourcemanager_v3.ProjectsClient()

        # Load Organizations
        org_nodes = cls._load_organizations(
            org_client,
            display_names,
            via_resource_manager,
            scope_resource,
            recursive,
            include_labels=include_labels,
        )

        # Fallback: if no orgs found and scope is a folder, try folder-scoped loading
        if (
            not org_nodes
            and scope_resource
            and scope_resource.startswith(_PREFIX_FOLDERS)
        ):
            logger.debug(
                f"No organizations found, falling back to folder-scoped loading for {scope_resource}"
            )
            return cls._load_from_folder_scope(
                scope_resource,
                via_resource_manager,
                recursive,
                include_labels=include_labels,
                include_tags=include_tags,
            )

        # Load Projects
        all_projects = cls._load_all_projects(
            project_client,
            org_nodes,
            via_resource_manager,
            scope_resource,
            recursive,
            include_labels=include_labels,
        )

        hierarchy = cls(organizations=org_nodes, projects=all_projects)

        # Load tags if requested (separate Asset API query)
        if include_tags and not via_resource_manager:
            tag_scopes = (
                [scope_resource]
                if scope_resource
                else [org_node.organization.name for org_node in org_nodes]
            )
            for tag_scope in tag_scopes:
                tags_map = load_tags_asset(tag_scope)
                apply_tags(hierarchy, tags_map)

        return hierarchy

    @classmethod
    def _search_organizations(cls, org_client) -> List[resourcemanager_v3.Organization]:
        """Search for accessible organizations."""
        try:
            page_result = org_client.search_organizations(
                request=resourcemanager_v3.SearchOrganizationsRequest()
            )
            return list(page_result)
        except exceptions.PermissionDenied:
            logger.warning("Permission denied searching organizations")
        except Exception as e:
            logger.error(f"Error searching organizations: {e}")
        return []

    @classmethod
    def _load_organizations(
        cls,
        org_client,
        display_names: Optional[List[str]],
        via_resource_manager: bool,
        scope_resource: Optional[str],
        recursive: bool,
        include_labels: bool = False,
    ) -> List[OrganizationNode]:
        """Load organizations and their folders."""
        display_names_set = set(display_names) if display_names else None
        org_nodes = []

        for org in cls._search_organizations(org_client):
            if display_names_set and org.display_name not in display_names_set:
                logger.debug(
                    f"Skipping organization '{org.display_name}' (not in filter)"
                )
                continue

            logger.debug(
                f"Processing organization: {org.display_name} (name: {org.name})"
            )
            node = OrganizationNode(organization=org)
            org_nodes.append(node)

            cls._load_folders_for_org(
                node,
                via_resource_manager,
                scope_resource,
                recursive,
                include_labels=include_labels,
            )
            logger.debug(
                f"Loaded {len(node.folders)} folders for org {node.organization.display_name}"
            )

        return org_nodes

    @classmethod
    def _load_from_folder_scope(
        cls,
        scope_resource: str,
        via_resource_manager: bool,
        recursive: bool,
        include_labels: bool = False,
        include_tags: bool = False,
    ) -> "Hierarchy":
        """Load hierarchy rooted at a folder when org access is unavailable.

        Creates a synthetic OrganizationNode and loads descendants of the folder.
        """
        folders_client = resourcemanager_v3.FoldersClient()
        org_client = resourcemanager_v3.OrganizationsClient()

        # Get the entrypoint folder info
        try:
            folder_proto = folders_client.get_folder(name=scope_resource)
        except Exception as e:
            logger.error(f"Could not access folder {scope_resource}: {e}")
            raise

        # Try to resolve the real org by traversing parents upward
        org_name = None
        org_display_name = None
        current = folder_proto.parent
        while current:
            if current.startswith(_PREFIX_ORGS):
                try:
                    org_proto = org_client.get_organization(name=current)
                    org_name = org_proto.name
                    org_display_name = org_proto.display_name
                except exceptions.PermissionDenied:
                    logger.debug(f"Permission denied accessing org {current}")
                break
            elif current.startswith(_PREFIX_FOLDERS):
                try:
                    parent_proto = folders_client.get_folder(name=current)
                    current = parent_proto.parent
                except exceptions.PermissionDenied:
                    logger.debug(f"Permission denied traversing to {current}")
                    break
                except Exception:
                    break
            else:
                break

        # Build synthetic OrganizationNode
        if org_name and org_display_name:
            synth_org = resourcemanager_v3.Organization(
                name=org_name, display_name=org_display_name
            )
        else:
            synth_org = resourcemanager_v3.Organization(
                name=SYNTHETIC_ORG_NAME,
                display_name=folder_proto.display_name,
            )

        node = OrganizationNode(organization=synth_org)

        # Add entrypoint folder with ancestors=[itself] (no org at end)
        entrypoint_folder = Folder(
            name=folder_proto.name,
            display_name=folder_proto.display_name,
            ancestors=[scope_resource],
            organization=node,
            parent=folder_proto.parent,
        )
        node.folders[scope_resource] = entrypoint_folder

        # Load child folders and projects
        if via_resource_manager:
            load_folders_rm(node, scope_resource)
        else:
            cls._load_folders_for_org(
                node,
                via_resource_manager=False,
                scope_resource=scope_resource,
                recursive=recursive,
                query_parent=scope_resource,
                root_ancestor=scope_resource,
                include_labels=include_labels,
            )

        # Load projects
        all_projects: List[Project] = []
        if via_resource_manager:
            # RM path: search_projects returns all accessible, filter by parent
            project_client = resourcemanager_v3.ProjectsClient()
            all_projects = cls._load_projects_rm(
                project_client,
                [node],
                include_labels=include_labels,
            )
        else:
            all_projects = cls._load_projects_asset_all_orgs(
                [node],
                scope_resource=scope_resource,
                recursive=recursive,
                query_parent=scope_resource,
                include_labels=include_labels,
            )

        hierarchy = cls(organizations=[node], projects=all_projects)

        if include_tags and not via_resource_manager:
            tags_map = load_tags_asset(scope_resource)
            apply_tags(hierarchy, tags_map)

        return hierarchy

    @classmethod
    def _load_folders_for_org(
        cls,
        node: OrganizationNode,
        via_resource_manager: bool,
        scope_resource: Optional[str],
        recursive: bool,
        query_parent: Optional[str] = None,
        root_ancestor: Optional[str] = None,
        include_labels: bool = False,
    ):
        """Load folders for a single organization."""
        if via_resource_manager:
            root_parent = query_parent or node.organization.name
            load_folders_rm(node, root_parent)
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
                query_parent=query_parent,
                root_ancestor=root_ancestor,
                include_labels=include_labels,
            )

            # Load scope folder separately if needed (for recursive scoped loads)
            if scope_resource and scope_resource.startswith("folders/") and recursive:
                load_scope_folder(node, scope_resource, root_ancestor=root_ancestor)

    @classmethod
    def _load_all_projects(
        cls,
        project_client,
        org_nodes: List[OrganizationNode],
        via_resource_manager: bool,
        scope_resource: Optional[str],
        recursive: bool,
        include_labels: bool = False,
    ) -> List[Project]:
        """Load all projects across all organizations."""
        all_projects = []

        if via_resource_manager:
            all_projects = cls._load_projects_rm(
                project_client,
                org_nodes,
                include_labels=include_labels,
            )
        else:
            # Asset API mode
            all_projects = cls._load_projects_asset_all_orgs(
                org_nodes,
                scope_resource,
                recursive,
                include_labels=include_labels,
            )

            # Load organizationless projects
            existing_project_names = {p.name for p in all_projects}
            orgless_projects = load_organizationless_projects(existing_project_names)
            all_projects.extend(orgless_projects)

        return all_projects

    @classmethod
    def _load_projects_rm(
        cls,
        project_client,
        org_nodes: List[OrganizationNode],
        include_labels: bool = False,
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

                if p_proto.parent.startswith(_PREFIX_ORGS):
                    parent_org = next(
                        (o for o in org_nodes if o.organization.name == p_proto.parent),
                        None,
                    )
                elif p_proto.parent.startswith(_PREFIX_FOLDERS):
                    for o in org_nodes:
                        if p_proto.parent in o.folders:
                            parent_folder = o.folders[p_proto.parent]
                            parent_org = o
                            break

                labels = (
                    dict(p_proto.labels) if include_labels and p_proto.labels else {}
                )

                proj = Project(
                    name=p_proto.name,
                    project_id=p_proto.project_id,
                    display_name=p_proto.display_name or p_proto.project_id,
                    parent=p_proto.parent,
                    organization=parent_org,
                    folder=parent_folder,
                    labels=labels,
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
        query_parent: Optional[str] = None,
        include_labels: bool = False,
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
                query_parent=query_parent,
                include_labels=include_labels,
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

    def _find_orgless_project(self, path: str) -> str:
        """Find and return the resource name for an organizationless project."""
        for proj in self.projects:
            if not proj.organization and proj.path == path:
                return proj.name
        raise ResourceNotFoundError(
            f"Project path '{path}' not found in organizationless scope"
        )

    def get_resource_name(self, path: str) -> str:
        org_name, resource_path = self._parse_path(path)

        # Reserved for organizationless scope
        if org_name == "_":
            return self._find_orgless_project(path)

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
        if resource_name.startswith(_PREFIX_ORGS):
            org = self._orgs_by_name.get(resource_name)
            if org:
                return "//" + path_escape(org.organization.display_name)
            raise ResourceNotFoundError(f"Organization '{resource_name}' not found")

        if resource_name.startswith(_PREFIX_FOLDERS):
            folder = self._folders_by_name.get(resource_name)
            if folder:
                return folder.path
            raise ResourceNotFoundError(f"Folder '{resource_name}' not found")

        if resource_name.startswith(_PREFIX_PROJECTS):
            proj = self._projects_by_name.get(resource_name)
            if proj:
                return proj.path
            raise ResourceNotFoundError(f"Project '{resource_name}' not found")

        raise ResourceNotFoundError(f"Unsupported resource name '{resource_name}'")

    @staticmethod
    def _get_resource_info(
        name: str,
        folders_client,
        projects_client,
        org_client,
    ) -> tuple[str, Optional[str]]:
        """Fetch display name and parent for a resource.

        Returns (display_name, parent_name_or_None).
        Raises ResourceNotFoundError on permission issues.
        """
        if name.startswith(_PREFIX_PROJECTS):
            try:
                p = projects_client.get_project(name=name)
                logger.debug(f"GCP API: get_project({name}) returned")
                return (p.display_name or p.project_id), p.parent
            except exceptions.PermissionDenied:
                raise ResourceNotFoundError(
                    f"Permission denied accessing project {name}"
                )

        if name.startswith(_PREFIX_FOLDERS):
            try:
                f = folders_client.get_folder(name=name)
                logger.debug(f"GCP API: get_folder({name}) returned")
                return f.display_name, f.parent
            except exceptions.PermissionDenied:
                raise ResourceNotFoundError(
                    f"Permission denied accessing folder {name}"
                )

        if name.startswith(_PREFIX_ORGS):
            try:
                o = org_client.get_organization(name=name)
                logger.debug(f"GCP API: get_organization({name}) returned")
                return o.display_name, None
            except exceptions.PermissionDenied:
                return f"_unknown_org_({name})", None

        raise ResourceNotFoundError(f"Unknown resource type: {name}")

    @staticmethod
    def _resolve_org_directly(resource_name: str) -> Optional[str]:
        """Resolve an organization resource name to its path. Returns None for non-org resources."""
        if not resource_name.startswith(_PREFIX_ORGS):
            return None
        try:
            org_client = resourcemanager_v3.OrganizationsClient()
            org = org_client.get_organization(name=resource_name)
            logger.debug(f"GCP API: get_organization({resource_name}) returned")
            return "//" + path_escape(org.display_name)
        except exceptions.PermissionDenied:
            logger.warning(f"Permission denied accessing organization {resource_name}")
            return f"//_unknown_org_({resource_name})"

    @staticmethod
    def resolve_ancestry(resource_name: str) -> str:
        """
        Resolves the path for a given resource name by traversing up the hierarchy.
        This avoids loading the entire hierarchy.
        """
        # Handle organization directly
        org_path = Hierarchy._resolve_org_directly(resource_name)
        if org_path is not None:
            return org_path

        # Lazy client initialization
        folders_client = resourcemanager_v3.FoldersClient()
        projects_client = resourcemanager_v3.ProjectsClient()
        org_client = resourcemanager_v3.OrganizationsClient()

        segments: List[str] = []
        current = resource_name

        while current:
            try:
                display_name, parent = Hierarchy._get_resource_info(
                    current,
                    folders_client,
                    projects_client,
                    org_client,
                )
            except exceptions.NotFound:
                raise ResourceNotFoundError(f"Resource not found: {current}")

            if current.startswith(_PREFIX_ORGS):
                prefix = "//" + path_escape(display_name)
                return prefix + ("/" + "/".join(segments) if segments else "")

            segments.insert(0, path_escape(display_name))

            if not parent:
                return "//_/" + "/".join(segments)

            current = parent

        return "//?/" + "/".join(segments)

    @staticmethod
    def _fetch_chain_link(
        name: str,
        folders_client,
        projects_client,
        org_client,
    ) -> tuple[str, str, str, Optional[str]]:
        """Fetch a single link in the ancestry chain.

        Returns (resource_name, display_name, type, parent_or_None).
        parent is None when the chain should stop (org reached or no parent).
        """
        if name.startswith(_PREFIX_ORGS):
            try:
                org = org_client.get_organization(name=name)
                return (name, org.display_name, "organization", None)
            except exceptions.PermissionDenied:
                return (name, name, "organization", None)

        if name.startswith(_PREFIX_FOLDERS):
            try:
                f = folders_client.get_folder(name=name)
                return (name, f.display_name, "folder", f.parent)
            except exceptions.PermissionDenied:
                # Graceful fallback matching organization handling
                return (name, name, "folder", None)
            except exceptions.NotFound:
                raise ResourceNotFoundError(f"Resource not found: {name}")

        if name.startswith(_PREFIX_PROJECTS):
            try:
                p = projects_client.get_project(name=name)
                display_name = p.display_name or p.project_id
                return (name, display_name, "project", p.parent or None)
            except exceptions.PermissionDenied:
                # Graceful fallback matching organization handling
                return (name, name, "project", None)
            except exceptions.NotFound:
                raise ResourceNotFoundError(f"Resource not found: {name}")

        raise ResourceNotFoundError(f"Unknown resource type: {name}")

    def summary(self, top_n: int = 5, deepest_n: int = 3) -> Dict[str, Any]:
        """Build an agent-friendly snapshot of the loaded hierarchy.

        Returns counts, depth, top label/tag keys, per-org project counts, and
        a few of the deepest paths. All values are JSON-serializable.

        Depth convention: an org is depth 0; each folder/project layer adds 1.
        For a Folder, ``ancestors`` includes the folder itself plus its
        ancestors up to the org, so depth == ``len(ancestors) - 1``. A Project
        directly under a folder is one deeper than that folder, which is
        equivalent to ``len(folder.ancestors)``. A Project directly under an
        org has depth 1.
        """
        real_orgs = [
            o for o in self.organizations
            if o.organization.name != SYNTHETIC_ORG_NAME
        ]

        def _project_depth(p: Project) -> int:
            if p.folder:
                return len(p.folder.ancestors)
            if p.organization:
                return 1
            return 0

        max_depth = 0
        for f in self.folders:
            depth = max(0, len(f.ancestors) - 1)
            if depth > max_depth:
                max_depth = depth
        for p in self.projects:
            pd = _project_depth(p)
            if pd > max_depth:
                max_depth = pd

        label_counter, tag_counter = self._summary_metadata_counters()
        top_label_keys = [
            {"key": k, "count": c} for k, c in label_counter.most_common(top_n)
        ]
        top_tag_keys = [
            {"key": k, "count": c} for k, c in tag_counter.most_common(top_n)
        ]

        org_rows = self._summary_org_rows(real_orgs)

        candidate_paths: List[tuple[int, str]] = []
        for f in self.folders:
            candidate_paths.append((max(0, len(f.ancestors) - 1), f.path))
        for p in self.projects:
            candidate_paths.append((_project_depth(p), p.path))
        candidate_paths.sort(key=lambda t: (-t[0], t[1]))
        seen: set = set()
        deepest_paths: List[str] = []
        for _depth, path in candidate_paths:
            if path in seen:
                continue
            seen.add(path)
            deepest_paths.append(path)
            if len(deepest_paths) >= deepest_n:
                break

        return {
            "org_count": len(real_orgs),
            "folder_count": len(self.folders),
            "project_count": len(self.projects),
            "max_depth": max_depth,
            "top_label_keys": top_label_keys,
            "top_tag_keys": top_tag_keys,
            "orgs": org_rows,
            "deepest_paths": deepest_paths,
        }

    def _summary_metadata_counters(self) -> tuple[Counter, Counter]:
        label_counter: Counter = Counter()
        tag_counter: Counter = Counter()
        for resource in list(self.folders) + list(self.projects):
            for k in (getattr(resource, "labels", None) or {}).keys():
                label_counter[k] += 1
            for k in (getattr(resource, "tags", None) or {}).keys():
                tag_counter[k] += 1
        return label_counter, tag_counter

    def _summary_org_rows(
        self, real_orgs: List["OrganizationNode"]
    ) -> List[Dict[str, Any]]:
        return [
            {
                "display_name": org.organization.display_name,
                "resource_name": org.organization.name,
                "folders": len(org.folders),
                "projects": sum(
                    1 for p in self.projects if p.organization is org
                ),
            }
            for org in real_orgs
        ]

    @staticmethod
    def resolve_ancestry_chain(resource_name: str) -> List[tuple[str, str, str]]:
        """Resolve full ancestry chain for a resource, returning structured data.

        Returns list of (resource_name, display_name, type) tuples from root to leaf.
        """
        folders_client = resourcemanager_v3.FoldersClient()
        projects_client = resourcemanager_v3.ProjectsClient()
        org_client = resourcemanager_v3.OrganizationsClient()

        chain: List[tuple[str, str, str]] = []
        current: Optional[str] = resource_name

        while current:
            name, display_name, rtype, parent = Hierarchy._fetch_chain_link(
                current, folders_client, projects_client, org_client
            )
            chain.append((name, display_name, rtype))
            current = parent

        chain.reverse()
        return chain
