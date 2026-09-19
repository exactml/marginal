# ADR 0003: Two-layer code graph -- per-language symbol graphs plus a separate contract-linking layer

**Choice:** Build the code-graph context feature (`config.context.code_graph`) as
two independent layers behind one shared interface (`SymbolGraph`, `Definition`,
`CallSite`): (1) one symbol graph per language, each populated by whatever
indexing method suits that language, merged into the shared interface; (2) a
separate layer above that links *across* those per-language graphs wherever the
dependency is a contract -- an HTTP route, a protobuf/OpenAPI/GraphQL schema --
rather than a shared symbol name. #82 ships layer 1's first slice (Python only,
via the stdlib `ast` module); #90 investigates the per-language indexing
methodology for the general case; #91 scopes layer 2.

**Why:** A same-repo Python call resolves by name -- `Widget().render()` and
`class Widget: def render(...)` share the string `render` somewhere in the
graph, however indirectly. A cross-language dependency usually doesn't: a
Python `def get_order(...)` and a TypeScript `fetch("/api/orders/:id")` share
no symbol name at all, however good the parser is on either side. No amount of
per-language parsing precision closes that gap -- it needs a second mechanism
entirely, matching on the contract (the route string, the schema field) both
sides actually agree on. Keeping that as its own layer, rather than trying to
stretch symbol resolution to cover it, keeps each layer's job well-defined and
lets them be worked on independently.

This also reconciles with [ADR 0001](0001-language-and-runtime.md), which
anticipated `tree-sitter`'s Python bindings for code graph parsing specifically.
#82 shipped with stdlib `ast` instead -- zero new dependencies, enough to prove
the concept and unblock #83/#84's prompt-wiring work immediately. That
substitution is safe only because the public interface (`SymbolGraph`,
`Definition`, `CallSite`) was designed to be resolver-agnostic from the start:
swapping `ast` for `tree-sitter`, `SCIP`, or anything else #90 recommends is an
internal change to `marginal/graph/symbols.py`, not a break to anything
downstream. `tree-sitter` (or SCIP, which uses tree-sitter-based indexers under
the hood for several languages) remains the leading candidate for layer 1's
general, multi-language case -- #90 is where that gets decided against
evidence rather than assumed upfront.

This is also a deliberate point of difference from the other PR-review tools
in this space (`pr-agent`, `octopus`, `roborev` -- all evaluated directly,
local checkouts under `~/workspaces/open-source/`). None of them build a real
structural code or call graph: `pr-agent` and `roborev` are diff-text-only
(`roborev`'s own config goes as far as stating it doesn't attempt structural
claims and trusts the build instead); `octopus` has a UI feature literally
named "code graph," but its nodes are files, not symbols, and its edges come
from a single import-statement regex plus embedding cosine-similarity, not
call resolution. All three achieve "works across any language" specifically by
not attempting real structural understanding at all -- diff text and
embeddings are language-agnostic because neither one parses syntax. marginal's
bet is the opposite: real per-language structural resolution, merged behind
one interface, with cross-language contract edges as an explicit additional
layer rather than a gap nobody names. The tradeoff is real engineering cost
layer 1 alone doesn't pay for itself on: the advantage stays Python-only until
#90 and #91 land, and a polyglot repo gets partial coverage in the meantime,
same as it does today.
