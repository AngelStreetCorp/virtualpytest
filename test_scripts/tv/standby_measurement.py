#!/usr/bin/env python3
"""
Standby Wake-Time Measurement Script for VirtualPyTest

Measures the KPI timing of the `standby → live` transition (how long the STB
takes to show live TV again after being woken from standby), for a configurable
standby mode and a configurable dwell time in standby.

This is a focused sibling of kpi_measurement.py. Instead of resolving an edge
from the RunTests dropdown and pairing forward/reverse, it drives a fixed
power-cycle and reuses kpi_measurement's DB-fetch + reporting helpers so the
output looks identical and we don't fork the KPI plumbing.

The live↔standby edge is chosen via the RunTests `--edge` dropdown (the same
KPI edge selector kpi_measurement uses), filtered to edges whose label contains
both "live" and "standby". The standby and live node labels are recovered from
that edge; the timed transition is always the `standby → live` (wake) direction.

Workflow:
1. (precondition, once) goto(<standby_mode_node>) to select the standby mode in
   Settings — skipped when --standby_mode_node is empty. Defaults to the `fast`
   standby mode.
2. goto(<live_node>) to establish a known baseline before cycling.
3. For each iteration:
     a. goto(<standby_node>)            → traverses the `live → standby` edge (POWER)
     b. wait --wait minutes             → dwell in standby
     c. goto(<live_node>)               → traverses the `standby → live` edge (POWER),
                                           which auto-queues the KPI measurement
4. Poll execution_results until the `standby → live` measurements are
   post-processed by vpt-kpi.service, then fetch + summarize min/max/avg.

The actual timing is produced by the standard KPI pipeline (kpi_executor) — this
script never times anything itself. That requires the `standby → live` action
set to anchor a KPI reference (explicit kpi_references, or use_verifications_for_kpi
with at least one verification on the destination `live` node).

Usage:
    python test_scripts/tv/standby_measurement.py <userinterface_name> \
        --edge "<live → standby label>" --wait <minutes> --iterations <count>

The --edge dropdown offers only the edge whose target is standby
("live → standby"); the wake direction (standby → live) it measures is derived
internally. The reverse edge isn't separately selectable.

Examples:
    python test_scripts/tv/standby_measurement.py example_tv \
        --edge "live → standby" --wait 1 --iterations 5
    python test_scripts/tv/standby_measurement.py example_tv \
        --edge "live → standby" --standby_mode_node settings_system_standby_eco \
        --wait 5 --iterations 3
"""

import sys
import os
import time
import asyncio
from datetime import datetime, timezone

# Add project root to path (this script lives in test_scripts/tv/, so the repo
# root is two levels up).
current_dir = os.path.dirname(os.path.abspath(__file__))      # test_scripts/tv
test_scripts_dir = os.path.dirname(current_dir)               # test_scripts
project_root = os.path.dirname(test_scripts_dir)              # repo root
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# kpi_measurement.py lives in test_scripts/ (the parent dir, not a package), so
# add it to the path to reuse its helpers. Reuse > fork: same DB fetch + report.
if test_scripts_dir not in sys.path:
    sys.path.insert(0, test_scripts_dir)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device
import kpi_measurement as km


# Script arguments - defined early for backend parameter detection (within first 300 lines)
_script_args = [
    '--userinterface:str:example_tv',    # Framework param with default
    '--variant:str:',                     # Optional named variant; empty = base
    # Precondition node selecting the standby mode. RunTests renders a node
    # picker filtered to nodes that carry a friendly display name
    # (data.display_name, e.g. "TC266 Eco ColdStandby"); that display name — not
    # the raw node label — names the measurement in the report, because the
    # measured wake edge is identical for every mode. Empty = mode unchanged.
    # NOTE: keep square brackets OUT of comments inside this list — the param
    # analyzer captures the list with a non-greedy regex that stops at the first
    # closing bracket.
    '--standby_mode_node:str:',
    # live↔standby edge (action_set label). RunTests renders a KPI edge dropdown
    # filtered to labels containing both "live" and "standby". The standby/live
    # node labels are recovered from this; the wake (standby → live) is measured.
    '--edge:str:',
    '--wait:int:1',                       # Minutes to dwell in standby before waking
    '--iterations:int:3',                 # Number of wake measurements
]
_script_description = "Measure standby → live wake KPI for a given standby mode and dwell time."
_arg_descriptions = {
    'userinterface': 'UI interface name',
    'variant': "Optional variant name; if omitted, base data is used.",
    'standby_mode_node': 'Standby mode node to select before measuring; its display name names the run.',
    'edge': 'live→standby edge (target is standby); the standby → live wake is what gets timed.',
    'wait': 'Minutes to dwell in standby before waking',
    'iterations': 'Number of wake measurements to take',
}

# Unicode arrow used in action_set labels (e.g. "standby → live").
ARROW = " → "

# Dwelling in standby for at least this long drops the STB into deep/eco
# (cold) standby: the host CPU powers off and the BLE link is torn down, so a
# plain POWER HID press in the wake edge can no longer reach it. At/above this
# threshold we first emit the Broadcom WoBLE cold-wake (see cold_wake_on_press
# in hid_remote.py) and wait for the host to reboot + reconnect, THEN run the
# wake goto whose POWER press lands on a live link. Below it the box is still
# in active standby and the existing auto-wake handles reconnection.
COLD_STANDBY_THRESHOLD_S = 5 * 60
# How long to wait for the woken host to re-establish the BLE link before
# pressing POWER (host boot from S2/S3 + reconnect). Matches the daemon's
# WOBLE_BROADCAST_S + COLD_WAKE_TIMEOUT_S budget with a small margin.
COLD_WAKE_RECONNECT_TIMEOUT_S = 30


def _setup_tree(context, device) -> bool:
    """Resolve the root tree id and warm the navigation cache.

    Mirrors kpi_measurement._get_available_edges' setup (variant resolved from
    device.navigation_context) without the dropdown/validation-sequence machinery.
    """
    from shared.src.lib.database.userinterface_db import get_userinterface_by_name
    from shared.src.lib.database.navigation_trees_db import get_root_tree_for_interface

    userinterface = get_userinterface_by_name(context.userinterface, context.team_id,
                                              mode=getattr(context.args, 'ui_mode', 'dev'))
    if not userinterface:
        context.error_message = f"User interface '{context.userinterface}' not found"
        return False

    root_tree = get_root_tree_for_interface(userinterface['id'], context.team_id)
    if not root_tree:
        context.error_message = f"No root tree found for interface '{context.userinterface}'"
        return False
    context.tree_id = root_tree['id']

    nav_result = device.navigation_executor.load_navigation_tree(
        context.userinterface, context.team_id
    )
    if not nav_result.get('success'):
        context.error_message = "Navigation tree loading failed"
        return False
    return True


def _resolve_action_set_id(context, from_label: str, to_label: str) -> str:
    """Return the action_set id for the `from_label → to_label` direction.

    execution_results.action_set_id equals the action set's `id` in the edge
    JSONB (verified: 'standby_to_live'). We match on the human label first
    (`"standby → live"`) which is how the directions are stored, so the fetched
    KPI rows can be filtered to the wake direction only (the per-iteration
    goto(standby) also produces a `live → standby` row we don't want here).
    """
    from shared.src.lib.database.navigation_trees_db import get_tree_edges

    result = get_tree_edges(context.tree_id, context.team_id)
    if not result.get('success'):
        return ''
    wanted = f"{from_label}{ARROW}{to_label}"
    for edge in result.get('edges', []):
        for action_set in (edge.get('action_sets') or []):
            if action_set.get('label') == wanted:
                return action_set.get('id', '')
    return ''


def _resolve_node_display_name(context, device, node_label: str) -> str:
    """Resolve the node name from the active graph, then fall back to the DB.

    The runtime graph includes variant overrides, while the shared DB helper
    reads the base hierarchy. Prefer the graph so the KPI label matches the
    display name shown by the variant-aware node picker for this run.
    """
    graph = getattr(getattr(device, 'navigation_executor', None), 'unified_graph', None)
    if graph is not None:
        for _node_id, node_data in graph.nodes(data=True):
            if (node_data.get('label') or '') != node_label:
                continue
            metadata = node_data.get('metadata')
            if isinstance(metadata, dict):
                display_name = (metadata.get('display_name') or '').strip()
                if display_name:
                    return display_name

    from shared.src.lib.database.navigation_trees_db import get_node_display_name
    return get_node_display_name(context.tree_id, context.team_id, node_label)


def _resolve_standby_live_nodes(edge_label: str):
    """Split an `A → B` action_set label and classify the standby vs live node.

    The RunTests dropdown is filtered to edges whose label contains both "live"
    and "standby", and action_set labels are built as "{source} → {target}", so
    the two node labels are recoverable by splitting on the arrow. Whichever side
    contains "standby" is the standby node; the other is the live (wake-target)
    node. Returns (standby_node, live_node), or (None, None) if the label is
    malformed or doesn't carry exactly one standby side.
    """
    parts = [p.strip() for p in edge_label.split(ARROW)]
    if len(parts) != 2 or not all(parts):
        return None, None
    a, b = parts
    a_is_standby = 'standby' in a.lower()
    b_is_standby = 'standby' in b.lower()
    if a_is_standby and not b_is_standby:
        return a, b
    if b_is_standby and not a_is_standby:
        return b, a
    return None, None


def _goto(context, device, target_label: str) -> dict:
    """Navigate to a node; returns the raw navigation result dict."""
    return asyncio.run(device.navigation_executor.execute_navigation(
        tree_id=context.tree_id,
        userinterface_name=context.userinterface_name,
        target_node_label=target_label,
        team_id=context.team_id,
        context=context,
    ))


def _cold_wake_before_power(context, device, standby_node) -> None:
    """Wake a deep/cold-standby STB before the measured POWER press.

    Called only when the dwell was ≥ COLD_STANDBY_THRESHOLD_S. The host CPU is
    off and the BLE link gone, so the wake edge's POWER HID press would hit a
    dead link; we first emit the Broadcom WoBLE cold-wake and wait for the host
    to reboot + reconnect. No-op for remotes that don't expose cold_wake (only
    the BLE HID controller does), so non-BLE STBs fall straight through to the
    normal wake goto. Recorded as a step so the extra wake is visible in the
    report.
    """
    remote = device._get_controller('remote') if hasattr(device, '_get_controller') else None
    if not remote or not hasattr(remote, 'cold_wake'):
        # Non-BLE remote (e.g. IR) — nothing to do; the wake goto's POWER
        # press is the only available path.
        return

    print("🌅 [standby_measurement] Deep standby (≥5min) — WoBLE cold-wake before POWER")
    cw_start = datetime.now()
    res = remote.cold_wake() or {}
    if not res.get('success'):
        print(f"⚠️  [standby_measurement] cold_wake request failed: {res.get('error')}")

    # cold_wake() returns as soon as the FIFO sentinel is written; the actual
    # WoBLE broadcast + host reboot happen on the daemon. Poll the link state
    # until the STB is HID-ready so the subsequent POWER press lands live.
    #
    # Gate on hid_ready, NOT connected: after deep standby the box leaves
    # without a clean BLE disconnect, so BlueZ keeps reporting a stale
    # Connected=true from the torn-down session for several seconds. The old
    # `connected` check read that leftover state on the first poll (~2s) and
    # fired POWER into a dead link. hid_ready is the only signal that the Arris
    # HID subscription is actually live and key presses will flow.
    #
    # Use the daemon's RAW StartNotify signal (_read_hid_ready) — NOT
    # get_pairing_status()['hid_ready']. The latter OR's in a CCCD fallback
    # (bluetooth.py: connected + bond-has-HID-CCCD ⇒ hid_ready=true) that fires
    # on a bonded reconnect WITHOUT a fresh StartNotify — the battery-only trap,
    # where keys are silently dropped. The raw file is cleared to false on
    # disconnect (hid_remote.py _clear_subscriptions) and only set true by a
    # genuine StartNotify, so it can't false-positive the POWER press.
    def _hid_ready() -> bool:
        if hasattr(remote, '_read_hid_ready'):
            return bool(remote._read_hid_ready())
        # Fallback for non-Arris controllers without the raw reader.
        return bool((remote.get_pairing_status() or {}).get('hid_ready'))

    hid_ready = False
    deadline = time.time() + COLD_WAKE_RECONNECT_TIMEOUT_S
    while time.time() < deadline:
        time.sleep(2)
        if _hid_ready():
            hid_ready = True
            break
    cw_end = datetime.now()
    print(f"{'✅' if hid_ready else '⚠️ '} [standby_measurement] cold_wake "
          f"{'HID-ready' if hid_ready else 'NOT HID-ready (POWER may be dropped)'} after "
          f"{(cw_end - cw_start).total_seconds():.1f}s")

    context.record_step_immediately({
        'success': hid_ready,
        'message': 'Cold-wake from deep standby (WoBLE)',
        'from_node': standby_node,
        'to_node': standby_node,
        'execution_time_ms': int((cw_end - cw_start).total_seconds() * 1000),
        'start_time': cw_start.strftime('%H:%M:%S'),
        'end_time': cw_end.strftime('%H:%M:%S'),
        'actions': [{'command': 'cold_wake'}],
        'verifications': [],
        'step_category': 'cold_wake',
    })


def capture_standby_summary(context, args, variant, standby_node, live_node,
                            mode_name, measured_action_set_id,
                            measurement_attempted, relevant_results) -> str:
    """Render the execution summary; reuses kpi_measurement's metrics block.

    `standby_node` / `live_node` are resolved from --edge (empty until the edge
    parses), so the summary stays renderable on the early-failure paths.
    `mode_name` is the standby mode's friendly display name (falls back to the
    node label) — it names the measurement, since the wake edge is mode-agnostic.
    """
    wake = f"{standby_node}{ARROW}{live_node}" if standby_node and live_node else (args.edge or '?')
    down = f"{live_node}{ARROW}{standby_node}" if standby_node and live_node else '?'
    lines = []
    lines.append("=" * 60)
    lines.append("📊 [STANDBY MEASUREMENT] EXECUTION SUMMARY")
    lines.append("=" * 60)
    if context.selected_device:
        lines.append(f"📱 Device: {context.selected_device.device_name} ({context.selected_device.device_model})")
    else:
        lines.append("📱 Device: Setup failed - no device selected")
    if context.host:
        lines.append(f"🖥️ Host: {context.host.host_name}")
    else:
        lines.append("🖥️ Host: Setup failed - no host available")
    lines.append(f"📋 Interface: {context.userinterface}")
    lines.append(f"🎨 Variant: {variant or 'base'}")
    if args.standby_mode_node:
        lines.append(f"🏷️ Standby mode: {mode_name}  (node: {args.standby_mode_node})")
    else:
        lines.append("🏷️ Standby mode: (none — mode unchanged)")
    lines.append(f"🔗 Edge: {args.edge or '(none selected)'}")
    lines.append(f"🔁 Cycle: {down} → wait {args.wait}min → {wake}")
    lines.append(f"🎯 Measured edge: {wake}")
    lines.append(f"🔢 Requested Iterations: {args.iterations}")
    lines.append(f"⏱️ Total Script Time: {context.get_execution_time_ms()/1000:.1f}s")
    lines.append("")

    # Name the KPI block by the standby mode display name (the measured wake edge
    # is identical across modes, so the mode is what distinguishes the run).
    metrics_label = f"{mode_name} ({wake})" if args.standby_mode_node else f"{wake} (wake)"
    if relevant_results:
        km._append_direction_metrics(
            lines,
            metrics_label,
            relevant_results,
            args.iterations,
        )
    elif measurement_attempted and not context.error_message:
        lines.append("⚠️  No KPI measurements found in database")
        lines.append("   (Post-processing may still be in progress, or the "
                     f"'{wake}' action set has no KPI reference)")

    lines.append("")
    lines.append(f"📸 Screenshots: {len(context.screenshot_paths)} captured")
    lines.append(f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}")
    if context.error_message:
        lines.append(f"\n❌ Error: {context.error_message}")
    lines.append("=" * 60)
    return "\n".join(lines)


def _run_standby_measurement(context, args, device, state) -> bool:
    wait_seconds = max(0, args.wait) * 60
    print(f"📊 [standby_measurement] Starting standby wake measurement")
    print(f"📱 [standby_measurement] Device: {device.device_name} ({device.device_model})")
    print(f"🔢 [standby_measurement] Iterations: {args.iterations}, dwell: {args.wait}min ({wait_seconds}s)")

    script_start_time = datetime.now(timezone.utc)

    # Resolve the standby / live node labels from the selected edge.
    if not args.edge:
        context.error_message = "No edge selected — pick a live↔standby edge in the --edge dropdown."
        print(f"❌ [standby_measurement] {context.error_message}")
        return False
    standby_node, live_node = _resolve_standby_live_nodes(args.edge)
    if not standby_node or not live_node:
        context.error_message = (
            f"Could not derive a standby/live pair from edge '{args.edge}'. Expected an "
            f"'A → B' label with exactly one side containing 'standby' and the other 'live'."
        )
        print(f"❌ [standby_measurement] {context.error_message}")
        return False
    state['standby_node'] = standby_node
    state['live_node'] = live_node
    print(f"🔀 [standby_measurement] Edge '{args.edge}' → standby='{standby_node}', live='{live_node}'")

    if not _setup_tree(context, device):
        print(f"❌ [standby_measurement] {context.error_message}")
        return False

    # Resolve the wake direction's action_set id so we can filter KPI rows to it.
    measured_action_set_id = _resolve_action_set_id(context, standby_node, live_node)
    if not measured_action_set_id:
        context.error_message = (
            f"Could not resolve the '{standby_node}{ARROW}{live_node}' action set in the "
            f"tree. Check the node labels and that the edge exists."
        )
        print(f"❌ [standby_measurement] {context.error_message}")
        return False
    state['measured_action_set_id'] = measured_action_set_id
    print(f"🔑 [standby_measurement] Wake action_set id: {measured_action_set_id}")

    # Resolve the standby mode's friendly display name. The measured wake edge is
    # identical for every mode, so the run is named by the mode node's
    # data.display_name (e.g. "[TC266] Eco (ColdStandby)"); fall back to the raw
    # node label when unset.
    mode_display = _resolve_node_display_name(context, device, args.standby_mode_node)
    mode_name = mode_display or args.standby_mode_node
    state['mode_name'] = mode_name
    if args.standby_mode_node:
        print(f"🏷️  [standby_measurement] Standby mode: {mode_name}"
              f"{'' if mode_display else ' (no display name set)'}")
        # Forward the mode name to the KPI report header. NavigationExecutor reads
        # this off navigation_context (same channel as `variant`) and threads it
        # into every KPI request queued during this run, so the per-edge KPI
        # report is named by the standby mode (the measured wake edge is identical
        # across modes and can't carry it). Cleared in main()'s finally.
        if getattr(device, 'navigation_context', None) is not None:
            device.navigation_context['kpi_display_label'] = mode_name

    # 1. Precondition: select the standby mode in Settings (once).
    if args.standby_mode_node:
        print(f"\n🛠️  [standby_measurement] Precondition: goto '{args.standby_mode_node}' (select '{mode_name}')")
        pre = _goto(context, device, args.standby_mode_node)
        if not pre.get('success', False):
            context.error_message = (
                f"Precondition failed: could not reach standby-mode node "
                f"'{args.standby_mode_node}' ({mode_name})"
            )
            print(f"❌ [standby_measurement] {context.error_message}")
            return False
        print(f"✅ [standby_measurement] Standby mode selected: {mode_name}")

    # 2. Baseline: ensure we are at live before the first power-down.
    print(f"\n📍 [standby_measurement] Baseline: goto '{live_node}'")
    base = _goto(context, device, live_node)
    if not base.get('success', False):
        context.error_message = f"Could not reach baseline '{live_node}' before cycling"
        print(f"❌ [standby_measurement] {context.error_message}")
        return False

    state['measurement_attempted'] = True

    # 3. Power-cycle loop: live → standby → (wait) → live.
    wake_success_count = 0
    for i in range(args.iterations):
        print(f"\n{'='*60}")
        print(f"🔄 [standby_measurement] Iteration {i+1}/{args.iterations}")
        print(f"{'='*60}")

        # live → standby
        print(f"🌙 [standby_measurement] Enter standby: goto '{standby_node}'")
        down = _goto(context, device, standby_node)
        if not down.get('success', False):
            print(f"❌ [standby_measurement] Iteration {i+1} could not enter standby — skipping wake")
            continue

        # dwell — recorded as an explicit step so the intentional wait between
        # the standby and wake transitions is visible in the step report (a bare
        # time.sleep() would otherwise just be an invisible gap between steps).
        if wait_seconds > 0:
            dwell_start = datetime.now()
            print(f"\n{'─'*60}")
            print(f"⏳ [standby_measurement] DWELL START {dwell_start.strftime('%H:%M:%S')} "
                  f"— sleeping {args.wait}min ({wait_seconds}s) in standby")
            print(f"{'─'*60}")
            time.sleep(wait_seconds)
            dwell_end = datetime.now()
            print(f"{'─'*60}")
            print(f"⏰ [standby_measurement] DWELL END   {dwell_end.strftime('%H:%M:%S')} "
                  f"— dwelled {(dwell_end - dwell_start).total_seconds():.0f}s; waking now")
            print(f"{'─'*60}")
            context.record_step_immediately({
                'success': True,
                'message': f"Wait in standby {args.wait} min",
                'from_node': standby_node,
                'to_node': standby_node,
                'execution_time_ms': int((dwell_end - dwell_start).total_seconds() * 1000),
                'start_time': dwell_start.strftime('%H:%M:%S'),
                'end_time': dwell_end.strftime('%H:%M:%S'),
                'actions': [{'command': f'wait {args.wait} min ({wait_seconds}s)'}],
                'verifications': [],
                'step_category': 'dwell',
            })

        # Deep/eco standby recovery: a long dwell powers the host CPU off and
        # tears down the BLE link, so the wake edge's POWER press can't reach
        # the STB. Emit the WoBLE cold-wake first and wait for reconnect, then
        # the POWER press below lands on a live link. No-op for short dwells
        # (active standby) and for non-BLE remotes.
        if wait_seconds >= COLD_STANDBY_THRESHOLD_S:
            _cold_wake_before_power(context, device, standby_node)

        # standby → live (this is the measured transition)
        print(f"\n{'═'*60}")
        print(f"☀️  [standby_measurement] WAKE {datetime.now().strftime('%H:%M:%S')} "
              f"— goto '{live_node}' (measured standby → live)")
        print(f"{'═'*60}")
        up = _goto(context, device, live_node)
        if up.get('success', False):
            wake_success_count += 1
            print(f"✅ [standby_measurement] Iteration {i+1} wake SUCCESS")
        else:
            print(f"❌ [standby_measurement] Iteration {i+1} wake FAILED")

    print(f"\n{'='*60}")
    print(f"🎉 [standby_measurement] Completed {args.iterations} cycles "
          f"({wake_success_count} wakes succeeded)")
    print(f"{'='*60}")

    # 4. Poll the DB until every wake's KPI is post-processed by vpt-kpi.service.
    print(f"\n⏳ [standby_measurement] Polling DB for {args.iterations} wake KPI measurements...")
    max_wait_seconds = 60
    poll_interval = 3
    elapsed = 0
    kpi_db_results = []
    while elapsed < max_wait_seconds:
        time.sleep(poll_interval)
        elapsed += poll_interval
        script_end_time = datetime.now(timezone.utc)
        kpi_db_results = km._fetch_kpi_results_from_db(
            team_id=context.team_id,
            device_name=device.device_name,
            start_time=script_start_time,
            end_time=script_end_time,
        )
        wake_count = sum(1 for r in kpi_db_results if r.get('action_set_id') == measured_action_set_id)
        print(f"   [{elapsed}s] wake {wake_count}/{args.iterations} (total fetched: {len(kpi_db_results)})")
        if wake_count >= args.iterations:
            print(f"✅ [standby_measurement] All wake measurements present after {elapsed}s")
            break
    else:
        print(f"⚠️  [standby_measurement] Timed out after {max_wait_seconds}s — proceeding with partial results")

    # Filter to the wake direction only (drop the incidental live → standby rows).
    relevant_results = sorted(
        [r for r in kpi_db_results if r.get('action_set_id') == measured_action_set_id],
        key=lambda r: r.get('executed_at') or '',
    )
    state['relevant_results'] = relevant_results

    successful = sum(1 for r in relevant_results if r.get('kpi_measurement_success'))
    skipped = sum(1 for r in relevant_results if km._is_kpi_skip(r))
    hard_failed = len(relevant_results) - successful - skipped
    print(f"📊 [standby_measurement] Wake KPIs: {successful}/{len(relevant_results)} successful "
          f"({skipped} skipped, {hard_failed} failed)")

    context.overall_success = (
        len(relevant_results) >= args.iterations
        and hard_failed == 0
        and successful >= 1
        and successful >= (args.iterations - skipped)
    )

    wake_label = f"{standby_node}{ARROW}{live_node}"
    if not context.overall_success and not context.error_message:
        if not relevant_results:
            context.error_message = (
                f"No KPI measurements recorded for '{wake_label}'. "
                f"The wake edge likely has no KPI reference — add kpi_references to the "
                f"'{wake_label}' action set, or give the "
                f"'{live_node}' node a verification (with use_verifications_for_kpi=true)."
            )
        else:
            context.error_message = (
                f"Only {successful}/{args.iterations} wake KPIs succeeded for "
                f"'{wake_label}' ({hard_failed} failed, {skipped} skipped)."
            )
        print(f"❌ [standby_measurement] {context.error_message}")

    return context.overall_success


@script("standby_measurement", "Measure standby → live wake KPI", default_device="device1")
def main():
    """Run standby wake measurement; always emit an execution summary."""
    args = get_args()
    context = get_context()
    device = get_device()

    # Resolve the active variant (device.navigation_context is canonical).
    variant = None
    if device is not None and getattr(device, 'navigation_context', None):
        variant = device.navigation_context.get('variant')
    if not variant:
        variant = getattr(args, 'variant', None)
    if isinstance(variant, str):
        variant = variant.strip() or None

    state = {
        'standby_node': '',
        'live_node': '',
        'mode_name': args.standby_mode_node or '',
        'measured_action_set_id': '',
        'measurement_attempted': False,
        'relevant_results': [],
    }

    try:
        return _run_standby_measurement(context, args, device, state)
    finally:
        # Don't leak the run-level KPI label onto a later script sharing this
        # device's navigation_context (it persists in-memory on the host).
        if device is not None and getattr(device, 'navigation_context', None):
            device.navigation_context.pop('kpi_display_label', None)
        context.execution_summary = capture_standby_summary(
            context, args, variant,
            state['standby_node'],
            state['live_node'],
            state['mode_name'],
            state['measured_action_set_id'],
            state['measurement_attempted'],
            state['relevant_results'],
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
