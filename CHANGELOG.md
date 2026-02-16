# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.4.0] - 2026-02-16

### Features

- **diagram command**: Generate Mermaid or D2 diagrams of the GCP resource hierarchy ([`c2d6c70`](https://github.com/tardigrde/gcpath/commit/c2d6c70))
  - Supports `--format mermaid` (default) and `--format d2` output formats
  - Scoped diagram generation via resource argument (e.g. `gcpath diagram folders/123`)
  - `--output` flag to write diagram to a file
  - `--level` depth limiting, `--ids` to show resource names in labels

### Refactoring

- Deduplicated `tree` and `diagram` CLI setup into shared `_prepare_hierarchy_command()` helper ([`387ecbc`](https://github.com/tardigrde/gcpath/commit/387ecbc))
- Replaced `hasattr`-based ternaries with explicit `isinstance` checks in formatters
- Added `Hierarchy` type annotations to all formatter functions (replacing `Any`)

---

**Detailed Changes**: [v0.3.0...v0.4.0](https://github.com/tardigrde/gcpath/compare/v0.3.0...v0.4.0)

## [v0.3.0] - 2026-02-08

### Bug Fixes

- Add missing mock in test_tree_user_declines_prompt ([`c7aa4c8`](https://github.com/tardigrde/gcpath/commit/c7aa4c84622bb87067654f3f182a765d90726455))

- Address linting errors ([`242db12`](https://github.com/tardigrde/gcpath/commit/242db1270e8f3475d79a94f3eaea8c7a85fdd18e))

### Chores

- Refactor code into modules (v0.2.3) ([`ac156e7`](https://github.com/tardigrde/gcpath/commit/ac156e714b2752ddf3458cc03e31dad7205dae18))

### Features

- Add local caching for GCP resource hierarchy ([`385b3be`](https://github.com/tardigrde/gcpath/commit/385b3be810c6507ab292ee04b432a0e918e2469c))

### Refactoring

- Address PR feedback ([`c37ab27`](https://github.com/tardigrde/gcpath/commit/c37ab27401a352046029e93a30edbb5664abdaf2))

- Implement robust caching layer with TTL and architectural improvements ([`caa73c8`](https://github.com/tardigrde/gcpath/commit/caa73c8c79a66269e250fc36b9ff644c4ed06af7))

---

**Detailed Changes**: [v0.2.3...v0.3.0](https://github.com/tardigrde/gcpath/compare/v0.2.3...v0.3.0)

## [0.2.3] - 2025-12-22

### Fixed
- Fixed `ls -l` formatting: simplified to 2 columns (Path, Resource Name) for better readability. Previously showed 4 columns with redundant information and path truncation.
- Removed artificial tree depth limit of 3 levels. Tree command now accepts unlimited depth.

### Changed
- Tree command now prompts user before loading large hierarchies (when no level limit is specified or level >= 4). This prevents accidentally loading massive hierarchies that could take a long time.
- Tree command accepts `-y/--yes` flag to skip confirmation prompts for automation/scripting use cases.
- Improved `ls -l` output: full paths are now visible without truncation, resource names show complete GCP identifiers (e.g., `organizations/123`, `folders/456`, `projects/789`).

### Documentation
- Updated README.md with expanded API modes section explaining when to use each API.
- Updated CONTRIBUTING.md with development setup, testing guidelines, and instructions for testing both API modes.
- Enhanced permission documentation with complete permission requirements for both APIs.

### Refactoring
- **Modular Architecture**: Reorganized codebase from 2 monolithic files into 5 focused modules for better maintainability and testability.
  - Created `parsers.py`: Centralized all Asset API response parsing logic with 8 pure functions for handling STRUCT/MapComposite complexity.
  - Created `loaders.py`: Extracted all GCP API loading logic with 8 functions for Resource Manager and Asset API operations.
  - Created `formatters.py`: Extracted display formatting logic with 6 functions for path formatting, tree visualization, and resource filtering.
  - Simplified `cli.py`: Removed nested functions, now uses formatters module for display logic.
  - Simplified `core.py`: Removed loader/parser logic, now focuses on data structures and coordination.
- **Code Quality**: All functions are following single responsibility principle.
- **Test Organization**: Restructured tests to match source organization:
  - Created `test_parsers.py` for parsing logic.
  - Created `test_loaders.py` for loading logic.
  - Created `test_formatters.py` for formatting logic.
  - Removed obsolete `test_loading.py` after migrating all tests.

## [0.2.2] - 2025-12-22

### Added
- **Scoped Loading**: Added support for incremental/scoped loading of the resource hierarchy. The `ls`, `tree`, and `path` commands now only load the necessary descendants when a specific resource is targeted, significantly improving performance for large organizations.
- **SQL Robustness**: Implemented `lifecycleState = 'ACTIVE'` filtering in Asset API queries to exclude deleted or recovering resources.
- **Parent Resolution**: Improved project parent resolution by fetching and parsing the `resource.data.parent` STRUCT directly from the Asset API, reducing reliance on the `ancestors` array.

### Changed
- Refactored `Hierarchy.load` to support a `target_resource_name` parameter for targeted descendant loading.

## [0.2.1] - 2025-12-21

### Optimized
- **Logging**: Refactored logging to provide relevant debug information after every GCP API call, facilitating easier troubleshooting.
- **Logging**: Reduced log noise by removing redundant client initialization messages and streamlining inner loop logs.

## [0.2.0] - 2025-12-21

### Added
- **tree command**: Added support for positional resource name argument to display a sub-tree (e.g., `gcpath tree folders/123`).
- **tree command**: Implemented stricter `-L` (depth limit) logic that respects the root of the sub-tree.
- **name command**: Added `--id` flag to output only the resource ID number (e.g., `123` from `folders/123`).

### Changed
- `name` command robustly handles path-like input (e.g., `//example.com`) for resolution.

## [0.1.4] - 2025-12-21

### Fixed
- **CRITICAL FIX**: Fixed `AttributeError: 'MapComposite' object has no attribute 'fields'` by accessing row data directly as dictionaries. This aligns with how `google-cloud-asset` unmarshals Structs.
- Fixed logic to correctly append `Project` objects to the returned list in `_load_projects_asset`.

### Changed
- **Optimization**: `gcpath path` command now uses direct recursive lookup (Resource Manager API) instead of loading the entire hierarchy, significantly improving performance for single resource queries.
- Configured automated release to stay within `0.x.y` version range (`major_on_zero = false`).

## [0.1.3] - 2025-12-21

### Fixed
- Fixed mypy type annotation error for `projects` variable in `_load_projects_asset`.

### Added
- `CONTRIBUTING.md` with feature branch workflow and conventional commits guide.
- Automated semantic versioning with GitHub Actions (`.github/workflows/release.yml`).

## [0.1.2] - 2025-12-21

### Fixed
- Fixed `Unknown field for QueryAssetsResponse: pages` by updating pagination to iterate directly over `response.query_result.rows`.
- Fixed `displayName does not exist` error by removing `resource.data.displayName` from Project Asset API query (field not available in that table).

## [0.1.1] - 2025-12-21

### Fixed
- Fixed `AttributeError: type object 'QueryAssetsRequest' has no attribute 'Statement'` by updating `google-cloud-asset` usage to pass `statement` directly.
- Fixed PyPI classifiers in `pyproject.toml` to use standard "Intended Audience".

### Changed
- Removed `get-resource-name` and `get-path` command aliases to simplify CLI.

## [0.1.0] - 2025-12-21

### Added
- Core logic for GCP resource hierarchy management.
- Dual mode loading: Cloud Asset API (fast bulk) and Resource Manager API (iterative).
- CLI commands: `ls`, `tree`, `name` (get resource name), `path` (get path).
- Support for organizationless projects (`//_` prefix).
- O(1) resource lookups via cached dictionaries.
- Comprehensive test suite for core logic and CLI.
- GitHub Actions CI workflow with automatic test, lint, type check, and coverage reporting.
- Defensive API response parsing and structured error handling.
- MIT License.
