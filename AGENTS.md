# gardevoir — agent guide

Tool-neutral guide for coding agents (Claude Code, Codex, …). Claude also reads `CLAUDE.md`;
Codex reads this file. Keep shared guidance here.

## What this repo is

`gardevoir` — an OpenAI-compatible reverse proxy that puts guardrails in front of LLM
applications, including **agent action control** rather than text moderation alone.
Point an app at gardevoir instead of the provider and policies apply with no application
code changes.

- `backend/` — FastAPI **modular monolith** on a **uv workspace** (async SQLAlchemy 2.0 +
  PostgreSQL for state, ClickHouse for audit events, Pydantic v2). DDD + CQRS-lite.
  `shared_kernel` is a library; **`gateway` is the only service.**

  ```
  gateway/
    app.py            composition root — lifespan builds the process-lifetime graph,
                      mounts routers, owns API_PREFIX ("/v1")
    settings.py  health.py
    identity/         ApiKey (proxy credential) · User (JWT·Role) (§7.2)
    guardrail/        CORE DOMAIN — domain/ shared by definition · plan · inspection
    proxy/            LLM request/response, streaming, the §7 wire contract
    provider/         upstream LLM providers — routed by the request's model
    audit/            AuditEvent — ClickHouse
  ```

  Contexts live *inside* `gateway` because they share one process (§12). Each has only the
  layers it needs, plus its own `composition.py` exporting `provide_*` wiring functions. See the
  `gardevoir-be` skill for the full layout and why the boundaries fall where they do.
- `frontend/` — pnpm workspace. `apps/console` (Next.js guardrail authoring console with a
  React Flow node editor).
- `infra/` — docker-compose (Postgres, ClickHouse) · dockerfiles · per-environment envs.
- `docs/superpowers/specs/` — design documents. `docs/superpowers/plans/` — implementation plans.

## Structural principles

These came out of carving the bounded contexts (#10–#18) and are worth stating because most
of the problems found there were the *same* problem. Detail and the layout live in the
`gardevoir-be` skill; this is the short form.

**1. A name that does not match the thing hides violations from the rules that would catch
them.** `composition.py` called itself the composition root while `app.py` was the one
actually building the object graph, so the layering rule exempted both as "wiring roots" —
and an infrastructure adapter sat inside `app.py` for months, invisible. A root
`infrastructure/` meant "process resources" while `<bc>/infrastructure/` meant "adapters", so
the word carried two meanings in one tree. When a rule needs an exception, check the name
first: the exception is usually the rule pointing at a mislabelled thing.

**2. Wiring is split by lifetime, and only the process-lifetime half is the composition
root.** `app.py`'s lifespan builds what lives as long as the process and puts it on
`app.state`; `<bc>/composition.py` assembles per-request services out of that. A composition
root does not take an HTTP request — if a wiring function's signature starts with
`request: Request`, it is framework glue.

**3. A default on a wired dependency turns a missing wire into a silent wrong answer.**
Three times: `plans=getattr(state, "plans", None)` made publish return 200 without recompiling,
`mode: Mode = Mode.ENFORCE` made dry-run requests record themselves as `enforce` while
inspecting correctly, and a defaulted `uow=None` would let a service with no unit of work wired
persist nothing at all. Let it fail instead. The related shape is a **second owner** of the same
decision: while `provide_*` also committed after its `yield`, a service that forgot to commit
still persisted — just after the response, which is the defect the boundary exists to prevent. A
safety net that hides the failure it catches is not a safety net.

**4. A list that has to be remembered is a failure mode.** `orm.py` existed to import every
ORM model, and its own docstring warned that a model missing from it would vanish from
migrations. Alembic now walks the package. Prefer removing the way to forget over documenting
the consequence of forgetting.

**5. Dependencies point toward the core domain, and translation happens at the edge.**
`Inspection` used to be typed with the wire `Action`, so the guardrail domain imported the
HTTP contract. There are deliberately two verdict vocabularies — `VerdictAction`
(block/mask/allow) is what a policy author declares, `Action` (allow/blocked/…) is what the
caller sees — and `proxy/contract.to_wire_action` is the only place they meet.

**6. Whatever describes a resource, the code that opens it belongs beside.** `DatabaseSettings`
and `ClickHouseSettings` are shared_kernel's, so `get_session_factory` and
`get_clickhouse_client` are too — and both are disposed in the same `finally`. Symmetry here
is what makes a *real* asymmetry visible: Postgres migrates through Alembic, ClickHouse
applies an idempotent schema in the lifespan, and that difference is intentional (§12).

**7. An adapter owns its transport.** `HttpxUpstream` creates and closes its own
`AsyncClient`. The composition root imports no driver at all now — no `httpx`, no
`clickhouse_connect`, no `sqlalchemy`.

**8. A bounded context earns its boundary when the model changes, the storage differs, or the
lifecycle differs.** "These files are related" is a package, not a context. `guardrail` is the
core domain and is roughly half the code; a core domain smaller than its supporting contexts
would be the thing to worry about.

**9. Verify by starting the server, and measure before accepting a premise.** Three defects
were invisible to anything short of a real process: publish taking effect one request late,
streaming latency counting upstream generation as ours, and a dry-run request recording itself
as `enforce`. Measurement has also reversed the *direction* of a decision more than once —
"a per-request DB read is too expensive" turned out to be false (the cache's misses were already
reading the DB inside a request), and the alternatives were worse (Redis 318×, JWT 11×). State
the number before choosing the shape.

## Domain modelling principles

These came out of reshaping the `ApiKey` aggregate (#20, #22). Same spirit as above: most were
one mistake wearing different clothes.

**1. An aggregate holds what the thing *is*, not what it is *allowed to do*.** `ApiKey` carried
provider secrets, a guardrail allowlist, and scopes. §7.2 says "authorisation comes from the
credential" — that means authorisation *derives from* the credential, **not** that it has to be
*fields on the aggregate*. Misreading that put the fields back once after they had been removed;
a row keyed by `api_key_id` satisfies §7.2 just as well.

**2. Methods follow fields.** All three original methods (`has_scope`, `require_scope`,
`resolve_guardrail`) hung off the fields that did not belong, and left with them. It works in
reverse too: if an aggregate has behaviour you cannot derive from what it *is*, suspect the
fields before the behaviour.

**3. A factory returns its own type.** `issue()` needing to return `(ApiKey, str)` was a symptom
— the secret had to escape because only its hash was stored. When plaintext storage removed the
hashing, the awkwardness vanished on its own. If a factory cannot cleanly return its own type,
something else in the model is wrong; do not paper over it with a tuple or a nullable transient
field.

**4. Never inject the clock into a security decision.** `ensure_active(now)` would make `now` the
bypass — a caller passing the wrong value lets an expired credential through. Calling
`datetime.now(UTC)` inside means it cannot be got wrong. The cost is that time cannot be frozen
in a test; that is the cheaper side.

**5. One outcome, one path.** Allowing `expires_at` in the past would create a second way to
kill a key that does not record `revoked_at`, so "why is this dead" gets two answers. Related:
an optional parameter that must mean both "leave unchanged" and "clear" is a missing sentinel —
require both fields (PUT) and let the service fill the rest from the aggregate it already loaded.

**6. Format is the transport's job; rules are the domain's.** A naive `datetime` compared against
an aware one is a `TypeError`, i.e. a 500. `AwareDatetime` in the command DTO turns that into a
422 with a field error, and the domain only asks "is it in the future". Do **not** coerce naive
to UTC — a caller who meant KST and omitted the offset would silently store a 9-hour error.

**7. Do not name a one-liner.** The *reason* for a rule belongs in one docstring; a two-line
condition can sit in the two places that need it. Extracting it buys a name and costs a jump.

## Read the design document first

`docs/superpowers/specs/2026-08-12-gardevoir-design.md` is the source of truth for
architecture, and §11 records measurements taken on this hardware. Several structural
choices exist **because** of those measurements and will be silently undone by an otherwise
reasonable refactor. Section references (§N) throughout the code and skills point there.

## Skills

Reusable skills live in **`skills/`** (single source of truth), exposed to each tool via
committed relative symlinks: `.claude/skills -> ../skills` and `.codex/skills -> ../skills`.
Add a skill once under `skills/<name>/SKILL.md`; both tools pick it up.

- **`gardevoir-be`** — backend architecture conventions. **Read it before implementing or
  modifying any backend code** (layers, repositories/DAOs, ports, services, command/result
  DTOs, domain errors, DI, guardrail compilation, and the request-path performance
  constraints).

## Working in the backend

- **There are no tests right now.** `backend/gateway/tests/` was deleted while the bounded
  contexts were carved out (kept in git at `ae52c5b`). Verify by importing every module,
  running `ruff`, and **actually starting the server** — see the `gardevoir-be` skill for the
  commands and the end-to-end smoke path. Do not restore the old suite wholesale and do not
  add tests opportunistically; the bar for the next suite is in that skill.
- **Python 3.14** — pinned in `backend/.python-version`. `uuid.uuid7()` is stdlib here; do not
  add a UUIDv7 dependency.
- Sync deps from `backend/` (the workspace root): `uv sync --all-packages`.
  **`--all-packages` is required.** The root is a virtual workspace with nothing to
  install, so a bare `uv sync` *uninstalls* every member and its dependencies. The
  failure is confusing: `import shared_kernel` still succeeds, because the member
  directory is picked up as an implicit namespace package, and only surfaces as
  `AttributeError` on a missing attribute.
- The first account comes from `GARDEVOIR_ROOT_EMAIL` / `GARDEVOIR_ROOT_PASSWORD` at startup,
  only when no user exists; every account after that is created by an admin through
  `POST /v1/users`. `GARDEVOIR_JWT_SECRET` has no default on purpose. There is no CLI.
- Bring up dependencies first — see `infra/README.md` for the command. It needs
  `--env-file infra/envs/example/compose.env`; without it compose fails on an empty
  `cpus` value.
- Commit before any experiment that ends in `git checkout --`. The restore reverts your
  uncommitted work too — and for a file staged by `git mv`, it restores the *index* version,
  silently reinstating pre-move content.

## Authorisation is not a URL

There is no `/admin/**` prefix. A route names a resource; who may call it is a property of the
caller, so it belongs in a dependency — `Depends(require_role(Role.ADMIN))` on the routes that
need it. `GET /v1/users` and `GET /v1/users/me` are the same resource tree with different
permissions, and that reads correctly.

The guard must be a **dependency**, never a check inside the handler body: FastAPI resolves
sub-dependencies before validating the endpoint's own params, so a dependency that raises gives
401/403 while a body check would let an unauthorised caller read the schema off a 422. Verified
over HTTP — `POST /v1/users` with no token and an empty body returns 401, not 422.

The prefix used to double as an operational handle ("block `/v1/admin/*` at the ingress"), but
that mitigation existed *because* the admin surface had no human authentication. It has one now.

The guard, the principal it produces, and the role vocabulary live in **`shared_kernel.auth`**,
not in identity — `require_role`, `AccessTokenClaims`, `Role`, `AuthError`, `AccessTokenCodec`.
JWT is a pure in-process transform (no I/O), so it is not behind a port/adapter — the concrete
codec sits in `shared_kernel.auth` directly, the way `PasswordHash` does `scrypt`.
The test is "if the server split, what crosses the boundary?": every context that protects a
route needs to *verify* a token and read a role, so the verify contract is shared; only *issuing*
(signing, login, sessions, `User`) stays in identity. A separate service cannot
`import gateway.identity`, so what it would need is a contract, and the contract is what belongs
in `shared_kernel`. This is the one reason the domain may import past `shared_kernel.exception`:
`User.role` uses the shared `Role`.

## Dependency injection

`<bc>/composition.py` exports `provide_*` functions and nothing else. Write
`Annotated[Service, Depends(provide_service)]` **in the handler signature that needs it** — not
aliased in composition, and not aliased at the top of the router either. Then the type a handler
receives and the function that builds it both read off that handler, with nothing to look up. It
repeats across handlers; that is the cost of the signature being complete.

## Comments

**First principle: the code should not need one.** A method name, a type, or a small
well-shaped function carries the intent better than a paragraph above it, and it cannot drift
out of date.

Write a comment only when the code genuinely cannot say the thing:

- A decision a reader would otherwise "fix" — `ApiKey.key` holds the raw key, not a hash, and
  reverting that invalidates every issued key.
- A non-obvious consequence — swallowing a malformed password hash into
  `INVALID_CREDENTIALS` is deliberate, because a 500 there is itself a signal about the account.

Do **not** put in code: why an alternative was rejected, what was measured, how the design
evolved. That belongs in the design document, this file, or the `gardevoir-be` skill — a commit
message is the right place for "why not the other way". Code that explains its own history is
code nobody dares to change.

The same rule applies to docstrings. One line saying what the thing is beats ten justifying it.

## Naming

Guards raise; they are not requests. `require_password(pw)` read as "demand a password" when it
meant "check this one" — it is now `authenticate(pw)`, which is simply the operation's name.

- Name the operation if it has one: `authenticate`, `issue`, `revoke`, `deactivate`.
- Otherwise `ensure_<state>()` for a raising guard, and `is_<state>` only when a boolean is
  actually read somewhere.
- Prefer one shared word across aggregates when the meaning is the same: both `ApiKey` and
  `User` answer `ensure_active()`, and the reason each might not be active (`revoked_at`,
  `expires_at`, `deactivated_at`) is what the error codes distinguish.

**A collaborator field names its kind, spelled out — not a terse handle.** A service holds
`self._user_repository`, `self._user_dao`, `self._refresh_session_repository`,
`self._access_token_codec`, `self._unit_of_work` — the constructor parameter matches
(`user_repository: UserRepository`). Not `self._users`, `self._dao`, `self._uow`. The collection
metaphor (`users` for a repository) reads nicely in isolation but pairs badly with the read side
(`users` write / `dao` read is asymmetric and `dao` says nothing); the parallel
`user_repository` / `user_dao` says write-side vs read-side at a glance, and no field is a bare
layer-abbreviation you have to decode. The stutter with the type is the price, and it is cheaper
than the decode. Values, not collaborators, keep their plain name (`refresh_ttl: timedelta`).

## Conventions

- `ruff check` and `ruff format --check` must pass before commit.
- Comments and commit messages in Korean; identifiers and docstrings in English.
  Module and class docstrings stay English everywhere. (When tests return: test *function*
  docstrings are the exception — they state why the test exists rather than describing an
  API, so they follow the comment rule and are written in Korean.)
- Reference the design document as a bare `§N` (e.g. `(§11.4)`), matching the
  `gardevoir-be` skill.
- **`import re2`, never `import re`.** **`orjson`, never `json`.** Both are load-bearing —
  see the `gardevoir-be` skill.

## Testing principles — for when tests come back

None of this is in force today (there is no suite). It is the bar the next one must meet;
the previous suite reached 906 tests and a large share of them failed these rules.


- Test observable behavior through a public boundary: inputs and outputs, state transitions,
  rendered results, persisted data, or integration calls.
- **Do not read implementation source files and assert on their text with regular expressions
  or string matching.** Those tests validate code shape, not behavior, and make harmless
  refactors fail.
- A test must be capable of failing when the user-visible or externally observable behavior
  breaks. Finding a function name, call order as text, or a prop spelling is not sufficient
  evidence.
- Prefer the narrowest real boundary over mocks. If a dependency must be faked, execute the
  production code under test and assert its calls or results; never mock the behavior being
  claimed as verified.
- Some tests exist to pin an external contract rather than our own behavior — for example
  the OpenAI SDK's tolerance of our response extension field (§11.9), or ClickHouse's
  handling of `DateTime64(3)` inputs (§11.10). Keep them; they are how an upstream change
  becomes visible instead of silent.
