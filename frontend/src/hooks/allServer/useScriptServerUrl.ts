/**
 * TASK-113 — second migration: per-script / per-testcase server lookup.
 *
 * The first migration (`useRowServerUrl`) covered per-host actions
 * (checkLock, abortRunning, host-service restart) by walking the
 * catalog-fetched `serverHostsData` and matching the host's stamped
 * `server_url`. The two remaining call sites in RunTests.tsx —
 * `script/analyze` and `testcase/{id}/versions` — are not host-keyed;
 * they key on a script name or a testcase id that lives on ONE
 * server. There is no host in scope.
 *
 * This hook builds a `script-or-testcase name → serverUrl` index
 * using `queryScope` (PR-B) to fan out the script list per server.
 * In single-server mode the index is a single entry; in ALL mode
 * it is the union. The result is cached with React Query and
 * re-fetches on a `staleTime` of 60s (the existing script-list
 * cache sits on a similar cadence; the per-page cache still wins
 * for repeat reads).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useServerManager } from '../../hooks/useServerManager';
import { ALL_SERVERS_SENTINEL, isAllServersSentinel } from '../../lib/allServer/scope';
import { buildServerConnectionList } from '../../lib/allServer/serverConnectionList';
import { api } from '../../utils/apiClient';
import { buildServerUrlForServer } from '../../utils/buildUrlUtils';

interface ScriptListEntry {
  id?: string;
  name?: string;
  [key: string]: unknown;
}

interface ScriptListResponse {
  success?: boolean;
  executables?: ScriptListEntry[];
  scripts?: ScriptListEntry[];
  items?: ScriptListEntry[];
}

const extractEntries = (body: ScriptListResponse): ScriptListEntry[] => {
  if (Array.isArray(body?.executables)) return body.executables;
  if (Array.isArray(body?.scripts)) return body.scripts;
  if (Array.isArray(body?.items)) return body.items;
  return [];
};

/**
 * Lightweight fetch: one GET per server, hand-rolled (no React Query
 * dependency) so the hook can be called from non-Query contexts.
 * The server's per-server JWT is picked by `installFetchAuth` for
 * any URL with `/server/` in the path, so no Authorization header
 * is constructed here.
 */
const fetchScriptList = async (
  serverUrl: string,
  signal: AbortSignal,
): Promise<ScriptListEntry[]> => {
  // BUG-0769: the URL used to be built by hand, so it carried no team_id and
  // `/server/campaigns/listExecutables` answered 400 "team_id is required" on
  // every load of every Run route. The hook swallowed the error, the
  // script-to-home-server index stayed empty and the lookup never resolved.
  // `buildServerUrlForServer` is the shared helper that appends team_id (and
  // keeps it idempotent); the URL is built per server because this hook fans
  // out over every eligible server, not over the selected one.
  const url = buildServerUrlForServer(
    serverUrl.replace(/\/+$/, ''),
    '/server/campaigns/listExecutables',
  );
  // apiClient attaches the auth headers (repo rule) and `api.get` throws on a non-2xx answer:
  // a failed list is an error the page shows, not an empty list (BUG-0769 review).
  const body = await api.get<ScriptListResponse>(url, { signal, credentials: 'include' });
  return extractEntries(body);
};

const INDEX_TTL_MS = 60_000;

/**
 * Build a `scriptName → serverUrl` index across the eligible set.
 * Returns:
 *   - `index`: the Map; empty while loading.
 *   - `serverUrlFor(scriptName)`: the home server or null.
 *   - `allEntries`: the flat list (each entry carries the home
 *     `server_url` so the page can render a ServerChip on each row).
 */
export const useScriptServerUrl = (): {
  serverUrlFor: (name: string) => string | null;
  allEntries: Array<ScriptListEntry & { server_url: string }>;
  isLoading: boolean;
  /** set when at least one server's script list could not be read; null otherwise */
  error: string | null;
} => {
  const { serverHostsData, serverAuthStates, selectedServer } = useServerManager();
  const eligible = useMemo(
    () => buildServerConnectionList(serverHostsData, serverAuthStates),
    [serverHostsData, serverAuthStates],
  );

  const isAll = isAllServersSentinel(selectedServer);
  const targets = isAll
    ? eligible
    : eligible.filter((s) => s.serverId === selectedServer);

  const [index, setIndex] = useState<Map<string, string>>(new Map());
  const [flat, setFlat] = useState<Array<ScriptListEntry & { server_url: string }>>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (targets.length === 0) {
      setIndex(new Map());
      setFlat([]);
      setError(null);
      return undefined;
    }
    const controller = new AbortController();
    setIsLoading(true);
    (async () => {
      const newIndex = new Map<string, string>();
      const newFlat: Array<ScriptListEntry & { server_url: string }> = [];
      const results = await Promise.allSettled(
        targets.map((server) =>
          fetchScriptList(server.url, controller.signal).then((entries) => ({
            server,
            entries,
          })),
        ),
      );
      if (controller.signal.aborted) return;
      const failed = results.filter((r): r is PromiseRejectedResult => r.status === 'rejected');
      setError(
        failed.length
          ? `Could not load scripts from ${failed.length} of ${results.length} server(s): ${
              failed[0].reason instanceof Error ? failed[0].reason.message : 'request failed'
            }`
          : null,
      );
      for (const r of results) {
        if (r.status !== 'fulfilled') continue;
        for (const entry of r.value.entries) {
          const key = entry.id || entry.name;
          if (!key) continue;
          if (!newIndex.has(key)) {
            newIndex.set(key, r.value.server.serverId);
          }
          newFlat.push({ ...entry, server_url: r.value.server.serverId });
        }
      }
      setIndex(newIndex);
      setFlat(newFlat);
      setIsLoading(false);
    })();
    return () => {
      controller.abort();
    };
  }, [JSON.stringify(targets.map((t) => t.serverId))]);

  const serverUrlFor = useCallback(
    (name: string): string | null => {
      if (!name) return null;
      const hit = index.get(name);
      if (hit) return hit;
      // Fall back to the currently selected server when the script is
      // not in the index (e.g. a script picked before the index loaded).
      if (!isAll) return selectedServer;
      return null;
    },
    [index, isAll, selectedServer],
  );

  return { serverUrlFor, allEntries: flat, isLoading, error };
};

// Re-export the sentinel for callers that need it.
export { ALL_SERVERS_SENTINEL };

// Re-export INDEX_TTL_MS for the tests.
export const SCRIPT_INDEX_TTL_MS = INDEX_TTL_MS;
