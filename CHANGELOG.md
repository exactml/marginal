# CHANGELOG

<!-- towncrier release notes start -->

## marginal v0.3.0, 2026-10-28

### Breaking Changes

- Findings are posted on checked evidence instead of a self-rated confidence.
  The model now gives each finding a trigger, 1-3 exactly quoted lines and its
  assumptions; marginal checks the quotes against your code (within 2 lines) and
  posts a finding only if a quote is verified and the trigger names real code,
  with a "Why marginal flagged this" block. `review.confidence_threshold` and
  `review.self_reflect` are removed: delete both from `.marginal/config.yaml`,
  or the config fails to load. In `--format json`, findings lose `confidence`,
  gain `trigger`, `evidence`, `assumptions` and `checks`, and
  `filtered_findings` is now `dropped_findings`, each with a `reason`

  ([ISSUE-200](https://github.com/exactml/marginal/issues/200), [PR-202](https://github.com/exactml/marginal/pull/202) by [@exactml](https://github.com/exactml))

### New Features

### Improvements

### Fixes

- Renaming a file no longer makes marginal post its findings on it again: a
  finding that matches one of marginal's comments at the path and line GitHub
  shows it on now counts as already posted

  ([ISSUE-177](https://github.com/exactml/marginal/issues/177), [PR-201](https://github.com/exactml/marginal/pull/201) by [@babyhuey](https://github.com/babyhuey))

- The caller context reaches the model on repos the graph couldn't
  fully read: a file that doesn't parse (newer syntax than the Python marginal
  runs on, or a file kept broken on purpose) is skipped instead of dropping the
  whole graph. Callers elsewhere in a changed file are kept, and the caller
  snippets are shared across the changed definitions, so a changed method's
  callers aren't crowded out by the class around it

  ([ISSUE-198](https://github.com/exactml/marginal/issues/198), [PR-199](https://github.com/exactml/marginal/pull/199) by [@exactml](https://github.com/exactml))

### Warnings

## marginal v0.2.10, 2026-10-28

### Breaking Changes

### New Features

- `marginal review` can now review the diff between two commits without a pull
  request: `marginal review --repo owner/name --base <sha> --head <sha>` uses the
  config and policies as of `--base` and posts nothing, so `--comment` isn't
  allowed with it

  ([ISSUE-179](https://github.com/exactml/marginal/issues/179), [PR-181](https://github.com/exactml/marginal/pull/181) by [@exactml](https://github.com/exactml))

### Improvements

- `marginal review --format json` now reports the tokens the review used, in a
  top-level `usage` object with the model and the input and output token counts
  summed over every model call, including a retry and the self-critique pass.
  A count is `null` when the provider doesn't report usage, as some local
  Ollama servers don't

  ([ISSUE-179](https://github.com/exactml/marginal/issues/179), [PR-182](https://github.com/exactml/marginal/pull/182) by [@exactml](https://github.com/exactml))

- `marginal review --format json` now lists `filtered_findings`: the findings the
  model returned that `review.confidence_threshold` or `review.max_comments`
  dropped. They're never posted, but their confidence shows how close they came,
  so "the model missed it" and "the threshold dropped it" can be told apart

  ([ISSUE-188](https://github.com/exactml/marginal/issues/188), [PR-189](https://github.com/exactml/marginal/pull/189) by [@exactml](https://github.com/exactml))

### Fixes

- Reviews work with Claude Opus 5.5 and Fable 5.1: marginal no longer
  forces the structured-output tool call, which these models reject with a 400,
  and asks for it instead. A reply without the tool call is retried once, and
  structured output gets room for the thinking these models always do

  ([ISSUE-185](https://github.com/exactml/marginal/issues/185), [PR-186](https://github.com/exactml/marginal/pull/186) by [@exactml](https://github.com/exactml))

### Warnings

## marginal v0.2.9, 2026-10-25

### Breaking Changes

### New Features

- With `--comment`, `marginal review` now skips a PR instead of reviewing it
  when it's a draft (`review.skip_drafts`), opened by a bot such as
  dependabot or renovate (`review.skip_bots`), or carries a label listed in
  `review.skip_labels` (default `skip-review`), and `review.enabled: false`
  now actually turns reviews off. A skipped PR gets no model call and nothing
  posted, just one line in the run log saying why. Without `--comment` the
  review still runs, so a draft can be previewed locally. The workflow
  `marginal init` writes now also triggers on `ready_for_review`, so a draft is
  reviewed as soon as it's marked ready -- add `types: [opened, synchronize,
  reopened, ready_for_review]` under `pull_request:` in an existing workflow
  to get the same

  ([ISSUE-138](https://github.com/exactml/marginal/issues/138),
  [PR-141](https://github.com/exactml/marginal/pull/141) by [@exactml](https://github.com/exactml))

- Added `review.ignore_paths`, a list of glob patterns for changed files
  `marginal review` never sends to the model -- by default common lockfiles
  (`*.lock`, `package-lock.json`, `pnpm-lock.yaml`, `go.sum`) and minified
  `*.min.js`/`*.min.css`. A pattern with no `/` matches the file name in any
  directory; one with a `/` matches the whole path. Ignored files stay in the
  changed-file list, the summary says how many were left out, and a dependency
  bump no longer eats `review.max_prompt_tokens`. A PR that only changes
  ignored files gets no model call at all

  ([ISSUE-139](https://github.com/exactml/marginal/issues/139),
  [PR-142](https://github.com/exactml/marginal/pull/142) by [@exactml](https://github.com/exactml))

- Added `marginal --version`, which prints the installed release (e.g.
  `marginal 0.2.9`)

  ([ISSUE-145](https://github.com/exactml/marginal/issues/145),
  [PR-148](https://github.com/exactml/marginal/pull/148) by [@exactml](https://github.com/exactml))

### Improvements

- When a provider's API key variable is set but empty -- which is how a
  missing or blank repository secret reaches marginal in GitHub Actions --
  `marginal review` and `marginal doctor` now say so and point at the
  secret, instead of claiming the variable isn't set

  ([ISSUE-144](https://github.com/exactml/marginal/issues/144),
  [PR-147](https://github.com/exactml/marginal/pull/147) by [@exactml](https://github.com/exactml))

### Fixes

- A finding's message no longer ends with a stray fragment of the model's
  structured output (e.g. `...fractional cents.', 'file'] ,`), which a model
  could write into the text and marginal used to post as-is

  ([ISSUE-143](https://github.com/exactml/marginal/issues/143),
  [PR-146](https://github.com/exactml/marginal/pull/146) by [@exactml](https://github.com/exactml))

- A pull request can no longer change the rules it's reviewed by.
  `marginal review` and `marginal compact` now read `.marginal/config.yaml`,
  policies, and anti-policies from the PR's base commit instead of its
  checkout, so a PR that sets `review.enabled: false`, ignores every file, or
  adds an anti-policy is still reviewed under the base branch's rules. The
  summary notes when a PR edits `.marginal/`, since the edits apply after it
  merges. The PR that first adds marginal's config still uses its own

  ([ISSUE-151](https://github.com/exactml/marginal/issues/151),
  [PR-172](https://github.com/exactml/marginal/pull/172) by [@exactml](https://github.com/exactml))

- Two kinds of secret could reach the model unredacted and now don't: a
  password inside a URL (`https://user:pass@host` is sent as
  `https://[REDACTED]@host`), and anything in the snippets of out-of-diff
  callers that the code graph adds to the prompt. URLs without credentials,
  and plain profile names like `local`, are unchanged

  ([ISSUE-170](https://github.com/exactml/marginal/issues/170),
  [PR-171](https://github.com/exactml/marginal/pull/171) by [@exactml](https://github.com/exactml))

- In GitHub Actions, marginal now actually collapses the threads it resolves.
  The Actions token needs `contents: write` to resolve a review thread --
  with only `pull-requests: write` GitHub answers "Resource not accessible by
  integration" -- so the workflow `marginal init` writes, and the README
  example, now grant it (marginal never pushes). Existing workflows need
  `contents: write` added under the job's `permissions:`. A thread marginal
  already replied `✅ Resolved` in but couldn't resolve is resolved on the next
  run, without posting the reply again, and a failed resolve now says which
  permission is missing

  ([PR-135](https://github.com/exactml/marginal/pull/135) by [@exactml](https://github.com/exactml))

### Warnings

- Draft PRs and PRs opened by bots are no longer reviewed by default. Set
  `review.skip_drafts: false` or `review.skip_bots: false` to keep reviewing
  them. To have a draft reviewed as soon as it's marked ready, add
  `ready_for_review` to your workflow's `pull_request` types

  ([ISSUE-138](https://github.com/exactml/marginal/issues/138),
  [PR-141](https://github.com/exactml/marginal/pull/141) by [@exactml](https://github.com/exactml))

- Changes to `.marginal/config.yaml` and policy files now take effect only after
  they merge to the base branch. A PR that tunes marginal's settings is reviewed
  with the old ones

  ([ISSUE-151](https://github.com/exactml/marginal/issues/151),
  [PR-172](https://github.com/exactml/marginal/pull/172) by [@exactml](https://github.com/exactml))

## marginal v0.2.8, 2026-10-18

### Breaking Changes

### New Features

- New `marginal doctor` command checks your setup before the first review: that
  `.marginal/config.yaml` is valid, that `models.reviewer` is set and each
  configured provider's API key is in the environment, that `permissions` let
  `marginal review` read the PR, and that `GITHUB_TOKEN` is set. With
  `--repo owner/name` it also makes one read-only GitHub call to confirm the
  token is accepted and the repository is reachable. It never calls a model or
  posts anything. Each check prints one ✓/✗ line with a fix under each failure;
  `permissions.write.comments` being off is only noted, since you need it just to
  post with `--comment`. The command exits 0 only when every check passes, else 1

  ([ISSUE-45](https://github.com/exactml/marginal/issues/45),
  [PR-129](https://github.com/exactml/marginal/pull/129) by [@exactml](https://github.com/exactml))

- New `anti_policies` config key: a list of Markdown files describing
  deliberate trade-offs marginal must never flag, such as "a +/-1 line dedup
  window is intended". `marginal review` adds their content to the reviewer
  prompt as its own "never flag" section, separate from `policies`' "check for"
  guidance. A missing file is skipped with a warning, the same as a missing
  policy file. With no anti-policies configured, the prompt is unchanged. This
  is guidance to the model, not a filter on its findings.

  ([ISSUE-46](https://github.com/exactml/marginal/issues/46),
  [PR-126](https://github.com/exactml/marginal/pull/126) by [@exactml](https://github.com/exactml))

- New `ollama` provider runs reviews on a model you host yourself, so no code
  leaves your network. Set `models.reviewer` to `provider: ollama` and a local
  model name; it needs no API key and talks to `http://localhost:11434/v1` unless
  the new optional `base_url` field points it elsewhere. It uses Ollama's
  OpenAI-compatible API, so other compatible servers such as vLLM work too.
  `base_url` also works for the `anthropic` and `openai` providers, for a proxy
  or a self-hosted OpenAI-compatible endpoint that still needs a key. Install
  with `pip install 'marginal-review[ollama]'`

  ([ISSUE-48](https://github.com/exactml/marginal/issues/48),
  [PR-130](https://github.com/exactml/marginal/pull/130) by [@exactml](https://github.com/exactml))

- New opt-in `review.self_reflect` setting (off by default): after the reviewer
  model proposes its findings, marginal sends them back to the same model with
  the diff for a second look before any filtering. The model drops a finding
  that the diff doesn't support, that a comment marks as an intended trade-off,
  or that repeats another finding, and may lower the confidence of the rest --
  never raise it, so the second look can only keep a finding out -- and
  `confidence_threshold` and `max_comments` act on that second-look confidence.
  It costs one extra model call per review that found anything. If that call
  fails or its prompt is over `review.max_prompt_tokens`, the findings go on
  unchanged and the review still succeeds

  ([ISSUE-72](https://github.com/exactml/marginal/issues/72),
  [PR-127](https://github.com/exactml/marginal/pull/127) by [@exactml](https://github.com/exactml))

- `marginal review --comment` now re-checks marginal's earlier findings on
  every later push, the same way `marginal compact --comment` does: a finding
  the push fixed gets a `✅ Resolved: <reason>` reply and its thread resolved,
  and a finding still there gets nothing posted. It runs only once marginal has
  already reviewed the PR, so the first review costs nothing extra, and it costs
  one extra model call per push only while earlier findings are still open.
  It's best-effort: if the re-check fails, the review is unaffected and only a
  line is logged to stderr; stdout, including `--format json`, is unchanged

  ([PR-125](https://github.com/exactml/marginal/pull/125) by [@exactml](https://github.com/exactml))

### Improvements

- When a person says one of marginal's inline findings is wrong, marginal now
  closes it and credits them: it replies `✅ Resolved: @alice says this isn't an
  issue ("…"), so marginal is closing it.` and resolves the thread. The person
  can answer in the finding's own thread or in an ordinary PR comment; the
  model matches each open finding against the human replies in its thread and
  the human PR comments posted after it, so an unrelated comment such as "LGTM"
  or a question closes nothing, and a dismissal only counts if it names one of
  those comments. This runs wherever marginal re-checks open findings: in
  `marginal compact` and on every later `marginal review --comment`

  ([PR-128](https://github.com/exactml/marginal/pull/128) by [@exactml](https://github.com/exactml))

### Fixes

- `marginal review --comment` no longer fails, and no longer loses every
  finding, when the model pins one finding to a line outside the diff. GitHub
  only accepts inline comments on lines inside the diff's hunks and rejects the
  whole review (`GitHub API error 422`) over a single one placed anywhere else,
  so the run exited 1 and posted nothing. A finding on such a line, or in a
  file GitHub shows no patch for, is now posted in the review body with its
  `file:line`, like a finding with no line

  ([PR-132](https://github.com/exactml/marginal/pull/132) by [@exactml](https://github.com/exactml))

### Warnings

## marginal v0.2.7, 2026-10-17

### Breaking Changes

### New Features

- New `marginal compact --repo <owner/name> --pr <number>` closes marginal's
  findings that a later push already resolved, so they stop looking live. It
  re-checks every inline finding marginal posted on the PR that hasn't been
  closed yet. A finding whose file the PR no longer changes is resolved
  straight away, without calling the model. The rest go to `models.reviewer`
  in one call with the current diff of their files; a finding stays open
  unless the model says the current code clearly no longer has the problem,
  and stays open if the model doesn't answer for it. It prints a summary, and
  with `--comment` it replies `✅ Resolved: <reason>` in each resolved
  finding's thread and resolves the thread, collapsing it in GitHub's UI; a
  thread already resolved, by marginal or by hand, is skipped next time. A PR with nothing open is
  a no-op that never calls the model. It respects `review.max_prompt_tokens`
  and uses the same exit codes as `marginal review` (1 for errors, 3 for a
  missing provider key). It only re-checks inline findings, not ones that
  landed in a review's body

  ([ISSUE-54](https://github.com/exactml/marginal/issues/54),
  [PR-121](https://github.com/exactml/marginal/pull/121) by [@exactml](https://github.com/exactml))

### Improvements

- `marginal init` now ends with provider-neutral next steps: set
  `models.reviewer` in `.marginal/config.yaml` to either `anthropic` or
  `openai`, then add that provider's key with `gh secret set ANTHROPIC_API_KEY`
  or `gh secret set OPENAI_API_KEY`. The workflow it scaffolds passes both keys
  to `marginal-action`, so whichever provider you pick needs only its own
  secret, with no workflow edits. Before, a fresh setup had no reviewer model
  and no key wired in, and gave no hint about either. A review that ran
  without a reviewer model now says so (`ℹ️ No reviewer model configured`)
  instead of showing only a title and file list. The README's Quickstart now
  matches what `marginal init` really prints and writes; it previously showed
  an outdated workflow that passed the key through `env:`

  ([ISSUE-74](https://github.com/exactml/marginal/issues/74),
  [PR-119](https://github.com/exactml/marginal/pull/119) by [@exactml](https://github.com/exactml))

### Fixes

### Warnings

## marginal v0.2.6, 2026-10-17

### Breaking Changes

### New Features

- New `review.max_prompt_tokens` setting (default 100000) caps how large a
  review prompt marginal will send to your model. Right before the model call,
  marginal estimates the size of the fully built prompt (diff, policies and
  code-graph context together) at roughly 3 characters per token. If it's over
  the cap, the model is never called, so a huge PR or an overgrown policy set
  can't run up an unexpected bill on your API key. The run still exits 0: it
  prints a notice to stderr, and the summary (and the review posted with
  `--comment`) keeps the PR metadata plus a `⚠️ Review skipped` line, so it
  can't be mistaken for a review that found nothing. That notice is posted
  even if marginal already reviewed the PR, since the new push went unreviewed.
  `--format json` gets a new `prompt_over_budget` field. The estimate is a
  length heuristic, not the provider's real tokenizer

  ([ISSUE-44](https://github.com/exactml/marginal/issues/44),
  [PR-114](https://github.com/exactml/marginal/pull/114) by [@exactml](https://github.com/exactml))

- `marginal review` now remembers what a maintainer said back to it on the same
  PR. Before generating findings, it reads the PR's review-comment threads,
  picks out human replies to marginal's own inline comments, and quotes each
  comment and its replies in the prompt, asking the model not to raise those
  points again (reworded or on a nearby line) unless the code they're about has
  changed. Comments from releases that predate the fingerprint marker are still
  recognized by their severity badge. Replies to anyone else's comments, and
  replies from bot accounts, are ignored. The section keeps the 10 most recent
  answered threads, clips each one, and redacts likely secrets. With no such
  replies the prompt is exactly what it was before. The comments are now read
  on every run with a reviewer model, not only with `--comment`, which needs
  only `permissions.read.pull_requests`; a failure to read them exits 1 like
  any other GitHub error. This is context for the model, not a filter: a
  finding can still repeat if the model ignores it, and only this PR's own
  threads are read

  ([ISSUE-55](https://github.com/exactml/marginal/issues/55),
  [PR-115](https://github.com/exactml/marginal/pull/115) by [@exactml](https://github.com/exactml))

### Improvements

- A marginal review now opens with its verdict, so the outcome is readable
  without opening any inline thread: `**3 findings** · 🔴 1 critical · 🟠 2
  high`, counted by severity with the most serious first, or `✅ **No issues
  found**` when the model reviewed the diff and flagged nothing. On a re-run it
  counts only what's new and notes how many were already flagged earlier on
  the PR. A run without a reviewer model shows no verdict, so it never claims
  "no issues" for a diff nobody reviewed. The base and head SHAs in the header
  are shortened to 7 characters

  ([PR-117](https://github.com/exactml/marginal/pull/117) by [@exactml](https://github.com/exactml))

### Fixes

- The workflow `marginal init` scaffolds now runs one review per PR at a time
  (a `concurrency` group keyed on the PR number, queueing rather than
  cancelling). Two pushes a few seconds apart used to start two runs in
  parallel; neither saw the other's review, so both posted the same header and
  findings. Queued, the second run sees the first one's review and skips what's
  already there. An existing `.github/workflows/marginal.yml` isn't rewritten:
  add the same `concurrency` block to it, as shown in the README

  ([PR-116](https://github.com/exactml/marginal/pull/116) by [@exactml](https://github.com/exactml))

### Warnings

## marginal v0.2.5, 2026-10-17

### Breaking Changes

### New Features

- `marginal review` gains a `--format {text,json}` flag. With `--format json`
  it prints a single JSON object to stdout -- repo, PR number, title, state,
  base/head SHAs, the changed-file list, the surviving findings (each
  `Finding` dumped in full, severity as a plain string), any files whose diff
  had a secret redacted, and whether a comment was posted -- instead of the
  human-readable Markdown summary, so `marginal review` can feed a dashboard,
  a notifier, or another CI step without anyone scraping printed text. The
  default (`--format text`) output is unchanged byte-for-byte, and `--comment`
  posts the identical Markdown body and inline comments under either format:
  the flag changes what goes to stdout, never what goes to GitHub. Errors keep
  their existing exit codes (1, or 3 for missing reviewer credentials) and
  stay plain text on stderr -- an invalid `.marginal/config.yaml` now follows
  that same contract instead of escaping as a traceback -- so stdout under
  `--format json` is either exactly one complete object or nothing at all.
  The shape is best-effort for v1 -- there's no versioned schema contract
  yet, and formalizing one is left until there's real external consumption

  ([ISSUE-50](https://github.com/exactml/marginal/issues/50),
  [PR-81](https://github.com/exactml/marginal/pull/81) by [@rishcx](https://github.com/rishcx))

- `marginal review --comment` no longer reposts a finding it already posted on
  the same PR. Each posted finding carries a hidden fingerprint marker, and a
  re-run reads the PR's existing reviews and comments and skips any finding
  whose fingerprint is already there. If nothing is new and marginal has
  already reviewed the PR, it posts nothing at all, so every push no longer
  adds another copy of the same header and file list. The fingerprint is the
  file, the severity, and the text of the line the finding points at, not the
  model's wording, which changes on every run, and not the line number, which
  shifts when lines are added above it. A finding also counts as a repeat when
  it's one line away from a same-severity finding already posted, because the
  model's line anchor drifts by one between runs. Human replies in marginal's
  threads are left alone. A finding with no line is matched by its message,
  which may still repeat when the model rewords it

  ([ISSUE-56](https://github.com/exactml/marginal/issues/56),
  [PR-110](https://github.com/exactml/marginal/pull/110) by [@exactml](https://github.com/exactml))

- Added `marginal help` and `marginal help <command>`: the first prints the
  same top-level usage as `marginal --help`, the second the usage for that
  subcommand (e.g. `marginal help review` lists `--repo`, `--pr` and
  `--comment`). An unknown command exits 2 with argparse's usual error, just
  like an unknown subcommand does

  ([ISSUE-77](https://github.com/exactml/marginal/issues/77),
  [PR-78](https://github.com/exactml/marginal/pull/78) by [@HarshRajSinghania](https://github.com/HarshRajSinghania))

- Added `marginal.graph.find_out_of_diff_callers`, which maps a PR's changed
  definitions (from #82's symbol graph) to the callers of each that sit
  outside the diff's own changed files -- a caller already visible in the
  diff is dropped, since the diff already shows it directly. Determines
  "changed" by overlapping each file's diff hunks (parsed from the unified
  diff's `@@ ... @@` headers) against a definition's line span; an unchanged
  definition is skipped, and one touched by several hunks is reported once.
  Nothing consumes this yet -- it's the input the review prompt in upcoming
  work will use to show a reviewer what its own diff doesn't

  ([ISSUE-83](https://github.com/exactml/marginal/issues/83),
  [PR-94](https://github.com/exactml/marginal/pull/94) by [@exactml](https://github.com/exactml))

- `config.context.code_graph` (on by default) now does something: `marginal
  review`'s prompt names any definition a diff changes that's called from a
  file outside the diff, with a short source snippet at each call site --
  #82's indexer and #83's diff-to-caller lookup feed straight into it. A
  change to `Widget.render()` in one file now shows the reviewer model the
  caller in another file it would otherwise never see, capped at 10 caller
  snippets total so a large fan-out can't blow up the prompt. Best-effort
  throughout: a definition with only in-diff callers, `code_graph` turned
  off, or the graph failing to build at all (no git checkout, `git`
  missing, a tracked file with invalid syntax) all leave the prompt exactly
  as before -- this never fails the review itself

  ([ISSUE-84](https://github.com/exactml/marginal/issues/84),
  [PR-106](https://github.com/exactml/marginal/pull/106) by [@exactml](https://github.com/exactml))

### Improvements

- Changelog entries are now one file per PR under `changelog.d/` (e.g.
  `changelog.d/50.feature.md`), assembled into `CHANGELOG.md` by towncrier at
  release time, instead of every PR editing the same `UNDER DEVELOPMENT` block.
  Two open PRs no longer conflict over the changelog, and git's auto-merge can
  no longer drop an entry under an already-released version. The rendered
  format is unchanged; `CONTRIBUTING.md` documents the fragment types, and the
  `cut-release` skill now builds the release section with `towncrier build`. A
  new CI check fails a PR that adds no fragment, unless it has the
  `skip-changelog` label

  ([ISSUE-107](https://github.com/exactml/marginal/issues/107),
  [PR-108](https://github.com/exactml/marginal/pull/108) by [@exactml](https://github.com/exactml))

### Fixes

### Warnings

## marginal v0.2.4, 2026-09-20

### Breaking Changes

### New Features

### Improvements

### Fixes

- Fixes a regression introduced in v0.2.3: `AnthropicProvider.generate_structured`'s
  `strict: true` tool definition was rejected outright by the API (`400
  invalid_request_error`) for every request, because `Finding.confidence`'s
  `ge`/`le` bounds and `_FindingsResponse.findings`' `max_length` render as
  `minimum`/`maximum`/`maxItems` -- keywords outside strict tool use's supported
  JSON Schema subset. The wire schema sent to Anthropic now has those keywords
  stripped (and a nullable field's `anyOf: [{type: X}, {type: "null"}]` rewritten
  to the `{"type": [X, "null"]}` form Anthropic's docs describe), while pydantic's
  own validation of the response still enforces the same bounds locally -- the
  server-side guarantee for a bound is gone, the check itself isn't.
  `_strict_input_schema` checks every schema keyword against two explicit
  lists (confirmed-unsupported -> stripped, confirmed-supported -> kept) and
  raises immediately on anything in neither -- a keyword nobody's vetted yet
  now breaks a test the next time a constrained field is added, instead of
  breaking production the way this regression did

  ([ISSUE-96](https://github.com/exactml/marginal/issues/96),
  [PR-101](https://github.com/exactml/marginal/pull/101) by [@exactml](https://github.com/exactml))

### Warnings

## marginal v0.2.3, 2026-09-20

### Breaking Changes

### New Features

### Improvements

### Fixes

- `AnthropicProvider.generate_structured` now sets `strict: true` on its tool
  definition, so Claude's response is generated via grammar-constrained decoding
  instead of free-form generation that merely tries to follow the schema. The
  two-attempt retry from ISSUE-96 stays in place as a dormant safety net (e.g. a
  schema complex enough to hit strict mode's compilation limits fails at the
  request level, not via a validation mismatch), but the schema-mismatch failures
  ISSUE-96 was built to recover from should no longer occur in the first place --
  the server can no longer emit a token that violates `_FindingsResponse`'s shape

  ([ISSUE-96](https://github.com/exactml/marginal/issues/96),
  [PR-99](https://github.com/exactml/marginal/pull/99) by [@exactml](https://github.com/exactml))

### Warnings

## marginal v0.2.2, 2026-09-20

### Breaking Changes

### New Features

### Improvements

### Fixes

- `AnthropicProvider.generate_structured` and `OpenAIProvider.generate_structured` now
  retry once (two attempts total) when the model's response fails schema validation,
  instead of failing the review outright on the first mismatch. Observed live twice on
  the exact same `_FindingsResponse` schema, in two different shapes -- an extra
  wrapper key around the payload, and the correct payload double-encoded as a string
  inside the field it belongs in -- both are the kind of one-off structured-output
  quirk a second attempt at the identical request routinely clears. A transport-level
  `ProviderAPIError`, or a response with no tool call/content at all, still fails
  immediately without retrying -- only a schema mismatch gets the second attempt

  ([ISSUE-96](https://github.com/exactml/marginal/issues/96),
  [PR-97](https://github.com/exactml/marginal/pull/97) by [@exactml](https://github.com/exactml))

### Warnings

## marginal v0.2.1, 2026-09-20

### Breaking Changes

### New Features

- `marginal init` now seeds `.marginal/policies/README.md` with guidance and
  distinguishes forced reruns with `↻ Overwrote` status lines, so the policy
  directory survives the first commit and scaffold changes are visible

  ([ISSUE-75](https://github.com/exactml/marginal/issues/75),
  [PR-80](https://github.com/exactml/marginal/pull/80) by [@dvd233](https://github.com/dvd233))

- `marginal review` can now return more than one finding per run. The
  reviewer model is asked for a bounded list of the most important,
  actionable issues in the diff (up to 20) instead of a single one, so
  `config.review.confidence_threshold` and `config.review.max_comments` --
  already built to filter and cap a *list* of findings -- finally have more
  than one item to work with. A diff with several real issues can now
  produce several posted findings in one review, capped at `max_comments`
  (highest-confidence first); a diff with nothing worth flagging still
  produces the same metadata-only summary as before

  ([ISSUE-57](https://github.com/exactml/marginal/issues/57),
  [PR-79](https://github.com/exactml/marginal/pull/79) by [@exactml](https://github.com/exactml))

- `marginal review` now checks whether it actually saw everything that
  changed in the PR. `GitHubClient.get_pull_request_files` previously made
  one unpaginated call to GitHub's files endpoint, so a PR with more files
  than fit on a single page was silently truncated -- it now follows every
  page GitHub returns (up to GitHub's own 3000-file-per-PR cap). Separately,
  a file whose `patch` GitHub omits (large diff or binary) is now detected
  and named. Either gap -- a file count short of `changed_files`, or a
  present-but-patchless file -- surfaces as a `⚠️ **Incomplete review
  coverage**` / `⚠️ **No diff available**` line in the same summary/review
  body as the existing redaction warning, so a review with no findings
  can't be mistaken for one that looked at everything and found nothing

  ([ISSUE-71](https://github.com/exactml/marginal/issues/71),
  [PR-73](https://github.com/exactml/marginal/pull/73) by [@exactml](https://github.com/exactml))

- Added `marginal.graph.build_symbol_graph`, a same-repo Python symbol graph
  built by `ast`-parsing every tracked file: every module- and class-level
  function/class definition, plus every call site resolved to its
  definition on a best-effort basis (a same-module match first, otherwise
  the one definition repo-wide whose name matches uniquely). A call to
  `Widget().render()` in one file now resolves to `Widget.render`'s
  definition in another; an ambiguous or dynamic call site is left
  unresolved rather than guessed. Nothing consumes the graph in a review
  yet -- this is the indexer the diff-to-caller lookup and prompt wiring in
  upcoming work build on

  ([ISSUE-82](https://github.com/exactml/marginal/issues/82),
  [PR-89](https://github.com/exactml/marginal/pull/89) by [@exactml](https://github.com/exactml))

### Improvements

### Fixes

- `AnthropicProvider.generate_structured` and `OpenAIProvider.generate_structured`
  now catch `pydantic.ValidationError` when the model returns content that does
  not match the requested schema and re-raise it as `ProviderResponseError`.
  Previously a malformed tool-call or JSON payload crashed the review job with
  a raw traceback instead of the one-line provider error `run_review` already
  handles

  ([ISSUE-39](https://github.com/exactml/marginal/issues/39),
  [PR-42](https://github.com/exactml/marginal/pull/42) by [@HarshRajSinghania](https://github.com/HarshRajSinghania))

### Warnings

## marginal v0.2.0, 2026-09-12

### Breaking Changes

- `marginal review`'s exit code for a configured `models.reviewer` missing
  its required credentials (`MissingCredentialsError`) changes from `1` to
  `3`, distinct from the `1` still returned for every other provider/GitHub
  error. Lets a caller -- `marginal-action`, specifically -- tell "this is
  misconfigured, go fix it" apart from "expected, e.g. a forked PR whose
  secrets GitHub never forwarded" and react differently instead of failing
  both alike

  ([ISSUE-60](https://github.com/exactml/marginal/issues/60),
  [PR-61](https://github.com/exactml/marginal/pull/61) by [@exactml](https://github.com/exactml))

### New Features

- `marginal review` now folds the content of any `config.policies` files into
  the finding-generation prompt, via a new `marginal.policy.load_policies`
  (reads each path relative to the repo root, skipping and warning to stderr
  on a missing file rather than failing the whole review). With no policies
  configured -- the default -- the prompt is unchanged from before. This
  makes `marginal/policy/__init__.py`'s previously-empty stub load-bearing
  for the first time; folding the loaded policies into a model's own
  understanding of *why* a policy applies is left for later

  ([ISSUE-29](https://github.com/exactml/marginal/issues/29),
  [PR-40](https://github.com/exactml/marginal/pull/40) by [@exactml](https://github.com/exactml))

- `marginal review` now redacts likely secrets from a diff before it's
  folded into the finding-generation prompt, via a new
  `marginal.review.redact_secrets`: a small, fixed set of high-confidence
  patterns (PEM private-key blocks, JWTs, GitHub tokens, AWS access keys,
  and generic `api_key=`/`token=`/`secret=` assignments) get their value
  masked as `[REDACTED]`. Applied unconditionally to every file's patch as
  a safety default, not opt-in -- a patch with nothing matching passes
  through byte-for-byte unchanged, and the generic-assignment pattern is
  deliberately conservative so it doesn't mangle a plain identifier or
  function call. Masking it from the model isn't the whole story, though:
  `run_review` also names any redacted file in a `⚠️ **Redacted a likely
  secret**` line folded into the same summary/review body, so the client
  still learns a credential landed in their diff and can rotate it --
  still exactly one `create_review` call, not a second comment. This is a
  fixed pattern set, not exhaustive secret detection: false negatives (a
  real secret in an unrecognized shape) are the accepted failure mode

  ([ISSUE-47](https://github.com/exactml/marginal/issues/47),
  [PR-58](https://github.com/exactml/marginal/pull/58) by [@exactml](https://github.com/exactml))

### Improvements

- `marginal review`'s output is restructured for readability instead of flat
  indented text. Findings (both inline comments and the summary-body
  fallback) now lead with a severity+confidence badge (`🔴 **Critical** ·
  92% confidence`) before the message, so they're triageable by eye without
  reading the prose. The overall review gets a `### 🤖 marginal review`
  heading and a compact one-line PR summary, with the changed-file list
  collapsed behind a `<details>` block so it doesn't dominate the review on
  larger PRs. Still not addressed: re-running `marginal review --comment`
  on the same PR after a new push still posts a fresh review restating this
  same header/file-list block -- true dedup across pushes needs either
  identifying and updating a prior review or accepting the (now much
  smaller, collapsed) repetition, and is left open

  ([ISSUE-36](https://github.com/exactml/marginal/issues/36),
  [PR-38](https://github.com/exactml/marginal/pull/38) by [@exactml](https://github.com/exactml))

- `tests/test_cli.py`'s `review` test cases now share `mock_github_client` and
  `mock_provider` fixtures and consistently reuse the existing `_pull_request()`
  helper, replacing roughly ten near-identical inline mock-patching blocks and
  PR-metadata dict literals. Test-only: no behavior or coverage change

  ([PR-41](https://github.com/exactml/marginal/pull/41) by [@exactml](https://github.com/exactml))

- Added `SECURITY.md` documenting how to report a vulnerability responsibly:
  GitHub private vulnerability reporting as the intake channel (no public
  security@ email exists for this project), an acknowledgement/assessment
  response-time commitment, and a supported-versions policy that -- being
  pre-1.0 -- covers only the latest `0.1.x` release on PyPI

  ([ISSUE-62](https://github.com/exactml/marginal/issues/62),
  [PR-67](https://github.com/exactml/marginal/pull/67) by [@exactml](https://github.com/exactml))

- Adopted a `CODE_OF_CONDUCT.md` based on the Contributor Covenant (v2.1),
  with the enforcement contact pointed at the project's existing public
  maintainer email rather than a fabricated address

  ([ISSUE-63](https://github.com/exactml/marginal/issues/63),
  [PR-68](https://github.com/exactml/marginal/pull/68) by [@exactml](https://github.com/exactml))

- Added two Claude Code skills under `.claude/skills/`: `dev-setup` wraps
  CONTRIBUTING.md's manual venv/`pip install -e ".[dev]"`/pre-commit steps
  into a single guided flow that verifies each step instead of assuming it
  worked, and `cut-release` codifies the mechanical `CHANGELOG.md`
  UNDER-DEVELOPMENT-to-dated-version split, the version-bump/tag/branch
  naming this repo already uses, and drafting GitHub release notes with a
  contributor-thanks section -- gated behind an explicit confirmation before
  actually publishing, since publishing fires the PyPI trusted-publish
  workflow immediately and irreversibly

  ([ISSUE-66](https://github.com/exactml/marginal/issues/66),
  [PR-69](https://github.com/exactml/marginal/pull/69) by [@exactml](https://github.com/exactml))

### Fixes

### Warnings

## marginal v0.1.3, 2026-09-09

### Breaking Changes

### New Features

- `marginal review` now wires up `config.review.confidence_threshold` and
  `config.review.max_comments`, both previously dead config. `Finding` gets
  a required `confidence: float` field (the model self-reports it via the
  generation prompt), and every generated finding is run through the new
  `marginal.review.filter_findings` before it can reach a PR comment: dropped
  outright below `confidence_threshold`, then capped at `max_comments`
  (highest-confidence first). If everything gets filtered out, behavior is
  unchanged from no finding being generated at all -- metadata-only summary,
  nothing posted beyond that. `marginal review` currently only ever
  generates one finding per run, so the `max_comments` cap doesn't yet have
  a real multi-finding case to bite on -- covered directly against
  `filter_findings` instead

  ([ISSUE-28](https://github.com/exactml/marginal/issues/28),
  [PR-35](https://github.com/exactml/marginal/pull/35) by [@exactml](https://github.com/exactml))

### Improvements

### Fixes

### Warnings

## marginal v0.1.2, 2026-09-09

### Breaking Changes

### New Features

- `marginal review`'s generated finding is now structured
  (`marginal.review.Finding`: `file`, `line`, `severity`, `message`) instead
  of a raw text blob — generated via `ModelProvider.generate_structured()`
  instead of `generate()`. Still folded into the same one summary
  comment for now (`Finding (severity): file[:line]` followed by the
  message); a finding with no identifiable line falls back to just the
  filename. This is what makes inline per-line comments and confidence-based
  filtering possible next. Raises `ProviderResponseError` (not a bare
  `assert`, which `-O` strips entirely) if a provider's structured output
  doesn't actually come back as a `Finding` — caught live by
  `marginal-action`'s own real review of this PR's diff

  ([ISSUE-26](https://github.com/exactml/marginal/issues/26),
  [PR-30](https://github.com/exactml/marginal/pull/30) by [@exactml](https://github.com/exactml))

- `marginal review --comment` now posts a finding anchored to a `line` as an
  inline review comment (`{path, line, body}`) instead of folding it into
  the one overall review body. A finding with no identifiable line still
  falls back to the body, so nothing is silently dropped. Still exactly one
  `create_review` call either way — inline comments ride along with the
  same review as its `comments` list. `PermissionDeniedError` maps through
  the same existing clean error path, unchanged. The printed local summary
  is unaffected: it still shows every finding (anchored or not), same as
  before — only the posted review body drops the ones that now ride inline
  instead, an omission caught live by `marginal-action`'s own real review of
  this PR's diff

  ([ISSUE-27](https://github.com/exactml/marginal/issues/27),
  [PR-33](https://github.com/exactml/marginal/pull/33) by [@exactml](https://github.com/exactml))

### Improvements

### Fixes

- Provider SDK errors (`anthropic.APIError`, `openai.APIError` — bad
  request, auth failure, rate limit, network error) no longer crash with a
  raw traceback. `AnthropicProvider`/`OpenAIProvider`'s `generate`,
  `generate_structured`, and `stream` now catch them and re-raise as the
  new `ProviderAPIError` (a `ProviderError`), so `run_review`'s existing
  clean error path handles them with no changes needed there. `stream`
  wraps its whole generator body, not just the initial call, so an error
  raised mid-iteration is caught too. Found live in CI via an Anthropic key
  that wasn't scoped to a workspace, and the `stream` gap was caught by
  `marginal-action`'s own review of this PR's diff

  ([ISSUE-31](https://github.com/exactml/marginal/issues/31),
  [PR-32](https://github.com/exactml/marginal/pull/32) by [@exactml](https://github.com/exactml))

### Warnings

## marginal v0.1.1, 2026-09-08

### Breaking Changes

### New Features

- `marginal review` generates a real finding: when `models.reviewer` is
  configured, it builds a prompt from the PR's changed files (filename +
  patch) asking for the single most important, actionable issue, calls that
  model's `.generate()`, and folds the result into the same summary that's
  already printed and, with `--comment`, posted — no second comment, no new
  GitHub-writing path. Without `models.reviewer` configured, behavior is
  unchanged: metadata-only, no model call attempted. A `ProviderError`
  raised while generating surfaces through the same clean
  one-line/non-zero-exit handling as a GitHub error. Still no validation,
  deduplication, or confidence scoring — one raw, unvalidated finding

  ([ISSUE-21](https://github.com/exactml/marginal/issues/21),
  [PR-22](https://github.com/exactml/marginal/pull/22) by [@exactml](https://github.com/exactml))

### Improvements

- Configures a real `models.reviewer` (anthropic, `claude-sonnet-5`) in this
  repo's own `.marginal/config.yaml`, and passes
  `anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}` through to
  `marginal-action` in `.github/workflows/marginal.yml` (requires
  `marginal-action` v1.1.0's provider-key forwarding). Still needs the
  `ANTHROPIC_API_KEY` repository secret added manually before this repo's
  own PRs get a real generated finding instead of a `MissingCredentialsError`

  ([ISSUE-23](https://github.com/exactml/marginal/issues/23),
  [PR-24](https://github.com/exactml/marginal/pull/24) by [@exactml](https://github.com/exactml))

### Fixes

- `marginal init`'s scaffolded `.github/workflows/marginal.yml`: dropped the
  stale "action hasn't shipped yet" comment now that `marginal-action` is
  published, dropped the redundant `actions/checkout@v4` step (the action
  already checks out the consuming repo internally), and added the
  `permissions: pull-requests: write` block the action's README documents
  as required. Also adds this same corrected workflow to `marginal`'s own
  repo, so it reviews its own PRs via `exactml/marginal-action@v1`

  ([ISSUE-19](https://github.com/exactml/marginal/issues/19),
  [PR-20](https://github.com/exactml/marginal/pull/20) by [@exactml](https://github.com/exactml))

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
  [PR-14](https://github.com/exactml/marginal/pull/14) by [@exactml](https://github.com/exactml))

- `marginal review` CLI subcommand: fetches a pull request's metadata and
  changed files via `GitHubClient` and prints a plain-text summary — title,
  state, base/head SHA, and the changed file list. Posts nothing back to
  GitHub, since there's no analysis yet to report, and catches
  `PermissionDeniedError`, `GitHubAuthenticationError`, and `GitHubAPIError`
  at the CLI boundary, printing each as a single line instead of a raw
  traceback and exiting non-zero

  ([ISSUE-11](https://github.com/exactml/marginal/issues/11),
  [PR-12](https://github.com/exactml/marginal/pull/12) by [@exactml](https://github.com/exactml))

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
  [PR-10](https://github.com/exactml/marginal/pull/10) by [@exactml](https://github.com/exactml))

- `marginal init` CLI command: scaffolds `.marginal/config.yaml` (serialized
  from a default `MarginalConfig`, so it can never drift from the schema),
  an empty `.marginal/policies/`, and a starter
  `.github/workflows/marginal.yml`. Each artifact is skipped (not
  overwritten) if already present, unless `--force` is given. Adds the
  `marginal` console entry point and an argparse-based subcommand dispatcher
  in `marginal/cli/` for future subcommands to plug into

  ([ISSUE-7](https://github.com/exactml/marginal/issues/7),
  [PR-8](https://github.com/exactml/marginal/pull/8) by [@exactml](https://github.com/exactml))

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
  [PR-6](https://github.com/exactml/marginal/pull/6) by [@exactml](https://github.com/exactml))

- Repository-local config schema: `marginal.config.load_config` parses and
  validates `.marginal/config.yaml` (review behavior, context toggles, model
  selection, ownership behavior, policy paths, and agent permissions) into a
  typed `MarginalConfig`, defaulting every field to a least-privilege
  baseline and raising `ConfigParseError` on malformed YAML or
  `ConfigValidationError` on invalid values (both `ConfigError`), each with
  a clear message. Adds `pydantic` and `pyyaml` as runtime dependencies

  ([ISSUE-3](https://github.com/exactml/marginal/issues/3),
  [PR-4](https://github.com/exactml/marginal/pull/4) by [@exactml](https://github.com/exactml))

### Improvements

- PyPI packaging: publishes as `marginal-review` on PyPI (the `marginal` name
  is already taken by an unrelated project) via a trusted-publishing
  GitHub Actions workflow triggered on a published GitHub Release. The
  importable module and `marginal` console command are unaffected — only
  the `pip install` name changes

  ([ISSUE-17](https://github.com/exactml/marginal/issues/17),
  [PR-16](https://github.com/exactml/marginal/pull/16) by [@exactml](https://github.com/exactml))

- Project scaffold: `marginal` package layout (`config`, `providers`, `context`,
  `graph`, `policy`, `agent`, `review`, `github`, `cli`), `ruff` + `pytest`
  tooling, CI workflow, `CONTRIBUTING.md`, and the language/runtime ADR

  ([ISSUE-1](https://github.com/exactml/marginal/issues/1),
  [PR-2](https://github.com/exactml/marginal/pull/2) by [@exactml](https://github.com/exactml))

### Fixes

### Warnings
