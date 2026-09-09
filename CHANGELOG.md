# CHANGELOG

## UNDER DEVELOPMENT marginal vx.x.x, xxxx-xx-xx

### Breaking Changes

### New Features

- `marginal review`'s generated finding is now structured
  (`marginal.review.Finding`: `file`, `line`, `severity`, `message`) instead
  of a raw text blob — generated via `ModelProvider.generate_structured()`
  instead of `generate()`. Still folded into the same one summary
  comment for now (`Finding (severity): file[:line]` followed by the
  message); a finding with no identifiable line falls back to just the
  filename. This is what makes inline per-line comments and confidence-based
  filtering possible next. Raises `ProviderResponseError` (not a bare
  `assert`, which `-O` strips entirely) if a provider's structured output
  doesn't actually come back as a `Finding` — caught live by
  `marginal-action`'s own real review of this PR's diff

  ([ISSUE-26](https://github.com/exactml/marginal/issues/26),
  [PR-30](https://github.com/exactml/marginal/pull/30))

- `marginal review --comment` now posts a finding anchored to a `line` as an
  inline review comment (`{path, line, body}`) instead of folding it into
  the one overall review body. A finding with no identifiable line still
  falls back to the body, so nothing is silently dropped. Still exactly one
  `create_review` call either way — inline comments ride along with the
  same review as its `comments` list. `PermissionDeniedError` maps through
  the same existing clean error path, unchanged. The printed local summary
  is unaffected: it still shows every finding (anchored or not), same as
  before — only the posted review body drops the ones that now ride inline
  instead, an omission caught live by `marginal-action`'s own real review of
  this PR's diff

  ([ISSUE-27](https://github.com/exactml/marginal/issues/27),
  [PR-33](https://github.com/exactml/marginal/pull/33))

### Improvements

### Fixes

- Provider SDK errors (`anthropic.APIError`, `openai.APIError` — bad
  request, auth failure, rate limit, network error) no longer crash with a
  raw traceback. `AnthropicProvider`/`OpenAIProvider`'s `generate`,
  `generate_structured`, and `stream` now catch them and re-raise as the
  new `ProviderAPIError` (a `ProviderError`), so `run_review`'s existing
  clean error path handles them with no changes needed there. `stream`
  wraps its whole generator body, not just the initial call, so an error
  raised mid-iteration is caught too. Found live in CI via an Anthropic key
  that wasn't scoped to a workspace, and the `stream` gap was caught by
  `marginal-action`'s own review of this PR's diff

  ([ISSUE-31](https://github.com/exactml/marginal/issues/31),
  [PR-32](https://github.com/exactml/marginal/pull/32))

### Warnings

## marginal v0.1.1, 2026-09-08

### Breaking Changes

### New Features

- `marginal review` generates a real finding: when `models.reviewer` is
  configured, it builds a prompt from the PR's changed files (filename +
  patch) asking for the single most important, actionable issue, calls that
  model's `.generate()`, and folds the result into the same summary that's
  already printed and, with `--comment`, posted — no second comment, no new
  GitHub-writing path. Without `models.reviewer` configured, behavior is
  unchanged: metadata-only, no model call attempted. A `ProviderError`
  raised while generating surfaces through the same clean
  one-line/non-zero-exit handling as a GitHub error. Still no validation,
  deduplication, or confidence scoring — one raw, unvalidated finding

  ([ISSUE-21](https://github.com/exactml/marginal/issues/21))

### Improvements

- Configures a real `models.reviewer` (anthropic, `claude-sonnet-5`) in this
  repo's own `.marginal/config.yaml`, and passes
  `anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}` through to
  `marginal-action` in `.github/workflows/marginal.yml` (requires
  `marginal-action` v1.1.0's provider-key forwarding). Still needs the
  `ANTHROPIC_API_KEY` repository secret added manually before this repo's
  own PRs get a real generated finding instead of a `MissingCredentialsError`

  ([ISSUE-23](https://github.com/exactml/marginal/issues/23))

### Fixes

- `marginal init`'s scaffolded `.github/workflows/marginal.yml`: dropped the
  stale "action hasn't shipped yet" comment now that `marginal-action` is
  published, dropped the redundant `actions/checkout@v4` step (the action
  already checks out the consuming repo internally), and added the
  `permissions: pull-requests: write` block the action's README documents
  as required. Also adds this same corrected workflow to `marginal`'s own
  repo, so it reviews its own PRs via `exactml/marginal-action@v1`

  ([ISSUE-19](https://github.com/exactml/marginal/issues/19))

### Warnings

## marginal v0.1.0, 2026-09-08

### Breaking Changes

### New Features

- `marginal review --comment`: posts the same PR summary `marginal review`
  already prints locally as a single PR comment, via the existing
  `GitHubClient.create_review(..., event="COMMENT")` — no new
  GitHub-writing code path. Omitting `--comment` leaves behavior unchanged
  (local-only, nothing posted). A `PermissionDeniedError` raised while
  posting (`permissions.write.comments` off) surfaces through the same
  clean one-line/non-zero-exit handling as a fetch-time error

  ([ISSUE-13](https://github.com/exactml/marginal/issues/13),
  [PR-14](https://github.com/exactml/marginal/pull/14))

- `marginal review` CLI subcommand: fetches a pull request's metadata and
  changed files via `GitHubClient` and prints a plain-text summary — title,
  state, base/head SHA, and the changed file list. Posts nothing back to
  GitHub, since there's no analysis yet to report, and catches
  `PermissionDeniedError`, `GitHubAuthenticationError`, and `GitHubAPIError`
  at the CLI boundary, printing each as a single line instead of a raw
  traceback and exiting non-zero

  ([ISSUE-11](https://github.com/exactml/marginal/issues/11),
  [PR-12](https://github.com/exactml/marginal/pull/12))

- GitHub API client: `marginal.github.GitHubClient` wraps the GitHub REST API
  (pull request reads, review writes) for one `"owner/name"` repo, gating
  every method on the caller's `PermissionsConfig` before it touches the
  network — a denied read or write raises `PermissionDeniedError` with no
  request made, and `event="APPROVE"` on `create_review` additionally
  requires `permissions.write.approve`. Reads its token only from
  `GITHUB_TOKEN`, never from `.marginal/config.yaml`, and surfaces non-2xx
  responses as typed errors (`GitHubAuthenticationError`,
  `GitHubNotFoundError`, `GitHubAPIError`) instead of raw HTTP exceptions.
  Adds `requests` as a core runtime dependency

  ([ISSUE-9](https://github.com/exactml/marginal/issues/9),
  [PR-10](https://github.com/exactml/marginal/pull/10))

- `marginal init` CLI command: scaffolds `.marginal/config.yaml` (serialized
  from a default `MarginalConfig`, so it can never drift from the schema),
  an empty `.marginal/policies/`, and a starter
  `.github/workflows/marginal.yml`. Each artifact is skipped (not
  overwritten) if already present, unless `--force` is given. Adds the
  `marginal` console entry point and an argparse-based subcommand dispatcher
  in `marginal/cli/` for future subcommands to plug into

  ([ISSUE-7](https://github.com/exactml/marginal/issues/7),
  [PR-8](https://github.com/exactml/marginal/pull/8))

- Model provider abstraction (BYOK): `marginal.providers.get_provider` resolves
  a config `ModelSpec` to a `ModelProvider` (`generate`, `generate_structured`,
  `stream`), with concrete `anthropic` and `openai` implementations. Each
  provider's SDK is imported lazily so installing `marginal[anthropic]`
  doesn't require `openai` to be present, and credentials are read only from
  `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` — never from `.marginal/config.yaml`.
  Raises `UnknownProviderError` for an unregistered provider name and
  `MissingCredentialsError` when the required environment variable is unset
  (both `ProviderError`). Adds `anthropic` and `openai` as optional
  dependencies

  ([ISSUE-5](https://github.com/exactml/marginal/issues/5),
  [PR-6](https://github.com/exactml/marginal/pull/6))

- Repository-local config schema: `marginal.config.load_config` parses and
  validates `.marginal/config.yaml` (review behavior, context toggles, model
  selection, ownership behavior, policy paths, and agent permissions) into a
  typed `MarginalConfig`, defaulting every field to a least-privilege
  baseline and raising `ConfigParseError` on malformed YAML or
  `ConfigValidationError` on invalid values (both `ConfigError`), each with
  a clear message. Adds `pydantic` and `pyyaml` as runtime dependencies

  ([ISSUE-3](https://github.com/exactml/marginal/issues/3),
  [PR-4](https://github.com/exactml/marginal/pull/4))

### Improvements

- PyPI packaging: publishes as `marginal-review` on PyPI (the `marginal` name
  is already taken by an unrelated project) via a trusted-publishing
  GitHub Actions workflow triggered on a published GitHub Release. The
  importable module and `marginal` console command are unaffected — only
  the `pip install` name changes

  ([ISSUE-17](https://github.com/exactml/marginal/issues/17),
  [PR-16](https://github.com/exactml/marginal/pull/16))

- Project scaffold: `marginal` package layout (`config`, `providers`, `context`,
  `graph`, `policy`, `agent`, `review`, `github`, `cli`), `ruff` + `pytest`
  tooling, CI workflow, `CONTRIBUTING.md`, and the language/runtime ADR

  ([ISSUE-1](https://github.com/exactml/marginal/issues/1),
  [PR-2](https://github.com/exactml/marginal/pull/2))

### Fixes

### Warnings
