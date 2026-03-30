---
name: gcpath
description: >
  Use this skill when you need to navigate, query, or resolve resources in a
  Google Cloud Platform (GCP) organization hierarchy — listing folders or
  projects under a resource, converting between resource names (e.g.
  folders/12345) and human-readable paths (e.g. //example.com/dept/team),
  searching resources by display name, showing ancestry chains, or generating
  hierarchy diagrams. Do NOT use for IAM policy, billing, cost analysis,
  Kubernetes, or Compute Engine resources.
---

# gcpath

A CLI for querying GCP resource hierarchy paths. It translates between GCP
resource names (`folders/12345`) and human-readable paths (`//example.com/dept/team`)
and lets you explore the org → folder → project tree.

## When to Use

**Use gcpath when asked to:**

- List what folders or projects are inside a GCP folder or organization
- Find the hierarchy path of a project or folder
- Convert a human-readable path to a GCP resource name (for use in `gcloud`, Terraform, etc.)
- Search for a project or folder by display name
- Show the ancestry chain of any resource
- Generate a Mermaid or D2 diagram of the resource hierarchy
- Count folders and projects under a scope

**Do NOT use gcpath for:**

- IAM policy management (`gcloud projects get-iam-policy` is the right tool)
- Billing or cost queries
- Compute, GKE, Cloud Run, or other product-level resources
- Resource creation or modification (gcpath is read-only)

## Installation

```bash
pip install gcpath
# or
uv add gcpath
```

**Authentication** — gcpath uses Application Default Credentials. Authenticate with:

```bash
gcloud auth application-default login
```

Or set `GOOGLE_APPLICATION_CREDENTIALS` to a service account key file.

**Required IAM roles** (on the org or target scope):

- `roles/resourcemanager.organizationViewer`
- `roles/resourcemanager.folderViewer`
- `roles/resourcemanager.projectViewer`
- Or: `roles/cloudasset.viewer` (Cloud Asset API mode, the default)

## Core Concepts

- **Resource names**: `organizations/123`, `folders/456`, `projects/789` or `projects/my-project-id`
- **Paths**: `//example.com/Department/Team` — double-slash prefix, then org domain, then slash-separated display names
- **Organizationless projects**: shown with `//_/` prefix (no org parent)
- **Entrypoint**: a default root resource to scope all commands to (set once, used implicitly)

## Commands

### List children: `ls`

```bash
gcpath ls                          # all orgs/projects you have access to
gcpath ls folders/123              # direct children of a folder
gcpath ls folders/123 -R           # all descendants, recursively
gcpath ls folders/123 -R -L 2      # recursive, max 2 levels deep
gcpath ls folders/123 -l           # long format: show resource names alongside paths
gcpath ls folders/123 --type project          # only projects
gcpath ls folders/123 --label env=production  # filter by GCP label
gcpath ls folders/123 --tag cost-center=eng   # filter by GCP tag
gcpath ls folders/123 --show-labels --show-tags  # show labels/tags in output
```

### Tree view: `tree`

```bash
gcpath tree                        # full hierarchy tree
gcpath tree folders/123            # subtree from a folder
gcpath tree folders/123 -L 3       # limit depth
gcpath tree folders/123 -i         # show resource names alongside display names
gcpath tree folders/123 --type project   # only show projects
gcpath tree -y                     # skip confirmation for large loads
```

### Diagram: `diagram`

```bash
gcpath diagram                     # Mermaid diagram of full hierarchy
gcpath diagram folders/123         # diagram of a subtree
gcpath diagram -f d2               # D2 format instead of Mermaid
gcpath diagram -o hierarchy.mmd    # write to file
gcpath diagram folders/123 -L 2    # limit depth
```

### Statistics: `stats`

```bash
gcpath stats                       # count orgs, folders, projects globally
gcpath stats folders/123           # count within a folder subtree
gcpath stats organizations/456
```

### Resolve path → resource name: `name`

```bash
gcpath name //example.com/Department/Team
gcpath name //example.com/Department/Team --id   # print only the numeric ID
gcpath name //example.com/Dept/A //example.com/Dept/B  # multiple paths
```

### Resolve resource name → path: `path`

```bash
gcpath path folders/123
gcpath path projects/my-project
gcpath path folders/123 folders/456  # multiple resources
```

### Search by display name: `find`

```bash
gcpath find "data-*"               # glob pattern, case-insensitive
gcpath find "*team*" folders/123   # scoped to a subtree
gcpath find "prod-*" --type project
gcpath find "*" --label env=production  # find all labeled resources
```

### Ancestry chain: `ancestors`

```bash
gcpath ancestors projects/my-project
gcpath ancestors folders/123
```

### Cache management

```bash
gcpath cache status   # show cache age, size, scope
gcpath cache clear    # force next run to re-fetch from GCP
```

### Configuration

```bash
gcpath config set-entrypoint folders/123  # always scope to this folder by default
gcpath config show                         # display current config
gcpath config clear-entrypoint
```

## Global Flags

These apply to any command:

| Flag | Short | Description |
|------|-------|-------------|
| `--entrypoint RESOURCE` | `-e` | Default scope for this invocation |
| `--json` | | Output as JSON |
| `--yaml` | | Output as YAML |
| `--force-refresh` | `-F` | Bypass cache, re-fetch from GCP API |
| `--no-use-asset-api` | `-U` | Use Resource Manager API instead of Cloud Asset API |
| `--debug` | | Enable debug logging |

## Common Workflows

### 1. Find which folder a project lives in

```bash
gcpath ancestors projects/my-project
# or
gcpath path projects/my-project
```

### 2. List all projects in a folder

```bash
gcpath ls folders/123 -R --type project
```

### 3. Get the resource name for a path (e.g. to use in gcloud)

```bash
gcpath name //example.com/Engineering/Backend
# → folders/456789
gcloud projects list --filter="parent.id=456789"
```

### 4. Search for a project by display name

```bash
gcpath find "*payments*" --type project
```

### 5. Explore a subtree visually

```bash
gcpath tree folders/123 -L 3 -i
```

### 6. Generate a diagram for docs

```bash
gcpath diagram folders/123 -f mermaid -o team-hierarchy.mmd
```

### 7. Filter resources by label

```bash
gcpath ls --label env=production --label team=platform -R
```

## Output Formats

By default, output is formatted for terminal readability (using Rich). For
programmatic use:

```bash
gcpath ls folders/123 --json | jq '.[] | .path'
gcpath tree folders/123 --yaml
gcpath ancestors projects/my-project --json
```

## API Modes

| Mode | Flag | Speed | Permissions needed |
|------|------|-------|--------------------|
| Cloud Asset API | (default) | Fast — bulk SQL queries | `roles/cloudasset.viewer` |
| Resource Manager | `-U` | Slower — iterative paging | `roles/resourcemanager.*Viewer` |

Use `-U` if the Cloud Asset API is not enabled in the project or if you lack the Asset Viewer role.

## Caching

gcpath caches hierarchy data locally to avoid repeated API calls. The cache is
scoped to the resource used. Use `-F` / `--force-refresh` to bypass it, or
`gcpath cache clear` to wipe it.

## Gotchas

- `tree`, `diagram`, `stats` do not support starting from a project (projects are leaf nodes).
- Organizationless projects appear under `//_/` in paths.
- `--label` and `--tag` filters are ANDed together when repeated.
- `gcpath path` resolves without loading the full hierarchy (it uses the GCP ancestry API directly) — it's fast even without cache.
- Scoped loads (`gcpath ls folders/123`) are faster and not cached by default unless `folders/123` is also the configured entrypoint.

## Reference

See [`references/commands.md`](references/commands.md) for a compact flag reference per command.
