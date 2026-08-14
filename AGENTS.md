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
    identity/         ApiKey — credentials and scopes (§7.2)
    guardrail/        CORE DOMAIN — domain/ shared by definition · plan · inspection
    proxy/            LLM request/response, streaming, the §7 wire contract
    audit/            AuditEvent — ClickHouse
  ```

  Contexts live *inside* `gateway` because they share one process (§12). Each has only the
  layers it needs, plus its own `composition.py` for request-scoped wiring. See the
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
Twice: `plans=getattr(state, "plans", None)` made publish return 200 without recompiling, and
`mode: Mode = Mode.ENFORCE` made dry-run requests record themselves as `enforce` while
inspecting correctly — a lie that no behavioural check would catch. Let it fail instead.

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

**9. Verify by starting the server.** Not a stopgap for having no tests — three defects this
session were invisible to anything short of a real process: publish taking effect one request
late, streaming latency counting upstream generation as ours, and the dry-run mode misreport
above.

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
- Sync deps from `backend/` (the workspace root): `uv sync --all-packages`.
  **`--all-packages` is required.** The root is a virtual workspace with nothing to
  install, so a bare `uv sync` *uninstalls* every member and its dependencies. The
  failure is confusing: `import shared_kernel` still succeeds, because the member
  directory is picked up as an implicit namespace package, and only surfaces as
  `AttributeError` on a missing attribute.
- The first admin key comes from `GARDEVOIR_BOOTSTRAP_ADMIN_KEY` at startup; every key after
  that is made through `/v1/admin/api-keys`. There is no CLI.
- Bring up dependencies first — see `infra/README.md` for the command. It needs
  `--env-file infra/envs/example/compose.env`; without it compose fails on an empty
  `cpus` value.
- Commit before any experiment that ends in `git checkout --`. The restore reverts your
  uncommitted work too — and for a file staged by `git mv`, it restores the *index* version,
  silently reinstating pre-move content.

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
