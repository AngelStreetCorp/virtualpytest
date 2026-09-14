# BUG-0036 — Conditional-edge divergence recorded as a KPI failure instead of a recovered success

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0036                                                    |
| Reported  | 2026-07-29                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium (conditional edges accrue false KPI failures; the diverged-to hop is left unmeasured) |
| Area      | backend_host/navigation_executor — per-step KPI queue + conditional recovery |
| Fixed in  | build 8713                                                   |
| Commit    | `a3d1ad0f7`, `374b6cc4d`                                                  |

---

## Symptom

Measuring `apps_disney → disney_home` on `host7`: the device opens Disney but lands on the
`disney_profile` screen (a conditional sibling of `disney_home`), then recovers via
`disney_profile → disney_home` and reaches the target. Despite the overall navigation **succeeding**,
the KPI store showed a **failure** on `apps_disney → disney_home` (action_set
`apps_disney_to_disney_profile_1780417713647`, `kpi_measurement_success = false`, `ms = NULL`,
error `skipped: live destination verification failed`) — while the `apps_disney → disney_profile`
transition that actually happened was **never measured**. The conditional edge's KPI success-rate in
Grafana was corrupted by these false failures.

## Root cause

KPI is queued **per step, on ACTION success** (`navigation_executor.py:1512`), independent of whether
the destination verified. When a conditional edge's action fires but its target verify fails (device
on a sibling), the block at `1512-1580` computes `live_verification_failed=True` and writes a **skip
KPI** against the intended edge — **before** the conditional-sibling recovery even runs
(`~1638`). So by the time the executor detects the sibling and recovers, the false-failure KPI is
already queued, and nothing records the real `source → sibling` transition.

## Fix

All in `navigation_executor.py` (best-effort, non-fatal, scoped to conditional edges only):

- **Suppress the skip.** Compute `conditional_divergence = is_conditional_step and verifications_ran
  and not verification_success`; skip the per-step KPI queue when it's set. The step's nav row still
  records (accurate — the direct transition failed), but with **no KPI**, so it drops out of the
  KPI dashboards (which filter on KPI-not-null). Non-conditional verify failures are unchanged and
  still record their skip + failure report.
- **Emit a positive recovered KPI.** A local `_emit_recovered_kpi(reached_node, label)` is called in
  the three accepted-recovery branches (reached-target / recovery-path-spliced / arrived-on-sibling).
  It records a **success** `source → reached-node` row + KPI: the sibling **shares the edge's
  `action_set_id`**, so it swaps `edge_id`/target and measures `action → sibling-appeared` using the
  **sibling node's own verifications**. The spliced `sibling → target` step keeps recording its own
  success on its next iteration.

**Net** for `apps_disney → disney_home` via `disney_profile`: two clean successes
(`apps_disney → disney_profile` + `disney_profile → disney_home`), no corrupting failure KPI.

## Scope / blast radius

This is the live navigation path for **every goto / validation / script** on the fleet. The
behavioral change: any conditional edge that diverges to a verified sibling now logs a **success to
the sibling** instead of a **failure to the intended target**. That is the intent, but it shifts
conditional-edge KPI telemetry, so verify a plain non-conditional goto is unaffected after deploy.

Related: [[BUG-0034]](BUG-0034-2026-07-29-kpi-conditional-multihop-recovered-edge-dropped.md) fixed
the KPI *script's* aggregation for the same conditional-multi-hop scenario; this fixes the *executor*
that produces the underlying rows (so it also applies to plain gotos, not just the KPI script).

## Follow-up: skip the diverged step's ROW too (`374b6cc4d`)

The first pass suppressed only the *KPI* for the diverged step, leaving its
`execution_results` row behind — a redundant NULL / `success=false` duplicate under
the SHARED sibling action_set (e.g. a null `apps_disney_to_disney_profile` row next
to the real recovered success). It drops out of the KPI dashboards (NULL KPI is
filtered) but still pollutes that action_set's success-rate in validation/nav
dashboards. Fixed by skipping `_record_step_execution_results` entirely for a
conditional divergence (also gated on `action_success`, so a genuine action failure
on a conditional edge is still recorded). An unrecoverable divergence now leaves no
per-step row at all — the overall navigation still fails with a clear error.

## Verification

`python3 -m py_compile` clean (main + prod). Runtime validation pending deploy of the **host backend**
service (this runs in the nav process, not `vpt-kpi`): re-run `apps_disney → disney_home` and confirm
the `vpt-kpi` logs show an `apps_disney → disney_profile` **success** (not a skip) plus
`disney_profile → disney_home` success, and that a non-conditional goto is unchanged.
