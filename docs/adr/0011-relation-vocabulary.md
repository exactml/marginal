# ADR 0011: Relation vocabulary for organizational knowledge, proposed by pull requests

**Status:** Proposed · recorded 2026-11-21

## Context

The OIC domain model (ADR 0010) types three kinds of links:

| Level | Example | Where it is typed |
|---|---|---|
| Claim → claim | claim A `supersedes` claim B | `ClaimLinkType` |
| Evidence → claim | PR #88 `supports` claim A | `EvidenceRelation` |
| Entity → entity | `checkout dependsOn billing` | **not typed yet** |

Entity-to-entity relations are what the knowledge is about: what depends on
what, who owns what, which decision applies where. Without a fixed vocabulary,
every extractor and every agent invents its own wording ("uses", "needs",
"relies on"), duplicates go undetected, and nothing can be inferred from a chain
of relations.

The same vocabulary also decides where knowledge can come from. A merged pull
request is dated, reviewed, attributable evidence that something in the
organization changed, and marginal already reviews every pull request. If a
relation can be read from a pull request, marginal can propose it without an
agent and without an extra model call.

## Decision

### 1. Relations are a closed, typed vocabulary

Every entity-to-entity claim uses one predicate from the catalog below. A
predicate has a domain and range (which entity types it connects), an inverse,
and optional rules:

- **T** (transitive): A→B and B→C imply A→C.
- **F** (functional): at most one value at a time. A second, different value is
  a contradiction, not an addition.
- **⊑ p** (sub-relation of p): every fact of this relation is also a fact of p.

Entity types form a hierarchy. `component` is the parent of `module`, `class`,
`repository`, `system`, `library`, `release`, `service`, `task` and `dataset`, so a
relation declared on `component` accepts any of them. This is what lets a
sub-relation such as `installs` (repository → release) also be a `dependsOn`
(component → component) fact without failing type checks.

Names follow the Backstage catalog's well-known relations where one exists
(`ownedBy`, `dependsOn`, `partOf`, `memberOf`), so the vocabulary is familiar
and maps onto existing catalogs.

Relations need no time variants. `formerlyOwnedBy` is not a relation: the old
`ownedBy` claim gets a `valid_until`, using the two timelines already on every
claim.

### 2. Core relations

These are the relations the first version supports. Each one can be proposed
from a pull request alone, and together they answer three questions: *what is
affected if this changes*, *why is this like this*, and *who should review this*.

| Relation (inverse) | From → To | Rules | Evidence in a PR |
|---|---|---|---|
| `partOf` (`hasPart`) | component → component (e.g. module → repository → system) | T | file tree |
| `inherits` (`inheritedBy`) | class → class | T, ⊑ `dependsOn` | source |
| `dependsOn` (`dependencyOf`) | component → component | T | manifests, imports |
| `installs` (`installedBy`) | repository → release | ⊑ `dependsOn` | requirements and lock files |
| `releaseOf` (`hasRelease`) | release → library | F | release PR, tag |
| `schedules` (`scheduledBy`) | workflow → task | | workflow definition |
| `ownedBy` (`ownerOf`) | component → team | | CODEOWNERS |
| `decisionAbout` | decision → component | | maintainer reply to a finding, review |
| `constrains` (`constrainedBy`) | rule → component | | test name, review |

The first seven are the **structural layer**: what the code is made of. The
last two are the **business layer**: what the organization requires and why,
which is what nobody can read off the code later. `rule` and `decision` are
entity types of their own, named by their statement, for example
`rule: discount never exceeds 50 percent`.

Which files a pull request changed is not a relation. Git already records it,
and storing it would add one claim per directory per pull request, burying the
claims that say something about the organization. Staleness reads a merged
pull request's changed files as an event when it happens instead.

`ownedBy` is not functional: a CODEOWNERS line often names several teams, and
each becomes its own claim. A change of owner shows up as a CODEOWNERS change,
which closes the old claim with `valid_until`.

Example: from `checkout dependsOn billing` and
`billing installs ledger-client@2.1`, the rules give
`checkout dependsOn ledger-client@2.1`, a component → component fact because a
release is a component. A change released as `ledger-client@2.1` is reported
as affecting `checkout`, with both claims as the evidence chain. To reach the
library itself, follow `releaseOf` from the release:
`checkout → ledger-client@2.1 → ledger-client`.

### 3. Full catalog

Relations outside the core are named now so that extractors and agents do not
invent synonyms. Each is enabled when a question needs it and a source for its
evidence exists. "PR" means a pull request alone is enough evidence.

**Code structure**

| Relation (inverse) | From → To | Rules | Evidence |
|---|---|---|---|
| `defines` (`definedIn`) | module → symbol | F on inverse | PR |
| `imports` (`importedBy`) | module → module or library | | PR |
| `calls` (`calledBy`) | symbol → symbol | | PR (code graph) |
| `implements` (`implementedBy`) | class → interface | | PR |
| `tests` (`testedBy`) | test → symbol or module | | PR |
| `generates` (`generatedBy`) | tool → file | | PR, partly |

**Dependencies and releases**

| Relation (inverse) | From → To | Rules | Evidence |
|---|---|---|---|
| `pins` (`pinnedBy`) | repository → version range | | PR |
| `builtFrom` (`builds`) | artifact → commit | F | CI |
| `configures` (`configuredBy`) | config key → component | | PR |

**Runtime and data**

| Relation (inverse) | From → To | Rules | Evidence |
|---|---|---|---|
| `deployedTo` (`hosts`) | service → environment | | deploy logs |
| `providesApi` (`apiProvidedBy`) | service → API | | PR, partly |
| `consumesApi` (`apiConsumedBy`) | service → API | | PR, partly |
| `readsFrom` (`readBy`) | task → dataset | | PR, lineage |
| `writesTo` (`writtenBy`) | task → dataset | | PR, lineage |
| `upstreamOf` (`downstreamOf`) | dataset → dataset | T | lineage |
| `triggers` (`triggeredBy`) | event or job → job | | PR |

**People and organization**

| Relation (inverse) | From → To | Rules | Evidence |
|---|---|---|---|
| `memberOf` (`hasMember`) | person → team | | directory |
| `reportsTo` (`manages`) | person → person | F | directory |
| `maintains` (`maintainedBy`) | person → component | | PR history |
| `onCallFor` (`onCall`) | person or team → service | | on-call tool |
| `expertIn` (`hasExpert`) | person → component or concept | | PR and review history |
| `authored`, `reviewed`, `approved` | person → pull request | | PR |

**Work and change**

| Relation (inverse) | From → To | Rules | Evidence |
|---|---|---|---|
| `resolves` (`resolvedBy`) | pull request → issue | | PR |
| `reverts` (`revertedBy`) | pull request → pull request | F | PR |
| `introducedIn` (`introduced`) | defect → commit or pull request | | bisect, incident |
| `blocks` (`blockedBy`) | issue → issue | | issue tracker |
| `releasedIn` (`releaseContains`) | pull request → release | | PR, tags; several values when backported |

**Decisions and rules**

| Relation (inverse) | From → To | Rules | Evidence |
|---|---|---|---|
| `decidedBy` (`decided`) | decision → person or team | | PR, ADR |
| `exceptionTo` (`hasException`) | decision → rule | | maintainer reply |
| `deprecates` (`deprecatedBy`) | component → component | | PR |
| `replaces` (`replacedBy`) | component → component | F | PR |
| `documentedIn` (`documents`) | component → document | | PR, partly |

**Quality and operations**

| Relation (inverse) | From → To | Rules | Evidence |
|---|---|---|---|
| `affects` (`affectedBy`) | incident → service | | incident tool |
| `causedBy` (`caused`) | incident → change | | postmortem |
| `flakyIn` (`hasFlakyTest`) | test → environment | | CI history |
| `monitors` (`monitoredBy`) | monitor → service | | monitoring config |

### 4. Organizations extend the vocabulary; they do not change the core

An organization adds its own entity types and relations. A relation that
refines a core one is declared its sub-relation, so the core rules still apply
to it; a relation with no core counterpart states its own domain, range and
rules. Example: a team that runs one pipeline per customer adds `enablesTask`
(pipeline → task, ⊑ `dependsOn`) and a new relation `servesCustomer`
(pipeline → customer, F). Impact questions then reach customers through
`dependsOn` and `servesCustomer` with no change to marginal. Extensions live in the organization's own configuration,
not in this repository.

### 5. Each merged pull request posts one proposal; the team decides later

When a pull request merges, marginal posts **one** comment on it listing the
candidate claims the pull request evidences. An open or closed-unmerged pull
request gets nothing, and a pull request with no candidates gets no comment.
A rerun edits the comment instead of posting a second.

```
Merged. Proposed for the knowledge graph:
| id     | subject                                  | relation   | object   | source                    |
| e1815c | shop                                     | installs   | requests@2.32.3 | pyproject.toml:6   |
| 7c1a90 | rule: discount never exceeds 50 percent  | constrains | pricing  | tests/test_pricing.py:14  |
| 2be4f1 | decision: zero-stock items stay listed   | decisionAbout | shop/stock.py | shop/stock.py:12 |
These are candidates, not knowledge yet: the team reviews them before any goes into the graph.
```

A merge approves code, not the claims read from it. So a candidate is only
**proposed**. Which candidates become knowledge, and so enter the store and the
graph, is decided in a separate review step outside the pull request, where the
team accepts, edits or rejects each one. Until then nothing is queried as
knowledge.

Each claim's id is a short hash of its subject, relation and object, so the
review step can refer to a candidate and spot one proposed again by a later
pull request.

**Where candidates come from, with no extra model call:**

| Source | Layer | How it is checked |
|---|---|---|
| Manifests, CODEOWNERS, version bumps | structural | read from the diff; what the removed side already said is not new |
| Added tests whose name states a rule (`never`, `must`, `at most`, …) | business | the test name is the evidence |
| A maintainer's reply that explains a marginal finding away ("intentional, because …") | business | the reply is the evidence |
| Rules and decisions the review model reports, at most five per review, in the call the review already makes | business | its quote must be found in the diff when the review runs, and still be in the merged diff |

Merge time is not always when something becomes true. A library fix merged on
one date reaches a consumer only when that consumer's pull request bumps the
version. `valid_from` follows the pull request that carries the evidence, so
the library merge and each consumer's install are separate claims.

## Options considered

| Option | For | Against |
|---|---|---|
| **Closed vocabulary with rules (chosen)** | Duplicates and contradictions are detectable; chains can be inferred; extractors agree on wording. | Adding a relation needs a change here. |
| Free-text predicates | Nothing to maintain. | "uses", "needs" and "relies on" become three facts; no inference. |
| Adopt a full OWL ontology and a reasoner now | Standard semantics. | A new dependency and a graph store before one question has been answered; ADR 0010 chose no graph database. |
| Agents investigate, PRs not used | Covers knowledge PRs never contain. | Costly per question; ignores the reviewed evidence marginal already sees on every PR. |

## What this means

- The core relations become an enum next to `ClaimLinkType`, and proposal
  validation rejects a predicate outside it or one that connects the wrong
  entity types.
- The team review step, and storing what it accepts, are separate changes. A
  proposal comment is the hand-off to that step, not a write to the store.
- Knowledge that no pull request carries (directory data, incidents, on-call)
  waits for its own sources or for agent investigations.
- The core list changes only by updating this ADR. Before it is accepted, the
  core should be checked against a set of real questions: keep a relation if
  at least two questions need it and a pull request can evidence it.
