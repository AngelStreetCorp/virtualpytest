/**
 * Navbar visibility — deployment-wide overrides via build-time env vars.
 *
 * All three vars take a **comma-separated list of full route paths**, matching
 * what `NavigationItem.path` and `workspace.hidden_pages` use. This gives one
 * unified convention for hiding a nav item at every level:
 *
 *   VITE_NAV_HIDDEN      → not rendered at all
 *   VITE_NAV_DISABLED    → rendered but greyed out, not clickable
 *   VITE_NAV_COMING_SOON → rendered greyed out with a "Soon" badge
 *
 * Per-workspace hides live on `workspace.hidden_pages` (runtime, no rebuild);
 * see `WorkspaceContext.isPathHidden`. A workspace hide always wins.
 *
 * Example .env:
 *   VITE_NAV_HIDDEN=/integrations/jira,/integrations/slack
 *   VITE_NAV_DISABLED=/langfuse-dashboard
 *   VITE_NAV_COMING_SOON=/configuration/cicd-reports,/configuration/code-deployment
 */

export type NavVisibility = 'visible' | 'hidden' | 'disabled' | 'coming-soon';

/** Normalize a path-ish token to a canonical `/path/like/this`. */
function normalizePath(token: string): string {
  const trimmed = token.trim();
  if (!trimmed) return '';
  return trimmed.startsWith('/') ? trimmed : '/' + trimmed;
}

function parseSet(raw: string | undefined): Set<string> {
  if (!raw) return new Set();
  return new Set(raw.split(',').map(normalizePath).filter(Boolean));
}

const HIDDEN      = parseSet(import.meta.env.VITE_NAV_HIDDEN as string | undefined);
const DISABLED    = parseSet(import.meta.env.VITE_NAV_DISABLED as string | undefined);
const COMING_SOON = parseSet(import.meta.env.VITE_NAV_COMING_SOON as string | undefined);

/**
 * Env-level visibility for a nav item keyed by its full route path.
 * Accepts `/foo/bar` or `foo/bar` on either side — both are normalized
 * to `/foo/bar` so a missing leading slash doesn't silently skip a match.
 */
export function getNavVisibility(path: string): NavVisibility {
  const p = normalizePath(path);
  if (HIDDEN.has(p))      return 'hidden';
  if (COMING_SOON.has(p)) return 'coming-soon';
  if (DISABLED.has(p))    return 'disabled';
  return 'visible';
}

/**
 * Feature toggles — controlled via VITE_FEATURE_* env vars.
 * Default is true (enabled) when the env var is missing.
 */
export function isDeploymentsEnabled(): boolean {
  const val = import.meta.env.VITE_FEATURE_DEPLOYMENTS as string | undefined;
  return val === undefined || val === '' || val === 'true';
}

export function isRunVersionSelectorEnabled(): boolean {
  const val = import.meta.env.VITE_FEATURE_RUN_VERSION_SELECTOR as string | undefined;
  return val === 'true';
}
