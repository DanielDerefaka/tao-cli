# What to Commit

Quick reference for contributors on what belongs in version control.

## ✅ Commit These

**Source code**: `src/**/*.py`, `tests/**/*.py`

**Config templates**: `pyproject.toml`, `.env.example`, `config.example.yaml`

**Docs**: `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/*.md`

**GitHub**: `.github/workflows/*.yml`, issue templates, `.gitignore`

**Other**: `LICENSE`

## ❌ Never Commit

**Secrets**
- `.env` (contains API keys)
- `*.pem`, `*.key`, `credentials.json`
- Anything with real API keys or passwords

**Wallet data**
- Wallet files, coldkeys, hotkeys
- Seed phrases / mnemonics

**Generated files**
- `dist/`, `build/`, `*.egg-info/`
- `__pycache__/`, `.pytest_cache/`
- `.coverage`, `htmlcov/`

**Personal files**
- `.idea/`, `.vscode/`
- `.DS_Store`
- `*.log`

## 🟡 Templates Only

| Commit this | Never commit |
|-------------|--------------|
| `.env.example` | `.env` |
| `config.example.yaml` | `~/.taox/config.yaml` |

## Before Committing

```bash
# Check what's staged
git diff --cached

# Look for secrets
git diff --cached | grep -iE "(key|token|secret|password)"
```

## If You Committed a Secret

1. **Rotate the key immediately** at the source (Chutes, Taostats, etc.)
2. Remove from git history using `git filter-branch` or BFG
3. Force push and notify maintainers
