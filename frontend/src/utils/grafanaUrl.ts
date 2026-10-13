/**
 * Grafana links carry the app's active workspace (TASK-31 phase D).
 *
 * Every dashboard has a visible `workspace` variable; its device limits are applied by the
 * dashboard itself from the viewer's email. Grafana cannot see the app's active workspace, so
 * links pass it as `var-workspace=<id>` and a dashboard opened from the app starts on the same
 * workspace. Without one the dashboard starts on "None".
 */
export function withGrafanaWorkspace(url: string, workspaceId: string | null | undefined): string {
  if (!workspaceId || /[?&]var-workspace=/.test(url)) return url;
  const [path, hash = ''] = url.split('#');
  const sep = path.includes('?') ? '&' : '?';
  return `${path}${sep}var-workspace=${encodeURIComponent(workspaceId)}${hash ? `#${hash}` : ''}`;
}

/**
 * Resolve a server-returned dashboard path (`/grafana/d/<uid>?...`) against the app's Grafana base
 * (VITE_GRAFANA_URL), exactly like the /grafana redirect route does: base + path without `/grafana`.
 * Servers never know the public Grafana host (the Pi server and the main server share one Grafana),
 * so they return a path. Without a configured base the same-origin `/grafana/...` path is kept
 * (that route redirects). Returns null for anything that is not a /grafana/ path.
 */
export function resolveGrafanaPath(path: string | undefined | null, base: string | undefined | null): string | null {
  if (!path || !/^\/grafana\/[^\s]*$/.test(path)) return null;
  const root = (base || '').trim().replace(/\/+$/, '');
  if (!root) return path;
  if (!/^https?:\/\/[^\s]+$/.test(root)) return null;
  return root + path.slice('/grafana'.length);
}
