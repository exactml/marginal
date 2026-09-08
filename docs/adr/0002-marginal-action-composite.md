# ADR 0002: marginal-action as a composite action

**Choice:** Implement `exactml/marginal-action` (the GitHub Action wiring
`marginal review --comment` into CI on `pull_request`) as a composite action
(`runs.using: composite`), not a Docker action.

**Why:** `marginal` is a small, pure-Python CLI with no OS-level
dependencies, so there is nothing a Docker image would isolate that
`actions/setup-python` plus a `pip install` step doesn't already give us. A
composite action starts faster (no image build or pull per run), runs on any
GitHub-hosted runner OS instead of Linux-only, and needs no image to build,
publish, or version separately from the action's own tags. The tradeoff is
less hermetic reproducibility — the runner's Python/pip environment isn't
pinned the way a Docker image would be — and Linux-only tooling isn't an
option if `marginal` ever needs one; acceptable for now, revisit if that
changes.
