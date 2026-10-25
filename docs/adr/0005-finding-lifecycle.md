# ADR 0005: Finding lifecycle — post once, resolve only when fixed

**Status:** Accepted · recorded 2026-10-25

## Context

A review isn't one event. A PR gets pushed to again and again, and on each push
marginal runs again. Without a plan for what happens to a finding over time,
two things go wrong:

- **Repeats.** The model rewords the same issue every run ("blocking sleep in
  the retry loop" vs. "time.sleep blocks the loop"), so the same finding gets
  posted on every push.
- **Stale threads.** A finding that a later push fixed stays open forever, and
  the PR looks worse than it is.

People also disagree with findings. If marginal ignores their replies, it
raises the same point again and gets muted.

## Decision

Each finding moves through a simple lifecycle, and the state lives in GitHub
itself, not in a database:

1. **Posted once.** Every posted finding carries a hidden fingerprint in its
   comment. The fingerprint is built from the file, the severity, and the
   *text of the line it points at*, not from the model's wording and not from
   the line number. A later run skips a finding whose fingerprint (or a
   neighbouring line's) is already on the PR.
2. **Re-checked on every push.** On each later review, marginal asks the model
   whether each open finding still holds against the new diff.
3. **Resolved only when fixed.** If the model confirms the problem is gone,
   marginal replies `✅ Resolved` in the thread and collapses it. A finding the
   model leaves out of its answer stays open.
4. **Closed when a person disputes it.** A maintainer's reply goes into the
   next prompt. If it explains why the finding is wrong, marginal closes the
   thread and credits that person.

## Trade-offs

| Option | Pros | Cons |
|---|---|---|
| **Fingerprints + re-check + dispute** (chosen) | No repeats, even when the model rewords a finding. A thread closes only after a check that it's really fixed. People are listened to. No database: GitHub comments are the store. | One extra model call on re-reviews. A genuinely new issue on the line next to an old one of the same severity counts as a repeat. A finding with no line falls back to its wording, which rarely matches, so it may repeat. |
| Resolve when a finding is absent from the next run | Cheap: no extra call. | The model rewording or simply forgetting a finding "resolves" it. Bugs get marked fixed when they aren't. |
| Never resolve; people close threads by hand | Simplest. | Fixed findings pile up as open threads, and the review looks noisier than it is. |
| One summary comment, rewritten each run | Only one comment to manage. | No inline threads to reply to or resolve. Hard to discuss a single finding. |

## What this means

- The workflow needs `contents: write`: GitHub requires it to resolve a review
  thread, even though marginal never pushes code.
- `marginal compact` runs the same re-check on demand. `marginal review
  --comment` already runs it on every later push.
- Changing what goes into a fingerprint makes old findings look new once, so it
  should be rare and called out in the changelog.

## Accepted in

- [#110 Skip findings marginal already posted on the PR](https://github.com/exactml/marginal/pull/110)
- [#115 Feed maintainer replies to marginal's comments into the review prompt](https://github.com/exactml/marginal/pull/115)
- [#121 Add marginal compact to close findings a later push resolved](https://github.com/exactml/marginal/pull/121)
- [#125 Re-check earlier findings on every later marginal review](https://github.com/exactml/marginal/pull/125)
- [#128 Close a finding a person disputes, crediting them](https://github.com/exactml/marginal/pull/128)
- [#135 Let marginal resolve review threads in GitHub Actions](https://github.com/exactml/marginal/pull/135)
