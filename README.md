# gcpath

`gcpath` is a CLI utility to manage Google Cloud Platform resource hierarchy paths.
It helps you translate between GCP resource names (e.g., `folders/12345`) and human-readable paths (e.g., `//example.com/department/team`).

## Features

- **Recursive Listing**: List all folders in your organization as paths.
- **Path Resolution**: Get the resource name (ID) for a given path.
- **Reverse Lookup**: Get the path for a given resource name (ID).
- **Dual Mode**:
    - **Cloud Asset API (Default)**: Fast, bulk loading using GCP Cloud Asset Inventory.
    - **Resource Manager API**: Iterative loading using standard Resource Manager API (slower, but different permissions).

## Installation

```bash
pip install gcpath
# or with uv
uv tool install gcpath
```

## Usage

### List Folders

Recursively list all folders in your organization(s):

```bash
gcpath ls
```

Output:
```
//example.com/engineering
//example.com/engineering/backend
//example.com/sales
...
```

You can also filter by organization display name:

```bash
gcpath ls "example.com"
```

### Get Resource Name

Get the GCP resource name (e.g., `folders/123`) from a path:

```bash
gcpath name //example.com/engineering/backend
# Output: folders/987654321
```

To get just the ID:

```bash
gcpath name --id //example.com/engineering/backend
# Output: 987654321
```

### Get Path

Get the path from a resource name:

```bash
gcpath path folders/987654321
# Output: //example.com/engineering/backend
```

### Modes

By default, `gcpath` uses the Cloud Asset API which is faster for large hierarchies.
To force using the Resource Manager API (iterative), use the `-U` / `--no-use-asset-api` flag:

```bash
gcpath ls -U
```

## Permissions

### Cloud Asset API (Default)
Requires `cloudasset.assets.searchAllResources` permission on the Organization.

### Resource Manager API
Requires `resourcemanager.folders.list` on the Organization and folders.

## Development

Prerequisites: `uv` (https://github.com/astral-sh/uv).

1. Clone the repository.
2. Install dependencies:
   ```bash
   uv sync
   ```
3. Run tests:
   ```bash
   uv run pytest
   ```

## License

MIT
