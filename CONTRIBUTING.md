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
make test            # tests/unit/, free: no model calls
make review-quality  # tests/integration/review_quality/, calls the model
```

`make test` runs the unit tests in `tests/unit/`. They mock GitHub and the
model, so they're fast and free. Run them before every push.

Optionally, install the pre-commit hooks so lint runs automatically before
each commit:

```bash
pip install pre-commit
pre-commit install
```

`make review-quality` runs the review-quality benchmark in
`tests/integration/review_quality/`: every **attempt** in `cases.yml` (a
review tool with one provider and model: today marginal and
[PR-Agent](https://github.com/qodo-ai/pr-agent), both with Claude Opus 5.5)
reviews every case once (`make review-quality RUNS=3` for more), and
`score.py` compares each attempt with its own line in `baseline.json`. It
needs each attempt's provider key (and
`GITHUB_TOKEN` for the GitHub API), and it **costs money**. You don't need to
run it for a normal PR: it runs on every release PR, one GitHub Actions job
per attempt. To benchmark another model, add an attempt to `cases.yml`; to run
one locally, `python tests/integration/review_quality/run.py --attempt
marginal/anthropic/claude-opus-5-5`. The PR-Agent attempt runs PR-Agent in its
plain-diff mode, which never contacts GitHub, from its own Python 3.12+
environment: `pip install pr-agent==0.49.0` there and point
`PR_AGENT_PYTHON` at that environment's `python`.

### Adding a benchmark case

A case is a real PR from a public repo: one that introduced a bug someone
later fixed or reverted, or a clean PR with nothing to flag.

- **Propose one** with the
  [Benchmark case](https://github.com/exactml/marginal/issues/new?template=benchmark_case.yml)
  issue form. A maintainer checks it and adds it.
- **Or add it to `cases.yml` directly** in a PR: pin the base and head SHAs,
  link the PR that introduced the bug (`source`) and the fix or revert that
  proves it (`evidence`), and give the file, line range, and expected
  severity. A case without evidence won't be merged.

Rate the expected severity the way the reviewer is told to, by how bad the
effect is when it happens and how likely it is to happen:

| Severity | Meaning |
|---|---|
| `critical` | A security hole someone can use (an auth or permission check that can be skipped, injection, a leaked secret), data loss, or a wrong result for every user |
| `high` | A wrong result or a crash on a normal, realistic input |
| `medium` | Wrong only in an edge case, or it works but worse (slower, noisier) |
| `low` | A small effect, unlikely to matter in practice |

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

## Before asking for a merge: prove it

A PR is ready when there's evidence it works, not just a claim. Add an
**Evidence** section to the PR body covering:

| Check | Evidence |
|---|---|
| CI | every check green (`lint-and-test`, `fragment`, `review`) |
| Tests | `make lint && make test` output |
| marginal | each of marginal's findings on the PR is fixed or answered in its thread, none left open |
| Cleanup | a pass over the diff for dead code and needless complexity, each point applied or dismissed |
| E2E | for changes to what a team sees on a PR: a real review on [marginal-client](https://github.com/exactml/marginal-client) with your branch (a maintainer runs this if you lack access) |

With [Claude Code](https://claude.com/claude-code), the `prove-it` skill in
`.claude/skills/` runs every check and writes the section for you:

```text
/prove-it #123
```

The evidence is tied to the PR's latest commit, so run it again after a push.

## Package layout

```text
marginal/
├── config/     # repo-local config loading
├── providers/  # model provider abstraction (BYOK)
├── context/    # diff, git history, dependency detection
├── graph/      # code graph
├── policy/     # policy engine
├── agent/      # orchestration loop
├── review/     # findings, evidence checks, dedup, redaction
├── github/     # GitHub API integration, auth
└── cli/        # command entry points
```

See [`docs/adr/`](docs/adr/) for recorded architecture decisions.
