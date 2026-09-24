# BUG-0152 — Picking "base" in Run Tests ran the device's `.env` variant instead, and navigation lost its path

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                    |
|-----------|--------------------------------------------------------------------------|
| ID        | BUG-0152                                                                 |
| Reported  | 2026-09-21                                                               |
| Status    | Fixed (pending deploy)                                                   |
| Severity  | High (silently ran a different navigation tree than the one selected)    |
| Area      | `frontend/src/utils/scriptArgsUtils.ts`, `backend_server/src/routes/server_script_routes.py`, `shared/src/lib/executors/script_executor.py` |
| Fixed in  | Unreleased                                                               |
| Regression of | none — latent since the initial snapshot, activated by config on 2026-09-15 |

---

## Symptom

`kpi_measurement` on **stb3** (vpt-pi1) failed every navigation, while the exact same navigation
driven by hand from the userinterface worked. The execution log's real error is 250 lines below the
first red line:

```
No path found from 'ENTRY' to 'home_replay' in unified graph
```

The Run Tests form had **`variant: base`** explicitly selected. The run did not use base.

## Cause

**Three** independent defects, one per hop. All reduce to the same thing: **an explicit "base" is
indistinguishable from "the caller said nothing"**, so the device's `.env` default wins a contest it
was never supposed to enter. Each hop is enough on its own — Run Tests dies at the first, an API
caller at the second, the scheduler at the third.

### 1. The frontend drops it before the request is even built — *this is the one Run Tests hit*

`RunTests.tsx:1249` resolves the value correctly: an explicit base comes back as `''`, with a comment
saying exactly that. One function later the signal is gone. `buildScriptArgs` skips every empty
value, and Run Tests sends **only** a `parameters` string — `useScript.ts:277` has no top-level
`variant` field at all:

```ts
const value = (valueOf(param.name) || '').trim();
if (!value) continue;                    // explicit base discarded here
```

For every other parameter that is right. For `variant` it is not: the caller has *already* resolved
the device's `DEVICE{i}_VARIANT` into that value, so anything still empty is a decision. The request
therefore looks identical to one that never mentioned a variant, and defects 2 and 3 never even get
the chance to be wrong.

### 2. The server drops the explicit base before it reaches argv

`server_script_routes.py` canonicalises the top-level `variant` field, and
`canonical_variant_name()` maps `''`, `'base'` **and an absent field** all to `None`:

```python
raw_variant   = data.get('variant')          # '' when the user picked base
variant_name  = canonical_variant_name(raw_variant)   # -> None
...
if variant_name and '--variant' not in parameters_normalized:   # never fires for base
    parameters_normalized += f" --variant {variant_name}"
```

So an API caller that *does* send `variant: ''` as a top-level field gets the same outcome: the
spawned script's argv carries no `--variant` at all.

### 3. The host-side executor only recognises an explicit choice if it came through argv

`script_executor.py` decides "explicit" by scanning `sys.argv` — reasonable, since argparse cannot
tell a passed value from a declared default — but it then destroys the one other signal available:

```python
variant_value = getattr(args, 'variant', None)
if isinstance(variant_value, str):
    variant_value = variant_value.strip() or None       # '' -> None, signal gone
if ... and not _flag_in_argv('--variant') and not variant_value and pref_variant:
    variant_value = pref_variant                         # DEVICE3_VARIANT wins
```

With no `--variant` in argv and the empty string flattened to `None`, the fallback fires and the run
adopts `DEVICE3_VARIANT`.

### Why it surfaced now, on this device

`DEVICE3_VARIANT=variant1` was added to vpt-pi1's `.env` on **2026-09-15**. Before that
`pref_variant` was empty and the fallback could never fire, so the dropped signal cost nothing. The
code is unchanged since the initial snapshot — this is a latent bug **activated by configuration**,
not a code regression.

`variant1`'s `edge_overrides` disable three edges, including `home_apps → home_replay`. Running the
base tree's plan against variant1's graph therefore leaves no route to `home_replay`, which is the
`No path found` above. The failure was specific to stb3 because it is the only device carrying a
`DEVICE*_VARIANT`.

## Fix

The contract, in the reporter's words: *the frontend suggests the favourite from `.env` by default,
but if the frontend sends something different it has to be honoured.*

**Frontend** — `variant` is the one parameter whose empty value is emitted rather than skipped, as
`--variant base`:

```ts
if (!value) {
  if (param.name === 'variant' && param.type !== 'positional') args.push('--variant base');
  continue;
}
```

Nothing else changes: when the user has *not* overridden, `getEffectiveParamValue` has already put
the device's `.env` variant in that value, so it is emitted as before and the default still applies.

**Server** — an explicitly supplied variant that canonicalises to nothing is still a choice, and is
forwarded as `--variant base`:

```python
variant_flag = variant_name or ('base' if raw_variant is not None else None)
```

`canonical_variant_name('base')` is `None` on the host side, so this runs base — while the literal
flag in argv tells the executor the caller decided, suppressing the `.env` fallback.

**Executor** — the same distinction is kept for callers that arrive without argv (scheduler, MCP,
direct invocation):

```python
explicit_base = isinstance(raw_arg_variant, str) and not raw_arg_variant.strip()
if ... and not variant_value and not explicit_base and pref_variant:
```

Run Tests, per selection (device default `variant1`):

| form shows | argv | variant used |
|---|---|---|
| `variant1` (preselected, untouched) | `--variant variant1` | `variant1` |
| `base` (user picked) | `--variant base` | base |
| `variant2` (user picked) | `--variant variant2` | `variant2` |

API caller, per `variant` field:

| caller sends | argv | variant used |
|---|---|---|
| field absent | *(nothing)* | `variant1` — the `.env` default, unchanged |
| `''` (explicit base) | `--variant base` | base |
| `'base'` | `--variant base` | base |
| `'variant2'` | `--variant variant2` | `variant2` |
| `['a','b']` | `--variant a+b` | `a+b` |

## Verification

The API table above was executed against the real `canonical_variant_name()` and both fixed Python
branches: absent still yields `variant1`, every explicit value (base included) is honoured.
`tsc --noEmit` clean for the frontend half.

The end-to-end re-run of `kpi_measurement` on stb3 with `base` selected is **pending deploy** — and
it needs **all three**: the frontend bundle, the backend server and the host. A frontend-only deploy
is enough to fix Run Tests itself, but leaves the API and scheduler paths wrong.

## Prevention

The trap is a canonicaliser that is **lossy about intent**: `canonical_variant_name()` legitimately
maps base to `None` for graph lookups, but callers kept using its output to answer a different
question — "did the user choose?". Anywhere a default may override a caller's value, decide
"supplied?" on the **raw** input before canonicalising, never on the canonical result.

The frontend variant of the same trap is the generic `if (!value) continue` in a serialiser: it is
correct for every parameter whose empty value means "unset", and wrong for the one whose empty value
means "base". A resolved default and an omitted field must not share a representation.

It also cost a day of looking in the wrong place: `RunTests.tsx` carries a correct, well-commented
fix for exactly this bug at line 1249, which made the frontend look innocent. A correct value is not
a delivered value — follow it to the wire.
