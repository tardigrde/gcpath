# CHANGELOG


## v0.12.0 (2026-06-11)

### Features

- Add open, labels/tags, summary, audit, and mcp commands
  ([#34](https://github.com/tardigrde/gcpath/pull/34),
  [`d52f9c8`](https://github.com/tardigrde/gcpath/commit/d52f9c8cc7e2535be73bc0a6ac51ace21409a55f))

* feat: add open, labels/tags, summary, audit, and mcp commands

Adds the top 5 features from the implementation plan to make gcpath stickier for daily human use and
  richer for AI agents.

- `open <path>` opens or prints the GCP Cloud Console URL for a resource. Multi-arg supported;
  rejects orgless and synthetic-org resources with structured errors. - `labels` / `tags` aggregate
  label/tag occurrences across the hierarchy with counts, examples, and `--key`/`--top` filters. -
  `summary` prints a one-shot agent-friendly snapshot (counts, depth, top label/tag keys, deepest
  paths) and excludes the synthetic org. - `audit` runs governance checks (orphan projects,
  synthetic-org, required labels, duplicate display names, name-pattern violations) with severity
  gating and a `--exit-zero` CI flag. - `mcp` runs gcpath as an MCP server (FastMCP, stdio/sse
  transports) exposing path/name/list/find/ancestors/summary/labels/tags/console_url/ audit tools so
  Claude Desktop, Claude Code, and other MCP clients can query the hierarchy directly. Optional
  `[mcp]` extra in pyproject.toml.

Test coverage: 420 tests passing, ruff and mypy clean.

* fix: address PR #34 review, CodeQL, SonarCloud, and Codecov findings

Reviews (high-severity correctness): - core.summary: include projects in max_depth and use the
  correct project depth formula (folder.depth + 1 == len(folder.ancestors)) so deepest_paths and
  max_depth no longer underreport hierarchy depth. - audit._check_synthetic_org: also flag projects
  directly attached to the synthetic org instead of only its folders. - formatters.console_url:
  reject projects that live under the synthetic org (directly or via folder), matching the
  org/folder rejection. - mcp_server.list_resources: at root scope, only return org-level projects
  (mirroring the folder filter) and merge identical branches.

Reviews (mediums): - Move _aggregate_metadata into core.aggregate_metadata so cli.py and
  mcp_server.py both consume it without an upward dependency. - mcp_server cache key now varies on
  include_labels/include_tags so different metadata requirements don't reuse a labelless hierarchy.
  - mcp_server.name_to_path serves resolutions from the cached hierarchy and only falls back to live
  GCP calls for unknown resources. - Reject oversized name_pattern (>200 chars) in the audit CLI and
  the audit_hierarchy MCP tool to bound ReDoS risk. - audit CLI: --check
  missing_required_label/name_pattern_violation now errors out when --require-labels /
  --name-pattern is missing instead of silently emitting `0 issues`. - open --browser: surface error
  rows even when at least one URL opened successfully, so partial-success no longer swallows
  failures. - audit._resource_path: url-escape org display names so paths stay canonical for orgs
  containing spaces/specials. - toon_audit: pluralize correctly ("1 issue", "N issues") and emit the
  count + table in a single TOON block (same fix for toon_metadata_aggregation). - cli.mcp_command:
  drop the dead ImportError wrapper around `from gcpath.mcp_server import run_server` (mcp_server is
  import-safe; the missing-extra signal already flows through GCPathError).

SonarCloud: - Define _RICH_HEADER_STYLE / _SCOPE_ALL_ORGS constants for the duplicated "bold
  magenta" / "all organizations" literals (S1192). - Refactor open_resource (CC=44 -> below
  threshold) into resolve / browser-open / render helpers, and audit_command (CC=25) into validators
  + render helpers; reduce summary_command, mcp build_server, _resolve_to_object,
  _resolve_path_to_object cognitive complexity by extracting tool/render/finder helpers (S3776). -
  Merge the duplicate `_serialize_resource(...)` branches in list_resources (S1871).

CodeQL: - tests/test_open_single_folder: assert against the fully-formed URL rather than the host
  substring so the URL-substring sanitization rule no longer flags the assertion. - Replace
  tautology `assert result.exit_code in (0, 1)` with a precise assertion against the missing-extra
  error path.

Codecov: - New tests/test_mcp_server.py covers cache keying, list_resources scoping, find_resources,
  name_to_path/path_to_name, console_url, aggregation, audit_hierarchy, ReDoS guard, synthetic-org
  flagging, build_server import-error path, and a smoke roundtrip through every registered FastMCP
  tool. - Additional tests for audit pattern errors, audit CLI validation, open --browser
  partial-success, summary/audit rich rendering, and the formatters.console_url synthetic-org guard.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

* fix: address remaining SonarCloud nits on PR #34

- formatters.console_url: replace `elif item.organization is not None` (always-true after the
  early-return guard) with an `else` + assertion so S2589 stops firing. - mcp_server: introduce
  `_PREFIX_ORGS/_FOLDERS/_PROJECTS` constants and reuse them in `_resolve_to_object` and
  `_include_in_listing` to clear the S1192 duplicate-literal finding. - core.Hierarchy.summary:
  extract `_summary_max_depth`, `_summary_deepest_paths`, and a `_project_depth` helper to drop the
  function below the S3776 cognitive-complexity threshold.

* fix: address CodeRabbit follow-up findings on PR #34

- core.summary: filter folders/projects to drop synthetic-org descendants before computing
  folder_count, project_count, max_depth, top label/tag keys, and deepest_paths so the snapshot
  isn't skewed by the artificial folder-root org. Orgless projects (no org and no folder) remain in
  the count — they're real GCP resources that just sit outside any visible organization. -
  mcp_server: url-escape organization display names in _serialize_resource and _name_to_path so
  paths emitted by MCP tools are canonical and round-trip cleanly through path_to_name. -
  mcp_server._aggregate_impl: treat `top` with `is not None` so an explicit `top=0` returns an empty
  list instead of being silently collapsed to "no limit". - mcp_server.build_server: add `->
  "FastMCP"` return annotation (under TYPE_CHECKING import) for full mypy coverage.

New tests cover: synthetic-org descendants excluded from summary metrics, MCP org-path escaping
  (serialize_resource + name_to_path), and the `top=0` aggregation edge case.

---------

Co-authored-by: Claude <noreply@anthropic.com>


## v0.11.1 (2026-06-11)

### Bug Fixes

- Vendor toon-format to unblock PyPI publishing ([#36](https://github.com/tardigrde/gcpath/pull/36),
  [`9173307`](https://github.com/tardigrde/gcpath/commit/9173307d538c9c93fe9ae22ffb0b64f76e8e4391))

* fix: vendor toon-format to unblock PyPI publishing

The latest toon-format PyPI release (0.9.0b1) predates fixes we depend on, so gcpath was pinned to a
  git commit — which PyPI rejects as a direct dependency. Vendor toon_format at commit 9086144 (MIT)
  under gcpath._vendor and drop the git dependency.

Vendored code is excluded from ruff, mypy, and coverage. Remove the vendor copy once upstream cuts a
  new release (toon-format/toon-python#58).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

* ci: exclude vendored code from SonarCloud analysis

---------

Co-authored-by: Claude Fable 5 <noreply@anthropic.com>


## v0.11.0 (2026-04-28)

### Bug Fixes

- Address PR review comments and CI failures
  ([`1d733c9`](https://github.com/tardigrde/gcpath/commit/1d733c93c16e562d7cbbd381d0f4cc2e5c6bed20))

- Remove duplicate test_ls_rich_format (ruff F811 CI blocker) - Tighten test_format_json_output
  assertion to check exit_code and option parsing - Replace import-time assert in toon.py with
  GCPathError for deterministic check - Keep count header in empty toon_ls output for schema
  consistency - Make _write_json atomic via tmp-file + os.replace - Validate JSON root type is dict
  in _read_json - Centralize managed hook matching with _is_managed_hook helper - Handle 0.0 cache
  age as fresh data (is not None check) - Narrow broad Exception catch in _parse_resource_arg to
  GCP/GCPath errors - Replace /tmp paths in hook status mock data with user config paths - Update
  README to drop non-existent --json/--yaml shorthand docs - Add minimal contents:read permission to
  CI workflow

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

- Address PR review comments and SonarCloud hotspots
  ([`070529c`](https://github.com/tardigrde/gcpath/commit/070529c847b19aacd95f543498ea77b50783c8e4))

- Restore docstring on _resolve_scope in cli.py - Narrow except Exception to specific GCP/gcpath
  exceptions in path command - Fix return type hint on _truncate_metadata (Any -> Dict[str, str]) -
  Add docstring on serialize_resource - Replace /tmp paths in test_serializers.py to resolve
  SonarCloud S5443

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Narrow broad exception catch and remove conflicting CodeQL workflow
  ([`aae603b`](https://github.com/tardigrde/gcpath/commit/aae603b1c169031e23dc942d0e7db36485510c87))

- Replace bare `except Exception` in `_resolve_target_path_prefix` with specific `(GCPathError,
  gcp_exceptions.GoogleAPICallError)` as suggested in review - Remove custom CodeQL workflow files
  that conflict with the repository's default CodeQL setup, causing SARIF upload failures

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Remove unused Path import in test_hooks
  ([`8226380`](https://github.com/tardigrde/gcpath/commit/82263803827659955eb9e78e976cb3b8f5d48d54))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Resolve CodeQL false positives and improve test coverage
  ([`509df66`](https://github.com/tardigrde/gcpath/commit/509df665fc8992f14c0766064aa23919ec3c4357))

- Add custom CodeQL workflow with config that excludes test paths from URL sanitization checks
  (fixes 5 false-positive high severity alerts) - Add 23 targeted tests for hook commands, rich
  format outputs, fresh cache home view, and format validation (cli.py coverage 73% → 87%) - Add
  codecov.yml with appropriate thresholds (patch ≥80%, project ±2%)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Resolve SonarCloud issues across cli, hooks, and tests
  ([`5414569`](https://github.com/tardigrde/gcpath/commit/5414569d2d68fc2991ed2f7f7f44df1ac2992589))

- Extract _cache_status_rich and _stats_rich to reduce cognitive complexity (S3776) - Extract
  _validate_stats_resource helper for stats command - Remove unused params: ctx in _show_home, level
  in _prepare_hierarchy_command, target_resource_name in _ls_help_lines (S1172) - Replace duplicated
  "gcpath hook run" literal with _GCPATH_HOOK_COMMAND constant (S1192) - Extract _check_hook_entries
  to reduce get_hook_status complexity (S3776) - Fix unused variables in test_serializers.py (S1481)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Suppress CodeQL false positives in test assertions
  ([`8720d2c`](https://github.com/tardigrde/gcpath/commit/8720d2cb9bc293a1f63d6020b8720eae1771ce22))

The `in` operator on strings like "example.com" triggers CodeQL rule
  py/incomplete-url-substring-sanitization. These are test output assertions, not URL sanitization
  code — suppress with lgtm comments.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Test_ls_type_organization assertion for TOON output format
  ([`2872c99`](https://github.com/tardigrde/gcpath/commit/2872c993f67fc519349cdd652a6959936f360154))

- Use simple substring check instead of urlparse which fails on TOON comma-separated rows - Remove
  unused urlparse import to silence CodeQL false positive

### Chores

- **deps**: Bump requests in the uv group across 1 directory
  ([`29b2d81`](https://github.com/tardigrde/gcpath/commit/29b2d816cb43c0dacc07d223bf94dc4eb79f639f))

Bumps the uv group with 1 update in the / directory: [requests](https://github.com/psf/requests).

Updates `requests` from 2.32.5 to 2.33.0 - [Release notes](https://github.com/psf/requests/releases)
  - [Changelog](https://github.com/psf/requests/blob/main/HISTORY.md) -
  [Commits](https://github.com/psf/requests/compare/v2.32.5...v2.33.0)

--- updated-dependencies: - dependency-name: requests dependency-version: 2.33.0

dependency-type: indirect

dependency-group: uv ...

Signed-off-by: dependabot[bot] <support@github.com>

### Documentation

- Add Agent Skill section to README
  ([`be96998`](https://github.com/tardigrde/gcpath/commit/be96998baaf6167b996fc25ed4d36bde10c9054c))

Adds a dedicated section explaining the bundled agent skill and how to install it via bunx/npx, plus
  a one-liner callout in the "Why use gcpath" bullet list.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Add gcpath agent skill for AI agent consumption
  ([`30bd24f`](https://github.com/tardigrde/gcpath/commit/30bd24f41a001e8b167c7a1dab5925ef259b9933))

Adds a skills/gcpath/ directory following the Agent Skills spec (agentskills.io), enabling agents to
  install and use gcpath via:

bunx skills add github:tardigrde/gcpath --skill gcpath

Includes SKILL.md (when-to-use guidance, all commands with examples, common workflows, gotchas) and
  references/commands.md (compact flag reference per command).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Rewrite README to highlight agent-native design
  ([`32e4bd3`](https://github.com/tardigrde/gcpath/commit/32e4bd337c3fbcea6c828acddd3aee704d930897))

Restructure the README to lead with gcpath's agent-native qualities: read-only safety, AXI-compliant
  TOON output, ambient context hooks, and Agent Skill integration. Add output format comparison
  table and dedicated Agent Integration section with hook setup instructions.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **skill**: Enrich frontmatter and trim body per Agent Skills spec
  ([`531d4d5`](https://github.com/tardigrde/gcpath/commit/531d4d535edff873ec9cd517cd37d4ddd1a61435))

- Add allowed-tools: Bash(gcpath:*) Bash(uvx gcpath:*) - Add compatibility, license, and metadata
  fields - Trim SKILL.md from 258 to 143 lines: collapse verbose commands section into common
  workflows + key flags table, move full flag reference to references/commands.md with explicit load
  trigger - Keep gotchas inline per best-practices guidance

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

### Features

- Add AXI-compliant output with TOON format, hooks, and content-first home
  ([`1e10e8d`](https://github.com/tardigrde/gcpath/commit/1e10e8d8aa5906ab5a4094bb640ecb2de7f387cc))

Refactor gcpath from Rich-table-first output to AXI-compliant TOON-first output following the AXI
  specification (https://axi.md/).

New capabilities: - TOON format as default output (token-efficient, structured for AI agents) -
  `--format toon|json|yaml|rich` flag replaces old `--json`/`--yaml` flags - `--fields` flag for
  controlling output columns (replaces `--long`) - `--full` flag to expand truncated labels/tags -
  Content-first home view: `gcpath` with no args shows live dashboard - Pre-computed aggregates:
  `count: N of M total` on list outputs - Contextual `help[]` sections with next-step suggestions -
  Structured errors to stdout in TOON format (no more Rich stderr markup) - Ambient context hooks:
  `gcpath hook install` for Claude Code and Codex - `gcpath hook run` outputs compact session-start
  dashboard - Definitive empty states: `0 resources found` not empty output - All interactive
  prompts removed (no more `typer.confirm`)

New files: - `src/gcpath/toon.py` — TOON encoder wrapper + AXI helpers - `src/gcpath/hooks.py` —
  Claude Code / Codex session hook management - `tests/test_hooks.py` — Hook management tests

Design decisions: - `tree` keeps classic unicode tree output (not TOON) — agents use `ls -R` -
  `diagram` keeps raw Mermaid/D2 output with `--diagram-format` flag - `toon-format` library (git
  dep) handles TOON encoding

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add new Claude Code hook format support and README badges
  ([`cbfa81f`](https://github.com/tardigrde/gcpath/commit/cbfa81f1286570736dea649d91779c60a9e5eec0))

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.10.0 (2026-03-29)

### Bug Fixes

- Address PR review comments and SonarCloud findings
  ([`c756062`](https://github.com/tardigrde/gcpath/commit/c75606241587851f9224c4bf149bde1c9f6d8555))

- Remove unimplemented --show-labels/--show-tags from ancestors command - Deduplicate
  _matches_labels/_matches_tags into generic _matches_metadata - Deduplicate
  _format_labels/_format_tags into generic _format_metadata - Use scope_resource for tag lookups
  instead of always querying org root - Replace duplicated "organizations/" literal with
  _RESOURCE_PREFIX_ORGS constant - Sanitize user-controlled data from cache log message - Fix
  single-iteration loop in build_folder_ancestors (parsers.py) - Reduce cognitive complexity across
  cli.py, core.py, formatters.py, loaders.py, and parsers.py by extracting helper functions

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Findings
  ([`3be86b0`](https://github.com/tardigrde/gcpath/commit/3be86b03d357dfdae65d983db330bbecc3b1fa97))

### Chores

- Update uv.lock
  ([`ea0a688`](https://github.com/tardigrde/gcpath/commit/ea0a6889a087f6ed0a65423971526271bd238ce6))

https://claude.ai/code/session_01HugtU9fbaL97tbb7zaqNPL

- **deps**: Bump pyasn1 in the uv group across 1 directory
  ([`8adfd85`](https://github.com/tardigrde/gcpath/commit/8adfd8516d85343895dbd8189a907d86a7bb83cf))

Bumps the uv group with 1 update in the / directory: [pyasn1](https://github.com/pyasn1/pyasn1).

Updates `pyasn1` from 0.6.2 to 0.6.3 - [Release notes](https://github.com/pyasn1/pyasn1/releases) -
  [Changelog](https://github.com/pyasn1/pyasn1/blob/main/CHANGES.rst) -
  [Commits](https://github.com/pyasn1/pyasn1/compare/v0.6.2...v0.6.3)

--- updated-dependencies: - dependency-name: pyasn1 dependency-version: 0.6.3

dependency-type: indirect

dependency-group: uv ...

Signed-off-by: dependabot[bot] <support@github.com>

### Features

- Add GCP labels and tags support to CLI commands
  ([`d428c9a`](https://github.com/tardigrde/gcpath/commit/d428c9a161cd19cb928d39ffb8c9ba1d55916370))

Add opt-in support for GCP resource labels (key-value pairs) and resource tags (Tag Manager
  bindings) across CLI commands. Labels are fetched via an additional SQL column in Asset API
  queries (cheap). Tags require a separate Asset API query against TagBinding resources (expensive).
  Both are only fetched when explicitly requested via CLI flags.

New CLI options on ls, tree, find, ancestors: - --show-labels: display labels in output -
  --show-tags: display tags in output - --label key=value: filter by label (repeatable, ANDed) -
  --tag key=value: filter by tag (repeatable, ANDed)

Changes across the stack: - core.py: labels/tags fields on Folder and Project dataclasses -
  parsers.py: extract_labels() and has_labels param on parse functions - loaders.py: include_labels
  in SQL builders, load_tags_asset/apply_tags - cache.py: bump CACHE_VERSION to 2,
  serialize/deserialize labels+tags - serializers.py: include labels/tags in JSON/YAML output when
  non-empty - formatters.py: show labels/tags in tree view labels

https://claude.ai/code/session_01HugtU9fbaL97tbb7zaqNPL


## v0.9.0 (2026-03-19)

### Bug Fixes

- Address PR review feedback — narrow exception handling and improve consistency
  ([`d358e26`](https://github.com/tardigrde/gcpath/commit/d358e265f407a637f3092d07480eb369b0433393))

- Narrow bare `except Exception` in `_resolve_scope()` to catch only `PermissionDenied`, `NotFound`,
  and `GCPathError` - Move `import fnmatch` from local scope to top-level imports (PEP 8) - Add
  detailed comment explaining base_segments depth calculation - Make PermissionDenied handling
  consistent in `_fetch_chain_link()`: folders and projects now use graceful fallback like
  organizations

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Reduce cognitive complexity and extract constants for SonarCloud
  ([`819f5dd`](https://github.com/tardigrde/gcpath/commit/819f5dd0df2903cd3be4ba150444c2989c92799d))

- Extract _fetch_chain_link() from resolve_ancestry_chain() to reduce cognitive complexity from 25
  to under 15 - Extract _search_hierarchy() from find command to reduce complexity - Extract
  _get_node_parent_name(), _get_child_folders() in formatters to reduce build_tree_view() complexity
  from 18 to under 15 - Extract _node_to_dict(), _get_child_folders() in serializers to reduce
  serialize_tree_node() complexity from 18 to under 15 - Add
  _PREFIX_ORGS/_PREFIX_FOLDERS/_PREFIX_PROJECTS constants in core.py to replace duplicated string
  literals

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Resolve CI failures, CodeQL alerts, and eager client initialization
  ([`d054977`](https://github.com/tardigrde/gcpath/commit/d054977d4be99fc16bc9c06ae2f339fa0450a7f4))

- Add missing resolve_ancestry mock to two tests that pass a positional resource to `ls -l`, which
  triggers _resolve_scope() → resolve_ancestry() and fails in CI without GCP credentials - Fix 4
  CodeQL "Incomplete URL substring sanitization" alerts by replacing `"example.com" in
  result.stdout` substring checks with exact-match alternatives (split()/list comprehension) -
  Lazily initialize GCP API clients in resolve_ancestry() so only the client needed for the given
  resource prefix triggers credential lookup

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Resolve remaining SonarCloud issues — constants and complexity
  ([`6257f97`](https://github.com/tardigrde/gcpath/commit/6257f97a42a7e42593214cb51f753853b8f44432))

- Replace all bare "organizations/", "folders/", "projects/" string literals in core.py with
  _PREFIX_ORGS/_PREFIX_FOLDERS/_PREFIX_PROJECTS - Simplify _search_hierarchy() by extracting
  _get_resource_display_name() and _get_resource_path() helpers, using a flat candidate list with
  list comprehension instead of nested loops

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Use explicit equality checks to resolve CodeQL URL sanitization alerts
  ([`26f4896`](https://github.com/tardigrde/gcpath/commit/26f489676b5fc68dc7a452b79acd10517d68eaf5))

Replace `"example.com" in result.stdout.split()` with `any(token == "example.com" for token in ...)`
  to avoid CodeQL's incomplete-url-substring-sanitization rule, which still triggers on `in` with
  split lists.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Documentation

- Document find, ancestors, --type filter, -L depth limit, and structured output
  ([`ce92751`](https://github.com/tardigrde/gcpath/commit/ce92751f6a39b8cab7cf21a4f8405a93dddac37c))

Add README sections for features from PR #26 (--json/--yaml structured output) and PR #28 (find
  command, ancestors command, --type filter on ls/tree, -L depth limit on ls -R). Updates Quick
  Start and Features summary accordingly.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Features

- Add --type filter, find command, ancestors command, and -L depth limit
  ([`25e1ded`](https://github.com/tardigrde/gcpath/commit/25e1ded729a141a5ddbf50283b4aa2c06f642af9))

Add four new features to gcpath CLI:

- `--type`/`-t` filter on `ls` and `tree` commands (folder, project, organization) - `find` command
  for glob-style name search with optional type and scope filters - `ancestors` command to show full
  ancestry chain from resource to org root - `--level`/`-L` depth limit on `ls -R` for recursive
  listing

Refactors scope resolution into shared `_resolve_scope()` helper to reduce duplication between `ls`
  and `find` commands.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


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
