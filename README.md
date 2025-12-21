# gcpath

`gcpath` is a CLI utility to manage Google Cloud Platform resource hierarchy paths.
It helps you translate between GCP resource names (e.g., `folders/12345`) and human-readable paths (e.g., `//example.com/department/team`).

## Features

- **Recursive Listing**: List all folders in your organization as paths.
- **Path Resolution**: Get the resource name (ID) for a given path.
- **Reverse Lookup**: Get the path for a given resource name (ID).
- **Tree Visualization**: View your hierarchy as a tree with depth limits.
- **Dual Mode**:
    - **Cloud Asset API (Default)**: Fast, bulk loading using GCP Cloud Asset Inventory.
    - **Resource Manager API**: Iterative loading using standard Resource Manager API (slower, but different permissions).

## Quick Start

After installation, ensure you are authenticated with Google Cloud and have the necessary permissions.

```bash
# List all resources
gcpath ls

# List children of a specific folder
gcpath ls folders/123456789

# Find ID of a specific path
gcpath name //example.com/engineering

# Find path of a specific resource ID
gcpath path folders/123456789

# View tree rooted at organization
gcpath tree

# View tree rooted at folder
gcpath tree folders/123456789
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

Examples:
```bash
# List all organizations and their top-level children
gcpath ls

# List all contents of an organization recursively
gcpath ls -R

# List children of a specific folder
gcpath ls folders/123456789
```

### Tree View (`tree`)

Visualize the resource hierarchy in a tree format.

```bash
gcpath tree [RESOURCE_NAME]
```

Options:
- `-L, --level N`: Limit depth of the tree (max 3).
- `-i, --ids`: Include resource IDs in the output.

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

## Authentication

`gcpath` uses [Google Cloud Application Default Credentials (ADC)](https://cloud.google.com/docs/authentication/provide-credentials-adc).

1. Install [gcloud CLI](https://cloud.google.com/sdk/docs/install).
2. Authenticate:
   ```bash
   gcloud auth application-default login
   ```

## Permissions

- **Cloud Asset API**: `cloudasset.assets.searchAllResources` on the Organization.
- **Resource Manager API**: `resourcemanager.folders.list` and `resourcemanager.projects.get`.

## License

MIT
