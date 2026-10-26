/**
 * TASK-113 — PR-C tests: scope derivation, ServerChip, ServerSelector
 * "All servers" row.
 *
 * The scope test covers the pure helper. ServerSelector / ServerChip
 * need DOM; the existing vitest config has `environment: 'jsdom'`, so
 * component renders are in scope.
 */
import { describe, it, expect } from 'vitest';
import {
  ALL_SERVERS_SENTINEL,
  isAllServersSentinel,
  deriveScope,
} from '../../../frontend/src/lib/allServer/scope';

describe('ALL_SERVERS_SENTINEL', () => {
  it('is a string that no real server URL can collide with', () => {
    expect(typeof ALL_SERVERS_SENTINEL).toBe('string');
    expect(ALL_SERVERS_SENTINEL.length).toBeGreaterThan(0);
    expect(ALL_SERVERS_SENTINEL).toContain('__all__');
  });
});

describe('isAllServersSentinel', () => {
  it('returns true only for the sentinel value', () => {
    expect(isAllServersSentinel(ALL_SERVERS_SENTINEL)).toBe(true);
  });
  it('returns false for a real server URL', () => {
    expect(isAllServersSentinel('https://a.example.test')).toBe(false);
    expect(isAllServersSentinel('')).toBe(false);
    expect(isAllServersSentinel('__other__')).toBe(false);
  });
});

describe('deriveScope', () => {
  it("returns { kind: 'all' } for the sentinel", () => {
    expect(deriveScope(ALL_SERVERS_SENTINEL)).toEqual({ kind: 'all' });
  });
  it("returns { kind: 'single', serverId } for a real URL", () => {
    expect(deriveScope('https://a.example.test')).toEqual({
      kind: 'single',
      serverId: 'https://a.example.test',
    });
  });
  it("returns { kind: 'single', serverId: '' } for empty input", () => {
    expect(deriveScope('')).toEqual({ kind: 'single', serverId: '' });
  });
});
