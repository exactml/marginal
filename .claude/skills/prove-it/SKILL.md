---
name: prove-it
description: >-
  Prove a marginal pull request is ready to merge, with evidence for every
  claim: CI green, lint and tests passing, no unanswered marginal findings, a
  code-cleanup pass, and (when the change affects what a team sees on a PR)
  a real end-to-end review on exactml/marginal-client with the PR's branch.
  Writes the results to an "Evidence" section in the PR body. Use when a PR
  is about to be called done: "prove it", "is this PR ready", "prove-it
  #148", "evidence for this PR", or before asking for a merge.
allowed-tools: Bash, Read, Edit, Skill
---

# prove-it — show that a PR works, don't just say it

"Ready to merge" is a claim. This skill turns it into evidence a reviewer
can click: a link or a command output for each check. A check that wasn't
run is reported as not run, never as passed.

Work on one PR at a time. Find it from the argument (`#148`, a URL, a
branch) or from the current branch with `gh pr view --json number`.

## Check 1 — CI is green

```bash
gh pr checks <n> --watch
```

Every check must pass (`lint-and-test`, `fragment` (or the
`skip-changelog` label), `review`). A failure stops here: fix it, push,
start over. Evidence: the checks' names, each with its run link.

## Check 2 — Lint and tests pass locally

```bash
make lint && make test
```

`make lint` includes `ruff format --check`, which CI also runs. Evidence:
the test count line, e.g. `381 passed`.

## Check 3 — No unanswered marginal findings

marginal reviews every PR. Each finding must be either **fixed** (its
thread is resolved) or **answered** (a reply explains why it's wrong or why
it stays). List the threads:

```bash
gh api graphql -f query='
  query($owner:String!,$repo:String!,$n:Int!){repository(owner:$owner,name:$repo){
    pullRequest(number:$n){reviewThreads(first:100){nodes{
      isResolved comments(first:20){nodes{author{login} body url}}}}}}}' \
  -f owner=exactml -f repo=marginal -F n=<n>
```

A thread is marginal's when its first comment contains
`<!-- marginal:finding:`. For each one that's unresolved with no reply after
it, stop and either fix the code or reply in the thread. Don't resolve a
thread without a fix or an answer. Evidence: `N findings: X fixed, Y
answered, 0 open`, linking each answered thread.

## Check 4 — Cleanup pass

Review the PR's diff for anything it doesn't need: dead code, a needless
abstraction, a missed edge case. Use `/ponytail:ponytail-review` if it's
installed, otherwise `/simplify`. For each finding, apply it or dismiss it
with a one-line reason. If you change code, commit and push, then go back to
Check 1, since CI and marginal run again. Evidence: `N findings: X applied,
Y dismissed`, each with a short note.

## Check 5 — Real end-to-end review on marginal-client

**Required** when the PR changes what a team sees on a pull request: review
output, findings, skip rules, `ignore_paths`, config, the workflow
`marginal init` writes, provider behavior. **Exempt** for docs, tests, CI,
and skill-only changes. Write `exempt: <reason>` instead.

1. Pick the scenario from the release checklist in
   [marginal-client's README](https://github.com/exactml/marginal-client#release-checklist)
   that exercises the change. If none does, add one to that README in the
   same step.
2. Open the scenario PR on marginal-client from a branch named
   `prove-it/<marginal-branch>`. Those branches skip the automatic `master`
   review.
3. Review it with the PR's branch, and wait for the run (it takes a few
   seconds to appear in the list):
   ```bash
   gh workflow run marginal.yml -R exactml/marginal-client -f ref=<marginal-branch> -f pr=<client PR>
   gh run watch -R exactml/marginal-client $(gh run list -R exactml/marginal-client --workflow marginal.yml --limit 1 --json databaseId --jq '.[0].databaseId')
   ```
4. Read what marginal posted (or, for a skip, the run log line) and compare
   it with the scenario's "Expect" column. A mismatch is a failure: fix,
   push, start over.
5. Close the scenario PR unmerged, with a comment linking the marginal PR.

This needs write access to marginal-client. Without it, write
`⏳ needs a maintainer` and stop there. Evidence: the link to the review or
run, plus one line on what it showed.

## Write the evidence into the PR body

Replace the section between the markers if it's already there, otherwise
append it. Record the commit the evidence is for: a later push makes it
stale, so run the skill again.

```markdown
<!-- prove-it -->
## Evidence @ `<short head SHA>`

| Check | Result |
|---|---|
| CI | ✅ lint-and-test, fragment, review ([runs](<link>)) |
| Tests | ✅ 381 passed, lint clean |
| marginal | ✅ 2 findings: 1 fixed, 1 answered ([thread](<link>)), 0 open |
| Cleanup | ✅ ponytail-review: 1 applied (label casefold), 0 open |
| E2E | ✅ [marginal-client#4](<link>), scenario 8: PR with `Skip-Review` label skipped |
<!-- /prove-it -->
```

```bash
gh pr view <n> --json body --jq .body > body.md   # edit the section, then:
gh pr edit <n> --body-file body.md
```

Use ✅ only with evidence next to it. Use ❌ for a failure and ⏳ for a
check that couldn't run. Then tell the user, in one line, whether the PR is
ready: every check ✅ (or E2E exempt with a reason) means ready. Anything
else means not ready, and say what's missing.
