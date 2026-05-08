"""Unit tests for gcpath.audit checks."""

from conftest import make_test_hierarchy
from google.cloud import resourcemanager_v3

from gcpath.audit import (
    run_audit,
    summarize_severities,
    severity_at_least,
)
from gcpath.core import (
    Folder,
    Hierarchy,
    OrganizationNode,
    Project,
    SYNTHETIC_ORG_NAME,
)


def test_severity_at_least():
    assert severity_at_least("error", "warn")
    assert severity_at_least("warn", "warn")
    assert not severity_at_least("info", "warn")


def test_orphan_project_detection():
    h = make_test_hierarchy()
    issues = run_audit(h)
    orphan_issues = [i for i in issues if i["check"] == "orphan_project"]
    assert len(orphan_issues) == 1
    assert "Standalone" in orphan_issues[0]["path"]
    assert orphan_issues[0]["severity"] == "warn"


def test_synthetic_org_detection():
    org_proto = resourcemanager_v3.Organization(
        name=SYNTHETIC_ORG_NAME, display_name="root_folder"
    )
    org_node = OrganizationNode(organization=org_proto)
    f = Folder(
        name="folders/9",
        display_name="root",
        ancestors=["folders/9"],
        organization=org_node,
        parent=SYNTHETIC_ORG_NAME,
    )
    org_node.folders["folders/9"] = f
    h = Hierarchy([org_node], [])
    issues = run_audit(h)
    synthetic_issues = [i for i in issues if i["check"] == "synthetic_org"]
    assert len(synthetic_issues) == 1
    assert synthetic_issues[0]["severity"] == "info"


def test_missing_required_label():
    h = make_test_hierarchy()
    h.folders[0].labels = {"team": "platform"}
    issues = run_audit(h, require_labels=["owner"])
    missing = [i for i in issues if i["check"] == "missing_required_label"]
    assert len(missing) >= 2
    assert all(i["severity"] == "error" for i in missing)


def test_no_required_labels_no_check():
    h = make_test_hierarchy()
    issues = run_audit(h, require_labels=None)
    assert not any(i["check"] == "missing_required_label" for i in issues)


def test_duplicate_display_name():
    org_proto = resourcemanager_v3.Organization(
        name="organizations/dup", display_name="dup.example.com"
    )
    org_node = OrganizationNode(organization=org_proto)
    f1 = Folder(
        name="folders/100",
        display_name="shared",
        ancestors=["folders/100", "organizations/dup"],
        organization=org_node,
        parent="organizations/dup",
    )
    f2 = Folder(
        name="folders/101",
        display_name="shared",
        ancestors=["folders/101", "organizations/dup"],
        organization=org_node,
        parent="organizations/dup",
    )
    org_node.folders["folders/100"] = f1
    org_node.folders["folders/101"] = f2
    h = Hierarchy([org_node], [])
    issues = run_audit(h)
    dups = [i for i in issues if i["check"] == "duplicate_display_name"]
    assert len(dups) == 2


def test_name_pattern_violation():
    h = make_test_hierarchy()
    issues = run_audit(h, name_pattern=r"^\d+$")
    violations = [i for i in issues if i["check"] == "name_pattern_violation"]
    assert violations
    assert all(v["severity"] == "warn" for v in violations)


def test_audit_severity_filter():
    h = make_test_hierarchy()
    h.folders[0].labels = {}
    # `require_labels` produces error-level issues that the filter must keep,
    # so the assertion exercises real filtering rather than passing vacuously.
    all_issues = run_audit(h, require_labels=["owner"])
    error_issues = run_audit(h, require_labels=["owner"], severity="error")
    assert error_issues, "expected at least one error-severity issue"
    assert all(i["severity"] == "error" for i in error_issues)
    assert len(error_issues) < len(all_issues), (
        "severity filter should drop warn/info issues"
    )


def test_audit_check_subset():
    h = make_test_hierarchy()
    issues = run_audit(h, checks=["orphan_project"])
    assert all(i["check"] == "orphan_project" for i in issues)


def test_summarize_severities():
    issues = [
        {"severity": "error"},
        {"severity": "warn"},
        {"severity": "warn"},
        {"severity": "info"},
    ]
    counts = summarize_severities(issues)
    assert counts == {"error": 1, "warn": 2, "info": 1}


def test_run_audit_sorts_by_severity():
    h = make_test_hierarchy()
    h.folders[0].labels = {}
    issues = run_audit(h, require_labels=["owner"])
    severities = [i["severity"] for i in issues]
    severity_order = {"error": 2, "warn": 1, "info": 0}
    for a, b in zip(severities, severities[1:]):
        assert severity_order[a] >= severity_order[b]


def test_audit_invalid_name_pattern_returns_config_error():
    h = make_test_hierarchy()
    issues = run_audit(h, name_pattern="(unclosed")
    config_issues = [i for i in issues if i["type"] == "config"]
    assert config_issues
    assert config_issues[0]["severity"] == "error"


def test_audit_oversized_name_pattern_returns_config_error():
    h = make_test_hierarchy()
    issues = run_audit(h, name_pattern="a" * 500)
    config_issues = [i for i in issues if i["type"] == "config"]
    assert config_issues
    assert "ReDoS" in config_issues[0]["details"]


def test_resource_path_escapes_org_display_name():
    """Audit paths must use the canonical url-escaped form for org names."""
    from gcpath.audit import _resource_path
    from gcpath.core import OrganizationNode
    from google.cloud import resourcemanager_v3 as rm

    org = OrganizationNode(
        organization=rm.Organization(
            name="organizations/9", display_name="acme corp"
        )
    )
    assert _resource_path(org) == "//acme%20corp"


def test_audit_clean_hierarchy_no_orphans():
    org_proto = resourcemanager_v3.Organization(
        name="organizations/clean", display_name="clean.example.com"
    )
    org_node = OrganizationNode(organization=org_proto)
    proj = Project(
        name="projects/clean1",
        project_id="clean1",
        display_name="clean1",
        parent="organizations/clean",
        organization=org_node,
        folder=None,
    )
    h = Hierarchy([org_node], [proj])
    issues = run_audit(h)
    assert issues == []
