# BUG-0014 — Can't draw an edge when a hidden edge already exists between the nodes

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0014                                                     |
| Reported  | 2026-07-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend / navigation                                        |
| Fixed in  | build 8414                                                   |
| Commit    | `f3804d7de` (reveal) · scope-aware + create fix `5df676c99` |

---

## Symptom

In the navigation editor, drawing a connection between two nodes silently failed with a
console warning `[@useNavigationEditor:onConnect] Edge already exists between these nodes` —
even though **no edge was visible** between them on the canvas. The user was stuck: they
couldn't see the edge, couldn't select it, and couldn't create it. Observed on `example_tv`
trying to link `home_apps → home_replay` and other `home_*` siblings.

## Root cause

`onConnect` (`frontend/src/hooks/navigation/useNavigationEditor.ts`) rejects a new
connection when **any** edge already exists between the two nodes (either direction), and it
scans the raw `navigation.edges` — which includes edges that are **not visible in the
current view**, in particular `hidden_in_base = true` edges (orphaned or variant-only edges).
So a hidden edge with no way to reach it on the canvas blocked the connect with a dead-end
warning and no recourse.

These orphans arise from earlier variant delete/add behavior (an edge created while a
variant was selected is born `hidden_in_base=true`; if its owning variant is later
deleted/renamed it is stranded, invisible in Base yet still present in the edge list).

## Fix

Landed in three steps (see commits below):

1. **Initial reveal** (`useNavigationEditor.ts`) — `onConnect` revealed a `hidden_in_base=true`
   existing edge instead of dead-ending. But it un-hid on **any** connect regardless of scope,
   which could promote a variant-only edge into Base.
2. **Scope-aware reveal** (`NavigationEditor.tsx:wrappedOnConnect`, hook reverted to a plain
   visible-duplicate block) — the reveal now respects the viewing scope:
   - **Base** → un-hide only a **true orphan** (no variant shows it); if a variant shows/owns
     it, **warn** instead of silently promoting it to Base.
   - **Variant X** → reveal it **within X** (write the `{enabled:true}` marker), leaving
     `hidden_in_base` untouched so Base is never affected.
   - **Composition** → no-op with a hint to pick a single scope.
   Correctness hinges on `composeEdgeOverrides` (the additive model driving the canvas): a
   `hidden_in_base` edge is visible on a variant only if that variant **enables** it, so
   "true orphan" = hidden in Base **and** enabled by no variant.
3. **Variant edge-create persists the enable** (`NavigationEditor.tsx:wrappedOnConnect`) —
   drawing an edge while a variant is selected marks it `hidden_in_base=true` and **must**
   write `{enabled:true}` into that variant's `edge_overrides`, or `composeEdgeOverrides`
   hides it (invisible orphan; "success" toast for an edge that never appears). The create now
   does **one merged** `updateVariantOverrides` write (no N-PUT clobber) and **gates the
   success toast** on it persisting — a failed enable surfaces an error instead of a silent
   orphan. The edge is marked `hidden_in_base=true` **synchronously** (drives the "v" badge and
   is captured if the user saves immediately); an intermediate attempt to defer that mark until
   after the async enable was reverted because saving in that window persisted the edge as a
   **base** edge (no `v` badge, visible in Base).

Also removed the composition read-only preview banner in `NavigationEditor.tsx` (kept only the
override-conflict warning).

Related: [BUG-0013](BUG-0013-2026-07-23-variant-edge-direction-delete-hits-base.md).

## Verification

1. **Base orphan reveal** — an edge `hidden_in_base=true` that no variant enables. In Base,
   draw between its two nodes → it appears (no dead-end), selected + unsaved; Save persists
   `hidden_in_base=false`. If a variant DID enable it, Base warns instead.
2. **Variant reveal** — same edge disabled on variant X. In X, draw between the nodes → it
   becomes visible on X (`{enabled:true}` written), Base unchanged.
3. **Variant create** — in variant X, draw a new edge between two visible nodes → it appears
   on X and stays hidden in Base; DB shows the edge `hidden_in_base=true` **and**
   `X.edge_overrides[<id>] = {enabled:true}`. If the enable write fails, an error toast shows
   (no false success).
4. **Visible duplicate** — draw between two nodes with a visible edge → still blocked.
