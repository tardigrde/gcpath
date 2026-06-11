# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**gcpath** is an AXI-compliant CLI utility for querying Google Cloud Platform (GCP) resource hierarchy paths. It translates between GCP resource names (e.g., `folders/12345`) and human-readable paths (e.g., `//example.com/department/team`).

Key features:

- AXI-compliant output: TOON format by default, with `--format toon|json|yaml|rich`
- Dual API modes: Cloud Asset API (default, fast) and Resource Manager API (slower, different permissions)
- Commands: `ls`, `tree`, `name`, `path`, `find`, `ancestors`, `stats`, `diagram`
- Scoped loading to improve performance for large hierarchies
- Support for organizationless projects (`//_` prefix)
- Ambient context hooks for Claude Code and Codex (`gcpath hook install`)

## AXI Compliance

gcpath follows the [AXI specification](https://axi.md/) for agent-friendly CLI tools:

- **TOON default output**: All commands output TOON format by default (token-efficient, structured)
- **`--format` flag**: `toon` (default), `json`, `yaml`, `rich` (human-friendly colored tables)
- **Pre-computed aggregates**: `ls` shows `count: N of M total`, `find` shows match count
- **Definitive empty states**: `0 resources found` with contextual help
- **Structured errors**: Errors go to stdout in TOON format, not stderr Rich markup
- **Content-first home**: Running `gcpath` with no args shows a live dashboard from cache
- **Contextual help**: `help[]` sections appended after list outputs with relevant next-step commands
- **`--fields` flag**: Control which columns appear in tabular output (`path,type,display_name,resource_name,project_id,labels,tags`)
- **`--full` flag**: Expand truncated labels/tags without truncation
- **No interactive prompts**: All confirm prompts removed; commands just proceed
- **`tree` is human-oriented**: Classic unicode tree output, not TOON. Agents should use `ls -R` instead. No `help[]` suggestions for `tree` in agent followups.
- **`diagram` is raw output**: Mermaid/D2 text output as-is, no TOON wrapping

## Setup and Build

### Dependencies

- Python 3.12+
- `uv` for dependency management

### Install dependencies

```bash
make install
# or: uv sync
```

### Run

```bash
make run ls
make run tree folders/123
# or directly: uv run gcpath ls
```

### Build and test

```bash
make test              # Run all tests
make coverage          # Run with coverage report
make lint              # Check with ruff
make typecheck         # Check with mypy
make format            # Format and fix with ruff
```

## Architecture

### Module Organization

The codebase is organized into focused, single-responsibility modules:

- **`core.py`**: Core data structures and hierarchy loading coordination. Contains resource models and main `Hierarchy` class.

- **`loaders.py`**: GCP API loading logic for both Resource Manager and Cloud Asset APIs, including SQL query builders.

- **`parsers.py`**: Parses Asset API responses, handling protobuf STRUCT/MapComposite complexity.

- **`formatters.py`**: Display formatting logic for paths, trees, and resource filtering.

- **`filters.py`**: Resource filtering for `ls`/`find` — label/tag filters (including `key!=value` negation), glob/regex pattern matchers (display name, or full path for `//`-prefixed patterns), and `--exclude` glob handling.

- **`serializers.py`**: Output serialization — TOON, JSON, YAML serializers for all commands.

- **`toon.py`**: Thin wrapper around `toon_format.encode()` plus gcpath-specific AXI helpers (error formatting, empty states, help sections, dashboards).

- **`hooks.py`**: Agent session hook management (install/uninstall/status for Claude Code and Codex).

- **`cli.py`**: CLI commands and entry points using Typer framework.

- **`cache.py`**: Cache management for hierarchy data.

- **`config.py`**: Configuration management (entrypoint settings).

### Data Flow

1. **Hierarchy Loading** (`Hierarchy.load()`):
   - Determines which loader to use (Resource Manager vs Asset API)
   - Loads organizations from `search_organizations()`
   - For each org, loads folders and projects using selected API
   - Returns `Hierarchy` object with lookup maps for O(1) resolution

2. **API Modes**:
   - **Cloud Asset API** (default): Fast bulk loading via SQL queries. Supports scoped loading with `parent_filter` and `ancestors_filter` parameters.
   - **Resource Manager API**: Iterative loading via list/get operations. Slower but simpler permissions model.

3. **Scoped Loading**: When a specific resource is targeted (e.g., `ls folders/123`):
   - Passes `scope_resource` to `Hierarchy.load()`
   - Loaders use filters to only fetch descendants of that resource
   - Significantly reduces API calls and latency for large hierarchies

4. **Output**: CLI dispatches to serializers based on `--format`:
   - `toon` (default): TOON tabular arrays, objects, help sections
   - `json`/`yaml`: Structured dicts via `dump_json`/`dump_yaml`
   - `rich`: Rich-colored tables and tree widgets
   - `tree` command always uses Rich tree output (not TOON)
   - `diagram` command always outputs raw Mermaid/D2 text

### Key Design Patterns

- **Lookup Maps**: `Hierarchy` maintains `_orgs_by_name`, `_folders_by_name`, `_projects_by_name` for O(1) lookups
- **Protobuf Objects**: Use actual `google.cloud.resourcemanager_v3` protobuf objects (not mocks) throughout the data layer
- **Optional Organization**: Projects can be organizationless (no parent organization)
- **Lightweight Path Resolution**: `Hierarchy.resolve_ancestry()` traverses up the hierarchy without loading full state
- **Content-first home**: `gcpath` with no args reads cache and shows dashboard, never shows help text

## Important Implementation Details

### Asset API Complexity

The Asset API returns STRUCT fields as `MapComposite` objects. Key handling:

- Access data directly as dictionary (`.fields` not available)
- Use `IN UNNEST(ancestors)` for ancestry filtering in SQL
- Extract nested STRUCT data like `resource.data.parent.id` carefully

### Resource Naming

- Organizations: `organizations/[ORG_ID]`
- Folders: `folders/[FOLDER_ID]`
- Projects: `projects/[PROJECT_ID]`
- Organizationless projects use display name with `//_/` prefix

### Scoped Loading Parameters

- `parent_filter`: Returns direct children only (non-recursive)
- `ancestors_filter`: Returns all descendants including in ancestors list (recursive)
- Default (no filter): Returns org-level or root-level resources

### TOON Output Conventions

- Default `ls` schema: `{path,type,display_name}` (3 fields); adds `project_id` for projects
- `--fields` overrides: any subset of `path,type,display_name,resource_name,project_id,labels,tags`
- Labels/tags truncated to 5 entries by default; `--full` shows all
- `count: N of M total` header on list outputs
- `help[]` sections with next-step suggestions (omitted for single-result commands like `name`, `path`)
- Errors to stdout as `error: <message>` with optional `help[]`

## Testing

Test files mirror source organization:

- `test_core.py`: Data structures and hierarchy logic
- `test_loaders.py`: GCP API loading functions
- `test_parsers.py`: Asset API response parsing
- `test_formatters.py`: Display formatting
- `test_filters.py`: Metadata filters, pattern matchers, exclusions
- `test_serializers.py`: Output serialization (TOON, JSON, YAML)
- `test_cli.py`: CLI command integration

Run specific test:

```bash
uv run pytest tests/test_parsers.py -v
```

## Release and Versioning

The project uses **semantic versioning** with automated release workflow via GitHub Actions.

### Version Management

- Version is defined in `pyproject.toml` under `[project]` → `version`
- Uses `semantic-release` to automatically manage versions and tags
- Configured to stay in `0.x.y` range (won't bump to 1.0.0)
- CHANGELOG.md is automatically updated on release

### Preparing a Release

1. **Create a feature branch** and make your changes (follow conventional commit messages)

2. **Commit with conventional commit format**:
   - `feat: ...` for new features (bumps minor version)
   - `fix: ...` for bug fixes (bumps patch version)
   - `BREAKING CHANGE: ...` in commit body for major changes
   - See CONTRIBUTING.md for full guidelines

3. **Create a pull request** to merge into `main`

4. **Merge to main** - This triggers the automated release workflow:
   - `semantic-release` analyzes commits since last tag
   - Updates version in `pyproject.toml`
   - Updates CHANGELOG.md
   - Creates a git tag (e.g., `v0.2.4`)
   - Creates a GitHub Release with built artifacts

5. **Manual release** (if needed):

   ```bash
   # The workflow runs automatically on merges to main
   # Manual trigger is rarely needed
   ```

### Build and Publishing

- Package built with `hatchling` backend
- GitHub Actions workflow (`.github/workflows/release.yml`) handles automated releases
- Built wheels uploaded to GitHub Releases (not PyPI - `upload_to_pypi = false`)
- Install via: `pip install gcpath` or `uv add gcpath`

## Development Notes

- Use `logging.getLogger(__name__)` in modules (configured at CLI entry point)
- Type hints required for mypy compliance
- Ruff configured for linting and formatting
- All exceptions inherit from `GCPathError` base class
- CLI commands should wrap GCP API calls with error handling
- Follow conventional commits for automatic version bumping
- TOON encoding uses `toon_format` library (imported as `toon_format`)
- `toon.py` is a thin wrapper that adds gcpath-specific AXI conventions on top of `toon_format.encode()`
