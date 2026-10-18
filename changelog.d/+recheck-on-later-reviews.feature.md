`marginal review --comment` now re-checks marginal's earlier findings on
every later push, the same way `marginal compact --comment` does: a finding
the push fixed gets a `✅ Resolved: <reason>` reply and its thread resolved,
and a finding still there gets nothing posted. It runs only once marginal has
already reviewed the PR, so the first review costs nothing extra, and it costs
one extra model call per push only while earlier findings are still open.
It's best-effort: if the re-check fails, the review is unaffected and only a
line is logged to stderr; stdout, including `--format json`, is unchanged

([PR-125](https://github.com/exactml/marginal/pull/125) by [@exactml](https://github.com/exactml))
