---
name: gardevoir-be
description: Use when implementing or modifying the gardevoir backend — scaffolding DDD layers, repositories/DAOs, ports/adapters, services, command/result DTOs, domain errors, guardrail compilation, or DI wiring. Encodes the gardevoir backend architecture conventions and the performance constraints the request path must honour.
---

# gardevoir backend architecture (gardevoir-be)

## Overview

gardevoir = an OpenAI-compatible guardrail proxy. FastAPI **modular monolith** on a
**uv workspace**, DDD with **CQRS-lite**. Each bounded context (BC) is a workspace member
following the SAME layering. `shared_kernel` provides cross-cutting building blocks.

Design document: `docs/superpowers/specs/2026-08-12-gardevoir-design.md`. Section numbers
below (§N) refer to it. **Read the design document before changing anything on the request
path** — several structural choices there are backed by measurements and will be silently
undone by a well-intentioned refactor.

## When to use

- Adding or modifying a backend BC.
- Deciding where repositories / DAOs / ports / services / DTOs / domain errors / DI belong.
- Touching guardrail compilation or the request evaluation path.
- NOT for frontend.

## Package layout (uv workspace member, src layout)

```
backend/<bc>/
├── pyproject.toml            # [project] name="<bc>"; packages=["src/<bc>"]; deps include "shared-kernel"
├── alembic.ini  alembic/     # async, per-BC
├── src/<bc>/
│   ├── settings.py           # <Bc>Settings(BaseAppSettings)
│   ├── composition.py        # COMPOSITION ROOT: the ONLY place importing infra concretes + fastapi.Depends
│   ├── domain/
│   │   ├── models/           # PER-AGGREGATE: <aggregate>.py, enums.py
│   │   └── exception/        # PER-AGGREGATE catalog: <aggregate>_error.py → <Aggregate>Error(ErrorCatalog)
│   ├── application/
│   │   ├── service/          # <Aggregate>Service classes (deps via __init__; methods = use cases)
│   │   ├── repository/       # WRITE interfaces (Protocol), operate on DOMAIN models
│   │   ├── dao/              # READ interfaces (Protocol), return RESULT DTOs — never domain
│   │   ├── port/             # non-DB external capability interfaces (Protocol)
│   │   ├── plan/             # executable projections (see "Guardrail plan" below)
│   │   ├── command/          # input DTOs (CamelModel)
│   │   └── result/           # output DTOs (CamelModel)
│   ├── infrastructure/
│   │   ├── models/           # PER-MODEL ORM. __init__ re-exports ALL (metadata registration)
│   │   ├── mappers/          # PER-AGGREGATE domain<->ORM
│   │   ├── repository/       # SqlAlchemy<X>Repository
│   │   ├── dao/              # SqlAlchemy<X>Dao (→ result DTOs)
│   │   ├── plan/             # compiler + cached plan provider
│   │   ├── audit/            # ClickHouse sink
│   │   ├── upstream/         # httpx LLM relay
│   │   └── engine.py         # lazy @lru_cache get_engine/get_session_factory + dispose_engine()
│   └── presentation/
│       └── http/
│           ├── app.py        # create_app(), middleware/lifespan, router mounting
│           └── <resource>.py # THIN routers; import ONLY services from composition
└── tests/                    # mirror layout; TDD
```

## Single deployment — do not split the backend

**gardevoir ships as one backend service.** The control plane (guardrail
authoring, `/v1/admin/**`) and the data plane (`/v1/chat/completions`) live in the
same process, separated by route prefix and by credential scope — not by topology.

This is a decision, not an accident. Do not re-litigate it:

- **RE2 automata cannot be serialised (§11.5).** The compiler must run inside the
  process that serves requests, so the control plane cannot be moved away from the
  data plane without leaving the compiler homeless.
- **The hot path must have no network hop (§6).** Every boundary added is latency
  the design promised not to add. A guardrail that calls another service to decide
  is exactly the architecture §9 rejected — it is why AWS's ApplyGuardrail has to
  batch 1000 words at a time, and beating that trade-off is our main advantage.
- **"One container" is the product proposition.** A self-hosted gateway that needs
  five services orchestrated is a much harder thing to adopt.
- **One business domain.** Other internal repos have several bounded contexts
  because they have several domains. gardevoir has one: guardrails. Copying a
  topology without the domain multiplicity that justified it is cargo cult.

Scale horizontally with replicas, not by splitting. §6 already assumes this: each
instance polls Postgres and compiles into its own memory.

Ollama (Phase 4) and the Next.js console (Phase 5) are separate processes but not
our microservices — one is an external dependency, the other a frontend.

**Authorisation, not topology.** Admin routes are gated by the `admin` scope on the
API key; proxy routes by `proxy`. Identity, allowed guardrails, and scope all come
from the credential (§7.2) — never from a header.

Splitting becomes worth considering only when one of these is true, and none is
today: the audit dashboard outgrows serving from the gateway; the approval flow
(Phase 6) grows a state machine and notifications; the model tier needs to be ours
rather than external.

## Dependency direction (strict)

- **domain** — pure / persistence-ignorant. May import only `shared_kernel.exception`
  category bases (for the ErrorCatalog). NO SQLAlchemy / FastAPI / httpx.
- **application** — depends on domain. Owns repository(write) + dao(read) + port Protocols,
  plan types, command/result DTOs, service classes.
- **infrastructure** — implements application ports. SQLAlchemy, httpx, clickhouse-connect,
  and `re2` compilation live ONLY here.
- **presentation** — depends on application + composition. **MUST NOT import infrastructure.**
- **composition.py** — the ONLY place wiring infra concretes → services via `fastapi.Depends`.

## Reuse shared_kernel (don't reinvent)

- `config`: `BaseAppSettings` + nested `DatabaseSettings`, `ClickHouseSettings`, `LogSettings`.
- `database`: `Base` (DeclarativeBase + naming_convention), `UUIDPrimaryKeyMixin`,
  `TimestampMixin`, `create_engine` / `create_session_factory` / `build_session_dependency`.
- `exception`: `AppError` + category subclasses
  `ValidationError(422)/NotFoundError(404)/UnauthorizedError(401)/ForbiddenError(403)/ConflictError(409)`,
  `ErrorCatalog` base enum, `ErrorResponse`, `register_exception_handlers(app)`.
- `log`: `configure_logging`, `RequestContextMiddleware`, `get_request_id`, redaction.
- `api`: `CamelModel` (camelCase wire / snake_case py), `Page[T]`.

gardevoir's `shared_kernel` is a **reimplementation** of the pieces we need — it cannot
depend on any private repository. Keep it to what is actually used.

## Key patterns

1. **CQRS-lite Repository vs Dao.** Repository = write/aggregate lifecycle (`add`, `get`
   to load-for-mutation, `update`) on DOMAIN models. Dao = read/query returning RESULT DTOs
   directly — never domain objects. `get` legitimately appears on both.

2. **Single DTO at the boundary.** application owns `command` (input) + `result` (output) as
   `CamelModel`. Presentation returns the result DTO directly — no separate wire schema, no
   domain leakage.

3. **Services are classes.** `<Aggregate>Service.__init__(*, repos/daos/ports)`; methods are
   use cases. Router depends on the service (single `Depends`).

4. **Errors = ErrorCatalog enum per aggregate.** Members `NAME = (code, default_message, category)`.
   Code format `<AGGREGATE>-NNN`. Raise via `<Aggregate>Error.X.exception(...)` or `.raise_()`.
   NO class-per-error. Handler = `shared_kernel.register_exception_handlers`.

5. **Non-DB dependencies use port/adapter.** A `Protocol` port in `application/port/`, an
   adapter in `infrastructure/`, wired in `composition.py`. This covers the upstream LLM
   relay, the audit sink, and the judgement model tier. §12 requires the model tier to be
   swappable (Ollama → vLLM → Bedrock) without touching the core — the port is how.

6. **Use OOP for stateful policies and workflow units.** Prefer small classes when behavior
   has configuration, collaborators, or multiple related methods. Inject dependencies through
   `__init__`; expose a narrow method. Value objects and DTOs stay dataclasses/Pydantic.

## Guardrail plan — the executable projection

This is the one pattern that has no counterpart in an ordinary CRUD service, and the one
most likely to be broken by a refactor. **Read §6 and §11.4 before changing it.**

A `Guardrail` is a free-form DAG authored by a user. Evaluating it by walking that graph
per request was measured at **6.2 ms/request**; compiling it once at publish into a flat
instruction program and executing that was **0.62 ms/request** (§11.4). The compiled form
is therefore not an optimisation to add later — it is the design.

In CQRS-lite terms the compiled program is a **read projection** of the guardrail aggregate,
exactly like a Dao's Result DTO is a projection of a domain model. It is modelled as one:

```
domain/models/guardrail.py                    authored form; pure domain
application/plan/guardrail_plan.py            GuardrailPlan — instruction array + slot map
application/port/guardrail_plan_provider.py   Protocol: plan_for(name) -> GuardrailPlan
infrastructure/plan/compiler.py               domain model -> GuardrailPlan (once, at publish)
infrastructure/plan/cached_provider.py        in-memory cache + atomic swap
application/service/evaluation_service.py     plan_provider.plan_for(name), then execute
```

Rules that must hold:

- **`GuardrailPlan` is a slotted dataclass, NOT a `CamelModel`.** Pydantic validation must
  never run on the request path. The `CamelModel` convention applies to DTOs that cross the
  HTTP boundary; a plan never does.
- **Nothing recompiles per request.** `plan_for` is a dict lookup. A repository or provider
  implementation is free to be an in-memory cache — layering constrains dependency
  direction, not caching.
- **A request holds one plan for its whole lifetime.** Publishing swaps a reference
  atomically; a request that started on v37 finishes on v37. Mixing versions within one
  request makes the verdict incoherent and the audit record unreproducible (§6).
- **Compiled artefacts are never serialised or cached externally.** The expensive part —
  RE2 automata — cannot be pickled at all, and unpickling individual patterns re-compiles
  them (5% saving, §11.5). Each process compiles into its own memory.
- **Instruction execution stays a flat loop over an array with a slot array for outputs.**
  No per-node object graph walk, no dict-keyed variable environment.

## Mutation testing against a shared database

The suite runs against a real Postgres, so mutation runs need two guards. Both
were learned the hard way.

**1. Restore on any exit.** A killed mutation script leaves the source mutated,
and the next run measures the wrong code.

```bash
restore() { git checkout -- src/; find src -name __pycache__ -type d -print0 | xargs -0 rm -rf; }
trap restore EXIT INT TERM
```

`__pycache__` must go with it: a same-length edit restored within the same second
is byte-identical in size and mtime, so both of CPython's invalidation checks pass
and the stale `.pyc` keeps running.

**2. Never let a pytest run be killed mid-test.** A SIGKILLed pytest leaves its
Postgres backend `idle in transaction` holding locks on the test tables. Every
later run then blocks in the session fixture's `TRUNCATE`/`drop_all` — the symptom
is a *different* set of failures on each run, or a suite that hangs before the
first test, which reads like flaky tests rather than a wedged database.

Diagnose it:

```sql
SELECT pid, state, wait_event_type, xact_start, left(query, 60)
FROM pg_stat_activity WHERE datname = 'gardevoir' AND pid <> pg_backend_pid();
-- 'idle in transaction' holding a lock while others wait on TRUNCATE = wedged
SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity
WHERE datname = 'gardevoir' AND pid <> pg_backend_pid();
```

Also check for *other* mutation scripts still looping — several killed shells can
survive and run pytest concurrently against the same database, which produces the
same symptom and is easy to misread as a code defect.

**3. Count a hang as CAUGHT.** A mutation that makes the suite hang looks like
`SURVIVED` to the obvious classifier, because the killed output contains no
`failed`/`error` line. Check the exit code:

```bash
# 파이프를 쓰지 않는다. $? 는 파이프라인의 *마지막* 명령(tail)의 상태다.
out=$(timeout 300 uv run pytest -q 2>&1); rc=$?
if [ "$rc" -eq 124 ]; then echo "HANG (=CAUGHT)"
elif printf '%s' "$out" | grep -qE "[0-9]+ (failed|error)"; then echo CAUGHT
else echo SURVIVED; fi
```

`... | tail -3); rc=$?` 는 늘 0 이다 — `tail` 의 상태를 읽는다. `PIPESTATUS[0]` 도
명령 치환 안의 파이프라인에는 전파되지 않으니 쓰지 말 것. 출력을 통째로 받아서
나중에 자르는 것이 유일하게 맞는 형태다.

This misclassified a real result twice: removing `task.cancel()` from a background
task's `stop()` made every test wait forever on the poller, and both the naive
classifier *and* the pipeline-based "fix" reported the mutation as surviving.

**4. Commit before mutating, every time.** The `git checkout -- src/` that restores
a mutation also discards uncommitted source fixes. This has bitten three times in
this repo — including once *while fixing a survivor*, which silently reverted the
fix and made the next two mutations report `SKIP` because their target string was
gone.

## Determinism a single process cannot observe

Instruction order, slot numbers, and anything else derived from iterating a `set`
of strings varies **between processes** — string hashing is randomised per process.
Compiling twice in one test always agrees, so a test written that way cannot fail.

§6 compiles per worker, so an order that varies per worker changes where early exit
lands, which changes the `checks_fired` recorded for the same request. Pin it by
compiling in subprocesses with different `PYTHONHASHSEED` and comparing the shape —
and assert the probe actually produced a shape, or the comparison passes on two
empty strings.

Prefer removing the dependency over stabilising it: iterate a declared order (a
tuple, or a dict built from one) rather than sorting a set into place.

## Alembic autogenerate and the test fixtures

**`alembic revision --autogenerate` will produce an empty migration if the test
suite has run against the same database.** The session fixture calls
`Base.metadata.create_all`, so the tables already match the models and autogenerate
sees no diff. This has bitten twice.

Reset the database to the *migrated* state first:

```bash
docker exec gardevoir-postgres-1 psql -U gardevoir -q \
  -c 'DROP TABLE IF EXISTS api_keys CASCADE; DROP TABLE IF EXISTS alembic_version CASCADE;'
uv run alembic upgrade head          # applies the existing chain only
uv run alembic revision --autogenerate -m "..."
```

Then verify the generated file is not `pass`, apply it, and check the
upgrade/downgrade round trip.

**A new ORM model must also be re-exported from `infrastructure/models/__init__.py`**
— `alembic/env.py` imports only the package, so a model missing from that file is
absent from `Base.metadata` and silently absent from the migration.

## Request-path constraints (measured, not aspirational)

Total gateway overhead is 0.63 ms/request against a 300–2000 ms upstream call (§11.8).
The following are load-bearing:

- **No DB and no network on the request path** (§6). Key lookup is the only DB-backed read
  and is covered by a TTL in-memory cache. The cache key is the sha256 of the raw key, never
  the raw key itself.
- **`orjson` only** for JSON. `json` is 2.3× slower and the streaming path parses per chunk (§11.7).
- **`re2` only** for regex — never `re`. `(a+)+$` against 26 characters takes 8.9 s in
  Python `re` and 0.034 ms in `google-re2` (§11.1). A policy author's typo would otherwise
  become a denial-of-service switch. Use `re2.Set` to match many patterns in one pass —
  510× faster than looping (§11.2).
- **Never call a synchronous client from the event loop.** `clickhouse-connect` is sync;
  a 100-row insert blocks every in-flight request for 5–20 ms. Wrap it in
  `asyncio.to_thread`.
- **Audit writes never block the response** (§10). Queue, then batch in the background.

## Wire contract

`contract.py` in the gateway BC holds header names, `Action`/`Mode`, and the `gardevoir`
extension object. **Keep it minimal — §7 treats the protocol as the part that is hard to
change and configuration as the part that is easy.** Adding a field here can break deployed
applications; adding a guardrail check cannot.

- `finish_reason` takes **standard values only**: `stop` / `length` / `tool_calls` /
  `content_filter` / `function_call`. A custom value fails the OpenAI SDK's `Literal`
  validation and breaks every client, including ones that never integrated with us (§11.9).
- All gardevoir information goes in the top-level `gardevoir` object, which the SDK tolerates
  and exposes (§11.9). This is pinned by a regression test — do not delete it when bumping
  the SDK.
- Blocking must also write a human-readable reason into `content`. Many applications never
  read `finish_reason` (§7.3).
- The contract version is the URL prefix `/v1`. There is no protocol version header.

## Errors on the proxy path

Follow the Azure OpenAI convention the design adopted (§7.3):

```
input blocked      HTTP 400 + error.code = "content_filter"
output blocked     HTTP 200 + finish_reason = "content_filter"
tool_call blocked  HTTP 200 + finish_reason = "content_filter"
```

## Conventions

- UUIDv7 PKs for mutable state; **ULID for audit event ids** (time-ordered, and audit rows
  are sorted by time in ClickHouse).
- String-backed `StrEnum` columns.
- tz-aware UTC. **ClickHouse `DateTime64(3)` takes `datetime` objects only** — passing unix
  seconds as an int is read as milliseconds and silently stores 1970 dates with no error (§11.10).
- Engine lazy, disposed in lifespan.
- Postgres migrations via Alembic; the ClickHouse audit schema via numbered `.sql` files
  (one append-only table needs no migration tool).

## Not used here (differs from other internal repos)

| Absent | Why |
|---|---|
| Kafka / outbox / CDC / domain events | Nothing publishes events (§12) |
| Redis | Taint tracking is stateless — the `messages` array carries the full history (§7.4). Approvals are low-volume and live in Postgres |
| JWT / `Principal` / header-trust auth | Callers authenticate with a gardevoir-issued API key; app identity comes from the credential, never a header (§7.2) |
| Celery | No background fan-out; asyncio tasks suffice |
| Object storage | ClickHouse `TTL` + partition drop covers retention (§10) |
| Prometheus | The audit log already records per-request latency and verdicts; a second metrics path would split the source of truth (§12) |

## Scaffolding a new BC (order)

1. Workspace member `backend/<bc>/`; add to `backend/pyproject.toml` members; `uv sync`.
2. `domain/models/` aggregates + enums; `domain/exception/<aggregate>_error.py` catalog.
3. `application/{command,result,repository,dao,port,service}`.
4. `infrastructure/{models,mappers,repository,dao,engine}` + alembic.
5. `presentation/http` routers + `app.py`; `composition.py` wiring.
6. TDD per layer; run `uv run pytest` from `backend/<bc>` (not from `backend/` — it
   cross-collects sibling packages).

## Common mistakes (vs naive defaults)

| Naive default | gardevoir convention |
|---|---|
| repository interface in `domain/` | repository(write) + dao(read) **Protocols in `application/`**; domain stays pure |
| DAO returns domain entities | DAO returns application **result DTOs** |
| three DTO tiers | **single** application-owned `CamelModel` at the boundary |
| use cases as loose functions; a class per error | **service classes**; one `ErrorCatalog` enum per aggregate |
| one `models.py` / one `mappers.py` | per-model files under `infrastructure/models/`, per-aggregate under `infrastructure/mappers/` |
| DI in presentation | DI in `composition.py`; presentation never imports infrastructure |
| per-BC exception handler | reuse `shared_kernel.register_exception_handlers` |
| `GuardrailPlan` as a `CamelModel` | slotted dataclass — Pydantic must not run on the request path |
| walking the guardrail DAG per request | compile at publish, execute a flat instruction array (§11.4) |
| `import re` | `import re2` — always |
| `json.loads` | `orjson.loads` |
| calling `clickhouse_connect` insert directly in async code | `await asyncio.to_thread(...)` |
| serialising compiled plans to object storage | recompile in-process; RE2 automata do not serialise (§11.5) |
