/**
 * The GitLab link has to be a path on our own domain, not the instance's address.
 *
 * The instance lives at an address only the VirtualPyTest server can reach (a lab IP, or the
 * customer's LAN). Handing that to a browser produces a link that times out for anyone not sitting
 * on that network. The proxy VM already serves the instance under `/gitlab` — the same shape as the
 * Grafana block — so the browser stays on the app's domain and works from anywhere.
 *
 * Both the instance's configured `base_url` and GitLab's own `web_url` for a project are absolute
 * internal addresses, so both have to be rewritten. Rewriting is a prefix strip, not a guess:
 * `http://gitlab.internal/gitlab/root/overlay` becomes `/gitlab/root/overlay`.
 *
 * The counterpart on the other side of this is that gitlab-dev itself must be configured with the
 * same sub-path (`external_url '.../gitlab'` + `nginx['relative_url_root'] = '/gitlab'`). Without
 * it GitLab emits root-absolute URLs — `/assets/…`, `/users/sign_in` — which resolve against
 * VirtualPyTest's own frontend and render an unstyled, half-broken page.
 */

/** Where the proxy VM serves the instance. Mirrors the Grafana location in nginx. */
export const GITLAB_PUBLIC_PATH = '/gitlab';

/**
 * Map an instance URL onto the public `/gitlab` path.
 *
 * @param baseUrl  the configured instance base, e.g. `http://192.0.2.10/gitlab`
 * @param targetUrl optional deeper address (GitLab's `web_url` for a project) to preserve
 * @returns the same-origin `/gitlab…` path, or `''` when no instance is configured
 */
export function toPublicGitLabUrl(
  baseUrl: string | undefined | null,
  targetUrl?: string | undefined | null,
): string {
  const base = (baseUrl || '').trim().replace(/\/+$/, '');
  if (!base) return '';
  if (!/^https?:\/\/[^\s]+$/.test(base)) return GITLAB_PUBLIC_PATH;

  const target = (targetUrl || '').trim();
  // Only rewrite a target that really is on that instance; anything else (a web_url from a
  // different base, a stale cached value) falls back to the instance root rather than inventing
  // a path by string surgery.
  if (!target || !target.startsWith(base)) return GITLAB_PUBLIC_PATH;

  const rest = target.slice(base.length);
  return GITLAB_PUBLIC_PATH + (rest.startsWith('/') ? rest : rest ? `/${rest}` : '');
}