# gardevoir

An OpenAI-compatible reverse proxy that puts guardrails in front of LLM apps —
including **agent action control**, not just text moderation.

> Status: **design phase.** No implementation yet.
> See [the design document](docs/superpowers/specs/2026-08-12-gardevoir-design.md).

## What it is

Point your app at gardevoir instead of the provider, and policies apply with no
application code changes:

```diff
- client = OpenAI(base_url="https://api.openai.com/v1")
+ client = OpenAI(base_url="http://gardevoir:8080/v1")
```

## Why another guardrail framework

Text moderation is largely commoditized. The unsolved part in 2026 is what an
agent *does* — a tool result can carry injected instructions that turn a normal
agent into an exfiltration path, and nothing in the prompt or the model's reply
looks abnormal.

A proxy sees four distinct inspection points, and the last two are where the
differentiation is:

```
request  ├─ user message      →  ① input inspection
         └─ tool result       →  ② untrusted-data inspection   ★

response ├─ content           →  ③ output inspection
         └─ tool_calls        →  ④ action authorization        ★
```

Text is graded by provenance — app `system` is trusted, `user` is semi-trusted,
`tool` results are untrusted — and once untrusted data enters a conversation,
the agent's authority is reduced.

## Design highlights

- **Compile, don't interpret.** Guardrails are node graphs compiled to a linear
  instruction program at publish time. Measured: 0.62 ms/request compiled vs
  6.2 ms walking the graph per request.
- **Two tiers, short-circuiting.** Deterministic checks answer *block / allow /
  unknown*; only `unknown` reaches a model. Most requests never call a model.
- **RE2, not backtracking regex.** User-authored patterns cannot cause ReDoS.
  Measured: `(a+)+$` against 26 chars takes 8.9 s in Python `re`, 0.034 ms in
  `google-re2`. `re2.Set` matches 200 patterns in one pass, 510× faster than a
  loop.
- **Streaming hold-back.** Keep the last N tokens unflushed so short leak
  patterns are masked *before* the user sees them, instead of retracting after.
  A 32-token hold-back also buys ~640 ms — enough for a local guard model.
- **Approval is never inferred from conversation text.** It's the one gate that
  must stay deterministic; everything upstream of it is allowed to be
  probabilistic precisely because it is.

Full rationale, measurements, and stated limits are in the
[design document](docs/superpowers/specs/2026-08-12-gardevoir-design.md).

## Planned stack

FastAPI · google-re2 · orjson · httpx · PostgreSQL (jsonb) · React + React Flow · uv

## License

Not yet decided.
