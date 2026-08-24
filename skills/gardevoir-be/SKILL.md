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

## There are no tests right now — verify by running it

**`backend/gateway/tests/` was deleted** (kept in git at `ae52c5b`) while the bounded
contexts were being carved out. Tests will come back, but only after the structure settles
and only against a stated bar (see "When tests come back" at the end). **Do not restore the
old suite wholesale and do not add tests opportunistically** — that is what produced 906
tests, a large share of which asserted on code shape and broke on every move.

Until then, verification is:

```bash
# 1. 모든 모듈이 임포트되는가 — 경로가 깨졌으면 여기서 잡힌다
uv run python -c "
import importlib, pathlib
root = pathlib.Path('src/gateway')
for p in sorted(root.rglob('*.py')):
    m = ('gateway.' + str(p.relative_to(root))[:-3].replace('/', '.')).removesuffix('.__init__')
    importlib.import_module(m)
print('imports ok')"

# 2. ruff
uv run ruff format . && uv run ruff check .

# 3. 실제 기동 — 이것이 지금의 주된 검증이다
uv run uvicorn --factory gateway.app:create_app --port 21011
```

Then exercise the real path: start with `GARDEVOIR_JWT_SECRET` and `GARDEVOIR_ROOT_EMAIL` /
`GARDEVOIR_ROOT_PASSWORD` set, `POST /v1/auth/login`, author a guardrail via `/v1/guardrails`,
publish it, send a request that should be blocked, and read the ClickHouse audit row. Running it end to end catches a class of defect the old suite never
did — see "The response/cleanup boundary" below.

## When to use

- Adding or modifying a backend BC.
- Deciding where repositories / DAOs / ports / services / DTOs / domain errors / DI belong.
- Touching guardrail compilation or the request evaluation path.
- NOT for frontend.

## Package layout

`backend/` is a uv workspace. `shared_kernel` is a library; **`gateway` is the only
service**, and the bounded contexts live *inside* it as packages — they share one process
(see "Single deployment" below), so they are not workspace members.

```
backend/gateway/src/gateway/
├── app.py              COMPOSITION ROOT — lifespan builds the process-lifetime object graph
│                       (engine, key cache, audit sink, upstream, plan registry) into app.state;
│                       also middleware, exception handlers, and router mounting, which is
│                       where API_PREFIX ("/v1") lives — routers declare only their sub-path
├── settings.py  health.py
│
├── identity/           ApiKey — 크레덴셜과 스코프 (§7.2). 두 플레인의 상류
│   ├── domain/
│   │   ├── models/         api_key.py
│   │   └── exceptions/     api_key_error.py
│   ├── application/
│   │   ├── service/       auth_service.py · user_service.py
│   │   ├── repository/    user_repository.py · refresh_session_repository.py (write)
│   │   ├── dao/           user_dao.py (read)
│   │   ├── command/       user_command.py    ├── result/  user_result.py
│   │   └── port/          access_token_codec.py (Protocol + AccessTokenClaims)
│   ├── composition.py  provide_* + require_role(Role) — providers only, no aliases
│   ├── presentation/   auth_router.py → /v1/auth/*, user_router.py → /v1/users/*
│   └── infrastructure/ sqlalchemy repos · dao · ORM model · jwt_access_token_codec.py
│
├── guardrail/          CORE DOMAIN. 세 관심사가 domain/ 의 집합체를 공유한다
│   ├── domain/
│   │   ├── models/         guardrail.py (Guardrail·Node·Edge·VerdictAction·Decision) · mode.py
│   │   └── exceptions/     guardrail_error.py
│   ├── definition/     정의·초안·발행·버전 — 컨트롤 플레인 (§5)
│   │   ├── application/     service/ · repository/ · dao/ · command/ · result/
│   │   ├── infrastructure/  guardrail_model · guardrail_mapper · repository · dao
│   │   └── presentation/    guardrail_router.py  → /v1/guardrails
│   ├── plan/           컴파일 → 명령·슬롯 → 실행 (§6, §11.4)
│   │   ├── domain/          models/execution_plan.py (Program·instructions·slots)
│   │   │                    executor.py — 도메인 서비스라 층 루트에 둔다
│   │   ├── application/     service/registry.py · port/guardrail_source.py
│   │   │                    compiler.py — 순수 함수라 층 루트
│   │   └── infrastructure/  guardrail_source.py (발행본 읽기)
│   ├── inspection/     체크포인트 ①②③④ → 판정 (§3, §4)
│   │   └── application/     service/inspector.py
│   │                        outcome · provenance · text — 값 타입·순수 함수라 층 루트
│   └── composition.py  request-scoped provide_* (별칭 없음)
│
├── proxy/              LLM 쿼리 입출력 — 데이터 플레인 (§7, §9)
│   ├── application/    service/proxy_service.py · port/llm_upstream.py · streaming/
│   ├── contract.py     §7 wire contract: headers · extension · Action · to_wire_action
│   ├── infrastructure/ httpx_upstream.py
│   ├── composition.py  request-scoped provide_* (별칭 없음)
│   └── presentation/   chat_router.py  → /v1/chat/completions
│
└── audit/              AuditEvent (§10). 저장소가 다르다 — ClickHouse
    ├── application/    port/audit_sink.py · audit_event.py (값 타입이라 층 루트)
    └── infrastructure/ clickhouse_sink.py · schema.py
```

There is **no `infrastructure/` at the gateway root.** `infrastructure` means one thing —
adapters implementing a context's ports — and a root directory of the same name holding
process resources made the word ambiguous. The engine went to `shared_kernel.database` (it
has no gateway knowledge), and `orm.py` is gone — `alembic/env.py` walks `**/infrastructure/`
instead of trusting a hand-maintained list (see below).

### `application/` is split by role, and only by role

`service/` · `repository/` (write Protocols) · `dao/` (read Protocols) · `command/` · `result/`
(the boundary `CamelModel`s) · `port/` (every other external-capability Protocol). The test for
`service/` is a class that takes collaborators through `__init__` and exposes operations —
`PlanRegistry` and `Inspector` pass it, so they live there despite not being named `*Service`.

**Anything that is none of those six sits at the layer root** — `compiler.py` (a pure function),
`outcome.py`/`audit_event.py` (internal value types, not wire DTOs). Two files that briefly sat
there did not belong at all, and the layer root is where that became visible:

- `access_token.py` held a class doing HS256 with PyJWT — `import jwt` was the **only external
  driver anywhere in an application layer**, and it was the one holding a secret. Split into
  `application/port/access_token_codec.py` (Protocol + `AccessTokenClaims`) and
  `infrastructure/jwt_access_token_codec.py`, matching `LlmUpstream`/`HttpxUpstream`. The port
  is not there to swap the algorithm — §12 nails HS256 down — it is there so the driver stays out.
- `bearer.py` parsed the `Authorization` header, which is transport format, not an application
  concern. Its one caller was `current_claims` in `composition.py`, i.e. framework glue at the
  edge, so the four lines went inline there and the file is gone.

Do not stretch a role directory to cover a file that does not fit; `plan/domain/`
already does the same with `executor.py`. A misfiled file is worse than one at the root, because
the directory name then lies about what is in it.

**Each context has only the layers it needs.** `inspection` is pure logic, so it has no
infrastructure; `audit` has no domain aggregate beyond its event. Do not create empty
directories to make the contexts look symmetric.

### Why the boundaries fall here

- **guardrail is the core domain, so it is the big one** (2,713 of 5,588 lines). The other
  three are supporting. A core domain that is smaller than its supporting contexts is the
  signal something is misplaced.
- **`plan` is separate because the model and the storage both change.** `Guardrail`
  (nodes·edges, Postgres `jsonb`) → `Program` (instructions·slots, **process memory only**).
  §11.5: compiled artefacts cannot be serialised, so the plan's "storage" is the process.
- **`audit` is separate because of storage.** §12: the audit path never touches SQLAlchemy.
- **`identity` is upstream of both planes** (§7.2) — authorisation comes from the credential.
- **`contract.py` stays at the root.** It is the process-wide wire contract, not any one
  context's property; putting it in a context would make the other contexts depend on that
  context just to name a verdict.

## Single deployment — do not split the backend

**gardevoir ships as one backend service.** The control plane (guardrail
authoring, `/v1/guardrails` and `/v1/users`) and the data plane (`/v1/chat/completions`) live in the
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

**Authorisation, not topology — and not the URL either.** There is no `/admin/**` prefix. A
route names a resource; who may call it is a property of the caller, so it goes in a dependency:
`Depends(require_role(Role.ADMIN))` on the routes that need it. `GET /v1/users` (admin) and
`GET /v1/users/me` (self) are the same resource tree with different permissions, and that reads
correctly. Everything still comes from the credential (§7.2) — never from a header.

The guard must be a **dependency**, never a check inside the handler body: FastAPI resolves
sub-dependencies before validating the endpoint's own params, so a dependency that raises gives
401/403 while a body check would let an unauthorised caller read the schema off a 422. Verified
over HTTP — `POST /v1/users` with no token and an empty body returns 401.

The prefix used to double as an operational handle ("block `/v1/admin/*` at the ingress"), but
that mitigation existed *because* the admin surface had no human authentication. It has one now:
`/v1/auth/login` issues an access token carrying the role.

Splitting becomes worth considering only when one of these is true, and none is
today: the audit dashboard outgrows serving from the gateway; the approval flow
(Phase 6) grows a state machine and notifications; the model tier needs to be ours
rather than external.

## Dependency direction (strict)

- **domain** — pure / persistence-ignorant. May import only `shared_kernel.exception`
  category bases (for the ErrorCatalog). NO SQLAlchemy / FastAPI / httpx.
  Split into `models/` (aggregates, value objects, enums) and `exceptions/` (one
  `ErrorCatalog` per aggregate). Anything that is neither — a domain service such as
  `plan/domain/executor.py` — sits at the layer root rather than being forced into one.
- **application** — depends on domain. Owns repository(write) + dao(read) + port Protocols,
  plan types, command/result DTOs, service classes.
- **infrastructure** — implements application ports. SQLAlchemy, httpx, clickhouse-connect,
  and `re2` compilation live ONLY here.
- **presentation** — depends on application + its context's composition. **MUST NOT import
  infrastructure.**
- **`<bc>/composition.py`** — that context's request-scoped wiring: `provide_*` functions that
  build services out of `app.state`, plus `require_role(Role)`. It exports the providers only.
  `Annotated[Service, Depends(provide_service)]` is written **in the handler signature that needs
  it** — not aliased in composition, not aliased at the top of the router. The type a handler
  receives and the function that builds it then read off that handler with nothing to look up.
  It repeats; that is the cost of the signature being complete.

### Wiring is split by lifetime, and the names must say so

`app.py` is the composition root: its lifespan builds the object graph that lives as long as
the process and puts it on `app.state`. A context's `composition.py` takes a `Request` and
assembles per-request services out of what is already there.

This was wrong for a while and it cost something. A root `composition.py` called itself "the
ONLY place importing infra concretes" while `app.py` was doing the same thing, and the layering
rule exempted both as "wiring roots". An infrastructure adapter (`SessionScopedApiKeyRepository`)
sat inside `app.py` and nothing could see it, because the two files' roles had never been named
correctly.

**A composition root does not take an HTTP request.** If a wiring function's signature starts
with `request: Request`, it is framework glue, not the root.

## Reuse shared_kernel (don't reinvent)

- `config`: `BaseAppSettings` + nested `DatabaseSettings`, `ClickHouseSettings`, `LogSettings`.
- `database`: `Base` (DeclarativeBase + `NAMING_CONVENTION`), `TimestampMixin`, the engine
  lifecycle — `get_engine` / `get_session_factory` (both `lru_cache`d) / `dispose_engine` — and
  `Commit`, the `session.commit` callable every service takes.
- `clickhouse`: `get_clickhouse_client` / `dispose_clickhouse`, deliberately the same shape.
- `redis`: `get_redis_client` / `dispose_redis`, same again.

**Both stores open and close in shared_kernel, not in the composition root.** The settings
that *describe* a store (`DatabaseSettings`, `ClickHouseSettings`) were already there, so the
code that *opens the connection* belongs beside them; neither has any gateway knowledge.
ClickHouse was the odd one out for a while — `app.py` imported the driver directly, spelled
the five settings fields out by hand, and never closed the client, so the two stores looked
different at the same place in the lifespan. Symmetry here is what makes the asymmetry
visible when it is real (the schema step genuinely differs: Alembic for Postgres, an
idempotent `CREATE TABLE IF NOT EXISTS` applied in the lifespan for ClickHouse, §12).
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
   use cases. The handler asks for one inline:
   `service: Annotated[UserService, Depends(provide_user_service)]`.
   **Collaborator fields name their kind, spelled out** — `self._user_repository`,
   `self._user_dao`, `self._refresh_session_repository`, `self._access_token_codec`,
   `self._unit_of_work`, with the constructor parameter matching. Not `self._users`/`_dao`/`_uow`:
   `user_repository`/`user_dao` reads write-side vs read-side at a glance where `users`/`dao` is
   asymmetric and `dao` decodes to nothing. The stutter with the type is cheaper than the decode.
   Plain values keep a plain name (`refresh_ttl`).

4. **Errors = ErrorCatalog enum per aggregate.** Members `NAME = (code, default_message, category)`.
   Code format `<AGGREGATE>-NNN`. Raise via `<Aggregate>Error.X.exception(...)` or `.raise_()`.
   NO class-per-error. Handler = `shared_kernel.register_exception_handlers`.

5. **Non-DB dependencies use port/adapter.** A `Protocol` port in `application/port/`, an
   adapter in `infrastructure/`, wired in that context's `composition.py`. This covers the upstream LLM
   relay, the audit sink, and the judgement model tier. §12 requires the model tier to be
   swappable (Ollama → vLLM → Bedrock) without touching the core — the port is how.

6. **Use OOP for stateful policies and workflow units.** Prefer small classes when behavior
   has configuration, collaborators, or multiple related methods. Inject dependencies through
   `__init__`; expose a narrow method. Value objects and DTOs stay dataclasses/Pydantic.

## Aggregate design — the `ApiKey` worked example

`ApiKey` was reshaped from a nine-field record with three methods down to six fields with four,
and every step of that came from one question: **is this what the credential *is*, or what it is
*allowed to do*?** (AGENTS.md, "Domain modelling principles"). The result is worth reading as the
reference shape:

```python
@dataclass(frozen=True, slots=True)
class ApiKey:
    id: UUID                              # uuid7() — stdlib on 3.14
    name: str
    key: str = field(repr=False)          # plaintext; repr=False so logging the aggregate is safe
    user_id: UUID
    expires_at: datetime | None = None
    revoked_at: datetime | None = None    # not a `disabled` bool — *when* matters for audit

    @classmethod
    def issue(cls, *, name, user_id, expires_at=None) -> ApiKey
    def update(self, *, name, expires_at) -> ApiKey
    def revoke(self) -> ApiKey
    def ensure_active(self) -> None
```

`User` is the other half of this context and answers the mirror question — "may this person sign
in" — with the same vocabulary: `register` / `update` / `set_password` / `change_role` /
`deactivate` / `ensure_active` / `ensure_admin` / `authenticate`.

Passwords are hashed even though `ApiKey.key` is plaintext, and that asymmetry is the point: an
API key is high-entropy and its reader is the operator, while a human password is low-entropy and
**reused on other sites**, so a leak there compromises accounts that are not ours. Login is not
the request path, so a 74 ms KDF is free (`hashlib.scrypt`, stdlib, memory-hard).

The KDF lives in a `PasswordHash` value object rather than in `User`, because it is the one part
that does not change when the user does — bumping the cost or moving to argon2 leaves every `User`
method untouched. `User` asks `password_hash.matches(password)` and knows nothing about salts. If
per-environment cost ever matters (a test suite paying 74 ms per fixture), an injectable hasher
can wrap the value object without `User` noticing.

What left, and why it was not a loss:

| Removed | Where it belongs |
|---|---|
| `upstream_base_url` · `upstream_api_key` | provider configuration — a secret that several keys can share is not part of one key's identity |
| `allowed_guardrails` · `default_guardrail` | authorisation attached to the credential, not the credential |
| `scopes` | same, and the admin surface's authorisation is a separate credential (§14) |
| `has_scope` · `require_scope` · `resolve_guardrail` | they hung off those fields and left with them |
| `hash_key` · `generate_key` · `KEY_PREFIX` | folded into `issue()`, which is the only caller |

Three rules the transitions enforce, each because the alternative splits a single answer in two:

- **A revoked key cannot be updated** — extending a dead credential's expiry reads as reviving it.
- **An expiry cannot be in the past** — otherwise expiry becomes a second revocation path that
  leaves `revoked_at` empty, and "why is this dead" has two answers. Immediate kill is `revoke()`.
- **`revoke()` is idempotent** and never deletes the row: the audit log references `api_key_id`,
  so deleting it makes past records unattributable (§10).

**State transitions belong on the aggregate, not in a targeted `UPDATE`.** The old code did
`set_disabled(key_id, disabled)` straight to SQL, so "can you revoke twice?" and "can you extend
an expired key?" had no answer anywhere. `get` → `key.revoke()` → `save` puts those answers in
one place, and the extra read is off the request path (admin only).

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
guardrail/domain/guardrail.py                     authored form; pure domain
guardrail/plan/domain/execution_plan.py           ExecutionPlan · Program · instructions · slots
guardrail/plan/domain/executor.py                 execute(program, Subject) -> ExecutionResult
guardrail/plan/application/compiler.py            Guardrail -> ExecutionPlan (once, at publish)
guardrail/plan/application/service/registry.py    PlanRegistry — in-memory, atomic swap, polling
guardrail/plan/application/port/guardrail_source.py   Protocol: 발행본 읽기
guardrail/inspection/application/service/inspector.py 체크포인트별 대상 추출 -> execute -> Inspection
```

Rules that must hold:

- **`Program` and its instructions are slotted dataclasses, NOT `CamelModel`.** Pydantic validation must
  never run on the request path. The `CamelModel` convention applies to DTOs that cross the
  HTTP boundary; a plan never does.
- **Nothing recompiles per request.** `PlanRegistry.get` is a dict lookup. A repository or provider
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

## When tests come back

The suite is gone (`ae52c5b`). What follows is what it cost to learn — worth keeping so the
next suite starts from here rather than rediscovering it.

**The bar for writing one.** A test must be able to fail when externally observable
behaviour breaks. The old suite failed this in three recurring ways, and those are the
things not to rebuild:

- **Tests that read source and assert on its shape** (`test_layering`, `test_models_registry`
  parsed the package to check imports and `__tablename__`). They fail on every harmless move
  and pass while behaviour is broken. AGENTS.md forbids exactly this.
- **Meta-tests that assert another test can fail** (`test_the_registry_check_can_actually_fail`).
  If a test needs a test, the first one is testing the wrong thing.
- **The same property re-asserted from a slightly different angle.** 906 tests for 5,588
  source lines was mostly this.

Worth rebuilding, in rough priority: the defects that **only a real uvicorn run** exposed
(publish taking effect one request late; `PUT draft` then `publish` reading a stale draft;
streaming latency counting upstream generation as ours), and the two **external-contract
pins** — the OpenAI SDK tolerating our extension field (§11.9) and ClickHouse's handling of
`DateTime64(3)` (§11.10). Those two exist to make an upstream change visible instead of
silent, which no amount of our own testing replaces.

**Mutation testing was the gate that earned its keep.** It caught a cross-worker determinism
bug no in-process test could see. If it returns, three things are required or the numbers
lie:

- Restore on any exit (`trap restore EXIT INT TERM`), and delete `__pycache__` with the
  source — a same-length edit restored within the same second is byte-identical in size and
  mtime, so the stale `.pyc` keeps running.
- Never let a pytest run be SIGKILLed against the shared Postgres: it leaves a backend `idle
  in transaction` holding locks, and every later run then blocks in `TRUNCATE`/`drop_all`.
  The symptom is different failures on each run, which reads like flaky tests rather than a
  wedged database. Check `pg_stat_activity`, and check for other mutation shells still
  looping.
- **Count a hang as CAUGHT**, and read the exit code without a pipe — `$?` after
  `$(... | tail -3)` is `tail`'s status, always 0, and `PIPESTATUS[0]` does not propagate
  out of a command substitution:

```bash
out=$(timeout 300 uv run pytest -q 2>&1); rc=$?
if [ "$rc" -eq 124 ]; then echo "HANG (=CAUGHT)"
elif printf '%s' "$out" | grep -qE "[0-9]+ (failed|error)"; then echo CAUGHT
else echo SURVIVED; fi
```

**Commit before mutating.** The `git checkout -- src/` that restores a mutation also discards
uncommitted source fixes. This has bitten four times in this repo — including once *while
fixing a survivor*, and once on a file staged by `git mv`, where `checkout --` restored the
**index** version and silently reinstated the pre-move content.

## Determinism a single process cannot observe

Instruction order, slot numbers, and anything else derived from iterating a `set` of strings
varies **between processes** — string hashing is randomised per process. Compiling twice in
one process always agrees, so nothing run in a single process can observe this.

§6 compiles per worker, so an order that varies per worker changes where early exit lands,
which changes the `checks_fired` recorded for the same request — the audit log stops being
usable for tuning policy.

Prefer removing the dependency over detecting it: **iterate a declared order** (a tuple, or a
dict built from one) rather than sorting a set into place. `compiler._topological` walks
`self.nodes` in declaration order for this reason; do not "simplify" it to iterate the live
set.

## Editing code by string replacement

`s.replace(old, new)` silently does nothing when `old` no longer matches — and
after `ruff format` runs, multi-line call sites often collapse to one line, so a
replacement written against the pre-format text stops matching. This happened three
times in one session; every time, the test suite stayed green and only a real
uvicorn run surfaced it (a checkpoint that never ran, a `checks` list that stayed
empty).

Always assert the match:

```python
assert old in s, old[:60]
s = s.replace(old, new, 1)
```

Then grep for the new text to confirm it landed. `Edit` (which fails loudly on a
non-match) is preferable to a scripted `replace` for exactly this reason.

## The response/cleanup boundary

A FastAPI `yield` dependency's cleanup runs **after the response is sent**. Anything put
there is therefore late in production — and invisible to any test using
`httpx.ASGITransport`, which awaits the entire ASGI call before returning.

This produced three defects in one sitting, all of them green in the suite at the time: a
publish that took effect one request late, a `PUT draft` whose next `publish` read the
previous draft, and a compile failure that only reached the log.

**Put "must be true when the caller sees 200" work inside the service** — the application
service is the unit-of-work boundary, not the composition root. Commit before recompiling (a
new session cannot see uncommitted rows), and read your own write *before* committing so the
request stays one transaction: a read issued after the commit opens a second transaction that
only closes during cleanup, and that open transaction blocks DDL.

**Therefore the service owns the commit, and `provide_*` must not commit after its `yield`.**
It did for a while, and that safety net cancelled the rule: a service that forgot to commit
still persisted — just late, i.e. exactly the defect above, reintroduced invisibly. The service
now demarcates the boundary with `async with self._uow:`; on a clean exit the unit of work
commits, on an exception it rolls back. Forgetting the boundary means the write is never
committed and the session's `async with` in `provide_*` rolls it back — the miss shows up as
data that is *missing*, not data that is *late*.

### Only Postgres is transactional

The unit of work covers **one store**. Redis cannot join a commit protocol at all — measured against
the real server: inside `MULTI`/`EXEC` a failing command neither stops the rest nor undoes what
ran before it (`[True, ResponseError, True]`, and both `SET`s stayed), `DISCARD` only works
*before* `EXEC`, and of 447 commands there is no `PREPARE` and no `XA`. ClickHouse is batched and
asynchronous by design (§10), so the audit sink is outside the request's transaction on purpose.

So cross-store work is **ordered to fail safe, not rolled back**: a write that *revokes access*
goes **before** the commit. `change_password` and `deactivate` both save the user, drop the
user's Redis sessions, then commit — if the commit fails the sessions are gone and the password
is unchanged, which is more restrictive. Commit-then-revoke would leave the new password live
alongside the old sessions, which is a security hole, and "commit first, then side effects" is
exactly the reordering a reader would reach for.

**The service declares the boundary; the word `commit` never appears in it.** It takes a
`UnitOfWork` (a `Protocol` in `shared_kernel.database`) and writes:

```python
async with self._uow:          # uow=SqlAlchemyUnitOfWork(session) at the composition root
    await self._users.add(user)
    summary = await self._summary(user.id)   # read-own-write, still before the commit
# committed here on clean exit; post-commit work (publish's recompile) goes after the block
```

`commit`/`rollback` live only in `SqlAlchemyUnitOfWork.__aexit__` — that is an SQLAlchemy concept
and the application has no business knowing it. What the application *does* own is the boundary:
what is atomic together, what a side effect must precede (§ the revoke-before-commit above), and
what must follow the commit (`publish` recompiles **after** the `async with` block, where it is
visible — not in an after-commit hook). Required keyword, **no default**: a default on a wired
dependency is how a missing wire becomes a silent wrong answer, the same shape as `plans=` and
`mode=`. Opening is autobegin's job (the transaction starts at the first SQL) and closing is the
session's `async with` in `provide_*`; the unit of work only decides commit-or-rollback.

This went `Transaction` `Protocol` (one `commit()`, managed nothing — a name for a thing that did
not exist) → `Commit` type alias → a bare callable, before landing on the unit of work. The first
two named a *verb* the application had to call; `UnitOfWork` names the *boundary* the application
actually owns, and it does real work in `__aexit__`, so the name finally matches the thing. A
decorator (`@transactional`, Spring-style) was measured too and rejected: it commits at method
return, which forces `publish`'s post-commit recompile into an after-commit hook and hides the
revoke-before-commit ordering — both of which the `async with` keeps visible.

Verify by running real uvicorn and reading the ordering in the log. Disable anything that
could mask it first — set a huge `GARDEVOIR_PLAN_POLL_INTERVAL_S` so the poller cannot cover
for a broken immediate refresh.

## Alembic autogenerate

**`alembic revision --autogenerate` produces an empty migration if the database already
matches the models** — e.g. after anything ran `Base.metadata.create_all` against it. This
has bitten twice. Reset to the *migrated* state first:

```bash
docker exec gardevoir-postgres-1 psql -U gardevoir -q \
  -c 'DROP TABLE IF EXISTS api_keys CASCADE; DROP TABLE IF EXISTS alembic_version CASCADE;'
uv run alembic upgrade head          # applies the existing chain only
uv run alembic revision --autogenerate -m "..."
```

Then verify the generated file is not `pass`, apply it, and check the upgrade/downgrade
round trip.

**A new ORM model needs no registration step.** `alembic/env.py` walks the whole `gateway`
package with `pkgutil.walk_packages` and imports every module, so every `Base` subclass reaches
`Base.metadata` wherever it lives. The model belongs to its context
(`identity/infrastructure/api_key_model.py`,
`guardrail/definition/infrastructure/guardrail_model.py`) and that is the only place it needs
to exist.

There used to be a hand-written manifest (`gateway/orm.py`) whose own docstring warned that a
model missing from it would be silently absent from migrations. A list that has to be
remembered, guarding against forgetting — the walk removes the failure mode instead of
documenting it. It costs 269 ms, on a path that is not the request path.

## Request-path constraints (measured, not aspirational)

Total gateway overhead is 0.63 ms/request against a 300–2000 ms upstream call (§11.8).
The following are load-bearing:

- **No network hop on the request path** (§6). Measured: a local dict lookup is 0.287 µs, a
  localhost Redis GET is 91.1 µs (**318×**), and JWT HS256 verification is 3.110 µs (**11×**,
  and unlike a lookup it cannot be cached). Anything that would put a network round trip or a
  per-request crypto step in front of every proxied call has to clear that bar first.
- **Key lookup does hit Postgres, once per request, and that is deliberate.** 1.2 ms at
  concurrency 8 — 0.4% of a 300–2000 ms upstream call. It replaced a TTL cache whose *misses*
  were already hitting the DB **inside a request** (0.347 ms, making that request 2.3× slower,
  on 0.2–1% of traffic), so §6's "no DB on the request path" was only statistically true. What
  the trade buys: revocation takes effect immediately, and cache invalidation/propagation stops
  being a concept. What it costs: Postgres down means the proxy cannot serve.
- **The raw API key is stored in plaintext.** Deliberate and hard to reverse — moving back to
  hashes invalidates every issued key. The reasoning: in a self-hosted deployment whoever can
  read the DB is the operator, and `upstream_api_key` (a provider secret that can spend money)
  was already stored in plaintext beside it. Do not "fix" this back to hashing without saying
  so out loud.
- **`orjson` only** for JSON. `json` is 2.3× slower and the streaming path parses per chunk (§11.7).
- **Python 3.14** (`backend/.python-version`). `uuid.uuid7()` for mutable-state PKs comes from
  the stdlib — do not add a UUIDv7 library. The upgrade from 3.12 changed nothing measurable on
  the request path: pure-Python loops got 1.6× faster but §11.4's per-request figure moved
  0.269 → 0.260 ms, because that path is dominated by re2 (C++), not by the interpreter.
- **`re2` only** for regex — never `re`. `(a+)+$` against 26 characters takes 8.9 s in
  Python `re` and 0.034 ms in `google-re2` (§11.1). A policy author's typo would otherwise
  become a denial-of-service switch. Use `re2.Set` to match many patterns in one pass —
  510× faster than looping (§11.2).
- **Never call a synchronous client from the event loop.** `clickhouse-connect` is sync;
  a 100-row insert blocks every in-flight request for 5–20 ms. Wrap it in
  `asyncio.to_thread`.
- **Audit writes never block the response** (§10). Queue, then batch in the background.

## Wire contract, and the two verdict vocabularies

`proxy/contract.py` holds the `/v1/chat/completions` protocol: header names, the `gardevoir`
extension object, the blocked-response bodies, and the wire `Action`. **Keep it minimal — §7
treats the protocol as the part that is hard to change and configuration as the part that is
easy.** Adding a field here can break deployed applications; adding a guardrail check cannot.
§7.2 makes the URL prefix the contract version, so it is not in any contract module: `app.py`
applies it at `include_router(..., prefix=API_PREFIX)` and routers declare only their sub-path
(`/guardrails`, `/chat/completions`). Mounting is a composition-root decision — `/healthz`
deliberately gets no prefix because it is operational, not part of the contract — and keeping
the version there means one place to change when it moves to `/v2`.

**Two verdict vocabularies, and they do not match. That is deliberate.**

```
VerdictAction   block · mask · allow                  domain — what a node declares (§5)
Action          allow · blocked · approval_required   wire  — what the caller sees (§7.3)
```

`mask` has no wire counterpart: a masked response is, to the caller, an allowed response, and
the fact that something was masked is carried separately in the extension object.
`approval_required` has no domain counterpart yet (Phase 6).

**`proxy/contract.to_wire_action` is the only translation point.** Everything upstream of it —
`Inspection`, the compiler, the executor — speaks `VerdictAction`. This direction matters: the
core domain must not import the wire contract, or a protocol change shakes the domain. It was
the other way around for a while (`Inspection.action: Action` with `contract.py` at the root,
so the inversion was invisible), which is why `Inspection` needed both `action` and a separate
`masked` flag to say one thing.

`Mode` is domain vocabulary too (`guardrail/domain/mode.py`) — dry-run is *how the inspector
behaves*, and the header is only how the caller asks for it. The router parses it; identity
does not know about it.

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
- Engine lazy (`shared_kernel.database`), disposed in the app lifespan.
- Postgres migrations via Alembic; the ClickHouse audit schema via numbered `.sql` files
  (one append-only table needs no migration tool).

## Not used here (differs from other internal repos)

| Absent | Why |
|---|---|
| Kafka / outbox / CDC / domain events | Nothing publishes events (§12) |
| Redis for taint / approvals | Taint tracking is stateless — the `messages` array carries the full history (§7.4). Approvals are low-volume and live in Postgres. **Redis is used, but only for refresh sessions**: TTL expiry means the store cannot grow unboundedly, and the refresh path is not latency-sensitive. Persistence is off, which is also why the session token is stored as-is rather than hashed — nothing is ever written to disk, so the leaked-dump threat that would justify hashing does not exist. **Turning persistence on would change that.** Do not extend it to the proxy request path — a localhost GET is 91 µs against a 0.287 µs dict lookup |
| JWT / `Principal` / header-trust auth | Callers authenticate with a gardevoir-issued API key; app identity comes from the credential, never a header (§7.2) |
| Celery | No background fan-out; asyncio tasks suffice |
| Object storage | ClickHouse `TTL` + partition drop covers retention (§10) |
| Prometheus | The audit log already records per-request latency and verdicts; a second metrics path would split the source of truth (§12) |

## Adding a bounded context

Contexts are packages inside `gateway`, not workspace members — they share the process.

1. `src/gateway/<bc>/` with **only the layers it needs**. Do not scaffold empty ones.
2. `domain/models/` aggregate + `domain/exceptions/<aggregate>_error.py` catalog, if the
   context owns an aggregate.
3. `application/{service,repository,dao,command,result,port}/` — by role, per the rule above.
   Whatever fits none of them goes at the `application/` root, not into the nearest directory.
4. `infrastructure/`: ORM model, mapper, adapters. No manifest to register the model in —
   `alembic/env.py` finds it by walking `**/infrastructure/`.
5. `<bc>/composition.py` exporting `provide_*` and nothing else; `presentation/<name>_router.py`
   writing `Annotated[Service, Depends(provide_service)]` in each handler signature; mount the
   router in `app.py`. Process-lifetime resources go in `app.py`'s lifespan, not here.
6. Verify by importing every module, `ruff`, and a real uvicorn run (see the top of this file).

**Before adding one, check it is actually a context.** The signals that justified the current
four: the model changes at the boundary, the storage differs, or the lifecycle differs. "These
files are related" is not one — that is a package.

## Common mistakes (vs naive defaults)

| Naive default | gardevoir convention |
|---|---|
| repository interface in `domain/` | repository(write) + dao(read) **Protocols in `application/`**; domain stays pure |
| DAO returns domain entities | DAO returns application **result DTOs** |
| three DTO tiers | **single** application-owned `CamelModel` at the boundary |
| use cases as loose functions; a class per error | **service classes**; one `ErrorCatalog` enum per aggregate |
| one `models.py` / one `mappers.py` | per-model file in the owning context's `infrastructure/`; `alembic/env.py` finds them by walking |
| a flat `application/` package | split by role: `service/` `repository/` `dao/` `command/` `result/` `port/`; misfits stay at the layer root |
| DI in presentation | DI in the context's `composition.py`; presentation never imports infrastructure |
| one root `composition.py` for every context | one per context — a shared file is a chokepoint every new context edits |
| defaulting a wired dependency (`getattr(state, "x", None)`) | let it fail. A missing wire becomes a silent no-op otherwise — `plans=None` made publish return 200 without recompiling |
| per-BC exception handler | reuse `shared_kernel.register_exception_handlers` |
| `Program` as a `CamelModel` | slotted dataclass — Pydantic must not run on the request path |
| walking the guardrail DAG per request | compile at publish, execute a flat instruction array (§11.4) |
| `import re` | `import re2` — always |
| `json.loads` | `orjson.loads` |
| calling `clickhouse_connect` insert directly in async code | `await asyncio.to_thread(...)` |
| serialising compiled plans to object storage | recompile in-process; RE2 automata do not serialise (§11.5) |
