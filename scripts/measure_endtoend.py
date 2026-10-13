#!/usr/bin/env python3
"""
TASK-79 Phase 2 — end-to-end browser latency measurement.

Uses Python Playwright to:
  1. Open the rpitest public URL with the auto-signed Supabase session (this
     mints a host session cookie via the React app on page load).
  2. Navigate to a device page (capture1/FireTv) and wait for the HLS player
     to start playing.
  3. For 60 s, evaluate JavaScript in the page every 1 s to read the latest
     segment's wall-clock PDT (Date.now() - playingDate.getTime()), the hls.js
     latency, and stall state.
  4. Record 3 spot readings plus avg/max/min over 60 s.

This is the end-to-end number: the user's browser does the full chain
(browser -> Cloudflare -> vpt-pi1 nginx -> vpt-pi3 Flask -> playlist + segments),
and the wall-clock it sees is what they would feel.
"""
import json
import os
import statistics
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _server_url import server_public_url


def main():
    AUTO_SIGN = "1f36fe19e305f9b83fd97596296e2dfaa17f982b04407f2ba31f96777cad4f47"
    # The host_session authorize gate is bypassed for browser flows via the
    # auto-signed Supabase session. We do NOT pass X-API-Key — we want a real
    # browser session so the auth_request returns 200 the same way it does
    # for the user's actual page load.
    BASE = server_public_url()
    # The device-control page is the one that mounts HLSVideoPlayer for capture1.
    # We do not know the exact host/device id; the React app discovers it from
    # the server registry. We land on the home page first to learn the URL.
    PAGE = f"{BASE}/?auto_signed={AUTO_SIGN}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"])
        ctx = browser.new_context(viewport={"width": 1280, "height": 800}, ignore_https_errors=True)
        page = ctx.new_page()

        # Forward console for debugging
        page.on("console", lambda msg: print(f"  [console.{msg.type}] {msg.text}", file=sys.stderr) if msg.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: print(f"  [pageerror] {e}", file=sys.stderr))

        print(f"Loading {PAGE} ...", file=sys.stderr)
        page.goto(PAGE, wait_until="domcontentloaded", timeout=20000)
        # Let the auto-sign + Supabase + host-session bootstrap settle
        page.wait_for_timeout(3000)
        print("Page loaded. Discovering capture1 device URL...", file=sys.stderr)

        # Query the device list to find capture1's URL
        # The server exposes /server/system/getAllHosts. We can hit it from the
        # browser context so cookies/host session are sent.
        hosts_info = page.evaluate("""async () => {
            const r = await fetch('/server/system/getAllHosts', { credentials: 'include', headers: { 'X-Auto-Sign': '1f36fe19e305f9b83fd97596296e2dfaa17f982b04407f2ba31f96777cad4f47' } });
            if (!r.ok) return { error: 'getAllHosts ' + r.status };
            const j = await r.json();
            return j;
        }""")
        print(f"hosts_info keys: {list(hosts_info.keys()) if isinstance(hosts_info, dict) else type(hosts_info)}", file=sys.stderr)

        # Find a host named vpt-pi3 with a capture1 device
        target = page.evaluate("""async () => {
            const r = await fetch('/server/system/getAllHosts', { credentials: 'include', headers: { 'X-Auto-Sign': '1f36fe19e305f9b83fd97596296e2dfaa17f982b04407f2ba31f96777cad4f47' } });
            const j = await r.json();
            for (const h of (j.hosts || [])) {
                if (h.host_name !== 'vpt-pi3') continue;
                for (const d of (h.devices || [])) {
                    if (d.device_id === 'capture1' || d.video_capture_path?.includes('capture1')) {
                        return { host_name: h.host_name, device_id: d.device_id, device_name: d.device_name, video_stream_path: d.video_stream_path };
                    }
                }
            }
            return { error: 'capture1 not found', hosts: j.hosts?.map(h => ({ name: h.host_name, devices: h.devices?.map(d => d.device_id) })) };
        }""")
        print(f"target: {target}", file=sys.stderr)

        if 'error' in target:
            print(f"Cannot find capture1: {target['error']}")
            browser.close()
            sys.exit(1)

        # Navigate to the device control page
        device_url = f"{BASE}/device-control?auto_signed={AUTO_SIGN}&host={target['host_name']}&device={target['device_id']}"
        print(f"Loading {device_url} ...", file=sys.stderr)
        page.goto(device_url, wait_until="domcontentloaded", timeout=20000)
        # Wait for the HLS player to start
        page.wait_for_timeout(15000)
        # Verify the video element is playing
        playing = page.evaluate("""() => {
            const v = document.querySelector('video');
            if (!v) return { error: 'no video element', hasPlayer: !!document.querySelector('[class*="player"], [class*="Player"]') };
            return { readyState: v.readyState, currentTime: v.currentTime, paused: v.paused, src: v.currentSrc };
        }""")
        print(f"video state: {playing}", file=sys.stderr)

        if 'error' in playing:
            # Take a screenshot to see what the page looks like
            page.screenshot(path='/tmp/e2e-page.png', full_page=True)
            print("Screenshot saved to /tmp/e2e-page.png", file=sys.stderr)
            # Also print the DOM
            html = page.content()[:3000]
            print(f"HTML head: {html}", file=sys.stderr)
            browser.close()
            sys.exit(1)

        # Main measurement loop
        readings = []
        stalled_count = 0
        last_curtime = None
        start = time.monotonic()
        while time.monotonic() - start < 60:
            sample = page.evaluate("""() => {
                const v = document.querySelector('video');
                if (!v) return { error: 'no video' };
                // hls.js instances are stored on the video element by hls.js
                const hls = v._hlsInstance || (window.hls && window.hls) || null;
                let wall = null, hlsLat = null, hlsTgt = null;
                if (hls && hls.playingDate) {
                    wall = (Date.now() - hls.playingDate.getTime()) / 1000;
                }
                if (hls) {
                    hlsLat = hls.latency ?? null;
                    hlsTgt = hls.targetLatency ?? null;
                }
                return {
                    currentTime: v.currentTime,
                    paused: v.paused,
                    readyState: v.readyState,
                    wall,
                    hlsLat,
                    hlsTgt,
                    stalled: v.readyState < 3 && !v.paused,
                };
            }""")
            if 'error' in sample:
                print(f"  err: {sample['error']}", file=sys.stderr)
                page.wait_for_timeout(1000)
                continue
            if sample.get('wall') is not None:
                readings.append(sample['wall'])
            if sample.get('stalled'):
                stalled_count += 1
            if last_curtime is not None and abs(sample['currentTime'] - last_curtime) < 0.05 and not sample['paused']:
                stalled_count += 1
            last_curtime = sample['currentTime']
            elapsed = time.monotonic() - start
            if int(elapsed) % 5 == 0 and len(readings) % 5 == 0:
                print(f"  t={elapsed:5.1f}s  wall={sample.get('wall'):.3f}  hls.lat={sample.get('hlsLat')}  tgt={sample.get('hlsTgt')}  cur={sample['currentTime']:.2f}  ready={sample['readyState']}  stalled={sample['stalled']}", file=sys.stderr)
            page.wait_for_timeout(1000)

        # 3 spot readings
        spot = []
        for _ in range(3):
            s = page.evaluate("""() => {
                const v = document.querySelector('video');
                const hls = v && v._hlsInstance;
                return (hls && hls.playingDate) ? (Date.now() - hls.playingDate.getTime()) / 1000 : null;
            }""")
            spot.append(s)
            page.wait_for_timeout(300)

        result = {
            'device': f"{target['host_name']}/{target['device_id']} ({target.get('device_name')})",
            'wall_latency_avg_s': round(statistics.mean(readings), 3) if readings else None,
            'wall_latency_max_s': round(max(readings), 3) if readings else None,
            'wall_latency_min_s': round(min(readings), 3) if readings else None,
            'wall_latency_count': len(readings),
            'stalls_per_min': round(stalled_count, 1),
            'spot_readings_s': [round(x, 3) if x is not None else None for x in spot],
            'finished_at': datetime.now(timezone.utc).isoformat(),
        }
        print()
        print(json.dumps(result, indent=2))
        browser.close()


if __name__ == '__main__':
    main()
