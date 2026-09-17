/**
 * getEnv() precedence — runtime config over the values Vite baked in.
 *
 * Why this is worth a test: Vite replaces `VITE_*` at build time, so before the runtime
 * config existed a built frontend could only ever serve the address it was built for, and
 * no frontend image could be published. `public/config.js` (rewritten by
 * frontend/docker/entrypoint.sh on every container start) is what breaks that, and the
 * whole mechanism rests on this one function's precedence rules. Getting them wrong is
 * silent: the page still renders, it just talks to the wrong server.
 *
 * Scope: the runtime branch and its guards, which is what this change introduced. The
 * build-time branch is NOT asserted here and cannot be — under this vitest setup
 * `vi.stubEnv` only touches process.env, and assigning to `import.meta.env` from a test
 * file does not reach the copy `config/constants.ts` reads (both verified 2026-09-15).
 * That branch is covered where it is real instead: a probe production build with marker
 * values puts them in the bundle, and the image run with no VITE_* in its environment
 * writes an empty config and serves the baked values.
 */
import { beforeEach, describe, expect, it } from 'vitest';

import { getEnv } from '@/config/constants';

declare global {
  interface Window {
    __VPT_CONFIG__?: Record<string, unknown>;
  }
}

// A key no build ever defines, so "nothing baked in" is guaranteed and the default is
// the observable fallback.
const KEY = 'VITE_RUNTIME_CONFIG_TEST_KEY';

describe('getEnv', () => {
  beforeEach(() => {
    delete window.__VPT_CONFIG__;
  });

  it('uses a value from the runtime config', () => {
    window.__VPT_CONFIG__ = { [KEY]: 'https://runtime.example.com' };
    expect(getEnv(KEY, 'the-default')).toBe('https://runtime.example.com');
  });

  it('ignores the runtime config for a key it does not define', () => {
    window.__VPT_CONFIG__ = { VITE_SOMETHING_ELSE: 'other' };
    expect(getEnv(KEY, 'the-default')).toBe('the-default');
  });

  // The entrypoint omits unset variables, but a hand-edited config.js or a compose file
  // passing `VITE_X=` would send an empty string. That must not count as "set", or it
  // would blank out a working baked-in value — the case that takes a deployment down.
  it('treats an empty runtime value as unset', () => {
    window.__VPT_CONFIG__ = { [KEY]: '' };
    expect(getEnv(KEY, 'the-default')).toBe('the-default');
  });

  it('treats null and undefined runtime values as unset', () => {
    window.__VPT_CONFIG__ = { [KEY]: null };
    expect(getEnv(KEY, 'the-default')).toBe('the-default');
    window.__VPT_CONFIG__ = { [KEY]: undefined };
    expect(getEnv(KEY, 'the-default')).toBe('the-default');
  });

  it('works with no runtime config at all — the native, non-container install', () => {
    expect(window.__VPT_CONFIG__).toBeUndefined();
    expect(getEnv(KEY, 'the-default')).toBe('the-default');
  });

  it('returns an empty string when nothing is set and no default is given', () => {
    expect(getEnv(KEY)).toBe('');
  });

  it('passes through a value containing quotes, which the entrypoint JSON-escapes', () => {
    window.__VPT_CONFIG__ = { [KEY]: 'Acme "QA" Lab' };
    expect(getEnv(KEY)).toBe('Acme "QA" Lab');
  });

  it('coerces a non-string runtime value rather than returning it raw', () => {
    window.__VPT_CONFIG__ = { [KEY]: 30000 };
    expect(getEnv(KEY)).toBe('30000');
  });
});
