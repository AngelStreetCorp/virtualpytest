#!/usr/bin/env python3
"""
VirtualPyTest Smoke — Video Stream Verification

Verifies that the HLS video stream pipeline is working end-to-end:
  1. At least one host is registered with a device
  2. The host returns a valid stream URL for the device
  3. The HLS playlist (output.m3u8) is accessible and has valid content
  4. At least one video segment (.ts) is reachable from the playlist

This is what the frontend's RecHostPreview and RecHostStreamModal
rely on — if these checks pass, the stream should play in the UI.

Usage:
    python test_scripts/vpt/smoke_video_stream.py
    python test_scripts/vpt/smoke_video_stream.py --server http://192.168.0.103:5109
"""

import sys
import os
import time
import requests

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_args, get_context
from shared.src.lib.utils.build_url_utils import get_host_api_origin
from test_scripts.vpt.smoke_common import headers as _headers, make_step as _step_base


def _step(action: str, description: str, success: bool, error: str = None,
          status_code: int = None, ms: float = 0, detail: str = None) -> dict:
    return _step_base(action, description, success, error=error,
                       status_code=status_code, response_time_ms=ms, detail=detail)


def capture_summary(context, server_url: str, stream_url: str = None) -> str:
    total = len(context.step_results)
    passed = sum(1 for s in context.step_results if s.get("success"))
    lines = [
        "-" * 60,
        "🎯 [VPT SMOKE VIDEO STREAM] EXECUTION SUMMARY",
        "-" * 60,
        f"🌐 Server: {server_url}",
        f"📺 Stream URL: {stream_url or 'not resolved'}",
        f"⏱️ Total Time: {context.get_execution_time_ms() / 1000:.1f}s",
        f"📊 Checks: {total}  ✅ {passed}  ❌ {total - passed}",
        "",
        "📋 Check Results:",
    ]
    for s in context.step_results:
        icon = "✅" if s["success"] else "❌"
        err = f" — {s['error']}" if s.get("error") else ""
        lines.append(f"   {icon} {s['description']}{err}")
    lines += ["", f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}", "-" * 60]
    return "\n".join(lines)


@script("smoke_video_stream", "Verify VirtualPyTest HLS video stream is accessible and playing")
def main():
    context = get_context()
    args = get_args()
    server_url = getattr(args, "server", None) or os.getenv("SERVER_URL", "http://localhost:5109")
    team_id = context.team_id
    stream_url = None

    print(f"🔍 [smoke_video_stream] Verifying HLS stream pipeline at {server_url}")

    # ── Step 1: Get a host with a device ──────────────────────────────────────
    host_info = None
    device_id = None
    host_url = None
    candidates = []
    try:
        t0 = time.time()
        resp = requests.get(
            f"{server_url}/server/system/getAllHosts",
            params={"team_id": team_id},
            headers=_headers(), timeout=10, verify=False,
        )
        ms = round((time.time() - t0) * 1000, 1)
        data = resp.json() if resp.status_code == 200 else {}
        hosts = [h for h in data.get("hosts", []) if h.get("status") == "online"]
        ok = len(hosts) > 0
        context.record_step_immediately(_step(
            "GET /server/system/getAllHosts",
            f"Online host found ({len(hosts)} online)",
            ok,
            error=None if ok else "No online hosts",
            status_code=resp.status_code if not ok else None,
            ms=ms,
        ))
        # Deliberately do NOT just take hosts[0]/devices[0]: not every device
        # streams HLS. A host_vnc device answers getStreamUrl with a noVNC page
        # (/vnc_lite.html?...), so an HLS check against it fetches a .m3u8 that
        # was never going to exist. Find a device that actually serves a playlist.
        candidates = hosts
    except Exception as e:
        context.record_step_immediately(_step("GET /server/system/getAllHosts", "Online host found", False, error=str(e)))

    if not candidates:
        context.overall_success = False
        context.execution_summary = capture_summary(context, server_url)
        return False

    # ── Step 2: Find a device that serves an HLS stream ────────────────────────
    stream_url = None
    probed = []
    t0 = time.time()
    for candidate in candidates:
        # `host_url` is browser-relative (/host/<name>) — a reverse-proxy route.
        # Prefixing it with the backend server's origin 404s, because :5109 does
        # not serve that path. Use the direct origin the server calls hosts on.
        base = get_host_api_origin(candidate)
        if not base:
            continue
        for dev in (candidate.get("devices") or [{"device_id": "device1"}]):
            dev_id = dev.get("device_id", "device1")
            try:
                r = requests.get(
                    f"{base}/host/av/getStreamUrl",
                    params={"device_id": dev_id},
                    headers=_headers(), timeout=8, verify=False,
                )
                url = (r.json() or {}).get("stream_url") if r.status_code == 200 else None
            except Exception:
                url = None
            probed.append(f"{candidate.get('host_name')}/{dev_id}={url or 'n/a'}")
            if url and ".m3u8" in url:
                host_info, host_url, device_id, stream_url = candidate, base, dev_id, url
                break
        if stream_url:
            break

    ms = round((time.time() - t0) * 1000, 1)
    ok = bool(stream_url)
    context.record_step_immediately(_step(
        "GET /host/av/getStreamUrl",
        (f"HLS stream URL resolved on '{host_info.get('host_name')}' device '{device_id}'"
         if ok else "HLS stream URL resolved"),
        ok,
        error=None if ok else
        f"No device serves an HLS playlist. Probed: {', '.join(probed) or 'none'}",
        ms=ms,
        detail=stream_url if ok else None,
    ))

    if not stream_url:
        context.overall_success = False
        context.execution_summary = capture_summary(context, server_url)
        return False

    # Resolve the stream URL against the host's own origin. getStreamUrl returns
    # the PROXY form, "/host/<host_name>/stream/...", where "/host/<host_name>" is
    # the prefix nginx maps onto the host. The host itself serves the remainder at
    # its root, so that prefix has to come off — verified on labox-dongle:
    #   /host/labox-dongle/stream/capture1/segments/output.m3u8 -> 404
    #   /stream/capture1/segments/output.m3u8                   -> 200
    proxy_prefix = f"/host/{host_info.get('host_name', '')}"
    if stream_url.startswith(f"{proxy_prefix}/"):
        stream_url = host_url + stream_url[len(proxy_prefix):]
    elif stream_url.startswith("/"):
        stream_url = host_url + stream_url

    # ── Step 3: Fetch HLS playlist ─────────────────────────────────────────────
    segment_urls = []
    try:
        t0 = time.time()
        resp = requests.get(stream_url, timeout=10, verify=False)
        ms = round((time.time() - t0) * 1000, 1)
        content_type = resp.headers.get("Content-Type", "")
        is_hls = "mpegurl" in content_type or "m3u8" in content_type or (
            resp.status_code == 200 and resp.text.strip().startswith("#EXTM3U")
        )
        ok = resp.status_code == 200 and is_hls

        # Parse segment URLs from playlist
        if ok:
            base_url = stream_url.rsplit("/", 1)[0] + "/"
            for line in resp.text.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    seg_url = line if line.startswith("http") else base_url + line
                    segment_urls.append(seg_url)

        context.record_step_immediately(_step(
            f"GET {stream_url}",
            f"HLS playlist accessible (m3u8)",
            ok,
            error=None if ok else f"HTTP {resp.status_code}, type={content_type}",
            status_code=resp.status_code,
            ms=ms,
            detail=f"{len(segment_urls)} segments found" if ok and segment_urls else None,
        ))
    except Exception as e:
        context.record_step_immediately(_step(f"GET {stream_url}", "HLS playlist accessible", False, error=str(e)))

    # ── Step 4: Fetch first video segment ─────────────────────────────────────
    if segment_urls:
        seg_url = segment_urls[-1]  # latest segment most likely to exist
        try:
            t0 = time.time()
            resp = requests.get(seg_url, timeout=10, verify=False)
            ms = round((time.time() - t0) * 1000, 1)
            ok = resp.status_code == 200 and len(resp.content) > 0
            context.record_step_immediately(_step(
                f"GET segment",
                f"Video segment downloadable",
                ok,
                error=None if ok else f"HTTP {resp.status_code} or empty",
                status_code=resp.status_code,
                ms=ms,
                detail=f"{len(resp.content) // 1024}KB" if ok else None,
            ))
        except Exception as e:
            context.record_step_immediately(_step("GET segment", "Video segment downloadable", False, error=str(e)))
    else:
        context.record_step_immediately(_step(
            "GET segment", "Video segment downloadable", False,
            error="No segments in playlist to verify",
        ))

    total = len(context.step_results)
    passed = sum(1 for s in context.step_results if s.get("success"))
    context.overall_success = passed == total and total > 0
    context.execution_summary = capture_summary(context, server_url, stream_url)
    print(f"\n{'✅' if context.overall_success else '❌'} [smoke_video_stream] {passed}/{total} checks OK")
    return context.overall_success


main._script_args = [
    "--userinterface:str:virtualpytest_web",  # tags script_results so the Self-Test dashboard picks the run up
    "--server:str:",  # Override SERVER_URL env var
]

if __name__ == "__main__":
    main()
