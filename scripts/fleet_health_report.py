#!/usr/bin/env python3
"""
fleet_health_report.py — daily per-device fleet health report (GOAL-04).

Usage:
    AUTO_SIGN_TOKEN=... python3 scripts/fleet_health_report.py \\
        [--servers https://virtualpytest.angelstreet.io,https://rpitest.angelstreet.io] \\
        [--team 7fdeb4bb-3639-4ec3-959f-b54769a219ce] \\
        [--ai]                      # add per-device AI diagnosis (needs AI provider keys in env) \\
        [--output fleet_health_YYYY-MM-DD.md]

Passive signals only — NO probe takes control of any device (GOAL-04 guardrail):
  - host registry + heartbeat:  GET  /server/system/getAllHosts
  - capture freshness + flags:  POST /server/monitoring/latest-json  (server proxies to host)
  - incidents (open + 24h):     GET  /server/alerts/getAllAlerts
  - last script execution:      GET  /server/script-results/getAllScriptResults

Verdict semantics (layer-aware, reconciled against the CURRENT frame so the report
matches what the GUI shows):
  OK       — capture fresh, no open incident
  IDLE     — static screen (freeze) but no recent activity: device likely healthy,
             nothing is playing. This is NOT a fault. Desktop/VNC hosts (host_vnc)
             go further: static screen and missing audio are never faults, even
             during activity.
  DEGRADED — issue confirmed by current frame or during activity, with SINCE timestamp
  DOWN     — host offline or capture stalled
  UNKNOWN  — cannot assess (reason given; never silently skipped)
"""
from __future__ import annotations
import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

UA = {"User-Agent": "fleet-health-report/1.0", "Content-Type": "application/json"}

DEFAULT_SERVERS = os.environ.get(
    "FLEET_HEALTH_SERVERS",
    "https://virtualpytest.angelstreet.io,https://rpitest.angelstreet.io",
)
DEFAULT_TEAM = os.environ.get("FLEET_HEALTH_TEAM", "7fdeb4bb-3639-4ec3-959f-b54769a219ce")
DEFAULT_TOKEN = os.environ.get("AUTO_SIGN_TOKEN", "")

# Capture freshness thresholds (seconds). At 5fps a healthy device is <1s behind;
# generous margins absorb clock skew between host and wherever this script runs.
FRESH_WARN_S = 30
FRESH_DOWN_S = 120

# A device counts as "active" (someone/something is using it) if a script ran on it
# within this window or the registry reports a running deployment. Freeze during
# activity is a fault; freeze while idle is just a static screen.
ACTIVITY_WINDOW_H = 2

# Desktop/PC captures (VNC): a static screen is normal even during activity (scripts
# don't animate the desktop) and there is no audio path — freeze/audio_loss incidents
# are noise on these models, never faults.
DESKTOP_MODELS = {"host_vnc"}


def _url(server: str, path: str, token: str, **params) -> str:
    q = dict(params)
    if token:
        q["auto_signed"] = token
    qs = urllib.parse.urlencode(q)
    return f"{server}{path}" + (f"?{qs}" if qs else "")


def http_json(url: str, body: dict | None = None, timeout: int = 30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=UA)
    with urllib.request.urlopen(req, context=CTX, timeout=timeout) as resp:
        return json.loads(resp.read())


def parse_ts(value) -> datetime | None:
    """Parse ISO strings or epoch numbers into aware UTC datetimes; None on failure."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            # Hosts emit epoch seconds in some fields and epoch ms in others;
            # observed live: latest-json `timestamp` is SECONDS. Disambiguate by
            # magnitude (>1e11 ≈ year 5138 in seconds, so it must be ms).
            v = float(value)
            if v > 1e11:
                v /= 1000.0
            return datetime.fromtimestamp(v, tz=timezone.utc)
        s = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            # Host-written timestamps are host-local; treat as UTC — thresholds
            # are generous enough that an hour or two of tz skew flags WARN, not DOWN.
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def age_seconds(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    # Hosts may write local-time ISO strings without tz info; parsed as UTC they can
    # land "in the future". Negative age = clock/tz skew, not a stale capture — clamp.
    return max(0.0, age)


def human_duration(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = int(seconds)
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s // 60}m"
    if s < 172800:
        return f"{s // 3600}h{(s % 3600) // 60:02d}"
    return f"{s // 86400}d"


def fetch_hosts(server: str, token: str) -> list[dict]:
    data = http_json(_url(server, "/server/system/getAllHosts", token,
                          include_system_stats="true"))
    if not data.get("success", True):
        raise RuntimeError(f"getAllHosts failed: {data}")
    return data.get("hosts", [])


def fetch_alerts(server: str, token: str) -> list[dict]:
    data = http_json(_url(server, "/server/alerts/getAllAlerts", token,
                          active_limit=500, resolved_limit=500))
    return data.get("alerts", []) if isinstance(data, dict) else []


def fetch_script_results(server: str, token: str, team: str) -> list[dict]:
    data = http_json(_url(server, "/server/script-results/getAllScriptResults", token,
                          team_id=team, limit=500))
    return data if isinstance(data, list) else data.get("results", [])


def fetch_latest_json(server: str, token: str, host_name: str, device_id: str) -> dict:
    return http_json(_url(server, "/server/monitoring/latest-json", token),
                     body={"host_name": host_name, "device_id": device_id}, timeout=20)


def summarize_alerts(alerts: list[dict], host_name: str, device_id: str) -> dict:
    """Open incidents (with oldest start per type) + last-24h counts for one device."""
    now = datetime.now(timezone.utc)
    open_since: dict[str, datetime] = {}   # incident_type -> oldest active start
    counts_24h: dict[str, int] = {}
    for a in alerts:
        if a.get("host_name") != host_name or a.get("device_id") != device_id:
            continue
        itype = a.get("incident_type", "?")
        started = parse_ts(a.get("start_time"))
        if a.get("status") == "active" and started:
            if itype not in open_since or started < open_since[itype]:
                open_since[itype] = started
        if started and (now - started) <= timedelta(hours=24):
            counts_24h[itype] = counts_24h.get(itype, 0) + 1
    return {"open_since": open_since, "counts_24h": counts_24h}


def last_script_run(results: list[dict], host_name: str, device_name: str) -> dict | None:
    best, best_ts = None, None
    for r in results:
        if r.get("host_name") != host_name or r.get("device_name") != device_name:
            continue
        ts = parse_ts(r.get("completed_at") or r.get("created_at"))
        if ts and (best_ts is None or ts > best_ts):
            best, best_ts = r, ts
    return best


def device_is_active(device: dict, run: dict | None) -> bool:
    """Passive activity signal: running deployment, or a script run inside the window."""
    if device.get("has_running_deployment"):
        return True
    if run:
        ts = parse_ts(run.get("completed_at") or run.get("created_at"))
        if ts and age_seconds(ts) is not None and age_seconds(ts) < ACTIVITY_WINDOW_H * 3600:
            return True
    return False


def assess_device(host: dict, device: dict, latest: dict | None, latest_err: str | None,
                  asum: dict, run: dict | None) -> tuple[str, str, str]:
    """Return (verdict, since, reason).

    Layer-aware per GOAL-04 guardrails, and reconciled with the CURRENT frame so the
    verdict matches what the GUI shows: an open incident whose condition has already
    cleared on the latest frame is reported as recovering/flapping, not as a fault.
    """
    now = datetime.now(timezone.utc)
    open_since: dict[str, datetime] = asum["open_since"]

    def since_str(itype: str) -> str:
        dt = open_since.get(itype)
        if not dt:
            return "—"
        return f"{dt.strftime('%m-%d %H:%M')} ({human_duration((now - dt).total_seconds())})"

    if host.get("status") == "offline":
        return "DOWN", "—", (f"host offline (network/host layer) — "
                             f"last seen {host.get('last_seen', '?')}")

    if not device.get("video_capture_path"):
        if open_since:
            worst = min(open_since.items(), key=lambda kv: kv[1])
            return "DEGRADED", since_str(worst[0]), \
                f"open incidents: {', '.join(sorted(open_since))} (no video signal to cross-check)"
        return "UNKNOWN", "—", "no capture path configured — no passive video signal available"

    if latest_err:
        return "UNKNOWN", "—", f"monitoring unreachable ({latest_err}) — cannot assess capture layer"

    if not latest or not latest.get("success"):
        msg = (latest or {}).get("error", "no monitoring data")
        return "DEGRADED", "—", f"capture layer: {msg} (monitor not running or no frames yet)"

    jd = latest.get("json_data") or {}
    frame_age = age_seconds(parse_ts(jd.get("timestamp") or latest.get("timestamp")))

    if frame_age is not None and frame_age > FRESH_DOWN_S:
        return "DOWN", "—", (f"capture stalled — latest frame {human_duration(frame_age)} old "
                             f"(ffmpeg/monitor layer on host, not the device)")

    active = device_is_active(device, run)
    desktop = device.get("device_model") in DESKTOP_MODELS
    cur_freeze = bool(jd.get("freeze"))
    cur_black = bool(jd.get("blackscreen"))

    issues: list[tuple[str, str]] = []  # (since, text)

    if cur_black:
        issues.append((since_str("blackscreen"),
                       "blackscreen NOW — possibly device asleep (needs POWER) or no signal; "
                       "check host capture side before blaming the device"))
    if cur_freeze and active and not desktop:
        issues.append((since_str("freeze"),
                       "freeze DURING ACTIVITY — static picture while device is in use"))
    if "audio_loss" in open_since and jd.get("audio") is False and not desktop:
        issues.append((since_str("audio_loss"), "audio loss ongoing (confirmed by current frame)"))
    if frame_age is not None and frame_age > FRESH_WARN_S:
        issues.append(("—", f"frames lagging ({human_duration(frame_age)} old)"))

    # Open incidents whose condition has CLEARED on the current frame → recovering,
    # not a fault. This is what makes the report agree with the GUI.
    recovering = [t for t in open_since
                  if (t == "freeze" and not cur_freeze)
                  or (t == "blackscreen" and not cur_black)]
    if recovering:
        rec = ", ".join(f"{t} open since {since_str(t)} but current frame clear "
                        f"(flapping or just recovered)" for t in recovering)
        if not issues:
            return "OK", "—", f"capture fresh; {rec}"
        issues.append(("—", rec))

    if issues:
        since = next((s for s, _ in issues if s != "—"), "—")
        return "DEGRADED", since, "; ".join(t for _, t in issues)

    if cur_freeze and desktop:
        return "OK", "—", \
            "static desktop picture — normal for a VNC/PC host, even during activity (not a fault)"

    if cur_freeze and not active:
        return "IDLE", since_str("freeze"), \
            "static screen while idle — device likely healthy, nothing playing (not a fault)"

    fresh = f"capture fresh ({human_duration(frame_age)})" if frame_age is not None else "capture fresh"
    return "OK", "—", fresh


def db_insert_rows(rows: list[dict]) -> str:
    """Insert one row per device into fleet_health via Supabase REST.

    Writes with SUPABASE_SERVICE_ROLE_KEY. This used to use the anon key on the
    grounds that "the RLS policy is public" — true when it was written, false since
    the service_role lockdown (TASK-10) closed anon. Every run from 2026-09-08 to
    2026-09-17 generated and uploaded its report, then logged one WARNING line and
    exited 0 while writing nothing, so the table silently stopped nine days before
    anyone looked at it.

    Falls back to the anon key for an install that has not been locked down.
    Best-effort: returns a status string, never raises — a DB outage must not lose
    the report, which is uploaded before this runs.
    """
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "") or os.environ.get("SUPABASE_ANON_KEY", "")
    if not base or not key:
        return "skipped (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not in env)"
    try:
        req = urllib.request.Request(
            f"{base}/rest/v1/fleet_health",
            data=json.dumps(rows).encode(),
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Content-Type": "application/json", "Prefer": "return=minimal"},
        )
        with urllib.request.urlopen(req, context=CTX, timeout=30) as resp:
            return f"OK ({len(rows)} rows, HTTP {resp.status})"
    except Exception as e:
        return f"FAILED ({e})"


def ai_analyze(ctx: dict) -> str:
    """One-shot AI diagnosis for a problem device via the shared provider layer.

    Lazy import so the script stays stdlib-only unless --ai is requested; returns a
    readable 'unavailable' string instead of failing the report.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from shared.src.lib.utils.ai_utils import call_text_ai
    except Exception as e:
        return f"(AI unavailable: {e})"
    prompt = (
        "You are diagnosing one test-fleet device from passive monitoring signals.\n"
        f"Signals: {json.dumps(ctx, default=str)}\n"
        "Domain rules: IR/BLE transport never drops presses; the STB/device is rarely "
        "the culprit — suspect the host capture side first; sustained blackscreen "
        "usually means the device is asleep (needs POWER); freeze on an idle device "
        "is a static menu, not a fault; host_vnc models are PC desktops — a static "
        "screen is normal even during activity and they have no audio path, so freeze/"
        "audio signals are never faults there.\n"
        "Reply with EXACTLY two short sentences: (1) most likely cause naming the layer "
        "(host-capture / device-asleep / idle-content / network / real-fault), "
        "(2) the single next action."
    )
    try:
        res = call_text_ai(prompt, max_tokens=120, temperature=0.1)
        if res.get("success"):
            return " ".join(res.get("content", "").split())
        return f"(AI failed: {res.get('error', 'unknown')})"
    except Exception as e:
        return f"(AI failed: {e})"


def fmt_run(run: dict | None) -> str:
    if not run:
        return "—"
    ok = "✅" if run.get("success") else "❌"
    when = (run.get("completed_at") or run.get("created_at") or "?")[:16].replace("T", " ")
    return f"{ok} {run.get('script_name', '?')} ({when})"


def fmt_counts(counts: dict) -> str:
    return ", ".join(f"{k}:{v}" for k, v in sorted(counts.items())) if counts else "—"


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily fleet health report (passive probes only)")
    ap.add_argument("--servers", default=DEFAULT_SERVERS,
                    help="comma-separated backend server base URLs")
    ap.add_argument("--team", default=DEFAULT_TEAM)
    ap.add_argument("--token", default=DEFAULT_TOKEN, help="AUTO_SIGN_TOKEN (or env)")
    ap.add_argument("--ai", action="store_true",
                    help="add per-device AI diagnosis for non-OK devices")
    ap.add_argument("--upload-r2", action="store_true",
                    help="upload the report under fleet-health/ via the storage layer "
                         "(CLOUDFLARE_R2_* env, or the MINIO_* fallback used on the server VM)")
    ap.add_argument("--no-db", action="store_true",
                    help="skip inserting per-device rows into the fleet_health table")
    ap.add_argument("--output", default=None, help="output .md path")
    args = ap.parse_args()

    run_ts = datetime.now(timezone.utc)  # uniform per run — all DB rows share it
    db_rows: list[dict] = []

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    default_name = f"fleet_health_{today}.md"
    if args.output and (args.output.endswith(os.sep) or os.path.isdir(args.output)):
        out_path = os.path.join(args.output, default_name)   # --output may be a directory
    else:
        out_path = args.output or default_name

    sections: list[str] = []
    tally = {"OK": 0, "IDLE": 0, "DEGRADED": 0, "DOWN": 0, "UNKNOWN": 0}
    summary_rows: list[tuple[str, str, str, str, str]] = []  # (server, host, device, verdict, since)

    ai_col = args.ai
    header = ("| Device | Model | Verdict | Since | Reason | 24h incidents | Last script run |"
              + (" AI analysis |" if ai_col else ""))
    divider = "|---|---|---|---|---|---|---|" + ("---|" if ai_col else "")

    for server in [s.strip().rstrip("/") for s in args.servers.split(",") if s.strip()]:
        try:
            hosts = fetch_hosts(server, args.token)
        except Exception as e:
            sections.append(f"## {server}\n\n**UNREACHABLE:** getAllHosts failed: {e}\n")
            continue

        try:
            alerts = fetch_alerts(server, args.token)
        except Exception as e:
            alerts = []
            sections.append(f"> ⚠️ {server}: alerts fetch failed ({e}) — incident columns empty\n")
        try:
            results = fetch_script_results(server, args.token, args.team)
        except Exception as e:
            results = []
            sections.append(f"> ⚠️ {server}: script-results fetch failed ({e}) — last-run column empty\n")

        sections.append(f"## {server}\n")
        for host in sorted(hosts, key=lambda h: h.get("host_name", "")):
            host_name = host.get("host_name", "?")
            status = host.get("status", "?")
            sections.append(f"### {host_name} — {status} "
                            f"(v{host.get('deployed_version', '?')}, "
                            f"{host.get('device_count', len(host.get('devices', [])))} devices)\n")
            sections.append(header)
            sections.append(divider)

            for device in host.get("devices", []) or []:
                device_id = device.get("device_id", "?")
                device_name = device.get("device_name", device_id)
                asum = summarize_alerts(alerts, host_name, device_id)
                run = last_script_run(results, host_name, device_name)

                latest, latest_err = None, None
                if status != "offline" and device.get("video_capture_path"):
                    try:
                        latest = fetch_latest_json(server, args.token, host_name, device_id)
                    except Exception as e:
                        latest_err = str(e)

                verdict, since, reason = assess_device(host, device, latest, latest_err, asum, run)
                tally[verdict] += 1
                summary_rows.append((server.split("//")[-1], host_name, device_name, verdict, since))

                ai_text = None
                ai_cell = ""
                if ai_col:
                    if verdict in ("OK",):
                        ai_cell = " — |"
                    else:
                        jd = (latest or {}).get("json_data") or {}
                        ai_text = ai_analyze({
                            "host": host_name, "device": device_name,
                            "model": device.get("device_model"),
                            "verdict": verdict, "since": since, "reason": reason,
                            "open_incidents": {k: v.isoformat() for k, v in asum["open_since"].items()},
                            "incidents_24h": asum["counts_24h"],
                            "current_frame": {k: jd.get(k) for k in
                                              ("freeze", "blackscreen", "audio", "timestamp")},
                            "last_script_run": fmt_run(run),
                        })
                        ai_cell = " " + ai_text + " |"

                issue_since_dt = min(asum["open_since"].values()) if asum["open_since"] else None
                db_rows.append({
                    "generated_at": run_ts.isoformat(),
                    "run_date": today,
                    "server": server.split("//")[-1],
                    "host_name": host_name,
                    "device_id": device_id,
                    "device_name": device_name,
                    "device_model": device.get("device_model"),
                    "verdict": verdict,
                    "issue_since": issue_since_dt.isoformat() if issue_since_dt else None,
                    "reason": reason,
                    "ai_analysis": ai_text,
                    "open_incidents": {k: v.isoformat() for k, v in asum["open_since"].items()},
                    "incidents_24h": asum["counts_24h"],
                    "last_script_name": run.get("script_name") if run else None,
                    "last_script_success": run.get("success") if run else None,
                    "last_script_at": (run.get("completed_at") or run.get("created_at")) if run else None,
                })

                sections.append(
                    f"| {device_name} ({device_id}) | {device.get('device_model', '?')} "
                    f"| **{verdict}** | {since} | {reason} | {fmt_counts(asum['counts_24h'])} "
                    f"| {fmt_run(run)} |{ai_cell}")
            sections.append("")

    # Assemble report: summary first
    lines = [
        f"# Fleet Health Report — {today}",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
        "passive probes only (no device control taken)",
        "",
        f"**Fleet:** ✅ OK {tally['OK']} · 💤 IDLE {tally['IDLE']} · "
        f"⚠️ DEGRADED {tally['DEGRADED']} · 🔴 DOWN {tally['DOWN']} · "
        f"❔ UNKNOWN {tally['UNKNOWN']}",
        "",
    ]
    attention = [(s, h, d, v, sn) for (s, h, d, v, sn) in summary_rows
                 if v in ("DEGRADED", "DOWN", "UNKNOWN")]
    if attention:
        lines += ["**Needs attention:**", ""]
        for s, h, d, v, sn in attention:
            icon = "🔴" if v == "DOWN" else ("❔" if v == "UNKNOWN" else "⚠️")
            since_part = f" since {sn}" if sn != "—" else ""
            lines.append(f"- {icon} `{h}/{d}` — {v}{since_part} ({s})")
        lines.append("")
    lines += sections

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Report written: {out_path}")
    print(f"Fleet: OK={tally['OK']} IDLE={tally['IDLE']} DEGRADED={tally['DEGRADED']} "
          f"DOWN={tally['DOWN']} UNKNOWN={tally['UNKNOWN']}")

    report_url = None
    if args.upload_r2:
        # Best-effort: the local report is the source of truth; a failed upload is a
        # journal warning, not a failed run (report generation already succeeded).
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
            remote_path = f"fleet-health/{os.path.basename(out_path)}"
            r2 = get_cloudflare_utils()
            res = r2.upload_files([{"local_path": out_path, "remote_path": remote_path}],
                                  auto_delete_cold=False)
            if res.get("uploaded_files"):
                report_url = r2.get_url_for_report_asset(remote_path)
                print(f"R2 upload OK: {report_url}")
            else:
                print(f"WARNING: R2 upload failed: {res.get('failed_uploads')}")
        except Exception as e:
            print(f"WARNING: R2 upload unavailable: {e}")

    if not args.no_db and db_rows:
        for row in db_rows:
            row["report_url"] = report_url
        status = db_insert_rows(db_rows)
        if status.startswith("OK"):
            print(f"DB insert: {status}")
        else:
            # Exit non-zero so systemd marks the unit failed. Printing a WARNING and
            # returning 0 is exactly how this went unnoticed for nine days: the timer
            # kept reporting success while the table stopped growing. The report is
            # already written and uploaded by this point, so failing here costs
            # nothing except the visibility it should have had all along.
            print(f"ERROR: DB insert: {status}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
