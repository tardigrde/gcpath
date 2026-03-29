"""Tests for config.py module."""

import pytest
from unittest.mock import patch

from gcpath.config import (
    read_config,
    write_config,
    get_entrypoint,
    set_entrypoint,
    clear_entrypoint,
)


@pytest.fixture
def tmp_config(tmp_path):
    """Patch CONFIG_FILE to a temporary location."""
    config_file = tmp_path / "config.json"
    with (
        patch("gcpath.config.CONFIG_FILE", config_file),
        patch("gcpath.config.CACHE_DIR", tmp_path),
    ):
        yield config_file


def test_read_config_no_file(tmp_config):
    """read_config returns empty dict when no config file exists."""
    assert read_config() == {}


def test_write_and_read_config(tmp_config):
    """write_config writes JSON, read_config reads it back."""
    write_config({"entrypoint": "folders/123"})
    assert read_config() == {"entrypoint": "folders/123"}


def test_read_config_invalid_json(tmp_config):
    """read_config returns empty dict on invalid JSON."""
    tmp_config.write_text("not json{{{")
    assert read_config() == {}


def test_get_entrypoint_not_set(tmp_config):
    """get_entrypoint returns None when not configured."""
    assert get_entrypoint() is None


def test_set_and_get_entrypoint_folder(tmp_config):
    """set_entrypoint stores folder, get_entrypoint retrieves it."""
    set_entrypoint("folders/456")
    assert get_entrypoint() == "folders/456"


def test_set_and_get_entrypoint_org(tmp_config):
    """set_entrypoint stores organization, get_entrypoint retrieves it."""
    set_entrypoint("organizations/789")
    assert get_entrypoint() == "organizations/789"


def test_set_entrypoint_invalid(tmp_config):
    """set_entrypoint raises ValueError for invalid resource."""
    with pytest.raises(ValueError, match="must start with"):
        set_entrypoint("projects/123")
    with pytest.raises(ValueError, match="must start with"):
        set_entrypoint("invalid")


def test_clear_entrypoint(tmp_config):
    """clear_entrypoint removes the entrypoint key."""
    set_entrypoint("folders/123")
    assert get_entrypoint() == "folders/123"
    clear_entrypoint()
    assert get_entrypoint() is None


def test_clear_entrypoint_no_existing(tmp_config):
    """clear_entrypoint works even when no entrypoint is set."""
    clear_entrypoint()
    assert get_entrypoint() is None


def test_write_config_preserves_other_keys(tmp_config):
    """write_config preserves existing config keys."""
    write_config({"entrypoint": "folders/1", "other": "value"})
    config = read_config()
    assert config["entrypoint"] == "folders/1"
    assert config["other"] == "value"
