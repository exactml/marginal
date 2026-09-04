# CHANGELOG

## UNDER DEVELOPMENT marginal vx.x.x, xxxx-xx-xx

### Breaking Changes

### New Features

- Repository-local config schema: `marginal.config.load_config` parses and
  validates `.marginal/config.yaml` (review behavior, context toggles, model
  selection, ownership behavior, policy paths, and agent permissions from
  REQUIREMENTS.md §6/§28) into a typed `MarginalConfig`, defaulting every
  field to the least-privilege example in the spec and raising `ConfigError`
  with a clear message on malformed YAML or invalid values. Adds `pydantic`
  and `pyyaml` as runtime dependencies

  ([#3](https://github.com/exactml/marginal/issues/3), PR TBD)

### Improvements

- Project scaffold: `marginal` package layout (`config`, `providers`, `context`,
  `graph`, `policy`, `agent`, `review`, `github`, `cli`), `ruff` + `pytest`
  tooling, CI workflow, `CONTRIBUTING.md`, and the language/runtime ADR

  ([#1](https://github.com/exactml/marginal/issues/1), PR TBD)

### Fixes

### Warnings
