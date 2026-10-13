#!/usr/bin/env python3
"""
TASK-79 Phase C — re-measure end-to-end with a single hls.js instance.

The previous attempt drove the device-control page, which mounts hidden
hls.js instances for every device (vpt-mf1/capture{1..5},
vpt-pi1/capture{1,2}, vpt-pi3/capture{1,2,4}). With maxBufferLength: 6
each instance keeps 6s of segments in memory and fires ~30 segment
requests/sec through the CORS forwarder, which becomes the bottleneck.
The forwarder aborts segments and hls.js reports stalls (15/min) that
are not the stream's fault.

Use a standalone test page (scripts/hls_test.html) that hosts exactly
one hls.js + one <video>. The m3u8 hits
http://127.0.0.1:5109/host/vpt-pi3/stream/capture1/... which the CORS
forwarder proxies to rpitest.
"""
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

TEST_PAGE = "http://127.0.0.1:8765/hls_test.html"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required", "--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1280, "height": 720}, ignore_https_errors=True)
        page = ctx.new_page()

        page.on("pageerror", lambda e: print(f"  [pageerror] {e}", file=sys.stderr))
        page.on("requestfailed", lambda r: print(f"  [requestfailed] {r.url[:120]} - {r.failure}", file=sys.stderr))

        print(f"Loading {TEST_PAGE}", file=sys.stderr)
        page.goto(TEST_PAGE, wait_until="domcontentloaded", timeout=15000)
        try:
            page.wait_for_function("window.__hls && window.__hls.playingDate", timeout=20000)
            print("Manifest parsed, hls.playingDate set.", file=sys.stderr)
        except Exception:
            page.screenshot(path='/tmp/phase-c-fail.png', full_page=True)
            print("Failed to start; screenshot /tmp/phase-c-fail.png", file=sys.stderr)
            browser.close()
            sys.exit(1)

        snap = page.evaluate("""() => ({
            latency: window.__hls.latency,
            targetLatency: window.__hls.targetLatency,
            playingDate: window.__hls.playingDate?.toISOString(),
            firstLevel: window.__hls.levels?.[0]?.bitrate,
        })""")
        print(f"initial: {snap}", file=sys.stderr)

        readings = []
        stalls = 0
        last_cur = None
        start = time.monotonic()
        while time.monotonic() - start < 60:
            s = page.evaluate("""() => {
                const h = window.__hls;
                const v = document.querySelector('video');
                let wall = null;
                if (h?.playingDate) {
                    wall = (Date.now() - h.playingDate.getTime()) / 1000;
                }
                return {
                    wall,
                    hlsLat: h?.latency,
                    hlsTgt: h?.targetLatency,
                    curTime: v?.currentTime,
                    paused: v?.paused,
                    readyState: v?.readyState,
                    stalled: v ? (v.readyState < 3 && !v.paused) : false,
                };
            }""")
            if s.get('wall') is not None:
                readings.append(s['wall'])
            if s.get('stalled'):
                stalls += 1
            if s.get('curTime') is not None and last_cur is not None and abs(s['curTime'] - last_cur) < 0.01 and not s.get('paused'):
                stalls += 1
            last_cur = s.get('curTime')
            elapsed = time.monotonic() - start
            wall_str = f"{s.get('wall'):.3f}" if s.get('wall') is not None else 'n/a'
            if int(elapsed) % 5 == 0:
                print(f"  t={elapsed:5.1f}s  wall={wall_str}  hls.lat={s.get('hlsLat')}  tgt={s.get('hlsTgt')}  cur={s.get('curTime'):.2f}  stalled={s.get('stalled')}", file=sys.stderr)
            page.wait_for_timeout(1000)

        spot = []
        for _ in range(3):
            w = page.evaluate("""() => {
                const h = window.__hls;
                return (h?.playingDate) ? (Date.now() - h.playingDate.getTime()) / 1000 : null;
            }""")
            spot.append(w)
            page.wait_for_timeout(300)

        result = {
            'mode': 'end-to-end solo (1 hls.js via CORS forwarder, m3u8 on rpitest)',
            'device': 'vpt-pi3 / device1 (FireTv) on capture1',
            'wall_latency_avg_s': round(statistics.mean(readings), 3) if readings else None,
            'wall_latency_max_s': round(max(readings), 3) if readings else None,
            'wall_latency_min_s': round(min(readings), 3) if readings else None,
            'wall_latency_count': len(readings),
            'stalls_per_min': round(stalls, 1),
            'spot_readings_s': [round(x, 3) if x is not None else None for x in spot],
            'finished_at': datetime.now(timezone.utc).isoformat(),
        }
        print()
        print(json.dumps(result, indent=2))
        browser.close()


if __name__ == '__main__':
    main()
