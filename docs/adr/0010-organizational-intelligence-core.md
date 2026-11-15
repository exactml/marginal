# ADR 0010: Organizational Intelligence Core: module boundary, stack, and packaging

**Status:** Accepted · recorded 2026-10-30

## Context

Today marginal is a stateless CLI and GitHub Action. It has no server, no
database and no users, and `marginal-ui/` is only reserved. The Organizational
Intelligence Core (OIC) is a new layer that keeps an evidence-backed, versioned
model of what an engineering org knows: claims, evidence, entities, scopes and
time. Coding agents (Claude Code first) investigate questions. marginal owns the
durable state, the validation and the API. The reviewer becomes one consumer of
that API.

OIC adds a server, a database, background jobs, a UI and a login to a project
that has none of them. Every later OIC issue depends on how these are chosen,
so this ADR fixes them before any code is written.

## Decision

### 1. Module boundary

OIC lives in `marginal/oic/`, one package per layer:

```
marginal/oic/
  domain/    claims, evidence, entities, scopes, status transitions (pydantic only)
  services/  investigations, proposal validation, knowledge queries
  agents/    AgentProvider interface, FakeProvider, one adapter per runtime
  store/     SQLAlchemy tables, Alembic migrations, repositories
  jobs/      the database-backed job worker
  api/       FastAPI routers
marginal/server/   the one web app: mounts OIC routers (later the review-audit
                   routers) and serves the built UI
marginal-ui/       the React app's source
```

Pydantic models go in each package's `schema.py`, as elsewhere in marginal.
Three import rules, each enforced by a test:

- `marginal/review/`, `marginal/graph/` and `marginal/cli/review` never import
  `marginal.oic`. The reviewer only reads OIC knowledge over HTTP.
- `marginal/oic/domain/` and `marginal/oic/services/` never import a provider
  SDK or `marginal.oic.agents` adapters.
- `marginal/oic/domain/` never imports `marginal.oic.store`.

| Option | Pros | Cons |
|---|---|---|
| **`marginal/oic/` in this repo, layered** (chosen) | One release and one CI. Domain code can be tested without a database or an agent. | Boundaries hold only while the import tests do. |
| A separate repo or service | Hard boundary. | Two release trains and a cross-repo API before the API even exists. |
| OIC code inside `marginal/review/` | Short paths. | The reviewer starts depending on OIC internals, which is what the API is meant to prevent. |

### 2. Packaging

OIC ships as an optional extra:

```toml
[project.optional-dependencies]
oic = ["fastapi", "uvicorn", "sqlalchemy>=2", "alembic", "claude-agent-sdk"]
```

`pip install marginal-review`, which marginal-action runs on every PR, does not
change. `marginal serve` and the other OIC commands import the extra lazily. If
it is missing, they exit with `pip install 'marginal-review[oic]'`.

| Option | Pros | Cons |
|---|---|---|
| **Optional `oic` extra** (chosen) | Every PR review stays as light and fast to install as it is now. | Two install profiles to test. |
| Server deps in the base install | One profile. | Every Action run installs a web stack it never uses. |
| A second PyPI package | Fully separate. | Versioning across two packages for a module that still changes weekly. |

### 3. Storage

**SQLite first, in WAL mode, replicated to S3 by Litestream.** Tables and
migrations are SQLAlchemy 2 and Alembic, with no SQLite-only SQL, so Postgres
remains a deployment option on the same schema. No graph database: claims,
evidence, entities and their typed links are ordinary tables with indexes.
Claim history is append-only, so a new version is a new row and older rows are
never updated in place.

On a replaced host, `litestream restore` rebuilds the database from S3 before
the server starts. Litestream replicates asynchronously, about once a second, so
the recovery point is the last few seconds: writes committed in that window can
be lost with the host. A job whose result was lost restores as `queued` or as
an expired `running` job, and reruns. Its idempotency key protects only commits
that reached S3, which is acceptable for v1 because a rerun repeats an agent
run, not a human decision. Anything older than that window is never only on the
EC2 disk.

CI runs the store tests on SQLite. A Postgres CI job is added together with the
first Postgres deployment, not before.

| Option | Pros | Cons |
|---|---|---|
| **SQLite + Litestream** (chosen) | No database server to run or pay for. Tests and local dev use the same engine as production. Continuous off-host backup. | One writer host. Litestream is one more process to supervise. |
| Postgres (RDS) from day one | Managed backups, many writers. | A server to provision before the first investigation runs. Dev and prod use different engines. |
| Postgres everywhere | One SQL dialect. | Contributors need Postgres just to run the tests. |
| A graph database | Graph queries built in. | Nothing we need yet is a graph query that SQL can't answer, and it adds a second store to keep consistent. |

### 4. Jobs

Investigations run as rows in a `jobs` table: status, attempts, `run_after`,
`lease_until` and a unique `idempotency_key`. A worker (`marginal oic worker`)
claims a job with one conditional update and owns it only if exactly one row
changed:

```sql
UPDATE jobs SET status = 'running', worker = ?, lease_until = ?, attempts = attempts + 1
WHERE id = ? AND attempts < max_attempts
  AND ((status = 'queued' AND run_after <= now)
       OR (status = 'running' AND lease_until < now))
```

The update moves the job out of `queued`, so a second worker's identical update
changes no row. Only a `running` job whose lease has expired can be taken over;
finished and waiting jobs never match. The statement is atomic on SQLite and on
Postgres alike, so two workers can't claim the same job on either engine.

While an agent run is active, the worker renews its lease on a heartbeat well
inside the lease length, so a long run is never reclaimed while it is still
alive. The renewal is conditional too: `UPDATE jobs SET lease_until = ? WHERE
id = ? AND worker = ? AND status = 'running'`. If it changes no row, another
worker has taken the job over, and this worker stops its agent run instead of
taking the lease back.

Only a dead worker's lease expires, and then the job is taken over by the claim
above. When its attempts are used up, the claim can no longer match, so each
poll also fails such jobs: `UPDATE jobs SET status = 'failed' WHERE status =
'running' AND lease_until < now AND attempts >= max_attempts`. Their
investigations move to `failed` with the reason, so a job can't stay `running`
forever. A live worker whose agent run raises applies the same rule: it puts the
job back in `queued` with a later `run_after` only while `attempts <
max_attempts`, and otherwise marks it `failed`. So no job waits in `queued`
with no attempts left. An agent that asks a person a question doesn't hold a lease while it
waits: the run checkpoints and ends, the investigation moves to
`waiting_for_user`, and the answer queues a new job that resumes from the
checkpoint. Commits of knowledge carry the job's idempotency key, so a retried
job can't commit the same proposal twice. A setting caps how many agent runs
happen at once.

| Option | Pros | Cons |
|---|---|---|
| **Job table in the same database** (chosen) | A job and its results commit in one transaction. Nothing extra to deploy. | Polling. Throughput fits tens of investigations, not thousands. |
| Redis + RQ/Celery | Mature queues. | A second store whose state can disagree with the database. |
| SQS | Managed. | Ties local dev and tests to AWS. |

### 5. Web stack

One FastAPI app in `marginal/server/` serves the OIC API and the UI. The
review-audit UI (#167, #168) joins the same app instead of starting a second
one. The UI is a **React + Vite single-page app** in `marginal-ui/`. Its build
output is copied into `marginal/server/static/` during the release build and
ships inside the wheel, so installing doesn't need Node. Contributors who only
change Python don't need Node either. UI work runs the Vite dev server against
a local `marginal serve`. Live investigation progress reaches the UI as
server-sent events.

| Option | Pros | Cons |
|---|---|---|
| **React SPA served by FastAPI** (chosen) | Suited to the knowledge explorer, the claim history and the proposal review screens. One origin, so no CORS. | A Node toolchain in CI and the release build. |
| Server-rendered templates + htmx | No Node at all. | Interactive explorer views get harder as they grow. |
| A separate UI server | Independent deploys. | Two apps to run and secure for one product. |

### 6. Agent runtimes vs `marginal/providers`

`marginal/providers/` stays as it is: one chat-completion call per review that
returns JSON. Agent runtimes (Claude Code through the Claude Agent SDK first,
Codex later) are long-running sessions with tools, questions to a person, and
resumption. They get their own `AgentProvider` interface in
`marginal/oic/agents/`, with a `FakeProvider` for tests. Provider session IDs
are kept only in an agent run's runtime metadata and never reach domain objects
or API responses.

| Option | Pros | Cons |
|---|---|---|
| **Separate interface in OIC** (chosen) | Each interface fits its job. Review code doesn't change. | Two "provider" ideas in one repo, so their names must stay distinct. |
| Extend `marginal/providers` | One abstraction. | Forces session, tool and resume concepts onto a one-shot review call. |

### 7. Auth for v1

There is one organization and one trust domain. The host is the trust
boundary: it runs only the four processes listed below, and the auth proxy is
its only listener reachable from outside.

- **Every request**: the proxy drops any user header the client sent, on every
  request, before anything else. The server listens only on localhost, so a
  user header can come only from the proxy's own login.
- **People** sign in through the auth proxy, for example oauth2-proxy with
  GitHub or Google, which then sets the user header.
- **Machines**, including the reviewer on a GitHub-hosted runner, send
  `Authorization: Bearer <token>` to the proxy's public address. The proxy
  passes a request that carries a Bearer token through to the server without a
  login redirect. The server rejects any request whose Bearer token is invalid,
  revoked or unknown, and on a request with a token it never reads the user
  header. Tokens are created with `marginal oic token create`, stored only as
  hashes, and can be revoked.
- No request is anonymous: the server rejects a request that has neither a
  valid token nor a user header. Per-user permissions come later.

| Option | Pros | Cons |
|---|---|---|
| **Auth proxy for people, API tokens for machines** (chosen) | marginal writes no login, session or cookie code. Meets #168's no-anonymous-access requirement. | One more process on the host. The proxy must be the only way in. |
| API tokens only | Simplest. | Pasting a token into a browser is not a login. |
| Built-in OIDC | Nothing extra to deploy. | marginal owns session security. |

## What this means

- Each later OIC issue can cite this ADR for its stack, and it changes only by
  a new ADR.
- marginal-action users notice nothing: the base install and the review command
  are unchanged.
- A single EC2 host runs four processes: the auth proxy, `marginal serve`,
  `marginal oic worker` and Litestream.
- The first new contributor setup step is `pip install -e '.[dev,oic]'`. Node is
  needed only for `marginal-ui/` work.

## Accepted in

- [#219 Design: Organizational Intelligence Core module boundary, stack, and packaging](https://github.com/exactml/marginal/issues/219)
