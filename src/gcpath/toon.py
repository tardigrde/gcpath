"""TOON output helpers for gcpath.

Thin wrapper around toon_format.encode() plus gcpath-specific AXI conventions:
- Pre-computed aggregates (count headers)
- Contextual help[] sections
- Structured errors and definitive empty states
"""

from typing import Any, Callable, Dict, List, Optional, Sequence

import toon_format

from gcpath.core import GCPathError

_maybe_encode = getattr(toon_format, "encode", None)
if not callable(_maybe_encode):
    raise GCPathError("toon_format is missing encode(); check the pinned dependency")
_toon_encode: Callable[[Any], str] = _maybe_encode


def toon_encode(data: Any) -> str:
    return _toon_encode(data)


def toon_object(fields: Dict[str, Any]) -> str:
    return _toon_encode(fields)


def toon_table(
    key: str,
    items: Sequence[Dict[str, Any]],
    fields: Optional[Sequence[str]] = None,
) -> str:
    """Encode a tabular array with the given key.

    If fields is provided and items are non-empty dicts, the field order
    from ``fields`` is enforced by rebuilding each dict in that order.
    """
    if not items:
        return _toon_encode({key: []})

    if fields and isinstance(items[0], dict):
        ordered = [{f: item.get(f, "") for f in fields} for item in items]
        return _toon_encode({key: ordered})

    return _toon_encode({key: list(items)})


def toon_error(message: str, help_lines: Optional[List[str]] = None) -> str:
    data: Dict[str, Any] = {"error": message}
    if help_lines:
        data["help"] = help_lines
    return _toon_encode(data)


def toon_empty(
    resource_type: str,
    context: str,
    help_lines: Optional[List[str]] = None,
) -> str:
    msg = f"0 {resource_type} found"
    if context:
        msg = f"0 {resource_type} {context}"
    data: Dict[str, Any] = {"resources": msg}
    if help_lines:
        data["help"] = help_lines
    return _toon_encode(data)


def toon_help(lines: List[str]) -> str:
    return _toon_encode({"help": lines})


def with_help(toon_output: str, help_lines: Optional[List[str]] = None) -> str:
    if not help_lines:
        return toon_output
    help_section = _toon_encode({"help": help_lines})
    return toon_output.rstrip("\n") + "\n" + help_section


def toon_dashboard(data: Dict[str, Any]) -> str:
    return _toon_encode(data)


def format_age(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
