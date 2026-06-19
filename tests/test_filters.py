from typing import Any, Dict, List, Tuple

import pytest
from conftest import make_test_hierarchy

from gcpath.core import GCPathError
from gcpath.filters import (
    MAX_REGEX_PATTERN_LENGTH,
    apply_exclusions,
    build_pattern_matcher,
    get_display_name,
    get_resource_path,
    matches_metadata,
    parse_metadata_filter,
)


# ---- parse_metadata_filter ----


def test_parse_key_only():
    assert parse_metadata_filter("env") == ("env", None, False)


def test_parse_equality():
    assert parse_metadata_filter("env=prod") == ("env", "prod", False)


def test_parse_negation():
    assert parse_metadata_filter("env!=prod") == ("env", "prod", True)


def test_parse_negation_takes_precedence_over_equality():
    # "!=" contains "=", so it must be checked first
    key, value, negated = parse_metadata_filter("team!=a=b")
    assert (key, value, negated) == ("team", "a=b", True)


def test_parse_empty_value():
    assert parse_metadata_filter("env=") == ("env", "", False)


def test_parse_strips_whitespace():
    assert parse_metadata_filter("env = prod") == ("env", "prod", False)
    assert parse_metadata_filter("env != prod") == ("env", "prod", True)
    assert parse_metadata_filter(" env ") == ("env", None, False)


# ---- matches_metadata ----


class _Obj:
    def __init__(self, labels: Dict[str, str]) -> None:
        self.labels = labels


def test_matches_no_filters():
    assert matches_metadata(_Obj({}), None, "labels") is True
    assert matches_metadata(_Obj({}), [], "labels") is True


def test_matches_presence():
    assert matches_metadata(_Obj({"env": "prod"}), ["env"], "labels") is True
    assert matches_metadata(_Obj({}), ["env"], "labels") is False


def test_matches_equality():
    assert matches_metadata(_Obj({"env": "prod"}), ["env=prod"], "labels") is True
    assert matches_metadata(_Obj({"env": "dev"}), ["env=prod"], "labels") is False


def test_matches_negation_excludes_value():
    assert matches_metadata(_Obj({"env": "prod"}), ["env!=prod"], "labels") is False


def test_matches_negation_passes_different_value():
    assert matches_metadata(_Obj({"env": "dev"}), ["env!=prod"], "labels") is True


def test_matches_negation_passes_missing_key():
    assert matches_metadata(_Obj({}), ["env!=prod"], "labels") is True


def test_matches_filters_are_anded():
    obj = _Obj({"env": "prod", "team": "core"})
    assert matches_metadata(obj, ["env=prod", "team=core"], "labels") is True
    assert matches_metadata(obj, ["env=prod", "team=infra"], "labels") is False
    assert matches_metadata(obj, ["env=prod", "team!=core"], "labels") is False


def test_matches_missing_attr():
    assert matches_metadata(object(), ["env=prod"], "labels") is False
    assert matches_metadata(object(), ["env!=prod"], "labels") is True


# ---- build_pattern_matcher ----


def test_glob_matches_display_name():
    m = build_pattern_matcher("f*")
    assert m("//example.com/f1", "f1") is True
    assert m("//example.com/other", "other") is False


def test_glob_is_case_insensitive():
    m = build_pattern_matcher("PROJECT*")
    assert m("//example.com/f1/project 1", "Project 1") is True


def test_glob_requires_full_match_on_name():
    m = build_pattern_matcher("f1")
    assert m("//example.com/f1", "f1") is True
    assert m("//example.com/f1/f11", "f11") is False


def test_glob_with_path_prefix_matches_full_path():
    m = build_pattern_matcher("//example.com/f1*")
    assert m("//example.com/f1", "f1") is True
    assert m("//example.com/f1/f11", "f11") is True
    assert m("//other.org/f1", "f1") is False


def test_regex_searches_display_name():
    m = build_pattern_matcher(r"^f\d+$", regex=True)
    assert m("//example.com/f1", "f1") is True
    assert m("//example.com/folder", "folder") is False


def test_regex_search_semantics_substring():
    m = build_pattern_matcher("rod", regex=True)
    assert m("//x/prod-app", "prod-app") is True


def test_regex_is_case_insensitive():
    m = build_pattern_matcher("PROD", regex=True)
    assert m("//x/prod-app", "prod-app") is True


def test_regex_with_path_prefix_matches_full_path():
    m = build_pattern_matcher(r"//example\.com/f\d+", regex=True)
    assert m("//example.com/f1", "f1") is True
    assert m("//other.org/f1", "f1") is False


def test_regex_anchored_path_matches_full_path():
    m = build_pattern_matcher(r"^//example\.com/", regex=True)
    assert m("//example.com/f1", "f1") is True
    assert m("//other.org/f1", "f1") is False
    m = build_pattern_matcher(r"\A//example\.com/", regex=True)
    assert m("//example.com/f1", "f1") is True


def test_glob_anchored_prefix_is_not_path_pattern():
    # "^//" only signals a path pattern for regexes; globs match names
    m = build_pattern_matcher("^//*")
    assert m("//example.com/f1", "f1") is False


def test_regex_invalid_raises_gcpath_error():
    with pytest.raises(GCPathError, match="Invalid regex"):
        build_pattern_matcher("[unclosed", regex=True)


def test_regex_too_long_raises_gcpath_error():
    with pytest.raises(GCPathError, match="too long"):
        build_pattern_matcher("a" * (MAX_REGEX_PATTERN_LENGTH + 1), regex=True)


# ---- apply_exclusions ----


def _items() -> List[Tuple[str, Any]]:
    h = make_test_hierarchy()
    resources: List[Any] = [*h.folders, *h.projects]
    return [(get_resource_path(obj), obj) for obj in resources]


def test_apply_exclusions_none():
    items = _items()
    assert apply_exclusions(items, None) == items
    assert apply_exclusions(items, []) == items


def test_apply_exclusions_by_name():
    items = _items()
    remaining = apply_exclusions(items, ["f1*"])
    names = [get_display_name(obj) for _, obj in remaining]
    assert "f1" not in names
    assert "f11" not in names
    assert "Project 1" in names


def test_apply_exclusions_by_path():
    items = _items()
    remaining = apply_exclusions(items, ["//example.com/f1/*"])
    paths = [p for p, _ in remaining]
    assert "//example.com/f1" in paths
    assert all(not p.startswith("//example.com/f1/") for p in paths)


def test_apply_exclusions_multiple_globs_or_semantics():
    items = _items()
    remaining = apply_exclusions(items, ["f1", "Standalone"])
    names = [get_display_name(obj) for _, obj in remaining]
    assert "f1" not in names
    assert "Standalone" not in names
    assert "f11" in names
