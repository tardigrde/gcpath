"""Tests for the errors module (error-to-guidance mapping)."""

from unittest.mock import patch

from google.api_core import exceptions as gcp_exceptions
from google.auth import exceptions as auth_exceptions

from conftest import make_test_hierarchy
from gcpath.core import GCPathError, ResourceNotFoundError
from gcpath.errors import (
    ADC_LOGIN_HELP,
    _extract_query,
    describe_error,
    is_unexpected,
    suggest_similar,
)


def test_extract_query_quoted():
    assert _extract_query("Folder 'folders/123' not found") == "folders/123"


def test_extract_query_suffix():
    assert _extract_query("Resource not found: //example.com/f2") == "//example.com/f2"


def test_extract_query_none():
    assert _extract_query("something went wrong") is None


def test_extract_query_suffix_strips_trailing_punctuation():
    assert _extract_query("Resource not found: //example.com/f2.") == "//example.com/f2"


def test_describe_default_credentials_error():
    message, help_lines = describe_error(
        auth_exceptions.DefaultCredentialsError("no creds")
    )
    assert "credentials" in message.lower()
    assert ADC_LOGIN_HELP in help_lines


def test_describe_refresh_error():
    message, help_lines = describe_error(auth_exceptions.RefreshError("expired"))
    assert "expired" in message.lower()
    assert ADC_LOGIN_HELP in help_lines


def test_describe_permission_denied_service_disabled():
    e = gcp_exceptions.PermissionDenied(
        "Cloud Asset API has not been used in project 123 before or it is disabled."
    )
    message, help_lines = describe_error(e)
    assert "Cloud Asset API is disabled" in message
    assert (
        "Run `gcloud services enable cloudasset.googleapis.com` to enable it"
        in help_lines
    )
    assert any("-U" in line for line in help_lines)


def test_describe_permission_denied_service_disabled_reason_code():
    e = gcp_exceptions.PermissionDenied("Request denied. Reason: SERVICE_DISABLED")
    message, _ = describe_error(e)
    assert "Cloud Asset API is disabled" in message


def test_describe_permission_denied_other_service_disabled():
    e = gcp_exceptions.PermissionDenied(
        "Cloud Resource Manager API has not been used in project 123 before or it"
        " is disabled. Enable it by visiting https://console.developers.google.com"
        "/apis/api/cloudresourcemanager.googleapis.com/overview?project=123"
    )
    message, help_lines = describe_error(e)
    assert "cloudresourcemanager.googleapis.com is disabled" in message
    assert (
        "Run `gcloud services enable cloudresourcemanager.googleapis.com` to enable it"
        in help_lines
    )
    assert not any("-U" in line for line in help_lines)


def test_describe_permission_denied_generic():
    message, help_lines = describe_error(gcp_exceptions.PermissionDenied("denied"))
    assert "Permission Denied" in message
    assert ADC_LOGIN_HELP in help_lines


def test_describe_service_unavailable():
    message, help_lines = describe_error(
        gcp_exceptions.ServiceUnavailable("unavailable")
    )
    assert "unreachable" in message
    assert any("network" in line for line in help_lines)
    assert any("cache status" in line for line in help_lines)


def test_describe_gcpath_error_passthrough():
    message, help_lines = describe_error(GCPathError("custom failure"))
    assert message == "custom failure"
    assert help_lines == []


def test_describe_unexpected_error():
    message, _ = describe_error(ValueError("boom"))
    assert "Unexpected error" in message


def test_suggest_similar_from_cache():
    with patch("gcpath.cache.read_cache_unchecked", return_value=make_test_hierarchy()):
        suggestions = suggest_similar("//example.com/f2")
    assert "//example.com/f1" in suggestions


def test_suggest_similar_no_cache():
    with patch("gcpath.cache.read_cache_unchecked", return_value=None):
        assert suggest_similar("//example.com/f2") == []


def test_not_found_with_suggestions():
    with patch("gcpath.cache.read_cache_unchecked", return_value=make_test_hierarchy()):
        message, help_lines = describe_error(
            ResourceNotFoundError("Resource not found: //example.com/f2")
        )
    assert "not found" in message
    assert any("Did you mean" in line for line in help_lines)
    assert any("//example.com/f1" in line for line in help_lines)


def test_not_found_without_cache_falls_back_to_generic_help():
    with patch("gcpath.cache.read_cache_unchecked", return_value=None):
        _, help_lines = describe_error(
            ResourceNotFoundError("Folder 'folders/999' not found")
        )
    assert any("gcpath ls -R" in line for line in help_lines)
    assert not any("Did you mean" in line for line in help_lines)


def test_is_unexpected():
    assert not is_unexpected(GCPathError("x"))
    assert not is_unexpected(gcp_exceptions.PermissionDenied("x"))
    assert not is_unexpected(auth_exceptions.DefaultCredentialsError("x"))
    assert is_unexpected(ValueError("x"))
