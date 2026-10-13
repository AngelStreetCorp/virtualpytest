/**
 * Server picker labels.
 *
 * Two servers can legitimately carry the same `SERVER_NAME` — a copied `.env`, or a
 * rename that only reached one box — and the picker showed both as the same row, with
 * nothing to tell them apart and no way to see which one you were on (BUG-0432).
 *
 * The rule here is deliberately narrow: a name that is unique among the configured
 * servers is shown on its own, exactly as before. Only the rows whose name collides get
 * their host appended. Adding a host to everything would make the common case (every
 * server named differently) noisier for no gain.
 */

/** `https://host:5109/` → `host:5109`; a bare URL or '' is returned unchanged. */
export const serverHostLabel = (serverUrl: string): string =>
  (serverUrl || '').replace(/^https?:\/\//, '').replace(/\/+$/, '');

/**
 * Label per configured server URL.
 *
 * `nameFor` is injected rather than imported: the authoritative name comes from live
 * state (`getAllHosts`, then the unauthenticated `/server/auth/check` probe), which this
 * module has no business knowing about. It is called once per URL per count — cheap at
 * the handful of servers a deployment configures, and it re-runs every render so a name
 * that arrives late still disambiguates immediately.
 */
export const buildServerPickerLabels = (
  serverUrls: string[],
  nameFor: (serverUrl: string) => string,
): Record<string, string> => {
  const nameCounts = new Map<string, number>();
  for (const url of serverUrls) {
    const name = nameFor(url);
    nameCounts.set(name, (nameCounts.get(name) ?? 0) + 1);
  }

  const labels: Record<string, string> = {};
  for (const url of serverUrls) {
    const name = nameFor(url);
    const host = serverHostLabel(url);
    // A collision between a named server and a server that has no name yet both fall
    // back to the host, so only append when it actually adds information.
    labels[url] = (nameCounts.get(name) ?? 0) > 1 && host && host !== name
      ? `${name} — ${host}`
      : name;
  }
  return labels;
};
