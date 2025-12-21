import pytest
from gcpath.core import Folder, OrganizationNode, Hierarchy, Project
from google.cloud import resourcemanager_v3


def test_folder_path_simple():
    # Setup
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )
    org_node = OrganizationNode(organization=org_proto)

    # Hierarchy: Org -> F1 -> F2
    f1 = Folder(
        name="folders/1",
        display_name="f1",
        ancestors=["folders/1", "organizations/123"],
        organization=org_node,
    )
    f2 = Folder(
        name="folders/2",
        display_name="f2",
        ancestors=["folders/2", "folders/1", "organizations/123"],
        organization=org_node,
    )

    org_node.folders["folders/1"] = f1
    org_node.folders["folders/2"] = f2

    # Check paths
    assert f1.path == "//example.com/f1"
    assert f2.path == "//example.com/f1/f2"


def test_folder_is_path_match():
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )
    org_node = OrganizationNode(organization=org_proto)

    # Hierarchy: Org -> F1 -> F2
    f1 = Folder(
        name="folders/1",
        display_name="f1",
        ancestors=["folders/1", "organizations/123"],
        organization=org_node,
    )
    f2 = Folder(
        name="folders/2",
        display_name="f2",
        ancestors=["folders/2", "folders/1", "organizations/123"],
        organization=org_node,
    )

    org_node.folders["folders/1"] = f1
    org_node.folders["folders/2"] = f2

    # Test Matches
    assert f1.is_path_match(["f1"]) is True
    assert f2.is_path_match(["f1", "f2"]) is True

    # Test Non-Matches
    assert f1.is_path_match(["f2"]) is False
    assert f2.is_path_match(["f1"]) is False  # path too short
    assert f2.is_path_match(["f1", "f3"]) is False  # mismatch name


def test_get_resource_name():
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )
    org_node = OrganizationNode(organization=org_proto)

    f1 = Folder(
        name="folders/1",
        display_name="f1",
        ancestors=["folders/1", "organizations/123"],
        organization=org_node,
    )
    org_node.folders["folders/1"] = f1

    assert org_node.get_resource_name("/") == "organizations/123"
    assert org_node.get_resource_name("/f1") == "folders/1"

    with pytest.raises(ValueError, match="No folder found"):
        org_node.get_resource_name("/f2")


def test_hierarchy_get_resource_name_full_path():
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )
    org_node = OrganizationNode(organization=org_proto)
    f1 = Folder(
        name="folders/1",
        display_name="f1",
        ancestors=["folders/1", "organizations/123"],
        organization=org_node,
    )
    org_node.folders["folders/1"] = f1

    h = Hierarchy([org_node], [])

    assert h.get_resource_name("//example.com/f1") == "folders/1"
    assert h.get_resource_name("//example.com") == "organizations/123"


def test_hierarchy_get_path_by_resource_name():
    org_proto = resourcemanager_v3.Organization(
        name="organizations/123", display_name="example.com"
    )
    org_node = OrganizationNode(organization=org_proto)
    f1 = Folder(
        name="folders/1",
        display_name="f1",
        ancestors=["folders/1", "organizations/123"],
        organization=org_node,
    )
    org_node.folders["folders/1"] = f1

    p1 = Project(
        name="projects/p1",
        project_id="p1",
        display_name="Project 1",
        parent="folders/1",
        organization=org_node,
        folder=f1,
    )

    h = Hierarchy([org_node], [p1])

    assert h.get_path_by_resource_name("folders/1") == "//example.com/f1"
    assert h.get_path_by_resource_name("organizations/123") == "//example.com"
    assert h.get_path_by_resource_name("projects/p1") == "//example.com/f1/Project%201"


def test_organizationless_project_path():
    p1 = Project(
        name="projects/p1",
        project_id="p1",
        display_name="Project 1",
        parent="organizations/0",
        organization=None,
        folder=None,
    )
    assert p1.path == "//_/Project%201"

    h = Hierarchy([], [p1])
    assert h.get_resource_name("//_/Project%201") == "projects/p1"
