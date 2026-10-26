"""
The Clash of Clans run report (TASK-81 §81.1.8).

Mirrors `game_pokemon.report` but adapted to what the CoC bot actually
captures: an event log + per-cycle COLD-storage screenshots + KPIs.
There is no run-level video at the moment -- the script uploads the
HTML itself; the per-cycle screenshots are then uploaded by the host
batch upload (``context.upload_screenshots_to_r2``) so the
``game_report_url`` the script returns can be re-rendered against R2
URLs by replacing ``file://...`` placeholders with the matching R2 URLs.

The page is a self-contained HTML file -- no external assets, no
scripting dependencies. It is meant to be opened from disk and later
uploaded to R2. The viewer sees:

* the KPI badge bar (the eight run-level counters),
* the cycle timeline (one row per event, with the cold screenshot inline
  when one was captured),
* the screenshot gallery (one column per COLD path; unique entries only).
"""

from __future__ import annotations

import base64
import html
import json
import os
from typing import Any, Dict, List, Optional


from ...utils.report_theme import report_theme_head


# Event kinds and their labels + colours. ``cycle_start`` and ``idle`` are
# the steady state; everything else is something the runner decided.
KIND_LABEL: Dict[str, str] = {
    "run_start": "Run start",
    "run_stop": "Run stop",
    "cycle_start": "Cycle",
    "screen": "Screen",
    "decision": "Decision",
    "cross_to": "Cross",
    "action_fired": "Action",
    "disconnect_cleared": "Disconnect cleared",
    "idle": "Idle",
    "transition": "Transition",
    "guard": "R5 guard",
    "device_offline": "Device offline",
    "noop": "No-op",
    "video_start": "Video start",
    "video_disabled": "Video disabled",
}

COLOUR_FOR_KIND: Dict[str, str] = {
    "action_fired": "--vpt-accent",
    "decision": "--vpt-steel",
    "screen": "--vpt-text-2",
    "idle": "--vpt-text-2",
    "transition": "--vpt-warning",
    "guard": "--vpt-error",
    "device_offline": "--vpt-error",
    "disconnect_cleared": "--vpt-success",
    "noop": "--vpt-text-2",
    "cross_to": "--vpt-purple",
    "run_start": "--vpt-accent",
    "run_stop": "--vpt-accent",
    "video_start": "--vpt-success",
    "video_disabled": "--vpt-text-2",
}


def _video_data_uri(local_path: Optional[str]) -> Optional[str]:
    """Embed the host-screen MP4 as a data: URI for the local report.

    Sized for one recording (10-200 MB compressed). The video is what
    proves the run actually played -- the per-cycle screenshots are the
    thumbnails, this is the timeline. Returns None when the file is
    missing or oversized (>50 MB to keep the page light for chat / mail).
    """
    if not local_path or not os.path.exists(local_path):
        return None
    try:
        size = os.path.getsize(local_path)
        if size > 50 * 1024 * 1024:
            return None
        with open(local_path, "rb") as f:
            blob = f.read()
    except Exception:
        return None
    return "data:video/mp4;base64," + base64.b64encode(blob).decode()


def _build_video_section(data: Dict[str, Any]) -> str:
    """§81.1.9 run-video embed. Renders nothing when no video was recorded."""
    local_path = data.get("run_video_path", "")
    chunks = data.get("run_video_chunk_count", 0)
    reason = data.get("run_video_disabled_reason", "")
    if not local_path:
        msg = reason or "no run video was recorded"
        return ('<section class="card video-card no-video">'
                '<h2>Run video (not recorded)</h2>'
                '<p class="muted">' + html.escape(msg) + '</p>'
                '</section>')
    src = _video_data_uri(local_path)
    if src is None:
        # video too large to inline -- link to the local file
        return ('<section class="card video-card">'
                '<h2>Run video (too large to inline)</h2>'
                '<p class="muted">' + html.escape(f"local file: {local_path} "
                                                   f"({chunks} chunks)") + '</p>'
                '</section>')
    return ('<section class="card video-card">'
            '<h2>Run video <span class="muted">(' + str(chunks) + ' chunks, '
            + html.escape(os.path.basename(local_path)) + ')</span></h2>'
            '<video controls muted playsinline preload="metadata">'
            '<source src="' + html.escape(src) + '" type="video/mp4" />'
            'Your browser does not support video playback.'
            '</video></section>')


def _short(v: Any, n: int = 60) -> str:
    if v is None:
        return ""
    s = str(v)
    if len(s) > n:
        s = s[: n - 1] + "\u2026"
    return s


def _summary_kpis(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """The eight KPIs the report shows, exactly like the script_results column."""
    pairs = [
        ("Cycles completed", data.get("cycles_completed", 0),
         "of " + str(data.get("cycles_observed", 0)) + " observed"),
        ("Gold gained", data.get("gold_gained", 0), "across run"),
        ("Elixir gained", data.get("elixir_gained", 0), "across run"),
        ("Dark elixir", data.get("dark_elixir_gained", 0), "across run"),
        ("Troops trained", data.get("troops_trained", 0), ""),
        ("Troops donated", data.get("troops_donated", 0), ""),
        ("Capital chests", data.get("capital_chests_collected", 0), ""),
        ("Dailies", data.get("dailies_collected", 0), ""),
        ("Actions fired", data.get("actions_fired", 0), "tree actions"),
        ("Guard scans", data.get("guard_scan_count", 0),
         "warning seen: " + str(bool(data.get("account_warning_seen")))),
        ("No observation", data.get("no_observation_cycles", 0),
         "frames not classified"),
        ("Idle seconds", data.get("idle_seconds", 0), "passive wait"),
        ("Buy-surface refused", data.get("buy_surface_refused", 0),
         "real-money tap blocks"),
        ("Attack attempted", data.get("attack_attempted", False),
         "R1 lock — must stay False"),
    ]
    return [{"name": n, "value": str(v), "note": note} for n, v, note in pairs]


def _event_line(e: Dict[str, Any]) -> str:
    """A one-line summary of the event's interesting fields."""
    kind = e.get("kind", "")
    if kind == "run_start":
        return (f"start userinterface={e.get('userinterface','')} "
                f"device={e.get('device_model','')} "
                f"max_runtime={e.get('max_runtime_s', 0)}s "
                f"max_cycles={e.get('max_cycles', 0)}")
    if kind == "run_stop":
        kpis = e.get("kpis") or {}
        keys = ("gold_gained", "elixir_gained", "troops_trained", "troops_donated",
                "capital_chests_collected", "dailies_collected",
                "guard_scan_count", "buy_surface_refused")
        return (f"stop reason={e.get('stop_reason','')} duration={e.get('play_duration_s', 0)}s "
                f"observed={e.get('cycles_observed', 0)} cycles "
                f"completed={e.get('cycles_completed', 0)} "
                + " ".join(f"{k}={kpis.get(k)}" for k in keys if kpis.get(k)))
    if kind == "cycle_start":
        return "cycle " + str(e.get("cycle_index", "?"))
    if kind == "screen":
        bits = [f"screen={e.get('screen','?')}"]
        if e.get("collector_ready"):
            bits.append("collectors=" + ",".join(e["collector_ready"]))
        for k in ("donation_dot_present", "clan_capital_ready", "daily_present",
                  "account_warning_present"):
            if e.get(k) is not None:
                bits.append(f"{k}={e[k]}")
        for k in ("gold", "elixir", "dark_elixir"):
            if e.get(k) is not None:
                bits.append(f"{k}={e[k]}")
        return " ".join(bits)
    if kind == "decision":
        return f"action={e.get('action_name','')} target={e.get('target','')} reason={e.get('reason','')}"
    if kind == "cross_to":
        return f"cross_to {e.get('target','')} planned={e.get('planned', 0)} success={e.get('success')}"
    if kind == "action_fired":
        return (f"fired {e.get('action_name','')} -> {e.get('tree_node','?')} "
                f"ok={e.get('success')} cycles_completed={e.get('cycles_completed', 0)} "
                f"kpi_count={e.get('kpi_count', 0)}")
    if kind == "idle":
        return f"idle {e.get('reason','')} (+{e.get('idle_seconds', 0)}s)"
    if kind == "transition":
        return (f"transition no_obs={e.get('no_observation_count', 0)} "
                f"transition_count={e.get('transition_count', 0)}")
    if kind == "guard":
        return "R5 guard tripped scan_count=" + str(e.get("guard_scan_count", 0))
    if kind == "device_offline":
        return "frame() returned None reason=" + str(e.get("reason", ""))
    if kind == "noop":
        return f"noop action={e.get('action_name','')}"
    if kind == "disconnect_cleared":
        return "disconnect modal crossed back to home"
    return _short(e)


def _screenshot_data_uri(path: Optional[str]) -> Optional[str]:
    """Inline the screenshot as a data URI for the local report.

    Sized for 1-3 screenshots per cycle; a 30-min run with 200 cycles is
    ~5-10 MB of HTML which the user should open locally, not in chat.
    Returns ``None`` when the file does not exist (COLD path stale).
    """
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            blob = f.read()
    except Exception:
        return None
    # Detect kind from extension; the COLD paths always live in
    # /var/lib/vpt/... with .jpg or .png.
    if path.lower().endswith(".png"):
        mime = "image/png"
    else:
        mime = "image/jpeg"
    return "data:" + mime + ";base64," + base64.b64encode(blob).decode()


def build_html(data: Dict[str, Any], events: List[Dict[str, Any]],
               title: str = "CoC \u2014 run report") -> str:
    """Build a self-contained HTML for the CoC run.

    ``data`` is the ``GameRunner.run()`` result; ``events`` is the same as
    ``data["event_log"]`` (kept as a separate arg for tests).
    """
    kpis = _summary_kpis(data)
    stop_reason = data.get("stop_reason", "")
    userinterface = data.get("userinterface", "")
    device_model = data.get("device_model", "")
    play_duration_s = data.get("play_duration_s", 0)
    cycles_observed = data.get("cycles_observed", len([e for e in events if e.get("kind") == "cycle_start"]))

    rows: List[str] = []
    unique_paths: List[str] = []
    seen_paths = set()
    for e in events:
        kind = e.get("kind", "")
        label = KIND_LABEL.get(kind, kind)
        colour = "var(" + COLOUR_FOR_KIND.get(kind, "--vpt-text-2") + ")"
        t = e.get("t", 0)
        cycle_index = e.get("cycle_index", "")
        cold_path = e.get("cold_path") or ""
        img_html = ""
        if cold_path and cold_path not in seen_paths:
            uri = _screenshot_data_uri(cold_path)
            if uri:
                unique_paths.append(cold_path)
                seen_paths.add(cold_path)
        if cold_path:
            uri = _screenshot_data_uri(cold_path)
            if uri:
                img_html = ('<div class="img-wrap"><img alt="cycle ' + html.escape(str(cycle_index)) +
                            '" src="' + html.escape(uri) + '"/></div>')
        rows.append(
            '<tr>'
            + f'<td class="t">{t:.1f}s</td>'
            + f'<td class="c">c{cycle_index}</td>'
            + f'<td class="k"><span class="badge" style="background:{colour}">{html.escape(label)}</span></td>'
            + f'<td class="d">{html.escape(_event_line(e))}</td>'
            + f'<td class="s">{img_html}</td>'
            + '</tr>'
        )

    gallery = ""
    if unique_paths:
        thumbs = []
        for p in unique_paths[:200]:   # cap at 200 to keep the page light
            uri = _screenshot_data_uri(p)
            if uri:
                thumbs.append('<div class="thumb"><img alt="' +
                              html.escape(os.path.basename(p)) +
                              '" src="' + html.escape(uri) +
                              '"/><span class="cap">' +
                              html.escape(os.path.basename(p)) +
                              '</span></div>')
        gallery = ('<h2>Screenshot gallery (' + str(len(thumbs)) +
                   ' unique)</h2><div class="gallery">' + "".join(thumbs) + '</div>')

    kpi_html = "".join(
        '<div class="kpi"><b>' + html.escape(k["name"]) + '</b>' +
        '<span>' + html.escape(k["value"]) + (k["note"] and
                                                ' <em>' + html.escape(k["note"]) + '</em>' or '') +
        '</span></div>'
        for k in kpis
    )

    body = (
        '<header><h1>' + html.escape(title) + '</h1>'
        '<div class="meta">UI <code>' + html.escape(userinterface) +
        '</code> &middot; device <code>' + html.escape(device_model) +
        '</code> &middot; <span class="stop">stop=' +
        html.escape(stop_reason or "running") + '</span>'
        ' &middot; duration <b>' + f'{play_duration_s:.1f}s' + '</b>'
        ' &middot; cycles observed <b>' + str(cycles_observed) + '</b></div>'
        '<div class="kpis">' + kpi_html + '</div></header>'
        + _build_video_section(data)
        + '<main>'
        '<section class="card">'
        '<h2>Event timeline (' + str(len(events)) + ' events)</h2>'
        '<table>'
        '<thead><tr><th>t</th><th>cycle</th><th>kind</th><th>detail</th><th>screenshot</th></tr></thead>'
        '<tbody>' + "".join(rows) + '</tbody></table></section>'
        '<section class="card">' + gallery + '</section>'
        '</main>'
    )

    css = (
        ":root{--bg:var(--vpt-page);--card:var(--vpt-surface);--fg:var(--vpt-text);"
        "--muted:var(--vpt-text-2);--line:var(--vpt-border);--accent:var(--vpt-accent);}"
        "*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);"
        "font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}"
        "header{padding:16px}h1{margin:0 0 6px;font-size:20px}"
        ".meta{color:var(--muted);font-size:12px;margin-bottom:10px}"
        ".meta .stop{padding:1px 6px;border-radius:8px;background:var(--vpt-text-2);color:#fff;font-weight:600;font-size:11px}"
        ".kpis{display:flex;flex-wrap:wrap;gap:8px}"
        ".kpi{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 10px;min-width:120px}"
        ".kpi b{display:block;font-size:15px}.kpi span{color:var(--muted);font-size:12px}"
        ".kpi em{font-style:normal;color:var(--accent);margin-left:6px}"
        "main{display:grid;grid-template-columns:1fr;gap:16px;padding:0 16px 16px}"
        ".card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;min-width:0}"
        "h2{font-size:15px;margin:0 0 8px}table{width:100%;border-collapse:collapse;font-size:13px}"
        "td{padding:4px 6px;border-top:1px solid var(--line);vertical-align:top}"
        "td.t{width:60px;color:var(--muted)}td.c{width:50px;color:var(--muted);font-variant-numeric:tabular-nums}"
        "td.k{width:130px}.badge{display:inline-block;padding:1px 8px;border-radius:10px;color:#fff;font-size:11px;font-weight:600}"
        "td.d{word-break:break-word;max-width:0}td.s{width:200px}"
        ".img-wrap img{display:block;max-width:200px;max-height:120px;border-radius:4px;border:1px solid var(--line)}"
        ".gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px}"
        ".thumb{background:var(--vpt-subtle);border:1px solid var(--line);border-radius:6px;padding:4px}"
        ".thumb img{display:block;width:100%;height:auto;border-radius:4px}"
        ".thumb .cap{display:block;color:var(--muted);font-size:11px;margin-top:4px;word-break:break-all}"
    )

    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        + report_theme_head()
        + '<title>' + html.escape(title) + '</title>'
        '<style>' + css + '</style></head><body>' + body + '</body></html>'
    )


def build_event_json(data: Dict[str, Any], events: List[Dict[str, Any]]) -> str:
    """A JSON dump of the run -- the data + the event log.

    This is what ``scripts/coc_score.py`` parses for the ``metric=`` line,
    and what the report-page viewer can download for offline analysis.

    Includes ``run_video`` (the §81.1.9 host-screen recording) when
    ``data`` has a non-empty ``run_video_path``. When the script shipped
    the video to R2 the runner's caller fills ``data['run_video_r2_url']``
    in after ``runner.run()`` returns, so the JSON here will be missing
    that field -- ``scripts/coc_score.py`` is robust to either shape.
    """
    payload = {
        "userinterface": data.get("userinterface", ""),
        "device_model": data.get("device_model", ""),
        "play_duration_s": data.get("play_duration_s", 0),
        "cycles_observed": data.get("cycles_observed", 0),
        "kpis": {k: data.get(k) for k in (
            "gold_gained", "elixir_gained", "dark_elixir_gained",
            "troops_trained", "troops_donated",
            "capital_chests_collected", "dailies_collected",
            "cycles_completed", "attack_attempted", "account_warning_seen",
            "stop_reason", "actions_fired", "guard_scan_count",
            "no_observation_cycles", "transition_cycles",
            "buy_surface_refused", "idle_seconds")},
        "event_log": events,
    }
    if data.get("run_video_path"):
        payload["run_video"] = {
            "local_path": data.get("run_video_path", ""),
            "r2_url": data.get("run_video_r2_url", ""),
            "chunks": data.get("run_video_chunk_count", 0),
            "disabled_reason": data.get("run_video_disabled_reason", ""),
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)
