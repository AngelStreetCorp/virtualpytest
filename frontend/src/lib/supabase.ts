import { createClient, Session, SupabaseClient } from '@supabase/supabase-js';
import { getEnv } from '../config/constants';

// Get environment variables (lazy evaluation)
// Option 1: Add to frontend/.env: VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY
// Option 2: Leave empty to disable auth completely (no login required)
// The mobile app injects both at runtime too, via the same window.__VPT_CONFIG__ global
// (RuntimeConfigWebViewClient in MainActivity.kt serves /config.js from stored prefs).
const getSupabaseUrl = () => getEnv('VITE_SUPABASE_URL') || '';
const getSupabaseAnonKey = () => getEnv('VITE_SUPABASE_ANON_KEY') || '';

// Check if auth is enabled (credentials provided) - lazy evaluation
export const isAuthEnabled = !!(getSupabaseUrl() && getSupabaseAnonKey());

if (!isAuthEnabled) {
  console.error(
    '[SECURITY][OPEN_MODE] Supabase authentication is DISABLED: missing VITE_SUPABASE_URL and/or VITE_SUPABASE_ANON_KEY. ' +
      'Frontend -> Server API requests will be sent without JWT Authorization headers.'
  );
} else {
  console.info('[SECURITY] Supabase authentication enabled. Frontend -> Server API requests can use JWT.');
}

// Create Supabase client (with dummy values if auth disabled)
export const supabase = createClient(
  getSupabaseUrl() || 'https://placeholder.supabase.co',
  getSupabaseAnonKey() || 'placeholder-key',
  {
    auth: {
      autoRefreshToken: isAuthEnabled,
      persistSession: isAuthEnabled,
      detectSessionInUrl: isAuthEnabled,
    },
  }
);

/**
 * Per-identity Supabase clients (TASK-18).
 *
 * The platform talks to several backend servers, and they do NOT all authenticate
 * against the same Supabase. A session therefore belongs to a Supabase *identity*
 * (the browser-reachable Supabase URL a server advertises via /server/auth/check),
 * not to a server: two servers advertising the same identity share one session and
 * one login, a server advertising a different one gets its own.
 *
 * Each secondary identity gets an explicit `storageKey` so the sessions coexist in
 * localStorage instead of overwriting one another, and `autoRefreshToken` so a
 * cached session stays usable without asking the user again.
 */

/** Canonical form of an identity URL, so trailing-slash variants share one session. */
export const normalizeIdentity = (identityUrl: string): string =>
  (identityUrl || '').trim().replace(/\/+$/, '').toLowerCase();

/** Stable short hash (FNV-1a) — only needs to be collision-free across a handful of URLs. */
const hashIdentity = (value: string): string => {
  let hash = 0x811c9dc5;
  for (let i = 0; i < value.length; i++) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16);
};

const identityClients = new Map<string, SupabaseClient>();

/** The identity the bundle was built against — served by the primary client above. */
export const PRIMARY_IDENTITY = normalizeIdentity(getSupabaseUrl());

// Seed the cache with the primary client so the primary identity resolves to the SAME
// instance the LoginPage and AuthContext already use. It deliberately keeps supabase-js's
// default storageKey: giving it an explicit one here would move the session and sign out
// every user on deploy.
if (isAuthEnabled) {
  identityClients.set(PRIMARY_IDENTITY, supabase);
}

/**
 * Client for a Supabase identity, created once and reused.
 * Returns the primary client for the primary identity (same session, no second login).
 */
export const getClientForIdentity = (identityUrl: string, anonKey: string): SupabaseClient | null => {
  const key = normalizeIdentity(identityUrl);
  if (!key || !anonKey) return null;

  const existing = identityClients.get(key);
  if (existing) return existing;

  const client = createClient(identityUrl, anonKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      // Only the primary client may consume an OAuth callback from the URL; a secondary
      // client doing so would steal the fragment meant for the primary identity.
      detectSessionInUrl: false,
      storageKey: `sb-vpt-${hashIdentity(key)}`,
    },
  });
  identityClients.set(key, client);
  return client;
};

/**
 * How long any one caller may wait for `getSession()` before giving up on it.
 *
 * `getSession()` is normally a localStorage read and returns in microseconds — but when
 * the stored session is expired it first awaits a token refresh, and supabase-js retries
 * a refresh that fails with a *network* error (CORS block, DNS, edge 403) for its whole
 * auto-refresh tick: ~30 s of exponential backoff before it resolves. Every caller that
 * awaited it inherited that 30 s, which is how one unreachable deployment stalled the
 * requests to all the healthy ones (a fetch interceptor and apiClient both await this
 * BEFORE issuing the request, so a per-request AbortSignal never even got to run).
 *
 * Timing out here yields `null` = "no token for this identity right now". The caller
 * sends the request unauthenticated, that server answers 401 fast and is marked failed,
 * and the servers we *can* reach are unaffected. The refresh supabase-js started keeps
 * running in the background and populates its own cache if it ever succeeds.
 *
 * 5 s is comfortably above a healthy refresh round-trip (~200-500 ms) and well under the
 * 10 s request timeout the callers already apply.
 */
export const SESSION_RESOLUTION_TIMEOUT_MS = 5000;

/** `client.auth.getSession()`, but never blocking the caller longer than `timeoutMs`. */
export const getSessionWithTimeout = async (
  client: SupabaseClient,
  timeoutMs: number = SESSION_RESOLUTION_TIMEOUT_MS,
): Promise<Session | null> => {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      client.auth.getSession().then(({ data }) => data.session ?? null),
      new Promise<null>((resolve) => {
        timer = setTimeout(() => resolve(null), timeoutMs);
      }),
    ]);
  } catch {
    // A client whose session cannot be read is treated exactly like one holding none.
    return null;
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
};

/** Every identity this tab currently holds a client for (primary included). */
export const getKnownIdentities = (): string[] => Array.from(identityClients.keys());

/**
 * Sign out of every cached identity, not just the primary one.
 * One visible "sign out" must not leave live sessions behind for other servers.
 */
export const signOutAllIdentities = async (): Promise<void> => {
  await Promise.all(
    Array.from(identityClients.values()).map(async (client) => {
      try {
        await client.auth.signOut();
      } catch {
        // Never let one identity's failure strand the others still signed in.
      }
    }),
  );
};

// Database types for better type safety
export type Database = {
  public: {
    Tables: {
      profiles: {
        Row: {
          id: string;
          email: string | null;
          full_name: string | null;
          avatar_url: string | null;
          role: 'admin' | 'manager' | 'developer' | 'tester' | 'viewer';
          permissions: string[];
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id: string;
          email?: string | null;
          full_name?: string | null;
          avatar_url?: string | null;
          role?: 'admin' | 'manager' | 'developer' | 'tester' | 'viewer';
          permissions?: string[];
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          id?: string;
          email?: string | null;
          full_name?: string | null;
          avatar_url?: string | null;
          role?: 'admin' | 'manager' | 'developer' | 'tester' | 'viewer';
          permissions?: string[];
          created_at?: string;
          updated_at?: string;
        };
      };
    };
  };
};
