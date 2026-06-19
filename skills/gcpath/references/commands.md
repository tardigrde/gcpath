# gcpath Command Reference

Quick reference for current gcpath commands and flags.

## Global Flags

Global flags apply to every command and should be placed before the subcommand.

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--entrypoint RESOURCE` | `-e` | config/none | Scope commands to an organization or folder |
| `--format FORMAT` | | `toon` | Output: `toon`, `json`, `yaml`, or `rich` |
| `--use-asset-api / --no-use-asset-api` | `-u / -U` | asset | API backend |
| `--debug` | | false | Debug logging |

## `ls [RESOURCE]`

List direct children, or descendants with `-R`.

| Flag | Short | Description |
|------|-------|-------------|
| `--recursive` | `-R` | List all descendants |
| `--level N` | `-L N` | Max depth for recursive output |
| `--type TYPE` | `-t` | `organization`, `folder`, or `project` |
| `--fields FIELDS` | | Comma-separated fields |
| `--ids` | `-i` | Include resource names |
| `--full` | | Do not truncate label/tag fields |
| `--show-labels` | | Display labels |
| `--show-tags` | | Display tags |
| `--label FILTER` | | `key`, `key=value`, or `key!=value`; repeatable |
| `--tag FILTER` | | Same syntax as `--label` |
| `--exclude GLOB` | | Exclude name or path glob; repeatable |
| `--force-refresh` | `-F` | Bypass cache |

Examples:

```bash
gcpath ls
gcpath ls folders/123
gcpath ls folders/123 -R -L 2 --type project
gcpath --format json ls -R --label env=prod --show-labels
```

## `tree [RESOURCE]`

Display hierarchy as a tree.

| Flag | Short | Description |
|------|-------|-------------|
| `--level N` | `-L N` | Max display depth |
| `--ids` | `-i` | Show resource names |
| `--type TYPE` | `-t` | `folder` or `project` |
| `--show-labels` | | Show labels |
| `--show-tags` | | Show tags |
| `--label FILTER` | | Filter by label; repeatable |
| `--tag FILTER` | | Filter by tag; repeatable |
| `--force-refresh` | `-F` | Bypass cache |

Examples:

```bash
gcpath tree
gcpath tree folders/123 -L 3 -i
gcpath --format json tree --type project
```

## `diagram [RESOURCE]`

Generate a Mermaid or D2 diagram.

| Flag | Short | Description |
|------|-------|-------------|
| `--diagram-format FORMAT` | `-d` | `mermaid` or `d2` |
| `--level N` | `-L N` | Max display depth |
| `--ids` | `-i` | Show resource names in node labels |
| `--output FILE` | `-o` | Write to file |
| `--force-refresh` | `-F` | Bypass cache |

Examples:

```bash
gcpath diagram folders/123
gcpath diagram -d d2 -o org.d2
gcpath diagram folders/123 -L 2 --ids
```

## `stats [RESOURCE]`

Count organizations, folders, and projects. Resource must be an organization or folder.

| Flag | Short | Description |
|------|-------|-------------|
| `--force-refresh` | `-F` | Bypass cache |

## `summary [RESOURCE]`

Snapshot with counts, max depth, deepest paths, and top label/tag keys.

| Flag | Description |
|------|-------------|
| `--top N` | Number of top label/tag keys |
| `--force-refresh`, `-F` | Bypass cache |

## `audit [RESOURCE]`

Run read-only governance checks against the loaded hierarchy.

| Flag | Description |
|------|-------------|
| `--require-labels a,b` | Require labels on folders/projects |
| `--name-pattern REGEX` | Required display-name regex |
| `--severity info|warn|error` | Minimum severity |
| `--check CHECKS` | Comma-separated check subset |
| `--exit-zero` | Do not fail on warn/error findings |
| `--force-refresh`, `-F` | Bypass cache |

## `name PATH [PATH ...]`

Convert paths to GCP resource names.

| Flag | Description |
|------|-------------|
| `--id` | Print only the ID segment |
| `--force-refresh`, `-F` | Bypass cache |

Examples:

```bash
gcpath name //example.com/Engineering/Backend
gcpath name //example.com/Dept/Team --id
gcpath --format json name //a.com/X //a.com/Y
```

## `path RESOURCE [RESOURCE ...]`

Convert resource names to paths via direct ancestry API calls.

Examples:

```bash
gcpath path folders/123
gcpath path projects/my-project
gcpath --format json path folders/123 folders/456
```

## `find PATTERN [RESOURCE]`

Search display names or full paths using glob patterns; `--regex` enables regex search.

| Flag | Short | Description |
|------|-------|-------------|
| `--type TYPE` | `-t` | `organization`, `folder`, or `project` |
| `--regex` | `-E` | Use regex search semantics |
| `--fields FIELDS` | | Comma-separated fields |
| `--ids` | `-i` | Include resource names |
| `--full` | | Do not truncate label/tag fields |
| `--label FILTER` | | Filter by label; repeatable |
| `--tag FILTER` | | Filter by tag; repeatable |
| `--exclude GLOB` | | Exclude matches; repeatable |
| `--force-refresh` | `-F` | Bypass cache |

Examples:

```bash
gcpath find "*payments*"
gcpath find "prod-*" --type project
gcpath find -E "^api-.*-prod$"
gcpath --format json find "*" folders/123 --label env=staging
```

## `ancestors RESOURCE`

Show the full ancestry chain from a resource to the organization root.

```bash
gcpath ancestors projects/my-project
gcpath --format json ancestors folders/123
```

## `labels [RESOURCE]` / `tags [RESOURCE]`

Aggregate labels or tags across folders and projects.

| Flag | Description |
|------|-------------|
| `--key KEY` | Show only a specific key |
| `--top N` | Limit most frequent rows |
| `--force-refresh`, `-F` | Bypass cache |

## `open PATH [PATH ...]`

Print GCP Console URLs, or open them with `--browser`.

| Flag | Description |
|------|-------------|
| `--browser / --print` | Open in browser or print URL |
| `--force-refresh`, `-F` | Bypass cache |

## Local Management Commands

These commands write only local files; run write actions only when the user asks.

| Command | Description |
|---------|-------------|
| `gcpath cache status` | Show cache age, size, scope, API mode, and counts |
| `gcpath cache refresh` | Re-fetch hierarchy and rewrite cache |
| `gcpath cache clear` | Delete local cache |
| `gcpath config set-entrypoint RESOURCE` | Set default scope in local config |
| `gcpath config show` | Show local config |
| `gcpath config clear-entrypoint` | Remove default scope |
| `gcpath hook install` | Install local Claude Code/Codex hooks |
| `gcpath hook uninstall` | Remove local hooks |
| `gcpath hook status` | Show hook status |
| `gcpath hook run` | Print session-start dashboard |
| `gcpath mcp` | Run the optional MCP server |

## Resource Name Formats

| Resource | Format | Example |
|----------|--------|---------|
| Organization | `organizations/ID` | `organizations/123456789` |
| Folder | `folders/ID` | `folders/987654321` |
| Project | `projects/NUMBER` or `projects/PROJECT-ID` | `projects/my-project` |

## Path Format

```text
//DOMAIN/SEGMENT/SEGMENT/...
```

- `//example.com/Engineering/Backend/Services`
- `//_/OrphanedProject` for organizationless projects
