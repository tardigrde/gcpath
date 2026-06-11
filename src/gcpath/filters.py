"""Resource filtering for `ls` and `find`.

Covers metadata (label/tag) filters including negation (`key!=value`),
name/path pattern matching (glob or regex), and exclusion globs.
Patterns starting with `//` match against the full resource path;
all other patterns match against the display name.
"""

import fnmatch
import re
from typing import Callable, List, Optional, Tuple, Union

from gcpath.core import Folder, GCPathError, OrganizationNode, Project, path_escape

Resource = Union[OrganizationNode, Folder, Project]

# matcher(path, display_name) -> bool
PatternMatcher = Callable[[str, str], bool]


def get_display_name(obj: Resource) -> str:
    if isinstance(obj, OrganizationNode):
        return obj.organization.display_name
    return obj.display_name


def get_resource_path(obj: Resource) -> str:
    if isinstance(obj, OrganizationNode):
        return f"//{path_escape(obj.organization.display_name)}"
    return obj.path


def parse_metadata_filter(filter_str: str) -> Tuple[str, Optional[str], bool]:
    """Parse a label/tag filter into (key, value, negated).

    Supported forms: `key` (presence), `key=value` (equality),
    `key!=value` (exclusion). `!=` is checked first since it contains `=`.
    """
    if "!=" in filter_str:
        key, _, value = filter_str.partition("!=")
        return key, value, True
    if "=" in filter_str:
        key, _, value = filter_str.partition("=")
        return key, value, False
    return filter_str, None, False


def matches_metadata(
    obj: Resource,
    filters: Optional[List[str]],
    attr: str,
) -> bool:
    """True if the resource's labels/tags satisfy every filter (ANDed).

    `key!=value` passes when the key is absent or has a different value.
    """
    if not filters:
        return True
    metadata = getattr(obj, attr, {}) or {}
    for f in filters:
        key, value, negated = parse_metadata_filter(f)
        if negated:
            if metadata.get(key) == value:
                return False
        elif value is None:
            if key not in metadata:
                return False
        elif metadata.get(key) != value:
            return False
    return True


def build_pattern_matcher(pattern: str, regex: bool = False) -> PatternMatcher:
    """Build a matcher(path, display_name) for a glob or regex pattern.

    Patterns starting with `//` are matched against the full path,
    otherwise against the display name. Globs must match the whole
    target (case-insensitive); regexes use search semantics.

    Raises GCPathError for an invalid regex.
    """
    against_path = pattern.startswith("//")
    if regex:
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            raise GCPathError(f"Invalid regex '{pattern}': {e}") from e

        def regex_matcher(path: str, display_name: str) -> bool:
            return compiled.search(path if against_path else display_name) is not None

        return regex_matcher

    lower_pattern = pattern.lower()

    def glob_matcher(path: str, display_name: str) -> bool:
        target = path if against_path else display_name
        return fnmatch.fnmatch(target.lower(), lower_pattern)

    return glob_matcher


def apply_exclusions(
    items: List[Tuple[str, Resource]],
    excludes: Optional[List[str]],
) -> List[Tuple[str, Resource]]:
    """Drop (path, resource) pairs matching any exclusion glob."""
    if not excludes:
        return items
    matchers = [build_pattern_matcher(g) for g in excludes]
    return [
        (path, obj)
        for path, obj in items
        if not any(m(path, get_display_name(obj)) for m in matchers)
    ]
