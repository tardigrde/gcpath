import pytest
from google.cloud import resourcemanager_v3

from gcpath.core import Folder, Hierarchy, OrganizationNode, Project


def make_test_hierarchy() -> Hierarchy:
    """Build a small test hierarchy shared across test modules."""
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )
    org_node = OrganizationNode(organization=org_proto)

    f1 = Folder(
        name="folders/1",
        display_name="f1",
        ancestors=["folders/1", "organizations/123"],
        organization=org_node,
        parent="organizations/123",
    )
    f11 = Folder(
        name="folders/11",
        display_name="f11",
        ancestors=["folders/11", "folders/1", "organizations/123"],
        organization=org_node,
        parent="folders/1",
    )

    org_node.folders["folders/1"] = f1
    org_node.folders["folders/11"] = f11

    p1 = Project(
        name="projects/p1",
        project_id="p1",
        display_name="Project 1",
        parent="folders/1",
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
