"""
Configuration management for gcpath.

Stores user preferences (e.g., default entrypoint) in ~/.gcpath/config.json.
"""

import json
import logging
from typing import Any, Dict, Optional

from gcpath.cache import CACHE_DIR

logger = logging.getLogger(__name__)

CONFIG_FILE = CACHE_DIR / "config.json"


def read_config() -> Dict[str, Any]:
    """Read the config file. Returns empty dict if missing or invalid."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not read config file: {e}")
        return {}


def write_config(config: Dict[str, Any]) -> None:
    """Write the config dict to the config file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def _validate_entrypoint(resource: str) -> None:
    """Validate that the entrypoint is a valid resource name."""
    if not resource.startswith("organizations/") and not resource.startswith(
        "folders/"
    ):
        raise ValueError(
            f"Entrypoint must start with 'organizations/' or 'folders/', got '{resource}'"
        )


def get_entrypoint() -> Optional[str]:
    """Get the configured entrypoint, or None if not set."""
    config = read_config()
    return config.get("entrypoint")


def set_entrypoint(resource: str) -> None:
    """Set the entrypoint in config. Validates the resource format."""
    _validate_entrypoint(resource)
    config = read_config()
    config["entrypoint"] = resource
    write_config(config)


def clear_entrypoint() -> None:
    """Remove the entrypoint from config."""
    config = read_config()
    config.pop("entrypoint", None)
    write_config(config)
