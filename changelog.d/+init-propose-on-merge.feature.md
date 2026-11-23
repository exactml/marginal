The workflow `marginal init` writes now also runs when a pull request closes,
so with `proposals.enabled: true` a merged PR gets its knowledge proposal
from marginal-action. A PR closed without merging is skipped. Existing
workflows need `closed` added to their `pull_request` types to opt in

([PR-271](https://github.com/exactml/marginal/pull/271) by [@exactml](https://github.com/exactml))
