import pytest
from google.cloud import resourcemanager_v3

from gcpath.core import Folder, Hierarchy, OrganizationNode, Project

_ORG_NAME = "organizations/123"
_FOLDER_1 = "folders/1"
_FOLDER_11 = "folders/11"


def make_test_hierarchy() -> Hierarchy:
    """Build a small test hierarchy shared across test modules."""
    org_proto = resourcemanager_v3.Organization(
        name=_ORG_NAME, display_name="example.com"
    )
    org_node = OrganizationNode(organization=org_proto)

    f1 = Folder(
        name=_FOLDER_1,
        display_name="f1",
        ancestors=[_FOLDER_1, _ORG_NAME],
        organization=org_node,
        parent=_ORG_NAME,
    )
    f11 = Folder(
        name=_FOLDER_11,
        display_name="f11",
        ancestors=[_FOLDER_11, _FOLDER_1, _ORG_NAME],
        organization=org_node,
        parent=_FOLDER_1,
    )

    org_node.folders[_FOLDER_1] = f1
    org_node.folders[_FOLDER_11] = f11

    p1 = Project(
        name="projects/p1",
        project_id="p1",
        display_name="Project 1",
        parent=_FOLDER_1,
        organization=org_node,
        folder=f1,
    )

    orgless_p = Project(
        name="projects/standalone",
        project_id="standalone",
        display_name="Standalone",
        parent="organizations/0",
        organization=None,
        folder=None,
    )

    return Hierarchy([org_node], [p1, orgless_p])


@pytest.fixture
def mock_hierarchy():
    return make_test_hierarchy()
