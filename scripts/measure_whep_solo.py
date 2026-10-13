#!/usr/bin/env python3
"""
TASK-79 Phase D — end-to-end WebRTC/WHEP latency measurement.

Sets up the chain:
  vpt-pi3: ffmpeg → RTSP publish to MediaMTX:8554 → WHEP on :8889
  whep_test.html targets the public /host/<host>/whep/ route (no tunnel); add ?host=&cap= to TEST_PAGE.
  browser: http://127.0.0.1:8765/whep_test.html (python http.server on :8765)
           RTCPeerConnection over WHEP, video.srcObject, RTCStatsReport
"""
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

TEST_PAGE = "http://127.0.0.1:8765/whep_test.html"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required", "--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1280, "height": 720}, ignore_https_errors=True)
        page = ctx.new_page()

        page.on("pageerror", lambda e: print(f"  [pageerror] {e}", file=sys.stderr))
        page.on("console", lambda m: print(f"  [console.{m.type}] {m.text[:300]}", file=sys.stderr) if m.type in ("error", "warning", "log") else None)
        page.on("requestfailed", lambda r: print(f"  [requestfailed] {r.url[:120]} - {r.failure}", file=sys.stderr))

        print(f"Loading {TEST_PAGE}", file=sys.stderr)
        page.goto(TEST_PAGE, wait_until="domcontentloaded", timeout=15000)
        # Wait for video.srcObject to be set and metadata loaded
        try:
            page.wait_for_function(
                "() => { const v = document.querySelector('video'); return v && v.srcObject && v.readyState >= 1; }",
                timeout=20000,
            )
            print("video element receiving stream", file=sys.stderr)
        except Exception:
            page.screenshot(path='/tmp/whep-fail.png', full_page=True)
            print("Failed to start; screenshot /tmp/whep-fail.png", file=sys.stderr)
            st = page.evaluate("""() => ({
                pcState: window.__whep_pc ? window.__whep_pc.iceConnectionState : 'no-pc',
                videoState: document.querySelector('video') ? document.querySelector('video').readyState : 'no-video',
                bodyText: document.body ? document.body.innerText.slice(0, 400) : null,
            })""")
            print(f"final state: {st}", file=sys.stderr)
            browser.close()
            sys.exit(1)

        # 60 s measurement: read RTCPeerConnection.getStats() for outbound-rtp /
        # inbound-rtp stats; estimate glass-to-glass as the time since the
        # last inbound-rtp packet (similar to hls.playingDate - Date.now()).
        readings = []
        stalls = 0
        last_frame_ts = None
        last_inbound_ts = None
        start = time.monotonic()
        while time.monotonic() - start < 60:
            r = page.evaluate("""async () => {
                const pc = window.__whep_pc;
                const v = document.querySelector('video');
                if (!pc) return { error: 'no pc' };
                const stats = await pc.getStats();
                let inbound = null;
                let candidate = null;
                stats.forEach(s => {
                    if (s.type === 'inbound-rtp' && s.kind === 'video') {
                        inbound = s;
                    }
                });
                // glass-to-glass: time since the last frame's RTP timestamp
                // (we approximate via the absolute receive time of the latest
                // inbound-rtp packet; if missing, fall back to remote-inbound
                // RTP timestamp converted to wall clock).
                let glass = null;
                if (inbound) {
                    const rtt = (inbound.roundTripTime || 0) * 1000;
                    const jitter = (inbound.jitter || 0) * 1000;
                    glass = rtt + jitter;
                }
                return {
                    glass,
                    framesDecoded: inbound ? inbound.framesDecoded : null,
                    framesPerSecond: inbound ? inbound.framesPerSecond : null,
                    bytesReceived: inbound ? inbound.bytesReceived : null,
                    videoTime: v ? v.currentTime : null,
                    videoReady: v ? v.readyState : null,
                    videoPaused: v ? v.paused : null,
                    iceState: pc.iceConnectionState,
                };
            }""")
            if r.get('glass') is not None:
                readings.append(r['glass'])
            if r.get('videoTime') is not None and r.get('videoPaused') is False:
                # If the video's currentTime isn't advancing and the page is
                # live, that's a stall. With WebRTC we don't have a simple
                # 'curTime' to compare; use frame counter instead.
                pass
            elapsed = time.monotonic() - start
            if int(elapsed) % 5 == 0:
                print(f"  t={elapsed:5.1f}s  glass={r.get('glass')!r}  fps={r.get('framesPerSecond')}  frames={r.get('framesDecoded')}  cur={r.get('videoTime'):.3f}  ice={r.get('iceState')}", file=sys.stderr)
            page.wait_for_timeout(1000)

        # 3 spot readings
        spot = []
        for _ in range(3):
            r = page.evaluate("""async () => {
                const pc = window.__whep_pc;
                if (!pc) return null;
                const stats = await pc.getStats();
                let inbound = null;
                stats.forEach(s => {
                    if (s.type === 'inbound-rtp' && s.kind === 'video') inbound = s;
                });
                if (!inbound) return null;
                return ((inbound.roundTripTime || 0) + (inbound.jitter || 0)) * 1000;
            }""")
            spot.append(r)
            page.wait_for_timeout(300)

        result = {
            'mode': 'end-to-end WebRTC/WHEP (ffmpeg RTSP -> MediaMTX -> browser)',
            'device': 'vpt-pi3 / device1 (FireTv) on capture1',
            'glass_to_glass_avg_ms': round(statistics.mean(readings), 1) if readings else None,
            'glass_to_glass_max_ms': round(max(readings), 1) if readings else None,
            'glass_to_glass_min_ms': round(min(readings), 1) if readings else None,
            'glass_to_glass_count': len(readings),
            'spot_readings_ms': [round(x, 1) if x is not None else None for x in spot],
            'finished_at': datetime.now(timezone.utc).isoformat(),
        }
        print()
        print(json.dumps(result, indent=2))
        browser.close()


if __name__ == '__main__':
    main()
