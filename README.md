# gcpath

`gcpath` is a CLI utility to query Google Cloud Platform resource hierarchy paths.
It helps you translate between GCP resource names (e.g., `folders/12345`) and human-readable paths (e.g., `//example.com/department/team`).

## Why should I use gcpath?

- familiar linux-like CLI
- you can stay in the terminal for quick resource hierarchy lookups
- no need to learn the complex `gcloud` interface
- look-up only commands, so coding agents can't do harm using it

## Features

- **Tree Visualization**: View your hierarchy as a tree.
- **Recursive Listing**: List all folders and projects in your organization as paths.
- **Path Resolution**: Get the resource name (ID) for a given path.
- **Reverse Lookup**: Get the path for a given resource name (ID).
- **Find**: Search for resources by name using glob patterns.
- **Ancestors**: Show the full ancestry chain from any resource up to the org root.
- **Type Filtering**: Filter `ls`, `tree`, and `find` output by resource type (folder, project, organization).
- **Structured Output**: `--json` and `--yaml` flags for machine-readable output across all commands.
- **Dual Mode**:
  - **Cloud Asset API (Default)**: Fast, bulk loading using GCP Cloud Asset Inventory.
  - **Resource Manager API**: Iterative loading using standard Resource Manager API (slower, but different permissions).

## Installation

```bash
pipx install gcpath
# or
pip install gcpath
# or
uv tool install gcpath
```

## Prerequisites

### Authentication

`gcpath` uses [Google Cloud Application Default Credentials (ADC)](https://cloud.google.com/docs/authentication/provide-credentials-adc).

1. Install [gcloud CLI](https://cloud.google.com/sdk/docs/install).
2. Authenticate:

   ```bash
   gcloud auth application-default login
   ```

### Permissions

Ensure you have enough permissions on your entrypoint (organization or folder), see [API modes](#api-modes).

### Quick Start

```bash
# List all resources
gcpath ls

# List children of a specific folder
gcpath ls folders/123456789

# List only folders, recursively, up to depth 2
gcpath ls -R --type folder -L 2

# Find resources by name pattern
gcpath find "*prod*"

# Show ancestry chain of a resource
gcpath ancestors projects/my-project

# Find ID of a specific path
gcpath name //example.com/engineering

# Find path of a specific resource ID
gcpath path folders/123456789

# View tree rooted at organization
gcpath tree

# View tree rooted at folder
gcpath tree folders/123456789

# Generate a Mermaid diagram of the hierarchy
gcpath diagram

# Generate a D2 diagram scoped to a folder
gcpath diagram folders/123456789 --format d2

# Machine-readable output
gcpath --json ls -R
gcpath --yaml tree -L 2
```

## Usage

### List Resources (`ls`)

List folders and projects. Defaults to the organization root.

```bash
gcpath ls [RESOURCE_NAME]
```

Options:

- `-l, --long`: Show resource IDs and numbers (for projects).
- `-R, --recursive`: List resources recursively.
- `-t, --type TYPE`: Filter by resource type: `folder`, `project`, `organization`.
- `-L, --level N`: Limit depth for recursive listing (requires `-R`).

Examples:

```bash
# List all organizations and their top-level children
gcpath ls

# List all contents of an organization recursively
gcpath ls -R

# List children of a specific folder
gcpath ls folders/123456789

# List only folders, recursively
gcpath ls -R --type folder

# Recursive listing limited to depth 2
gcpath ls -R -L 2
```

### Tree View (`tree`)

Visualize the resource hierarchy in a tree format.

```bash
gcpath tree [RESOURCE_NAME]
```

Options:

- `-L, --level N`: Limit depth of the tree (no limit by default).
- `-i, --ids`: Include resource IDs in the output.
- `-t, --type TYPE`: Filter by resource type: `folder`, `project`.
- `-y, --yes`: Skip confirmation prompts for large hierarchy loads.

### Generate Diagram (`diagram`)

Generate a [Mermaid](https://mermaid.js.org/) or [D2](https://d2lang.com/) diagram of the resource hierarchy.

```bash
gcpath diagram [RESOURCE_NAME]
```

Options:

- `-f, --format FORMAT`: Output format: `mermaid` (default) or `d2`.
- `-L, --level N`: Limit depth of the diagram.
- `-i, --ids`: Include resource IDs in node labels.
- `-o, --output FILE`: Write diagram to a file instead of stdout.
- `-y, --yes`: Skip confirmation prompts for large hierarchy loads.

Examples:

```bash
# Generate Mermaid diagram of the full hierarchy
gcpath diagram

# Generate D2 diagram scoped to a folder
gcpath diagram folders/123456789 --format d2

# Save Mermaid diagram to a file with depth limit
gcpath diagram -L 3 -o hierarchy.mmd

# Include resource IDs in labels
gcpath diagram --ids
```

### Get Resource Name (`name`)

Get the GCP resource name (e.g., `folders/123`) from a path:

```bash
gcpath name //example.com/engineering/backend
```

To get just the ID:

```bash
gcpath name --id //example.com/engineering/backend
```

### Get Path (`path`)

Get the path from a resource name:

```bash
gcpath path folders/987654321
```

### Find Resources (`find`)

Search for resources by display name using glob patterns.

```bash
gcpath find PATTERN [RESOURCE]
```

Options:

- `-t, --type TYPE`: Filter by resource type: `folder`, `project`, `organization`.

The optional `RESOURCE` argument scopes the search to a subtree.

Examples:

```bash
# Find all resources with "prod" in the name
gcpath find "*prod*"

# Find only projects matching a pattern
gcpath find --type project "*backend*"

# Search within a specific folder
gcpath find "team-*" folders/123456789

# Case-insensitive by default
gcpath find "*STAGING*"
```

### Show Ancestry (`ancestors`)

Show the full ancestry chain from a resource up to the organization root. Uses direct API calls without loading the full hierarchy.

```bash
gcpath ancestors RESOURCE_NAME
```

Examples:

```bash
# Show ancestry of a project
gcpath ancestors projects/my-project

# Show ancestry of a folder
gcpath ancestors folders/123456789

# JSON output for scripting
gcpath --json ancestors projects/my-project
```

### Structured Output (`--json`, `--yaml`)

All commands support `--json` and `--yaml` global flags for machine-readable output:

```bash
# JSON output
gcpath --json ls -R
gcpath --json tree -L 2
gcpath --json find "*prod*"
gcpath --json ancestors projects/my-project
gcpath --json name //example.com/engineering
gcpath --json path folders/123456789

# YAML output
gcpath --yaml ls
gcpath --yaml tree
```

The flags are mutually exclusive. Structured output goes to stdout with status messages redirected to stderr, so it's safe to pipe:

```bash
gcpath --json ls -R | jq '.[] | select(.type == "project")'
```

## API Modes

gcpath supports two GCP APIs for loading resource hierarchy data:

### Cloud Asset API (Default - Recommended)

Fast bulk loading via Cloud Asset Inventory. Recommended for most users.

```bash
# Use Cloud Asset API (default)
gcpath ls
gcpath ls --use-asset-api  # explicit
gcpath ls -u               # short form
```

**Advantages:**

- 5-6x faster than Resource Manager API
- Supports scoped loading (`ls folders/123`, `tree folders/123`)
- Efficient for large hierarchies (1000+ folders)

**Required Permissions:**

- `cloudasset.assets.searchAllResources`
- `resourcemanager.organizations.get`
- `resourcemanager.folders.get`
- `resourcemanager.projects.get`

**Setup:** Requires Cloud Asset API to be enabled: `gcloud services enable cloudasset.googleapis.com`

### Resource Manager API

Traditional recursive API calls. Use when Cloud Asset API is not available.

```bash
# Use Resource Manager API
gcpath ls --no-use-asset-api
gcpath ls -U  # short form
```

**Advantages:**

- Works without Cloud Asset API enabled
- Simpler permission model
- Standard `resourcemanager.*` permissions

**Required Permissions:**

- `resourcemanager.organizations.get`
- `resourcemanager.folders.list`
- `resourcemanager.projects.list`
- `resourcemanager.projects.get`

### Which Should I Use?

- **For most users:** Use the default (Cloud Asset API) for best performance
- **If you get permission/API errors:** Use `-U` flag for Resource Manager API

## Entrypoint Configuration

If you're a folder admin without organization-level access, or simply want to focus on a specific part of the hierarchy, you can configure an **entrypoint**. This scopes all commands to a subtree, improving performance and relevance.

### Setting an Entrypoint

```bash
# Set a default entrypoint (persisted in ~/.gcpath/config.json)
gcpath config set-entrypoint folders/123456789

# Show current configuration
gcpath config show

# Remove the entrypoint
gcpath config clear-entrypoint
```

### One-off Override

Use the `--entrypoint` / `-e` flag to override the configured entrypoint for a single command:

```bash
gcpath -e folders/987654321 ls
gcpath -e folders/987654321 tree
```

### Behavior

- When an entrypoint is set, commands like `ls`, `tree`, `diagram`, and `name` automatically scope to that resource.
- Passing an explicit resource argument overrides the entrypoint:

  ```bash
  gcpath ls folders/555  # uses folders/555, not the configured entrypoint
  ```

- The cache is **scope-aware**: cached data stores which entrypoint it was built for. Changing the entrypoint automatically invalidates the cache and triggers a fresh load.

## Python API

In addition to the CLI, `gcpath` can be used as a Python library. See the [Installation](#installation) section; for `uv` projects, you may prefer `uv add gcpath`.

### Basic Usage

```python
from gcpath import Hierarchy

# Load the full GCP resource hierarchy
# The faster Cloud Asset API is recommended (requires `cloudasset.googleapis.com` enabled).
hierarchy = Hierarchy.load(via_resource_manager=False)

# Alternatively, use the default Resource Manager API. It's slower but has simpler permissions.
# hierarchy = Hierarchy.load()

# Iterate over organizations, folders, and projects
for org_node in hierarchy.organizations:
    print(org_node.organization.display_name)  # e.g. "example.com"

for folder in hierarchy.folders:
    print(folder.path)  # e.g. "//example.com/engineering/backend"

for project in hierarchy.projects:
    print(project.path, project.project_id)  # e.g. "//example.com/my-project", "my-project"
```

### Path ↔ Resource Name Conversion

```python
from gcpath import Hierarchy

hierarchy = Hierarchy.load(via_resource_manager=False)

# Path → resource name
resource_name = hierarchy.get_resource_name("//example.com/engineering/backend")
print(resource_name)  # e.g. "folders/123456789"

# Resource name → path
path = hierarchy.get_path_by_resource_name("folders/123456789")
print(path)  # e.g. "//example.com/engineering/backend"

# Works for organizations and projects too
org_path = hierarchy.get_path_by_resource_name("organizations/111111111")
project_path = hierarchy.get_path_by_resource_name("projects/my-project-id")
```

### Lightweight Single-Resource Lookup

When you only need the path for one resource, `resolve_ancestry()` traverses up the hierarchy via individual API calls — no full hierarchy load required:

```python
from gcpath import Hierarchy

path = Hierarchy.resolve_ancestry("folders/123456789")
print(path)  # e.g. "//example.com/engineering/backend"
```

### Scoped Loading

For large hierarchies or restricted access, scope the load to a specific folder or organization:

```python
from gcpath import Hierarchy

# Load only the subtree under a specific folder (recursive)
hierarchy = Hierarchy.load(
    via_resource_manager=False,
    scope_resource="folders/123456789",
    recursive=True,
)

# Load only direct children of a folder
hierarchy = Hierarchy.load(
    via_resource_manager=False,
    scope_resource="folders/123456789",
    recursive=False,
)
```

### Error Handling

```python
from gcpath import Hierarchy, GCPathError, ResourceNotFoundError, PathParsingError

try:
    hierarchy = Hierarchy.load(via_resource_manager=False)
    name = hierarchy.get_resource_name("//example.com/nonexistent/path")
except ResourceNotFoundError as e:
    print(f"Resource not found: {e}")
except PathParsingError as e:
    print(f"Invalid path format: {e}")
except GCPathError as e:
    print(f"gcpath error: {e}")
```

### API Reference

| Symbol | Description |
|---|---|
| `Hierarchy` | Main class. Load with `Hierarchy.load()`, then query with `get_resource_name()`, `get_path_by_resource_name()`. |
| `Hierarchy.load()` | Load the full hierarchy from GCP. Key params: `via_resource_manager`, `scope_resource`, `recursive`. |
| `Hierarchy.resolve_ancestry()` | Lightweight static method to resolve a single resource name to path. |
| `OrganizationNode` | Represents a GCP organization with its folders. |
| `Folder` | Represents a GCP folder. Has `.path`, `.name`, and `.display_name` attributes. |
| `Project` | Represents a GCP project. Has `.path`, `.project_id`, `.name`, and `.display_name` attributes. |
| `GCPathError` | Base exception class for all gcpath errors. |
| `ResourceNotFoundError` | Raised when a resource cannot be found in the hierarchy. |
| `PathParsingError` | Raised when a path string cannot be parsed. |
| `path_escape()` | URL-encodes a display name for safe use in paths. |

## Acknowledgments

Thanks for [xebia/gcp-path](https://github.com/xebia/gcp-path) for the inspiration!

## License

[MIT](./LICENSE)
