`marginal review --comment` no longer fails, and no longer loses every
finding, when the model pins one finding to a line outside the diff. GitHub
only accepts inline comments on lines inside the diff's hunks and rejects the
whole review (`GitHub API error 422`) over a single one placed anywhere else,
so the run exited 1 and posted nothing. A finding on such a line, or in a
file GitHub shows no patch for, is now posted in the review body with its
`file:line`, like a finding with no line

([PR-132](https://github.com/exactml/marginal/pull/132) by [@exactml](https://github.com/exactml))
