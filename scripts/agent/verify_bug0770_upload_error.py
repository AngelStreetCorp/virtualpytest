#!/usr/bin/env python3
"""Live check that a failed artifact upload is now VISIBLE (BUG-0770).

`labox-backend` carries storage credentials the object store does not know, so
every upload it attempts fails. Before the fix the run simply had no report and
no logs and said nothing about why. The platform side now keeps the reason:
the review pack carries "Artifact upload failed: ..." and the run metadata
carries `artifact_upload_error`.

Run it under a lease:
  ssh proxmox '~/bin/vpt-lease run node1-vpt labox-backend/host --agent ... -- <this script>'
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "https://virtualpytest.angelstreet.io"
TEAM = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"
HOST = "labox-backend"
DEVICE = "host"
SCRIPT = "av_check.py"


def api(path: str, token: str, method: str = "GET", body: dict | None = None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-Auto-Sign", token)
    # The edge in front of the app rejects a request without a browser signature
    # (Cloudflare error 1010).
    req.add_header("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    req.add_header("Accept", "application/json")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw or "{}")
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:400]}
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": str(exc)}


def main() -> int:
    token = subprocess.run(
        ["scripts/agent/auto_sign_token.sh"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    status, started = api(
        "/server/script/execute?team_id=" + TEAM,
        token,
        method="POST",
        body={"host_name": HOST, "device_id": DEVICE, "script_name": SCRIPT},
    )
    print(f"execute -> HTTP {status}: {json.dumps(started)[:300]}")
    if status not in (200, 202):
        return 1
    task_id = (
        started.get("task_id")
        or started.get("taskId")
        or started.get("script_task_id")
        or started.get("id")
    )
    if not task_id:
        print("no task_id in the answer; keys:", sorted(started.keys()))
        print(json.dumps(started)[:2000])
        return 1

    task = {}
    for _ in range(90):
        time.sleep(4)
        status, payload = api(f"/server/script/status/{task_id}?team_id={TEAM}", token)
        task = (payload or {}).get("task") or {}
        state = str(task.get("status") or task.get("state") or "")
        if state.lower() in ("completed", "failed", "error", "done", "success"):
            print(f"task state: {state} (after {90 * 4}s budget)")
            break
    print("task keys:", sorted(task.keys()))
    result = task.get("result") or {}
    print("result keys:", sorted(result.keys())[:20] if isinstance(result, dict) else type(result))

    # The result id of the run, wherever the task carries it.
    result_id = None
    for source in (result, task):
        if isinstance(source, dict):
            for key in ("script_result_id", "result_id", "scriptResultId"):
                if source.get(key):
                    result_id = source[key]
                    break
        if result_id:
            break

    if not result_id:
        status, listing = api(f"/server/script-results/getAllScriptResults?team_id={TEAM}", token)
        rows = listing.get("results") or listing.get("script_results") or listing.get("data") or []
        rows = rows if isinstance(rows, list) else []
        same = [r for r in rows if (r.get("script_name") or "").endswith(SCRIPT)]
        if same:
            result_id = same[0].get("id") or same[0].get("script_result_id")
    print("result_id:", result_id)

    failures = []
    if not result_id:
        failures.append("no script result id found for the run")
    else:
        status, review = api(
            f"/server/script-results/getVerificationReviewMarkdown/{result_id}?team_id={TEAM}", token
        )
        text = review.get("markdown") or review.get("review_markdown") or json.dumps(review)
        print("\n=== review pack (excerpt) ===")
        for line in str(text).splitlines():
            if any(word in line.lower() for word in ("upload", "report", "logs", "error", "failed")):
                print("  ", line.strip()[:220])
        if "artifact upload failed" not in str(text).lower():
            failures.append("the review pack does not say that the upload failed")

        status, row = api(f"/server/script-results/getAllScriptResults?team_id={TEAM}", token)
        rows = row.get("results") or row.get("script_results") or row.get("data") or []
        rows = rows if isinstance(rows, list) else []
        mine = [r for r in rows if str(r.get("id")) == str(result_id)]
        if mine:
            meta = mine[0].get("metadata") or {}
            upload_error = meta.get("artifact_upload_error")
            print("\nmetadata.artifact_upload_error:", upload_error)
            print("metadata.verification_review:",
                  json.dumps(meta.get("verification_review") or {})[:220])
            if not upload_error:
                failures.append("the run metadata carries no artifact_upload_error")
        else:
            failures.append("the run row was not found in getAllScriptResults")

    print("\n=== RESULT ===")
    if failures:
        for f in failures:
            print("  FAIL:", f)
        return 1
    print("  the failed upload is visible in the product")
    return 0


if __name__ == "__main__":
    sys.exit(main())
