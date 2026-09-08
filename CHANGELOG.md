# CHANGELOG

## UNDER DEVELOPMENT marginal vx.x.x, xxxx-xx-xx

### Breaking Changes

### New Features

### Improvements

### Fixes

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
