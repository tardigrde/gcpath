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
- **Dual Mode**:
  - **Cloud Asset API (Default)**: Fast, bulk loading using GCP Cloud Asset Inventory.
  - **Resource Manager API**: Iterative loading using standard Resource Manager API (slower, but different permissions).

### Roadmap

- caching, for lightning fast lookups
- diagram generation
- entrypoint configuration (organization or folder)
- IAM policies
- other resources

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

- `-L, --level N`: Limit depth of the tree (no limit by default).
- `-i, --ids`: Include resource IDs in the output.
- `-y, --yes`: Skip confirmation prompts for large hierarchy loads.

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

## Acknowledgments

Thanks for [xebia/gcp-path](https://github.com/xebia/gcp-path) for the inspiration!

## License

[MIT](./LICENSE)
