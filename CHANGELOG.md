# CHANGELOG

## UNDER DEVELOPMENT marginal vx.x.x, xxxx-xx-xx

### Breaking Changes

### New Features

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

- Project scaffold: `marginal` package layout (`config`, `providers`, `context`,
  `graph`, `policy`, `agent`, `review`, `github`, `cli`), `ruff` + `pytest`
  tooling, CI workflow, `CONTRIBUTING.md`, and the language/runtime ADR

  ([ISSUE-1](https://github.com/exactml/marginal/issues/1),
  [PR-2](https://github.com/exactml/marginal/pull/2))

### Fixes

### Warnings
