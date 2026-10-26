/**
 * TASK-113 — PR-C: the scope derivation.
 *
 * The picker still uses a single `selectedServer: string` (TASK-18
 * contract; persisted in localStorage). PR-C introduces the
 * `ALL_SERVERS_SENTINEL` as a special value the picker can switch to;
 * `deriveScope` turns the string into the discriminated `ServerScope`.
 * The picker renders an "All servers" row at the top whose value is
 * the sentinel; every other row's value is the server's URL.
 *
 * The `ServerManagerContext` is NOT changed in PR-C. The `selectedServer`
 * field stays a string; the `ServerScope` is derived on read. This
 * keeps PR-C purely additive and avoids breaking the existing single-
 * server consumers that read `selectedServer` directly.
 */
import type { ServerScope } from '../../types/allServer/AllServer_Types';

/**
 * The magic value the picker assigns when the user picks the
 * "All servers" row. Picked to be a string that is never a valid
 * server URL (no protocol prefix, contains a space, includes the
 * literal "__all__") so it cannot collide with `getAllServerUrls()`.
 */
export const ALL_SERVERS_SENTINEL = '__all__';

export const isAllServersSentinel = (value: string): boolean =>
  value === ALL_SERVERS_SENTINEL;

/**
 * Derive the discriminated `ServerScope` from the picker's
 * `selectedServer` string. When the value is the sentinel,
 * returns `{ kind: 'all' }`. When it is a normal URL, returns
 * `{ kind: 'single', serverId: value }`. An empty string
 * (no server configured) yields `{ kind: 'single', serverId: '' }`
 * — the consumer can treat that as "no scope".
 */
export const deriveScope = (selectedServer: string): ServerScope => {
  if (isAllServersSentinel(selectedServer)) return { kind: 'all' };
  return { kind: 'single', serverId: selectedServer };
};
