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

## Changelog

Don't edit `CHANGELOG.md` directly. Instead, add one file to `changelog.d/`
named `<issue>.<type>.md`, where `<type>` is one of:

| Type          | CHANGELOG section |
|---------------|-------------------|
| `breaking`    | Breaking Changes  |
| `feature`     | New Features      |
| `improvement` | Improvements      |
| `fix`         | Fixes             |
| `warning`     | Warnings          |

The file holds the entry text, ending with a line that links the issue and
PR and credits the PR author. For example, `changelog.d/77.feature.md`:

```markdown
Added `marginal help` and `marginal help <command>`, which print the usage
for the whole CLI or for one subcommand

([ISSUE-77](https://github.com/exactml/marginal/issues/77),
[PR-78](https://github.com/exactml/marginal/pull/78) by [@HarshRajSinghania](https://github.com/HarshRajSinghania))
```

Don't know the PR number yet? Open the PR first, then fill it in. To preview
how your entry will render in the next release:

```bash
towncrier build --draft --version next
```

At release time, `towncrier build` collects every fragment into a new
`CHANGELOG.md` section and deletes them.

CI fails a PR that adds no fragment. For a change users won't notice (a
typo fix, a CI tweak, a test-only refactor), a maintainer can add the
`skip-changelog` label instead.

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

See [`docs/adr/`](docs/adr/) for recorded architecture decisions.
