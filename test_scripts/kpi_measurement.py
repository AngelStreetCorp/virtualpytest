#!/usr/bin/env python3
"""
KPI Measurement Script for VirtualPyTest

This script measures KPIs for a specific edge transition by repeatedly navigating it.
Uses action_set label selection to ensure DIRECT navigation transition.
KPI measurements are post-processed by kpi_executor service and fetched from DB.

Workflow:
1. Frontend: User selects action_set from dropdown (e.g., "live → live_fullscreen")
2. Frontend: Sends edge paraeven worsmeter with action_set label
3. Script: Maps action_set label to correct from/to nodes (handles forward/backward)
4. Script: Navigate in loop: goto(from) → goto(to) (like goto.py)
5. Script: Wait 10 seconds for kpi_executor post-processing
6. Script: Fetch KPI measurements from database
7. Script: Display min/max/avg statistics

Usage:
    python test_scripts/kpi_measurement.py <userinterface_name> --edge <action_set_label> [--iterations <count>]
    
Examples:
    python test_scripts/kpi_measurement.py example_mobile --edge "live → live_fullscreen" --iterations 5
    python test_scripts/kpi_measurement.py example_androidtv --edge "settings → home" --iterations 10
"""

import sys
import os
import time
from datetime import datetime, timezone

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device


# Script arguments - defined early for backend parameter detection (must be within first 300 lines)
# Script arguments (framework params have defaults, script params are specific)
_script_args = [
    '--userinterface:str:example_mobile',  # Framework param with default
    '--variant:str:',                              # Optional named variant; empty = base
    '--edge:str:',                                 # Script-specific param
    '--iterations:int:3',                          # Script-specific param
    '--closing_edge:str:',                         # Optional edge to execute at end (empty = do nothing)
]
_script_description = "Measure KPI timing for a navigation edge."
_arg_descriptions = {
    'userinterface': 'UI interface name',
    'variant': "Optional variant name; if omitted, base data is used.",
    'edge': 'Action set label (e.g. "live -> live_fullscreen")',
    'iterations': 'Number of measurement iterations',
    'closing_edge': 'Optional action set label to execute after measurement (e.g. to close an app). Empty = leave device where the run ended.',
}


def _get_available_edges(context):
    """Get list of all available edges from navigation tree.

    Resolves the user's `--edge <action_set label>` choice against the
    VARIANT-scoped graph — matching the data source backing the RunTests
    EdgeKpiSelector dropdown (`/server/navigationTrees/kpi-action-sets`,
    which is now variant-filtered as of 2026-05-20). The dropdown only
    surfaces action_sets the active variant can actually reach, so this
    lookup must read from the same scope. Reading base when the variant
    has hidden/disabled the chosen action_set would surface it here and
    then the navigation step would fail.

    Variant is resolved the same way `load_navigation_tree` resolves it
    (`device.navigation_context['variant']`, set by the script executor
    from the launch payload).
    """
    from backend_host.src.services.navigation.navigation_pathfinding import find_optimal_edge_validation_sequence
    from shared.src.lib.database.userinterface_db import get_userinterface_by_name
    from shared.src.lib.database.navigation_trees_db import get_root_tree_for_interface

    device = context.selected_device

    # Get tree_id
    userinterface = get_userinterface_by_name(context.userinterface, context.team_id,
                                              mode=getattr(context.args, 'ui_mode', 'dev'))
    if not userinterface:
        print(f"❌ User interface '{context.userinterface}' not found")
        return []

    root_tree = get_root_tree_for_interface(userinterface['id'], context.team_id)
    if not root_tree:
        print(f"❌ No root tree found for interface '{context.userinterface}'")
        return []

    context.tree_id = root_tree['id']

    # Load navigation tree to populate cache. This reads variant from
    # nav_context so the variant-scoped graph gets warmed for both this
    # lookup and the later navigation calls — no second base-graph load
    # needed now that the lookup also runs in variant scope.
    nav_result = device.navigation_executor.load_navigation_tree(
        context.userinterface,
        context.team_id
    )
    if not nav_result['success']:
        print(f"❌ Navigation tree loading failed")
        return []

    variant_name = None
    if hasattr(device, 'navigation_context') and device.navigation_context:
        variant_name = device.navigation_context.get('variant')
    if isinstance(variant_name, str):
        variant_name = variant_name.strip() or None

    print(f"🎨 [_get_available_edges] Resolving --edge in variant scope: {variant_name or 'base'}")
    return find_optimal_edge_validation_sequence(
        context.tree_id, context.team_id, variant=variant_name
    )


def _action_set_label_exists_in_tree(context, label: str) -> bool:
    """Return True if any action set in the full tree carries this label.

    The runnable map is built from the validation sequence (traversable edges
    only), so an empty / variant-hidden action set won't appear there even
    though it's a real, selectable edge. This checks the full tree so we can
    tell "exists but unreachable (no path)" apart from "no such action set".
    """
    try:
        from shared.src.lib.database.navigation_trees_db import get_tree_edges
        if not getattr(context, 'tree_id', None):
            return False
        result = get_tree_edges(context.tree_id, context.team_id)
        if not result.get('success'):
            return False
        for edge in result.get('edges', []):
            for action_set in (edge.get('action_sets') or []):
                if action_set.get('label') == label:
                    return True
        return False
    except Exception as e:
        print(f"[@kpi_measurement] _action_set_label_exists_in_tree failed: {e}")
        return False


def _fetch_kpi_results_from_db(team_id: str, device_name: str, start_time: datetime, end_time: datetime):
    """Fetch KPI measurements from execution_results table filtered by team, device, and time range"""
    from shared.src.lib.utils.supabase_utils import get_supabase_client
    
    try:
        supabase = get_supabase_client()
        if not supabase:
            print("❌ [_fetch_kpi_results] Supabase client not available")
            return []
        
        # Query execution_results for KPI measurements in time range
        # Filter by team_id, device_name, and time window for precise device-specific results.
        #
        # Filter on kpi_measurement_success IS NOT NULL, NOT kpi_measurement_ms.
        # A FAILED measurement stores success=False, ms=NULL, plus an error and a
        # kpi_report_url (the failure report). Filtering on ms-not-null silently
        # dropped every failure — they surfaced as "❌ Missing" in the summary
        # with the failure report lost. kpi_measurement_success is NULL only on
        # ordinary nav rows (never post-processed by kpi_executor), so this keeps
        # both successes and failures while still excluding non-KPI rows.
        result = supabase.table('execution_results').select(
            'kpi_measurement_ms, kpi_measurement_success, kpi_measurement_error, kpi_report_url, executed_at, action_set_id, edge_id'
        ).eq('team_id', team_id).eq('device_name', device_name).gte(
            'executed_at', start_time.isoformat()
        ).lte(
            'executed_at', end_time.isoformat()
        ).not_.is_('kpi_measurement_success', 'null').order('executed_at', desc=False).execute()
        
        print(f"✅ [_fetch_kpi_results] Found {len(result.data)} KPI measurements from DB for device '{device_name}'")
        return result.data
        
    except Exception as e:
        print(f"❌ [_fetch_kpi_results] Error fetching KPI results: {e}")
        return []


def _is_kpi_skip(result) -> bool:
    """True when a non-success row is a benign SKIP, not a hard failure.

    The kpi_executor records `kpi_measurement_error = "skipped: live destination
    verification failed"` (kpi_executor.py) when the navigation step's live
    destination verifier failed — i.e. the device did not land on the expected
    node (typically it landed on a conditional sibling instead). That is an
    EXPECTED outcome for a KPI run, not a transport/measurement fault, so we
    surface it as an orange ⚠️ skip rather than a red ❌ failure and exclude it
    from the failure tally + the overall success verdict.
    """
    if result.get('kpi_measurement_success'):
        return False
    return (result.get('kpi_measurement_error') or '').startswith('skipped:')


def _fmt_iteration_line(index: int, result) -> str:
    """Format one iteration row; inlines kpi_report_url when present.

    The report URL is emitted using markdown link syntax `[label](url)` so the
    HTML formatter (format_console_summary_for_html) renders it as a clickable,
    new-tab anchor — styled like the script step report's "View Detailed
    Comparison Report" link (📊 … ↗) instead of a giant raw URL. The label
    reflects the outcome: a success KPI report vs a failure report (which on the
    live-verification-failed path is the verification failure report itself).
    Works for both absolute R2 URLs and root-relative `/host/...` URLs, since
    the markdown linker now accepts both. Terminal viewers still see a readable
    text fragment. Direction is implicit — the row sits under its KPI Metrics
    header.

    A sibling-skip (destination verifier failed — see _is_kpi_skip) renders as
    an orange ⚠️ with the simplified "Skipped - Destination Verification failed"
    message instead of the raw executor error, naming the sibling node we landed
    on when known (`_sibling_node_label`, injected by capture_kpi_summary).
    """
    if not result:
        return f"   {index}. ❌ Missing"
    success = result.get('kpi_measurement_success', False)
    is_skip = _is_kpi_skip(result)
    status = "✅" if success else ("⚠️" if is_skip else "❌")
    report_url = result.get('kpi_report_url') or ''
    if report_url:
        report_label = "📊 View KPI report ↗" if success else "📊 View failure report ↗"
        report_part = f"  [{report_label}]({report_url})"
    else:
        report_part = ""
    if success:
        kpi_ms = result.get('kpi_measurement_ms')
        return f"   {index}. {status} {kpi_ms}ms ({kpi_ms/1000:.2f}s){report_part}"
    if is_skip:
        sibling = result.get('_sibling_node_label')
        msg = "Skipped - Destination Verification failed"
        if sibling:
            msg += f" (landed on sibling '{sibling}')"
        return f"   {index}. {status} {msg}{report_part}"
    error = result.get('kpi_measurement_error', 'Unknown error')
    return f"   {index}. {status} Failed - {error}{report_part}"


def _append_direction_metrics(lines: list, direction_label: str, results: list):
    """Append a compact block for ONE traversed edge: header, totals on one
    line, stats on one line, then each recorded measurement inline.

    Renders exactly the rows recorded for this edge — no pad-to-N "Missing"
    rows. On a multi-hop conditional path different edges legitimately have
    different row counts (e.g. the conditional edge is skipped once while its
    recovered continuation is measured every iteration), so padding one block
    to the requested iteration count would invent phantom "Missing" rows.
    """
    successful = [r for r in results if r.get('kpi_measurement_success')]
    # Sibling-skips (destination verifier failed → likely landed on a sibling)
    # are tallied separately as ⚠️ and NOT counted as ❌ failures.
    skipped = [r for r in results if _is_kpi_skip(r)]
    failed = [r for r in results if not r.get('kpi_measurement_success') and not _is_kpi_skip(r)]
    lines.append(f"📈 KPI Metrics ({direction_label}):")
    summary = f"   ✅ {len(successful)}/{len(results)}"
    if skipped:
        summary += f"   ⚠️ {len(skipped)}/{len(results)} skipped"
    if failed:
        summary += f"   ❌ {len(failed)}/{len(results)}"
    lines.append(summary)
    if successful:
        durations_ms = [r['kpi_measurement_ms'] for r in successful]
        min_d = min(durations_ms)
        max_d = max(durations_ms)
        avg_d = sum(durations_ms) / len(durations_ms)
        lines.append(
            f"   Min: {min_d}ms ({min_d/1000:.2f}s)  "
            f"Max: {max_d}ms ({max_d/1000:.2f}s)  "
            f"Avg: {avg_d:.0f}ms ({avg_d/1000:.2f}s)"
        )
    for idx, result in enumerate(results, 1):
        lines.append(_fmt_iteration_line(idx, result))


def capture_kpi_summary(
    context,
    userinterface_name: str,
    edge_label: str,
    from_label: str,
    to_label: str,
    iterations: int,
    relevant_results: list,
    selected_action_set_id: str,
    sibling_action_set_id: str,
    selected_label: str = '',
    sibling_label: str = '',
    selected_kpi_name: str = '',
    sibling_kpi_name: str = '',
    variant: str = '',
    measurement_attempted: bool = False,
    measurement_fallback: dict = None,
    forward_sibling_labels: list = None,
    forward_action_set_ids: set = None,
    reverse_action_set_ids: set = None,
    recovered_sources: list = None,
    action_set_labels: dict = None,
) -> str:
    """Capture KPI measurement summary as text for report.

    `relevant_results` should contain rows for the selected action_set AND its
    reverse (if any). Forward and reverse get their own KPI Metrics block; the
    per-iteration breakdown pairs them chronologically.

    `measurement_attempted` is True only once the iteration loop actually
    ran (i.e. we reached `from_label` and started measuring). When False,
    we never queried the DB, so suppress any "No KPI measurements found"
    hint — the error line below it is the real story.
    """
    lines = []
    lines.append("="*60)
    lines.append("📊 [KPI MEASUREMENT] EXECUTION SUMMARY")
    lines.append("="*60)
    # Device/host may be unset when an early failure aborts before setup
    # completes — keep the summary renderable regardless (mirrors
    # validation.py's capture_validation_summary).
    if context.selected_device:
        lines.append(f"📱 Device: {context.selected_device.device_name} ({context.selected_device.device_model})")
    else:
        lines.append("📱 Device: Setup failed - no device selected")
    if context.host:
        lines.append(f"🖥️ Host: {context.host.host_name}")
    else:
        lines.append("🖥️ Host: Setup failed - no host available")
    lines.append(f"📋 Interface: {userinterface_name}")
    lines.append(f"🎨 Variant: {variant or 'base'}")
    lines.append(f"🎯 Edge: {edge_label}")
    lines.append(f"🔢 Requested Iterations: {iterations}")
    lines.append(f"⏱️ Total Script Time: {context.get_execution_time_ms()/1000:.1f}s")
    lines.append("")

    # Conditional-SOURCE recovery notice — ONE line. The source resolved to a
    # conditional sibling (e.g. Resume/Watch instead of the expected screen) and the
    # executor auto-recovered; the measurements below are for the sibling edges and
    # are NORMAL (not failures). Everything else renders exactly like a success.
    if recovered_sources:
        _sibs = ', '.join(sorted({s for s in recovered_sources if s}))
        lines.append(
            f"⚠️  Source recovered to conditional sibling '{_sibs}' "
            f"(asset showed Resume/Watch — normal for resume assets); "
            f"measured from the sibling."
        )
        lines.append("")

    # Conditional-sibling fallback notice. Rendered prominently when the
    # script swapped the measured edge mid-run because the originally-
    # selected branch was unreachable on this device (the conditional
    # consistently resolved to a sibling). The KPI numbers below are for
    # the actually-measured edge, NOT the originally-selected one — this
    # block makes that explicit so the reader doesn't conflate them.
    if measurement_fallback:
        lines.append("⚠️  MEASUREMENT FALLBACK — original edge unreachable")
        # The swap can be either source-side (setup nav failed because the
        # planned source was a conditional target; `original_from_label` is
        # set) or destination-side (an iteration's forward failed because
        # the planned destination was a conditional target; `original_to_label`
        # is set). Render whichever applies so the line stays accurate.
        if measurement_fallback.get('original_from_label'):
            lines.append(
                f"    Originally selected : {measurement_fallback.get('original_edge_label', '?')} "
                f"(from {measurement_fallback.get('original_from_label', '?')})"
            )
            lines.append(
                f"    Actually measured   : {measurement_fallback.get('measured_edge_label', '?')} "
                f"(from {measurement_fallback.get('measured_from_label', '?')})"
            )
        else:
            lines.append(
                f"    Originally selected : {measurement_fallback.get('original_edge_label', '?')} "
                f"(→ {measurement_fallback.get('original_to_label', '?')})"
            )
            lines.append(
                f"    Actually measured   : {measurement_fallback.get('measured_edge_label', '?')} "
                f"(→ {measurement_fallback.get('measured_to_label', '?')})"
            )
        lines.append(
            f"    Sibling detected    : {measurement_fallback.get('sibling_node_label', '?')}"
        )
        swap_at = measurement_fallback.get('swapped_at_iteration', '?')
        if swap_at == 0:
            # Sentinel: swap happened during initial setup, before iteration
            # 1. No iterations were consumed on the original edge, so the
            # loop did NOT need to be extended — all N iterations run on
            # the sibling edge as if the user had picked it directly.
            lines.append(
                f"    Swapped during      : initial setup (before iteration 1 — "
                f"planned source node unreachable; device landed on the "
                f"sibling, used as the measurement source for all "
                f"{iterations} iterations)"
            )
        else:
            bumped_total = (
                iterations + swap_at if isinstance(swap_at, int) else '?'
            )
            lines.append(
                f"    Swapped at iteration: {swap_at} "
                f"(iteration 1..{swap_at} ran on the original edge and failed; "
                f"loop extended to {bumped_total} so the sibling edge still "
                f"gets the requested {iterations} measurements)"
            )
        reason = measurement_fallback.get('reason')
        if reason:
            lines.append(f"    Reason              : {reason}")
        lines.append("")

    # Render ONE KPI Metrics block per distinct edge actually traversed, instead
    # of collapsing every forward hop into a single block. A conditional path
    # (e.g. apps_disney → disney_home that recovers via disney_profile) traverses
    # TWO edges — the skipped conditional edge AND its recovered continuation —
    # each recorded in execution_results under its own action_set_id. Showing
    # them as separate, individually-labelled blocks is what makes BOTH hops'
    # KPIs visible even when the originally-requested target was only reached via
    # recovery. "reverse" edges (the between-iterations walk back) still get their
    # own blocks after the forward ones.
    fwd_ids = set(forward_action_set_ids) if forward_action_set_ids else {selected_action_set_id}
    rev_ids = set(reverse_action_set_ids) if reverse_action_set_ids else (
        {sibling_action_set_id} if sibling_action_set_id else set())
    rev_ids = rev_ids - fwd_ids  # a forward id is never also counted as reverse
    labels = action_set_labels or {}

    def _hop_prefix(action_set_id: str) -> str:
        """Header for one edge's KPI block. Prefer the operator's friendly
        kpi_name (Edge Edit dialog) / raw label, but ALWAYS disambiguate with the
        from→to transition when it isn't already the header: the same Display Name
        is deliberately reused across the hops of a multi-hop flow, so the report
        must still tell the hops apart (unlike Grafana, which groups by name)."""
        info = labels.get(action_set_id) or {}
        transition = (
            f"{info.get('from')} → {info.get('to')}"
            if info.get('from') and info.get('to') else ''
        )
        friendly = info.get('kpi_name') or info.get('label') or ''
        if friendly and transition and friendly != transition:
            return f"{friendly} ({transition})"
        return friendly or transition or (action_set_id or 'unknown edge')

    # Name the sibling we landed on for forward sibling-skips. The DB row carries
    # no sibling label (the kpi_executor doesn't know it), so we use what the
    # iteration loop observed in the nav result's error_details. A KPI run targets
    # one edge, so the landed sibling is consistent — if exactly one distinct
    # sibling was seen, attach it to every skip row; if ambiguous, omit it.
    distinct_siblings = {s for s in (forward_sibling_labels or []) if s}
    only_sibling = next(iter(distinct_siblings)) if len(distinct_siblings) == 1 else None

    def _earliest(rows: list) -> str:
        return min((r.get('executed_at') or '' for r in rows), default='')

    # Group the relevant rows by the edge (action_set_id) they were recorded
    # under, then split forward vs reverse. Anything not explicitly reverse is
    # treated as forward, so a swapped-out original edge's row (kept in
    # relevant_results after a fallback) is still shown rather than silently
    # dropped. Blocks are ordered by the earliest measurement in each, so the
    # hops read in the order they were traversed.
    from collections import OrderedDict
    groups = OrderedDict()
    for r in relevant_results:
        groups.setdefault(r.get('action_set_id'), []).append(r)

    reverse_blocks = sorted(
        [(asid, rows) for asid, rows in groups.items() if asid in rev_ids],
        key=lambda kv: _earliest(kv[1]),
    )
    forward_blocks = sorted(
        [(asid, rows) for asid, rows in groups.items() if asid not in rev_ids],
        key=lambda kv: _earliest(kv[1]),
    )

    if forward_blocks or reverse_blocks:
        first = True
        for asid, rows in forward_blocks + reverse_blocks:
            rows = sorted(rows, key=lambda r: r.get('executed_at') or '')
            # Sibling naming is forward-only — the reverse leg has its own target,
            # so never stamp a forward sibling label onto a reverse skip row.
            is_forward = asid not in rev_ids
            if only_sibling and is_forward:
                for r in rows:
                    if _is_kpi_skip(r):
                        r['_sibling_node_label'] = only_sibling
            if not first:
                lines.append("")
            _append_direction_metrics(lines, _hop_prefix(asid), rows)
            first = False
    elif measurement_attempted and not context.error_message:
        # We polled the DB but came back empty. Only show the "post-processing
        # may still be in progress" hint when we have NO better explanation —
        # if context.error_message is set (e.g. all navigations were skipped
        # because the nodes verify identically), that error line below is the
        # real story and this generic hint would actively mislead.
        lines.append("⚠️  No KPI measurements found in database")
        lines.append("   (Post-processing may still be in progress)")

    lines.append("")
    lines.append(f"📸 Screenshots: {len(context.screenshot_paths)} captured")
    result_label = 'SUCCESS' if context.overall_success else 'FAILED'
    if context.overall_success and recovered_sources:
        result_label += ' (recovered)'
    lines.append(f"🎯 Result: {result_label}")

    if context.error_message:
        lines.append(f"\n❌ Error: {context.error_message}")

    lines.append("="*60)

    return "\n".join(lines)


def _resolve_edge_endpoints(context, label: str):
    """Resolve an action_set label to its (from_node, to_node) transition.

    Reuses `_get_available_edges` (variant-scoped, warms the same cache the
    measurement loop uses) and applies the SAME forward (action_sets[0]) /
    reverse (action_sets[1], source/target swapped) mapping that
    `_run_kpi_measurement` builds — so a label the user picked in the
    dropdown resolves here to exactly the nodes that direction navigates
    between. Returns (from_node, to_node) or None when the label isn't a
    traversable edge in the current scope.
    """
    edges = _get_available_edges(context)
    for edge in edges:
        edge_data = edge.get('original_edge_data', {})
        action_sets = edge_data.get('action_sets', [])
        source_label = edge.get('from_node_label', '')
        target_label = edge.get('to_node_label', '')
        # Forward direction (index 0): source → target
        if len(action_sets) > 0 and action_sets[0].get('label') == label and action_sets[0].get('actions'):
            return source_label, target_label
        # Reverse direction (index 1): target → source (swapped, like the loop)
        if len(action_sets) > 1 and action_sets[1].get('label') == label and action_sets[1].get('actions'):
            return target_label, source_label
    return None


def _goto_closing_edge_closure(context, device, closing_label: str):
    """Best-effort closure: execute the user-selected closing edge, if any.

    Replaces the previous always-goto-'home' closure. When `closing_label` is
    empty the device is left wherever the run ended (do nothing). Otherwise the
    edge's transition is FORCED — goto(from_node) then goto(to_node) — so the
    closing edge's own actions run (e.g. a real "quit app" key), rather than
    letting pathfinding pick a route to 'home' that may not close the app.

    Runs in main()'s finally AFTER _run_kpi_measurement has fully finished
    (DB poll done, verdict computed), so if the closing edge happens to be
    KPI-configured its stray measurement row can't pollute the run's counts.
    Strictly non-fatal — a closure failure never changes the run's result.
    """
    if not closing_label or not closing_label.strip():
        return  # no closing edge selected — leave the device where it is
    if device is None or not getattr(context, 'tree_id', None):
        return  # setup never got far enough to navigate; nothing to close out
    import asyncio
    try:
        endpoints = _resolve_edge_endpoints(context, closing_label)
        if not endpoints:
            print(f"⚠️  [kpi_measurement] Closure: closing edge '{closing_label}' "
                  f"not resolvable in this scope (non-fatal); leaving device as-is")
            return
        from_node, to_node = endpoints
        print(f"\n🚪 [kpi_measurement] Closure: executing closing edge "
              f"'{closing_label}' ({from_node} → {to_node})")
        # Position at the edge source, then traverse it — mirrors the forward
        # measurement nav so the specific closing edge's actions execute.
        asyncio.run(device.navigation_executor.execute_navigation(
            tree_id=context.tree_id,
            userinterface_name=context.userinterface_name,
            target_node_label=from_node,
            team_id=context.team_id,
            context=context
        ))
        result = asyncio.run(device.navigation_executor.execute_navigation(
            tree_id=context.tree_id,
            userinterface_name=context.userinterface_name,
            target_node_label=to_node,
            team_id=context.team_id,
            context=context
        ))
        if result.get('success', False):
            print(f"✅ [kpi_measurement] Closure: closing edge '{closing_label}' executed")
        else:
            print(f"⚠️  [kpi_measurement] Closure: closing edge '{closing_label}' "
                  f"failed (non-fatal)")
    except Exception as e:
        print(f"⚠️  [kpi_measurement] Closure: closing edge '{closing_label}' "
              f"error (non-fatal): {e}")


def _run_kpi_measurement(context, args, device, summary_state) -> bool:
    """Core KPI measurement loop.

    Updates `summary_state` in place as soon as each value is known so the
    caller can always render an execution summary — including on the early
    `return False` / exception paths (no edges, bad --edge label, setup
    navigation failed). Returns context.overall_success.
    """
    print(f"📊 [kpi_measurement] Starting KPI measurement")
    print(f"📱 [kpi_measurement] Device: {device.device_name} ({device.device_model})")
    print(f"🔗 [kpi_measurement] Action Set: {args.edge}")
    print(f"🔢 [kpi_measurement] Iterations: {args.iterations}")
    
    # Record script start time for DB query (use UTC to match database timestamps)
    script_start_time = datetime.now(timezone.utc)
    
    # Get available edges and build action_set map
    print(f"📥 [kpi_measurement] Loading available edges...")
    edges = _get_available_edges(context)
    if not edges:
        context.error_message = "No edges found in navigation tree"
        return False
    
    print(f"✅ [kpi_measurement] Found {len(edges)} edges in validation sequence")
    
    # Build action_set_map with forward/backward support
    action_set_map = {}
    # action_set_id → {label, kpi_name, from, to} for EVERY action_set in the
    # tree (both directions of every edge), so the summary can label any hop a
    # multi-hop conditional path traverses — not just the pre-selected forward/
    # reverse pair. Keyed by the same ids the executor records execution_results
    # rows under, so a recovered continuation edge (e.g. disney_profile →
    # disney_home) can be resolved back to a readable transition for its block.
    action_set_labels = {}

    for edge in edges:
        edge_data = edge.get('original_edge_data', {})
        action_sets = edge_data.get('action_sets', [])
        source_label = edge.get('from_node_label', '')
        target_label = edge.get('to_node_label', '')

        forward_id = action_sets[0].get('id', '') if len(action_sets) > 0 else ''
        reverse_id = action_sets[1].get('id', '') if len(action_sets) > 1 else ''
        forward_label_str = action_sets[0].get('label', '') if len(action_sets) > 0 else ''
        reverse_label_str = action_sets[1].get('label', '') if len(action_sets) > 1 else ''
        # Optional per-direction friendly KPI name (set in the Edge Edit dialog,
        # stored on the action_set). Preferred over the raw label in the report.
        forward_kpi_name = (action_sets[0].get('kpi_name') or '') if len(action_sets) > 0 else ''
        reverse_kpi_name = (action_sets[1].get('kpi_name') or '') if len(action_sets) > 1 else ''

        # Register both directions for the per-hop summary labels. Recorded even
        # for action_sets with no actions (they still can't be measured, but a
        # traversed sibling always has actions) — harmless and keeps the lookup
        # total. The forward direction goes source→target, the reverse swaps.
        if forward_id:
            action_set_labels[forward_id] = {
                'label': forward_label_str, 'kpi_name': forward_kpi_name,
                'from': source_label, 'to': target_label,
            }
        if reverse_id:
            action_set_labels[reverse_id] = {
                'label': reverse_label_str, 'kpi_name': reverse_kpi_name,
                'from': target_label, 'to': source_label,
            }

        # Sum of per-action wait_time for an action set — the dominant term in how
        # long the executor takes to post-process that direction's KPI (it waits up
        # to the timeout window before scanning). Used to size the DB-poll budget so
        # long edges (reboot ~90s) aren't declared "no measurements" prematurely.
        def _set_wait_ms(action_set):
            total = 0
            for a in (action_set.get('actions') or []):
                params = a.get('params') if isinstance(a.get('params'), dict) else {}
                total += params.get('wait_time', a.get('wait_time', 0)) or 0
            return total

        # Forward action_set (index 0)
        if len(action_sets) > 0:
            forward_set = action_sets[0]
            if forward_label_str and forward_set.get('actions'):
                action_set_map[forward_label_str] = {
                    'from_node': source_label,    # Normal direction
                    'to_node': target_label,
                    'action_set_id': forward_id,
                    'sibling_action_set_id': reverse_id,  # Reverse of this set (if any)
                    'sibling_label': reverse_label_str,
                    'kpi_name': forward_kpi_name,
                    'sibling_kpi_name': reverse_kpi_name,
                    'wait_ms': _set_wait_ms(forward_set),
                    # The forward-oriented validation step doubles as a ready-made
                    # single-step navigation_path. Used to FORCE this edge when the
                    # source is ENTRY (a virtual node we can't walk back to) and the
                    # device is already at the destination — passing it as
                    # navigation_path bypasses the already-at-target short-circuit.
                    'edge_step': edge,
                }

        # Reverse action_set (index 1) - SWAP source/target
        if len(action_sets) > 1:
            reverse_set = action_sets[1]
            if reverse_label_str and reverse_set.get('actions'):
                action_set_map[reverse_label_str] = {
                    'from_node': target_label,    # Swapped!
                    'to_node': source_label,      # Swapped!
                    'action_set_id': reverse_id,
                    'sibling_action_set_id': forward_id,  # Forward of this set
                    'sibling_label': forward_label_str,
                    'kpi_name': reverse_kpi_name,
                    'sibling_kpi_name': forward_kpi_name,
                    'wait_ms': _set_wait_ms(reverse_set),
                }

    # Secondary index: (from_node_label, to_node_label) → action_set_map entry.
    # The primary action_set_map is keyed by label, which is great for the user
    # picking from a dropdown, but the conditional-sibling fallback below needs
    # the inverse lookup: "given that the device actually landed on sibling Y
    # from source X, what action_set should I measure now?". Built from the
    # same edges, so reachability rules (variant scope, action presence) hold.
    edges_by_endpoints = {
        (entry['from_node'], entry['to_node']): {'label': label, **entry}
        for label, entry in action_set_map.items()
    }

    print(f"✅ [kpi_measurement] Built action_set map with {len(action_set_map)} action sets")
    # Expose the id→label map so the summary can title each traversed hop's block.
    summary_state['action_set_labels'] = action_set_labels

    # Find selected action_set
    if args.edge not in action_set_map:
        # The map is built from the VALIDATION SEQUENCE (pathfinding), which only
        # contains traversable action sets. A selectable action set that's absent
        # here either (a) exists in the tree but has no actions / can't be reached
        # in this variant — i.e. no path — or (b) doesn't exist at all. The
        # EdgeKpiSelector dropdown offers (a), so disambiguate against the full
        # tree to avoid the misleading "not found" for a real-but-unreachable edge.
        if _action_set_label_exists_in_tree(context, args.edge):
            context.error_message = (
                f"No path found to traverse '{args.edge}': the action set exists in the "
                f"tree but is not reachable here (it has no actions defined, or the active "
                f"variant hides/disables it). Add actions to this edge in the navigation "
                f"editor before measuring its KPI."
            )
        else:
            available_labels = list(action_set_map.keys())[:10]
            context.error_message = f"Action set '{args.edge}' not found. Available (first 10): {', '.join(available_labels)}"
        return False
    
    selected = action_set_map[args.edge]
    from_label = selected['from_node']
    to_label = selected['to_node']
    selected_action_set_id = selected['action_set_id']
    sibling_action_set_id = selected.get('sibling_action_set_id') or ''
    selected_label = args.edge
    sibling_label = selected.get('sibling_label') or ''
    sibling_kpi_name = selected.get('sibling_kpi_name') or ''
    # Reverse-direction pairing for SEPARATE one-way edges.
    # `sibling_action_set_id` is only populated when forward+reverse live on the
    # SAME bidirectional edge as action_sets[0]/[1] (e.g. apps_skysport ↔
    # skysport_home) — then both directions render in the summary. When the
    # transition is modeled as two distinct one-way edges (e.g. poweroff → live
    # and live → poweroff, each with a single action_set), there is no same-edge
    # sibling, so the reverse leg — which the iteration loop still traverses via
    # goto(from_label) and kpi_executor still records — was dropped from the
    # summary as "unrelated". Recover it by looking up the opposite-endpoint edge
    # so both directions pair regardless of how the tree models the transition.
    if not sibling_action_set_id:
        reverse_edge = edges_by_endpoints.get((to_label, from_label))
        if reverse_edge and reverse_edge.get('action_set_id'):
            sibling_action_set_id = reverse_edge['action_set_id']
            sibling_label = reverse_edge.get('label') or sibling_label
            sibling_kpi_name = reverse_edge.get('kpi_name') or sibling_kpi_name
            print(f"🔁 [kpi_measurement] No same-edge reverse; pairing reverse edge "
                  f"'{sibling_label}' ({to_label} → {from_label}) for the summary")
    # Seed summary state now that the edge is resolved — if anything below
    # fails (setup nav, exception) the summary still has the resolved
    # transition + action sets to report.
    summary_state['from_label'] = from_label
    summary_state['to_label'] = to_label
    summary_state['selected_action_set_id'] = selected_action_set_id
    summary_state['sibling_action_set_id'] = sibling_action_set_id
    summary_state['selected_label'] = selected_label
    summary_state['sibling_label'] = sibling_label
    summary_state['selected_kpi_name'] = selected.get('kpi_name') or ''
    summary_state['sibling_kpi_name'] = sibling_kpi_name
    # Set of action_sets we care to display in the raw printout: the chosen
    # one plus its reverse (used between iterations to walk back to from_label).
    # Anything else (e.g. entry_to_home from the very first navigation) is
    # incidental and would just clutter the report.
    relevant_action_set_ids = {selected_action_set_id}
    if sibling_action_set_id:
        relevant_action_set_ids.add(sibling_action_set_id)
    # Forward action_sets we accept as a valid measurement of "reaching to_label".
    # Starts as the selected edge; the iteration loop ADDS any sibling edge the
    # executor auto-recovers to when the source resolves to a conditional sibling
    # (e.g. replay_asset → replay_asset_resume). So both direct and recovered
    # iterations count, and a recovered source is reported (not failed).
    # Accept-sets are built from the edge the executor ACTUALLY measured each leg
    # (final step of the nav result), so they cover direct, recovered, and
    # duplicate-id cases. Forward is seeded with the selected edge; reverse is built
    # purely from measured reverse successes (so a failed/skipped main-reverse
    # routing artifact is never shown).
    forward_action_set_ids = {selected_action_set_id}
    reverse_action_set_ids = set()
    source_recovered = False  # flips once the source resolves to a conditional sibling
    # Forward edges whose KPI row the DB poll MUST wait for (not just any forward
    # row). When the selected edge is a conditional that lands on a sibling, its
    # own row is a fast SKIP recorded almost immediately — while the real
    # measurement is the recovered continuation edge, whose row the single worker
    # only stores ~10-15s later. Without waiting for the recovered id specifically,
    # the poll sees the skip, counts it as the one expected forward row, exits
    # early, and the verdict runs before the real measurement lands. Populated by
    # the recovery / fallback branches with the id we actually measure.
    recovered_forward_ids = set()
    summary_state['forward_action_set_ids'] = forward_action_set_ids
    summary_state['reverse_action_set_ids'] = reverse_action_set_ids

    print(f"✅ [kpi_measurement] Selected action_set: '{args.edge}'")
    print(f"📍 [kpi_measurement] Will navigate: {from_label} → {to_label}")
    print(f"🔑 [kpi_measurement] Action set ID: {selected_action_set_id}")
    
    # Iteration structure: setup once (walk to from_label), then per iteration do
    # forward (measures selected) + reverse (measures sibling, also resets state
    # for the next iter). This produces N forward + N reverse measurements that
    # pair cleanly in the summary, instead of N forward + (N-1) reverse.
    navigation_success_count = 0
    # A navigation can "succeed" by being SKIPPED: the executor's
    # already-at-target / position-tracking-bug check passes and it returns
    # success with transitions_executed=0 WITHOUT pressing any key. No edge is
    # traversed, so kpi_executor never queues a measurement. We must count
    # these separately — otherwise the run looks like "2/2 navigation success"
    # yet yields 0 KPI rows, and the report falls back to the misleading
    # "post-processing may still be in progress" hint. The usual cause is two
    # adjacent nodes whose verifications both pass on the same screen
    # (non-distinctive verifications, e.g. matching persistent menu-bar text).
    forward_skipped_count = 0
    reverse_skipped_count = 0
    # Reverse legs that actually traversed an edge (and thus queued a reverse KPI).
    # Drives expected_reverse so the DB poll waits for exactly what ran.
    reverse_success_count = 0
    import asyncio

    # Conditional-sibling fallback state. Declared BEFORE the initial setup
    # so the setup nav can also trigger the swap (e.g. user picked an edge
    # whose `from_label` is itself a conditional target — see the
    # `replay_asset → replay_asset_stream` case in kpi_measurement.md).
    # Once `fallback_used` flips, neither the setup retry nor the iteration
    # loop will swap again; one fallback per run.
    fallback_used = False
    iter_total = args.iterations

    if from_label.upper() == 'ENTRY':
        print(f"📍 [kpi_measurement] From node is ENTRY — skipping initial setup (virtual start point)")
    else:
        print(f"\n📍 [kpi_measurement] Initial setup: going to '{from_label}'")
        setup_result = asyncio.run(device.navigation_executor.execute_navigation(
            tree_id=context.tree_id,
            userinterface_name=context.userinterface_name,
            target_node_label=from_label,
            team_id=context.team_id,
            context=context
        ))
        if not setup_result.get('success', False):
            # Setup-time sibling fallback. The selected edge's source node
            # may itself be a conditional target (e.g. the user picked
            # `replay_asset → replay_asset_stream`; reaching `replay_asset`
            # requires a conditional press from `replay` and the device
            # may land on the sibling `replay_asset_resume`). Without this
            # block we'd abort here even though `replay_asset_resume` has
            # the equivalent outbound edge to `replay_asset_stream` we
            # could measure instead.
            err = setup_result.get('error_details') or {}
            sibling_node_label = err.get('sibling_landed_node_label')
            # Setup-case lookup differs from the iteration-loop case below:
            # we look up (sibling, to_label) — the sibling's outbound edge
            # to the originally-selected destination — because we want to
            # KEEP the destination and swap the source. The iteration loop
            # does the inverse (swap the destination, keep the source).
            fallback_entry = None
            if sibling_node_label:
                fallback_entry = edges_by_endpoints.get((sibling_node_label, to_label))
            if fallback_entry:
                original_label = selected_label
                original_from_label = from_label
                original_action_set_id = selected_action_set_id
                # Swap: the sibling becomes the measurement source. The
                # destination (to_label) is unchanged. Device is already on
                # the sibling (host updated current_node_id during sibling
                # verify), so no extra navigation is needed to start the
                # iteration loop.
                from_label = sibling_node_label
                selected_action_set_id = fallback_entry['action_set_id']
                sibling_action_set_id = fallback_entry.get('sibling_action_set_id') or ''
                selected_label = fallback_entry['label']
                sibling_label = fallback_entry.get('sibling_label') or ''
                relevant_action_set_ids = {selected_action_set_id, original_action_set_id}
                if sibling_action_set_id:
                    relevant_action_set_ids.add(sibling_action_set_id)
                forward_action_set_ids = {selected_action_set_id}
                reverse_action_set_ids = set()
                # Poll must wait for the swapped-in edge's row (see recovered_forward_ids).
                recovered_forward_ids = {selected_action_set_id}
                summary_state['forward_action_set_ids'] = forward_action_set_ids
                summary_state['reverse_action_set_ids'] = reverse_action_set_ids
                summary_state['from_label'] = from_label
                summary_state['selected_action_set_id'] = selected_action_set_id
                summary_state['sibling_action_set_id'] = sibling_action_set_id
                summary_state['selected_label'] = selected_label
                summary_state['sibling_label'] = sibling_label
                summary_state['selected_kpi_name'] = fallback_entry.get('kpi_name') or ''
                summary_state['sibling_kpi_name'] = fallback_entry.get('sibling_kpi_name') or ''
                summary_state['measurement_fallback'] = {
                    'original_edge_label': original_label,
                    'original_from_label': original_from_label,
                    'original_action_set_id': original_action_set_id,
                    'measured_edge_label': selected_label,
                    'measured_from_label': from_label,
                    'measured_action_set_id': selected_action_set_id,
                    'sibling_node_label': sibling_node_label,
                    # Sentinel 0 == "swapped during initial setup, before
                    # iteration 1". The summary report renders this case
                    # with different wording from the iteration-loop swap.
                    'swapped_at_iteration': 0,
                    'reason': (
                        f"Initial setup landed on conditional sibling "
                        f"'{sibling_node_label}' instead of "
                        f"'{original_from_label}'. Measuring "
                        f"'{selected_label}' (sibling's outbound edge to "
                        f"the same destination) for all {args.iterations} "
                        f"iterations instead of aborting."
                    ),
                }
                fallback_used = True
                # iter_total is NOT bumped: no iterations were consumed by
                # the setup swap (unlike the iteration-loop swap where the
                # failed iteration counts toward the bump).
                print(
                    f"🔀 [kpi_measurement] Setup-time fallback engaged: "
                    f"'{original_label}' source unreachable on this device — "
                    f"measuring '{selected_label}' from sibling "
                    f"'{sibling_node_label}' instead. Continuing with "
                    f"{args.iterations} iterations from here."
                )
            else:
                if sibling_node_label:
                    context.error_message = (
                        f"Initial setup failed: could not reach "
                        f"'{from_label}'. Device landed on sibling "
                        f"'{sibling_node_label}' but no "
                        f"'{sibling_node_label} → {to_label}' edge exists "
                        f"in the action_set map to fall back to."
                    )
                else:
                    context.error_message = f"Initial setup failed: could not reach '{from_label}'"
                print(f"❌ [kpi_measurement] {context.error_message}")
                return False
        else:
            print(f"✅ [kpi_measurement] Reached '{from_label}' — ready to iterate")

    # From here on we are actually issuing nav→DB measurements; let the
    # summary surface DB-related warnings (e.g. post-processing still
    # running). Anything earlier than this (no edges, bad --edge label,
    # initial setup nav failed) keeps `measurement_attempted` False, so
    # the summary shows just the error instead of a misleading DB hint.
    summary_state['measurement_attempted'] = True

    # `fallback_used` + `iter_total` are declared above the initial-setup
    # block so the setup nav can also engage the conditional-sibling swap.
    # If swap fires inside the iteration loop below (the user picked an
    # edge whose `to_label` is a conditional target, e.g.
    # `replay → replay_asset`), iter_total grows by the iterations already
    # consumed on the unreachable edge so the sibling still gets the
    # requested measurement count. Example (--iterations 3, swap at
    # iteration 1): iter_total bumps from 3 → 4, so iters 2/3/4 all run on
    # the sibling, yielding three sibling measurements.

    i = 0
    while i < iter_total:
        print(f"\n{'='*60}")
        # `iter_total` is the live total so the running counter stays
        # truthful after a fallback bump (3-iteration runs print "1/3 …
        # 4/4" instead of a misleading "4/3").
        print(f"🔄 [kpi_measurement] Iteration {i+1}/{iter_total}")
        print(f"{'='*60}")

        # FORWARD: from_label → to_label (KPI measured for selected action_set)
        print(f"⏱️  [kpi_measurement] Forward: '{from_label}' → '{to_label}'")
        to_result = asyncio.run(device.navigation_executor.execute_navigation(
            tree_id=context.tree_id,
            userinterface_name=context.userinterface_name,
            target_node_label=to_label,
            team_id=context.team_id,
            context=context
        ))

        if to_result.get('success', False):
            navigation_success_count += 1
            # transitions_executed==0 means the executor short-circuited
            # (already-at-target / position-tracking-bug) and pressed no key,
            # so no edge was traversed and no KPI was queued for this leg.
            if to_result.get('transitions_executed', 0) == 0:
                # Don't accept the skip — it leaves the iteration with no KPI.
                # Two cases:
                #  - Real source node: unblock by going to the reverse node first
                #    (moves the device off the destination), then retry the forward
                #    so the edge actually executes and gets measured.
                #  - ENTRY source: ENTRY is virtual — there's nothing to walk back
                #    to, so instead FORCE the ENTRY → to_label edge via a
                #    pre-computed navigation_path, which bypasses the
                #    already-at-target short-circuit.
                # Either way only helps when the edge can actually run; if two real
                # nodes verify identically the retry short-circuits again and we
                # record a genuine skip.
                if from_label.upper() != 'ENTRY':
                    print(
                        f"⚠️  [kpi_measurement] Iteration {i+1} forward SKIPPED — "
                        f"device already at '{to_label}'. Going to reverse "
                        f"'{from_label}' to unblock, then retrying forward."
                    )
                    asyncio.run(device.navigation_executor.execute_navigation(
                        tree_id=context.tree_id,
                        userinterface_name=context.userinterface_name,
                        target_node_label=from_label,
                        team_id=context.team_id,
                        context=context
                    ))
                    to_result = asyncio.run(device.navigation_executor.execute_navigation(
                        tree_id=context.tree_id,
                        userinterface_name=context.userinterface_name,
                        target_node_label=to_label,
                        team_id=context.team_id,
                        context=context
                    ))
                else:
                    forward_step = selected.get('edge_step')
                    if forward_step and forward_step.get('to_node_label') == to_label:
                        print(
                            f"⚠️  [kpi_measurement] Iteration {i+1} forward SKIPPED — "
                            f"already at '{to_label}' and source is ENTRY (virtual). "
                            f"Forcing the '{from_label} → {to_label}' edge."
                        )
                        to_result = asyncio.run(device.navigation_executor.execute_navigation(
                            tree_id=context.tree_id,
                            userinterface_name=context.userinterface_name,
                            target_node_label=to_label,
                            navigation_path=[forward_step],
                            team_id=context.team_id,
                            context=context
                        ))

                if to_result.get('success', False) and to_result.get('transitions_executed', 0) > 0:
                    print(f"✅ [kpi_measurement] Iteration {i+1} forward SUCCESS (after reverse unblock)")
                else:
                    forward_skipped_count += 1
                    print(
                        f"⚠️  [kpi_measurement] Iteration {i+1} forward still SKIPPED "
                        f"after reverse unblock — '{from_label}' and '{to_label}' "
                        f"likely verify identically (no edge traversed, no KPI queued)"
                    )
            else:
                print(f"✅ [kpi_measurement] Iteration {i+1} forward SUCCESS")
        else:
            print(f"❌ [kpi_measurement] Iteration {i+1} forward FAILED")

            # Conditional-sibling fallback. Only triggers when:
            #   1. We haven't already swapped this run (fallback_used).
            #   2. No forward iteration has succeeded yet — if the original
            #      edge has ever worked, this failure is transient noise, not
            #      a structural reachability problem.
            #   3. The host reported a known sibling landing (sibling_landed_*
            #      fields in error_details, added when sibling verification
            #      passed but no graph path back to the requested target was
            #      found).
            #   4. We can resolve the sibling's outbound edge from the same
            #      source in our action_set_map. If we can't, the dropdown
            #      can't actually let the user select it post-fact either, so
            #      bailing is honest.
            err = to_result.get('error_details') or {}
            sibling_node_label = err.get('sibling_landed_node_label')
            sibling_from_node_label = err.get('failed_step_from_node_label')
            # Record the sibling we landed on (if any) so the summary can name it
            # on the forward sibling-skip row. This forward failure produces a
            # "skipped: live destination verification failed" KPI row; the DB row
            # has no sibling label, so this in-memory observation is the only
            # source. Captured for every forward failure, not just fallback ones.
            if sibling_node_label:
                summary_state.setdefault('forward_sibling_labels', []).append(sibling_node_label)
            if (
                not fallback_used
                and navigation_success_count == 0
                and sibling_node_label
                and sibling_from_node_label
            ):
                fallback_entry = edges_by_endpoints.get(
                    (sibling_from_node_label, sibling_node_label)
                )
                if fallback_entry:
                    original_label = selected_label
                    original_to_label = to_label
                    original_action_set_id = selected_action_set_id
                    # Swap to the sibling edge for the remaining iterations.
                    to_label = fallback_entry['to_node']
                    selected_action_set_id = fallback_entry['action_set_id']
                    sibling_action_set_id = fallback_entry.get('sibling_action_set_id') or ''
                    selected_label = fallback_entry['label']
                    sibling_label = fallback_entry.get('sibling_label') or ''
                    # Update the result-filtering set so the post-loop DB
                    # query keeps both the original (this iteration's failed
                    # row) AND the new sibling-edge rows. Otherwise the
                    # summary would drop the iteration-1 failure entirely.
                    relevant_action_set_ids = {selected_action_set_id, original_action_set_id}
                    if sibling_action_set_id:
                        relevant_action_set_ids.add(sibling_action_set_id)
                    forward_action_set_ids = {selected_action_set_id}
                    reverse_action_set_ids = set()
                    # Poll must wait for the swapped-in edge's row (see recovered_forward_ids).
                    recovered_forward_ids = {selected_action_set_id}
                    summary_state['forward_action_set_ids'] = forward_action_set_ids
                    summary_state['reverse_action_set_ids'] = reverse_action_set_ids
                    # Reflect the swap in summary_state so the report can
                    # render it AND so the final filter / metrics use the
                    # NEW action_set_id.
                    summary_state['to_label'] = to_label
                    summary_state['selected_action_set_id'] = selected_action_set_id
                    summary_state['sibling_action_set_id'] = sibling_action_set_id
                    summary_state['selected_label'] = selected_label
                    summary_state['sibling_label'] = sibling_label
                    summary_state['selected_kpi_name'] = fallback_entry.get('kpi_name') or ''
                    summary_state['sibling_kpi_name'] = fallback_entry.get('sibling_kpi_name') or ''
                    summary_state['measurement_fallback'] = {
                        'original_edge_label': original_label,
                        'original_to_label': original_to_label,
                        'original_action_set_id': original_action_set_id,
                        'measured_edge_label': selected_label,
                        'measured_to_label': to_label,
                        'measured_action_set_id': selected_action_set_id,
                        'sibling_node_label': sibling_node_label,
                        'swapped_at_iteration': i + 1,
                        'reason': (
                            f"Conditional sibling detected: device landed on "
                            f"'{sibling_node_label}' instead of "
                            f"'{original_to_label}'. Swapping measurement to "
                            f"the sibling's edge for the remaining iterations."
                        ),
                    }
                    fallback_used = True
                    # Bump the loop's total so the sibling edge still gets
                    # exactly `args.iterations` forward measurements. The
                    # original-edge failure at iter `i+1` does NOT count
                    # toward the sibling's quota, so we add (i+1) extra
                    # iterations onto the back of the loop. With today's
                    # constraints (swap only when no forward has succeeded
                    # yet) this is always +1.
                    iter_total += i + 1
                    print(
                        f"🔀 [kpi_measurement] Conditional fallback engaged: "
                        f"'{original_label}' unreachable on this device — "
                        f"measuring '{selected_label}' instead from iteration "
                        f"{i+1} onwards. Total iterations bumped to "
                        f"{iter_total} so '{selected_label}' gets the "
                        f"requested {args.iterations} measurements."
                    )
                else:
                    print(
                        f"⚠️  [kpi_measurement] Sibling '{sibling_node_label}' "
                        f"landed but no '{sibling_from_node_label} → "
                        f"{sibling_node_label}' edge exists in the action_set "
                        f"map — cannot fall back; continuing with original "
                        f"edge."
                    )
            # Don't bail: still attempt reverse so the device returns to from_label
            # for the next iteration's forward to have a chance.

        # Conditional-SOURCE recovery. The executor auto-recovers when the planned
        # source resolves to a conditional sibling (e.g. replay_asset shows
        # Resume/Watch → replay_asset_resume) and measures `<sibling> → to_label`,
        # recording the KPI under the sibling's action_set while returning SUCCESS.
        # This is NORMAL for resume/watch assets: once Resume shows it stays sticky,
        # so from here we treat the sibling AS the source — both the reverse and the
        # subsequent forwards run and verify on the sibling edges. We accept the
        # recovered edges as the measurement and surface ONE warning; the rest of the
        # summary then looks exactly like a normal successful run.
        if to_result.get('success', False):
            _nav_path = to_result.get('navigation_path') or []
            _final_step = _nav_path[-1] if _nav_path else {}
            _rec_id = _final_step.get('action_set_id')
            # Enrich the id→label map from the ACTUAL traversed steps, so a spliced
            # recovery hop that isn't in the validation sequence (e.g. an internal
            # continuation edge) still gets a readable "from → to" title in its
            # summary block instead of a bare action_set_id.
            for _step in _nav_path:
                _sid = _step.get('action_set_id')
                if _sid and _sid not in action_set_labels:
                    action_set_labels[_sid] = {
                        'label': _step.get('label', ''),
                        'kpi_name': '',
                        'from': _step.get('from_node_label', ''),
                        'to': _step.get('to_node_label', ''),
                    }
            # Accept the edge ACTUALLY measured (direct or recovered), so duplicate
            # ids and recovered sources both count toward the forward KPI.
            if _rec_id:
                forward_action_set_ids.add(_rec_id)
                relevant_action_set_ids.add(_rec_id)
            # First time the source resolves to a conditional sibling, make that
            # sibling the source: the reverse + subsequent forwards then run and
            # verify on the sibling (resume/watch is sticky). One warning; the rest
            # of the summary then reads exactly like a normal success.
            if _final_step.get('is_recovery') and not source_recovered:
                source_recovered = True
                _rec_from = _final_step.get('recovered_from_node_label') or '?'
                from_label = _rec_from
                _fwd = edges_by_endpoints.get((_rec_from, to_label)) or {}
                selected_action_set_id = _fwd.get('action_set_id') or _rec_id or selected_action_set_id
                selected_label = _fwd.get('label') or _final_step.get('label') or selected_label
                # Attribute the recovered continuation edge (e.g. disney_profile →
                # disney_home) to the forward KPI. The executor records this hop's
                # row under the tree edge's action_set_id; splicing may leave the
                # nav-path final step's id blank/different, so relying on _rec_id
                # alone previously dropped the whole hop as "unrelated". Adding the
                # tree-resolved id makes the row count toward the verdict AND get
                # its own summary block.
                if selected_action_set_id:
                    forward_action_set_ids.add(selected_action_set_id)
                    relevant_action_set_ids.add(selected_action_set_id)
                    # The DB poll must wait for THIS edge's row — the selected
                    # edge's own row is a fast skip that would otherwise satisfy
                    # the forward count before this measurement is post-processed.
                    recovered_forward_ids.add(selected_action_set_id)
                summary_state.setdefault('recovered_sources', [])
                if _rec_from not in summary_state['recovered_sources']:
                    summary_state['recovered_sources'].append(_rec_from)
                summary_state['from_label'] = from_label
                summary_state['selected_action_set_id'] = selected_action_set_id
                summary_state['selected_label'] = selected_label
                summary_state['selected_kpi_name'] = _fwd.get('kpi_name') or summary_state.get('selected_kpi_name') or ''
                print(
                    f"🔀 [kpi_measurement] Iteration {i+1}: source recovered to "
                    f"sibling '{_rec_from}' (resume/watch is sticky). Measuring sibling "
                    f"edges from here; reverse returns to '{_rec_from}' normally."
                )

        # REVERSE: to_label → from_label (KPI measured for sibling action_set
        # if one exists; otherwise pathfinding takes whatever route is available).
        # Skip when from_label is ENTRY — we can't "return" to a virtual node.
        # Also skip for single-iteration runs: the reverse exists only to reset
        # the device to from_label so the NEXT iteration's forward has a chance —
        # with iter_total == 1 there is no next forward, so the reverse is pure
        # wasted navigation (a full walk back) whether the forward passed or
        # failed. (This means a 1-iteration run measures only the selected
        # direction, never the reverse.)
        if from_label.upper() != 'ENTRY' and iter_total > 1:
            print(f"↩️  [kpi_measurement] Reverse: '{to_label}' → '{from_label}'")
            back_result = asyncio.run(device.navigation_executor.execute_navigation(
                tree_id=context.tree_id,
                userinterface_name=context.userinterface_name,
                target_node_label=from_label,
                team_id=context.team_id,
                context=context
            ))
            if back_result.get('success', False):
                if back_result.get('transitions_executed', 0) == 0:
                    reverse_skipped_count += 1
                    print(
                        f"⚠️  [kpi_measurement] Iteration {i+1} reverse SKIPPED "
                        f"— device already at '{from_label}', no edge traversed "
                        f"(no KPI queued)"
                    )
                else:
                    # Accept the edge the reverse ACTUALLY measured (covers a reverse
                    # that itself recovered to the sibling, and duplicate ids). This is
                    # what the KPI row is recorded under, so the summary + report link
                    # reference the real reverse edge — never a guessed/failed main one.
                    _rb = back_result.get('navigation_path') or []
                    _rb_final = _rb[-1] if _rb else {}
                    _rev_id = _rb_final.get('action_set_id')
                    if _rev_id:
                        reverse_action_set_ids.add(_rev_id)
                        relevant_action_set_ids.add(_rev_id)
                        sibling_action_set_id = _rev_id
                        sibling_label = _rb_final.get('label') or sibling_label
                        summary_state['sibling_action_set_id'] = sibling_action_set_id
                        summary_state['sibling_label'] = sibling_label
                        reverse_success_count += 1
                        if _rb_final.get('is_recovery'):
                            _rb_from = _rb_final.get('recovered_from_node_label')
                            summary_state.setdefault('recovered_sources', [])
                            if _rb_from and _rb_from not in summary_state['recovered_sources']:
                                summary_state['recovered_sources'].append(_rb_from)
                    print(f"✅ [kpi_measurement] Iteration {i+1} reverse SUCCESS")
            else:
                print(f"⚠️  [kpi_measurement] Iteration {i+1} reverse FAILED")

        # `while`/manual-increment instead of `for i in range(...)` because
        # iter_total may have grown mid-loop on the conditional-sibling
        # fallback bump above.
        i += 1

    print(f"\n{'='*60}")
    print(f"🎉 [kpi_measurement] Completed {iter_total} iterations")
    print(f"📊 [kpi_measurement] Navigation success: {navigation_success_count}/{iter_total}")
    if forward_skipped_count or reverse_skipped_count:
        print(
            f"⚠️  [kpi_measurement] Skipped (already-at-target, no edge "
            f"traversed → no KPI): {forward_skipped_count} fwd, "
            f"{reverse_skipped_count} rev"
        )
    print(f"{'='*60}")
    
    # Poll the DB until every iteration's measurement has been post-processed.
    # vpt-kpi.service patches `execution_results.kpi_measurement_ms` async
    # after the navigation returns, so a fixed sleep can miss the final
    # iteration when post-processing lags. Loop returns as soon as we have
    # args.iterations matching rows; falls through after max_wait_seconds.
    # Wait for BOTH forward and (if sibling exists) reverse measurements.
    # Exiting the poll early on forward-only count caused the last reverse to
    # be missed when post-processing for it landed after the script left.
    # `iter_total` is the live loop count after any conditional-sibling
    # fallback bump (see while-loop above). The sibling forward edge gets
    # `args.iterations` rows (the swap-iteration failure produces a row on
    # the ORIGINAL action_set_id, not the new one, and we bumped iter_total
    # to compensate). The reverse edge gets one row per iteration that
    # actually ran a reverse leg = iter_total.
    expected_forward = args.iterations
    # Wait for exactly the reverse legs that actually traversed an edge (queued a KPI).
    expected_reverse = reverse_success_count
    print(f"\n⏳ [kpi_measurement] Polling DB for KPI post-processing (expect {expected_forward} fwd + {expected_reverse} rev)...")
    # Poll budget scales with the measured edge's traversal wait — the executor
    # waits up to the timeout window before scanning, so a long edge (reboot ~90s)
    # legitimately produces its KPI row much later than a short nav. Floor 60s keeps
    # short edges failing fast; long edges get wait+60s. The loop still exits the
    # instant all rows are present, so a larger cap is free for the common case and
    # only stops slow KPIs from being declared "no measurements" prematurely.
    _rev_entry = edges_by_endpoints.get((to_label, from_label)) or {}
    _longest_wait_s = max(selected.get('wait_ms', 0), _rev_entry.get('wait_ms', 0)) / 1000.0
    max_wait_seconds = max(60, int(_longest_wait_s) + 60)
    poll_interval = 3
    elapsed = 0
    kpi_db_results = []
    script_end_time = datetime.now(timezone.utc)
    while elapsed < max_wait_seconds:
        time.sleep(poll_interval)
        elapsed += poll_interval
        script_end_time = datetime.now(timezone.utc)
        kpi_db_results = _fetch_kpi_results_from_db(
            team_id=context.team_id,
            device_name=device.device_name,
            start_time=script_start_time,
            end_time=script_end_time,
        )
        fwd_count = sum(1 for r in kpi_db_results if r.get('action_set_id') in forward_action_set_ids)
        rev_count = sum(1 for r in kpi_db_results if reverse_action_set_ids and r.get('action_set_id') in reverse_action_set_ids)
        # When a recovery/fallback diverted the measurement, the selected edge's
        # own row is a fast SKIP that satisfies fwd_count on the first poll — but
        # the REAL measurement is the recovered edge, whose row the single worker
        # stores ~10-15s later. Require a row under every recovered id before
        # declaring the forward legs complete, so we don't exit on the skip alone.
        rec_present = all(
            any(r.get('action_set_id') == rid for r in kpi_db_results)
            for rid in recovered_forward_ids
        )
        rec_note = f", recovered {sum(1 for rid in recovered_forward_ids if any(r.get('action_set_id') == rid for r in kpi_db_results))}/{len(recovered_forward_ids)}" if recovered_forward_ids else ""
        print(f"   [{elapsed}s] fwd {fwd_count}/{expected_forward}, rev {rev_count}/{expected_reverse}{rec_note} (total fetched: {len(kpi_db_results)})")
        if fwd_count >= expected_forward and rev_count >= expected_reverse and rec_present:
            print(f"✅ [kpi_measurement] All measurements present after {elapsed}s")
            break
    else:
        print(f"⚠️  [kpi_measurement] Timed out waiting for KPI post-processing after {max_wait_seconds}s — proceeding with partial results")
    print(f"   Time range: {script_start_time.isoformat()} to {script_end_time.isoformat()}")
    
    # Filter the printout to the selected action_set + its reverse so the
    # report stays focused on the transition under test. Incidental rows
    # (e.g. entry_to_home from the initial walk) are still in kpi_db_results
    # for the downstream count check, just not shown here.
    relevant_results = [
        r for r in kpi_db_results if r.get('action_set_id') in relevant_action_set_ids
    ]
    summary_state['relevant_results'] = relevant_results

    print(f"\n{'='*60}")
    print(f"📊 [kpi_measurement] RAW DATABASE FETCH RESULTS:")
    print(f"{'='*60}")
    print(f"Total KPI measurements found: {len(relevant_results)} (filtered from {len(kpi_db_results)})")

    if relevant_results:
        print(f"\nAll fetched KPI measurements:")
        for idx, result in enumerate(relevant_results, 1):
            action_set = result.get('action_set_id', 'N/A')
            kpi_ms = result.get('kpi_measurement_ms', 'N/A')
            success = result.get('kpi_measurement_success', False)
            executed = result.get('executed_at', 'N/A')
            report_url = result.get('kpi_report_url') or ''
            status_icon = "✅" if success else "❌"
            report_part = f", report: {report_url}" if report_url else ""
            print(f"  {idx}. {status_icon} action_set: {action_set}, KPI: {kpi_ms}ms, time: {executed}{report_part}")
    else:
        print(f"⚠️  No KPI measurements found for selected action_set or its reverse")
    
    print(f"{'='*60}\n")
    
    # Filter KPI results to the accepted forward action_set(s): the selected edge
    # plus any sibling edge the executor auto-recovered to (conditional source).
    filtered_kpi_results = [
        r for r in kpi_db_results
        if r.get('action_set_id') in forward_action_set_ids
    ]

    print(f"🔍 [kpi_measurement] Filtering for forward action_set(s): {sorted(forward_action_set_ids)}")
    print(f"📊 [kpi_measurement] Filtered results: {len(filtered_kpi_results)}/{len(kpi_db_results)} match the forward action_set(s)")

    # Calculate overall success using filtered results
    successful_kpis = sum(1 for r in filtered_kpi_results if r.get('kpi_measurement_success'))
    # Sibling-skips (destination verifier failed → device landed on a sibling)
    # are an EXPECTED outcome, not a failure: they're excluded from both the
    # required-success count and the failure check below.
    skipped_kpis = sum(1 for r in filtered_kpi_results if _is_kpi_skip(r))
    hard_failed_kpis = len(filtered_kpi_results) - successful_kpis - skipped_kpis
    # `args.iterations` is the contract: that's the number of measurable
    # iterations the user asked for. With or without fallback we now run
    # the loop long enough to produce that many rows for the actually-
    # measured edge.
    expected_count = args.iterations

    print(f"📊 [kpi_measurement] KPI Results: {successful_kpis}/{len(filtered_kpi_results)} successful "
          f"({skipped_kpis} skipped, {hard_failed_kpis} failed)")
    print(f"🎯 [kpi_measurement] Expected: {expected_count} iterations, Got: {len(filtered_kpi_results)} matching KPIs")

    # Success when we recorded the expected number of rows, none of them are
    # hard failures, and at least one real measurement landed. Sibling-skips
    # don't count against us, so they reduce the required success count rather
    # than fail the run — landing on a conditional sibling is normal.
    context.overall_success = (
        len(filtered_kpi_results) >= expected_count
        and hard_failed_kpis == 0
        and successful_kpis >= 1
        and successful_kpis >= (expected_count - skipped_kpis)
    )

    # Explain WHY when we came up short, so the report shows the real cause
    # instead of the generic "post-processing may still be in progress" hint.
    # Don't clobber an error already set upstream (e.g. setup-nav failure).
    if not context.overall_success and not context.error_message:
        if forward_skipped_count >= args.iterations:
            # Every forward leg short-circuited: no edge ever ran, so KPI
            # measurement is structurally impossible until the nodes are
            # made distinguishable.
            context.error_message = (
                f"No KPI could be measured for '{selected_label}'. All "
                f"{forward_skipped_count}/{args.iterations} forward navigations "
                f"were SKIPPED because the device was already at '{to_label}' "
                f"(the executor's already-at-target check passed). That means "
                f"'{from_label}' and '{to_label}' verify as PASS on the same "
                f"screen — their verifications are not distinctive — so no edge "
                f"is traversed and no KPI is queued. Fix: give '{to_label}' "
                f"(and/or '{from_label}') a verification that only passes on "
                f"that screen (avoid matching persistent menu-bar text/icons "
                f"shared by both nodes)."
            )
        elif forward_skipped_count > 0:
            context.error_message = (
                f"Only {len(filtered_kpi_results)}/{expected_count} KPI "
                f"measurements recorded for '{selected_label}': "
                f"{forward_skipped_count}/{args.iterations} forward navigations "
                f"were SKIPPED (device already at '{to_label}' — likely "
                f"non-distinctive verifications between '{from_label}' and "
                f"'{to_label}'). Skipped navigations traverse no edge and queue "
                f"no KPI."
            )
        elif navigation_success_count >= iter_total and len(kpi_db_results) > 0:
            # Navigations actually ran (keys pressed) but no rows landed for
            # the selected action_set — measurement plumbing problem, not a
            # navigation problem.
            context.error_message = (
                f"Navigations ran but produced no KPI rows for '{selected_label}' "
                f"({len(kpi_db_results)} unrelated KPI row(s) recorded in the "
                f"window). The measured edge may execute zero actions, or its "
                f"action_set_id differs from the selected one — check the "
                f"navigation tree."
            )
        else:
            context.error_message = (
                f"KPI post-processing produced no measurements for "
                f"'{selected_label}' within {max_wait_seconds}s "
                f"({successful_kpis}/{expected_count} successful). If the "
                f"navigations succeeded, vpt-kpi.service may be lagging or not "
                f"running on this host."
            )
        print(f"❌ [kpi_measurement] {context.error_message}")

    return context.overall_success


@script("kpi_measurement", "Measure KPIs for specific navigation edge", default_device="device1")
def main():
    """Run KPI measurement; always emit an execution summary for the report.

    The summary (incl. Interface + Variant) is built in `finally` so it is
    produced on every exit path — success, early `return False`, or
    exception — matching validation.py. Previously the summary was only set
    on the final success path, so any early failure (no edges, bad --edge
    label, setup navigation failed) left the report showing
    "Execution summary not available".
    """
    args = get_args()
    context = get_context()
    device = get_device()

    # Resolve the active variant the same way _get_available_edges does
    # (device.navigation_context is canonical; args is the fallback).
    variant = None
    if device is not None and getattr(device, 'navigation_context', None):
        variant = device.navigation_context.get('variant')
    if not variant:
        variant = getattr(args, 'variant', None)
    if isinstance(variant, str):
        variant = variant.strip() or None

    # Pre-seeded so capture_kpi_summary can always render, even if the run
    # aborts before the edge is resolved. _run_kpi_measurement fills these
    # in as soon as each value is known.
    summary_state = {
        'from_label': '',
        'to_label': '',
        'relevant_results': [],
        'selected_action_set_id': '',
        'sibling_action_set_id': '',
        'selected_label': args.edge or '',
        'sibling_label': '',
        # Friendly KPI display names (Edge Edit dialog → action_set.kpi_name).
        # Empty until the edge resolves; preferred over the labels in the report.
        'selected_kpi_name': '',
        'sibling_kpi_name': '',
        # Flipped True once iteration starts. Keeps the summary from
        # claiming "post-processing may still be in progress" when we
        # never even reached the start node.
        'measurement_attempted': False,
        # Populated by _run_kpi_measurement when conditional-sibling
        # fallback engages mid-run. None means the run measured the
        # originally-selected edge cleanly.
        'measurement_fallback': None,
        # Sibling node labels observed on forward-nav failures (destination
        # verifier failed). Used only to NAME the sibling on the forward
        # sibling-skip rows in the summary; not all entries map 1:1 to rows.
        'forward_sibling_labels': [],
        # Accepted forward action_set(s); _run_kpi_measurement sets this to the live
        # set (selected edge + any auto-recovered sibling edge) so the summary's
        # forward/reverse split matches the filter used for success.
        'forward_action_set_ids': None,
        # Accepted reverse action_set(s), same idea for the reverse leg.
        'reverse_action_set_ids': None,
        # Conditional-source sibling labels recovered to during the run (e.g.
        # replay_asset_resume). Drives the single recovered-source warning line.
        'recovered_sources': [],
        # action_set_id → {label, kpi_name, from, to} for every edge in the tree,
        # so the summary can title each traversed hop's KPI block independently.
        'action_set_labels': {},
    }

    try:
        return _run_kpi_measurement(context, args, device, summary_state)
    finally:
        # Closure first (may add screenshots / execution time), then the
        # summary so it reflects the final state. Non-fatal by design.
        # Executes the user-selected --closing_edge; empty = leave device as-is.
        _goto_closing_edge_closure(context, device, getattr(args, 'closing_edge', ''))
        context.execution_summary = capture_kpi_summary(
            context,
            context.userinterface,
            args.edge,
            summary_state['from_label'],
            summary_state['to_label'],
            args.iterations,
            summary_state['relevant_results'],
            summary_state['selected_action_set_id'],
            summary_state['sibling_action_set_id'],
            selected_label=summary_state['selected_label'],
            sibling_label=summary_state['sibling_label'],
            selected_kpi_name=summary_state['selected_kpi_name'],
            sibling_kpi_name=summary_state['sibling_kpi_name'],
            variant=variant or '',
            measurement_attempted=summary_state['measurement_attempted'],
            # None when the run never had to swap; set by the iteration loop
            # in _run_kpi_measurement the moment a known-sibling failure
            # triggers the swap.
            measurement_fallback=summary_state.get('measurement_fallback'),
            # Sibling labels seen on forward failures — names the sibling on
            # the forward sibling-skip rows in the summary.
            forward_sibling_labels=summary_state.get('forward_sibling_labels'),
            # Accepted forward action_set(s) incl. any auto-recovered sibling edge.
            forward_action_set_ids=summary_state.get('forward_action_set_ids'),
            # Accepted reverse action_set(s) incl. the recovered sibling's reverse edge.
            reverse_action_set_ids=summary_state.get('reverse_action_set_ids'),
            # Sibling(s) the source recovered to → single warning line.
            recovered_sources=summary_state.get('recovered_sources'),
            # id→label map so each traversed hop gets its own titled KPI block.
            action_set_labels=summary_state.get('action_set_labels'),
        )


# Assign script args to main function
main._script_args = _script_args
main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "all",
}

if __name__ == "__main__":
    main()
