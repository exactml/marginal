---
name: marginal-pair
description: >-
  Pair this coding session with marginal as a separate, isolated reviewer
  before anything is pushed: run `marginal review --local` on the user's
  Claude Code subscription, treat each finding as an unverified claim, fix or
  dispute it with evidence, and repeat until marginal has nothing left (max 3
  rounds). Stops before `git push` and asks. Use when the user says "pair with
  marginal", "/marginal-pair", "/marginal:marginal-pair", "review before I
  push", "cook this PR with marginal", or a branch is about to be pushed.
allowed-tools: Bash, Read, Edit, Write
---

# marginal-pair — review locally until clean, then ask before pushing

You are the coder. marginal is the reviewer. It runs in its own `claude -p`
process with no tools and none of this session's context, so it sees only the
diff, nearby code and callers: what the PR's CI review will see. Don't argue
with it in the prompt; answer it with code or with evidence.

## Step 1 — Preconditions

```bash
git rev-parse --abbrev-ref HEAD          # must not be the default branch
git fetch -q origin
# origin/HEAD is only set by `git clone`; ask the remote otherwise.
git symbolic-ref -q refs/remotes/origin/HEAD >/dev/null || git remote set-head origin -a
BASE=$(git symbolic-ref --short refs/remotes/origin/HEAD)   # e.g. origin/master
marginal --version && claude --version
marginal review --help | grep -q -- --local   # needs marginal-review 0.4.0 or later
```

If `marginal` isn't found, activate the environment it's installed in, or ask
the user to `pip install marginal-review`; if it has no `--local`, ask them to
`pip install -U marginal-review`. If `claude` isn't found, this skill
can't run the reviewer. If on the default branch, stop and ask for a branch
name. New files the change needs must be visible to git: `git add -N <file>`
(marginal says how many untracked files it skipped).

## Step 2 — Review

```bash
marginal review --local "$BASE" --provider claude-code --format json
```

- Exit 3: `claude` is missing or signed out, so tell the user to run `claude` and sign in.
- "needs --model": the repo's `models.reviewer` isn't a Claude model (or isn't
  set), so add `--model opus`.
- stdout is one JSON object. Use `findings` (each already passed marginal's
  quote and trigger checks) and ignore `dropped_findings`.

## Step 3 — Judge each finding before touching code

A finding passed the evidence check, so its quote is real. Its *reasoning* can
still be wrong. For each one:

1. Read the code at `file:line` and the code its `trigger` names.
2. Check that the trigger can actually happen: does the call or caller it
   describes exist (`grep` for it)? Does the input it names reach that line?
3. Check it against the repo's rules: the files under `policies` and
   `anti_policies` in `.marginal/config.yaml`. A finding that contradicts an
   anti-policy (a tradeoff the team accepted) is false; cite that file.
4. Verdict:
   - **Real, Medium or above:** fix it with the smallest change, add or adjust a
     test, and commit it alone (one finding, one commit).
   - **Real, Low:** fix it only if it takes a few lines; otherwise mark it
     deferred, with a reason.
   - **False:** change nothing. Write the evidence (e.g. "nothing calls
     `get_file` with `head`; the only callers pass `base_sha`, context/base.py:24,39").
   - **Same Low in several places:** fix the whole class once, not one spot per round.

Run the repo's lint and tests before the next round.

## Step 4 — Repeat

Rerun Step 2. Stop when any of these is true:
- there are no findings;
- every finding left is one you already disputed or deferred;
- 3 rounds have run.

## Step 5 — Report, then ask

Show one table: round, severity, `file:line`, finding, verdict (fixed with
the commit / disputed with evidence / deferred with a reason). Then ask the user
whether to push. Never `git push`, open a PR or force anything without an
explicit yes. Once the PR exists, post each disputed finding's evidence as a
reply if marginal raises it again in CI.
