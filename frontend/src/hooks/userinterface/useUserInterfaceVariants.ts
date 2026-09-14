/**
 * User Interface Variants Hook
 *
 * Full CRUD access to the registered variants for a userinterface.
 * Drives:
 *   - the Variant dropdown on RunTests / RunScript
 *   - the per-row + ▾ menus inside Edit Node / Edit Edge dialogs
 *   - the Variants manager section on the userinterface detail page (§3.1)
 *
 * See docs/agent/ENHANCE_VARIANT.md §6.1 / §6.2 for the REST contract.
 */

import { useCallback, useEffect, useState } from 'react';

import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import type { VariantOverridesMap } from '../../types/pages/Navigation_Types';

export interface UserInterfaceVariant {
  name: string;
  description: string;
  /** Per-variant overrides keyed by node_id. */
  node_overrides: VariantOverridesMap;
  /** Per-variant overrides keyed by edge_id. */
  edge_overrides: VariantOverridesMap;
  created_at?: string;
  updated_at?: string;
}

export interface VariantHiddenRows {
  nodes: number;
  edges: number;
}

export interface VariantRowsChanged {
  nodes: number;
  edges: number;
}

export interface CreateVariantResult {
  variant: UserInterfaceVariant;
  /** Set when source_variant was null — counts of `hidden_in_base` rows the
   *  new variant gained `disabled: true` entries for. */
  hidden_rows?: VariantHiddenRows;
  /** Set when source_variant was a string — counts of override entries that
   *  were deep-copied from the source variant onto the new variant. */
  cloned_rows?: VariantHiddenRows;
}

export interface UpdateVariantOverridesPayload {
  node_overrides?: VariantOverridesMap;
  edge_overrides?: VariantOverridesMap;
}

export interface UseUserInterfaceVariantsResult {
  variants: UserInterfaceVariant[];
  loading: boolean;
  error: string | null;
  /** Re-fetch the variant list. */
  refresh: () => Promise<void>;
  /** Alias kept for callers that prefer the React-Query-style name. */
  refetch: () => Promise<void>;
  /**
   * Create a new variant. Throws Error(message) on server-side failure.
   *
   * `sourceVariant`:
   *   - undefined / null → Base-derived. Additive model: the new variant starts
   *     EMPTY — `hidden_in_base` rows stay off by default, no cross-disable
   *     fan-out (so it composes cleanly). Result `hidden_rows` is {0,0}.
   *     See docs/agent/navigation/VARIANT.md "Composition".
   *   - string           → must reference an existing registered variant.
   *     Backend deep-copies the source's `node_overrides` / `edge_overrides`
   *     onto the new variant. Result includes `cloned_rows`.
   */
  addVariant: (
    name: string,
    description: string,
    sourceVariant?: string | null,
  ) => Promise<CreateVariantResult>;
  /** Update an existing variant's description. */
  updateVariant: (name: string, description: string) => Promise<void>;
  /**
   * Replace a variant's `node_overrides` / `edge_overrides` JSONB maps. Both
   * are optional; pass only the field you want to overwrite. The backend does
   * NOT merge keys server-side — pass the post-merge map.
   *
   * Pass `{skipRefresh: true}` when issuing many updates back-to-back to defer
   * cache invalidation; call `refresh()` once when the batch completes.
   */
  updateVariantOverrides: (
    name: string,
    payload: UpdateVariantOverridesPayload,
    opts?: { skipRefresh?: boolean },
  ) => Promise<UserInterfaceVariant>;
  /** Delete a variant. Per-row cascade is automatic (data lives on the row). */
  deleteVariant: (name: string) => Promise<VariantRowsChanged>;
  /** Rename a variant; single-row UPDATE on userinterface_variants. */
  renameVariant: (oldName: string, newName: string) => Promise<VariantRowsChanged>;
}

interface ServerErrorBody {
  error?: string;
  message?: string;
}

const extractErrorMessage = async (response: Response, fallback: string): Promise<string> => {
  try {
    const body: ServerErrorBody = await response.json();
    return body?.error || body?.message || fallback;
  } catch {
    return fallback;
  }
};

// Module-level cache so repeated mounts of this hook (e.g. opening the Manage
// Variants modal multiple times) hydrate instantly from the previous fetch.
// Mutations invalidate by overwriting after refresh.
const variantsCache = new Map<string, UserInterfaceVariant[]>();

// Coalesces concurrent fetches keyed by userinterface_id. Multiple components
// (NavigationEditor + Navigation_ViewingScopeChip + edit dialogs + …) each mount
// this hook independently on the navigation editor page; without this they would
// each fire their own /variants request on mount.
const variantsInFlight = new Map<string, Promise<UserInterfaceVariant[]>>();

// Cross-instance broadcast: each hook instance has its own React state, so a
// mutation from one consumer (e.g. an edit dialog calling
// `updateVariantOverrides`) wouldn't reach NavigationEditor's instance —
// `useResolvedTree` would keep applying the pre-mutation override map and the
// canvas would render stale variant-resolved content. Subscribers are notified
// whenever the cache is overwritten (by `refresh()`).
type VariantsSubscriber = (next: UserInterfaceVariant[]) => void;
const variantsSubscribers = new Map<string, Set<VariantsSubscriber>>();

const notifyVariantsSubscribers = (
  uid: string,
  next: UserInterfaceVariant[],
): void => {
  const subs = variantsSubscribers.get(uid);
  if (!subs || subs.size === 0) return;
  for (const sub of subs) {
    try {
      sub(next);
    } catch (err) {
      console.error('[@hook:useUserInterfaceVariants] subscriber failed', err);
    }
  }
};

const toVariant = (v: any): UserInterfaceVariant => ({
  name: v.name,
  description: v.description ?? '',
  node_overrides: (v.node_overrides ?? {}) as VariantOverridesMap,
  edge_overrides: (v.edge_overrides ?? {}) as VariantOverridesMap,
  created_at: v.created_at,
  updated_at: v.updated_at,
});

// Set while a team-wide prime is loading. The per-id effect awaits it instead
// of firing its own request, which is the whole point: without it every row
// would race ahead and issue the per-interface GET before the batch lands.
let variantsBatchInFlight: Promise<void> | null = null;

/**
 * Fetch every interface's variants in ONE request and prime the module cache.
 *
 * The Interface page renders a variants cell per row, so each row's hook fired
 * its own GET — 16 interfaces meant 16 requests, which serialize on the
 * single-worker gevent backend and dominated that page's load time. Call this
 * once with the ids being rendered; the per-row hooks then hydrate from cache
 * and issue nothing.
 *
 * `interfaceIds` is required because the response only carries interfaces that
 * HAVE variants — the rest are primed empty here, otherwise every
 * variant-less row would still fall through to its own fetch.
 *
 * Never throws: on failure the cache is left untouched and per-id hooks fall
 * back to their own fetch.
 */
export async function primeAllVariants(interfaceIds: string[]): Promise<void> {
  if (variantsBatchInFlight) return variantsBatchInFlight;

  variantsBatchInFlight = (async () => {
    try {
      // buildServerUrl appends team_id itself.
      const url = buildServerUrl('/server/userinterface/variants');
      const response = await apiClient(url);
      if (!response.ok) {
        throw new Error(`Failed to load variants (${response.status})`);
      }
      const payload = await response.json();
      const byInterface: Record<string, any[]> = payload?.variants_by_interface ?? {};

      const primed = new Set<string>();
      for (const [uid, raw] of Object.entries(byInterface)) {
        const next = (Array.isArray(raw) ? raw : []).map(toVariant);
        variantsCache.set(uid, next);
        notifyVariantsSubscribers(uid, next);
        primed.add(uid);
      }
      for (const uid of interfaceIds) {
        if (primed.has(uid) || variantsCache.has(uid)) continue;
        variantsCache.set(uid, []);
        notifyVariantsSubscribers(uid, []);
      }
    } catch (err) {
      console.error('[@hook:useUserInterfaceVariants] batch prime failed', err);
    } finally {
      variantsBatchInFlight = null;
    }
  })();

  return variantsBatchInFlight;
}

/**
 * Fetches the list of registered variants for a given userinterface_id.
 * Returns an empty list when:
 *   - userInterfaceId is undefined / empty (caller hasn't picked a UI yet)
 *   - the userinterface has no variants registered
 *
 * Caches results in module-level memory so subsequent mounts (e.g. reopening
 * the Manage Variants modal) hydrate instantly. Mutations refresh and update
 * the cache. A warm cache entry is authoritative for the browser session: the
 * on-mount effect hydrates from it and does NOT background-revalidate. RunTests
 * mounts one VariantSelector per selected device whose userinterface resolves
 * at staggered times; revalidating on every mount made each device fire its own
 * /variants request into the single-worker/1-thread gevent backend. Mutations
 * still call refresh() explicitly, so edited data propagates.
 *
 * GET errors are surfaced via the `error` field. Mutations throw on failure
 * so dialogs can catch and display the server's error message inline.
 */
export function useUserInterfaceVariants(
  userInterfaceId?: string | null,
): UseUserInterfaceVariantsResult {
  const initialVariants = userInterfaceId ? variantsCache.get(userInterfaceId) ?? [] : [];
  const hadCache = userInterfaceId ? variantsCache.has(userInterfaceId) : false;

  const [variants, setVariants] = useState<UserInterfaceVariant[]>(initialVariants);
  // Don't show a spinner if we already have cached data — render the cached
  // list immediately and revalidate in the background.
  const [loading, setLoading] = useState(!hadCache && Boolean(userInterfaceId));
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!userInterfaceId) {
      setVariants([]);
      setError(null);
      return;
    }

    // Show spinner only when the cache is empty for this UI.
    if (!variantsCache.has(userInterfaceId)) {
      setLoading(true);
    }
    setError(null);

    let pending = variantsInFlight.get(userInterfaceId);
    if (!pending) {
      pending = (async () => {
        const url = buildServerUrl(`/server/userinterface/${userInterfaceId}/variants`);
        const response = await apiClient(url);
        if (!response.ok) {
          throw new Error(`Failed to load variants (${response.status})`);
        }
        const payload = await response.json();
        const raw: any[] = Array.isArray(payload?.variants) ? payload.variants : [];
        const next: UserInterfaceVariant[] = raw.map(toVariant);
        variantsCache.set(userInterfaceId, next);
        // Fan out to every other hook instance subscribed to this uid so
        // (e.g.) the dialog's PUT+refresh updates NavigationEditor's
        // `registeredVariants` and the canvas re-resolves.
        notifyVariantsSubscribers(userInterfaceId, next);
        return next;
      })().finally(() => {
        variantsInFlight.delete(userInterfaceId);
      });
      variantsInFlight.set(userInterfaceId, pending);
    }

    try {
      const next = await pending;
      setVariants(next);
    } catch (err) {
      console.error(
        `[@hook:useUserInterfaceVariants] Error loading variants for ${userInterfaceId}:`,
        err,
      );
      setError(err instanceof Error ? err.message : String(err));
      // Don't blow away the cache on transient errors — keep showing what we have.
      if (!variantsCache.has(userInterfaceId)) {
        setVariants([]);
      }
    } finally {
      setLoading(false);
    }
  }, [userInterfaceId]);

  useEffect(() => {
    if (!userInterfaceId) {
      setVariants([]);
      return;
    }
    // Warm cache → hydrate and stop. No background revalidation: staggered
    // per-device mounts would otherwise each fire a /variants request and
    // serialize on the single-threaded backend. Mutations call refresh()
    // explicitly, so edited data still propagates.
    let cancelled = false;
    const cached = variantsCache.get(userInterfaceId);
    if (cached) {
      setVariants(cached);
    } else if (variantsBatchInFlight) {
      // A team-wide prime is loading every interface's variants. Wait for it
      // rather than firing a per-row request — that fan-out is exactly what
      // primeAllVariants removes. Fall back only if the batch missed this id.
      setLoading(true);
      variantsBatchInFlight
        .then(() => {
          if (cancelled) return;
          const primed = variantsCache.get(userInterfaceId);
          if (primed) {
            setVariants(primed);
            setLoading(false);
          } else {
            refresh();
          }
        })
        .catch(() => {
          if (!cancelled) refresh();
        });
    } else {
      refresh();
    }
    // Subscribe to cross-instance broadcasts so this hook re-renders when
    // ANY consumer's mutation lands (the dialog's PUT/DELETE → refresh()
    // wouldn't reach NavigationEditor's instance otherwise).
    let subs = variantsSubscribers.get(userInterfaceId);
    if (!subs) {
      subs = new Set<VariantsSubscriber>();
      variantsSubscribers.set(userInterfaceId, subs);
    }
    subs.add(setVariants);
    return () => {
      cancelled = true;
      subs!.delete(setVariants);
      if (subs!.size === 0) {
        variantsSubscribers.delete(userInterfaceId);
      }
    };
    // Only re-run when the userinterface changes. `refresh` is a useCallback whose
    // identity is also keyed on userInterfaceId, but listing it here causes the
    // effect to fire twice in StrictMode and any time React decides to re-create
    // the callback. Intentionally omitted.
  }, [userInterfaceId]);

  const addVariant = useCallback(
    async (
      name: string,
      description: string,
      sourceVariant?: string | null,
    ): Promise<CreateVariantResult> => {
      if (!userInterfaceId) {
        throw new Error('No userinterface selected');
      }
      const url = buildServerUrl(`/server/userinterface/${userInterfaceId}/variants`);
      const body: { name: string; description: string; source_variant?: string | null } = {
        name,
        description,
      };
      if (sourceVariant) {
        body.source_variant = sourceVariant;
      } else {
        body.source_variant = null;
      }
      const response = await apiClient(url, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const message = await extractErrorMessage(
          response,
          `Failed to create variant (${response.status})`,
        );
        throw new Error(message);
      }
      const payload = await response.json();
      await refresh();
      const v = payload.variant || {};
      return {
        variant: {
          name: v.name,
          description: v.description ?? '',
          node_overrides: (v.node_overrides ?? {}) as VariantOverridesMap,
          edge_overrides: (v.edge_overrides ?? {}) as VariantOverridesMap,
          created_at: v.created_at,
          updated_at: v.updated_at,
        },
        hidden_rows: payload.hidden_rows as VariantHiddenRows | undefined,
        cloned_rows: payload.cloned_rows as VariantHiddenRows | undefined,
      };
    },
    [userInterfaceId, refresh],
  );

  const updateVariant = useCallback(
    async (name: string, description: string): Promise<void> => {
      if (!userInterfaceId) {
        throw new Error('No userinterface selected');
      }
      const url = buildServerUrl(
        `/server/userinterface/${userInterfaceId}/variants/${encodeURIComponent(name)}`,
      );
      const response = await apiClient(url, {
        method: 'PUT',
        body: JSON.stringify({ description }),
      });
      if (!response.ok) {
        const message = await extractErrorMessage(
          response,
          `Failed to update variant (${response.status})`,
        );
        throw new Error(message);
      }
      await refresh();
    },
    [userInterfaceId, refresh],
  );

  const updateVariantOverrides = useCallback(
    async (
      name: string,
      payload: UpdateVariantOverridesPayload,
      opts?: { skipRefresh?: boolean },
    ): Promise<UserInterfaceVariant> => {
      if (!userInterfaceId) {
        throw new Error('No userinterface selected');
      }
      const url = buildServerUrl(
        `/server/userinterface/${userInterfaceId}/variants/${encodeURIComponent(name)}`,
      );
      const body: Record<string, unknown> = {};
      if (payload.node_overrides !== undefined) body.node_overrides = payload.node_overrides;
      if (payload.edge_overrides !== undefined) body.edge_overrides = payload.edge_overrides;
      const response = await apiClient(url, {
        method: 'PUT',
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const message = await extractErrorMessage(
          response,
          `Failed to update variant overrides (${response.status})`,
        );
        throw new Error(message);
      }
      const json = await response.json();
      // Caller can defer the refresh when batching N updates back-to-back; a
      // single `refresh()` at the end covers the same cache invalidation.
      if (!opts?.skipRefresh) {
        await refresh();
      }
      const v = json.variant || {};
      return {
        name: v.name,
        description: v.description ?? '',
        node_overrides: (v.node_overrides ?? {}) as VariantOverridesMap,
        edge_overrides: (v.edge_overrides ?? {}) as VariantOverridesMap,
        created_at: v.created_at,
        updated_at: v.updated_at,
      };
    },
    [userInterfaceId, refresh],
  );

  const deleteVariant = useCallback(
    async (name: string): Promise<VariantRowsChanged> => {
      if (!userInterfaceId) {
        throw new Error('No userinterface selected');
      }
      const url = buildServerUrl(
        `/server/userinterface/${userInterfaceId}/variants/${encodeURIComponent(name)}`,
      );
      const response = await apiClient(url, { method: 'DELETE' });
      if (!response.ok) {
        const message = await extractErrorMessage(
          response,
          `Failed to delete variant (${response.status})`,
        );
        throw new Error(message);
      }
      const payload = await response.json();
      await refresh();
      const rows = (payload?.rows_changed ?? { nodes: 0, edges: 0 }) as VariantRowsChanged;
      return rows;
    },
    [userInterfaceId, refresh],
  );

  const renameVariant = useCallback(
    async (oldName: string, newName: string): Promise<VariantRowsChanged> => {
      if (!userInterfaceId) {
        throw new Error('No userinterface selected');
      }
      const url = buildServerUrl(
        `/server/userinterface/${userInterfaceId}/variants/${encodeURIComponent(oldName)}/rename`,
      );
      const response = await apiClient(url, {
        method: 'POST',
        body: JSON.stringify({ new_name: newName }),
      });
      if (!response.ok) {
        const message = await extractErrorMessage(
          response,
          `Failed to rename variant (${response.status})`,
        );
        throw new Error(message);
      }
      const payload = await response.json();
      await refresh();
      const rows = (payload?.rows_changed ?? { nodes: 0, edges: 0 }) as VariantRowsChanged;
      return rows;
    },
    [userInterfaceId, refresh],
  );

  return {
    variants,
    loading,
    error,
    refresh,
    refetch: refresh,
    addVariant,
    updateVariant,
    updateVariantOverrides,
    deleteVariant,
    renameVariant,
  };
}
