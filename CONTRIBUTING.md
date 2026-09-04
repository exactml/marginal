# Contributing

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Lint

```bash
make lint     # check
make format   # auto-fix
```

## Test

```bash
make test
```

Optionally, install the pre-commit hooks so lint runs automatically before
each commit:

```bash
pip install pre-commit
pre-commit install
```

## Package layout

```text
marginal/
├── config/     # repo-local config loading
├── providers/  # model provider abstraction (BYOK)
├── context/    # diff, git history, dependency detection
├── graph/      # code graph
├── policy/     # policy engine
├── agent/      # orchestration loop
├── review/     # validation, dedup, confidence scoring
├── github/     # GitHub API integration, auth
└── cli/        # command entry points
```

See [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) for the full specification
and [`docs/adr/`](docs/adr/) for recorded architecture decisions.
