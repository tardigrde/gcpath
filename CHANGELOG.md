# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
