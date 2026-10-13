import { api } from './apiClient';

/**
 * A one-entry, TTL'd, request-deduplicating cache for a GET endpoint.
 *
 * Why it exists: `executionListCache` held two of these written out longhand — the
 * executable list and the campaign executable list, the same thirty lines twice with
 * `campaign` spliced into every identifier — and `testcaseCache` was a third copy with
 * log lines added. One factory, three call sites.
 *
 * "One entry" is deliberate and matches what those three did: the cache holds a single
 * value plus the URL it came from, and a request for a different URL replaces it rather
 * than accumulating. These back page-level lists where the URL is effectively constant
 * for a session, so a Map would add eviction questions and buy nothing.
 *
 * `peek` is the reason this is not simply `react-query`: a page that flips a loading
 * flag before awaiting shows its loading state for a frame on every mount, even on a
 * cache hit. `peek` lets it seed synchronously and skip the flag — the difference
 * between a list that is just there and one that visibly rebuilds each time you return
 * to the page.
 */
export interface RequestCache<T> {
  /** Cached value if fresh, the in-flight request if one is running, else a new one. */
  get(apiUrl: string): Promise<T>;
  /** What is cached right now, without fetching. Null when there is nothing fresh. */
  peek(apiUrl: string): T | null;
  /** Drop the value and any in-flight request — call after a create/update/delete. */
  invalidate(): void;
}

export function createRequestCache<T = any>(name: string, ttlMs: number): RequestCache<T> {
  let value: T | null = null;
  let valueUrl: string | null = null;
  let loadedAt = 0;
  let inflight: Promise<T> | null = null;

  const fresh = (apiUrl: string) =>
    value !== null && valueUrl === apiUrl && Date.now() - loadedAt < ttlMs;

  return {
    get(apiUrl) {
      if (fresh(apiUrl)) return Promise.resolve(value as T);

      // Returns the in-flight request whatever URL it was started for. That is what all
      // three of the originals did; preserved rather than "fixed" because these are
      // called with a constant URL per page, so a mismatch cannot arise today, and
      // changing it would be a behaviour change smuggled into a deduplication commit.
      if (inflight) return inflight;

      console.log(`[@requestCache:${name}] miss — fetching`);
      inflight = api
        .get(apiUrl)
        .then((data: T) => {
          value = data;
          valueUrl = apiUrl;
          loadedAt = Date.now();
          return data;
        })
        .finally(() => {
          inflight = null;
        });

      return inflight;
    },

    peek(apiUrl) {
      return fresh(apiUrl) ? (value as T) : null;
    },

    invalidate() {
      console.log(`[@requestCache:${name}] invalidated`);
      value = null;
      valueUrl = null;
      loadedAt = 0;
      inflight = null;
    },
  };
}
