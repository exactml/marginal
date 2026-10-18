In GitHub Actions, marginal now actually collapses the threads it resolves.
The Actions token needs `contents: write` to resolve a review thread --
with only `pull-requests: write` GitHub answers "Resource not accessible by
integration" -- so the workflow `marginal init` writes, and the README
example, now grant it (marginal never pushes). Existing workflows need
`contents: write` added under the job's `permissions:`. A thread marginal
already replied `✅ Resolved` in but couldn't resolve is resolved on the next
run, without posting the reply again, and a failed resolve now says which
permission is missing

([PR-135](https://github.com/exactml/marginal/pull/135) by [@exactml](https://github.com/exactml))
