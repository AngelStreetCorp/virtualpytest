#!/usr/bin/env python3
"""
Clash of Clans menu-loop farm bot (TASK-81 §81.1).

One script for every platform. The device-specific parts live in the userinterface
tree (`clashofclans-android-mobile` for the S21 FE over HDMI, `clashofclans-web`
stub for future work) and the device is driven only through the navigation
executor. The bot loops collect → train → donate → clan-capital → daily on the
village, reads the account state on settings (for the §R5 guard), and refuses the
Attack button, the shop, and the Builder Base by design (§R1, §R3, §Out-of-scope).

Install path (when CoC is not installed):
    entry → install_game (open_url Play Store) → install (tap Install) → home
    The Play Store flow is `open_url(market://details?id=com.supercell.clashofclans,
    com.android.vending)` + `click_element "Install"` + wait for "Open" + launch.

When CoC is already installed:
    entry → launch (launch_app com.supercell.clashofclans) → home

The runner module lives in `shared/src/lib/game/clashofclans/runner.py` (owned
by a disjoint worker). We try-import it so this file stays importable while the
runner package is being built; once it lands, the real symbols take precedence
and the stubs below are unused.
"""

import os
import sys
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_args, get_context, get_device

try:
    from shared.src.lib.game.clashofclans.runner import (
        GameRunner,
        RunnerConfig,
        kpi_metadata,
        resolve_userinterface,
        summary,
    )
    _HAS_RUNNER = True
    _IMPORT_ERROR = ""
except ImportError as _exc:
    # Local stubs: the disjoint worker who owns shared/src/lib/game/clashofclans/
    # will land the real implementations. Until then, the file still imports
    # cleanly so the script decorator and CLI can be exercised in isolation.
    GameRunner = None
    RunnerConfig = None
    kpi_metadata = None
    resolve_userinterface = None
    summary = None
    _HAS_RUNNER = False
    _IMPORT_ERROR = str(_exc)

try:
    from shared.src.lib.game.clashofclans import report as coc_report
    _HAS_REPORT = True
except ImportError:
    coc_report = None  # type: ignore
    _HAS_REPORT = False


# Map the script-level policy enums (user-facing, TASK-81 §81.1) to the
# runner's RunnerConfig enum. The runner accepts "auto" | "manual"; we keep
# the script's finer-grained enum and collapse "never" / "on_requested" /
# "always" into the runner's "auto" or "manual" knob.
def _donate_policy(arg: str) -> str:
    return "manual" if arg == "never" else "auto"


def _collect_policy(arg: str) -> str:
    return "manual" if arg == "never" else "auto"


_script_args = [
    "--userinterface:str:auto",
    "--max_runtime:int:1800",
    "--max_cycles:int:0",
    "--idle_minutes:int:5",
    "--donate_policy:str:always:always|on_requested|never",
    "--collect_policy:str:ready:ready|aggressive|never",
    "--attack_opt_in:bool:false",
    "--dry_run:bool:false",
    "--install_only:bool:false",
]
_script_description = (
    "Clash of Clans menu-loop farm bot: collect / train / donate / "
    "clan-capital / dailies on the S21 FE over HDMI. Attack and real-money surfaces "
    "are locked off; --attack_opt_in exists only for ad-hoc non-farming testing."
)
_arg_descriptions = {
    "userinterface": ("auto picks the clashofclans-* userinterface matching the device "
                      "model (clashofclans-android-mobile, clashofclans-web)"),
    "max_runtime": "Hard stop in seconds; reaching it fails the run with stop_reason=time_cap",
    "max_cycles": "Max number of full home cycles; 0 means unlimited (until max_runtime)",
    "idle_minutes": "Minutes to idle between cycles when nothing is ready (collectors, training, donations)",
    "donate_policy": "always: donate on every cycle; on_requested: only when the clan has open requests; never: skip",
    "collect_policy": "ready: collect only ready collectors; aggressive: also start upgrades; never: skip",
    "attack_opt_in": ("FALSE in v1 — unlocks the Attack button in the tree (the edge is "
                      "disabled_by: attack_opt_in). The runner never picks it unless this "
                      "flag is True. Per §R1 and §Out-of-scope."),
    "dry_run": "Walk the tree without invoking real actions (smoke test for the UI bundle)",
    "install_only": "Run the install sub-tree only (entry → install_game → install → home) and exit",
}


@script("game_clashofclans", _script_description, default_device="device1")
def main():
    args = get_args()
    context = get_context()
    device = get_device()

    if not _HAS_RUNNER:
        # Stubs land when the disjoint worker merges their package.
        # The error is reported but the script still completes cleanly.
        context.error_message = (
            "shared.src.lib.game.clashofclans.runner is not yet available "
            "(other worker owns that package): " + _IMPORT_ERROR
        )
        context.overall_success = False
        context.execution_summary = (
            "GAME_CLASHOFCLANS SUMMARY\n"
            "Runner module missing — the disjoint worker has not yet landed "
            "shared/src/lib/game/clashofclans/runner.py."
        )
        return False

    userinterface = resolve_userinterface(args.userinterface, device.device_model, context.team_id)
    if not userinterface:
        context.error_message = (
            f"No clashofclans-* userinterface matches device model '{device.device_model}'"
        )
        context.overall_success = False
        context.execution_summary = summary({"device_model": device.device_model}, False, context.error_message)
        return False
    context.userinterface = userinterface
    context.userinterface_name = userinterface

    tree = device.navigation_executor.load_navigation_tree(userinterface, context.team_id)
    if not tree.get("success"):
        context.error_message = f"Navigation tree loading failed: {tree.get('error', 'unknown error')}"
        context.overall_success = False
        context.execution_summary = summary({"userinterface": userinterface}, False, context.error_message)
        return False
    context.tree_id = tree["tree_id"]

    data = GameRunner(
        device, context, userinterface, context.tree_id,
        config=RunnerConfig(
            max_runtime_s=int(args.max_runtime),
            max_cycles=int(args.max_cycles),
            donate_policy=_donate_policy(args.donate_policy),
            collect_policy=_collect_policy(args.collect_policy),
            attack_opt_in=bool(args.attack_opt_in),
            dry_run=bool(args.dry_run),
            install_only=bool(args.install_only),
        ),
    ).run()

    context.metadata = kpi_metadata(data)
    # §81.1.9: ship the host-screen recording (when present) to R2 before
    # the report builder runs, so the report can reference the URL.
    if data.get("run_video_path"):
        video_url = _upload_run_video(data["run_video_path"], context)
        data["run_video_r2_url"] = video_url
        context.metadata["run_video_r2_url"] = video_url
    # §81.1.8 report: a self-contained HTML + event-JSON, uploaded to R2 so
    # the user has a single verifiable artifact for the run (Pokémon
    # pattern, GAME_BOTS §3 "Reporting" column).
    report_meta = _build_and_ship_coc_report(data, context, device)
    context.metadata.update(report_meta)
    context.overall_success = bool(data.get("success"))
    if not context.overall_success:
        context.error_message = data.get("error") or "Clash of Clans run failed"
    context.execution_summary = summary(data, context.overall_success, context.error_message or "")
    return context.overall_success


def _upload_run_video(local_path: str, context) -> str:
    """Upload the §81.1.9 run video to R2 (next to the report HTML/JSON).

    Returns the signed URL or ``""`` on failure. Never raises -- the
    runner stays usable when R2 is down. ``context`` is used only for
    logging; the R2 URL is returned directly because the report JSON is
    rendered on the host before context.metadata gets the field."""
    from shared.src.lib.utils.cloudflare_utils import upload_game_run_video
    run_id = getattr(context, "script_result_id", None) or "coc-run"
    res = upload_game_run_video(local_path, f"script-reports/game/clashofclans/{run_id}/run.mp4")
    if not res["success"]:
        try:
            with open(os.path.join("/tmp", "coc_video_upload.log"), "a") as f:
                f.write(f"{datetime.now().isoformat()} upload failed: {res['error']}\n")
        except Exception:
            pass
    return res["url"]


main._script_args = _script_args
main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "all",
}


def _build_and_ship_coc_report(data, context, device):
    """Build the run's HTML + JSON report, upload to R2, stash URL in metadata.

    Mirrors game_pokémon's ``upload_game_report``: a single HTML file with
    the run's KPIs + the event timeline + per-cycle screenshots embedded
    as ``data:`` URIs. Pokemon saves alongside the script reports under
    ``script-reports/game/pokemon/<run_id>/``; CoC uses the same prefix.

    Returns the dict to merge into ``context.metadata``. Always returns
    something so the metadata write never blows up when the report/upload
    fails -- on failure the ``game_report_url`` key is empty and the local
    paths are recorded so the user can find the file on the host.
    """
    import json
    import os
    import tempfile
    from datetime import datetime

    if not _HAS_REPORT or coc_report is None:
        return {"game_report_url": "", "report_unavailable_reason": "report module missing"}
    if coc_report is None:
        return {"game_report_url": "", "report_unavailable_reason": "report module missing"}

    events = data.get("event_log") or []
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    ui_name = data.get("userinterface", "clashofclans")
    run_id = getattr(context, "script_result_id", None) or f"coc-run-{stamp}"
    title = f"CoC \u2014 {ui_name} on {data.get('device_model', '?')} ({stamp})"

    # Local staging dir on the host. The COLD screenshot paths live under
    # this same tree when running on the Pi, so the report opens cleanly
    # on the host. We don't write new files here -- we only persist the
    # event JSON and the HTML for R2 upload.
    staging_dir = "/var/lib/vpt/coc_frames"
    os.makedirs(staging_dir, exist_ok=True)
    html_local = os.path.join(staging_dir, f"{run_id}_report.html")
    json_local = os.path.join(staging_dir, f"{run_id}_events.json")

    try:
        html_text = coc_report.build_html(data, events, title=title)
    except Exception as e:
        return {"game_report_url": "", "report_html_path": html_local,
                "report_unavailable_reason": f"build_html failed: {e}"}

    try:
        json_text = coc_report.build_event_json(data, events)
    except Exception as e:
        json_text = json.dumps({"error": str(e)}, ensure_ascii=False)

    # Write the local copies so the host has the file even when R2 is down.
    try:
        with open(html_local, "w", encoding="utf-8") as f:
            f.write(html_text)
        with open(json_local, "w", encoding="utf-8") as f:
            f.write(json_text)
    except Exception as e:
        return {"game_report_url": "", "report_html_path": "",
                "report_unavailable_reason": f"local write failed: {e}"}

    # Upload to R2 next to the script reports so the URL is reachable from
    # chat / dashboard. Pokemon uses ``script-reports/game/pokemon/<run_id>/``
    # -- we mirror the prefix.
    report_url = ""
    upload_err = ""
    try:
        from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
        uploader = get_cloudflare_utils()
        res = uploader.upload_files([
            {"local_path": html_local,
             "remote_path": f"script-reports/game/clashofclans/{run_id}/game_report.html"},
            {"local_path": json_local,
             "remote_path": f"script-reports/game/clashofclans/{run_id}/events.json"},
        ], for_report_assets=True)
        uploaded = res.get("uploaded_files") or []
        for entry in uploaded:
            if entry.get("remote_path", "").endswith("game_report.html"):
                report_url = entry.get("url", "")
                break
    except Exception as e:
        upload_err = f"upload failed: {e}"

    return {
        "game_report_url": report_url,
        "report_html_path": html_local,
        "report_json_path": json_local,
        "event_log_count": len(events),
        "cycles_observed": data.get("cycles_observed", 0),
        "report_unavailable_reason": upload_err,
    }

if __name__ == "__main__":
    main()