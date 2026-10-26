/**
 * TASK-113 — PR-B: origin-aware React Query cache keys.
 *
 * The current React Query keys mix the active scope's `serverKey`
 * (`useRunManagement.ts:47`) into the cache. For ALL mode the
 * sentinel is `'*'`, but a `'*'` entry MUST NOT subsume per-server
 * entries — a single-server fetch and an ALL fetch with the same
 * resource id must produce two separate cache entries, otherwise an
 * earlier single-server fetch would leak its data into the ALL view.
 *
 * Rule: every key for a list/summary of resources is
 * `['<domain>', serverId, ...rest]`. ALL mode constructs the same
 * key for every eligible server and unions the results. `ALL` is
 * NEVER a substitute for the underlying server identity in a key.
 */
import type { ServerConnection } from '../../types/allServer/AllServer_Types';

export type ReactQueryDomain =
  | 'hosts'
  | 'projects'
  | 'scripts'
  | 'users'
  | 'workspaces'
  | 'runs'
  | 'campaigns'
  | 'executables'
  | 'settings'
  | 'logs'
  | 'status'
  | 'teams'
  | 'tenants';

/** Build a per-server React Query key. */
export const perServerKey = (
  domain: ReactQueryDomain,
  server: ServerConnection,
  ...rest: ReadonlyArray<string | number | boolean | undefined>
): ReadonlyArray<unknown> => [domain, server.serverId, ...rest];

/**
 * Build the key set for an ALL-mode fan-out. The caller unions the
 * `data` slices; React Query itself stores each per-server entry
 * under its own key. The `'all'` marker is for debugging only —
 * never use it as a substitute for `serverId`.
 */
export const allScopeKeys = (
  domain: ReactQueryDomain,
  eligibleServers: ServerConnection[],
  ...rest: ReadonlyArray<string | number | boolean | undefined>
): ReadonlyArray<ReadonlyArray<unknown>> =>
  eligibleServers.map((s) => perServerKey(domain, s, ...rest));
