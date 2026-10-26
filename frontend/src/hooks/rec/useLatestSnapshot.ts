import { useEffect, useState } from 'react';

import { useHostSession } from '../useHostSession';

const REFRESH_INTERVAL_MS = 1000;
const MAX_CONSECUTIVE_ERRORS = 3;

interface UseLatestSnapshotResult {
  /** Current src to feed to the <img>; `null` until the first frame loads. */
  src: string | null;
  /** True once `MAX_CONSECUTIVE_ERRORS` fetches in a row have failed. */
  error: boolean;
}

/**
 * Polls a `latest.jpg` once per second: each frame is fetched once and shown as a
 * blob URL (the previous one is revoked). The next tick is scheduled from the
 * previous tick's completion, not from setInterval — a slow network cannot queue
 * up multiple outstanding GETs against the same tile.
 *
 * Waits for the host-session cookie (`useHostSession`) before the first fetch so
 * the gated `/host/<name>/stream/...` path answers 200 instead of 401 (BUG-0107).
 *
 * Stops when `enabled` flips false, on unmount, or while `document.hidden` —
 * off-screen tiles and background tabs are free.
 *
 * Stops polling too after `MAX_CONSECUTIVE_ERRORS` in a row: with a
 * ffmpeg-disabled device (tv_lite dropped from .env, host restart) the path
 * answers 404 forever, and a 1 Hz retry loop on every dead tile saturates
 * the proxy with 404s (measured: 8 dropped devices on the device-control
 * page = 480 wasted requests / minute, +200 ms TTFB on every other request).
 * The host's device list refresh triggers a new `url`, which restarts the
 * loop the moment the device comes back; until then the tile renders
 * `error: true` and the proxy gets one request total per dead device.
 *
 * No HLS fallback on error: hosts that haven't shipped the new `latest.jpg`
 * output simply show "Snapshot unavailable" until they do (TASK-48 G1).
 */
export function useLatestSnapshot(
  url: string | null | undefined,
  enabled: boolean,
): UseLatestSnapshotResult {
  // Mint the host-session cookie (the gated path answers 401 without it); the
  // first fetch waits for it. Only while enabled, so live tiles mint nothing.
  const sessionReady = useHostSession(enabled ? url : null, true);

  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!url || !enabled || !sessionReady) {
      // Clean state on disable/url change so an old frame never flashes on re-enable.
      setSrc(null);
      setError(false);
      return undefined;
    }

    // Local to this effect run: a shared ref would be reset by the next run and
    // let a stale in-flight fetch from the previous url push its frame.
    let stopped = false;
    let errorCount = 0;
    let givenUp = false;
    let timeoutId: number | undefined;
    let shownUrl: string | null = null;
    const controller = new AbortController();

    const tick = async () => {
      if (stopped || givenUp) return;
      if (document.hidden) {
        // Background tab: poll the flag again next second (no request is made).
        timeoutId = window.setTimeout(tick, REFRESH_INTERVAL_MS);
        return;
      }
      // Cache-buster: images on the stream path carry max-age=14400, which would pin one frame.
      const freshUrl = `${url}${url.includes('?') ? '&' : '?'}t=${Date.now()}`;
      try {
        // One fetch per frame, shown as a blob URL: a preloading Image() plus the <img> on
        // the same URL downloaded every frame twice (measured on the deployed page).
        const res = await fetch(freshUrl, { credentials: 'include', signal: controller.signal });
        if (!res.ok) throw new Error(String(res.status));
        const blobUrl = URL.createObjectURL(await res.blob());
        if (stopped) {
          URL.revokeObjectURL(blobUrl);
          return;
        }
        if (shownUrl) URL.revokeObjectURL(shownUrl);
        shownUrl = blobUrl;
        setSrc(blobUrl);
        setError(false);
        errorCount = 0;
      } catch {
        if (stopped) return;
        errorCount += 1;
        if (errorCount >= MAX_CONSECUTIVE_ERRORS) {
          setError(true);
          // Persistent 404 means the source path is gone (ffmpeg disabled /
          // device dropped from .env) — the host won't bring it back during
          // this session, so stop hammering the proxy. A new `url` from the
          // device list refresh resets `errorCount` via this effect re-run.
          givenUp = true;
          return;
        }
      }
      // Chained from completion: one request in flight per tile, never a pile-up.
      if (!stopped && !givenUp) timeoutId = window.setTimeout(tick, REFRESH_INTERVAL_MS);
    };

    void tick();

    return () => {
      stopped = true;
      controller.abort();
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
      // Late revoke: opening the modal disables this tile and hands the last frame to it as poster.
      const last = shownUrl;
      if (last) window.setTimeout(() => URL.revokeObjectURL(last), 30000);
    };
  }, [url, enabled, sessionReady]);

  return { src, error };
}
