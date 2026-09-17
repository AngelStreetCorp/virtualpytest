/**
 * Per-server Supabase identity resolution (TASK-18).
 *
 * The thing worth testing here is the one that is invisible when it goes wrong: which
 * session authenticates a request. Before TASK-18 the frontend held a single session and
 * sent it to every server in the picker, including servers behind a different Supabase.
 * These tests pin the replacement rules — group by identity, never leak across
 * identities, and fall back (rather than fail) for servers that advertise nothing.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Hoisted with the mock factories that reference them — vi.mock is lifted above every
// plain top-level const, so these cannot be ordinary module constants.
const ids = vi.hoisted(() => ({
  PRIMARY: 'https://virtualpytest.angelstreet.io/supabase',
  OTHER: 'https://virtualpytest.qualiai.io/supabase',
}));
const PRIMARY = ids.PRIMARY;
const OTHER = ids.OTHER;

// Distinct client objects so "which client did it pick" is directly assertable.
const clients = vi.hoisted(() => ({
  primary: { id: 'primary-client' },
  made: new Map<string, { id: string }>(),
}));

vi.mock('../../frontend/src/lib/supabase', () => ({
  isAuthEnabled: true,
  supabase: clients.primary,
  PRIMARY_IDENTITY: ids.PRIMARY,
  normalizeIdentity: (url: string) => (url || '').trim().replace(/\/+$/, '').toLowerCase(),
  getClientForIdentity: (identityUrl: string) => {
    const key = identityUrl.toLowerCase();
    if (!clients.made.has(key)) clients.made.set(key, { id: `client-for-${key}` });
    return clients.made.get(key);
  },
}));

const fetchMock = vi.hoisted(() => ({ fn: vi.fn() }));
vi.mock('../../frontend/src/utils/pristineFetch', () => ({
  unauthenticatedFetch: (...args: unknown[]) => fetchMock.fn(...args),
}));

import {
  clearServerIdentities,
  discoverServerIdentity,
  getClientForRequest,
  registerServerIdentity,
  resolveServerForRequest,
} from '../../frontend/src/lib/serverIdentity';

const ANGELSTREET = 'https://virtualpytest.angelstreet.io';
const RPITEST = 'https://rpitest.angelstreet.io';
const QUALIAI = 'https://virtualpytest.qualiai.io';

describe('serverIdentity', () => {
  beforeEach(() => {
    clearServerIdentities();
    clients.made.clear();
    fetchMock.fn.mockReset();
    localStorage.clear();
  });

  it('routes a request to the client of its own target server, not the primary one', () => {
    registerServerIdentity(ANGELSTREET, { mode: 'supabase', identity: PRIMARY, anonKey: 'anon-a' });
    registerServerIdentity(QUALIAI, { mode: 'supabase', identity: OTHER, anonKey: 'anon-q' });

    expect(getClientForRequest(`${ANGELSTREET}/server/system/getAllHosts`)).toBe(clients.primary);
    expect(getClientForRequest(`${QUALIAI}/server/system/getAllHosts`)).toEqual({
      id: `client-for-${OTHER}`,
    });
  });

  it('gives two servers that share a Supabase the same session — one login, not two', () => {
    // RPI1-server lives on rpitest.angelstreet.io but authenticates against the
    // angelstreet Supabase. Splitting these would prompt for a second, useless login.
    registerServerIdentity(ANGELSTREET, { mode: 'supabase', identity: PRIMARY, anonKey: 'anon-a' });
    registerServerIdentity(RPITEST, { mode: 'supabase', identity: PRIMARY, anonKey: 'anon-a' });

    expect(getClientForRequest(`${RPITEST}/server/system/getAllHosts`)).toBe(
      getClientForRequest(`${ANGELSTREET}/server/system/getAllHosts`),
    );
  });

  it('falls back to the primary client for a server that advertises no identity', () => {
    // A server predating TASK-18 must keep behaving exactly as it did before.
    registerServerIdentity(ANGELSTREET, { mode: 'supabase' });

    expect(getClientForRequest(`${ANGELSTREET}/server/system/getAllHosts`)).toBe(clients.primary);
  });

  it('falls back to the primary client for a server that has not been discovered yet', () => {
    expect(getClientForRequest('https://unknown.example/server/health')).toBe(clients.primary);
  });

  it('matches a request to its server by origin, ignoring the path', () => {
    registerServerIdentity(QUALIAI, { mode: 'supabase', identity: OTHER, anonKey: 'anon-q' });

    expect(resolveServerForRequest(`${QUALIAI}/server/deep/nested?team_id=x`)).toBe(
      QUALIAI.toLowerCase(),
    );
    expect(resolveServerForRequest(`${ANGELSTREET}/server/health`)).toBeUndefined();
  });

  it('stores the identity a server advertises through /server/auth/check', async () => {
    fetchMock.fn.mockResolvedValue({
      ok: true,
      json: async () => ({
        authenticated: false,
        auth: { mode: 'supabase', identity: OTHER, anon_key: 'anon-q', server_name: 'QualiAI' },
      }),
    });

    const info = await discoverServerIdentity(QUALIAI);

    expect(fetchMock.fn).toHaveBeenCalledWith(`${QUALIAI}/server/auth/check`, { signal: undefined });
    expect(info).toMatchObject({ mode: 'supabase', identity: OTHER, serverName: 'QualiAI' });
    expect(getClientForRequest(`${QUALIAI}/server/x`)).toEqual({ id: `client-for-${OTHER}` });
  });

  it('treats an unreachable server as undiscovered rather than throwing', async () => {
    fetchMock.fn.mockRejectedValue(new Error('network down'));

    await expect(discoverServerIdentity(QUALIAI)).resolves.toBeNull();
    expect(getClientForRequest(`${QUALIAI}/server/x`)).toBe(clients.primary);
  });
});
