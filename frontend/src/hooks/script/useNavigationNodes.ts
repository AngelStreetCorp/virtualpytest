/**
 * Navigation Node picker hook
 *
 * Backs the goto script's `--node` dropdown on the RunTests modal. Mirrors
 * `useKpiActionSets` 1:1 — module-cache + in-flight coalescing, hydrate-from-
 * cache on mount (no background revalidation), same single-fetch-per-UI
 * rationale (one selector per selected device hits a single-worker/1-thread
 * gevent backend; revalidating on every mount starves cold callers).
 *
 * Server side does the hierarchy walk + dedupe; this hook just reads it.
 */

import { useCallback, useEffect, useState } from 'react';

import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

export interface NavigationNode {
  label: string;
  node_id: string;
  tree_id: string;
  node_type: string;
  /** Optional friendly name (Node Edit dialog → data.display_name). Empty when unset. */
  display_name?: string;
}

// Cache key is "<ui>|<variant or __base__>" — same shape as useKpiActionSets.
const cache = new Map<string, NavigationNode[]>();
const inFlight = new Map<string, Promise<NavigationNode[]>>();

const buildCacheKey = (ui: string, variant?: string | null) =>
  `${ui}|${(variant || '').trim().toLowerCase() || '__base__'}`;

export function useNavigationNodes(userinterfaceName?: string, variant?: string | null) {
  const variantNorm = (variant || '').trim() || null;
  const key = userinterfaceName ? buildCacheKey(userinterfaceName, variantNorm) : '';
  const initial = key ? cache.get(key) ?? [] : [];
  const hadCache = key ? cache.has(key) : false;

  const [nodes, setNodes] = useState<NavigationNode[]>(initial);
  const [loading, setLoading] = useState(!hadCache && Boolean(key));
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!key || !userinterfaceName) {
      setNodes([]);
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
          `/server/navigationTrees/nodes?userinterface_name=${encodeURIComponent(
            userinterfaceName,
          )}${variantParam}`,
        );
        const response = await apiClient(url);
        if (!response.ok) {
          throw new Error(`Failed to load navigation nodes (${response.status})`);
        }
        const json = await response.json();
        const list: NavigationNode[] = Array.isArray(json?.nodes) ? json.nodes : [];
        cache.set(key, list);
        return list;
      })().finally(() => {
        inFlight.delete(key);
      });
      inFlight.set(key, pending);
    }

    try {
      const next = await pending;
      setNodes(next);
    } catch (err) {
      console.error(
        `[@hook:useNavigationNodes] Error loading navigation nodes for '${userinterfaceName}'@${variantNorm || 'base'}:`,
        err,
      );
      setError(err instanceof Error ? err.message : String(err));
      if (!cache.has(key)) {
        setNodes([]);
      }
    } finally {
      setLoading(false);
    }
  }, [key, userinterfaceName, variantNorm]);

  useEffect(() => {
    if (!key) {
      setNodes([]);
      return;
    }
    // Warm cache → hydrate and stop. See useKpiActionSets for the rationale.
    const cached = cache.get(key);
    if (cached) {
      setNodes(cached);
      return;
    }
    refresh();
    // Re-run when the (ui, variant) pair changes.
  }, [key]);

  return { nodes, loading, error, refresh };
}
