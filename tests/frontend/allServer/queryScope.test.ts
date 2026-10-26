/**
 * TASK-113 — PR-B tests: the queryScope helper, serverConnectionList,
 * and origin-aware React Query keys.
 */
import { describe, it, expect, vi } from 'vitest';
import {
  queryScope,
  targetsForScope,
} from '../../../frontend/src/lib/allServer/queryScope';
import { buildServerConnectionList } from '../../../frontend/src/lib/allServer/serverConnectionList';
import { perServerKey, allScopeKeys } from '../../../frontend/src/lib/allServer/reactQueryKeys';
import type {
  ServerConnection,
  ServerScope,
  ServerResult,
} from '../../../frontend/src/types/allServer/AllServer_Types';
import type { ServerAuthState } from '../../../frontend/src/lib/serverIdentity';
import type { ServerHostData } from '../../../frontend/src/types/common/Server_Types';

const PEER_A: ServerConnection = {
  serverId: 'https://a.example.test',
  url: 'https://a.example.test',
  name: '1',
  authState: 'authenticated',
};

const PEER_B: ServerConnection = {
  serverId: 'https://b.example.test',
  url: 'https://b.example.test',
  name: '2',
  authState: 'authenticated',
};

const PEER_C: ServerConnection = {
  serverId: 'https://c.example.test',
  url: 'https://c.example.test',
  name: '3',
  authState: 'no-auth-required',
};

const PEER_NEEDS_AUTH: ServerConnection = {
  serverId: 'https://needs.example.test',
  url: 'https://needs.example.test',
  name: '4',
  authState: 'needs-auth',
};

describe('targetsForScope', () => {
  it("'all' returns the entire eligible set", () => {
    const out = targetsForScope({ kind: 'all' }, [PEER_A, PEER_B]);
    expect(out).toEqual([PEER_A, PEER_B]);
  });

  it("'single' returns only the named server", () => {
    const out = targetsForScope({ kind: 'single', serverId: PEER_B.serverId }, [
      PEER_A,
      PEER_B,
    ]);
    expect(out).toEqual([PEER_B]);
  });

  it("'single' with an unknown serverId returns []", () => {
    const out = targetsForScope(
      { kind: 'single', serverId: 'https://unknown.example.test' },
      [PEER_A, PEER_B],
    );
    expect(out).toEqual([]);
  });
});

describe('queryScope', () => {
  it('fans out to all eligible servers in parallel and preserves order', async () => {
    const seen: string[] = [];
    const results = await queryScope<{ n: number }>(
      { kind: 'all' },
      [PEER_A, PEER_B, PEER_C],
      async (server) => {
        seen.push(server.serverId);
        return { n: parseInt(server.name, 10) };
      },
      new AbortController().signal,
    );
    expect(seen.sort()).toEqual([PEER_A, PEER_B, PEER_C].map((p) => p.serverId).sort());
    expect(results).toHaveLength(3);
    const byServer: Record<string, ServerResult<{ n: number }>> = {};
    for (const r of results) {
      if (r.status === 'ok') byServer[r.serverId] = r;
    }
    expect(byServer[PEER_A.serverId].value).toEqual({ n: 1 });
    expect(byServer[PEER_B.serverId].value).toEqual({ n: 2 });
    expect(byServer[PEER_C.serverId].value).toEqual({ n: 3 });
  });

  it("'single' returns a single result, even if eligible has more", async () => {
    const results = await queryScope<{ n: number }>(
      { kind: 'single', serverId: PEER_B.serverId },
      [PEER_A, PEER_B],
      async (server) => ({ n: parseInt(server.name, 10) }),
      new AbortController().signal,
    );
    expect(results).toHaveLength(1);
    expect(results[0].serverId).toBe(PEER_B.serverId);
    if (results[0].status === 'ok') {
      expect(results[0].value).toEqual({ n: 2 });
    } else {
      throw new Error('expected ok');
    }
  });

  it('one peer failure does not empty the page (Promise.allSettled semantics)', async () => {
    const results = await queryScope<{ ok: boolean }>(
      { kind: 'all' },
      [PEER_A, PEER_B],
      async (server) => {
        if (server.serverId === PEER_B.serverId) {
          throw Object.assign(new Error('boom'), { status: 500 });
        }
        return { ok: true };
      },
      new AbortController().signal,
    );
    expect(results).toHaveLength(2);
    const a = results.find((r) => r.serverId === PEER_A.serverId);
    const b = results.find((r) => r.serverId === PEER_B.serverId);
    expect(a?.status).toBe('ok');
    expect(b?.status).toBe('error');
  });

  it('classifies a 401 as unauthorized', async () => {
    const results = await queryScope(
      { kind: 'all' },
      [PEER_A],
      async () => {
        throw Object.assign(new Error('forbidden'), { status: 401 });
      },
      new AbortController().signal,
    );
    expect(results[0].status).toBe('unauthorized');
  });

  it('classifies a network error as offline', async () => {
    const results = await queryScope(
      { kind: 'all' },
      [PEER_A],
      async () => {
        throw new TypeError('Failed to fetch');
      },
      new AbortController().signal,
    );
    expect(results[0].status).toBe('offline');
  });

  it('classifies a per-peer timeout as offline', async () => {
    const results = await queryScope(
      { kind: 'all' },
      [PEER_A],
      async (_server, signal) => {
        // Simulate a long-running fetch that respects the per-peer abort.
        return await new Promise<{ unreachable: true }>((resolve, reject) => {
          const timer = setTimeout(() => resolve({ unreachable: true }), 5_000);
          signal.addEventListener('abort', () => {
            clearTimeout(timer);
            reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
          });
        });
      },
      new AbortController().signal,
      { timeoutMs: 50, concurrency: 1 },
    );
    expect(results[0].status).toBe('offline');
  });

  it('a parent abort propagates to all in-flight loads', async () => {
    const parent = new AbortController();
    const loadSpy = vi.fn(async (server: ServerConnection, signal: AbortSignal) => {
      await new Promise<void>((resolve, reject) => {
        const t = setTimeout(resolve, 5_000);
        signal.addEventListener('abort', () => {
          clearTimeout(t);
          reject(new DOMException('parent aborted', 'AbortError'));
        });
      });
      return { server: server.serverId };
    });
    const promise = queryScope({ kind: 'all' }, [PEER_A, PEER_B], loadSpy, parent.signal);
    // Give the workers a tick to register their abort listeners, then abort.
    await new Promise((r) => setTimeout(r, 5));
    parent.abort();
    const results = await promise;
    expect(loadSpy).toHaveBeenCalledTimes(2);
    expect(results.every((r) => r.status === 'offline')).toBe(true);
  });

  it('returns [] when no servers match the scope', async () => {
    const results = await queryScope(
      { kind: 'single', serverId: 'https://absent.example.test' },
      [PEER_A, PEER_B],
      async () => ({ unreachable: true }),
      new AbortController().signal,
    );
    expect(results).toEqual([]);
  });
});

describe('buildServerConnectionList', () => {
  const hosts: ServerHostData[] = [
    {
      server_info: {
        server_url: PEER_A.serverId,
        server_name: 'A',
        server_url_display: 'a',
        server_port: '443',
        deployed_version: 'v1',
        last_deploy_at: null,
        deploy_state: null,
        system_stats: null,
        service_health: null,
      },
      frontend_info: null,
      hosts: [],
    },
    {
      server_info: {
        server_url: PEER_NEEDS_AUTH.serverId,
        server_name: 'D',
        server_url_display: 'd',
        server_port: '443',
        deployed_version: 'v1',
        last_deploy_at: null,
        deploy_state: null,
        system_stats: null,
        service_health: null,
      },
      frontend_info: null,
      hosts: [],
    },
  ];
  const authStates: Record<string, ServerAuthState> = {
    [PEER_A.serverId]: 'authenticated',
    [PEER_NEEDS_AUTH.serverId]: 'needs-auth',
  };

  it('keeps authenticated peers', () => {
    const out = buildServerConnectionList(hosts, authStates);
    expect(out.map((s) => s.serverId)).toEqual([PEER_A.serverId]);
  });

  it('drops needs-auth peers', () => {
    const out = buildServerConnectionList(hosts, authStates);
    expect(out.find((s) => s.serverId === PEER_NEEDS_AUTH.serverId)).toBeUndefined();
  });

  it('drops peers that have not been probed yet (authState === "unknown")', () => {
    const out = buildServerConnectionList(hosts, {});
    expect(out).toEqual([]);
  });
});

describe('React Query origin-aware keys', () => {
  it('perServerKey includes the serverId (never "all" or "*")', () => {
    const key = perServerKey('projects', PEER_A, 'drafts');
    expect(key).toEqual(['projects', PEER_A.serverId, 'drafts']);
    expect(key).not.toContain('all');
    expect(key).not.toContain('*');
  });

  it('allScopeKeys is a list of perServerKey, one per eligible server', () => {
    const keys = allScopeKeys('projects', [PEER_A, PEER_B], 'drafts');
    expect(keys).toEqual([
      ['projects', PEER_A.serverId, 'drafts'],
      ['projects', PEER_B.serverId, 'drafts'],
    ]);
  });

  it('two servers with the same rest produce distinct keys (no collision)', () => {
    const k1 = perServerKey('runs', PEER_A, 'r-1');
    const k2 = perServerKey('runs', PEER_B, 'r-1');
    expect(k1).not.toEqual(k2);
  });
});
