<h1 align="center" style="border-bottom: none">marginal</h1>
<h3 align="center" style="border-bottom: none">The Open Source Engineering Intelligence Agent for Pull Requests</h3>

<p align="center">
marginal reviews pull requests the way a senior engineer who knows your codebase would — not just the diff. It reads the code your change touches, checks it against the rules your team has written down, and posts only <b>findings it can back with evidence from your code</b>, running entirely on infrastructure you control.
</p>

<div align="center">

[![License](https://img.shields.io/github/license/exactml/marginal)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/exactml/marginal?style=social)](https://github.com/exactml/marginal)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#contributing)

</div>

<p align="center">
   <a href="#quickstart"><strong>Quickstart</strong></a> ·
   <a href="#the-marginal-family"><strong>Packages</strong></a> ·
   <a href="#configuration"><strong>Configuration</strong></a> ·
   <a href="#contributing"><strong>Contributing</strong></a>
</p>

<br>

## Why marginal

Diff-only review tools comment on what changed without understanding what it touches. They miss the caller in another file that a signature change just broke, or the rule a new handler quietly violates. And most of them require sending your source code to someone else's inference service.

marginal is built around a different bet: **context beats volume**. One well-evidenced finding that traces a regression to its root cause is worth more than ten shallow comments — and a reviewer that runs on your own infrastructure, with your own model keys, is one you can actually trust with your whole codebase.

## How it works

```text
         pull request (GitHub Actions)
                      |
                      v
        +---------------------------+
        |     diff (lockfiles and   |
        |   ignore_paths left out,  |
        |    secrets redacted)      |
        +-------------+-------------+
                      |
        +-------------+-------------+
        |             |             |
        v             v             v
   Code graph      Policies    Earlier replies
 (callers outside  & anti-     on marginal's
   the diff)       policies    own comments
        |             |             |
        +-------------+-------------+
                      |
                      v
            Your model (BYOK or local)
                      |
                      v
   evidence check · comment cap · dedup
                      |
                      v
       inline comments + summary on the PR
```

marginal builds one prompt from the diff and the context around it and asks your model for structured findings. Each finding has to show its work: the trigger that makes it go wrong, and the exact lines it rests on. marginal checks those lines against your code, with no second model call, and posts only the findings whose evidence holds. On later pushes it checks its earlier findings again and resolves the ones the new code fixed.

## What it reviews for

- **Context over diff** — when a PR changes a function, marginal finds its callers outside the diff and shows them to the model, so a change that breaks one of them is flagged with that caller as evidence. (The caller index covers Python today.)
- **Your team's rules** — Markdown policies in `.marginal/policies/` are checked against every diff, and anti-policies list the deliberate tradeoffs marginal must never re-litigate.
- **Findings that show their work** — each posted finding quotes the lines it rests on and names its trigger, in a folded "Why marginal flagged this" block. A finding whose quote isn't in your code, or whose trigger names no real code, is dropped, not posted.
- **Quiet by design** — evidence-checked findings and a comment cap, no repeated findings across pushes, findings closed once a later push fixes them, and a maintainer's reply taken into account on the next review.
- **Team-friendly defaults** — drafts, bot PRs, and PRs labelled `skip-review` are skipped, and lockfiles and minified assets never reach the model.

## Review quality

Every release is scored on a fixed set of real PRs from public repos: PRs that introduced a bug someone later fixed, and clean PRs with nothing to flag. **24 cases from 9 repos** (mlflow, Django, scikit-learn, celery, aiohttp, Starlette, click, pytest, setuptools): 18 bugs and 6 clean PRs, each answer key checked against the upstream fix. [PR-Agent](https://github.com/qodo-ai/pr-agent) runs on the same cases, model and key, for comparison.

| Metric | What it measures | marginal · Claude Opus 5.5 | PR-Agent · Claude Opus 5.5 |
|---|---|--:|--:|
| Recall | known bugs the reviewer posted a finding for | 🟡 0.73 | 🟡 0.73 |
| Recall before rules | known bugs the model raised, posted or not | 🟡 0.73 | 🟡 0.73 |
| Precision | posted findings that point at a known bug | 🟢 1.00 | 🟢 1.00 |
| Accuracy per PR | bug PRs with a hit, clean PRs with no findings | 🟢 0.88 | 🟢 0.83 |
| Severity accuracy | hits rated at or above the expected severity | 🟢 0.81 | ⚪ n/a |
| Evidence accuracy | hits whose verified quotes include the bug's own lines | 🟢 1.00 | ⚪ n/a |
| Time | median seconds per review | 20.8 | 16.0 |
| Cost | model cost in USD of reviewing all 24 cases once | $1.14 | $1.16 |

🟢 0.80 or more, 🟡 0.50 or more, 🔴 below 0.50, ⚪ not measured (PR-Agent rates no severity and quotes no evidence). marginal v0.3.0, one run per case ([run 40756859982](https://github.com/exactml/marginal/actions/runs/40756859982), 2026-10-28).

marginal posts every bug its model raises that it can back with a verified quote: Recall equals Recall before rules. Before v0.3.0 it posted only findings whose self-rated confidence cleared a threshold, and its Recall was 0.41 at 0.6 (0.05 at the old 0.85 default) while the model had raised 0.82 of the known bugs ([#200](https://github.com/exactml/marginal/issues/200)).

Neither tool posted a finding on any clean PR. The cases are in [`cases.yml`](tests/integration/review_quality/cases.yml). Know a PR that belongs there? Propose it with the [Benchmark case](https://github.com/exactml/marginal/issues/new?template=benchmark_case.yml) form.

## Safe to run on your code

- **Your infrastructure, your keys** — marginal runs in your own GitHub Actions (or on your machine) and calls your model provider with your key, or a local model with none. There is no marginal service.
- **Secrets stay out of the prompt** — likely secrets (API keys, tokens, private keys, passwords inside URLs) are replaced with `[REDACTED]` in the diff and in every code snippet before the model sees them, and the summary tells you when that happened.
- **A PR can't rewrite its own rules** — config and policies always come from the PR's base branch, so a PR (or the agent that wrote it) can't switch its review off or add an anti-policy to silence a finding.
- **Least privilege** — marginal reads the PR and posts review comments, nothing more. It never pushes code, and `permissions` in the config limits what it may read and write.

## Quickstart

```bash
marginal init
```

```text
✓ Created .marginal/config.yaml
✓ Created .marginal/policies/
✓ Created .marginal/policies/README.md
✓ Created .github/workflows/marginal.yml

marginal is ready.

Next steps -- pick one provider:

  1. In .marginal/config.yaml, set the reviewer model:

       models:
         reviewer:
           provider: anthropic    # or: openai
           model: <model id>

  2. Add that provider's API key as a repository secret:

       gh secret set ANTHROPIC_API_KEY    # provider: anthropic
       gh secret set OPENAI_API_KEY       # provider: openai

The workflow already passes both secrets, so nothing else needs editing.
Open a pull request to get your first review.
```

```yaml
# .github/workflows/marginal.yml
name: marginal

on:
  pull_request:
    # ready_for_review: a draft is skipped (review.skip_drafts), so review it
    # once it's marked ready rather than waiting for the next push.
    types: [opened, synchronize, reopened, ready_for_review]

# One review per PR at a time: two runs started by quick successive pushes
# would each miss the other's review and post the same header twice.
concurrency:
  group: marginal-${{ github.event.pull_request.number }}
  cancel-in-progress: false

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
      # Resolving a review thread (marginal closes ones a later push fixed)
      # needs contents: write; marginal never pushes.
      contents: write
    steps:
      - uses: exactml/marginal-action@v1
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          # Only the key for the provider in .marginal/config.yaml is used;
          # the other secret can stay unset.
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
```

Open a PR, and marginal builds context, reasons over the change, and posts inline comments plus a summary — all inside your own GitHub Actions run.

### Check your setup

`marginal doctor` checks everything a review needs, without calling a model or posting anything: that `.marginal/config.yaml` is valid, that `models.reviewer` is set and each configured provider's API key is in the environment, that `permissions` let `marginal review` read the PR, and that `GITHUB_TOKEN` is set. If `permissions.write.comments` is off it prints a note rather than a failure, since `--comment` is only needed to post. With `--repo`, it also makes one read-only GitHub call to confirm the token is accepted and the repository is reachable.

```bash
marginal doctor --repo owner/name
```

```text
✓ .marginal/config.yaml is valid
✗ models.reviewer: the 'anthropic' provider requires the ANTHROPIC_API_KEY environment variable to be set
    → export it in your shell, and add it as a repository secret for CI
✓ permissions allow `marginal review --comment`
✓ GITHUB_TOKEN is set
✓ GitHub accepted GITHUB_TOKEN and owner/name is reachable

1 check(s) failed.
```

It exits 0 when every check passes and 1 when any fails, so it also works as a CI step.

_marginal is under active, in-the-open development. Jump into [Issues](https://github.com/exactml/marginal/issues) to help build it._

## Commands

| Command | What it does |
|---|---|
| `marginal init` | Writes `.marginal/config.yaml`, a policies folder, and the GitHub Actions workflow. |
| `marginal review --repo owner/name --pr 12` | Reviews a PR and prints the result. Posts nothing, so it's a safe local preview (drafts included). |
| `marginal review ... --comment` | Same review, posted to the PR as inline comments plus a summary. This is what the workflow runs. Add `--format json` for machine-readable output. |
| `marginal review --repo owner/name --base <sha> --head <sha>` | Reviews the diff between two commits instead of a PR, with the config as of `--base`. Prints only; `--comment` isn't allowed. |
| `marginal compact --repo owner/name --pr 12 --comment` | Re-checks marginal's open findings against the latest code and resolves the ones that are fixed. `review --comment` already does this on every later push. |
| `marginal doctor` | Checks config, credentials, and GitHub access without calling a model. |
| `marginal help [command]`, `marginal --version` | Usage, and the installed version. |

## The marginal family

| Package | What it is |
|---|---|
| [`marginal-review`](https://pypi.org/project/marginal-review/) | This repo, on PyPI. The `marginal` CLI: `init`, `review`, `compact`, `doctor`. Install with `pip install marginal-review`. |
| [`marginal-action`](https://github.com/exactml/marginal-action) | The GitHub Action that installs `marginal-review` and runs `marginal review --comment` on each pull request. `marginal init` sets it up for you. |
| [`marginal-client`](https://github.com/exactml/marginal-client) | A small sample app set up with `marginal init`, where marginal's latest `master` reviews real pull requests before each release. Its PRs show what marginal's reviews look like. |

## Configuration

Everything lives in your repository, version-controlled alongside your code:

```text
.marginal/
├── config.yaml
├── policies/
│   ├── README.md
│   ├── security.md
│   ├── testing.md
│   ├── architecture.md
│   └── ...
└── ...
```

A review always uses the config and policies on the PR's **base branch**, so a pull request can't change the rules it's reviewed by. Edits to `.marginal/` apply once they merge.

```yaml
version: 1

review:
  enabled: true
  max_comments: 8
  max_prompt_tokens: 100000  # estimated; over this, the model is never called
  ignore_paths:    # never sent to the model; no "/" matches the file name anywhere
    - "*.lock"
    - package-lock.json
    - pnpm-lock.yaml
    - go.sum
    - "*.min.js"
    - "*.min.css"
  # With --comment, these PRs get no review and no model call
  skip_drafts: true
  skip_bots: true           # dependabot, renovate, any GitHub App author
  skip_labels: [skip-review]

context:
  code_graph: true   # show the model callers outside the diff (Python)

models:
  reviewer:
    provider: anthropic   # or: openai, ollama
    model: claude-opus-5-5

policies:        # rules the review checks the diff against
  - .marginal/policies/security.md
anti_policies:   # deliberate tradeoffs marginal must never flag
  - .marginal/anti-policies/accepted-tradeoffs.md
```

API keys are never stored in configuration — only in your CI secrets or environment. `marginal init` writes every option with its default, including a few reserved for upcoming features (`tone`, `git_history`, `cross_repository`, `ownership`) that have no effect yet.

### Policies

A policy is plain Markdown: the rule, why it exists, and where it applies. List it under `policies` and every review checks the diff against it:

```markdown
<!-- .marginal/policies/money.md -->
# Money

- Every amount is a `decimal.Decimal`, never a `float`.
- Round only once, at the end, with `ROUND_HALF_UP` to 2 places.
- Discounts apply before tax.
```

A finding that breaks a policy says so, e.g. *"Changing rounding from ROUND_HALF_UP to ROUND_DOWN violates the money policy."* Anti-policies work the same way for things marginal must never flag, such as a tradeoff your team made on purpose.

### Local models (Ollama)

To keep every model call on your own machines, run the model with [Ollama](https://ollama.com) and point a role at it. No API key is needed:

```yaml
models:
  reviewer:
    provider: ollama
    model: qwen2.5-coder:14b
    base_url: http://localhost:11434/v1  # the default; set it for a remote Ollama host
```

`ollama` talks to Ollama's OpenAI-compatible API, so any server exposing `/v1/chat/completions` with JSON-schema structured output (vLLM, for example) works the same way. Install it with `pip install 'marginal-review[ollama]'`. The machine running marginal must reach that URL, so in GitHub Actions that usually means a self-hosted runner on the same network.

## Run it anywhere

The same core agent runs as:

- **GitHub Actions** — the primary integration, zero infrastructure to operate
- **CLI** — `marginal review` for local runs
- **Self-hosted runners** — for orgs that need everything on their own network

No step requires code to leave your infrastructure, and no step requires a marginal-hosted service.

## Contributing

marginal is being designed in the open, and there's no ship deadline forcing shortcuts — it's built to grow with contributors, not around a single team's timeline. Design discussion, issues, and PRs are welcome. A good place to start is an issue labelled [`good first issue`](https://github.com/exactml/marginal/labels/good%20first%20issue) or [`help wanted`](https://github.com/exactml/marginal/labels/help%20wanted).

## License

[MIT](LICENSE)
