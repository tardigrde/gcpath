# CHANGELOG


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
