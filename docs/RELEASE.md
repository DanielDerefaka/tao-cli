# Release Process

This document describes how to release a new version of taox.

## Version Numbering

taox follows [Semantic Versioning](https://semver.org/):

- **MAJOR**: Breaking changes to the CLI interface or API
- **MINOR**: New features, backward compatible
- **PATCH**: Bug fixes, backward compatible

## Pre-Release Checklist

Before releasing, ensure:

1. **All tests pass**
   ```bash
   pytest -v
   ```

2. **Code quality checks pass**
   ```bash
   black --check src/ tests/
   ruff check src/ tests/
   ```

3. **Documentation is updated**
   - [ ] README.md reflects current features
   - [ ] CHANGELOG.md has release notes
   - [ ] Any new commands are documented

4. **Version numbers are updated**
   - [ ] `pyproject.toml` - `version = "X.Y.Z"`
   - [ ] `src/taox/__init__.py` - `__version__ = "X.Y.Z"`

## Release Steps

### 1. Update Version

Update version in both files:

```python
# pyproject.toml
version = "0.2.0"

# src/taox/__init__.py
__version__ = "0.2.0"
```

### 2. Update Changelog

Add release notes to `CHANGELOG.md`:

```markdown
## [0.2.0] - 2024-XX-XX

### Added
- New feature description

### Changed
- Changed feature description

### Fixed
- Bug fix description
```

### 3. Create Release Commit

```bash
git add pyproject.toml src/taox/__init__.py CHANGELOG.md
git commit -m "Release v0.2.0"
git push origin main
```

### 4. Create Git Tag

```bash
git tag -a v0.2.0 -m "Release v0.2.0"
git push origin v0.2.0
```

### 5. Create GitHub Release

1. Go to GitHub → Releases → "Create a new release"
2. Select the tag `v0.2.0`
3. Title: `v0.2.0`
4. Description: Copy from CHANGELOG.md
5. Click "Publish release"

### 6. Automated PyPI Publish

The GitHub Actions workflow will automatically:
1. Build the package
2. Publish to PyPI

This uses [trusted publishing](https://docs.pypi.org/trusted-publishers/) - no API token needed.

## Manual PyPI Publish (if needed)

If automated publishing fails:

```bash
# Install build tools
pip install build twine

# Build package
python -m build

# Check package
twine check dist/*

# Upload to PyPI
twine upload dist/*
```

## Post-Release

After releasing:

1. **Verify PyPI**
   ```bash
   pip install taox==0.2.0
   taox --version
   ```

2. **Announce** (if applicable)
   - Discord/Telegram
   - Twitter
   - Blog post

3. **Start next cycle**
   - Update version to `0.3.0-dev` (optional)
   - Create issues for next milestone

## Hotfix Process

For urgent bug fixes:

1. Create branch from tag
   ```bash
   git checkout -b hotfix/0.2.1 v0.2.0
   ```

2. Fix the bug and test

3. Update version to `0.2.1`

4. Merge to main and tag
   ```bash
   git checkout main
   git merge hotfix/0.2.1
   git tag -a v0.2.1 -m "Hotfix v0.2.1"
   git push origin main --tags
   ```

## Version History

| Version | Date | Notes |
|---------|------|-------|
| 0.1.0 | 2024-XX-XX | Initial release |

## PyPI Project Setup

### First-Time Setup

1. Create account at [pypi.org](https://pypi.org)
2. Go to Account Settings → Publishing
3. Add trusted publisher:
   - Owner: `your-username`
   - Repository: `taox`
   - Workflow: `release.yml`

### Test PyPI (Optional)

For testing releases:

```bash
# Upload to Test PyPI
twine upload --repository testpypi dist/*

# Install from Test PyPI
pip install --index-url https://test.pypi.org/simple/ taox
```
