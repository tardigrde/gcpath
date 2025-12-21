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

## Automated Versioning and Releases

We use [Python Semantic Release](https://python-semantic-release.readthedocs.io/) to automate:
- Version bumping based on commit messages
- CHANGELOG generation
- Git tag creation
- GitHub Release creation
- PyPI publishing

This runs automatically on every push to `main` via GitHub Actions (`.github/workflows/release.yml`).
