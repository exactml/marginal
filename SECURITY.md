# Security Policy

marginal reads pull request diffs -- including, in the course of that,
whatever secrets a diff happens to contain -- and its
`marginal.review.redact_secrets` step exists specifically to keep those out
of prompts and comments. That makes marginal itself a piece of your security
surface, so vulnerabilities in how it handles code, credentials, or model
provider calls should be reported responsibly rather than filed as public
issues.

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

marginal is pre-1.0 (currently `0.1.x`) and evolving quickly. Only the
latest release published to PyPI as
[`marginal-review`](https://pypi.org/project/marginal-review/) receives
security fixes; we don't backport patches to older `0.1.x` releases.

| Version | Supported |
| ------- | --------- |
| latest `0.1.x` | :white_check_mark: |
| < latest | :x: |

Once marginal reaches 1.0, this policy will be revisited to define a longer
support window.
