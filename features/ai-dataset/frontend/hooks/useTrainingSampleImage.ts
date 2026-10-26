/**
 * The screenshot of one training sample, fetched through the app's own API.
 *
 * The images live in the training bucket. The browser cannot fetch them by
 * itself: the public host in front of that bucket answers only the
 * allow-listed egress IPs, so every `<img>` got a 403 HTML page, which
 * Chromium then blocked as an opaque response — a broken-image glyph on every
 * sample and no error anywhere (BUG-0775). The server serves the screenshot
 * itself now (``GET /server/training-samples/<id>/image``), and this hook
 * reads it with the caller's credentials.
 *
 * The blobs are cached per session, so the next sample of the review queue is
 * usually on screen the moment the reviewer answers.
 */
import { useCallback, useEffect, useState } from 'react';

import { apiClient } from '../../../../frontend/src/utils/apiClient';
import { buildServerUrl } from '../../../../frontend/src/utils/buildUrlUtils';

export interface TrainingSampleImageResult {
  url: string | null;
  error: string | null;
  loading: boolean;
  /** Fetch the picture again (after a failure). */
  reload: () => void;
  /** The picture was fetched but the browser could not decode it. */
  reportBroken: (message: string) => void;
}

/** How many pictures stay in memory. A review session shows a handful. */
const CACHE_LIMIT = 12;

const cache = new Map<string, string>();
const inflight = new Map<string, Promise<{ url: string | null; error: string | null }>>();

const remember = (imagePath: string, url: string) => {
  cache.set(imagePath, url);
  while (cache.size > CACHE_LIMIT) {
    const oldest = cache.keys().next().value as string | undefined;
    if (oldest === undefined) break;
    const gone = cache.get(oldest);
    cache.delete(oldest);
    if (gone) URL.revokeObjectURL(gone);
  }
};

/**
 * Fetch one picture. `force` skips the cache (the retry after a failure).
 * Never rejects: the caller gets the reason as `error`.
 */
export const loadTrainingSampleImage = async (
  imagePath: string,
  force = false,
): Promise<{ url: string | null; error: string | null }> => {
  if (!force) {
    const cached = cache.get(imagePath);
    if (cached) return { url: cached, error: null };
    const running = inflight.get(imagePath);
    if (running) return running;
  }
  const promise = (async () => {
    try {
      const response = await apiClient(buildServerUrl(imagePath), { method: 'GET' });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error((body && body.error) || `HTTP ${response.status}`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      remember(imagePath, url);
      return { url, error: null };
    } catch (e) {
      return { url: null, error: e instanceof Error ? e.message : 'The screenshot could not be loaded' };
    } finally {
      inflight.delete(imagePath);
    }
  })();
  inflight.set(imagePath, promise);
  return promise;
};

export const useTrainingSampleImage = (
  imagePath: string | null | undefined,
): TrainingSampleImageResult => {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!imagePath) {
      setUrl(null);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void loadTrainingSampleImage(imagePath, attempt > 0).then((result) => {
      if (cancelled) return;
      setUrl(result.url);
      setError(result.error);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [imagePath, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  const reportBroken = useCallback(
    (message: string) => {
      setUrl(null);
      setError(message);
      setLoading(false);
    },
    [],
  );

  return { url, error, loading, reload, reportBroken };
};

export default useTrainingSampleImage;
