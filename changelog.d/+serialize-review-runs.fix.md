The workflow `marginal init` scaffolds now runs one review per PR at a time
(a `concurrency` group keyed on the PR number, queueing rather than
cancelling). Two pushes a few seconds apart used to start two runs in
parallel; neither saw the other's review, so both posted the same header and
findings. Queued, the second run sees the first one's review and skips what's
already there. An existing `.github/workflows/marginal.yml` isn't rewritten:
add the same `concurrency` block to it, as shown in the README

([PR-116](https://github.com/exactml/marginal/pull/116) by [@exactml](https://github.com/exactml))
