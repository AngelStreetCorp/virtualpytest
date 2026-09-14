/**
 * Lightweight page-data cache for navigation-back performance.
 *
 * Stores the last successful fetch result for each page/key.
 * On re-mount the hook reads the cache first so the page renders immediately,
 * then fetches fresh data silently in the background.
 *
 * TTL: 5 minutes (same as React Query global staleTime).
 */

const TTL_MS = 5 * 60 * 1000;

interface CacheEntry<T> {
  data: T;
  timestamp: number;
}

const store = new Map<string, CacheEntry<unknown>>();

export function getCached<T>(key: string): T | null {
  const entry = store.get(key) as CacheEntry<T> | undefined;
  if (!entry) return null;
  if (Date.now() - entry.timestamp > TTL_MS) {
    store.delete(key);
    return null;
  }
  return entry.data;
}

export function setCached<T>(key: string, data: T): void {
  store.set(key, { data, timestamp: Date.now() });
}

export function invalidateCache(...keys: string[]): void {
  keys.forEach((k) => store.delete(k));
}
