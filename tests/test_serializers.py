import json

import yaml

from conftest import make_test_hierarchy
from gcpath.serializers import (
    dump_json,
    dump_yaml,
    resource_type,
    serialize_ls,
    serialize_name_results,
    serialize_path_results,
    serialize_resource,
    serialize_tree,
    serialize_tree_node,
)


def _h():
    """Return hierarchy and extract commonly-used objects."""
    hierarchy = make_test_hierarchy()
    org_node = hierarchy.organizations[0]
    f1 = org_node.folders["folders/1"]
    p1 = next(p for p in hierarchy.projects if p.name == "projects/p1")
    orgless_p = next(p for p in hierarchy.projects if p.name == "projects/standalone")
    return hierarchy, org_node, f1, p1, orgless_p


class TestResourceType:
    def test_organization(self):
        _, org_node, *_ = _h()
        assert resource_type(org_node) == "organization"

    def test_folder(self):
        _, _, f1, *_ = _h()
        assert resource_type(f1) == "folder"

    def test_project(self):
        _, _, _, p1, _ = _h()
        assert resource_type(p1) == "project"


class TestSerializeResource:
    def test_organization(self):
        _, org_node, *_ = _h()
        d = serialize_resource("//example.com", org_node)
        assert d["path"] == "//example.com"
        assert d["type"] == "organization"
        assert d["resource_name"] == "organizations/123"
        assert d["display_name"] == "example.com"

    def test_folder(self):
        _, _, f1, *_ = _h()
        d = serialize_resource("//example.com/f1", f1)
        assert d["type"] == "folder"
        assert d["resource_name"] == "folders/1"
        assert d["display_name"] == "f1"

    def test_project(self):
        _, _, _, p1, _ = _h()
        d = serialize_resource("//example.com/f1/Project 1", p1)
        assert d["type"] == "project"
        assert d["resource_name"] == "projects/p1"
        assert d["project_id"] == "p1"


class TestSerializeLs:
    def test_basic(self):
        _, _, f1, p1, _ = _h()
        items = [("//example.com/f1", f1), ("//example.com/f1/Project 1", p1)]
        result = serialize_ls(items)
        assert len(result) == 2
        assert result[0]["type"] == "folder"
        assert result[1]["type"] == "project"

    def test_empty(self):
        assert serialize_ls([]) == []


class TestSerializeTreeNode:
    def test_basic_tree(self):
        _, org_node, _, p1, _ = _h()
        projects_by_parent = {"folders/1": [p1]}
        d = serialize_tree_node(org_node, projects_by_parent)
        assert d["type"] == "organization"
        assert d["display_name"] == "example.com"
        assert len(d["children"]) == 1  # f1
        f1_node = d["children"][0]
        assert f1_node["type"] == "folder"
        assert f1_node["display_name"] == "f1"
        # f1 has children: f11 and p1
        assert len(f1_node["children"]) == 2

    def test_depth_limit(self):
        _, org_node, _, p1, _ = _h()
        projects_by_parent = {"folders/1": [p1]}
        d = serialize_tree_node(org_node, projects_by_parent, level=1)
        assert d["type"] == "organization"
        # level=1 means we include org's direct children but not deeper
        f1_node = d["children"][0]
        assert f1_node["children"] == []  # depth limited


class TestSerializeTree:
    def test_with_orgless(self):
        _, org_node, _, p1, orgless_p = _h()
        projects_by_parent = {"folders/1": [p1]}
        result = serialize_tree(
            [org_node], projects_by_parent,
            orgless_projects=[orgless_p],
        )
        assert len(result) == 2
        assert result[0]["type"] == "organization"
        assert result[1]["type"] == "organizationless"
        assert len(result[1]["children"]) == 1
        assert result[1]["children"][0]["display_name"] == "Standalone"

    def test_without_orgless(self):
        _, org_node, _, p1, _ = _h()
        projects_by_parent = {"folders/1": [p1]}
        result = serialize_tree([org_node], projects_by_parent)
        assert len(result) == 1


class TestSerializeNameResults:
    def test_full(self):
        results = [("//example.com/f1", "folders/1")]
        data = serialize_name_results(results)
        assert data == [{"path": "//example.com/f1", "resource_name": "folders/1"}]

    def test_id_only(self):
        results = [("//example.com/f1", "folders/1")]
        data = serialize_name_results(results, id_only=True)
        assert data == [{"path": "//example.com/f1", "resource_id": "1"}]


class TestSerializePathResults:
    def test_basic(self):
        results = [("folders/1", "//example.com/f1")]
        data = serialize_path_results(results)
        assert data == [{"resource_name": "folders/1", "path": "//example.com/f1"}]


class TestDumpJson:
    def test_valid_json(self):
        data = [{"key": "value", "num": 42}]
        output = dump_json(data)
        parsed = json.loads(output)
        assert parsed == data

    def test_unicode(self):
        data = [{"name": "Prüfung"}]
        output = dump_json(data)
        assert "Prüfung" in output


class TestDumpYaml:
    def test_valid_yaml(self):
        data = [{"key": "value", "num": 42}]
        output = dump_yaml(data)
        parsed = yaml.safe_load(output)
        assert parsed == data

    def test_no_sort_keys(self):
        data = [{"z_key": 1, "a_key": 2}]
        output = dump_yaml(data)
        # z_key should appear before a_key (insertion order)
        assert output.index("z_key") < output.index("a_key")
