"""
Asset API response parsing utilities.

This module handles the complex parsing of GCP Asset API responses,
including STRUCT parsing, MapComposite handling, and row validation.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def clean_asset_name(name: str) -> str:
    """Strips the Asset API prefix from resource names.

    Args:
        name: Resource name from Asset API (e.g., "//cloudresourcemanager.googleapis.com/folders/123")

    Returns:
        Cleaned resource name (e.g., "folders/123")
    """
    prefix = "//cloudresourcemanager.googleapis.com/"
    if name.startswith(prefix):
        return name[len(prefix) :]
    return name


def extract_value(obj: Any) -> Any:
    """Extract value from MapComposite or dict.

    MapComposite objects from Asset API behave like dicts but aren't dict instances.
    This function handles both MapComposite and dict objects uniformly.

    Args:
        obj: MapComposite, dict, or plain value

    Returns:
        Extracted value from 'v' field, or the object itself
    """
    if hasattr(obj, "get"):
        return obj.get("v")
    elif isinstance(obj, dict):
        return obj.get("v")
    return obj


def extract_list_values(ancestors_wrapper: Any) -> List[str]:
    """Extract and clean list of ancestor values.

    Args:
        ancestors_wrapper: Wrapped list of ancestors from Asset API

    Returns:
        List of cleaned ancestor resource names
    """
    raw_ancestors_uncleaned = (
        ancestors_wrapper if isinstance(ancestors_wrapper, list) else []
    )
    return [
        clean_asset_name(str(extract_value(item))) for item in raw_ancestors_uncleaned
    ]


def parse_parent_struct(parent_col: Any) -> Optional[str]:
    """Parse parent STRUCT from Asset API response.

    The Asset API returns parent information in a nested STRUCT format:
    {"v": {"f": [{"v": "folder"}, {"v": "123"}]}}

    Args:
        parent_col: Parent column from Asset API row

    Returns:
        Parent resource name (e.g., "folders/123") or None
    """
    parent_struct_raw = extract_value(parent_col)
    if not parent_struct_raw:
        return None

    # Convert MapComposite to dict for easier access
    parent_dict = dict(parent_struct_raw) if hasattr(parent_struct_raw, "keys") else {}

    # Handle nested STRUCT format: {"f": [{"v": type}, {"v": id}]}
    if (
        "f" in parent_dict
        and hasattr(parent_dict["f"], "__len__")
        and len(parent_dict["f"]) >= 2
    ):
        struct_fields = parent_dict["f"]

        type_val = extract_value(struct_fields[0])
        id_val = extract_value(struct_fields[1])

        if type_val and id_val:
            parent_type_plural = (
                f"{type_val}s" if not type_val.endswith("s") else type_val
            )
            return f"{parent_type_plural}/{id_val}"

    return None


def validate_row_structure(row: Any, expected_columns: int, row_type: str) -> bool:
    """Validate Asset API row structure.

    Args:
        row: Row from Asset API response
        expected_columns: Expected number of columns
        row_type: Type of row for error messages (e.g., "project", "folder")

    Returns:
        True if valid, False otherwise
    """
    try:
        row_dict = dict(row)
        if "f" not in row_dict:
            logger.warning(f"Missing 'f' field in {row_type} row")
            return False

        f_list = row_dict["f"]
        if len(f_list) < expected_columns:
            logger.warning(
                f"Unexpected number of columns in Asset API {row_type} row: "
                f"expected {expected_columns}, got {len(f_list)}"
            )
            return False

        return True
    except (TypeError, AttributeError) as e:
        logger.warning(f"Error validating {row_type} row structure: {e}")
        return False


def parse_project_row(row: Any) -> Dict[str, Any]:
    """Parse a project row from Asset API.

    Expected columns: name, projectNumber, projectId, parent (STRUCT), ancestors

    Args:
        row: Project row from Asset API response

    Returns:
        Dict with keys: name, project_id, display_name, parent, ancestors

    Raises:
        ValueError: If row structure is invalid
    """
    if not validate_row_structure(row, 5, "project"):
        raise ValueError("Invalid project row structure")

    row_dict = dict(row)
    f_list = row_dict["f"]

    # Extract columns: 0=name, 1=projectNumber, 2=projectId, 3=parent, 4=ancestors
    name_val = extract_value(f_list[0])
    project_id = extract_value(f_list[2])
    parent_from_api = parse_parent_struct(f_list[3])
    ancestors_wrapper = extract_value(f_list[4])

    name = clean_asset_name(str(name_val))
    raw_ancestors = extract_list_values(ancestors_wrapper)

    logger.debug(
        f"Parsed project from Asset API: project_id={project_id}, name={name}, "
        f"parent_from_api={parent_from_api}, ancestors={raw_ancestors}"
    )

    return {
        "name": name,
        "project_id": str(project_id),
        "display_name": str(project_id),  # Use projectId as displayName
        "parent": parent_from_api,
        "ancestors": raw_ancestors,
    }


def parse_folder_row(row: Any) -> Dict[str, Any]:
    """Parse a folder row from Asset API.

    Expected columns: name, displayName, parent, ancestors

    Args:
        row: Folder row from Asset API response

    Returns:
        Dict with keys: name, display_name, parent, ancestors

    Raises:
        ValueError: If row structure is invalid or missing required fields
    """
    if not validate_row_structure(row, 4, "folder"):
        raise ValueError("Invalid folder row structure")

    row_dict = dict(row)
    f_list = row_dict["f"]

    # Extract columns: 0=name, 1=displayName, 2=parent, 3=ancestors
    name_val = extract_value(f_list[0])
    display_name = extract_value(f_list[1])
    parent_val = extract_value(f_list[2])
    ancestors_wrapper = extract_value(f_list[3])

    if not name_val or not display_name:
        raise ValueError("Missing name or display_name in folder row")

    name = clean_asset_name(str(name_val))
    parent = str(parent_val) if parent_val else None
    raw_ancestors = extract_list_values(ancestors_wrapper)

    logger.debug(
        f"Parsed folder from Asset API: name={name}, display_name={display_name}, "
        f"parent={parent}, ancestors={raw_ancestors}"
    )

    return {
        "name": name,
        "display_name": display_name,
        "parent": parent,
        "ancestors": raw_ancestors,
    }


def build_folder_ancestors(
    name: str,
    raw_ancestors: List[str],
    parent: str,
    loaded_folders: Dict[str, Any],
    org_name: str,
) -> List[str]:
    """Build complete ancestor chain for a folder.

    Ensures consistency with _load_folders_rm structure: [self, parent, ..., org]

    Args:
        name: Folder resource name
        raw_ancestors: Ancestor list from Asset API (may be incomplete)
        parent: Parent resource name
        loaded_folders: Dict of already loaded folders (for traversal)
        org_name: Organization resource name

    Returns:
        Complete ancestor chain from folder to organization
    """
    # Ensure ancestors start with self
    if not raw_ancestors or raw_ancestors[0] != name:
        ancestors = [name] + raw_ancestors
    else:
        ancestors = raw_ancestors

    # If we have empty or single-item ancestors, build the full chain
    if not ancestors or (len(ancestors) == 1 and ancestors[0] == name):
        ancestors = [name]
        current_parent = parent

        # Traverse up the parent chain
        while current_parent and current_parent.startswith("folders/"):
            ancestors.append(current_parent)

            # Check if this parent is already loaded
            if current_parent in loaded_folders:
                parent_folder = loaded_folders[current_parent]
                # Add remaining ancestors from the parent (excluding duplicates)
                for anc in parent_folder.ancestors:
                    if anc != current_parent and anc not in ancestors:
                        ancestors.append(anc)
                break
            else:
                # Parent not loaded yet, add org and break
                ancestors.append(org_name)
                break

        # If we didn't find any folders in the chain, add org
        if len(ancestors) == 1 or (
            len(ancestors) > 1 and not ancestors[-1].startswith("organizations/")
        ):
            ancestors.append(org_name)

    return ancestors
