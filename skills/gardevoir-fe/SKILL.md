---
name: gardevoir-fe
description: Use when creating or modifying the gardevoir console frontend — Next.js App Router setup, Feature-Sliced Design boundaries, authentication and API access, TanStack Query state, React Flow guardrail authoring, console pages, or frontend verification. Not for backend-only changes.
---

# gardevoir frontend architecture (gardevoir-fe)

## Overview

gardevoir's console is a **Next.js App Router** application in a **pnpm workspace**. It is the
control-plane UI for guardrail authoring, publishing and version inspection, user and API-key
management, and audit analysis. React Flow renders the authored guardrail DAG; TanStack Query
owns remote server state.

Follow **Feature-Sliced Design (FSD)** as an architectural boundary, not as a directory checklist.
Create only layers and slices that have a real responsibility.

Before changing frontend code, read:

1. Root `AGENTS.md` for repository-wide conventions.
2. `docs/superpowers/specs/2026-08-12-gardevoir-design.md`, especially §5–§7, §10, §12–§15.
3. The current frontend manifests and source tree, if they exist.
4. The backend router plus its command/result DTOs for every endpoint being consumed. The current
   implementation is authoritative for the wire shape; older phase plans may be stale.

If a frontend task requires changing a backend contract, also read `skills/gardevoir-be/SKILL.md`
before editing backend code.

## When to use

- Creating or changing `frontend/`, the console app, or a frontend workspace package.
- Placing code in FSD layers/slices or reviewing dependency direction.
- Adding a console route, page, widget, feature, entity model, query, or mutation.
- Implementing session handling, backend access, React Flow authoring, or audit dashboards.
- Choosing frontend verification proportional to the behavior being changed.

Do not use it for backend-only work or for the OpenAI-compatible proxy request path.

## Start by inspecting, not scaffolding

The frontend may not exist yet. Do not assume dependencies, package names, scripts, styling, test
tools, or generated clients from this skill alone.

- If the console exists, preserve its established stack and refine it in place.
- If it does not exist, create `frontend/` as the pnpm workspace root and
  `frontend/apps/console/` as the Next.js app. Do not add a reusable package until two real
  consumers justify it.
- Check current stable versions and official migration guidance before adding Next.js, React,
  TanStack Query, React Flow, or architectural-lint dependencies. Do not copy versions from the
  backend design document.
- Use TypeScript in strict mode. Treat unchecked casts and `any` at network or graph boundaries as
  missing validation, not as a convenient escape hatch.

## Next.js and FSD layout

Next.js reserves `app` and `pages`, which conflict with FSD layer names. Use the official FSD
integration shape: keep the Next.js router at the app root and prefix the two conflicting FSD
layers.

```text
frontend/
├── pnpm-workspace.yaml
└── apps/
    └── console/
        ├── app/                       Next.js routes only
        │   ├── (auth)/
        │   ├── (console)/
        │   └── api/                   thin Route Handler adapters, when needed
        ├── src/
        │   ├── _app/                  FSD App: providers, global styles, app-wide wiring
        │   ├── _pages/                FSD Pages: complete route screens
        │   ├── widgets/               reusable or independently meaningful page blocks
        │   ├── features/              reusable user interactions
        │   ├── entities/              gardevoir business concepts
        │   └── shared/                UI kit, transport, config, focused libraries
        └── public/
```

`app/**/page.tsx` and the other Next.js special files are thin adapters. A page normally re-exports
or renders its `_pages/<slice>` entry. Route adapters may translate framework-only props, but do
not accumulate queries, forms, mutations, or business rules.

Use route groups for layout/experience boundaries, never as authorization vocabulary. The backend
has no `/admin/**` resource tree; role is a caller property, not a URL property.

## Dependency direction (strict)

Code may import only from layers below it:

```text
_app → _pages → widgets → features → entities → shared
```

- **`shared`** — framework adapters, backend transport, configuration, design tokens, and small
  focused libraries. It contains no gardevoir use case or entity business rule.
- **`entities`** — business nouns visible to users: for example `user`, `api-key`, `guardrail`,
  or `audit-event`. A slice may own its wire/model types, query options, and small reusable entity
  UI.
- **`features`** — meaningful, reusable user actions such as login, publish guardrail, revoke API
  key, or change password. Not every button or form is a feature; page-local behavior may remain in
  the page slice.
- **`widgets`** — self-contained, meaningful UI blocks. Use it when the block is reused or a page
  contains several independently substantial blocks. A one-page-only block that is most of the
  page may stay in that page slice.
- **`_pages`** — complete screens and page-specific composition. Page-local loading, empty, and
  error states belong here.
- **`_app`** — providers, global styles, route-handler implementations, session wiring, and other
  application-wide composition.

Do not create the deprecated `processes` layer or custom FSD layers.

Slices on the same layer do not import one another. If two same-layer slices repeatedly need each
other, move their collaboration upward or reconsider the slice boundary. Use FSD `@x` cross-APIs
only for an unavoidable entity relationship, make the consumer explicit, and keep them rare.

## Slices, segments, and public APIs

- Name slices by business purpose in kebab-case.
- Use purpose-bearing segments such as `ui`, `model`, `api`, `lib`, and `config`; create only those
  a slice needs.
- Do not create dumping grounds named `components`, `hooks`, `helpers`, `types`, or `utils`.
- Cross-slice imports use the slice's public API and an absolute alias. Expose only the contract;
  never `export *`.
- Imports inside one slice are relative and use the real file path, not the slice barrel. This
  avoids barrel-induced cycles.
- `shared/ui` and `shared/lib` expose per-component or per-library entrypoints such as
  `@/shared/ui/button`; do not create a root barrel that pulls the whole design system or React
  Flow into every consumer.
- When one slice contains both client-safe and server-only modules, separate its public API with
  `index.ts` and `index.server.ts`. Mark secret-bearing or server transport modules with
  `server-only`. Do not create environment entrypoints mechanically when there is no boundary.

Use an FSD-aware architectural linter (currently Steiger) when scaffolding the console, and run it
in CI. The linter supports the rule; it does not replace code review of whether a slice name tells
the truth.

## Server and Client Components

App Router components are Server Components by default. Keep them that way unless the component
needs state, effects, event handlers, context, or browser-only APIs.

- Put `'use client'` at the smallest useful public boundary. Everything imported below that file
  enters the client module graph.
- React Flow's canvas is a client island. The surrounding page, title, authorization redirect, and
  server prefetch do not need to become client code with it.
- Props crossing from Server to Client Components must be serializable. Never pass service
  instances, callbacks, secrets, or library objects across that boundary.
- Render providers as deep as their consumers permit. A Query provider does not justify turning a
  static root layout into a broad client boundary.
- Do not call a Next.js Route Handler from a Server Component. Server code calls the gateway
  directly through the server transport; browser code uses the same-origin BFF only where it is
  needed.

## State has one owner

- **URL state**: shareable filters, pagination, selected audit range, and other navigation state.
- **TanStack Query**: gateway-owned remote state and mutation lifecycle.
- **local component/slice state**: transient presentation state.
- **editor working state**: the unsaved guardrail draft shown on the canvas.

Do not copy query data into a global store. A form/editor may take a deliberate editable snapshot,
but it must track a server baseline and dirty state explicitly. Do not keep the same graph in a
React Flow state, a form store, a query cache, and another global store.

Query keys and query options live with the entity/feature/page that owns the request. Mutations
live with the user action. Invalidate or update the narrow affected keys after success; never clear
the entire cache to avoid reasoning about ownership.

Read [references/auth-and-api.md](references/auth-and-api.md) before changing authentication,
Route Handlers, the gateway client, DTOs, TanStack Query configuration, error handling, user
management, or API-key management.

## Product invariants the UI must preserve

- Published guardrail versions are immutable. Editing always targets `draft`; publishing creates a
  numbered version (§6).
- Save then publish is sequential. A failed or dirty save must never be followed by publish.
- Backend authorization is authoritative. Hiding controls and server-side redirects improve UX but
  do not replace the role-protected endpoint.
- API keys are secrets. A newly issued raw key appears once; lists show only a preview. Never put
  the raw key in persistent browser storage, logs, analytics, URLs, or a long-lived query cache.
- Password change invalidates the user's sessions. On success, clear the console session and return
  to login instead of pretending the old session still works.
- Errors branch on stable `code`, not human `message`. Preserve `requestId` so an operator can
  correlate a UI failure with gateway logs.
- Audit filters and dashboards query a backend API. The browser never connects to ClickHouse and
  the console does not invent an audit endpoint that the gateway does not expose.
- The UI may provide earlier validation, but the gateway remains authoritative for graph, role,
  expiry, and state-transition rules.

Read [references/guardrail-editor.md](references/guardrail-editor.md) before changing the React
Flow editor, graph DTO mapping, node catalog, validation, draft persistence, publishing, or version
views.

## API boundaries

The backend uses camelCase on the wire and a single error shape:

```text
{ code, message, details?, requestId? }
```

Model the actual wire contract once. Do not create transport DTO → API DTO → entity DTO → view DTO
stacks when the shapes are identical. Translate only where semantics differ — notably backend
`src`/`dst` edges versus React Flow `source`/`target`, or a string timestamp versus a rendered date.

Prefer types generated from the current OpenAPI contract when the repository establishes a
repeatable generation path. Generated types do not validate runtime data by themselves. If no
generation path exists, keep narrow hand-written DTOs beside the request owner and verify them
against the router's command/result models.

Never parse a `204 No Content` response as JSON. Never expose server environment variables or
tokens through `NEXT_PUBLIC_*`; only public browser configuration belongs there.

## Guardrail authoring is not generic CRUD

The authored graph is both a domain definition and the input to publish-time compilation. Preserve
node IDs, edge endpoints, and declared array order. The backend uses declaration order as a stable
tie-breaker; sorting nodes by canvas position or regenerating IDs can change execution/audit order
even when the visible graph looks equivalent.

React Flow types are editor types, not the gateway wire contract. Keep one explicit mapper at the
editor boundary and test its round trip. Never leak `@xyflow/react` objects into entity API types or
send its whole JSON object to the backend.

## Decision gates — do not decide silently

Stop and surface these choices when the task reaches them:

1. **Console authentication transport.** Recommended v1: same-origin Next.js BFF with access and
   rotating refresh tokens in `HttpOnly`, `Secure`, `SameSite` cookies. Browser token storage is
   simpler but exposes bearer tokens to JavaScript and the gateway currently has no browser CORS
   contract. See the auth reference.
2. **Canvas layout persistence.** The current guardrail graph contract persists domain nodes and
   edges but not React Flow positions or viewport. Recommended: extend the authored graph contract
   with separate UI layout metadata that the compiler ignores. Do not smuggle coordinates into
   node `config` or imply that a layout will survive reload when it cannot.
3. **Draft concurrency and autosave.** The current draft update has no revision/ETag precondition.
   Recommended v1: explicit Save plus dirty-navigation protection; add an optimistic-concurrency
   contract before autosave or multi-editor support.
4. **RE2-compatible instant regex validation.** JavaScript `RegExp` is the wrong dialect and can
   reintroduce ReDoS. Use a vetted RE2-compatible client implementation or a backend validation
   endpoint; otherwise validate on draft save and say so in the UX.
5. **Design system and browser-test stack.** Follow an existing choice. On a new console, select
   these explicitly before growing `shared/ui` or CI; this skill does not silently choose a visual
   library or test runner.
6. **Planned UI without a backend read contract.** Audit dashboards and the shared-node library are
   in the product design, but the current gateway has no presentation API for them. Define filters,
   pagination/aggregation, authorization, and resource DTOs before implementing those screens; do
   not make a client mock the de facto contract.

Record a settled product/contract decision in the design document or an implementation plan, not
only in frontend code.

## Verification

Use the scripts declared by the workspace. For a newly scaffolded console, provide stable scripts
for at least architecture checks, lint, typecheck, tests, and production build. From the repository
root, the intended shape is:

```bash
pnpm --dir frontend --filter ./apps/console architecture
pnpm --dir frontend --filter ./apps/console lint
pnpm --dir frontend --filter ./apps/console typecheck
pnpm --dir frontend --filter ./apps/console test
pnpm --dir frontend --filter ./apps/console build
```

Do not invent a script name when working in an existing app; inspect `package.json` first.

Verify behavior through the narrowest real boundary:

- Pure mapper/schema behavior with unit tests.
- Component interaction and accessible output with component tests.
- Login/session rotation, route protection, create/edit/save/publish/reload, one-time API-key reveal,
  and important dashboard filters in a real browser against running services.

Tests must be capable of failing when visible behavior breaks. Do not assert source text, folder
names, class names, or that another test exists. Architecture belongs to the architectural linter;
behavior belongs to executable tests.

Run a real production build even when unit tests pass. It catches server/client graph leaks,
non-serializable props, route export mistakes, and environment-variable errors that isolated tests
do not.

## Repository conventions

- Use pnpm from the `frontend/` workspace root; do not mix npm or yarn lockfiles.
- Identifiers and API-facing types are English. Code comments follow the repository rule and are
  Korean; add a comment only for a decision or consequence the code cannot express.
- Use accessible names and semantic controls. Canvas-only interactions require a keyboard/list or
  inspector path for the same essential operation.
- Keep secrets, request bodies, tokens, and raw guardrail patterns out of client logging and
  analytics by default.

## Common mistakes

| Naive default | gardevoir frontend convention |
|---|---|
| Put all source under Next.js `app/` | root `app/` is a thin router; FSD code is under `src/` |
| Name FSD layers `app` and `pages` | `_app` and `_pages` avoid Next.js conflicts |
| Every form/button becomes a feature | extract only meaningful reusable interactions |
| Import another feature directly | compose siblings in widgets/pages or redraw the slice |
| Root `shared/ui/index.ts` barrel | per-component public APIs to protect bundles |
| Mark the page `'use client'` for React Flow | isolate the interactive editor client boundary |
| Put bearer tokens in `localStorage` | same-origin BFF + HttpOnly cookie session by default |
| Fetch a Route Handler from a Server Component | call the gateway directly on the server |
| Mirror query results into a global store | TanStack Query owns remote state |
| Send `ReactFlowJsonObject` as the draft | explicit wire/editor mapper |
| Sort nodes by position before saving | preserve declaration order and stable IDs |
| Validate policy regex with `new RegExp()` | RE2-compatible validation or gateway validation |
| Cache a newly issued raw API key | transient reveal, then reset and discard |
| Hide an admin button and call it authorization | backend role guard remains authoritative |
| Mock a dashboard API that does not exist | add the real backend contract first |

## Official references

- FSD with Next.js: <https://feature-sliced.design/docs/guides/tech/with-nextjs>
- FSD layers and import rule: <https://feature-sliced.design/docs/reference/layers>
- FSD public APIs: <https://feature-sliced.design/docs/reference/public-api>
- Next.js App Router structure: <https://nextjs.org/docs/app/getting-started/project-structure>
- Next.js Server and Client Components:
  <https://nextjs.org/docs/app/getting-started/server-and-client-components>
- TanStack Query advanced server rendering:
  <https://tanstack.com/query/latest/docs/framework/react/guides/advanced-ssr>
- React Flow documentation: <https://reactflow.dev/learn>
