# Security Policy

marginal reads pull request diffs -- including, in the course of that,
whatever secrets a diff happens to contain -- and its
`marginal.review.redact_secrets` step exists specifically to keep those out
of prompts and comments. That makes marginal itself a piece of your security
surface, so vulnerabilities in how it handles code, credentials, or model
provider calls should be reported responsibly rather than filed as public
issues.

For how marginal maps to SOC 2 and ISO 27001 controls, and what your team
stays responsible for, see [docs/compliance.md](docs/compliance.md).

## Reporting a Vulnerability

**Do not open a public GitHub issue for a security vulnerability.**

Report it privately via GitHub's
[private vulnerability reporting](https://github.com/exactml/marginal/security/advisories/new)
for this repository (Security tab -> "Report a vulnerability"). This opens a
private advisory visible only to you and the maintainers, and lets us
collaborate on a fix before any details become public.

Please include:

- The affected version (see [Supported Versions](#supported-versions) below)
- A description of the vulnerability and its potential impact
- Steps to reproduce, or a minimal proof of concept

## Response Time

We aim to acknowledge new reports within **5 business days** and to provide
an initial assessment -- confirmed, not applicable, or need more information
-- within **10 business days**. Time to a fix depends on severity and
complexity; we'll keep you updated on progress throughout.

We'll credit reporters in the eventual advisory and release notes, unless
you'd prefer to stay anonymous.

## Supported Versions

marginal is pre-1.0 and evolving quickly. Security fixes ship in the latest
release published to PyPI as
[`marginal-review`](https://pypi.org/project/marginal-review/); we don't
backport them to older releases.

| Version | Supported |
| ------- | --------- |
| latest | :white_check_mark: |
| < latest | :x: |

Once marginal reaches 1.0, this policy will be revisited to define a longer
support window.

## Pinned versions

You can pin marginal to a version and upgrade on your own schedule (see
[Pinning and upgrading](README.md#pinning-and-upgrading)). Three promises
make that safe:

- **You'll be told about security fixes.** Every security fix is published as
  a [GitHub Security Advisory](https://github.com/exactml/marginal/security/advisories)
  against the `marginal-review` package, and listed under **Security** in
  [CHANGELOG.md](CHANGELOG.md) and the release notes. To be notified, watch
  this repository for security alerts (Watch -> Custom -> Security alerts).
  Dependabot alerts only reach a repo that lists `marginal-review` in a
  dependency manifest, such as a `requirements.txt`; it doesn't read the
  `marginal-version:` input of a workflow.
- **Breaking changes are never hidden.** Each one is listed under **Breaking
  Changes** and never ships in a patch release: it always comes with at least
  a minor version bump (`0.3.x` -> `0.4.0`).
- **You can jump straight to the latest release.** You don't need to step
  through the releases in between: read only their **Breaking Changes** and
  **Security** sections, then change the pinned version.

Each release also attaches `constraints.txt` to its
[GitHub release](https://github.com/exactml/marginal/releases): the exact
dependency versions it was built and tested with. With `marginal-version`
pinned, `marginal-action` installs those versions too, so nothing changes
underneath you.
