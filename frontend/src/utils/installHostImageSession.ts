import { ensureHostSession, isGatedHostPath } from './buildUrlUtils';

// An <img> pointing at /host/<name>/stream/... (capture screenshots, thumbnails) is gated by
// the same host-session cookie as HLS and VNC, but nothing mints it for a plain image: only
// the players do. Without a player on the page the proxy answers 401 and every screenshot is
// broken. A failed gated image mints the session once and reloads; the error event does not
// bubble, so it is caught in the capture phase.
//
// One retry per source, not per element: the screen modal reuses one <img> for every new
// screenshot, and the cookie expires after 10 minutes, so a per-element guard left every
// screenshot after the first expiry broken for good.
const retriedSrc = new WeakMap<HTMLImageElement, string>();

export function installHostImageSession(): void {
  document.addEventListener(
    'error',
    (event) => {
      const img = event.target;
      if (!(img instanceof HTMLImageElement)) return;
      const src = img.currentSrc || img.src;
      if (!isGatedHostPath(src)) return;
      const url = new URL(src, window.location.href);
      url.searchParams.delete('_hs');
      const baseSrc = url.toString();
      if (retriedSrc.get(img) === baseSrc) return;
      retriedSrc.set(img, baseSrc);
      void ensureHostSession(src).then((ok) => {
        if (!ok) return;
        url.searchParams.set('_hs', String(Date.now()));
        img.src = url.toString();
      });
    },
    true,
  );
}
