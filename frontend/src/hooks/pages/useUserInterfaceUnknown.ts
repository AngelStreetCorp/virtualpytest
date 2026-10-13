import { useCallback, useEffect, useMemo, useState } from 'react';

import { APP_CONFIG } from '../../config/constants';
import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { formatRelativeTime } from '../../utils/dateUtils';

/**
 * Unknown screens for one interface: the screens a device shows that have no node in
 * its tree, plus the rows the content filter removed.
 *
 * Reads go through `getUnknownScreens` / `getUnknownCounts` with the params in the
 * query string (the routes accept `payload or request.args`, and `buildServerUrl`
 * already appends `team_id`). Actions POST a JSON body, which the routes also accept.
 */

const UNKNOWN_PATH = '/server/userinterface';

/**
 * `screen_type` as `vision.dom` emits it (see dom_generator.py) — wider than the
 * three the page was designed around, so unknown values fall back to 'other' rather
 * than crashing the pill.
 */
export type UnknownScreenType =
  | 'dialog'
  | 'overlay'
  | 'nav_row'
  | 'content'
  | 'app_launcher'
  | 'keyboard'
  | 'player'
  | 'other';

export type UnknownScreenStatus = 'pending' | 'accepted' | 'dismissed' | 'merged';

/** What the situation is, which decides the row's primary action. */
export type UnknownScreenAction = 'accept' | 'create_ui';

export interface UnknownScreen {
  /** Row uuid. The accept/dismiss routes key on this. */
  id: string;
  /** Name `vision.dom` proposes from `screen_summary` — editable in place. */
  proposedName: string;
  /** The `screen_summary` the name is derived from (from `dom`). */
  summary: string;
  type: UnknownScreenType;
  frames: number;
  /** Why this is unknown, in the words the reviewer needs. */
  signal: string;
  action: UnknownScreenAction;
  status: UnknownScreenStatus;
  /** A still capture exists for this cluster. */
  hasStill: boolean;
  thumbnailUrl?: string;
}

export interface ExcludedContentScreen {
  id: string;
  /** Screen name, when the filter kept one. */
  screenKey?: string;
  /** Plain description of the content is — the best text the row carries. */
  what: string;
  frames: number;
  /** A still capture exists for this cluster. */
  hasStill: boolean;
  thumbnailUrl?: string;
}

export interface UserInterfaceUnknownData {
  /** Rows still `pending` — the page's working list, matching the counts pill. */
  needsName: UnknownScreen[];
  excludedAsContent: ExcludedContentScreen[];
  /** Distinct screens removed by the content filter. */
  contentFilteredCount: number;
  /** Abstain frames the scan processed. */
  capturesProcessed: number;
  /** Pre-formatted, so the tile needs no date formatting. */
  lastScan: string;
}

/** Outcome of accept/dismiss. `needs` means "this device has no tree — do not accept". */
export interface UnknownScreenActionResult {
  ok: boolean;
  /** Server text to show verbatim: `reason`, `error` or `warning`. */
  message?: string;
  needs?: 'create_userinterface' | 'create_tree';
  nodeId?: string;
  label?: string;
  status?: string;
}

interface UseUserInterfaceUnknownResult {
  data: UserInterfaceUnknownData;
  loading: boolean;
  error: string | null;
  refetch: () => void;
  acceptScreen: (
    id: string,
    mode: 'accept' | 'create_ui' | 'merge',
    label?: string,
  ) => Promise<UnknownScreenActionResult>;
  dismissScreen: (id: string) => Promise<UnknownScreenActionResult>;
  /** Row id currently being acted on, so the row's buttons can show progress. */
  pendingAction: string | null;
}

const KNOWN_TYPES: readonly string[] = [
  'dialog',
  'overlay',
  'nav_row',
  'content',
  'app_launcher',
  'keyboard',
  'player',
  'other',
];

const KNOWN_STATUSES: readonly string[] = ['pending', 'accepted', 'dismissed', 'merged'];

const EMPTY_DATA: UserInterfaceUnknownData = {
  needsName: [],
  excludedAsContent: [],
  contentFilteredCount: 0,
  capturesProcessed: 0,
  lastScan: '—',
};

/**
 * A screen from a device that has no tree at all cannot become a node — accepting it
 * would attach it to somebody else's tree. The server says so with `reason`, but the
 * row's own `signal` is what lets us label it correctly before the first click.
 */
const CROSS_DEVICE_SIGNAL = /no tree|different device/i;

const asText = (value: unknown): string =>
  typeof value === 'string' ? value.trim() : value == null ? '' : String(value);

const asCount = (value: unknown): number => (typeof value === 'number' ? value : 0);

const normaliseType = (raw: unknown): UnknownScreenType => {
  const type = asText(raw).toLowerCase();
  return (KNOWN_TYPES as readonly string[]).includes(type) ? (type as UnknownScreenType) : 'other';
};

const mapUnknownRow = (row: any): UnknownScreen => {
  const dom = row?.dom && typeof row.dom === 'object' ? (row.dom as Record<string, unknown>) : {};
  const imageUrl = asText(row?.image_url) || undefined;
  const signal = asText(row?.signal);
  const status = asText(row?.status).toLowerCase();

  return {
    id: asText(row?.id),
    proposedName: asText(row?.proposed_name),
    summary: asText(dom.screen_summary),
    type: normaliseType(row?.screen_type),
    frames: asCount(row?.frame_count),
    signal,
    action: CROSS_DEVICE_SIGNAL.test(signal) ? 'create_ui' : 'accept',
    status: (KNOWN_STATUSES as readonly string[]).includes(status)
      ? (status as UnknownScreenStatus)
      : 'pending',
    hasStill: Boolean(imageUrl),
    thumbnailUrl: imageUrl,
  };
};

const mapContentRow = (row: any): ExcludedContentScreen => {
  const imageUrl = asText(row?.image_url) || undefined;
  const screenKey = asText(row?.proposed_name) || undefined;

  return {
    id: asText(row?.id),
    screenKey,
    // description first: it states what the footage actually was, where signal only states why
    // the row was filtered. signal is the fallback for rows written before description existed.
    what: asText(row?.description) || asText(row?.signal) || screenKey || 'Filtered as content',
    frames: asCount(row?.frame_count),
    hasStill: Boolean(imageUrl),
    thumbnailUrl: imageUrl,
  };
};

/** These routes answer with useful detail in the body, so read it before falling back. */
const readFailure = async (response: Response, fallback: string): Promise<string> => {
  const body = await response.json().catch(() => null);
  const detail = body?.reason || body?.error || body?.warning;
  return typeof detail === 'string' && detail ? detail : `${fallback} (HTTP ${response.status})`;
};

export const useUserInterfaceUnknown = (
  userInterfaceName: string | undefined,
): UseUserInterfaceUnknownResult => {
  const [data, setData] = useState<UserInterfaceUnknownData>(EMPTY_DATA);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [pendingAction, setPendingAction] = useState<string | null>(null);

  const refetch = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    if (!userInterfaceName) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const url = buildServerUrl(
          `${UNKNOWN_PATH}/getUnknownScreens?userinterface=${encodeURIComponent(userInterfaceName)}`,
        );
        const response = await apiClient(url, { method: 'POST' });
        if (!response.ok) {
          throw new Error(await readFailure(response, 'Failed to load unknown screens'));
        }
        const result = await response.json();
        if (cancelled) return;

        const unknown = Array.isArray(result?.unknown) ? result.unknown : [];
        const content = Array.isArray(result?.content) ? result.content : [];

        setData({
          // The list page's pill counts `pending` rows, so the working list is pending
          // rows: an accepted row must not linger in "needs a name".
          needsName: unknown
            .map(mapUnknownRow)
            .filter((screen: UnknownScreen) => screen.status === 'pending'),
          excludedAsContent: content.map(mapContentRow),
          contentFilteredCount: asCount(result?.counts?.content_filtered) || content.length,
          capturesProcessed: asCount(result?.frames_processed),
          lastScan: result?.last_scan ? formatRelativeTime(result.last_scan) : '—',
        });
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load unknown screens');
        setData(EMPTY_DATA);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [userInterfaceName, reloadKey]);

  const runAction = useCallback(
    async (
      id: string,
      endpoint: string,
      payload: Record<string, unknown>,
    ): Promise<UnknownScreenActionResult> => {
      setPendingAction(id);
      try {
        const response = await apiClient(buildServerUrl(`${UNKNOWN_PATH}/${endpoint}`), {
          method: 'POST',
          // These two routes read team_id / id from the body only.
          body: JSON.stringify({ team_id: APP_CONFIG.DEFAULT_TEAM_ID, id, ...payload }),
        });
        const result = await response.json().catch(() => null);

        if (!response.ok) {
          return {
            ok: false,
            needs: result?.needs,
            message: result?.reason || result?.error || result?.warning,
            nodeId: asText(result?.node_id) || undefined,
            status: result?.status,
          };
        }
        if (!result?.success) {
          return { ok: false, message: asText(result?.error) || 'The server refused the action' };
        }
        return {
          ok: true,
          nodeId: asText(result?.node_id) || undefined,
          label: asText(result?.label) || undefined,
          status: result?.status,
        };
      } catch (err) {
        return {
          ok: false,
          message: err instanceof Error ? err.message : 'The action failed to reach the server',
        };
      } finally {
        setPendingAction(null);
      }
    },
    [],
  );

  const acceptScreen = useCallback(
    (id: string, mode: 'accept' | 'create_ui' | 'merge', label?: string) =>
      runAction(id, 'acceptUnknownScreen', { mode, ...(label ? { label } : {}) }),
    [runAction],
  );

  const dismissScreen = useCallback(
    (id: string) => runAction(id, 'dismissUnknownScreen', {}),
    [runAction],
  );

  return {
    data,
    loading,
    error,
    refetch,
    acceptScreen,
    dismissScreen,
    pendingAction,
  };
};

interface UseUnknownScreenCountsResult {
  counts: Record<string, number>;
  total: number;
  /** Interface carrying the most pending rows — where the page button goes. */
  topName: string | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

/** Unknown count for one interface name (0 when the scan found nothing). */
export const unknownCountFor = (
  counts: Record<string, number>,
  name: string | undefined,
): number => (name ? counts[name] ?? 0 : 0);

/** Pending-unknown counts per interface, for the list page's "N unknown" pill. */
export const useUnknownScreenCounts = (): UseUnknownScreenCountsResult => {
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const refetch = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const url = buildServerUrl(`${UNKNOWN_PATH}/getUnknownCounts`);
        const response = await apiClient(url, {
          method: 'POST',
          body: JSON.stringify({ team_id: APP_CONFIG.DEFAULT_TEAM_ID }),
        });
        if (!response.ok) {
          throw new Error(await readFailure(response, 'Failed to load unknown counts'));
        }
        const result = await response.json();
        if (cancelled) return;

        const raw = result?.counts && typeof result.counts === 'object' ? result.counts : {};
        const normalised: Record<string, number> = {};
        Object.entries(raw).forEach(([name, value]) => {
          if (typeof value === 'number') normalised[name] = value;
        });

        setCounts(normalised);
        setTotal(typeof result?.total === 'number' ? result.total : 0);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load unknown counts');
        setCounts({});
        setTotal(0);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  // The page button answers the cross-device case: it lands on the interface carrying
  // the most unnamed screens.
  const topName = useMemo(() => {
    let top: string | null = null;
    let topCount = 0;
    Object.entries(counts).forEach(([name, count]) => {
      if (typeof count === 'number' && count > topCount) {
        top = name;
        topCount = count;
      }
    });
    return top;
  }, [counts]);

  return { counts, total, topName, loading, error, refetch };
};