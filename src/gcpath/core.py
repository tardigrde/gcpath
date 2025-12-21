import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse

from google.cloud import asset_v1  # type: ignore
from google.cloud import resourcemanager_v3  # type: ignore
from google.api_core import exceptions

# Configure logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)


def path_escape(s: str) -> str:
    """Escapes path components."""
    import urllib.parse
    return urllib.parse.quote(s, safe="")

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
            raise ValueError(f"No folder found with path '{path}' in '{self.organization.display_name}'")
        if len(matches) > 1:
            raise ValueError(f"Multiple folders found with path '{path}' in '{self.organization.display_name}'")
        
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

    @classmethod
    def load(
        cls,
        ctx_ignored=None,
        display_names: Optional[List[str]] = None,
        via_resource_manager: bool = True
    ) -> "Hierarchy":
        org_client = resourcemanager_v3.OrganizationsClient()
        project_client = resourcemanager_v3.ProjectsClient()
        
        # Load Orgs
        org_nodes = []
        try:
            page_result = org_client.search_organizations(request=resourcemanager_v3.SearchOrganizationsRequest())
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
                projects_pager = project_client.search_projects(request=resourcemanager_v3.SearchProjectsRequest())
                for p_proto in projects_pager:
                    # Find parent
                    parent_org = None
                    parent_folder = None
                    
                    if p_proto.parent.startswith("organizations/"):
                        parent_org = next((o for o in org_nodes if o.organization.name == p_proto.parent), None)
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
                        folder=parent_folder
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
            # So for organizationless projects, we have to use Resource Manager search_projects or similar.
            if not org_nodes:
                 try:
                     projects_pager = project_client.search_projects(request=resourcemanager_v3.SearchProjectsRequest())
                     for p_proto in projects_pager:
                         proj = Project(
                             name=p_proto.name,
                             project_id=p_proto.project_id,
                             display_name=p_proto.display_name or p_proto.project_id,
                             parent=p_proto.parent,
                             organization=None,
                             folder=None
                         )
                         all_projects.append(proj)
                 except Exception as e:
                     logger.error(f"Error searching projects: {e}")

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
                        organization=node
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
            query=asset_v1.QueryAssetsRequest.Statement(statement=statement)
        )
        
        response = asset_client.query_assets(request=query_request)
        
        for page in response.pages:
             if not page.query_result or not page.query_result.rows:
                 continue
                 
             for row in page.query_result.rows:
                 row_dict = dict(row.fields)
                 
                 if "f" in row_dict:
                      f_list = row_dict["f"].list_value.values
                      if len(f_list) != 3:
                          logger.warning("Unexpected number of columns in Asset API row")
                          continue
                      
                      name_val = f_list[0].struct_value.fields["v"].string_value
                      display_name_val = f_list[1].struct_value.fields["v"].string_value
                      ancestors_val = f_list[2].struct_value.fields["v"].list_value.values
                      
                      if name_val.startswith("//cloudresourcemanager.googleapis.com/"):
                           name = name_val[len("//cloudresourcemanager.googleapis.com/"):]
                      else:
                           name = name_val
                           
                      ancestors = [item.struct_value.fields["v"].string_value for item in ancestors_val]
                      
                      f = Folder(
                          name=name,
                          display_name=display_name_val,
                          ancestors=ancestors,
                          organization=node
                      )
                      node.folders[f.name] = f
                 else:
                      pass

    @staticmethod
    def _load_projects_asset(node: OrganizationNode) -> List[Project]:
        asset_client = asset_v1.AssetServiceClient()
        projects = []
        # Query Projects
        statement = "SELECT name, resource.data.projectNumber, resource.data.projectId, resource.data.displayName, ancestors FROM `cloudresourcemanager_googleapis_com_Project`"
        query_request = asset_v1.QueryAssetsRequest(
            parent=node.organization.name,
            query=asset_v1.QueryAssetsRequest.Statement(statement=statement)
        )
        
        try:
            response = asset_client.query_assets(request=query_request)
            for page in response.pages:
                if not page.query_result or not page.query_result.rows:
                    continue
                    
                for row in page.query_result.rows:
                    row_dict = dict(row.fields)
                    if "f" in row_dict:
                        f_list = row_dict["f"].list_value.values
                        
                        name_val = f_list[0].struct_value.fields["v"].string_value
                        project_id_val = f_list[2].struct_value.fields["v"].string_value
                        display_name_val = f_list[3].struct_value.fields["v"].string_value or project_id_val
                        ancestors_val = f_list[4].struct_value.fields["v"].list_value.values
                        
                        if name_val.startswith("//cloudresourcemanager.googleapis.com/"):
                            name = name_val[len("//cloudresourcemanager.googleapis.com/"):]
                        else:
                            name = name_val
                            
                        ancestors = [item.struct_value.fields["v"].string_value for item in ancestors_val]
                        
                        parent_folder = None
                        if len(ancestors) > 1:
                            parent_res = ancestors[1]
                            if parent_res.startswith("folders/"):
                                parent_folder = node.folders.get(parent_res)

                        proj = Project(
                            name=name,
                            project_id=project_id_val,
                            display_name=display_name_val,
                            parent=ancestors[1] if len(ancestors) > 1 else node.organization.name,
                            organization=node,
                            folder=parent_folder
                        )
                        projects.append(proj)
        except Exception as e:
            logger.error(f"Error querying projects via Asset API: {e}")
            
        return projects

    def get_resource_name(self, path: str) -> str:
        # Helper to find org from path
        # //org_name/...
        if not path.startswith("//"):
             raise ValueError("Path must start with //")
        
        parsed = urlparse(path, scheme="")
        org_name = parsed.netloc
        
        if org_name == "_":
            # Organizationless projects
            import urllib.parse
            project_path = urllib.parse.unquote(parsed.path.strip("/"))
            for proj in self.projects:
                if not proj.organization and proj.display_name == project_path:
                    return proj.name
            raise ValueError(f"Project '{project_path}' not found in organizationless scope")

        org_node = next((o for o in self.organizations if o.organization.display_name == org_name), None)
        if not org_node:
            raise ValueError(f"Organization '{org_name}' not found")
            
        # Try finding a project first
        project_path = parsed.path.strip("/")
        try:
            return org_node.get_resource_name(parsed.path)
        except ValueError:
            # Maybe it's a project at the end of the path?
            for proj in self.projects:
                if proj.organization == org_node and proj.path == path:
                    return proj.name
            raise

    def get_path_by_resource_name(self, resource_name: str) -> str:
        if resource_name.startswith("organizations/"):
            for org in self.organizations:
                if org.organization.name == resource_name:
                    return "//" + path_escape(org.organization.display_name)
            raise ValueError(f"Organization '{resource_name}' not found")
        
        if resource_name.startswith("folders/"):
            for org in self.organizations:
                folder = org.folders.get(resource_name)
                if folder:
                    return folder.path
            raise ValueError(f"Folder '{resource_name}' not found")

        if resource_name.startswith("projects/"):
            for proj in self.projects:
                if proj.name == resource_name:
                    return proj.path
            raise ValueError(f"Project '{resource_name}' not found")
        
        raise ValueError(f"Unsupported resource name '{resource_name}'")
