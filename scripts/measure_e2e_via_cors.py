#!/usr/bin/env python3
"""
TASK-79 Phase 2 (real) — end-to-end browser latency via the worktree
frontend + CORS forwarder + rpitest.

Setup (the user pointed out TESTING.md which I missed):
  1. `node ~/.claude/skills/vpt-ui-restyle/cors_forwarder.mjs rpitest.angelstreet.io 5109`
     — localhost:5109 now forwards to rpitest.angelstreet.io:443 with full CORS
  2. `cd frontend && VITE_SERVER_URL=http://localhost:5109 VITE_HTTPS=false
     ./node_modules/.bin/vite --port 5073 --strictPort`
     — dev server with the new hlsLiveConfig + useLatencyDebug
  3. Open http://127.0.0.1:5073/?auto_signed=<token>&latency_debug=1
     — the URL token mints a fake admin session in the React app, which then
     mints a host session cookie for vpt-pi3 via the CORS-forwarded API
  4. Navigate to /device-control?host=vpt-pi3&device=device1, the HLSVideoPlayer
     mounts with the new LIVE_HLS_CONFIG, and the ?latency_debug overlay shows
     wall / hls / target / stalls in real time
"""
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _auto_sign import auto_sign_token, redact

# The auto-sign token is a team-admin credential: read it at runtime, never store it.
AUTO_SIGN = auto_sign_token()
BASE = "http://127.0.0.1:5073"
LANDING = f"{BASE}/?auto_signed={AUTO_SIGN}&latency_debug=1"
DEVICE_URL = f"{BASE}/device-control?host=vpt-pi3&device=device1&latency_debug=1"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required", "--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1400, "height": 900}, ignore_https_errors=True)
        page = ctx.new_page()

        page.on("pageerror", lambda e: print(f"  [pageerror] {redact(e, AUTO_SIGN)}", file=sys.stderr))
        page.on("console", lambda m: print(f"  [console.{m.type}] {redact(m.text[:300], AUTO_SIGN)}", file=sys.stderr) if m.type in ("error", "warning") else None)
        page.on("requestfailed", lambda r: print(f"  [requestfailed] {redact(r.url[:120], AUTO_SIGN)} - {r.failure}", file=sys.stderr))

        print(redact(f"Landing: {LANDING}", AUTO_SIGN), file=sys.stderr)
        page.goto(LANDING, wait_until="domcontentloaded", timeout=30000)
        # Let React bootstrap, auto-sign, Supabase mock, host session, etc.
        page.wait_for_timeout(8000)

        # Diagnostic: did auto-sign succeed? Check sessionStorage + page state
        diag = page.evaluate("""() => {
            return {
                ss: {
                    flag: sessionStorage.getItem('vpt_auto_signed'),
                    token: sessionStorage.getItem('vpt_auto_sign_token') ? 'present' : 'missing',
                },
                url: location.href,
                title: document.title,
                bodyPreview: document.body ? document.body.innerText.slice(0, 200) : null,
            };
        }""")
        print(f"diag: {redact(diag, AUTO_SIGN)}", file=sys.stderr)

        # Navigate to device control (the URL with ?latency_debug=1 stays for the overlay)
        print(redact(f"Device page: {DEVICE_URL}", AUTO_SIGN), file=sys.stderr)
        page.goto(DEVICE_URL, wait_until="domcontentloaded", timeout=30000)
        # Let the player mount
        page.wait_for_timeout(12000)

        # Find the video element + hls instance
        state = page.evaluate("""() => {
            const v = document.querySelector('video');
            return {
                hasVideo: !!v,
                videoReady: v ? v.readyState : null,
                videoSrc: v ? v.currentSrc : null,
                videoCurrentTime: v ? v.currentTime : null,
                overlay: !!document.querySelector('[data-testid="latency-debug-overlay"]'),
                overlayText: document.querySelector('[data-testid="latency-debug-overlay"]')?.innerText || null,
            };
        }""")
        print(f"state: {state}", file=sys.stderr)

        if not state.get('overlay'):
            page.screenshot(path='/tmp/e2e-cors.png', full_page=True)
            print("Screenshot saved to /tmp/e2e-cors.png — overlay not found, check the page", file=sys.stderr)
            browser.close()
            sys.exit(1)

        if not state.get('hasVideo'):
            print("No video element mounted; waiting longer for the player...", file=sys.stderr)
            try:
                page.wait_for_function("() => document.querySelector('video')", timeout=15000)
            except Exception:
                pass

        # 60 s measurement: read the overlay text + the underlying hls instance
        overlay_readings = []
        hls_readings = []
        stalls = 0
        start = time.monotonic()
        while time.monotonic() - start < 60:
            r = page.evaluate("""() => {
                const overlay = document.querySelector('[data-testid="latency-debug-overlay"]');
                // Use the FIRST overlay found (only the live player renders one).
                // For hls reading, find the <video> that is currently playing (not paused,
                // not the hidden audio pre-loaders).
                const allVideos = Array.from(document.querySelectorAll('video'));
                const playingVideo = allVideos.find(v => !v.paused && v.readyState >= 2 && v.currentTime > 0) || allVideos[0];
                let bestHls = null;
                if (playingVideo) {
                    let h = playingVideo._hlsInstance || playingVideo.__hls || null;
                    if (!h) {
                        const fk = Object.keys(playingVideo).find(k => k.startsWith('__reactFiber'));
                        if (fk) {
                            let fiber = playingVideo[fk];
                            while (fiber) {
                                const memo = fiber.memoizedState;
                                let hook = memo;
                                while (hook) {
                                    const cur = hook.memoizedState;
                                    if (cur?.current?.latency !== undefined && cur.current.playingDate) {
                                        h = cur.current;
                                        break;
                                    }
                                    hook = hook.next;
                                }
                                if (h) break;
                                fiber = fiber.return;
                            }
                        }
                    }
                    bestHls = h;
                }
                let wall = null, hlsLat = null, hlsTgt = null;
                if (bestHls) {
                    if (bestHls.playingDate) {
                        wall = (Date.now() - bestHls.playingDate.getTime()) / 1000;
                    }
                    hlsLat = bestHls.latency;
                    hlsTgt = bestHls.targetLatency;
                }
                return {
                    overlayText: overlay ? overlay.innerText : null,
                    wall,
                    hlsLat,
                    hlsTgt,
                    videoReady: playingVideo ? playingVideo.readyState : null,
                    videoCurrentTime: playingVideo ? playingVideo.currentTime : null,
                    videoPaused: playingVideo ? playingVideo.paused : null,
                    hasHls: !!bestHls,
                };
            }""")
            if r.get('wall') is not None:
                overlay_readings.append(r['wall'])
            if r.get('hlsLat') is not None:
                hls_readings.append(r['hlsLat'])
            elapsed = time.monotonic() - start
            if int(elapsed) % 5 == 0:
                print(f"  t={elapsed:5.1f}s  wall={r.get('wall')!r}  hls.lat={r.get('hlsLat')}  tgt={r.get('hlsTgt')}  cur={r.get('videoCurrentTime')!r}  paused={r.get('videoPaused')}  hasHls={r.get('hasHls')}", file=sys.stderr)
                if r.get('overlayText'):
                    print(f"    overlay: {r['overlayText'].replace(chr(10), ' | ')}", file=sys.stderr)
            page.wait_for_timeout(1000)

        # 3 spot readings from the overlay text
        spots = []
        for _ in range(3):
            r = page.evaluate("""() => {
                const overlay = document.querySelector('[data-testid="latency-debug-overlay"]');
                return overlay ? overlay.innerText : null;
            }""")
            spots.append(r)
            page.wait_for_timeout(300)

        result = {
            'mode': 'end-to-end (worktree frontend + CORS forwarder + rpitest, ?latency_debug=1 overlay)',
            'device': 'vpt-pi3 / device1 (FireTv) on capture1',
            'wall_latency_avg_s': round(statistics.mean(overlay_readings), 3) if overlay_readings else None,
            'wall_latency_max_s': round(max(overlay_readings), 3) if overlay_readings else None,
            'wall_latency_min_s': round(min(overlay_readings), 3) if overlay_readings else None,
            'wall_latency_count': len(overlay_readings),
            'hls_latency_avg_s': round(statistics.mean(hls_readings), 3) if hls_readings else None,
            'spot_overlay_text': spots,
            'finished_at': datetime.now(timezone.utc).isoformat(),
        }
        print()
        print(json.dumps(result, indent=2))
        browser.close()


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        # A traceback would carry the ?auto_signed= URL of the page that failed.
        print(redact(f"{type(exc).__name__}: {exc}", AUTO_SIGN), file=sys.stderr)
        sys.exit(1)
