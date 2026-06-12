"""Error-to-guidance mapping for the gcpath CLI.

Translates exceptions into AXI-style structured errors: a one-line message
plus actionable help[] lines. Includes cache-backed "did you mean" suggestions
for resource-not-found errors — these never trigger an API call.
"""

import difflib
import logging
import re
from typing import List, Optional, Tuple

from google.api_core import exceptions as gcp_exceptions
from google.auth import exceptions as auth_exceptions

from gcpath.core import GCPathError, ResourceNotFoundError, path_escape

logger = logging.getLogger(__name__)

ADC_LOGIN_HELP = "Run `gcloud auth application-default login` to authenticate"
_SERVICE_DISABLED_MARKERS = (
    "service_disabled",
    "has not been used in project",
    "it is disabled",
)
_QUOTED_TOKEN = re.compile(r"'([^']+)'")
_NOT_FOUND_SUFFIX = re.compile(r"not found:\s*(\S+)", re.IGNORECASE)
_SERVICE_NAME = re.compile(r"([a-z][a-z0-9-]+\.googleapis\.com)")


def _extract_query(message: str) -> Optional[str]:
    """Pull the resource/path the user asked for out of a not-found message."""
    match = _QUOTED_TOKEN.search(message)
    if match:
        return match.group(1)
    match = _NOT_FOUND_SUFFIX.search(message)
    if match:
        return match.group(1).rstrip(".,;:")
    return None


def _cached_candidates() -> List[str]:
    """Collect known paths and resource names from the local cache.

    Reads the cache even if stale — suggestions are advisory, not authoritative.
    """
    from gcpath.cache import read_cache_unchecked

    hierarchy = read_cache_unchecked()
    if hierarchy is None:
        return []

    candidates: List[str] = []
    for org_node in hierarchy.organizations:
        candidates.append("//" + path_escape(org_node.organization.display_name))
        candidates.append(org_node.organization.name)
    for folder in hierarchy.folders:
        candidates.append(folder.path)
        candidates.append(folder.name)
    for project in hierarchy.projects:
        candidates.append(project.path)
        candidates.append(f"projects/{project.project_id}")
    return candidates


def suggest_similar(query: str, n: int = 3) -> List[str]:
    """Return up to n cached paths/resource names similar to query."""
    candidates = _cached_candidates()
    if not candidates:
        return []
    try:
        return difflib.get_close_matches(query, candidates, n=n, cutoff=0.6)
    except Exception:
        logger.debug("Suggestion lookup failed", exc_info=True)
        return []


def _not_found_help(message: str) -> List[str]:
    query = _extract_query(message)
    suggestions = suggest_similar(query) if query else []
    if suggestions:
        return [f"Did you mean: {s}" for s in suggestions]
    return [
        "Run `gcpath ls -R` to list known resources",
        "Run `gcpath find <pattern>` to search by name",
    ]


def _is_service_disabled(e: Exception) -> bool:
    text = str(e).lower()
    return any(marker in text for marker in _SERVICE_DISABLED_MARKERS)


def describe_error(e: Exception) -> Tuple[str, List[str]]:
    """Map an exception to (message, help_lines) for AXI-style error output."""
    if isinstance(e, ResourceNotFoundError):
        return str(e), _not_found_help(str(e))

    if isinstance(e, GCPathError):
        return str(e), []

    if isinstance(e, auth_exceptions.RefreshError):
        return (
            "Google Cloud credentials are expired or revoked.",
            [ADC_LOGIN_HELP],
        )

    if isinstance(e, auth_exceptions.DefaultCredentialsError):
        return (
            "No Google Cloud credentials found (Application Default Credentials).",
            [
                ADC_LOGIN_HELP,
                "See https://cloud.google.com/docs/authentication/provide-credentials-adc",
            ],
        )

    if isinstance(e, gcp_exceptions.PermissionDenied):
        if _is_service_disabled(e):
            # Attribute to the service named in the message; default to the
            # Cloud Asset API since it is the default API mode.
            match = _SERVICE_NAME.search(str(e))
            service = match.group(1) if match else "cloudasset.googleapis.com"
            if service == "cloudasset.googleapis.com":
                return (
                    "Cloud Asset API is disabled for your project.",
                    [
                        "Run `gcloud services enable cloudasset.googleapis.com` to enable it",
                        "Or retry with `-U` to use the Resource Manager API instead",
                    ],
                )
            return (
                f"{service} is disabled for your project.",
                [f"Run `gcloud services enable {service}` to enable it"],
            )
        return (
            "Permission Denied. Ensure you have the required permissions and are authenticated.",
            [
                ADC_LOGIN_HELP,
                "If using the Cloud Asset API (default), retry with `-U` for the Resource Manager API",
            ],
        )

    if isinstance(e, gcp_exceptions.ServiceUnavailable):
        return (
            "The GCP API is currently unreachable.",
            [
                "Check network connectivity and proxy settings",
                "Run `gcpath cache status` to see if cached data is available",
            ],
        )

    return f"Unexpected error: {e}", []


def is_unexpected(e: Exception) -> bool:
    """True when the exception has no specific mapping (warrants a logged traceback)."""
    return not isinstance(
        e,
        (
            GCPathError,
            auth_exceptions.GoogleAuthError,
            gcp_exceptions.GoogleAPICallError,
        ),
    )
