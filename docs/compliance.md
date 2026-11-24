# marginal and SOC 2 / ISO 27001 controls

Teams under SOC 2, ISO/IEC 27001 or a similar framework have to show an
auditor how a tool that reads their code and comments on their merges is
controlled: what data leaves, who can change its settings, and where the
evidence lives. This page maps marginal's behavior to the control areas an
auditor usually asks about, and says plainly what marginal does **not** do.

> **This is a mapping to help your team, not a certification.** marginal has
> no SOC 2 report or ISO 27001 certificate, and nothing here is an
> attestation. Your controls are yours; this page shows where marginal fits
> in them.

## How marginal runs

There is no marginal service. marginal is a Python package
([`marginal-review`](https://pypi.org/project/marginal-review/)) that runs in
your GitHub Actions (through
[`exactml/marginal-action`](https://github.com/exactml/marginal-action)) or on
a developer's machine. It reads a pull request with the token you give it,
sends a prompt to the model provider you configure with your key, and posts
comments back. Nothing is sent to the marginal project.

## Control mapping

Rows marked **planned** describe work that hasn't shipped yet; they say what
you can rely on today.

| Control area | SOC 2 (TSC) | ISO/IEC 27001:2022 Annex A | What marginal provides | Backed by |
|---|---|---|---|---|
| Change management | CC8.1 | A.8.32 | A review on every PR the workflow triggers on. Config, policies and anti-policies are read from the PR's **base commit**, so a PR can't switch its own review off or silence a finding; the summary says when a PR edits `.marginal/`. Per-review audit record: **planned** (#163); today the evidence is the PR's comments and the Actions run log. | [ADR 0004](adr/0004-review-rules-from-the-base-commit.md), `review.*` in `.marginal/config.yaml` |
| Access control / least privilege | CC6.1, CC6.3 | A.5.15, A.8.2 | marginal reads the PR and posts comments. Every write is gated by a `permissions.write.*` key and checked before the API call: `comments` on by default; `labels`, `approve` and `push` off by default. There is no merge call at all. The workflow needs only `pull-requests: write` and `contents: write` (to resolve fixed threads), plus `issues: write` if `labels` is on and the `marginal:<severity>` labels don't exist yet (GitHub creates a missing label on first use). When marginal reads its own earlier comments back (for knowledge proposals), it trusts only those posted by the workflow's bot or by people with write access. | `permissions:` in `.marginal/config.yaml`, README [Safe to run on your code](../README.md#safe-to-run-on-your-code), `marginal doctor` |
| Data sent to third parties | CC6.7, CC9.2 | A.5.19–A.5.23, A.8.12 | The prompt holds the PR's diff, callers of changed functions, your policies, anti-policies and accepted knowledge, maintainer replies to marginal's comments, and the triggering CI run's conclusion. Not the PR's title or description. Likely secrets are replaced with `[REDACTED]` in the diff, caller snippets, accepted knowledge and replies before the prompt is sent (policies and anti-policies, which your team writes, are sent as written); detection uses a small set of sure patterns, so a secret in an unusual shape can still pass. `review.ignore_paths` keeps lockfiles and generated files out. To keep code off third-party APIs, use `provider: ollama` (a model you host) or `base_url` to reach an endpoint you approve. First-class Azure OpenAI, Bedrock and Vertex providers: **planned** (#268). | [ADR 0006](adr/0006-secret-redaction.md), `models.*`, `review.ignore_paths`, `context.*` |
| Logging and monitoring | CC7.2 | A.8.15, A.8.16 | Today: the Actions run log, the PR's review comments and summary, and `marginal review --format json` for your own pipeline. One structured record per review and per finding outcome, written to a sink you choose: **planned** (#163). marginal keeps no logs of its own, so retention is set by your GitHub and sink settings. | GitHub Actions logs, `--format json` |
| Secure development / supply chain | CC8.1 | A.8.25, A.8.28 | Every marginal change passes lint and tests in CI and is reviewed by marginal itself; changes a team would see are proven on a real test repo before release. Releases are published to PyPI from a GitHub Release by trusted publishing (OIDC, no stored token). You can pin the version with `marginal-version`; pinning its dependencies to the versions a release was tested with: **planned** (#270). | [ADR 0002](adr/0002-marginal-action-composite.md), [ADR 0007](adr/0007-prove-changes-on-a-real-repo-before-release.md), `.github/workflows/publish.yml` |
| Vulnerability management | CC7.1 | A.8.8 | Private reporting through GitHub Security Advisories, with response targets and a support window (security fixes ship in the latest release). | [SECURITY.md](../SECURITY.md) |

## Shared responsibility

marginal provides the controls above. Your team is responsible for:

- **Choosing the model provider** and checking its data terms: whether it
  keeps prompts, trains on them, and where it processes them. A self-hosted
  model keeps code inside your infrastructure.
- **Protecting the provider key and the GitHub token**: store them as
  repository or organization secrets, and keep the workflow's
  `permissions:` to what the README lists.
- **Deciding who can merge changes to `.marginal/`**, for example with a
  CODEOWNERS entry and branch protection. marginal makes sure a PR can't
  change its own rules, but whoever can merge to the base branch decides
  them.
- **Keeping the evidence**: set retention for Actions logs, and, once audit
  records ship (#163), choose and retain their sink.
- **Deciding what a finding means for a merge**: marginal comments; branch
  protection and required reviewers decide what can merge.
- **Watching for security fixes**: watch the marginal repository for
  security alerts. Dependabot alerts only reach a repo that lists
  `marginal-review` in a dependency manifest, not one that pins it through
  marginal-action's `marginal-version` input.

## Evidence an auditor can collect

| Evidence | Where it lives |
|---|---|
| The rules a review ran under | `.marginal/config.yaml`, `.marginal/policies/` and `.marginal/knowledge/` at the PR's base commit (git history) |
| Who changed those rules, and who approved it | The PR that changed `.marginal/`, its review, and its merge (GitHub) |
| That a PR was reviewed, and what was found | marginal's summary and inline comments on the PR; the Actions run log |
| How a finding was handled | The review thread: the fix commit, a maintainer's reply, or marginal resolving it on a later push |
| What marginal is allowed to do | `permissions:` in `.marginal/config.yaml`, the workflow's `permissions:` block |
| Which version ran | The `marginal-version` input (if pinned) and the install step in the Actions run log |
| Per-review records with model, cost and outcome | **Planned** (#163) |

## Not covered

marginal does not:

- certify or attest to any framework, for itself or for your code;
- replace human review or branch protection;
- detect every secret (see the limits in [ADR 0006](adr/0006-secret-redaction.md));
- store or retain anything itself, so it can't produce evidence your GitHub
  settings didn't keep;
- control what your model provider does with a prompt once sent.

The optional Organizational Intelligence Core (`marginal-review[oic]`) is in
development and is not covered by this page yet.
