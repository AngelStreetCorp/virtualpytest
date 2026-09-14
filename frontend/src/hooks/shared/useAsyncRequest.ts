/**
 * Shared hook for async request state (loading, error) without changing behavior.
 * Use where straightforward - wraps async execution with loading/error tracking.
 */

import { useState, useCallback } from 'react';

export interface UseAsyncRequestReturn<T> {
  loading: boolean;
  error: string | null;
  execute: <R = T>(fn: () => Promise<R>) => Promise<R>;
  clearError: () => void;
}

/**
 * Provides loading/error state for async operations.
 * Execute runs the given async function and tracks loading/error.
 */
export function useAsyncRequest<T = unknown>(): UseAsyncRequestReturn<T> {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const execute = useCallback(async <R = T>(fn: () => Promise<R>): Promise<R> => {
    setLoading(true);
    setError(null);
    try {
      const result = await fn();
      return result;
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Unknown error';
      setError(msg);
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return { loading, error, execute, clearError };
}
