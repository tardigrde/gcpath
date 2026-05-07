"""Hierarchy governance checks for `gcpath audit`.

Each check returns issue dicts with a stable shape:
    {"severity": str, "check": str, "path": str, "type": str, "details": str}

Checks are pure functions over a Hierarchy plus optional config; no GCP API
calls happen here.
"""

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from gcpath.core import (
    Folder,
    Hierarchy,
    OrganizationNode,
    Project,
    SYNTHETIC_ORG_NAME,
)


_SEVERITY_ORDER = {"info": 0, "warn": 1, "error": 2}

_DEFAULT_CHECKS = (
    "orphan_project",
    "synthetic_org",
    "missing_required_label",
    "duplicate_display_name",
    "name_pattern_violation",
)


def severity_at_least(severity: str, threshold: str) -> bool:
    return _SEVERITY_ORDER.get(severity, 0) >= _SEVERITY_ORDER.get(threshold, 0)


def _resource_type(item: Any) -> str:
    if isinstance(item, OrganizationNode):
        return "organization"
    if isinstance(item, Folder):
        return "folder"
    if isinstance(item, Project):
        return "project"
    return "unknown"


def _resource_path(item: Any) -> str:
    if isinstance(item, OrganizationNode):
        return f"//{item.organization.display_name}"
    return getattr(item, "path", "") or getattr(item, "name", "")


def _check_orphan(hierarchy: Hierarchy) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for p in hierarchy.projects:
        if p.organization is None and p.folder is None:
            issues.append({
                "severity": "warn",
                "check": "orphan_project",
                "path": p.path,
                "type": "project",
                "details": f"project '{p.project_id}' has no organization or folder",
            })
    return issues


def _check_synthetic_org(hierarchy: Hierarchy) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for org in hierarchy.organizations:
        if org.organization.name != SYNTHETIC_ORG_NAME:
            continue
        for f in org.folders.values():
            issues.append({
                "severity": "info",
                "check": "synthetic_org",
                "path": f.path,
                "type": "folder",
                "details": "loaded under synthetic org (no real org access)",
            })
    return issues


def _check_required_labels(
    hierarchy: Hierarchy, required_labels: Sequence[str]
) -> List[Dict[str, Any]]:
    if not required_labels:
        return []
    issues: List[Dict[str, Any]] = []
    targets: Iterable[Any] = list(hierarchy.folders) + list(hierarchy.projects)
    for item in targets:
        labels = getattr(item, "labels", None) or {}
        missing = [k for k in required_labels if k not in labels]
        if missing:
            issues.append({
                "severity": "error",
                "check": "missing_required_label",
                "path": _resource_path(item),
                "type": _resource_type(item),
                "details": "missing label keys: " + ",".join(missing),
            })
    return issues


def _check_duplicate_names(hierarchy: Hierarchy) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    by_parent: Dict[str, Dict[str, List[Any]]] = {}
    for f in hierarchy.folders:
        by_parent.setdefault(f.parent, {}).setdefault(f.display_name, []).append(f)
    for p in hierarchy.projects:
        by_parent.setdefault(p.parent, {}).setdefault(p.display_name, []).append(p)

    for parent, by_name in by_parent.items():
        for display_name, items in by_name.items():
            if len(items) <= 1:
                continue
            for item in items:
                issues.append({
                    "severity": "warn",
                    "check": "duplicate_display_name",
                    "path": _resource_path(item),
                    "type": _resource_type(item),
                    "details": (
                        f"display_name '{display_name}' shared with "
                        f"{len(items) - 1} sibling(s) under {parent}"
                    ),
                })
    return issues


def _check_name_pattern(
    hierarchy: Hierarchy, pattern: Optional[str]
) -> List[Dict[str, Any]]:
    if not pattern:
        return []
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return [{
            "severity": "error",
            "check": "name_pattern_violation",
            "path": "",
            "type": "config",
            "details": f"invalid --name-pattern '{pattern}': {e}",
        }]
    issues: List[Dict[str, Any]] = []
    targets: Iterable[Any] = list(hierarchy.folders) + list(hierarchy.projects)
    for item in targets:
        display_name = getattr(item, "display_name", "")
        if not regex.fullmatch(display_name):
            issues.append({
                "severity": "warn",
                "check": "name_pattern_violation",
                "path": _resource_path(item),
                "type": _resource_type(item),
                "details": f"display_name '{display_name}' does not match /{pattern}/",
            })
    return issues


def run_audit(
    hierarchy: Hierarchy,
    *,
    require_labels: Optional[Sequence[str]] = None,
    name_pattern: Optional[str] = None,
    checks: Optional[Sequence[str]] = None,
    severity: str = "info",
) -> List[Dict[str, Any]]:
    """Run audit checks against a loaded hierarchy.

    Args:
        hierarchy: Loaded Hierarchy.
        require_labels: List of required label keys (for `missing_required_label`).
        name_pattern: Regex that display names must `fullmatch`.
        checks: Optional subset of check IDs to run. Defaults to all.
        severity: Minimum severity to include in the result.

    Returns:
        List of issue dicts, sorted by severity (error > warn > info), then path.
    """
    enabled = set(checks) if checks else set(_DEFAULT_CHECKS)
    issues: List[Dict[str, Any]] = []

    if "orphan_project" in enabled:
        issues.extend(_check_orphan(hierarchy))
    if "synthetic_org" in enabled:
        issues.extend(_check_synthetic_org(hierarchy))
    if "missing_required_label" in enabled and require_labels:
        issues.extend(_check_required_labels(hierarchy, require_labels))
    if "duplicate_display_name" in enabled:
        issues.extend(_check_duplicate_names(hierarchy))
    if "name_pattern_violation" in enabled and name_pattern:
        issues.extend(_check_name_pattern(hierarchy, name_pattern))

    issues = [i for i in issues if severity_at_least(i["severity"], severity)]
    issues.sort(
        key=lambda i: (-_SEVERITY_ORDER.get(i["severity"], 0), i["check"], i["path"])
    )
    return issues


def summarize_severities(issues: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"error": 0, "warn": 0, "info": 0}
    for issue in issues:
        sev = issue.get("severity", "info")
        if sev in counts:
            counts[sev] += 1
    return counts
