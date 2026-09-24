/**
 * Data for the Monitoring > Analytics tabs.
 *
 * Three layers of caching, each doing a different job (the server does two more —
 * see backend_server/src/lib/utils/section_cache.py):
 *
 *   1. A MODULE-LEVEL map. Switching tabs inside the SPA repaints with no network at
 *      all. This is the case that matters most, because switching tabs is what people
 *      actually do on this page.
 *   2. `prefetch()`, wired to a tab's onMouseEnter. A pointer typically rests ~200ms
 *      before the click lands, which is usually the whole round trip, so the tab looks
 *      instant. Only what someone is reaching for is fetched — never all seven.
 *   3. An in-flight map, so hovering then immediately clicking issues ONE request.
 *
 * What is deliberately NOT here: a fetch of every section on mount. That is exactly
 * the cost the tabbed design exists to avoid.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  ApiSection,
  ProjectMetrics,
  SectionEnvelope,
} from '../../types/pages/Analytics_Types';
import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

/** How long a cached section is reused before a visit refetches it. */
const CLIENT_TTL_MS = 30_000;

interface CacheEntry {
  data: unknown;
  fetchedAt: number;
  cacheState?: string;
}

const cache = new Map<string, CacheEntry>();
const inFlight = new Map<string, Promise<unknown>>();

let projectCache: { data: ProjectMetrics | null; fetchedAt: number } | null = null;

const keyFor = (section: string) => section;

const isFresh = (entry: CacheEntry | undefined): entry is CacheEntry =>
  !!entry && Date.now() - entry.fetchedAt < CLIENT_TTL_MS;

async function fetchSection<T>(section: ApiSection): Promise<T> {
  const key = keyFor(section);

  const existing = inFlight.get(key);
  if (existing) return existing as Promise<T>;

  const promise = (async () => {
    console.log(`[@hook:useAnalytics] fetching section '${section}'`);
    const envelope = (await api.get(
      buildServerUrl(`/server/analytics/${section}`),
    )) as SectionEnvelope<T>;

    if (!envelope?.success) {
      throw new Error(`Analytics section '${section}' returned an unsuccessful response`);
    }
    cache.set(key, {
      data: envelope.data,
      fetchedAt: Date.now(),
      cacheState: envelope.cache,
    });
    console.log(`[@hook:useAnalytics] '${section}' served ${envelope.cache} by the server`);
    return envelope.data;
  })().finally(() => {
    inFlight.delete(key);
  });

  inFlight.set(key, promise);
  return promise as Promise<T>;
}

/**
 * Warm a section without rendering it. Safe to call repeatedly — a fresh entry or an
 * in-flight request short-circuits, so hover-then-click issues one request.
 */
export function prefetchSection(section: ApiSection): void {
  if (isFresh(cache.get(keyFor(section))) || inFlight.has(keyFor(section))) return;
  fetchSection(section).catch(() => {
    /* a failed prefetch is not an error the user should ever see — the real
       fetch on click will surface it */
  });
}

export interface UseAnalyticsSection<T> {
  data: T | null;
  /** True only while there is nothing to show yet. */
  loading: boolean;
  /** True while refreshing content already on screen. */
  refreshing: boolean;
  error: string | null;
  /** Where the server said the value came from: fresh | stale | cold. */
  cacheState?: string;
  reload: () => void;
}

/** Fetch one section, reusing the module cache. */
export function useAnalyticsSection<T>(
  section: ApiSection,
  enabled = true,
): UseAnalyticsSection<T> {
  const cached = cache.get(keyFor(section));
  const [data, setData] = useState<T | null>((cached?.data as T) ?? null);
  const [loading, setLoading] = useState(enabled && !cached);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(
    async (force: boolean) => {
      const entry = cache.get(keyFor(section));
      if (!force && isFresh(entry)) {
        setData(entry.data as T);
        setLoading(false);
        return;
      }
      // Content already on screen refreshes quietly; only an empty card spins.
      if (entry) setRefreshing(true);
      else setLoading(true);
      setError(null);

      try {
        const result = await fetchSection<T>(section);
        if (!mounted.current) return;
        setData(result);
      } catch (e) {
        if (!mounted.current) return;
        const message = e instanceof Error ? e.message : String(e);
        console.error(`[@hook:useAnalytics] '${section}' failed:`, message);
        // Keep whatever is on screen — stale numbers beat an empty card.
        setError(message);
      } finally {
        if (mounted.current) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [section],
  );

  useEffect(() => {
    if (!enabled) return;
    void load(false);
  }, [enabled, load]);

  return {
    data,
    loading,
    refreshing,
    error,
    cacheState: cache.get(keyFor(section))?.cacheState,
    reload: () => void load(true),
  };
}

/**
 * The Project tab's build-time numbers.
 *
 * A static file next to the bundle, so no auth and no database. A missing file is a
 * normal state, not an error: it is gitignored and only exists once prebuild step 6
 * has run, so a checkout that has never been built legitimately has no metrics.
 *
 * "Missing" is NOT a 404. The app is served with SPA fallback, so an absent file comes
 * back as index.html with HTTP 200, and parsing it threw `Unexpected token '<'` across
 * all five cards. The content type is what actually distinguishes the two.
 */
export function useProjectMetrics(enabled = true): {
  data: ProjectMetrics | null;
  loading: boolean;
  missing: boolean;
  error: string | null;
} {
  const [data, setData] = useState<ProjectMetrics | null>(projectCache?.data ?? null);
  const [loading, setLoading] = useState(enabled && !projectCache);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || projectCache) {
      if (projectCache) {
        setData(projectCache.data);
        setMissing(projectCache.data === null);
        setLoading(false);
      }
      return;
    }
    let cancelled = false;

    (async () => {
      try {
        const response = await fetch('/analytics/project.json', { cache: 'no-cache' });
        const isJson = (response.headers.get('content-type') || '').includes('json');
        if (response.status === 404 || !isJson) {
          // Either a real 404, or the SPA fallback handing back index.html.
          projectCache = { data: null, fetchedAt: Date.now() };
          if (!cancelled) {
            setMissing(true);
            setLoading(false);
          }
          return;
        }
        if (!response.ok) throw new Error(`project.json: ${response.status}`);
        const parsed = (await response.json()) as ProjectMetrics;
        projectCache = { data: parsed, fetchedAt: Date.now() };
        if (!cancelled) {
          setData(parsed);
          setLoading(false);
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return { data, loading, missing, error };
}

/** Drop every cached section. Used by the page's manual refresh. */
export function invalidateAnalytics(): void {
  cache.clear();
  projectCache = null;
}
