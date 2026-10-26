/**
 * TASK-113 — PR-D tests: dispatchForRow, urlForRef, buildDeviceKey.
 */
import { describe, it, expect } from 'vitest';
import {
  dispatchForRow,
  urlForRef,
} from '../../../frontend/src/lib/allServer/dispatchForRow';
import {
  buildDeviceKey,
  parseDeviceKey,
} from '../../../frontend/src/lib/allServer/buildDeviceKey';
import type {
  ResourceRef,
  ServerConnection,
} from '../../../frontend/src/types/allServer/AllServer_Types';

const PEER_A: ServerConnection = {
  serverId: 'https://a.example.test',
  url: 'https://a.example.test',
  name: 'A',
  authState: 'authenticated',
};
const PEER_B: ServerConnection = {
  serverId: 'https://b.example.test',
  url: 'https://b.example.test',
  name: 'B',
  authState: 'authenticated',
};
const ELIGIBLE = [PEER_A, PEER_B];

const REF_A: ResourceRef = {
  serverId: PEER_A.serverId,
  resourceType: 'device',
  localId: 'host-foo/42',
};

describe('dispatchForRow', () => {
  it('refuses to dispatch when the row server is not in the eligible set', async () => {
    const absent: ResourceRef = {
      serverId: 'https://absent.example.test',
      resourceType: 'device',
      localId: 'x',
    };
    await expect(
      dispatchForRow(absent, ELIGIBLE, async () => 'never'),
    ).rejects.toMatchObject({ code: 'ineligible-server' });
  });

  it('forwards the resolved ServerConnection to the call', async () => {
    const seen: ServerConnection[] = [];
    await dispatchForRow(REF_A, ELIGIBLE, async (server) => {
      seen.push(server);
      return 'ok';
    });
    expect(seen).toEqual([PEER_A]);
  });

  it('cancels the call when the per-call timeout elapses', async () => {
    await expect(
      dispatchForRow(
        REF_A,
        ELIGIBLE,
        async (_server, signal) => {
          await new Promise<never>((_resolve, reject) => {
            const t = setTimeout(() => reject(new Error('timeout')), 5_000);
            signal.addEventListener('abort', () => {
              clearTimeout(t);
              reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
            });
          });
        },
        { timeoutMs: 30 },
      ),
    ).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('passes a parent abort signal through to the call', async () => {
    const parent = new AbortController();
    const promise = dispatchForRow(
      REF_A,
      ELIGIBLE,
      async (_server, signal) =>
        await new Promise<never>((_resolve, reject) => {
          const t = setTimeout(() => reject(new Error('timeout')), 5_000);
          signal.addEventListener('abort', () => {
            clearTimeout(t);
            reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
          });
        }),
      { signal: parent.signal, timeoutMs: 5_000 },
    );
    await new Promise((r) => setTimeout(r, 5));
    parent.abort();
    await expect(promise).rejects.toMatchObject({ name: 'AbortError' });
  });
});

describe('urlForRef', () => {
  it("builds a URL on the ref's home server", () => {
    const url = urlForRef(REF_A, '/server/devices/42');
    expect(url).toContain(PEER_A.serverId);
    expect(url).toContain('/server/devices/42');
  });

  it('adds team_id (mirroring buildServerUrl behaviour)', () => {
    const url = urlForRef(REF_A, '/server/devices/42');
    expect(url).toMatch(/team_id=/);
  });
});

describe('buildDeviceKey', () => {
  it('includes the serverUrl as the first component', () => {
    expect(buildDeviceKey('https://a.example.test', 'host-foo', '42')).toBe(
      'https://a.example.test/host-foo/42',
    );
  });

  it('two peers with the same host/device produce distinct keys', () => {
    const k1 = buildDeviceKey('https://a.example.test', 'host-poci', '42');
    const k2 = buildDeviceKey('https://b.example.test', 'host-poci', '42');
    expect(k1).not.toBe(k2);
  });

  it('parses back into its parts', () => {
    const k = buildDeviceKey('https://a.example.test', 'host-foo', '42');
    expect(parseDeviceKey(k)).toEqual({
      serverUrl: 'https://a.example.test',
      hostName: 'host-foo',
      deviceId: '42',
    });
  });
});
