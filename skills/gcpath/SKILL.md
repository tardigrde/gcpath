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
license: MIT
compatibility: >
  Requires gcpath CLI (pip install gcpath or uvx gcpath) and GCP Application
  Default Credentials (gcloud auth application-default login or
  GOOGLE_APPLICATION_CREDENTIALS env var).
allowed-tools: Bash(gcpath:*) Bash(uvx gcpath:*)
metadata:
  author: tardigrde
  repository: https://github.com/tardigrde/gcpath
---

# gcpath

A read-only CLI for querying GCP resource hierarchy paths. Translates between
GCP resource names (`folders/12345`) and human-readable paths
(`//example.com/dept/team`) and lets you explore the org → folder → project
tree.

## When to Use

**Use gcpath when asked to:**

- List folders or projects inside a GCP folder or organization
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

## Running gcpath

Prefer the bare command if gcpath is already installed:

```bash
gcpath <command>
```

If not installed, use uvx (no install required):

```bash
uvx gcpath <command>
```

**Required IAM role** (on the org or target scope): `roles/cloudasset.viewer`
(default API mode), or `roles/resourcemanager.folderViewer` +
`roles/resourcemanager.projectViewer` (with `-U` flag).

## Core Concepts

- **Resource names**: `organizations/123`, `folders/456`, `projects/789` or `projects/my-project-id`
- **Paths**: `//example.com/Department/Team` — double-slash prefix, then org domain, then slash-separated display names
- **Organizationless projects**: shown with `//_/` prefix (no org parent)
- **Entrypoint**: a persistent default root resource (`gcpath config set-entrypoint folders/123`)

## Common Workflows

### Find which folder/org a project belongs to

```bash
gcpath path projects/my-project
gcpath ancestors projects/my-project   # full chain with display names
```

### List all projects in a folder

```bash
gcpath ls folders/123 -R --type project
```

### Convert a path to a resource name (e.g. for gcloud/Terraform)

```bash
gcpath name //example.com/Engineering/Backend
# → folders/456789
```

### Search by display name

```bash
gcpath find "*payments*" --type project
gcpath find "prod-*" folders/123        # scoped to a subtree
```

### Explore a subtree

```bash
gcpath tree folders/123 -L 3 -i        # tree, depth 3, show resource IDs
gcpath ls folders/123 -R -L 2          # flat list, depth 2
```

### Machine-readable output

```bash
gcpath --json ls -R | jq '.[] | .path'
gcpath --yaml ancestors projects/my-project
```

### Filter by GCP labels or tags

```bash
gcpath ls -R --label env=production --label team=platform
gcpath find "*" --tag cost-center=eng
```

## Key Flags (most commands)

| Flag | Short | Description |
|------|-------|-------------|
| `--json` / `--yaml` | | Structured output (global) |
| `--force-refresh` | `-F` | Bypass cache, re-fetch from GCP |
| `--recursive` | `-R` | List all descendants (`ls` only) |
| `--level N` | `-L` | Max depth |
| `--type TYPE` | `-t` | Filter: `folder`, `project`, `organization` |
| `--no-use-asset-api` | `-U` | Use Resource Manager API instead |

For the full flag reference, read [`references/commands.md`](references/commands.md).

## Gotchas

- `tree`, `diagram`, `stats` do not accept projects as starting point (leaf nodes).
- Organizationless projects appear under `//_/` in paths.
- `--label` / `--tag` filters are ANDed when repeated.
- `gcpath path` and `gcpath ancestors` hit the GCP API directly — no cache needed, always fast.
- Scoped loads (`gcpath ls folders/123`) are not cached unless that folder is the configured entrypoint.
- Use `-U` if you get "Cloud Asset API not enabled" errors.
