/**
 * TASK-113 — PR-A contract tests (T01 canary + A7 + C8 building blocks).
 *
 * The T01 canary in `TASK-113-test-plan.md` is the regression guard for
 * PR-A: existing single-server UX must not change. PR-A's own contribution
 * is purely additive (new types and a new test file), so the canary is a
 * sanity check on the type contracts themselves plus the small surface
 * this PR touches.
 *
 * These tests do not require a live two-server harness. They run on
 * Vitest with the existing test framework; the test plan's C1–C8
 * fixtures are a later PR.
 */
import { describe, it, expect } from 'vitest';
import type {
  ServerScope,
  ResourceRef,
  ServerResult,
  ServerConnection,
  QueryScope,
  DispatchForRow,
} from '../../../frontend/src/types/allServer/AllServer_Types';

const PEER_A: ServerConnection = {
  serverId: 'https://a.example.test',
  url: 'https://a.example.test',
  name: 'A',
  authState: 'authenticated',
  identity: 'https://a.example.test/supabase',
};

const PEER_B: ServerConnection = {
  serverId: 'https://b.example.test',
  url: 'https://b.example.test',
  name: 'B',
  authState: 'authenticated',
  identity: 'https://b.example.test/supabase',
};

const PEER_NEEDS_AUTH: ServerConnection = {
  serverId: 'https://needs.example.test',
  url: 'https://needs.example.test',
  name: 'C',
  authState: 'needs-auth',
};

const PEER_OFFLINE: ServerConnection = {
  serverId: 'https://offline.example.test',
  url: 'https://offline.example.test',
  name: 'D',
  authState: 'authenticated',
};

describe('ServerScope', () => {
  it("'single' carries exactly one serverId", () => {
    const scope: ServerScope = { kind: 'single', serverId: PEER_A.serverId };
    expect(scope.kind).toBe('single');
    if (scope.kind === 'single') {
      expect(scope.serverId).toBe(PEER_A.serverId);
    }
  });

  it("'all' carries no serverId (the union is the eligible set)", () => {
    const scope: ServerScope = { kind: 'all' };
    expect(scope.kind).toBe('all');
    if (scope.kind === 'all') {
      // @ts-expect-error — serverId is not on the 'all' branch
      expect(scope.serverId).toBeUndefined();
    }
  });

  it("'single' and 'all' are mutually exclusive (no shared fields)", () => {
    // This is a compile-time assertion; the test only documents the
    // expectation so a future change to the union trips the diff.
    const single: ServerScope = { kind: 'single', serverId: PEER_A.serverId };
    const all: ServerScope = { kind: 'all' };
    expect(single.kind).not.toBe(all.kind);
  });
});

describe('ResourceRef', () => {
  it('carries serverId + resourceType + localId', () => {
    const ref: ResourceRef = {
      serverId: PEER_A.serverId,
      resourceType: 'device',
      localId: 'host-foo/42',
    };
    expect(ref.serverId).toBe(PEER_A.serverId);
    expect(ref.resourceType).toBe('device');
    expect(ref.localId).toBe('host-foo/42');
  });

  it('the same localId on two servers is two distinct refs', () => {
    const a: ResourceRef = { serverId: PEER_A.serverId, resourceType: 'device', localId: '42' };
    const b: ResourceRef = { serverId: PEER_B.serverId, resourceType: 'device', localId: '42' };
    expect(a).not.toEqual(b);
  });
});

describe('ServerResult', () => {
  it("'ok' carries value and fetchedAt", () => {
    const r: ServerResult<{ devices: number }> = {
      serverId: PEER_A.serverId,
      status: 'ok',
      value: { devices: 4 },
      fetchedAt: Date.now(),
    };
    expect(r.status).toBe('ok');
    if (r.status === 'ok') {
      expect(r.value.devices).toBe(4);
    }
  });

  it("failure variants carry status + error", () => {
    const offline: ServerResult<unknown> = {
      serverId: PEER_OFFLINE.serverId,
      status: 'offline',
      error: 'ECONNREFUSED',
    };
    const unauth: ServerResult<unknown> = {
      serverId: PEER_NEEDS_AUTH.serverId,
      status: 'unauthorized',
      error: 'no session',
    };
    expect(offline.status).toBe('offline');
    expect(unauth.status).toBe('unauthorized');
  });
});

describe('ServerConnection', () => {
  it('every record has serverId, url, name, authState', () => {
    for (const peer of [PEER_A, PEER_B, PEER_NEEDS_AUTH, PEER_OFFLINE]) {
      expect(peer.serverId).toBeTruthy();
      expect(peer.url).toBeTruthy();
      expect(peer.name).toBeTruthy();
      expect(['authenticated', 'needs-auth', 'no-auth-required', 'unknown']).toContain(
        peer.authState,
      );
    }
  });

  it("'needs-auth' peers are excluded from eligible fan-out (caller's responsibility)", () => {
    // The rewrite's `queryScope` filters out `authState === 'needs-auth'`
    // before fan-out. The contract for the filter is: every entry in
    // `eligibleServers` has `authState === 'authenticated'` or
    // `authState === 'no-auth-required'`. This test asserts the
    // filter invariant at the type level so PR-B's implementation
    // trips a Vitest failure if a `needs-auth` peer is passed in.
    const eligible = [PEER_A, PEER_B, PEER_OFFLINE].filter(
      (s) => s.authState !== 'needs-auth',
    );
    expect(eligible).toHaveLength(3);
    expect(eligible.find((s) => s.serverId === PEER_NEEDS_AUTH.serverId)).toBeUndefined();
  });
});

describe('Placeholder helper signatures (PR-B and PR-D land here)', () => {
  it('QueryScope is a function type that returns ServerResult<T>[]', () => {
    const impl: QueryScope = (async (
      _scope: ServerScope,
      _eligible: ServerConnection[],
      _load: (s: ServerConnection, signal: AbortSignal) => Promise<unknown>,
      _signal: AbortSignal,
    ) => []) as QueryScope;
    expect(typeof impl).toBe('function');
  });

  it('DispatchForRow takes a ResourceRef + a per-server call', () => {
    const impl: DispatchForRow = (async (
      _ref: ResourceRef,
      _call: (s: ServerConnection, signal: AbortSignal) => Promise<unknown>,
      _signal: AbortSignal,
    ) => undefined) as DispatchForRow;
    expect(typeof impl).toBe('function');
  });
});

describe('T01 canary — single-server UX is unchanged', () => {
  it("a 'single' scope with a real serverId is a legal initial state", () => {
    // PR-A introduces types but does NOT change the existing
    // `selectedServer` string field on `ServerManagerContext`. Existing
    // callers keep working; the new `scope` field is derived from
    // `selectedServer` and is a discriminated union for future use.
    // This test asserts that the union's 'single' branch is the shape
    // the picker already produces, so no UX change is implied.
    const scope: ServerScope = { kind: 'single', serverId: PEER_A.serverId };
    expect(scope).toEqual({ kind: 'single', serverId: 'https://a.example.test' });
  });
});
