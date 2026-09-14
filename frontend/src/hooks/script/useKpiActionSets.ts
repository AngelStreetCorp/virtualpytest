/**
 * KPI Action-Set picker hook
 *
 * Backs the kpi_measurement script's edge dropdown on the RunTests modal.
 * Mirrors the module-cache + in-flight coalescing pattern used by
 * useUserInterfaceVariants so opening the modal repeatedly doesn't refire
 * the request, and N components mounting at once share a single fetch.
 *
 * IMPORTANT: a warm module-cache entry is treated as authoritative for the
 * browser session — the on-mount effect hydrates from it and does NOT fire a
 * background revalidation. The server already invalidates its own cache on
 * structural tree edits, and the RunTests modal mounts one EdgeKpiSelector per
 * selected device whose `userinterfaceName` resolves at staggered times (it is
 * derived from each device's per-host registry data). Revalidating on every
 * mount made each device fire its own request into a single-worker/1-thread
 * gevent backend; the cold full-hierarchy computation then starved later
 * devices, leaving them stuck on the `loading…` placeholder. Fetch once per
 * distinct userinterface, then serve from cache.
 *
 * Server side does the heavy lifting (cache keyed on tree hierarchy with
 * structural-edit invalidation) — this hook just reads the result.
 */

import { useCallback, useEffect, useState } from 'react';

import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

export interface KpiActionSet {
  label: string;
  /** Friendly KPI display name (action_set.kpi_name); empty string when unset. */
  kpi_name?: string;
  action_set_id: string;
  edge_id: string;
  tree_id: string;
  from_label: string;
  to_label: string;
  reason: 'kpi_references' | 'target_verifications';
}

// Cache key is "<ui>|<variant or __base__>" so distinct variants on the same
// UI don't collide. Matches the server-side cache key shape and the
// `_variant_cache_key` sentinel.
const cache = new Map<string, KpiActionSet[]>();
const inFlight = new Map<string, Promise<KpiActionSet[]>>();

const buildCacheKey = (ui: string, variant?: string | null) =>
  `${ui}|${(variant || '').trim().toLowerCase() || '__base__'}`;

export function useKpiActionSets(userinterfaceName?: string, variant?: string | null) {
  const variantNorm = (variant || '').trim() || null;
  const key = userinterfaceName ? buildCacheKey(userinterfaceName, variantNorm) : '';
  const initial = key ? cache.get(key) ?? [] : [];
  const hadCache = key ? cache.has(key) : false;

  const [actionSets, setActionSets] = useState<KpiActionSet[]>(initial);
  const [loading, setLoading] = useState(!hadCache && Boolean(key));
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!key || !userinterfaceName) {
      setActionSets([]);
      setError(null);
      return;
    }

    if (!cache.has(key)) {
      setLoading(true);
    }
    setError(null);

    let pending = inFlight.get(key);
    if (!pending) {
      pending = (async () => {
        const variantParam = variantNorm
          ? `&variant=${encodeURIComponent(variantNorm)}`
          : '';
        const url = buildServerUrl(
          `/server/navigationTrees/kpi-action-sets?userinterface_name=${encodeURIComponent(
            userinterfaceName,
          )}${variantParam}`,
        );
        const response = await apiClient(url);
        if (!response.ok) {
          throw new Error(`Failed to load KPI action sets (${response.status})`);
        }
        const json = await response.json();
        const list: KpiActionSet[] = Array.isArray(json?.action_sets) ? json.action_sets : [];
        cache.set(key, list);
        return list;
      })().finally(() => {
        inFlight.delete(key);
      });
      inFlight.set(key, pending);
    }

    try {
      const next = await pending;
      setActionSets(next);
    } catch (err) {
      console.error(
        `[@hook:useKpiActionSets] Error loading KPI action sets for '${userinterfaceName}'@${variantNorm || 'base'}:`,
        err,
      );
      setError(err instanceof Error ? err.message : String(err));
      if (!cache.has(key)) {
        setActionSets([]);
      }
    } finally {
      setLoading(false);
    }
  }, [key, userinterfaceName, variantNorm]);

  useEffect(() => {
    if (!key) {
      setActionSets([]);
      return;
    }
    // Warm cache → hydrate and stop. No background revalidation: every extra
    // request serializes on the single-threaded backend and starves the cold
    // first request (see header note). Use the returned `refresh()` for an
    // explicit re-fetch after a structural edit.
    const cached = cache.get(key);
    if (cached) {
      setActionSets(cached);
      return;
    }
    refresh();
    // Re-run when the (ui, variant) pair changes — refresh's identity is
    // already keyed on both. Same intentional omission as useUserInterfaceVariants.
  }, [key]);

  return { actionSets, loading, error, refresh };
}
