<h1 align="center" style="border-bottom: none">marginal</h1>
<h3 align="center" style="border-bottom: none">The Open Source Engineering Intelligence Agent for Pull Requests</h3>

<p align="center">
marginal reviews pull requests the way a senior engineer who knows your whole codebase would — not just the diff. It reasons over your code graph, git history, engineering policies, ownership, and cross-repository impact to produce <b>high-confidence, actionable feedback</b>, and it runs entirely on infrastructure you control.
</p>

<div align="center">

[![License](https://img.shields.io/github/license/exactml/marginal)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/exactml/marginal?style=social)](https://github.com/exactml/marginal)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#contributing)

</div>

<p align="center">
   <a href="docs/REQUIREMENTS.md"><strong>Specification</strong></a> ·
   <a href="#configuration"><strong>Configuration</strong></a> ·
   <a href="#roadmap"><strong>Roadmap</strong></a> ·
   <a href="#contributing"><strong>Contributing</strong></a>
</p>

<br>

## Why marginal

Diff-only review tools comment on what changed without understanding what it touches. They miss the breaking change in a shared library three repos away, the architecture rule a new handler quietly violates, the technical debt a PR is about to make worse. And most of them require sending your source code to someone else's inference service.

marginal is built around a different bet: **context beats volume**. One well-evidenced finding that traces a regression to its root cause is worth more than ten shallow comments — and a reviewer that runs on your own infrastructure, with your own model keys, is one you can actually trust with your whole codebase.

## How it works

```text
                    GitHub
                      |
               GitHub Actions
                      |
                      v
              +---------------+
              |   marginal    |
              |     Agent     |
              +-------+-------+
                      |
        +-------------+-------------+
        |             |             |
        v             v             v
   Code Graph     Policy Engine   Git Context
        |             |             |
        +-------------+-------------+
                      |
                Agent / Planner
                      |
             +--------+--------+
             |                 |
             v                 v
        Model Provider     Validation
        (BYOK)             / Deduplication
             |                 |
             +--------+--------+
                      |
                      v
                 GitHub PR
```

The agent inspects the PR, walks the code graph, checks it against your policies and ownership rules, and pulls in git history and dependency context — then validates, deduplicates, and ranks every candidate finding before anything reaches GitHub. Nothing ships to a comment unless it clears your confidence threshold.

## What it reviews for

- **Context over diff** — changed code is understood in terms of callers, callees, interfaces, tests, and the repositories that depend on it, not in isolation.
- **Breaking changes** — signature changes, removed fields, schema changes, and incompatible library updates, flagged with the affected consumers as evidence.
- **Dependency intelligence** — when a PR bumps a dependency, marginal correlates the upstream changelog against how your code actually uses it, and only speaks up when something you rely on actually changed.
- **Architecture & policy drift** — deviations from the rules your team has written down in `.marginal/policies/`, evaluated against real repository relationships, not vibes.
- **Ownership & technical debt** — findings are connected to CODEOWNERS and known debt items, without pinging anyone unless you've explicitly enabled it.

## Quickstart

```bash
marginal init
```

```text
✓ Created .marginal/config.yaml
✓ Created .marginal/policies/
✓ Created .github/workflows/marginal.yml

marginal is ready.
```

```yaml
# .github/workflows/marginal.yml
on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: exactml/marginal-action@v1
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

Open a PR, and marginal builds context, reasons over the change, and posts inline comments plus a summary — all inside your own GitHub Actions run.

_marginal is under active, in-the-open development — this is the interface it's being built toward. Follow [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) for current scope, or jump into [Issues](https://github.com/exactml/marginal/issues) to help build it._

## Configuration

Everything lives in your repository, version-controlled alongside your code:

```text
.marginal/
├── config.yaml
├── policies/
│   ├── coding.md
│   ├── architecture.md
│   └── review.md
└── ...
```

```yaml
version: 1

review:
  enabled: true
  inline_comments: true
  confidence_threshold: 0.85
  max_comments: 8
  tone: concise

context:
  git_history: true
  code_graph: true
  cross_repository: true

models:
  planner:
    provider: anthropic
    model: claude-sonnet
  reviewer:
    provider: openai
    model: codex
```

API keys are never stored in configuration — only in your CI secrets or environment. See the full [specification](docs/REQUIREMENTS.md) for every option.

## Run it anywhere

The same core agent runs as:

- **GitHub Actions** — the primary integration, zero infrastructure to operate
- **Docker** — one image, the full runtime
- **CLI** — `marginal review` for local runs
- **Self-hosted runners** — for orgs that need everything on their own network

No step requires code to leave your infrastructure, and no step requires a marginal-hosted service.

## Roadmap

marginal is being built in three horizons:

```text
Repository Intelligence  →  Organization Intelligence  →  Engineering Intelligence
```

Today's focus is getting the core loop right on a single repository: diff and repository context, code graph, policies, and high-signal inline review. From there: cross-repository impact analysis, architecture drift detection, an evaluation framework for benchmarking review quality across models, and a local UI for visibility into everything the agent does. The long-term goal is an agent that can answer not just "is this code correct?" but "does this PR actually satisfy the requirement it was written for?"

See [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) for the full specification driving this.

## Contributing

marginal is being designed in the open, and there's no ship deadline forcing shortcuts — it's built to grow with contributors, not around a single team's timeline. Design discussion, issues, and PRs against both the code and the specification are welcome. A good place to start is [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md).

## License

[MIT](LICENSE)
