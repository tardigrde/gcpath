# CHANGELOG


## v0.8.0 (2026-03-17)

### Bug Fixes

- Address PR review feedback — reduce duplication in serializers and CLI
  ([`40ae2c6`](https://github.com/tardigrde/gcpath/commit/40ae2c65fc63d58b0189783956baf8a39490f1f6))

- Extract _get_dumper() helper to eliminate repeated dumper selection logic - Remove unused
  hierarchy and show_ids params from serialize_tree_node - Reuse serialize_resource() for project
  dicts instead of duplicating

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Extract duplicated string literals to constants in conftest.py
  ([`ed34bc6`](https://github.com/tardigrde/gcpath/commit/ed34bc6b96f256b7f6111438e1aa197402d5d78d))

Resolves SonarCloud S1192 issues for "organizations/123", "folders/1", and "folders/11" repeated in
  test hierarchy builder.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Resolve SonarCloud duplication and unused variable issues
  ([`aa47ef5`](https://github.com/tardigrde/gcpath/commit/aa47ef5bdc946abc3a2abb0886512d451c6c8e18))

- Extract shared test hierarchy builder to conftest.py (eliminates ~40-line duplication between
  test_cli.py and test_serializers.py) - Fix all 6 unused variable warnings in test_serializers.py

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- Add --json and --yaml structured output flags
  ([`949d8e3`](https://github.com/tardigrde/gcpath/commit/949d8e31a6115496a1ee580bfc69375db01ed2fe))

Add global --json and --yaml flags for machine-readable output across all commands (ls, tree, name,
  path). This makes gcpath composable with jq, yq, shell scripts, and CI pipelines.

- New serializers.py module for dict-building and JSON/YAML dumping - Mutually exclusive flags with
  clear error message - Cache status message moved to stderr to avoid polluting structured output -
  pyyaml>=6.0 added as dependency

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.7.1 (2026-03-17)

### Bug Fixes

- Extract duplicated "folders/" literal to constant in loaders
  ([`b292a3e`](https://github.com/tardigrde/gcpath/commit/b292a3e62ba694a612386fe1d53bd64150e93ad1))

SonarCloud S1192: the string "folders/" was duplicated 5 times. Extract to module-level
  _FOLDER_PREFIX constant.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Resolve SonarCloud code quality issues
  ([`054bdbe`](https://github.com/tardigrde/gcpath/commit/054bdbe30fff9cad0b9179ac16add54bb353d4f9))

Addresses 19 of 31 SonarCloud findings:

S1192 (CRITICAL): Extract duplicated string literals into module-level constants - Added
  _RESOURCE_PREFIX_PROJECTS, _RESOURCE_PREFIX_FOLDERS, _RESOURCE_PREFIX_ORGS - Added
  _RESOURCE_PREFIXES tuple and _REFRESH_HELP constant - Replaced all occurrences in cli.py

S1871 (MAJOR): Merge duplicate branches - formatters.py: Merged Folder/Project branches in
  get_display_path and _get_node_label - parsers.py: Merged hasattr/get and isinstance/dict checks
  in extract_value

S3358 (MAJOR): Extract nested ternaries into if/else blocks - loaders.py: Refactored folder_parent
  and project parent_res determination logic

S3776 (CRITICAL): Reduce cognitive complexity with helper extraction - cli.py: Extracted
  _try_read_cache() from _load_hierarchy() - core.py: Extracted _find_orgless_project() from
  get_resource_name() - loaders.py: Extracted _build_single_ancestor_chain() from
  fix_folder_ancestors()

S7504 (MINOR): Remove unnecessary list() call - loaders.py: Changed list(node.folders.values()) to
  node.folders.values()

S2737 (MINOR): Remove bare except clause - core.py: Removed no-op try/except that just re-raised

S2772 (MINOR): Remove unneeded pass - tests/test_cli.py: Replaced pass with meaningful assertion

S1481 (MINOR): Fix unused variable - tests/test_formatters.py: Changed folders to _ for unused
  variable

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Testing

- Add coverage for extracted helper functions
  ([`ab315ee`](https://github.com/tardigrde/gcpath/commit/ab315ee00fce36b4917f05ad8450f850d3dde59f))

Add direct tests for: - _build_single_ancestor_chain (loaders.py) - _find_orgless_project (core.py)
  - _try_read_cache (cli.py)

Coverage improved from 87% to 88%

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add coverage for loader conditional branches and remove dead code
  ([`37b7f01`](https://github.com/tardigrde/gcpath/commit/37b7f0144fff1e11fdda25100d559bf2a522a42a))

Cover the refactored if/elif/else branches in load_folders_asset and load_projects_asset that handle
  fallback parent resolution. Remove unreachable elif/else in the last else-branch where ancestors
  is guaranteed non-empty.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.7.0 (2026-03-09)

### Bug Fixes

- Validate resource format and escape rich markup in stats command
  ([`7728b16`](https://github.com/tardigrde/gcpath/commit/7728b162ecb5bc4b5f2c088afd7373b6ba866efb))

- Add explicit else branch for invalid resource formats (not organizations/ or folders/) with a
  clear "Invalid resource format" error message instead of silently loading the full hierarchy -
  Escape user-supplied scope label with rich.markup.escape to prevent markup injection via crafted
  resource name arguments - Add test_stats_invalid_scope_error test case

https://claude.ai/code/session_01JxDqkYXvoag1R6LWBV8Mtq

### Chores

- **deps**: Bump protobuf in the uv group across 1 directory
  ([`176815d`](https://github.com/tardigrde/gcpath/commit/176815d8f01d376bd61587091610efedf5f87148))

Bumps the uv group with 1 update in the / directory:
  [protobuf](https://github.com/protocolbuffers/protobuf).

Updates `protobuf` from 6.33.2 to 6.33.5 - [Release
  notes](https://github.com/protocolbuffers/protobuf/releases) -
  [Commits](https://github.com/protocolbuffers/protobuf/commits)

--- updated-dependencies: - dependency-name: protobuf dependency-version: 6.33.5

dependency-type: indirect

dependency-group: uv ...

Signed-off-by: dependabot[bot] <support@github.com>

### Features

- Add stats subcommand for folder/project counts in a scope
  ([`9a28f93`](https://github.com/tardigrde/gcpath/commit/9a28f93d21df458237e1c51f9b1bc101b8bf05a4))

Adds a new `stats` CLI subcommand that reports the number of organizations, folders, and projects
  within a given scope (organization or folder). When no scope is provided, it reports totals across
  all accessible organizations. Projects are rejected as the starting scope since they are leaf
  nodes.

https://claude.ai/code/session_01JxDqkYXvoag1R6LWBV8Mtq


## v0.6.1 (2026-03-07)

### Bug Fixes

- **deps**: Bump pyasn1 to 0.6.2 and urllib3 to 2.6.3
  ([`bd4c47c`](https://github.com/tardigrde/gcpath/commit/bd4c47c9a44fc4cc9e35b1d3ed4f613f1b9244fb))

Fixes CVE-2026-23490 (pyasn1 OID decoder issue) and CVE-2026-21441 (urllib3 decompression-bomb
  bypass, High severity).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

### Documentation

- Refocus README on CLI usage, add pipx install, remove roadmap
  ([`cb03af6`](https://github.com/tardigrde/gcpath/commit/cb03af699a6a9daf4ba7533b0f6b2bc5a47367e6))

Move Python API section to the end as a secondary use case. Add pipx as a recommended installation
  option alongside pip and uv. Remove the roadmap section.

https://claude.ai/code/session_01E5TmezTsqmhrkBS6HdVSL9


## v0.6.0 (2026-03-07)

### Chores

- **deps**: Bump protobuf in the uv group across 1 directory
  ([`a21b624`](https://github.com/tardigrde/gcpath/commit/a21b6246e8f4253ad8693e1afaa21dd5d19b8a05))

Bumps the uv group with 1 update in the / directory:
  [protobuf](https://github.com/protocolbuffers/protobuf).

Updates `protobuf` from 6.33.2 to 6.33.5 - [Release
  notes](https://github.com/protocolbuffers/protobuf/releases) -
  [Commits](https://github.com/protocolbuffers/protobuf/commits)

--- updated-dependencies: - dependency-name: protobuf dependency-version: 6.33.5

dependency-type: indirect

dependency-group: uv ...

Signed-off-by: dependabot[bot] <support@github.com>

- **deps**: Configure Dependabot to use pip for updates
  ([`322a771`](https://github.com/tardigrde/gcpath/commit/322a771d26a43f031e86de2afe6ae51a667f935f))

### Features

- Add Python API documentation and library usage examples
  ([`aa65f59`](https://github.com/tardigrde/gcpath/commit/aa65f59ed96ad13bd5f8a6475d5651adac3c260e))

- Add comprehensive "Python API" section to README.md covering: - Basic usage with Hierarchy.load()
  (both RM and Asset API modes) - Path ↔ resource name conversion methods - Lightweight
  single-resource lookup via Hierarchy.resolve_ancestry() - Scoped loading for large or restricted
  hierarchies - Error handling with GCPathError, ResourceNotFoundError, PathParsingError - API
  reference table for all public symbols - Update pyproject.toml description to reflect library
  capability - Add "Topic :: Software Development :: Libraries :: Python Modules" classifier

https://claude.ai/code/session_01M3eDcpXVjivW3zbCXnvbmx


## v0.5.1 (2026-02-17)

### Bug Fixes

- Make cache scope-aware so entrypoint loads are cached
  ([`c288a51`](https://github.com/tardigrde/gcpath/commit/c288a511e6157be7c70fc5b57d717454f5e87a5c))

The cache was completely bypassed when an entrypoint was configured because _load_hierarchy() only
  read/wrote cache when scope_resource was None. Now the cache stores which scope it was built for
  and only serves hits when the scope matches, enabling instant subsequent commands with
  entrypoints.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.5.0 (2026-02-16)

### Features

- Add folder entrypoint support for folder admins without org access
  ([`e15c6ca`](https://github.com/tardigrde/gcpath/commit/e15c6cab83245539e49df8250f3e6ba870c5d602))

Allow users who only have access to a folder (not the parent organization) to use ls, tree, diagram,
  and name commands by configuring a folder as the default entrypoint. When org loading fails and
  the scope is a folder, a fallback path creates a synthetic OrganizationNode and queries the Asset
  API directly from the folder scope.

Adds config subcommands (set-entrypoint, show, clear-entrypoint) and a global --entrypoint/-e flag.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.4.1 (2026-02-16)

### Bug Fixes

- Add missing v0.4.0 CHANGELOG entry and pin PSR to v9
  ([`0d35cec`](https://github.com/tardigrde/gcpath/commit/0d35cec55cefbcd27b057c997f9125dc36b8e8a7))

The v0.4.0 release was created by PSR v10.x (pulled via unpinned `--with python-semantic-release`)
  which silently skipped changelog generation due to breaking template changes from v9.

- Add the v0.4.0 CHANGELOG entry manually - Pin PSR to >=9,<10 in release workflow to prevent
  version drift - Revert changelog config key to v9 format

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.4.0 (2026-02-16)

### Chores

- Update uv.lock
  ([`6cccda9`](https://github.com/tardigrde/gcpath/commit/6cccda9357113423fab09d5144c22a99f48a8ec8))

https://claude.ai/code/session_01Jmv8XrUQSV3r83cSgHtqys

### Features

- Add diagram generation command (Mermaid & D2)
  ([`c2d6c70`](https://github.com/tardigrde/gcpath/commit/c2d6c70822955c550584298df8254dda6bb3f4dc))

Add a `diagram` command that generates Mermaid or D2 diagrams from the GCP resource hierarchy. Works
  directly from structured hierarchy data rather than parsing tree ASCII output, inspired by
  tree2diagram.

Supports scoped resources, depth limiting, resource ID labels, and file output. Closes the "diagram
  generation" roadmap item.

https://claude.ai/code/session_01Jmv8XrUQSV3r83cSgHtqys


## v0.3.0 (2026-02-08)

### Bug Fixes

- Add missing mock in test_tree_user_declines_prompt
  ([`c7aa4c8`](https://github.com/tardigrde/gcpath/commit/c7aa4c84622bb87067654f3f182a765d90726455))

The test was failing in CI environments without GCP credentials because Hierarchy.load() was being
  called even after the user declined the prompt. Added mock for Hierarchy.load to prevent actual
  client creation.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Address linting errors
  ([`242db12`](https://github.com/tardigrde/gcpath/commit/242db1270e8f3475d79a94f3eaea8c7a85fdd18e))

This commit fixes the linting errors reported by ruff.

### Chores

- Refactor code into modules (v0.2.3)
  ([`ac156e7`](https://github.com/tardigrde/gcpath/commit/ac156e714b2752ddf3458cc03e31dad7205dae18))

### Features

- Add local caching for GCP resource hierarchy
  ([`385b3be`](https://github.com/tardigrde/gcpath/commit/385b3be810c6507ab292ee04b432a0e918e2469c))

This commit introduces a local caching mechanism to speed up API calls when fetching the GCP
  resource hierarchy. The cache is stored as a single JSON file at `~/.gcpath/cache.json`.

New features include: - A `gcpath cache clear` command to manually clear the cache. - A
  `--force-refresh` flag on commands that display the resource hierarchy to bypass the cache and
  fetch fresh data from GCP. - User notifications in the console when a command is using cached
  data.

Comprehensive unit tests have been added for the new caching functionality, and existing tests have
  been updated to account for the caching layer.

### Refactoring

- Address PR feedback
  ([`c37ab27`](https://github.com/tardigrde/gcpath/commit/c37ab27401a352046029e93a30edbb5664abdaf2))

This commit addresses the feedback from the pull request:

- Renames the `SimpleOrg` class to `SerializableOrganization` for clarity. - Refactors the `cache`
  subcommand to be more integrated with the main Typer application.

- Implement robust caching layer with TTL and architectural improvements
  ([`caa73c8`](https://github.com/tardigrde/gcpath/commit/caa73c8c79a66269e250fc36b9ff644c4ed06af7))

- Add TTL (4-hour default) to cache expiration with UTC timestamp validation - Implement cache
  freshness checking and raw JSON reading without deserialization - Add CacheInfo dataclass for
  cache metadata inspection (age, size, freshness, resource counts) - Remove circular dependency:
  eliminate cache I/O from Hierarchy.load(), move orchestration to CLI - Add `cache status`
  subcommand showing cache state and resource counts - Refactor _load_hierarchy() as single cache
  orchestration point with post-load org filtering - Update tree command to use get_cache_info() for
  freshness checking - Show human-readable cache age on hits ("2h 15m ago") - Revert premature
  version bump (0.3.0 → 0.2.3) for semantic-release - Comprehensive test updates: TTL checking,
  cache info inspection, cache subcommands

Fixes circular dependency architecture, implements proper cache expiration, and enables cache state
  inspection. All 127 tests passing, lint and type checks clean.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.2.2 (2025-12-22)

### Bug Fixes

- Improve tree, ls, path subcommands (0.2.2)
  ([`5b59880`](https://github.com/tardigrde/gcpath/commit/5b59880e2f62acc595902abd12af06390c7b4c3c))


## v0.2.1 (2025-12-21)

### Bug Fixes

- Debug logs (v0.2.1)
  ([`0bd2c57`](https://github.com/tardigrde/gcpath/commit/0bd2c57bd73a5a86f5059c5e33993049989d5f45))


## v0.2.0 (2025-12-21)

### Features

- Subcommand improvements (v0.2.0)
  ([`d4d2c36`](https://github.com/tardigrde/gcpath/commit/d4d2c367d2db2c94d2419acb386c64c9f0cfa732))


## v0.1.3 (2025-12-21)

### Bug Fixes

- Add type annotation for mypy compliance
  ([`6cd1464`](https://github.com/tardigrde/gcpath/commit/6cd1464d590b5169e157d1a702f1955c6cea82b0))

- Added List[Project] type annotation to projects variable - Created CONTRIBUTING.md with feature
  branch workflow - Added automated semantic versioning with GitHub Actions - Bumped version to
  0.1.3

- Mapcomposite error & optimize path command (v0.1.4)
  ([`2437608`](https://github.com/tardigrde/gcpath/commit/2437608a98e296d5292041f29ab90834fcb6a22a))

- Releases with 0.x
  ([`3cee1be`](https://github.com/tardigrde/gcpath/commit/3cee1be02ec35467f620b00bfe9c74f1ea426398))

- **release**: Use uv run for semantic-release to avoid PEP 668 errors
  ([`3915394`](https://github.com/tardigrde/gcpath/commit/39153945413f081999ab93430fef400aa2457920))

### Chores

- Configure semantic-release to stay in 0.x.y range
  ([`b5e11e9`](https://github.com/tardigrde/gcpath/commit/b5e11e9423ad7d60a43c3ca1afa86dcf1f998a0e))


## v0.1.2 (2025-12-21)

### Bug Fixes

- Asset API pagination and Project schema compatibility (v0.1.2)
  ([`f35edbe`](https://github.com/tardigrde/gcpath/commit/f35edbe8daf7dcf76733a8ac213418c643f400ce))


## v0.1.1 (2025-12-21)

### Chores

- Bump version to 0.1.1 and fix bugs
  ([`63ab844`](https://github.com/tardigrde/gcpath/commit/63ab844fbddf4f65bde2876cfd05ffe004fdc067))


## v0.1.0 (2025-12-21)

### Features

- Initial release v0.1.0 ([#1](https://github.com/tardigrde/gcpath/pull/1),
  [`c21530f`](https://github.com/tardigrde/gcpath/commit/c21530fbc737acf10fe2396a159cbff586459957))

- Core logic for GCP resource hierarchy management. - Dual mode loading: Cloud Asset API (fast bulk)
  and Resource Manager API (iterative). - CLI commands: `ls`, `tree`, `name` (get resource name),
  `path` (get path). - Support for organizationless projects (`//_` prefix). - O(1) resource lookups
  via cached dictionaries. - Comprehensive test suite for core logic and CLI. - GitHub Actions CI
  workflow with automatic test, lint, type check, and coverage reporting. - Defensive API response
  parsing and structured error handling. - MIT License.

---------

Co-authored-by: gemini-code-assist[bot] <176961590+gemini-code-assist[bot]@users.noreply.github.com>
