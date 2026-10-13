#!/usr/bin/env python3
"""
TASK-79 Phase 2 — end-to-end browser latency via SSH-tunneled local
test page + hls.js.

The test page (scripts/hls_test.html) is served by python3 -m http.server
on 127.0.0.1:8765, and the m3u8 source is reached via an SSH tunnel
(127.0.0.1:16109 -> vpt-pi3:192.168.1.144:6109). Both origins are
http://127.0.0.1:* so CORS does not apply. hls.js xhrSetup injects
X-API-Key (vpt-pi3 Flask is unauthenticated for /stream/*, so X-API-Key
isn't needed, but is sent harmlessly).

We then poll window.__hls.playingDate and report the same metrics as
the server-side LAN script.
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
        browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required", "--disable-features=AudioServiceOutOfProcess"])
        ctx = browser.new_context(viewport={"width": 1280, "height": 720}, ignore_https_errors=True)
        page = ctx.new_page()

        page.on("pageerror", lambda e: print(f"  [pageerror] {e}", file=sys.stderr))
        page.on("console", lambda m: print(f"  [console.{m.type}] {m.text[:300]}", file=sys.stderr) if m.type in ("error", "warning", "log") else None)
        page.on("requestfailed", lambda r: print(f"  [requestfailed] {r.url[:120]} - {r.failure}", file=sys.stderr))

        print(f"Loading {TEST_PAGE}", file=sys.stderr)
        page.goto(TEST_PAGE, wait_until="domcontentloaded", timeout=15000)
        # Wait for hls.js to parse manifest and start playing
        try:
            page.wait_for_function("window.__hls && window.__hls.playingDate", timeout=20000)
            print("Manifest parsed, hls.playingDate set.", file=sys.stderr)
        except Exception as e:
            print(f"Timeout waiting for hls.playingDate: {e}", file=sys.stderr)
            state = page.evaluate("""() => ({
                hasHls: !!window.__hls,
                hlsLatency: window.__hls ? window.__hls.latency : null,
                hlsPlayingDate: window.__hls && window.__hls.playingDate ? window.__hls.playingDate.toISOString() : null,
                bodyText: document.body ? document.body.innerText.slice(0, 200) : null,
            })""")
            print(f"Final state: {state}", file=sys.stderr)
            browser.close()
            sys.exit(1)

        # Initial snapshot
        snap = page.evaluate("""() => {
            const h = window.__hls;
            return {
                latency: h.latency,
                targetLatency: h.targetLatency,
                playingDate: h.playingDate ? h.playingDate.toISOString() : null,
                firstLevel: h.levels?.[0]?.bitrate,
            };
        }""")
        print(f"initial: {snap}", file=sys.stderr)

        # 60 s measurement loop
        readings = []
        stalls = 0
        last_cur = None
        start = time.monotonic()
        while time.monotonic() - start < 60:
            s = page.evaluate("""() => {
                const h = window.__hls;
                const v = document.querySelector('video');
                let wall = null;
                if (h && h.playingDate) {
                    wall = (Date.now() - h.playingDate.getTime()) / 1000;
                }
                return {
                    wall,
                    hlsLat: h ? h.latency : null,
                    hlsTgt: h ? h.targetLatency : null,
                    curTime: v ? v.currentTime : null,
                    paused: v ? v.paused : null,
                    readyState: v ? v.readyState : null,
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
            if int(elapsed) % 5 == 0:
                print(f"  t={elapsed:5.1f}s  wall={s.get('wall')!r}  hls.lat={s.get('hlsLat')}  tgt={s.get('hlsTgt')}  cur={s.get('curTime')!r}  paused={s.get('paused')}  stalled={s.get('stalled')}", file=sys.stderr)
            page.wait_for_timeout(1000)

        # 3 spot readings
        spot = []
        for _ in range(3):
            w = page.evaluate("""() => {
                const h = window.__hls;
                return (h && h.playingDate) ? (Date.now() - h.playingDate.getTime()) / 1000 : null;
            }""")
            spot.append(w)
            page.wait_for_timeout(300)

        result = {
            'mode': 'end-to-end (hls.js + local HTTP server + SSH tunnel to vpt-pi3 LAN)',
            'device': 'vpt-pi3 / device1 (FireTv) on capture1',
            'note': 'Same origin (127.0.0.1), so CORS does not apply. m3u8 hits the vpt-pi3 Flask at LAN IP via SSH tunnel. Adds the user-browser decode + hls.js target on top of the server-side 0.473 s.',
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
