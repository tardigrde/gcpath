# gcpath Command Reference

Quick reference for all gcpath commands and flags.

## Global Flags

Apply to every command (place before the subcommand):

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--entrypoint RESOURCE` | `-e` | config/none | Scope all commands to this resource |
| `--json` | | false | JSON output |
| `--yaml` | | false | YAML output |
| `--use-asset-api / --no-use-asset-api` | `-u / -U` | true (asset) | API backend |
| `--debug` | | false | Debug logging |

---

## `ls [RESOURCE]`

List direct children (or descendants with `-R`) of a resource.

| Flag | Short | Description |
|------|-------|-------------|
| `--long` | `-l` | Show resource names alongside paths |
| `--recursive` | `-R` | List all descendants |
| `--level N` | `-L N` | Max depth (requires `-R`) |
| `--type TYPE` | `-t` | Filter: `folder`, `project`, `organization` |
| `--show-labels` | | Show GCP labels column |
| `--show-tags` | | Show GCP tags column |
| `--label KEY=VALUE` | | Filter by label (repeatable, ANDed) |
| `--tag KEY=VALUE` | | Filter by tag (repeatable, ANDed) |
| `--force-refresh` | `-F` | Bypass cache |

**Examples:**

```
gcpath ls
gcpath ls folders/123
gcpath ls folders/123 -R -L 2 --type project
gcpath ls -R --label env=prod --show-labels --json
```

---

## `tree [RESOURCE]`

Display resource hierarchy as an interactive tree.

| Flag | Short | Description |
|------|-------|-------------|
| `--level N` | `-L N` | Max display depth |
| `--ids` | `-i` | Show resource names next to display names |
| `--type TYPE` | `-t` | Filter: `folder`, `project` |
| `--yes` | `-y` | Skip confirmation for large unscoped loads |
| `--show-labels` | | Show labels in tree nodes |
| `--show-tags` | | Show tags in tree nodes |
| `--label KEY=VALUE` | | Filter by label (repeatable, ANDed) |
| `--tag KEY=VALUE` | | Filter by tag (repeatable, ANDed) |
| `--force-refresh` | `-F` | Bypass cache |

**Examples:**

```
gcpath tree
gcpath tree folders/123 -L 3 -i
gcpath tree --type project --json
```

---

## `diagram [RESOURCE]`

Generate a Mermaid or D2 diagram of the hierarchy.

| Flag | Short | Description |
|------|-------|-------------|
| `--format FORMAT` | `-f` | `mermaid` (default) or `d2` |
| `--level N` | `-L N` | Max display depth |
| `--ids` | `-i` | Show resource names in node labels |
| `--output FILE` | `-o` | Write to file instead of stdout |
| `--yes` | `-y` | Skip confirmation |
| `--force-refresh` | `-F` | Bypass cache |

**Examples:**

```
gcpath diagram folders/123
gcpath diagram -f d2 -o org.d2
gcpath diagram folders/123 -L 2 --ids
```

---

## `stats [RESOURCE]`

Count organizations, folders, and projects in scope. Resource must be `organizations/...` or `folders/...`.

| Flag | Short | Description |
|------|-------|-------------|
| `--force-refresh` | `-F` | Bypass cache |

**Examples:**

```
gcpath stats
gcpath stats folders/123
gcpath stats organizations/456
```

---

## `name PATH [PATH ...]`

Convert human-readable path(s) to GCP resource name(s).

| Flag | Short | Description |
|------|-------|-------------|
| `--id` | | Print only the numeric ID (not the full resource name) |
| `--force-refresh` | `-F` | Bypass cache |

**Examples:**

```
gcpath name //example.com/Engineering/Backend
gcpath name //example.com/Dept/Team --id
gcpath name //a.com/X //a.com/Y --json
```

---

## `path RESOURCE [RESOURCE ...]`

Convert GCP resource name(s) to human-readable path(s). Does not load full hierarchy — resolves via GCP ancestry API directly.

No extra flags (uses global `--json` / `--yaml`).

**Examples:**

```
gcpath path folders/123
gcpath path projects/my-project
gcpath path folders/123 folders/456 --json
```

---

## `find PATTERN [RESOURCE]`

Search resources by display name glob pattern (case-insensitive). Supports `*` and `?`.

| Flag | Short | Description |
|------|-------|-------------|
| `--type TYPE` | `-t` | Filter: `folder`, `project`, `organization` |
| `--label KEY=VALUE` | | Filter by label (repeatable, ANDed) |
| `--tag KEY=VALUE` | | Filter by tag (repeatable, ANDed) |
| `--force-refresh` | `-F` | Bypass cache |

**Examples:**

```
gcpath find "*payments*"
gcpath find "prod-*" --type project
gcpath find "*" folders/123 --label env=staging
gcpath find "data-*" --json
```

---

## `ancestors RESOURCE`

Show the full ancestry chain from a resource up to the organization root. Works for `organizations/...`, `folders/...`, and `projects/...`.

No extra flags (uses global `--json` / `--yaml`).

**Output columns:** Resource Name, Display Name, Type

**Examples:**

```
gcpath ancestors projects/my-project
gcpath ancestors folders/123 --json
```

---

## `cache status`

Show cache age, size, scope, and resource counts.

No flags.

---

## `cache clear`

Delete the local cache file, forcing next run to re-fetch from GCP.

No flags.

---

## `cache refresh`

Re-load the hierarchy from GCP and rewrite the cache. Respects the configured entrypoint. Useful for warming the cache out-of-band (e.g., cron) so session-start hooks serve fresh data.

No flags.

---

## `config set-entrypoint RESOURCE`

Set a persistent default entrypoint. Subsequent commands will scope to this resource unless overridden with `-e`.

**Example:**

```
gcpath config set-entrypoint folders/123
```

---

## `config show`

Display current configuration and config file location.

---

## `config clear-entrypoint`

Remove the configured default entrypoint.

---

## Resource Name Formats

| Resource | Format | Example |
|----------|--------|---------|
| Organization | `organizations/ID` | `organizations/123456789` |
| Folder | `folders/ID` | `folders/987654321` |
| Project (by number) | `projects/NUMBER` | `projects/111222333` |
| Project (by ID) | `projects/PROJECT-ID` | `projects/my-project` |

## Path Format

```
//DOMAIN/SEGMENT/SEGMENT/...
```

- `//example.com/Engineering/Backend/Services`
- `//_/OrphanedProject` (organizationless)
