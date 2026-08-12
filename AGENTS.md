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
  Each bounded context is a workspace member; `shared_kernel` holds cross-cutting building
  blocks.
- `frontend/` — pnpm workspace. `apps/console` (Next.js guardrail authoring console with a
  React Flow node editor).
- `infra/` — docker-compose (Postgres, ClickHouse) · dockerfiles · per-environment envs.
- `docs/superpowers/specs/` — design documents. `docs/superpowers/plans/` — implementation plans.

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

- Run a context's tests from its package dir: `cd backend/<bc> && uv run pytest`
  (do NOT run bare `pytest` from `backend/` — it cross-collects sibling packages).
- Sync deps from `backend/` (the workspace root): `uv sync --all-packages`.
  **`--all-packages` is required.** The root is a virtual workspace with nothing to
  install, so a bare `uv sync` *uninstalls* every member and its dependencies. The
  failure is confusing: `import shared_kernel` still succeeds, because the member
  directory is picked up as an implicit namespace package, and only surfaces as
  `AttributeError` on a missing attribute.
- Bring up dependencies first — see `infra/README.md` for the command. It needs
  `--env-file infra/envs/example/compose.env`; without it compose fails on an empty
  `cpus` value.
- TDD: failing test → implement → green → commit.
- Commit before mutation-testing or any other experiment that ends in
  `git checkout --`. Otherwise the restore reverts your uncommitted work too.

## Conventions

- Keep changes green: per-package test suites must pass before commit.
- `ruff check` and `ruff format --check` must pass before commit.
- Comments and commit messages in Korean; identifiers and docstrings in English.
  Test *function* docstrings are the exception: they state why the test exists rather
  than describing an API, so they follow the comment rule and are written in Korean.
  Module and class docstrings stay English everywhere, tests included.
- Reference the design document as a bare `§N` (e.g. `(§11.4)`), matching the
  `gardevoir-be` skill.
- **`import re2`, never `import re`.** **`orjson`, never `json`.** Both are load-bearing —
  see the `gardevoir-be` skill.

## Testing principles

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
