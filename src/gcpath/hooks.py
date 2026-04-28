"""Agent session hook management for gcpath.

Implements AXI Principle 7 (ambient context) by self-installing
session-start hooks into Claude Code and Codex configurations.
"""

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_GCPATH_HOOK_COMMAND = "gcpath hook run"

_CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
_CODEX_HOOKS_PATH = Path.home() / ".codex" / "hooks.json"


def _get_gcpath_bin() -> str:
    return shutil.which("gcpath") or "gcpath"


def _get_hook_command() -> str:
    bin_path = _get_gcpath_bin()
    return f"{bin_path} hook run"


def _is_managed_hook(command: str) -> bool:
    return command.strip().endswith(_GCPATH_HOOK_COMMAND)


def _get_claude_entry_command(entry: Dict[str, Any]) -> str:
    """Extract command from a Claude Code SessionStart hook entry (new or legacy format)."""
    # New format: {"matcher": ..., "hooks": [{"type": "command", "command": ...}]}
    nested = entry.get("hooks")
    if isinstance(nested, list) and nested:
        return nested[0].get("command", "")
    # Legacy flat format: {"command": ...}
    return entry.get("command", "")


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            loaded = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not read {path}: {e}")
        return None
    if not isinstance(loaded, dict):
        logger.warning(f"Unexpected JSON shape in {path}: {type(loaded).__name__}")
        return None
    return loaded


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _install_claude_code(command: str) -> bool:
    """Install hook into Claude Code settings. Returns True if changed."""
    data = _read_json(_CLAUDE_SETTINGS_PATH) or {}

    if "hooks" not in data:
        data["hooks"] = {}

    hooks = data["hooks"]
    if "SessionStart" not in hooks:
        hooks["SessionStart"] = []

    for entry in hooks["SessionStart"]:
        if isinstance(entry, dict) and _is_managed_hook(_get_claude_entry_command(entry)):
            if _get_claude_entry_command(entry) == command:
                return False
            # Update command in-place (new format preferred)
            nested = entry.get("hooks")
            if isinstance(nested, list) and nested:
                nested[0]["command"] = command
            else:
                entry["hooks"] = [{"type": "command", "command": command, "timeout": 10000}]
                entry.pop("command", None)
                entry.setdefault("matcher", "")
            _write_json(_CLAUDE_SETTINGS_PATH, data)
            return True

    hooks["SessionStart"].append({
        "matcher": "",
        "hooks": [{"type": "command", "command": command, "timeout": 10000}],
    })
    _write_json(_CLAUDE_SETTINGS_PATH, data)
    return True


def _uninstall_claude_code() -> bool:
    """Remove gcpath hooks from Claude Code settings. Returns True if changed."""
    data = _read_json(_CLAUDE_SETTINGS_PATH)
    if not data or "hooks" not in data:
        return False

    hooks = data["hooks"]
    if "SessionStart" not in hooks:
        return False

    original_len = len(hooks["SessionStart"])
    hooks["SessionStart"] = [
        entry for entry in hooks["SessionStart"]
        if not (isinstance(entry, dict) and _is_managed_hook(_get_claude_entry_command(entry)))
    ]

    if len(hooks["SessionStart"]) == original_len:
        return False

    if not hooks["SessionStart"]:
        del hooks["SessionStart"]
    if not hooks:
        del data["hooks"]

    _write_json(_CLAUDE_SETTINGS_PATH, data)
    return True


def _install_codex(command: str) -> bool:
    """Install hook into Codex hooks. Returns True if changed."""
    data = _read_json(_CODEX_HOOKS_PATH) or {}

    if "SessionStart" not in data:
        data["SessionStart"] = []

    for entry in data["SessionStart"]:
        if isinstance(entry, dict) and _is_managed_hook(entry.get("command", "")):
            if entry.get("command") == command:
                return False
            entry["command"] = command
            _write_json(_CODEX_HOOKS_PATH, data)
            return True

    data["SessionStart"].append({"command": command})
    _write_json(_CODEX_HOOKS_PATH, data)
    return True


def _uninstall_codex() -> bool:
    """Remove gcpath hooks from Codex hooks. Returns True if changed."""
    data = _read_json(_CODEX_HOOKS_PATH)
    if not data or "SessionStart" not in data:
        return False

    original_len = len(data["SessionStart"])
    data["SessionStart"] = [
        entry for entry in data["SessionStart"]
        if not (isinstance(entry, dict) and _is_managed_hook(entry.get("command", "")))
    ]

    if len(data["SessionStart"]) == original_len:
        return False

    if not data["SessionStart"]:
        del data["SessionStart"]

    _write_json(_CODEX_HOOKS_PATH, data)
    return True


def install_hooks() -> Dict[str, bool]:
    """Install hooks into all supported targets.

    Returns dict of {target: changed} indicating what was updated.
    """
    command = _get_hook_command()
    results = {
        "claude_code": _install_claude_code(command),
        "codex": _install_codex(command),
    }
    return results


def uninstall_hooks() -> Dict[str, bool]:
    """Remove hooks from all supported targets.

    Returns dict of {target: changed} indicating what was removed.
    """
    results = {
        "claude_code": _uninstall_claude_code(),
        "codex": _uninstall_codex(),
    }
    return results


def repair_hooks() -> Dict[str, bool]:
    """Check and fix executable path in existing hooks.

    Returns dict of {target: changed} indicating what was repaired.
    """
    command = _get_hook_command()
    results = {
        "claude_code": _install_claude_code(command),
        "codex": _install_codex(command),
    }
    return results


def _check_hook_entries(entries: list, command: str) -> tuple:
    """Check if gcpath hook is installed in a list of hook entries."""
    for entry in entries:
        if isinstance(entry, dict) and _is_managed_hook(_get_claude_entry_command(entry)):
            return True, _get_claude_entry_command(entry) == command
    return False, False


def get_hook_status() -> Dict[str, Any]:
    """Report hook installation status for all targets."""
    command = _get_hook_command()

    claude_data = _read_json(_CLAUDE_SETTINGS_PATH)
    claude_entries = (claude_data or {}).get("hooks", {}).get("SessionStart", [])
    claude_installed, claude_path_ok = _check_hook_entries(claude_entries, command)

    codex_data = _read_json(_CODEX_HOOKS_PATH)
    codex_entries = (codex_data or {}).get("SessionStart", [])
    codex_installed, codex_path_ok = _check_hook_entries(codex_entries, command)

    return {
        "claude_code": {
            "installed": claude_installed,
            "path_ok": claude_path_ok,
            "location": str(_CLAUDE_SETTINGS_PATH),
        },
        "codex": {
            "installed": codex_installed,
            "path_ok": codex_path_ok,
            "location": str(_CODEX_HOOKS_PATH),
        },
    }


def run_session_start() -> str:
    """Generate compact TOON dashboard for session-start hook output.

    Keeps output under ~500 tokens as per AXI spec.
    """
    from gcpath.cache import get_cache_info, read_cache_raw
    from gcpath.toon import toon_encode, format_age

    info = get_cache_info()

    if not info.exists or not info.fresh:
        return toon_encode({
            "gcp": {"cache": "empty"},
            "help": [
                "Run `gcpath ls` to list resources",
                "Run `gcpath ls -R` for recursive listing",
            ],
        })

    age_str = format_age(info.age_seconds) if info.age_seconds is not None else "unknown"

    org_rows = []
    raw_data = read_cache_raw()
    if raw_data:
        for org_data in raw_data.get("organizations", []):
            org_info = org_data.get("organization", {})
            name = org_info.get("display_name", "unknown")
            folder_count = len(org_data.get("folders", {}))
            project_count = len(org_data.get("projects", []))
            org_rows.append({
                "name": name,
                "folders": folder_count,
                "projects": project_count,
            })

    data: Dict[str, Any] = {
        "gcp": {
            "cache": f"fresh ({age_str})",
        },
    }
    if org_rows:
        data["gcp"]["orgs"] = org_rows[:5]

    data["help"] = [
        "Run `gcpath ls` to list resources",
        "Run `gcpath ls -R` for recursive listing",
    ]

    return toon_encode(data)
