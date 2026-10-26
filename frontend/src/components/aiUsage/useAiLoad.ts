/**
 * Loads one panel's data and keeps failures plain: the cause goes to the browser console (and the server log
 * holds the rest), the panel only learns "failed" and shows <PanelError>. Reloads when `deps` change.
 */
import { DependencyList, useCallback, useEffect, useRef, useState } from 'react';

export interface AiLoad<T> {
  data: T | null;
  loading: boolean;
  failed: boolean;
  /** The last failure, for a caller that tells kinds apart (a server without the API). */
  error: unknown;
  reload: () => void;
}

export function useAiLoad<T>(name: string, fetcher: () => Promise<T>, deps: DependencyList, enabled = true): AiLoad<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [failed, setFailed] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [tick, setTick] = useState(0);
  const run = useRef(0);

  useEffect(() => {
    if (!enabled) return;
    const id = ++run.current;
    setLoading(true);
    fetcher()
      .then((d) => {
        if (id !== run.current) return;
        // The API answers { success: false, error } for a failed read: that is a failure, not data.
        if ((d as { success?: boolean } | null)?.success === false) throw new Error((d as { error?: string }).error || 'request failed');
        setData(d);
        setFailed(false);
        setError(null);
      })
      .catch((e) => {
        if (id !== run.current) return;
        console.error(`[@component:aiUsage] ${name} failed`, e);
        setFailed(true);
        setError(e);
      })
      .finally(() => id === run.current && setLoading(false));
  }, [...deps, tick, enabled]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { data, loading, failed, error, reload };
}
