import { buildHostImageUrl } from './buildUrlUtils';

/**
 * A match run stores the frame as the host saw it: a local path, or the public host URL
 * (`https://<origin>/host/<host>/stream/captureN/capture_x.jpg`). Opened raw, that URL asks for a
 * session the browser does not have (401). Every other page shows host images through
 * `buildHostImageUrl(host, path)`, so reduce the stored value to its `stream/...` path and use it.
 * Returns the stored value untouched when it has no stream path or the host is unknown.
 */
export const matchRunFrameSrc = (host: { host_name?: string } | null | undefined, frameUrl: string | null): string => {
  if (!frameUrl) return '';
  let path = frameUrl;
  if (/^https?:\/\//.test(frameUrl)) {
    try {
      path = new URL(frameUrl).pathname;
    } catch {
      return frameUrl;
    }
  }
  const at = path.indexOf('/stream/');
  if (!host?.host_name || at < 0) return frameUrl;
  return buildHostImageUrl(host, path.slice(at + 1));
};
