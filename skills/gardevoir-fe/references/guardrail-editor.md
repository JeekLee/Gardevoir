# Guardrail editor

Read this reference before changing the React Flow editor, graph types or mapping, node catalog,
validation, draft persistence, publish/version flows, or graph-editor tests.

## Read the live domain contract

The source of truth is the current backend implementation, not a copied TypeScript enum:

```text
backend/gateway/src/gateway/guardrail/domain/models/guardrail.py
backend/gateway/src/gateway/guardrail/domain/exceptions/guardrail_error.py
backend/gateway/src/gateway/guardrail/definition/application/command/guardrail_command.py
backend/gateway/src/gateway/guardrail/definition/application/result/guardrail_result.py
backend/gateway/src/gateway/guardrail/definition/presentation/guardrail_router.py
```

Read `NodeType`, `Decision`, `VerdictAction`, `NODE_ARITY`, per-node validators, serialized parsing,
and error details together. A new backend node kind is not complete in the console until the editor
can create, configure, connect, validate, explain, and round-trip it.

The backend remains authoritative. Client validation exists for faster feedback, not as a second
definition of what can be published.

## Keep wire graph and editor graph separate

The wire graph is intentionally small: domain nodes plus directed edges. React Flow needs different
field names and extra presentation state.

```text
Gateway node          { id, type, config }
Gateway edge          { src, dst }

React Flow node       { id, type, data, position, ...editor fields }
React Flow edge       { id, source, target, ...editor fields }
```

Create one named conversion boundary, for example:

```text
toEditorGraph(guardrailGraph, layout?)
toGuardrailGraph(editorGraph)
```

Rules:

- Map `src`/`dst` to `source`/`target` explicitly.
- Do not use `ReactFlowJsonObject` as an API DTO.
- Do not put viewport, selection, measured dimensions, handles, component functions, or React Flow
  internals into the domain graph.
- Do not put React Flow `Node`/`Edge` types in the `guardrail` entity's network model.
- Preserve unknown-but-supported domain `config` fields through an edit when the UI does not change
  them. Dropping fields during a frontend rollout corrupts policies authored by a newer backend.
- Reject a node type the editor truly cannot represent with a clear read-only/upgrade state; never
  silently coerce it to a generic node and save a changed payload.

Round-trip tests should assert domain meaning, not byte-for-byte editor JSON. Editor-only state may
change; IDs, types, configs, edges, and declared ordering may not.

## Stable identity and declared order

Node IDs are domain identity. Generate once when the author creates a node and preserve the ID
through drag, edit, save, refetch, and publish. Never derive it from array position, label, or canvas
coordinates.

Array order is a deterministic tie-breaker in the compiler and affects stable instruction/audit
ordering when several nodes are otherwise independent.

- Preserve server node and edge order when loading and editing.
- Append new nodes/edges deterministically.
- Deleting an item removes it without re-sorting the rest.
- Never sort by canvas coordinates, display label, localized text, object-key order, or a `Set`.
- If the UI intentionally offers execution priority in the future, model that as an explicit domain
  contract rather than encoding it accidentally through drag position.

## One working graph

Use one controlled editor working state for the unsaved graph. React Flow change handlers update
that state. Derive inspector forms, selected-node data, minimap data, and save payloads from it.

Do not mirror the whole graph into a form library or global store. A node inspector may hold
short-lived invalid text while the user types, but commit it back through one explicit editor
operation and make ownership visible.

Track these separately:

- **server baseline** — the canonical draft returned by the last successful fetch/save;
- **working graph** — the user's current domain edits;
- **layout/viewport** — presentation state, only if the persistence contract supports it;
- **selection/panels** — local transient UI state;
- **dirty** — derived by revision/change tracking, not set independently in several components.

Do not overwrite a dirty working graph merely because TanStack Query refetched in the background.
Prompt for conflict/reload, or hold refetch application until the user resolves it.

## Layout persistence is a contract decision

The current backend serialized graph keeps nodes and edges but not React Flow `position` or
`viewport`. React Flow cannot restore a deliberately arranged canvas without more data.

Before promising persistent layout, decide and document the contract. Recommended shape: separate
UI metadata on the authored graph, keyed by stable node ID, with optional viewport. The compiler
must ignore it and the backend must round-trip it.

Do not:

- smuggle `{ x, y }` into a node's rule `config`;
- infer permanent positions by sorting nodes;
- persist only in `localStorage` and imply another browser/user will see the same layout;
- add an automatic layout on every load that destroys the author's arrangement;
- silently discard layout data on save because the backend parser ignores unknown fields.

If the contract is still absent, an explicitly temporary auto-layout is acceptable for a prototype,
but disclose that reload does not preserve layout and keep it out of the production acceptance
criteria.

## Validation without a second truth

Validation has levels:

1. **Immediate editor affordances** — required fields, allowed connections, obvious arity, duplicate
   local IDs, and field input shape.
2. **Gateway draft validation** — complete serialized structure, node configuration, RE2 syntax,
   dangling edges, cycles, arity, and domain rules.
3. **Publish** — persists an immutable version and compiles it; success means the returned version is
   usable when the response arrives.

Local connection prevention improves UX, but save must still handle backend graph errors. A race,
unsupported node type, or stale client can bypass client checks.

### Regex is load-bearing

Never compile or execute an author-supplied policy pattern with JavaScript `RegExp`:

- JavaScript regex is not the gateway's RE2 dialect.
- Backtracking patterns can freeze the browser, recreating the ReDoS class the backend deliberately
  removed.
- A pattern accepted by one engine may fail in the other.

For instant syntax feedback, adopt a vetted RE2-compatible browser implementation or add a narrow
backend validation contract. Otherwise validate on Save and explain the timing. Do not debounce a
mutating draft PUT on every keystroke and call it validation without also settling concurrency,
dirty-state, and failure semantics.

Map structured backend details to the canvas. When details include a node ID, select it, fit/focus it
without disorienting the user, open the inspector, and show the reason next to the relevant control
when possible. Keep a graph-level summary for cycle/dangling-edge errors involving several nodes.

## Save, publish, and versions

The draft and numbered versions are different resources.

### Save

1. Convert the working editor graph through the explicit wire mapper.
2. Send the whole draft expected by the current PUT contract.
3. On success, treat the returned draft as canonical and advance the baseline without losing
   separately owned layout/selection.
4. On failure, preserve the working graph and surface structured errors. Never reset to stale query
   data.

Until the backend supports a revision/ETag precondition, prefer explicit Save and warn on dirty
navigation. Autosave can overwrite another tab or user's draft with no conflict signal.

### Publish

1. If dirty, save and await success.
2. Only then call publish.
3. Use the returned numbered version as the success result; do not predict the next number.
4. Refresh latest detail, version data, summaries, and relevant list metadata.
5. Keep the draft editable unless the backend contract says otherwise.

Never run save and publish concurrently. Never show “published” on button click before the server
returns. A 200 publish means commit and immediate recompilation are already complete on the gateway;
the UI should not add a speculative delay or poll to mask a broken backend boundary.

### Version views

Numbered versions are read-only. Make the state visually and semantically explicit, disable editing
operations, and offer a deliberate navigation/restore flow only when a real backend contract exists.
Do not implement “rollback” by editing a numbered version or by silently overwriting the draft.

## React Flow boundary and performance

- Keep `nodeTypes` and `edgeTypes` stable and outside render functions.
- Keep callbacks stable where React Flow identity affects rendering.
- Subscribe to narrow editor state; avoid rerendering the full canvas for a toolbar hover or an
  unrelated query change.
- Memoize custom node components after measuring the relevant rerender path.
- The canvas parent needs explicit dimensions.
- Load the heavy editor only on routes that need it. Do not export React Flow from a broad shared
  barrel.
- Do not optimize by making the editor uncontrolled if doing so creates a second hidden graph owner.

Use React Flow's supported connection/selection APIs instead of reaching into its internal store.
Wrap library-specific behavior inside the editor slice so a library upgrade does not shake every
page.

## Accessibility and safe editing

A graph canvas is not a complete authoring interface by itself.

- Every essential operation needs a semantic control and accessible name.
- Node configuration must be reachable in an inspector or list without precision dragging.
- Provide keyboard deletion/connection alternatives supported by the chosen interaction design.
- Announce save, publish, validation, and one-time destructive results through an appropriate live
  region or focused status.
- Destructive node deletion must be undoable or explicitly confirmed in proportion to the damage.
- Do not encode node type or verdict only by color.
- Preserve focus when opening an inspector and return it sensibly when the inspector closes.

## Observable verification

### Pure boundary tests

- wire → editor → wire preserves IDs, types, configs, edges, and order;
- `src`/`dst` maps to `source`/`target` and back;
- editor-only state never reaches the API payload;
- unknown supported config survives an unrelated edit;
- a node type the UI cannot edit is not silently corrupted.

### Interaction tests

- add/configure/connect/delete changes the one working graph;
- invalid connections are prevented locally and backend errors still render;
- backend node errors focus the correct node/field;
- a failed save keeps user edits;
- dirty navigation is guarded;
- publish waits for save and stops if save fails;
- numbered versions are read-only;
- essential operations are keyboard accessible.

### Real browser path

Against a running gateway and dependencies: log in as an authorized user, create a guardrail, add and
connect nodes, save, provoke a structured invalid-node/graph response, correct it, publish, reload,
and verify the same graph and numbered version. Include layout persistence only after its contract is
implemented.

Do not test FSD by reading source text. Let the architectural linter enforce imports, and let these
tests prove behavior.
