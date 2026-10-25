# ADR 0003: Two-layer code graph

**Status:** Accepted · 2026-09-19 · updated 2026-10-25

## Context

A diff shows what changed, not what depends on it. If a PR changes
`total(order)` to `total(order, currency)`, the call in `checkout.py` that
still passes one argument is outside the diff, and a diff-only reviewer never
sees it. marginal's "context over diff" promise needs a map of who calls what.

There are two kinds of dependency:

- **Same-language calls** share a name. Python's `checkout.py` calls
  `pricing.total`, and a parser can match the two by name.
- **Cross-language dependencies** usually share no name at all. A Python
  `def get_order(...)` behind the route `/api/orders/:id` and a TypeScript
  `fetch("/api/orders/:id")` only agree on the route string. No parser,
  however good, links them by symbol name.

## Decision

Build the code graph as **two layers behind one interface** (`SymbolGraph`,
`Definition`, `CallSite`):

1. **Per-language symbol graphs.** Each language is indexed by whatever method
   suits it, and all of them produce the same `Definition` / `CallSite` shapes.
   Python came first, using the standard library's `ast` module: no new
   dependency, and enough to prove the idea.
2. **A contract layer on top.** It links the per-language graphs where the
   dependency is a contract (an HTTP route, an OpenAPI, protobuf or GraphQL
   schema) rather than a shared name.

Because the interface doesn't depend on the parser, swapping `ast` for
tree-sitter or SCIP-style indexers later is an internal change, not a break
for anything that uses the graph.

## Trade-offs

| Option | Pros | Cons |
|---|---|---|
| **Per-language symbol graphs + a contract layer** (chosen) | Real call resolution: finds the actual broken caller, with its line as evidence. Each layer has one clear job and can grow on its own. | Real engineering cost per language. Until more languages are indexed, other languages get a diff-only review. |
| Diff text only | Works on every language with zero effort. | Can't see a caller outside the diff, which is the main thing diff reviewers miss. |
| File-level graph from import regexes + embeddings | Cheap and language-agnostic. | Nodes are files, not functions, and similarity isn't a call. It can't say *which* caller breaks. |
| One universal parser for cross-language links | One mechanism for everything. | Cross-language dependencies share no symbol names, so better parsing alone can't link them. |

## What this means

- Caller context is real call resolution, not similarity, so a finding can cite
  the exact caller line.
- Adding a language means adding an indexer behind the same interface. The
  prompt and review code don't change.
- A repo in several languages gets caller context for the indexed languages
  and a diff-only review for the rest, until they're added.

## Accepted in

- [#89 Add a Python symbol graph indexer to marginal/graph](https://github.com/exactml/marginal/pull/89)
- [#92 Add ADR 0003 for the two-layer code graph architecture](https://github.com/exactml/marginal/pull/92)
- [#94 Resolve a diff's changed functions to their out-of-diff callers](https://github.com/exactml/marginal/pull/94)
