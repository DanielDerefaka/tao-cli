# Contributing to taox

Thank you for your interest in contributing to taox! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- Python 3.9 or higher
- [btcli](https://github.com/opentensor/bittensor) (for full functionality)
- Git

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/taox-project/taox.git
   cd taox
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install in development mode**
   ```bash
   pip install -e ".[dev]"
   ```

4. **Verify installation**
   ```bash
   taox --version
   taox doctor
   ```

## Development Workflow

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=taox --cov-report=term-missing

# Run specific test file
pytest tests/test_executor.py -v
```

### Code Quality

We use automated tools to maintain code quality:

```bash
# Format code
black src/ tests/

# Lint code
ruff check src/ tests/

# Type checking (optional but recommended)
mypy src/taox/
```

### Pre-commit Checks

Before submitting a PR, ensure:

1. All tests pass: `pytest`
2. Code is formatted: `black --check src/ tests/`
3. No lint errors: `ruff check src/ tests/`

## Project Structure

```
taox/
├── src/taox/
│   ├── chat/          # LLM integration and conversation handling
│   ├── commands/      # Command implementations (stake, wallet, etc.)
│   ├── config/        # Configuration management
│   ├── data/          # API clients (Taostats, SDK)
│   ├── security/      # Credentials and confirmation
│   ├── ui/            # Console output and prompts
│   └── cli.py         # Main entry point
├── tests/             # Test suite
├── docs/              # Documentation
└── pyproject.toml     # Project configuration
```

## Making Changes

### Branch Naming

- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation changes
- `refactor/description` - Code refactoring

### Commit Messages

Write clear, concise commit messages:

```
Add validator search with fuzzy matching

- Implement fuzzy search using name similarity
- Add caching for search results
- Include tests for edge cases
```

### Pull Request Process

1. **Fork the repository** and create your branch from `main`
2. **Make your changes** with appropriate tests
3. **Update documentation** if needed
4. **Run quality checks** (tests, lint, format)
5. **Submit a PR** with a clear description

### PR Description Template

```markdown
## Summary
Brief description of changes

## Changes
- Change 1
- Change 2

## Testing
How to test these changes

## Checklist
- [ ] Tests pass
- [ ] Code formatted with black
- [ ] No ruff lint errors
- [ ] Documentation updated (if needed)
```

## Testing Guidelines

### Writing Tests

- Place tests in the `tests/` directory
- Name test files `test_*.py`
- Use descriptive test names: `test_stake_with_valid_amount`
- Use fixtures from `conftest.py` for common setup

### Demo Mode Testing

Use demo mode for safe testing without real network calls:

```bash
# Run taox in demo mode
taox --demo chat

# Tests automatically run in demo mode
pytest  # TAOX_DEMO_MODE=true is set in conftest.py
```

### Mocking External Services

```python
@pytest.fixture
def mock_taostats_client():
    """Mock TaostatsClient for testing."""
    from taox.data.taostats import Validator, PriceInfo
    client = MagicMock()
    # ... setup mocks
    return client
```

## Code Style

### Python Style

- Follow [PEP 8](https://pep8.org/)
- Use type hints for function signatures
- Maximum line length: 100 characters
- Use docstrings for public functions

### Example

```python
def stake_to_validator(
    amount: float,
    validator_hotkey: str,
    netuid: int,
    wallet_name: str = "default",
) -> StakeResult:
    """Stake TAO to a validator.

    Args:
        amount: Amount of TAO to stake
        validator_hotkey: SS58 address of the validator
        netuid: Subnet ID
        wallet_name: Name of the wallet to use

    Returns:
        StakeResult with transaction details
    """
    ...
```

## Getting Help

- **Issues**: Report bugs or request features via GitHub Issues
- **Discussions**: Ask questions in GitHub Discussions
- **Security**: Report vulnerabilities via SECURITY.md

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
