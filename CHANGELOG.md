# CHANGELOG

## UNDER DEVELOPMENT marginal vx.x.x, xxxx-xx-xx

### Breaking Changes

### New Features

- `marginal review` now folds the content of any `config.policies` files into
  the finding-generation prompt, via a new `marginal.policy.load_policies`
  (reads each path relative to the repo root, skipping and warning to stderr
  on a missing file rather than failing the whole review). With no policies
  configured -- the default -- the prompt is unchanged from before. This
  makes `marginal/policy/__init__.py`'s previously-empty stub load-bearing
  for the first time; folding the loaded policies into a model's own
  understanding of *why* a policy applies is left for later

  ([ISSUE-29](https://github.com/exactml/marginal/issues/29),
  [PR-40](https://github.com/exactml/marginal/pull/40))

- `marginal review` now redacts likely secrets from a diff before it's
  folded into the finding-generation prompt, via a new
  `marginal.review.redact_secrets`: a small, fixed set of high-confidence
  patterns (PEM private-key blocks, JWTs, GitHub tokens, AWS access keys,
  and generic `api_key=`/`token=`/`secret=` assignments) get their value
  masked as `[REDACTED]`. Applied unconditionally to every file's patch as
  a safety default, not opt-in -- a patch with nothing matching passes
  through byte-for-byte unchanged, and the generic-assignment pattern is
  deliberately conservative so it doesn't mangle a plain identifier or
  function call. Masking it from the model isn't the whole story, though:
  `run_review` also names any redacted file in a `⚠️ **Redacted a likely
  secret**` line folded into the same summary/review body, so the client
  still learns a credential landed in their diff and can rotate it --
  still exactly one `create_review` call, not a second comment. This is a
  fixed pattern set, not exhaustive secret detection: false negatives (a
  real secret in an unrecognized shape) are the accepted failure mode

  ([ISSUE-47](https://github.com/exactml/marginal/issues/47),
  [PR-58](https://github.com/exactml/marginal/pull/58))

### Improvements

- `marginal review`'s output is restructured for readability instead of flat
  indented text. Findings (both inline comments and the summary-body
  fallback) now lead with a severity+confidence badge (`🔴 **Critical** ·
  92% confidence`) before the message, so they're triageable by eye without
  reading the prose. The overall review gets a `### 🤖 marginal review`
  heading and a compact one-line PR summary, with the changed-file list
  collapsed behind a `<details>` block so it doesn't dominate the review on
  larger PRs. Still not addressed: re-running `marginal review --comment`
  on the same PR after a new push still posts a fresh review restating this
  same header/file-list block -- true dedup across pushes needs either
  identifying and updating a prior review or accepting the (now much
  smaller, collapsed) repetition, and is left open

  ([ISSUE-36](https://github.com/exactml/marginal/issues/36),
  [PR-38](https://github.com/exactml/marginal/pull/38))

- `tests/test_cli.py`'s `review` test cases now share `mock_github_client` and
  `mock_provider` fixtures and consistently reuse the existing `_pull_request()`
  helper, replacing roughly ten near-identical inline mock-patching blocks and
  PR-metadata dict literals. Test-only: no behavior or coverage change

  ([PR-41](https://github.com/exactml/marginal/pull/41))

- Added `SECURITY.md` documenting how to report a vulnerability responsibly:
  GitHub private vulnerability reporting as the intake channel (no public
  security@ email exists for this project), an acknowledgement/assessment
  response-time commitment, and a supported-versions policy that -- being
  pre-1.0 -- covers only the latest `0.1.x` release on PyPI

  ([ISSUE-62](https://github.com/exactml/marginal/issues/62),
  [PR-67](https://github.com/exactml/marginal/pull/67))

- Adopted a `CODE_OF_CONDUCT.md` based on the Contributor Covenant (v2.1),
  with the enforcement contact pointed at the project's existing public
  maintainer email rather than a fabricated address

  ([ISSUE-63](https://github.com/exactml/marginal/issues/63),
  [PR-68](https://github.com/exactml/marginal/pull/68))

- Added two Claude Code skills under `.claude/skills/`: `dev-setup` wraps
  CONTRIBUTING.md's manual venv/`pip install -e ".[dev]"`/pre-commit steps
  into a single guided flow that verifies each step instead of assuming it
  worked, and `cut-release` codifies the mechanical `CHANGELOG.md`
  UNDER-DEVELOPMENT-to-dated-version split, the version-bump/tag/branch
  naming this repo already uses, and drafting GitHub release notes with a
  contributor-thanks section -- gated behind an explicit confirmation before
  actually publishing, since publishing fires the PyPI trusted-publish
  workflow immediately and irreversibly

  ([ISSUE-66](https://github.com/exactml/marginal/issues/66),
  [PR-69](https://github.com/exactml/marginal/pull/69))

### Fixes

### Warnings

## marginal v0.1.3, 2026-09-09

### Breaking Changes

### New Features

- `marginal review` now wires up `config.review.confidence_threshold` and
  `config.review.max_comments`, both previously dead config. `Finding` gets
  a required `confidence: float` field (the model self-reports it via the
  generation prompt), and every generated finding is run through the new
  `marginal.review.filter_findings` before it can reach a PR comment: dropped
  outright below `confidence_threshold`, then capped at `max_comments`
  (highest-confidence first). If everything gets filtered out, behavior is
  unchanged from no finding being generated at all -- metadata-only summary,
  nothing posted beyond that. `marginal review` currently only ever
  generates one finding per run, so the `max_comments` cap doesn't yet have
  a real multi-finding case to bite on -- covered directly against
  `filter_findings` instead

  ([ISSUE-28](https://github.com/exactml/marginal/issues/28),
  [PR-35](https://github.com/exactml/marginal/pull/35))

### Improvements

### Fixes

### Warnings

## marginal v0.1.2, 2026-09-09

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
