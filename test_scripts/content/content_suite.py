#!/usr/bin/env python3
"""
Content-surface test suite: radio / replay / video on demand / recording.

One reusable harness, one case per feature, runnable per device and per
platform (STB remote, STB web UI, mobile UI). Every case prints one
machine-readable result line:

    VPT_CASE_RESULT {"case":"radio","platform":"web","status":"PASS",...}

The harness and the platform adapters live in `test_scripts/content/`. The
platform mechanics are in `test_scripts/content/_<platform>_adapter.py`.

The recording case is deliberately three steps in one case: record, then check
the recording is listed, then play it back. A recording that is listed but does
not play back is a FAIL, and a recording that never appears is a FAIL too.
"""

import os
import sys

# Add project root to path so the helper imports work from anywhere.
# The virtual-script converter rewrites this block (it only ever reads
# `project_root`, never `current_dir`), so keep the canonical shape.
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import (  # noqa: E402
    script,
    get_args,
    get_context,
    get_device,
)

import test_scripts.content._harness as harness  # noqa: E402

_SCRIPT_DESCRIPTION = (
    "Tests the whole content surface of the TV apps: radio, replay, video on "
    "demand and recording (record, then verify it is listed and plays back). "
    "Prints one VPT_CASE_RESULT line per case."
)


def _parse_cases(raw):
    wanted = []
    for part in str(raw or '').split(','):
        name = part.strip().lower()
        if not name:
            continue
        if name not in harness.CASES:
            raise ValueError(
                f"unknown case '{name}'; known cases: {', '.join(harness.CASES)}")
        if name not in wanted:
            wanted.append(name)
    return wanted


def _run(context, device, args):
    """Run the requested cases and return True when nothing failed."""
    try:
        cases = _parse_cases(getattr(args, 'cases', ''))
    except ValueError as exc:
        context.overall_success = False
        context.error_message = str(exc)
        # One row, built by the harness so the shape is the agreed one (the
        # same 8 fields as a case row), not a hand-rolled line.
        outcome = harness.CaseOutcome.failed(str(exc), cause=harness.CAUSE_INFRA)
        row = outcome.to_dict("suite", "unknown",
                              getattr(getattr(context, "host", None), "host_name", ""),
                              getattr(device, "device_name", ""), 0.0)
        harness.emit_result(row)
        harness.emit_summary([row])
        return False

    try:
        adapter = harness.build_adapter(getattr(args, 'platform', 'auto'), device, context, args)
    except Exception as exc:                                   # noqa: BLE001
        context.overall_success = False
        context.error_message = f"no adapter for this device: {exc}"
        print(f"[content_suite] no adapter for this device: {exc}", flush=True)
        # The report must show WHY there are no rows, not an empty run.
        outcome = harness.CaseOutcome.failed(f"no adapter for this device: {exc}",
                                             cause=harness.CAUSE_INFRA)
        row = outcome.to_dict("suite", str(getattr(args, 'platform', 'auto')),
                              getattr(getattr(context, "host", None), "host_name", ""),
                              getattr(device, "device_name", ""), 0.0)
        harness.emit_result(row)
        harness.emit_summary([row])
        return False

    print(f"[content_suite] platform={adapter.platform} "
          f"device={getattr(device, 'device_name', '')} "
          f"cases={','.join(cases)}", flush=True)

    rows = harness.run_suite(device, context, args, adapter, cases)

    failed = [r for r in rows if r.get('status') == harness.STATUS_FAIL]
    skipped = [r for r in rows if r.get('status') == harness.STATUS_SKIP]
    product = [r for r in rows if r.get('cause') == harness.CAUSE_PRODUCT]

    context.overall_success = harness.suite_passed(rows)
    if failed:
        context.error_message = "; ".join(
            f"{r.get('case')}: {r.get('reason')}" for r in failed)
    if skipped or product:
        context.execution_summary = (
            f"{len(rows)} cases: {len(rows) - len(failed) - len(skipped)} passed, "
            f"{len(failed)} failed, {len(skipped)} skipped "
            f"({len(product)} attributed to the product)")

    return harness.suite_passed(rows)


@script('content_suite', _SCRIPT_DESCRIPTION)
def main():
    return _run(get_context(), get_device(), get_args())


# Script arguments (framework params have defaults, script params are specific).
# The names must match what the adapters read with ctx.arg(...).
main._script_args = [
    '--userinterface:str:',                 # Framework param: the UI to test
    '--cases:str:radio,replay,vod,recording',
    '--platform:str:auto',
    '--max_items:int:3',
    '--play_seconds:int:12',
    '--settle_ms:int:800',
    '--motion_threshold:float:1.0',
    '--motion_window_s:float:2.0',
    '--record_wait_s:int:45',
    '--record_poll_s:int:5',
    '--record_enabled:bool:true',
    # --- STB adapter -------------------------------------------------------
    '--stb_radio_nodes:str:apps_radio,radio_home',
    '--stb_replay_nodes:str:replay',
    '--stb_replay_asset_nodes:str:replay_asset_stream,replay_asset',
    '--stb_vod_nodes:str:movies,home_movies',
    '--stb_recordings_nodes:str:recordings,home_recodings',
    '--stb_live_nodes:str:live',
    '--stb_select_key:str:OK',
    '--stb_back_key:str:BACK',
    '--stb_next_key:str:DOWN',
    '--stb_record_key:str:RECORD',
    '--stb_key_settle_s:float:0.8',
    '--stb_item_settle_s:float:3.0',
    '--stb_list_settle_s:float:2.0',
    '--stb_live_settle_s:float:8.0',
    '--stb_record_settle_s:float:4.0',
    '--stb_record_poll_s:float:10.0',
    '--stb_probe_retries:int:2',
    '--stb_probe_gap_s:float:1.5',
    '--stb_record_diff_pct:float:2.0',
    '--stb_record_list_top_pct:float:0.25',
    # --- web adapter -------------------------------------------------------
    '--probe_interval_s:float:2.0',
    '--nav_timeout_s:int:30',
    '--player_refusal_cause:str:infra',
    # --- mobile adapter ----------------------------------------------------
    '--app_package:str:',
    '--app_name_hint:str:',
    '--radio_keywords:str:radio',
    '--radio_probe_nodes:str:',
    '--record_nodes:str:',
    '--record_keywords:str:record,aufnahme,aufnahme,recording,recorder',
]
main._script_description = _SCRIPT_DESCRIPTION
main._arg_descriptions = {
    'userinterface': 'UI interface name (the TV, browser or phone UI)',
    'cases': 'Comma-separated cases: radio,replay,vod,recording',
    'platform': 'Platform adapter: auto, stb, web, mobile',
    'max_items': 'How many catalogue items to try per case',
    'play_seconds': 'How long an item may play before it counts as not started',
    'settle_ms': 'Pause after a navigation or a key press',
    'motion_threshold': 'Frame-change percent that counts as playback on screen',
    'motion_window_s': 'Seconds between the two frames compared by the motion probe',
    'record_wait_s': 'Seconds to wait for a recording to appear in the list',
    'record_poll_s': 'Seconds between two checks of the recordings list',
    'record_enabled': 'Run the recording case at all (false skips it)',
    'probe_interval_s': 'Seconds between two playback samples on the web',
    'nav_timeout_s': 'Seconds a web navigation may take before it is a failure',
    'player_refusal_cause': 'Cause to report when the web player refuses (infra or product)',
    'app_package': 'Android package name of the TV app (empty: discover it)',
    'app_name_hint': 'Keyword used to find the TV app on the phone',
    'radio_keywords': 'Comma-separated keywords that identify a radio entry',
    'radio_probe_nodes': 'Nodes to search for a radio entry point (empty: the adapter default)',
    'record_nodes': 'Nodes that can start a recording (empty: the adapter default)',
    'record_keywords': 'Comma-separated keywords that identify the record control',
}
for _arg in ('stb_radio_nodes', 'stb_replay_nodes', 'stb_replay_asset_nodes', 'stb_vod_nodes',
             'stb_recordings_nodes', 'stb_live_nodes', 'stb_select_key', 'stb_back_key',
             'stb_next_key', 'stb_record_key', 'stb_key_settle_s', 'stb_item_settle_s',
             'stb_list_settle_s', 'stb_live_settle_s', 'stb_record_settle_s',
             'stb_record_poll_s', 'stb_probe_retries', 'stb_probe_gap_s',
             'stb_record_diff_pct', 'stb_record_list_top_pct'):
    main._arg_descriptions[_arg] = f"STB adapter: {_arg.replace('stb_', '').replace('_', ' ')}."
main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "all",
}

if __name__ == "__main__":
    main()
