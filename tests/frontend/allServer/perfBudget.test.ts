/**
 * TASK-113 — PR-F tests: perf budget placeholder + observability sink.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { withinBudget, budgetFor, PERF_BUDGET } from '../../../frontend/src/lib/allServer/perfBudget';
import {
  setAllServerLogSink,
  traceAllServer,
  summarizeResults,
} from '../../../frontend/src/lib/allServer/observability';
import type { ServerConnection } from '../../../frontend/src/types/allServer/AllServer_Types';

const SERVER: ServerConnection = {
  serverId: 'https://a.example.test',
  url: 'https://a.example.test',
  name: 'A',
  authState: 'authenticated',
};

describe('PERF_BUDGET placeholder', () => {
  it('returns Infinity for every (category, serverCount) pair', () => {
    for (const category of Object.keys(PERF_BUDGET) as Array<keyof typeof PERF_BUDGET>) {
      for (const n of [1, 2, 5, 10]) {
        expect(budgetFor(category, n)).toBe(Infinity);
      }
    }
  });

  it('withinBudget returns ok=true with Infinity headroom for the placeholder', () => {
    const r = withinBudget('listP95MsByServerCount', 5, 9_999_999);
    expect(r.ok).toBe(true);
  });
});

describe('traceAllServer', () => {
  let sinkEvents: unknown[] = [];
  beforeEach(() => {
    sinkEvents = [];
    setAllServerLogSink((e) => sinkEvents.push(e));
  });
  afterEach(() => {
    setAllServerLogSink(null);
  });

  it('emits an "ok" event with durationMs on success', async () => {
    await traceAllServer('query', 'all', SERVER, '/server/hosts/getAll', async () => ({ ok: 1 }));
    const ev = sinkEvents[0] as { op: string; status: string; durationMs: number; serverId: string };
    expect(ev.op).toBe('query');
    expect(ev.status).toBe('ok');
    expect(ev.serverId).toBe(SERVER.serverId);
    expect(typeof ev.durationMs).toBe('number');
  });

  it('emits an "unauthorized" event on a 401 and rethrows', async () => {
    const err = Object.assign(new Error('nope'), { status: 401 });
    await expect(
      traceAllServer('action', 'single', SERVER, '/server/foo', async () => {
        throw err;
      }),
    ).rejects.toBe(err);
    const ev = sinkEvents[0] as { status: string; error: string };
    expect(ev.status).toBe('unauthorized');
    expect(ev.error).toBe('nope');
  });
});

describe('summarizeResults', () => {
  it('counts by status', () => {
    const s = summarizeResults([
      { serverId: 'a', status: 'ok', value: 1, fetchedAt: 0 },
      { serverId: 'b', status: 'ok', value: 2, fetchedAt: 0 },
      { serverId: 'c', status: 'offline', error: 'refused' },
    ]);
    expect(s).toContain('ok=2');
    expect(s).toContain('offline=1');
  });
});
