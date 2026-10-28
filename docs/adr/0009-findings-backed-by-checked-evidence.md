# ADR 0009: Post findings on checked evidence, not a self-rated confidence

**Status:** Accepted · recorded 2026-10-28

## Context

marginal used to ask the model for a confidence between 0 and 1 with each
finding, and posted the finding if it cleared `review.confidence_threshold`.
Nothing said why the number was what it was, and nothing checked it.

The review-quality benchmark (ADR 0008) measured what that cost. On 24 real
PRs, Claude Opus 5.5 raised 16 of 18 known bugs but rated them 0.3-0.85, mostly
0.5-0.6: at the 0.85 default marginal posted almost none of them (Recall 0.05).
Lowering the threshold traded recall for noise without knowing which findings
were real; the first false positive on a clean PR appeared at 0.4. Other
reviewers report the same: Greptile found a model's rating of its own comments
"nearly random".

## Decision

Every finding **shows its work**, marginal **checks** it, and a **rule** decides
what gets posted. All in the one review call; no second model call.

- **The model returns** a `trigger` (the concrete input, state or call path
  that makes it go wrong), `evidence` (1-3 lines it rests on, each quoted
  exactly with its file and line) and `assumptions` (what it couldn't see). No
  confidence.
- **marginal checks** with no model call: a quote is verified if its text is at
  its line, within 2 lines, in the diff (with the diff's own numbering) or the
  checkout; the trigger is concrete if it names an identifier from the diff,
  the caller context, or a verified quote.
- **The rule:** post a finding with at least one verified quote and a concrete
  trigger. Drop the rest with a plain reason: "no quoted evidence", "quoted line
  not found", "no concrete trigger", or "over review.max_comments". No severity
  exception.
- **What a team sees:** a severity badge (no percentage) and a folded "Why
  marginal flagged this" block with the trigger, the verified quotes and the
  assumptions. `--format json` gives every finding its `checks` and lists the
  dropped ones with their `reason`.
- **Removed, in one breaking release:** `review.confidence_threshold` and
  `review.self_reflect` (a second model call whose only job was lowering
  confidence). A config that still sets either fails to load and says why.

## Trade-offs

| Option | Pros | Cons |
|---|---|---|
| **Evidence checked by marginal, posted by rule** (chosen) | Every post and drop has a reason a person can read. Invented code is caught for free. One model call. | About 15% more output tokens per review. A real issue the model can't quote evidence for isn't posted. |
| A rubric for the confidence number | No schema change. | Still a number nobody can check; the model's calibration is the problem. |
| A second model call to re-check findings | An independent look. | About double the cost per review. With coding agents opening many PRs a day, cost per review rules it out. |
| A points score over the checks, with a cutoff | Flexible. | The cutoff becomes another number to tune blind, like the threshold it replaces. |
| Learning factor weights from maintainers' replies | Adapts per repo. | Needs history first. Possible later, on these same checks. |

## What this means

- A team reads why each finding was posted, and the JSON says why each dropped
  one wasn't.
- There's no threshold to tune. The quote tolerance (2 lines) and the rule are
  fixed in code.
- The benchmark reports **Recall before rules** (known bugs raised, posted or
  not) and **Evidence accuracy** (hits whose verified quotes include the bug's
  own lines).
- Upgrading means deleting `confidence_threshold` and `self_reflect` from
  `.marginal/config.yaml`.

## Accepted in

- [#200 Design: findings that explain themselves, with rules instead of a self-rated confidence](https://github.com/exactml/marginal/issues/200)
