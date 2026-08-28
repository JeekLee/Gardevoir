# gardevoir

An OpenAI-compatible reverse proxy that puts guardrails in front of LLM apps —
including **agent action control**, not just text moderation.

> Current status: the gateway, console, and deployment stack are implemented and
> running in a self-hosted deployment. This is working software, not a claim of
> production readiness; the current limits are listed below.

## What it is

Point an application at gardevoir instead of its provider, and published policies
apply without changing the application's guardrail logic:

```diff
- client = OpenAI(base_url="https://api.openai.com/v1")
+ client = OpenAI(base_url="http://gardevoir:8080/v1")
```

The proxy inspects the four places where data or an action crosses the LLM boundary:

```text
request  ├─ user message      →  ① input
         └─ tool result       →  ② untrusted data

response ├─ content           →  ③ output
         └─ tool calls        →  ④ action authorization
```

Text is graded by provenance: application `system` messages are trusted, user
messages are semi-trusted, and tool results are untrusted. A policy names which
source it reads and at which checkpoint, so an output or tool-call rule can condition
on what arrived untrusted earlier in the same request. Tool policies select calls by
name and read into their argument values before an action reaches the application.

## What works today

- **Four inspection checkpoints.** Input, tool-result history, output, and complete
  tool-call JSON are inspected. Tool calls are buffered until their arguments are
  complete, so the proxy can block an injected action before the application executes
  it.
- **A two-tier decision path.** Published node graphs compile into flat in-memory
  programs. Deterministic RE2 checks short-circuit to allow or block; an unresolved
  input model check can be sent to Shieldstral. The deployed model path accepts text
  and supported image inputs.
- **Graph authoring and immutable releases.** The Next.js console uses React Flow to
  author Extract, Transform, Check, and Verdict nodes across the four checkpoints.
  Drafts can be saved, published as immutable numbered versions, and inspected later.
- **Span-based masking.** Regex checks return exact spans, allowing matched text to be
  replaced before it is returned. Model checks currently produce a verdict, not spans,
  so they can block or allow but cannot drive masking.
- **Audit and observability.** Proxy requests emit ClickHouse audit events with the
  applied guardrail version, checkpoint, action, tier, fired checks, and latency.
  The admin console exposes action trends, checkpoint distribution, and the most
  frequently fired nodes; request and response bodies are restricted to the detail
  view.
- **A real-request Playground.** Operators can select a published guardrail version
  and upstream model, run enforce or dry-run requests, and inspect the checkpoint
  flow, fired nodes, upstream response, and raw-to-applied masking diff.

The action-control path is designed for indirect prompt injection. At the tool-call
checkpoint a policy reads two things at once: the untrusted tool-result text that
arrived earlier in the same request, and the complete call the model is now proposing.
Blocking is a conjunction over both, so an instruction planted in retrieved data cannot
become an executed action. This covers the attack path that ordinary input/output
moderation does not see.

## Console tour

These screenshots use synthetic demo policies, identifiers, events, and upstream
labels. They contain no production credentials or personal data.

![A published tool-call guardrail in the React Flow editor](docs/assets/guardrail-editor.png)

The editor builds checkpoint-specific policy graphs from extraction, check, transform,
and verdict nodes.

![The Playground showing a masked synthetic identifier and raw-to-applied diff](docs/assets/playground-masking.png)

The Playground shows the four-checkpoint flow, fired node chain, masking diff, and final
upstream response for a real request.

![The Playground blocking a tool call induced by an untrusted tool result](docs/assets/playground-injection-blocked.png)

An indirect-injection scenario reaches the tool-call checkpoint and is blocked before
the proposed action is returned to the application.

![Audit trends, fired-node ranking, checkpoint distribution, and event records](docs/assets/audit-observability.png)

Audit filters drive the summary, decision trend, fired-node ranking, checkpoint chart,
and event table from the same ClickHouse records.

## Measured latency

These are local warm-path measurements on the target aarch64 hardware, not service
level objectives:

| Path | Measured p50 | Sample |
|---|---:|---|
| Compiled deterministic tier | **0.26 ms** | 252 instructions across two checkpoints |
| Shieldstral verdict | **42.5 ms** | 27-character Korean input, 7 runs after warm-up |
| Shieldstral verdict | **53.4 ms** | approximately 1,400 characters, 7 runs after warm-up |

The rule path is compiled once at publish time and executes without a per-request graph
walk. The model figures measure one-token classification; they do not describe a span
localizer or a remote judge. Measurement details and constraints are recorded in the
[design document](docs/superpowers/specs/2026-08-12-gardevoir-design.md) and the
[guardrail landscape survey](docs/research/2026-08-28-guardrail-landscape-survey.md).

## Stack

- **Gateway:** Python 3.14, FastAPI, uvicorn, httpx, orjson, and google-re2
- **Mutable state:** PostgreSQL with async SQLAlchemy 2.0 and Alembic
- **Sessions:** Redis for rotating refresh sessions only; it is not on the guardrail
  evaluation path
- **Audit:** ClickHouse with a separate Alembic lineage and asynchronous batched writes
- **Console:** Next.js, React, React Flow, TanStack Query, and Recharts
- **Model tier:** Shieldstral 1.0 3B behind an OpenAI-compatible vLLM endpoint
- **Deployment:** Docker Compose, with gateway and console images plus PostgreSQL,
  Redis, and ClickHouse

The gateway is a modular monolith: authoring, publishing, proxying, identity, provider
routing, and audit access share one backend service. PostgreSQL owns mutable state;
ClickHouse owns append-only analytical events.

## Quick start

The complete stack uses a checked-in localhost template plus an ignored machine-local
override. Create the override and replace the development JWT secret and bootstrap
credentials before starting the stack:

```bash
mkdir -p infra/envs/local
cp infra/envs/example/compose.env infra/envs/local/compose.env
${EDITOR:-vi} infra/envs/local/compose.env
```

Both `--env-file` arguments are required. The second file overrides the template with
machine-local browser URLs, CORS origins, ports, credentials, and optional model-tier
settings:

```bash
docker compose \
  --env-file infra/envs/example/compose.env \
  --env-file infra/envs/local/compose.env \
  -f infra/docker-compose/gardevoir.yml up -d --build
```

The migration service upgrades the independent PostgreSQL and ClickHouse Alembic
lineages before the gateway starts. Open the console at the port selected by
`CONSOLE_HTTP_PORT`; the gateway health endpoint is `/healthz` on `GATEWAY_HTTP_PORT`.
For dependency-only startup, bootstrap account details, health checks, and environment
notes, see [`infra/README.md`](infra/README.md).

For backend development, sync the entire uv workspace; a bare `uv sync` removes the
workspace members:

```bash
cd backend
uv sync --all-packages
```

## Current limits

- **Human approval is not implemented.** Action policies can allow, mask, or block,
  but there is no durable approval request, replay protection, expiry, or application
  approval UX yet.
- **There is no Retrieval rail.** gardevoir can inspect retrieval content when it is
  exposed as a tool result, but it cannot see an application's internal document
  chunks, ranking, ACL metadata, or source trust before prompt assembly.
- **There is no Dialog or workflow rail.** Taint and action checks constrain an
  individual tool call; they do not enforce a multi-turn state machine, prerequisite
  steps, or dual-control workflow.
- **There is no maintained full-system test suite today.** Attack regression coverage
  is incomplete for jailbreak variants, multilingual bypasses, SSE leakage, and
  over-refusal. Real-process smoke verification remains the primary system check.
- **Model evidence is deliberately narrow.** The latency figures above are small local
  measurements, and the current model verdict does not localize spans. Broader Korean
  quality and adversarial evaluation remain to be built.

The [landscape survey](docs/research/2026-08-28-guardrail-landscape-survey.md) compares
these gaps with NeMo Guardrails, Guardrails AI, OpenAI Guardrails, Presidio, Promptfoo,
and garak without presenting unimplemented work as a feature.

## Design and operations

The [design document](docs/superpowers/specs/2026-08-12-gardevoir-design.md) records the
architecture, wire contract, measurements, and explicit trade-offs. Operational setup
and the commands used by the deployed stack live in [`infra/README.md`](infra/README.md).

## License

Not yet decided.
