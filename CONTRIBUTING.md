# Contributing to mcpool

Thank you for your interest in contributing to **mcpool**!

## Development Setup

```bash
git clone https://github.com/adwantg/mcp-pool.git
cd mcp-pool
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Quality Bar

All contributions must pass:

```bash
# Tests (90% coverage minimum)
pytest -v --cov=mcpool --cov-report=term-missing

# Linting
ruff check src/ tests/
ruff format --check src/ tests/

# Type checking
mypy src/
```

## Pull Request Process

1. Fork the repository and create a feature branch.
2. Write tests for new functionality.
3. Ensure all checks pass locally.
4. Submit a PR with a clear description of changes.

## Code Style

- Follow `ruff` formatting conventions.
- Use type annotations everywhere.
- Docstrings on all public APIs.

## Reporting Issues

Open an issue at https://github.com/adwantg/mcp-pool/issues with:
- Python version, OS, and `mcp-pool` version.
- Minimal reproduction steps.
- Expected vs. actual behavior.
