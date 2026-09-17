/**
 * Server → Supabase identity registry (TASK-18).
 *
 * The platform talks to several backend servers and they do not all authenticate against
 * the same Supabase. This module is the single place that answers, for a given request
 * URL, "which Supabase session should authenticate this?".
 *
 * Why a registry and not a convention: a server's Supabase cannot be derived from its own
 * hostname. RPI1-server lives on `rpitest.angelstreet.io` but authenticates against
 * `virtualpytest.angelstreet.io/supabase` — `rpitest.angelstreet.io/supabase` is a 404.
 * Guessing would split one identity in two and prompt the user for a second, useless
 * login. So each server advertises its identity through `/server/auth/check` and we
 * remember it here.
 *
 * Deliberately framework-free: `installFetchAuth` and `apiClient` run outside React and
 * must resolve a token synchronously on the hot path of every fetch.
 */
import { Session, SupabaseClient } from '@supabase/supabase-js';

import { STORAGE_KEYS } from '../config/constants';
import { unauthenticatedFetch } from '../utils/pristineFetch';

import { getClientForIdentity, normalizeIdentity, supabase, isAuthEnabled, PRIMARY_IDENTITY } from './supabase';

export type ServerAuthMode = 'supabase' | 'open' | 'public_key' | 'closed';

export interface ServerAuthInfo {
  mode: ServerAuthMode;
  /** Browser-reachable Supabase URL; absent when the server advertises no usable identity. */
  identity?: string;
  anonKey?: string;
  serverName?: string;
}

/** What the picker needs to know about a server before switching to it. */
export type ServerAuthState =
  | 'authenticated' // we hold a live session for this server's identity
  | 'needs-auth' // reachable, but no session for its identity yet
  | 'no-auth-required' // open mode / public-key mode — nothing to sign in to
  | 'unknown'; // not probed yet

/** Same normalisation as the server list, so `https://x/` and `https://x` are one server. */
export const normalizeServerKey = (serverUrl: string): string => {
  const trimmed = (serverUrl || '').trim().replace(/\/+$/, '');
  if (!trimmed) return '';
  return trimmed.toLowerCase();
};

let registry: Record<string, ServerAuthInfo> = hydrate();

function hydrate(): Record<string, ServerAuthInfo> {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.SERVER_IDENTITIES);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    // A corrupt or unavailable cache must never stop the app from booting.
    return {};
  }
}

function persist(): void {
  try {
    localStorage.setItem(STORAGE_KEYS.SERVER_IDENTITIES, JSON.stringify(registry));
  } catch {
    // Private-window / quota. The registry still works for this tab's lifetime.
  }
}

/** Record what a server said about itself. Returns true when the identity changed. */
export const registerServerIdentity = (serverUrl: string, info: ServerAuthInfo): boolean => {
  const key = normalizeServerKey(serverUrl);
  if (!key) return false;

  const normalized: ServerAuthInfo = {
    ...info,
    identity: info.identity ? normalizeIdentity(info.identity) : undefined,
  };
  const previous = registry[key];
  const changed = previous?.identity !== normalized.identity;

  registry[key] = normalized;
  persist();
  return changed;
};

export const getServerAuthInfo = (serverUrl: string): ServerAuthInfo | undefined =>
  registry[normalizeServerKey(serverUrl)];

/** Forget everything — used on sign-out so a later user re-probes rather than inheriting. */
export const clearServerIdentities = (): void => {
  registry = {};
  try {
    localStorage.removeItem(STORAGE_KEYS.SERVER_IDENTITIES);
  } catch {
    // Nothing to do; the in-memory registry is already cleared.
  }
};

/** Origin of a request URL, tolerating the relative `/server/...` form. */
const originOf = (url: string): string => {
  try {
    return new URL(url, window.location.origin).origin.toLowerCase();
  } catch {
    return '';
  }
};

/**
 * Which registered server a request URL belongs to.
 * Matches on origin because a server URL may carry a path while the request URL
 * appends its own.
 */
export const resolveServerForRequest = (requestUrl: string): string | undefined => {
  const target = originOf(requestUrl);
  if (!target) return undefined;

  return Object.keys(registry).find((serverKey) => {
    // A registered server stored as '' means "relative URLs against this origin".
    if (!serverKey) return target === window.location.origin.toLowerCase();
    return originOf(serverKey) === target;
  });
};

/**
 * The Supabase client whose session authenticates this request.
 *
 * Falls back to the primary client whenever the target is unknown or advertises no
 * identity, which keeps pre-TASK-18 servers (and the first paint, before discovery has
 * run) behaving exactly as they did before.
 */
export const getClientForRequest = (requestUrl: string): SupabaseClient | null => {
  if (!isAuthEnabled) return null;

  const serverKey = resolveServerForRequest(requestUrl);
  const info = serverKey !== undefined ? registry[serverKey] : undefined;

  if (!info?.identity || !info.anonKey) return supabase;
  if (info.identity === PRIMARY_IDENTITY) return supabase;

  return getClientForIdentity(info.identity, info.anonKey) ?? supabase;
};

/** The client for a server URL (not a request URL) — used by the picker and sockets. */
export const getClientForServer = (serverUrl: string): SupabaseClient | null => {
  if (!isAuthEnabled) return null;

  const info = getServerAuthInfo(serverUrl);
  if (!info?.identity || !info.anonKey) return supabase;
  if (info.identity === PRIMARY_IDENTITY) return supabase;

  return getClientForIdentity(info.identity, info.anonKey) ?? supabase;
};

/** Live session for a server's identity, or null when we hold none. */
export const getSessionForServer = async (serverUrl: string): Promise<Session | null> => {
  const client = getClientForServer(serverUrl);
  if (!client) return null;
  try {
    const {
      data: { session },
    } = await client.auth.getSession();
    return session ?? null;
  } catch {
    return null;
  }
};

/** Access token for a server, or null when we hold no session for its identity. */
export const getAccessTokenForServer = async (serverUrl: string): Promise<string | null> =>
  (await getSessionForServer(serverUrl))?.access_token ?? null;

/**
 * Ask a server which Supabase it authenticates against, and remember the answer.
 *
 * Sent without a credential on purpose (see `unauthenticatedFetch`): we cannot know
 * which token is appropriate until this call answers, and guessing would send one
 * server's token to another.
 *
 * Returns the parsed info, or null when the server is unreachable or predates the
 * `auth` block — both of which leave the caller on the pre-TASK-18 fallback path.
 */
export const discoverServerIdentity = async (
  serverUrl: string,
  signal?: AbortSignal,
): Promise<ServerAuthInfo | null> => {
  const base = (serverUrl || '').trim().replace(/\/+$/, '');
  const url = `${base}/server/auth/check`;

  try {
    const response = await unauthenticatedFetch(url, { signal });
    if (!response.ok) return null;

    const body = await response.json();
    const auth = body?.auth;
    if (!auth || typeof auth !== 'object') return null;

    const info: ServerAuthInfo = {
      mode: (auth.mode as ServerAuthMode) || 'closed',
      identity: typeof auth.identity === 'string' ? auth.identity : undefined,
      anonKey: typeof auth.anon_key === 'string' ? auth.anon_key : undefined,
      serverName: typeof auth.server_name === 'string' ? auth.server_name : undefined,
    };
    registerServerIdentity(serverUrl, info);
    return info;
  } catch {
    return null;
  }
};

/**
 * Sign in to one server's Supabase identity.
 *
 * Signing in to any server that shares this identity signs you in to all of them —
 * that is the point of keying sessions by identity rather than by server.
 */
export const signInToServer = async (
  serverUrl: string,
  email: string,
  password: string,
): Promise<{ error: string | null }> => {
  const client = getClientForServer(serverUrl);
  if (!client) return { error: 'Authentication is not configured for this server.' };

  try {
    const { error } = await client.auth.signInWithPassword({ email, password });
    return { error: error?.message ?? null };
  } catch (err: any) {
    return { error: err?.message || 'Sign-in failed' };
  }
};

/** Whether a server can be used right now, for the picker's lock icon. */
export const getServerAuthState = async (serverUrl: string): Promise<ServerAuthState> => {
  const info = getServerAuthInfo(serverUrl);
  if (!info) return 'unknown';
  if (info.mode !== 'supabase') return 'no-auth-required';
  // A server in supabase mode that advertises no identity predates TASK-18: the single
  // primary session is all we have, so report it the way the app behaved before.
  if (!info.identity || !info.anonKey) return isAuthEnabled ? 'authenticated' : 'no-auth-required';

  const token = await getAccessTokenForServer(serverUrl);
  return token ? 'authenticated' : 'needs-auth';
};
