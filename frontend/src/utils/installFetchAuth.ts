/**
 * Global fetch auth interceptor.
 *
 * Attaches the Supabase JWT to every request aimed at a backend_server
 * `/server/*` endpoint, so the ~100 call sites that use raw `fetch()` (not just
 * the `apiClient` wrapper) authenticate once the server enforces frontend JWT
 * (ENFORCE_FRONTEND_JWT=true). Installed once from main.tsx.
 *
 * Which JWT: the one belonging to the TARGET server's Supabase identity, resolved
 * through `lib/serverIdentity` (TASK-18). Servers in the picker do not all share a
 * Supabase, so there is no single "current" token — sending the primary session to
 * every server is exactly the behaviour this replaced. A target that advertises no
 * identity (or is not yet discovered) falls back to the primary session, so nothing
 * regresses for single-Supabase deployments.
 *
 * Design constraints (why this is safe to ship before the flip):
 *  - Header-only. It never touches method, body, or non-/server/ requests, so
 *    while enforcement is OFF the extra header is simply ignored by the server.
 *  - Never clobbers an Authorization the caller already set (apiClient still
 *    sets its own; this only fills the gap for raw fetch()).
 *  - Scoped to URLs whose path contains `/server/` — Supabase's own auth calls,
 *    static assets, and third-party requests are untouched.
 *  - Fails open: any error resolving the session just sends the request as-is,
 *    exactly like today.
 *
 * Not covered here: Socket.IO / EventSource use their own transport, not fetch;
 * their auth is handled in SocketContext, tracked separately in TASK-09.
 *
 * Browser navigations: a report opened in a new tab (CI/CD report, DOM report,
 * API-testing report) is a plain GET the interceptor never sees, and a tab
 * cannot carry an Authorization header. So the same credential is mirrored into
 * a cookie scoped to Path=/server/ with SameSite=Strict; the server accepts it
 * for GET/HEAD only (auth_middleware._navigation_cookie). Refreshed on every
 * auth state change, cleared on sign-out.
 */
import { supabase, isAuthEnabled } from '../lib/supabase';
import { getAutoSignHeaderToken } from '../lib/autoSign';
import { getClientForRequest, getSessionForServer } from '../lib/serverIdentity';
import { getServerBaseUrl } from './buildUrlUtils';
import { capturePristineFetch } from './pristineFetch';
import type { Session } from '@supabase/supabase-js';
import { getEnv } from '../config/constants';

let installed = false;

const NAV_COOKIE_JWT = 'vpt_jwt';
const NAV_COOKIE_SERVER_KEY = 'vpt_server_key';
const NAV_COOKIE_PATH = '/server/';

function writeNavCookie(name: string, value: string, maxAgeSeconds: number): void {
  const secure = window.location.protocol === 'https:' ? '; Secure' : '';
  document.cookie = `${name}=${value}; Path=${NAV_COOKIE_PATH}; Max-Age=${maxAgeSeconds}; SameSite=Strict${secure}`;
}

function clearNavCookie(name: string): void {
  document.cookie = `${name}=; Path=${NAV_COOKIE_PATH}; Max-Age=0; SameSite=Strict`;
}

/** Mirror the current credential into the navigation cookies (see header comment). */
export async function syncNavigationAuthCookies(session?: Session | null): Promise<void> {
  try {
    if (isAuthEnabled) {
      // A navigation always lands on the SELECTED server, so the cookie must carry that
      // server's identity — not the primary session, which may belong to a different
      // Supabase (TASK-18). Fall back to the primary session when the selected server
      // advertises no identity of its own, which is the pre-TASK-18 behaviour.
      const selectedServerSession = await getSessionForServer(getServerBaseUrl());
      const current =
        selectedServerSession ??
        (session === undefined ? (await supabase.auth.getSession()).data.session : session);
      if (current?.access_token) {
        const nowSec = Math.floor(Date.now() / 1000);
        const ttl = current.expires_at ? Math.max(60, current.expires_at - nowSec) : 3600;
        writeNavCookie(NAV_COOKIE_JWT, current.access_token, ttl);
      } else {
        clearNavCookie(NAV_COOKIE_JWT);
      }
    }
    const serverPublicKey = getEnv('VITE_SERVER_PUBLIC_KEY') || '';
    if (serverPublicKey) {
      writeNavCookie(NAV_COOKIE_SERVER_KEY, serverPublicKey, 30 * 24 * 3600);
    }
  } catch {
    // Cookies are a convenience for new-tab navigations; never break the app over them.
  }
}

function targetsServerApi(url: string): boolean {
  // Match both absolute (https://host/server/...) and relative (/server/...) URLs.
  return url.includes('/server/');
}

export function installFetchAuth(): void {
  if (installed || typeof window === 'undefined' || !window.fetch) return;
  installed = true;

  void syncNavigationAuthCookies();
  if (isAuthEnabled) {
    supabase.auth.onAuthStateChange((_event, session) => {
      void syncNavigationAuthCookies(session);
    });
  }

  const originalFetch = window.fetch.bind(window);
  capturePristineFetch(originalFetch);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    try {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof URL
          ? input.toString()
          : input.url;

      if (url && targetsServerApi(url)) {
        // Merge onto whatever headers the caller passed (Headers | array | object).
        const headers = new Headers(init?.headers || (input instanceof Request ? input.headers : undefined));

        if (isAuthEnabled && !headers.has('Authorization')) {
          // TASK-18: the session is chosen by the request's TARGET server, not globally.
          // Servers can sit behind different Supabase instances, and sending one
          // server's token to another is what this replaces.
          const client = getClientForRequest(url);
          if (client) {
            const {
              data: { session },
            } = await client.auth.getSession();
            if (session?.access_token) {
              headers.set('Authorization', `Bearer ${session.access_token}`);
            }
          }
        }

        // No-JWT deployments (no Supabase): present the weak, published
        // SERVER_PUBLIC_KEY so the closed-by-default server still accepts the SPA.
        // Never the strong API_KEY. Skipped once an Authorization/JWT is set.
        const serverPublicKey = getEnv('VITE_SERVER_PUBLIC_KEY') || '';
        if (serverPublicKey && !headers.has('Authorization') && !headers.has('X-Server-Key')) {
          headers.set('X-Server-Key', serverPublicKey);
        }

        const autoSign = getAutoSignHeaderToken();
        if (autoSign && !headers.has('X-Auto-Sign')) {
          headers.set('X-Auto-Sign', autoSign);
        }

        return originalFetch(input as RequestInfo, { ...init, headers });
      }
    } catch {
      // Fall through to an unmodified request on any error.
    }
    return originalFetch(input as RequestInfo, init);
  };
}
