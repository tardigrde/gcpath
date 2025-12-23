# Development Workflow

## Branching Strategy

All changes must be developed on feature branches and merged via Pull Requests.

### Branch Naming Convention

- `feat/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation updates
- `chore/description` - Maintenance tasks
- `refactor/description` - Code refactoring

### Workflow Steps

1. **Create a feature branch**:

   ```bash
   git checkout -b feat/your-feature-name
   ```

2. **Make your changes** and commit using [Conventional Commits](https://www.conventionalcommits.org/):

   ```bash
   git commit -m "feat: add new feature"
   git commit -m "fix: resolve bug in core logic"
   git commit -m "docs: update README"
   ```

3. **Push your branch**:

   ```bash
   git push origin feat/your-feature-name
   ```

4. **Create a Pull Request** on GitHub targeting `main`.

5. **Wait for CI checks** to pass (tests, lint, typecheck).

6. **Merge** the PR (squash and merge recommended).

7. **Automated versioning** will trigger on merge to `main` (see below).

## Conventional Commits

Use semantic commit messages to enable automated versioning:

- `feat:` - Triggers a **minor** version bump (0.x.0)
- `fix:` - Triggers a **patch** version bump (0.0.x)
- `BREAKING CHANGE:` in footer - Triggers a **major** version bump (x.0.0)
- `chore:`, `docs:`, etc. - No version bump

Example:

```
feat: add support for custom labels

Add --label flag to filter resources by labels.

Closes #123
```

## Development and Testing

### Setup Development Environment

1. **Clone your fork**:

   ```bash
   git clone https://github.com/your-org/gcpath.git
   cd gcpath
   ```

2. **Install dependencies** using `uv`:

   ```bash
   uv sync
   ```

3. **Authenticate with GCP**:

   ```bash
   gcloud auth application-default login
   ```

### Running Tests

Run the full test suite:

```bash
uv run pytest tests/ -v
```

Run specific tests:

```bash
uv run pytest tests/test_cli.py::test_ls_command -v
```

Run with coverage:

```bash
uv run pytest tests/ --cov=gcpath --cov-report=term-missing
```

### Testing Both API Modes

gcpath supports two APIs: Cloud Asset API (default) and Resource Manager API. Both should be tested:

**Test with Cloud Asset API (default):**

```bash
uv run gcpath ls
uv run gcpath tree
```

**Test with Resource Manager API:**

```bash
uv run gcpath ls --no-use-asset-api
uv run gcpath tree -U
```

**Automated tests** mock both API modes, so running `pytest` tests both implementations.

### Linting and Type Checking

Before submitting a PR, ensure your code passes all checks:

```bash
# Run linter
make lint
# or: uv run ruff check src/ tests/

# Run type checker
make typecheck
# or: uv run mypy src/

# Run all tests
make test
# or: uv run pytest tests/
```

All three must pass before merging.

## Automated Versioning and Releases

We use [Python Semantic Release](https://python-semantic-release.readthedocs.io/) to automate:

- Version bumping based on commit messages
- CHANGELOG generation
- Git tag creation
- GitHub Release creation
- PyPI publishing

This runs automatically on every push to `main` via GitHub Actions (`.github/workflows/release.yml`).
