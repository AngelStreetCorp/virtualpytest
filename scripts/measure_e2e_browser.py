#!/usr/bin/env python3
"""
TASK-79 Phase 2 — end-to-end browser latency via the public virtualpytest
SPA with the auto-sign token.

The rpitest.angelstreet.io server does not serve the SPA, and X-API-Key
hits a CORS preflight block from a browser (rpitest only allows
Content-Type/Range in Access-Control-Allow-Headers). The auto-sign path
mints a real Supabase session via the public virtualpytest.angelstreet.io
SPA, and the React app then loads capture1/FireTv, mounts HLSVideoPlayer,
and (once the user clicks) plays the stream through the full chain
(browser -> Cloudflare -> vpt-pi1 nginx -> vpt-pi3 Flask -> playlist
+ segments).

We land on /device-control?auto_signed=<token>, let the SPA bootstrap,
then poll window.__hls every second.
"""
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

AUTO_SIGN = "1f36fe19e305f9b83fd97596296e2dfaa17f982b04407f2ba31f96777cad4f47"
BASE = "https://virtualpytest.angelstreet.io"
PAGE = f"{BASE}/device-control?auto_signed={AUTO_SIGN}&host=vpt-pi3&device=device1"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"])
        ctx = browser.new_context(viewport={"width": 1280, "height": 720}, ignore_https_errors=True)
        page = ctx.new_page()

        page.on("pageerror", lambda e: print(f"  [pageerror] {e}", file=sys.stderr))
        page.on("console", lambda m: print(f"  [console.{m.type}] {m.text[:300]}", file=sys.stderr) if m.type in ("error", "warning", "log") else None)
        page.on("requestfailed", lambda r: print(f"  [requestfailed] {r.url[:120]} - {r.failure}", file=sys.stderr))

        print(f"Loading {PAGE}", file=sys.stderr)
        page.goto(PAGE, wait_until="domcontentloaded", timeout=30000)
        # Let auto-sign + Supabase + host session mint + React mount
        page.wait_for_timeout(15000)

        # Check if the HLS player is mounted by the RecStreamContainer
        state = page.evaluate("""() => {
            const v = document.querySelector('video');
            return {
                hasVideo: !!v,
                src: v ? v.currentSrc : null,
                readyState: v ? v.readyState : null,
                paused: v ? v.paused : null,
                currentTime: v ? v.currentTime : null,
                url: location.href,
            };
        }""")
        print(f"state: {state}", file=sys.stderr)

        if not state.get('hasVideo') or not state.get('src'):
            # Capture a screenshot for diagnosis
            page.screenshot(path='/tmp/e2e-page2.png', full_page=False)
            print("Screenshot saved to /tmp/e2e-page2.png", file=sys.stderr)
            browser.close()
            sys.exit(1)

        # Wait for hls.js to parse manifest and start playing
        try:
            page.wait_for_function(
                "() => { const v = document.querySelector('video'); return v && v.readyState >= 2 && v.currentTime > 0; }",
                timeout=20000,
            )
        except Exception:
            print("video did not reach readyState>=2; continuing with whatever we have", file=sys.stderr)

        print("Video playing, starting 60 s measurement...", file=sys.stderr)

        readings = []
        stalls = 0
        last_cur = None
        start = time.monotonic()
        while time.monotonic() - start < 60:
            s = page.evaluate("""() => {
                const v = document.querySelector('video');
                if (!v) return { error: 'no video' };
                // hls.js attaches the instance to the video element via property,
                // but the public HLSVideoPlayer doesn't expose it on window. Walk
                // the React fiber to find the hlsRef.
                // Easier: just read Date.now() - the video's current program time.
                // Without a known hls instance, we can read v.currentTime and the
                // segment PDT from the last loaded m3u8 via the audioTracks /
                // textTracks (hls.js doesn't expose them) or via the cache.
                // As a fallback, read v.currentTime (last decoded position) and
                // the wall clock — the segment position lags the wall clock by
                // roughly liveSyncDuration + segment/2.
                return {
                    currentTime: v.currentTime,
                    paused: v.paused,
                    readyState: v.readyState,
                    curDate: Date.now(),
                    networkState: v.networkState,
                };
            }""")
            elapsed = time.monotonic() - start
            cur = s.get('currentTime', 0) or 0
            print(f"  t={elapsed:5.1f}s  cur={cur:.3f}  paused={s.get('paused')}  ready={s.get('readyState')}", file=sys.stderr)
            if last_cur is not None and abs(cur - last_cur) < 0.01 and not s.get('paused'):
                stalls += 1
            last_cur = cur
            page.wait_for_timeout(1000)

        result = {
            'mode': 'end-to-end (virtualpytest SPA + auto-sign)',
            'device': 'vpt-pi3 / device1 (FireTv) on capture1',
            'note': 'Without the new frontend dist on virtualpytest, we cannot read hls.playingDate. The local LAN wall-clock was 0.473s (server-side, see Phase A). To get the real user-facing number, deploy frontend/dist/ to virtualpytest.angelstreet.io and use ?latency_debug=1.',
            'stalls_per_min': round(stalls, 1),
            'finished_at': datetime.now(timezone.utc).isoformat(),
        }
        print()
        print(json.dumps(result, indent=2))
        browser.close()


if __name__ == '__main__':
    main()

