You are reviewing a pull request. Identify the most important, actionable issues in the diff below -- as many as are genuinely warranted, up to {max_findings}. Return an empty list if nothing in the diff is worth flagging. For each issue, report the file it's in, the line number in the new version of the file if you can identify one (null if you can't), a severity, and a concise 2-3 sentence explanation of the problem and its effect. Rate severity by how bad the effect is when it happens and how likely it is to happen:
- critical: a security hole someone can use (an auth or permission check that can be skipped, injection, a leaked secret), data loss, or a wrong result for every user.
- high: a wrong result or a crash on a normal, realistic input.
- medium: wrong only in an edge case, or it works but worse (slower, noisier).
- low: a small effect, unlikely to matter in practice.
Then show your work, which is checked against the code before anything is posted:
- trigger: the concrete input, state or call path that makes it go wrong, naming the functions or variables involved in backticks.
- evidence: 1-3 lines of code the issue rests on, each with its file, its line number in the new version, and the line's text copied exactly. Quote only lines shown below (the diff or the caller context).
- assumptions: what must be true for this to be a problem that you couldn't see; an empty list if none.
Don't report an issue you can't quote evidence for, or a stylistic nitpick.
