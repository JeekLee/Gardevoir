# Authentication, gateway access, and remote state

Read this reference when changing console authentication, session cookies, Next.js Route Handlers,
gateway transport, TanStack Query, DTOs, errors, user management, or API-key management.

## Discover the contract first

Do not copy an endpoint inventory from an old implementation plan. For the use case in scope, read:

```text
backend/gateway/src/gateway/<context>/presentation/*_router.py
backend/gateway/src/gateway/<context>/application/command/*.py
backend/gateway/src/gateway/<context>/application/result/*.py
backend/shared_kernel/shared_kernel/api/
backend/shared_kernel/shared_kernel/exception/schema.py
```

When the gateway is runnable in debug mode, compare the code with `/openapi.json`. OpenAPI is a
generated view, not a substitute for understanding endpoint consequences such as refresh-token
rotation, logout idempotency, session invalidation, or one-time secret display.

The wire uses camelCase. Preserve the central error shape `{ code, message, details?, requestId? }`.
Branch on `code`; `message` is for people and can change.

## Recommended session boundary: a small BFF

Until the repository records a different decision, prefer this shape:

```text
Browser Client Component
    │ same-origin /api/*; no bearer token visible to JavaScript
    ▼
Next.js explicit Route Handler
    │ reads/rotates HttpOnly cookies and adds Authorization
    ▼
gardevoir /v1/*

Server Component
    │ reads the server cookie and calls the gateway directly
    └──────────────────────────────────────────────────────▶ gardevoir /v1/*
```

The BFF is a security/session adapter, not a second business backend.

- Keep the base gateway transport and error parsing in a focused server-only `shared/api` library.
- Keep cookie/session orchestration and Route Handler implementations in `_app`.
- Root `app/api/**/route.ts` files only export the relevant handler.
- Create explicit, allowlisted Route Handlers. Do not expose an arbitrary catch-all proxy that can
  turn the console into a credentialed tunnel to every gateway path.
- Do not call those Route Handlers from Server Components; that adds a needless HTTP hop.
- Do not replicate backend domain validation or authorization in the BFF.

If the team chooses browser-held bearer tokens instead, record the threat model, CORS contract,
storage choice, refresh behavior, and XSS consequences in the design document before implementation.
Never default to `localStorage` merely because it is easy.

## Cookie and refresh rules

Access and refresh tokens are credentials. If the BFF decision is adopted:

- Store them only in `HttpOnly` cookies, with `Secure` in deployed environments, `SameSite=Lax` or
  stricter, a narrow `Path` where practical, and explicit expiry.
- Keep token values out of React props, TanStack Query data, browser storage, logs, analytics,
  error messages, and rendered HTML.
- Validate the request origin for state-changing cookie-authenticated Route Handlers. SameSite is
  a useful boundary, not the whole CSRF design.
- Centralize 401 handling and refresh-token rotation. Do not give every query its own refresh loop.
- A refresh token rotates on every successful refresh; replace both cookies atomically in the
  response. The old refresh token is immediately invalid.
- Allow at most one bounded refresh-and-retry attempt for an API request. A repeated 401 clears the
  session and returns an authentication error; never recurse indefinitely.
- Coordinate concurrent refresh attempts inside one runtime. Do not assume an in-memory mutex
  coordinates multiple Next.js instances. If cross-instance races become observable, the session
  contract needs a stronger design rather than more retries.
- Logout is idempotent from the user's perspective. Clear local cookies even when the upstream
  token is already absent or invalid.
- Password change invalidates all of that user's refresh sessions. Clear the console session after
  success and redirect to login.

Keep protected, user-specific gateway fetches explicitly dynamic/uncached unless a cache is proven
safe for the full authorization key. Never let Next.js reuse one user's response for another.

## Authorization in the console

Use the authenticated user returned by the gateway as the UI principal.

- Protect console route groups on the server so an anonymous user does not receive the protected
  screen first and redirect after hydration.
- Admin-only navigation and controls may be omitted for non-admin users, but this is UX only.
- Treat backend 401/403 as authoritative. Do not turn an unexpected 403 into a hidden button or a
  generic empty state.
- There is no `/admin/**` resource namespace. Prefer resource routes such as `/users` and
  `/guardrails`; role is not a URL segment.

## Transport shape

Build one small transport primitive that:

- joins the configured gateway origin with an explicit path;
- adds authorization and request correlation headers at the server boundary;
- serializes the request body exactly once;
- distinguishes JSON, streaming responses, and `204 No Content`;
- parses the central error shape without losing `details` or `requestId`;
- applies a timeout/abort signal suitable for console operations;
- never logs credentials or entire payloads by default.

Do not turn HTTP into an all-purpose `request<T>()` that asserts any caller-supplied `T` without
runtime evidence. Generated OpenAPI types improve compile-time consistency but do not validate an
untrusted response at runtime.

Use ISO timestamps on the wire and convert only at the display/input boundary. Datetime inputs that
reach the gateway must include a timezone offset. Do not silently reinterpret a timezone-less value
as UTC.

## TanStack Query ownership

TanStack Query owns data whose source of truth is the gateway.

- Put query key factories and reusable query options beside the entity or use case that owns them.
- Include every result-changing parameter in the key: resource id/name, version, filters, page,
  time range, and mode.
- Do not include credentials in a query key.
- Use a fresh QueryClient per server request when doing RSC prefetch/dehydration. Reuse a single
  browser QueryClient for the browser lifetime.
- Give hydrated queries a nonzero `staleTime` when immediate client refetch would duplicate the
  server fetch.
- Prefetch only when it improves the route's loading behavior. An empty cache is not a defect, and
  not every client query needs hydration.
- Put `HydrationBoundary` near the subtree that consumes the data; do not make the entire root a
  client component.
- Keep URL-owned filters in the URL. The query reads them; it does not become their second owner.

After mutations, update or invalidate the narrow affected data:

```text
create user       → users list
update self       → current user + any visible user summary
create API key    → API-key list, but never cache the raw key
update/revoke key → that key/list
save draft        → draft detail + guardrail summary/list metadata
publish           → latest detail + versions + summary/list; draft remains a draft
```

Confirm the actual endpoints before implementing these examples.

Choose one mutation transport per use case. Do not implement the same operation once as a Server
Action and again as a browser Route Handler unless they intentionally serve two callers and share
the same underlying operation.

## API keys: one-time secret handling

An issued raw API key is intentionally returned only by the create response.

- Use a mutation, not a query.
- Render the raw key only in a dedicated one-time reveal state.
- Set BFF responses carrying the key to `Cache-Control: no-store`.
- Do not put it in a URL, toast description, global store, persistent form state, session replay,
  telemetry, console output, or query cache.
- Offer an explicit copy action with accessible confirmation. Do not copy automatically.
- When the reveal closes or navigation occurs, reset the mutation and discard the string.
- State clearly that the key cannot be shown again. The list uses `keyPreview`, never the raw key.

## Error handling

Normalize gateway failures once into a typed console error that preserves:

```text
httpStatus, code, message, details, requestId
```

- Known field errors render next to the field.
- Graph errors carrying a node id select/focus that node and render the reason in its inspector.
- 401 starts the one bounded refresh flow; repeated 401 returns to login.
- 403 renders a permission state, not a missing-resource state.
- 409 keeps the user's unsaved input and explains the state conflict.
- 422 maps structured field/node details without branching on English message text.
- Unknown errors show a safe fallback and the request ID when available.

Do not leak a raw backend traceback, token, request body, or secret-bearing details into a toast or
client logger.

## Verification scenarios

At minimum, cover the consequences that are easy to get wrong:

- anonymous protected-route navigation never renders protected data;
- login does not expose tokens to browser JavaScript;
- refresh rotates credentials and retries once;
- repeated refresh failure clears the session;
- logout clears cookies even when upstream logout is already idempotently complete;
- a role-restricted screen and operation handle 403 coherently;
- password change forces a new login;
- a created API key is visible once, copyable, uncached, and gone after dismissal;
- `204` mutations do not fail with a JSON parse error;
- an error request ID reaches the visible support/debug affordance.
