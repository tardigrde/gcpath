import json

import yaml

from conftest import make_test_hierarchy
from gcpath.serializers import (
    dump_json,
    dump_yaml,
    resource_type,
    serialize_ancestors,
    serialize_ls,
    serialize_name_results,
    serialize_path_results,
    serialize_resource,
    serialize_tree,
    serialize_tree_node,
    toon_ls,
    toon_name,
    toon_path,
    toon_ancestors,
    toon_find,
    toon_stats,
    toon_cache_status,
    toon_config,
    toon_confirmed,
    _truncate_metadata,
    _default_fields_for_items,
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
            [org_node],
            projects_by_parent,
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


class TestSerializeTreeNodeTypeFilter:
    def test_type_filter_folder(self):
        _, org_node, _, p1, _ = _h()
        projects_by_parent = {"folders/1": [p1]}
        d = serialize_tree_node(org_node, projects_by_parent, type_filter="folder")
        # Should have folder children but no project children
        f1_node = d["children"][0]
        assert f1_node["type"] == "folder"
        # f1's children should only contain f11 (folder), not p1 (project)
        child_types = [c["type"] for c in f1_node["children"]]
        assert "project" not in child_types
        assert "folder" in child_types

    def test_type_filter_project(self):
        _, org_node, _, p1, _ = _h()
        projects_by_parent = {"folders/1": [p1]}
        d = serialize_tree_node(org_node, projects_by_parent, type_filter="project")
        # Folders should not appear as children, but their projects should bubble up
        child_types = [c["type"] for c in d["children"]]
        assert "folder" not in child_types
        assert "project" in child_types


class TestSerializeTreeTypeFilter:
    def test_folder_filter_excludes_orgless(self):
        _, org_node, _, p1, orgless_p = _h()
        projects_by_parent = {"folders/1": [p1]}
        result = serialize_tree(
            [org_node],
            projects_by_parent,
            orgless_projects=[orgless_p],
            type_filter="folder",
        )
        # Should only have org node, no organizationless section
        assert len(result) == 1
        assert result[0]["type"] == "organization"


class TestSerializeAncestors:
    def test_basic(self):
        chain = [
            ("organizations/123", "example.com", "organization"),
            ("folders/456", "engineering", "folder"),
            ("projects/p1", "my-project", "project"),
        ]
        result = serialize_ancestors(chain)
        assert len(result) == 3
        assert result[0] == {
            "resource_name": "organizations/123",
            "display_name": "example.com",
            "type": "organization",
        }
        assert result[1] == {
            "resource_name": "folders/456",
            "display_name": "engineering",
            "type": "folder",
        }
        assert result[2] == {
            "resource_name": "projects/p1",
            "display_name": "my-project",
            "type": "project",
        }

    def test_empty(self):
        assert serialize_ancestors([]) == []


class TestSerializeResourceWithLabelsAndTags:
    def test_folder_with_labels(self):
        hierarchy = make_test_hierarchy()
        org_node = hierarchy.organizations[0]
        f1 = org_node.folders["folders/1"]
        f1.labels = {"env": "prod", "team": "eng"}
        d = serialize_resource(f1.path, f1)
        assert d["labels"] == {"env": "prod", "team": "eng"}
        assert "tags" not in d  # Empty tags should not appear

    def test_project_with_tags(self):
        hierarchy = make_test_hierarchy()
        p1 = next(p for p in hierarchy.projects if p.name == "projects/p1")
        p1.tags = {"org/env": "production"}
        d = serialize_resource(p1.path, p1)
        assert d["tags"] == {"org/env": "production"}
        assert "labels" not in d  # Empty labels should not appear

    def test_no_labels_no_tags(self):
        hierarchy = make_test_hierarchy()
        org_node = hierarchy.organizations[0]
        f1 = org_node.folders["folders/1"]
        d = serialize_resource(f1.path, f1)
        assert "labels" not in d
        assert "tags" not in d

    def test_organization_has_no_labels(self):
        hierarchy = make_test_hierarchy()
        org_node = hierarchy.organizations[0]
        d = serialize_resource("//example.com", org_node)
        assert "labels" not in d
        assert "tags" not in d


class TestToonLs:
    def test_basic_output(self):
        _, _, f1, p1, _ = _h()
        items = [("//example.com/f1", f1), ("//example.com/f1/Project 1", p1)]
        output = toon_ls(items, total_in_scope=2)
        assert "count:" in output
        assert "resources" in output
        assert "f1" in output

    def test_empty_items(self):
        output = toon_ls([], total_in_scope=0)
        assert "0" in output

    def test_with_help(self):
        _, _, f1, _, _ = _h()
        items = [("//example.com/f1", f1)]
        output = toon_ls(items, total_in_scope=1, help_lines=["Run `gcpath ls -R`"])
        assert "help" in output

    def test_fields_override(self):
        _, _, f1, _, _ = _h()
        items = [("//example.com/f1", f1)]
        output = toon_ls(items, total_in_scope=1, fields=("path", "type"))
        assert "path" in output
        assert "type" in output

    def test_full_flag(self):
        _, _, f1, _, _ = _h()
        f1.labels = {f"k{i}": f"v{i}" for i in range(8)}
        items = [("//example.com/f1", f1)]
        output_truncated = toon_ls(
            items, total_in_scope=1, fields=("path", "type", "labels"), full=False
        )
        output_full = toon_ls(
            items, total_in_scope=1, fields=("path", "type", "labels"), full=True
        )
        assert "k7" in output_full
        assert "--full" in output_truncated


class TestToonName:
    def test_single(self):
        output = toon_name([("//example.com/f1", "folders/1")])
        assert "resource_name:" in output
        assert "folders/1" in output

    def test_single_id_only(self):
        output = toon_name([("//example.com/f1", "folders/1")], id_only=True)
        assert "resource_id:" in output
        assert "1" in output

    def test_multiple(self):
        output = toon_name(
            [
                ("//example.com", "organizations/123"),
                ("//example.com/f1", "folders/1"),
            ]
        )
        assert "organizations/123" in output
        assert "folders/1" in output


class TestToonPath:
    def test_single(self):
        output = toon_path([("folders/1", "//example.com/f1")])
        assert "path:" in output
        assert "//example.com/f1" in output

    def test_multiple(self):
        output = toon_path(
            [
                ("folders/1", "//example.com/f1"),
                ("folders/2", "//example.com/f2"),
            ]
        )
        assert "//example.com/f1" in output
        assert "//example.com/f2" in output


class TestToonAncestors:
    def test_basic(self):
        chain = [
            ("organizations/123", "example.com", "organization"),
            ("folders/456", "eng", "folder"),
        ]
        output = toon_ancestors(chain)
        assert "organizations/123" in output
        assert "example.com" in output
        assert "folder" in output


class TestToonFind:
    def test_with_results(self):
        _, _, f1, _, _ = _h()
        items = [("//example.com/f1", f1)]
        output = toon_find(items, "f*", total_searched=5)
        assert "count:" in output
        assert "1 of 5 searched" in output
        assert "f1" in output

    def test_empty(self):
        output = toon_find([], "xyz*")
        assert "0" in output


class TestToonStats:
    def test_basic(self):
        output = toon_stats(
            "all organizations", organizations=2, folders=10, projects=25
        )
        assert "scope:" in output
        assert "2" in output
        assert "10" in output
        assert "25" in output

    def test_scoped(self):
        output = toon_stats(
            "folders/123", folders=5, projects=8, help_lines=["Run `gcpath stats`"]
        )
        assert "folders/123" in output
        assert "help" in output


class TestToonCacheStatus:
    def test_fresh(self):
        output = toon_cache_status(
            exists=True,
            fresh=True,
            age_seconds=300.0,
            org_count=1,
            folder_count=5,
            project_count=10,
            location="/var/cache/gcpath/test",
        )
        assert "fresh" in output
        assert "5m" in output

    def test_empty(self):
        output = toon_cache_status(
            exists=False, fresh=False, location="/var/cache/gcpath/test"
        )
        assert "empty" in output

    def test_stale(self):
        output = toon_cache_status(
            exists=True,
            fresh=False,
            age_seconds=7200.0,
            org_count=0,
            folder_count=0,
            project_count=0,
            location="/var/cache/gcpath/test",
        )
        assert "stale" in output


class TestToonConfig:
    def test_with_data(self):
        output = toon_config({"entrypoint": "folders/123"}, "/var/cache/gcpath/config")
        assert "folders/123" in output

    def test_empty(self):
        output = toon_config({}, "/var/cache/gcpath/config")
        assert "empty" in output


class TestToonConfirmed:
    def test_basic(self):
        output = toon_confirmed("Cache cleared")
        assert "ok" in output
        assert "Cache cleared" in output


class TestTruncateMetadata:
    def test_short_dict(self):
        d = {"a": "1", "b": "2"}
        result = _truncate_metadata(d)
        assert result == d

    def test_long_dict_truncated(self):
        d = {f"k{i}": f"v{i}" for i in range(8)}
        result = _truncate_metadata(d, limit=5)
        assert len(result) == 6  # 5 real + 1 truncation notice

    def test_full_flag_overrides(self):
        d = {f"k{i}": f"v{i}" for i in range(8)}
        result = _truncate_metadata(d, limit=5, full=True)
        assert len(result) == 8


class TestDefaultFieldsForItems:
    def test_with_projects(self):
        _, _, _, p1, _ = _h()
        items = [("//x", p1)]
        fields = _default_fields_for_items(items)
        assert "project_id" in fields

    def test_without_projects(self):
        _, _, f1, _, _ = _h()
        items = [("//x", f1)]
        fields = _default_fields_for_items(items)
        assert "project_id" not in fields


class TestToonOpen:
    def test_single_result_object_form(self):
        from gcpath.serializers import toon_open

        out = toon_open(
            [{"path": "//e/f1", "resource_name": "folders/1", "url": "https://x"}]
        )
        assert "url" in out
        assert "https://x" in out

    def test_multiple_results_table_form(self):
        from gcpath.serializers import toon_open

        out = toon_open(
            [
                {"path": "//e/f1", "resource_name": "folders/1", "url": "u1"},
                {"path": "//e/f2", "resource_name": "folders/2", "url": "u2"},
            ]
        )
        assert "results" in out
        assert "u1" in out and "u2" in out


class TestToonLabelsTags:
    def test_labels_with_rows(self):
        from gcpath.serializers import toon_labels

        rows = [
            {"key": "team", "value": "eng", "count": 3, "examples": "//x/a"},
        ]
        out = toon_labels(rows, total_resources=10)
        assert "team" in out
        assert "of 10" in out

    def test_labels_empty(self):
        from gcpath.serializers import toon_labels

        out = toon_labels([], total_resources=5)
        assert "0 labels" in out

    def test_tags_with_rows(self):
        from gcpath.serializers import toon_tags

        rows = [
            {"key": "env", "value": "prod", "count": 2, "examples": "//x/a"},
        ]
        out = toon_tags(rows, total_resources=4)
        assert "env" in out


class TestToonSummary:
    def test_summary_serializes(self):
        from gcpath.serializers import toon_summary

        data = {
            "org_count": 1,
            "folder_count": 2,
            "project_count": 3,
            "max_depth": 2,
            "top_label_keys": [{"key": "team", "count": 5}],
            "top_tag_keys": [],
            "orgs": [],
            "deepest_paths": ["//x/a/b"],
        }
        out = toon_summary(data)
        assert "org_count" in out
        assert "folder_count" in out


class TestToonAudit:
    def test_audit_with_issues(self):
        from gcpath.serializers import toon_audit

        issues = [
            {
                "severity": "warn",
                "check": "orphan_project",
                "path": "//_/p1",
                "type": "project",
                "details": "no parent",
            }
        ]
        out = toon_audit(issues, {"error": 0, "warn": 1, "info": 0})
        assert "orphan_project" in out
        # Singular noun for a count of 1 (avoids "1 issues" UI defect).
        assert "1 issue" in out
        assert "1 issues" not in out

    def test_audit_empty(self):
        from gcpath.serializers import toon_audit

        out = toon_audit([], {"error": 0, "warn": 0, "info": 0})
        assert "0 issues" in out
