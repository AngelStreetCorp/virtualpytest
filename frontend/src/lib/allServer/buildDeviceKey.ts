/**
 * TASK-113 — PR-D: origin-aware device key.
 *
 * The single place to build a stable, unique key for a (server, host,
 * device) triple. The `server_url` is the FIRST component so two
 * devices with the same `host_name`/`device_id` on different
 * servers — which can happen if two VPT installs both register a
 * host called `host-poci` — get distinct keys. Without the
 * `server_url` prefix, two rows would collide on `host_name/device_id`
 * and the React renderer's reconciliation would treat them as the
 * same row.
 *
 * The `DEVICE_KEY_SEPARATOR` is the existing on-the-wire character
 * used in the codebase (`/`); a different separator would have
 * broken existing keys persisted in `localStorage` and React Query
 * caches. The new key is a strict superset of the old one.
 */
export const DEVICE_KEY_SEPARATOR = '/';

/**
 * Build the origin-aware device key.
 *
 * Old shape: `${hostName}/${deviceId}` (e.g. `host-foo/42`).
 * New shape: `${serverUrl}/${hostName}/${deviceId}` (e.g.
 * `https://a.example.test/host-foo/42`).
 *
 * The new shape is a strict superset: any old key value can be
 * losslessly converted by treating the absence of a `serverUrl`
 * prefix as "the current server". The default behaviour in
 * `useDeviceKeyFromHost` is to fall back to the current server's
 * URL when none is supplied.
 */
export const buildDeviceKey = (
  serverUrl: string,
  hostName: string,
  deviceId: string,
): string => `${serverUrl}${DEVICE_KEY_SEPARATOR}${hostName}${DEVICE_KEY_SEPARATOR}${deviceId}`;

/**
 * Parse a device key back into its parts. The serverUrl is everything
 * before the last two `DEVICE_KEY_SEPARATOR` segments; the hostName
 * and deviceId are the last two segments. Returns null for keys
 * that don't have at least 3 segments. For old 2-segment keys
 * (`hostName/deviceId`), the `serverUrl` is `''` and the caller is
 * expected to substitute the current server.
 */
export const parseDeviceKey = (key: string): { serverUrl: string; hostName: string; deviceId: string } | null => {
  const parts = key.split(DEVICE_KEY_SEPARATOR);
  if (parts.length < 3) return null;
  const hostName = parts[parts.length - 2];
  const deviceId = parts[parts.length - 1];
  // Re-join the leading parts as the serverUrl; preserves any `//` in
  // the original URL (a naive split would yield `https:` and `` as
  // separate parts, breaking https://a.example.test).
  const serverUrl = parts.slice(0, parts.length - 2).join(DEVICE_KEY_SEPARATOR);
  return { serverUrl, hostName, deviceId };
};
