/**
 * Server URL building (BUG-0430).
 *
 * The invariant worth pinning: a URL built for a named server keeps THAT server's
 * origin. `buildServerUrlForServer` and `buildServerUrl` used to rebuild the URL from
 * `u.pathname + u.search + u.hash`, which keeps everything except the origin — and a
 * path-only URL is resolved by the browser against the page's own host. So every
 * cross-server call silently went to whichever server served the page, and the server
 * picker listed the primary's name once per configured server.
 *
 * The second invariant is the one that fix must not break: `team_id` stays idempotent
 * (TASK-66) — an endpoint that already carries one gets exactly one in the result.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  buildServerUrl,
  buildServerUrlForServer,
  getAllServerUrls,
} from '../../frontend/src/utils/buildUrlUtils';
import { APP_CONFIG, STORAGE_KEYS } from '../../frontend/src/config/constants';
import { ALL_SERVERS_SENTINEL } from '../../frontend/src/lib/allServer/scope';

const PRIMARY = 'https://primary.example.com';
const SECONDARY = 'https://secondary.example.com';
const TEAM = APP_CONFIG.DEFAULT_TEAM_ID;
const ENDPOINT = '/server/system/getAllHosts';

describe('buildServerUrlForServer', () => {
  it('keeps the origin of the server it was asked for (BUG-0430)', () => {
    const url = buildServerUrlForServer(SECONDARY, ENDPOINT);

    expect(url.startsWith(`${SECONDARY}${ENDPOINT}`)).toBe(true);
    expect(new URL(url).origin).toBe(new URL(SECONDARY).origin);
  });

  it('keeps each configured server distinct, so no two resolve to the same host', () => {
    const urls = [PRIMARY, SECONDARY].map((s) => buildServerUrlForServer(s, ENDPOINT));

    expect(new Set(urls.map((u) => new URL(u).origin)).size).toBe(2);
  });

  it('is idempotent for team_id and keeps exactly one (TASK-66)', () => {
    const once = buildServerUrlForServer(SECONDARY, ENDPOINT);
    const twice = buildServerUrlForServer(SECONDARY, once);

    expect(twice.match(/team_id=/g)).toHaveLength(1);
    expect(new URL(twice).searchParams.get('team_id')).toBe(TEAM);
  });

  it('strips a trailing /server so it cannot double up', () => {
    const url = buildServerUrlForServer(`${SECONDARY}/server`, ENDPOINT);

    expect(url).not.toContain('/server/server/');
    expect(new URL(url).origin).toBe(new URL(SECONDARY).origin);
  });

  it('adds the protocol when the configured URL has none', () => {
    // The builder logs when it guesses; keep the suite output clean.
    const log = vi.spyOn(console, 'log').mockImplementation(() => {});
    try {
      expect(buildServerUrlForServer('secondary.example.com', ENDPOINT).startsWith('http://')).toBe(true);
    } finally {
      log.mockRestore();
    }
  });

  it('rejects an empty server URL rather than guessing the page origin', () => {
    // This is why the relative branch below is unreachable from here: an unset
    // VITE_SERVER_URL cannot reach buildServerUrlForServer at all.
    expect(() => buildServerUrlForServer('', ENDPOINT)).toThrow(/Invalid serverUrl/);
  });

  it('never builds a request against the "__all__" sentinel (BUG-0769)', () => {
    localStorage.clear();
    delete (window as unknown as Record<string, unknown>).__VPT_CONFIG__;

    const url = buildServerUrlForServer(ALL_SERVERS_SENTINEL, ENDPOINT);

    expect(url).not.toContain('__all__');
    expect(() => new URL(url)).not.toThrow();
    expect(new URL(url).searchParams.get('team_id')).toBe(TEAM);
  });
});

describe('buildServerUrl', () => {
  beforeEach(() => {
    localStorage.clear();
    delete (window as unknown as Record<string, unknown>).__VPT_CONFIG__;
  });

  it('keeps the origin of the SELECTED server, not the page (BUG-0430)', () => {
    localStorage.setItem(STORAGE_KEYS.SELECTED_SERVER, SECONDARY);

    const url = buildServerUrl(ENDPOINT);

    expect(url.startsWith(`${SECONDARY}${ENDPOINT}`)).toBe(true);
    expect(new URL(url).origin).toBe(new URL(SECONDARY).origin);
  });

  it('is idempotent for team_id and keeps exactly one (TASK-66)', () => {
    localStorage.setItem(STORAGE_KEYS.SELECTED_SERVER, SECONDARY);

    const twice = buildServerUrl(buildServerUrl(ENDPOINT));

    expect(twice.match(/team_id=/g)).toHaveLength(1);
  });
});

describe('getAllServerUrls', () => {
  const setConfig = (cfg: Record<string, string>) => {
    (window as unknown as Record<string, unknown>).__VPT_CONFIG__ = cfg;
  };

  beforeEach(() => {
    localStorage.clear();
    delete (window as unknown as Record<string, unknown>).__VPT_CONFIG__;
  });

  it('lists the primary and every slave URL, in order', () => {
    setConfig({
      VITE_SERVER_URL: PRIMARY,
      VITE_SLAVE_SERVER_URL: `${SECONDARY},https://third.example.com`,
    });

    expect(getAllServerUrls()).toEqual([PRIMARY, SECONDARY, 'https://third.example.com']);
  });

  it('drops a slave URL that repeats the primary verbatim (BUG-0431)', () => {
    setConfig({ VITE_SERVER_URL: PRIMARY, VITE_SLAVE_SERVER_URL: `${PRIMARY},${SECONDARY}` });

    expect(getAllServerUrls()).toEqual([PRIMARY, SECONDARY]);
  });

  it('drops a slave URL that repeats the primary as <primary>/server (BUG-0431)', () => {
    // The /server suffix is stripped while parsing, so this used to produce two
    // identical rows and two identical /getAllHosts requests per refresh round.
    setConfig({ VITE_SERVER_URL: PRIMARY, VITE_SLAVE_SERVER_URL: `${PRIMARY}/server,${SECONDARY}` });

    expect(getAllServerUrls()).toEqual([PRIMARY, SECONDARY]);
  });

  it('treats a trailing slash and letter case as the same server (BUG-0431)', () => {
    setConfig({
      VITE_SERVER_URL: PRIMARY,
      VITE_SLAVE_SERVER_URL: `${PRIMARY}/,${PRIMARY.toUpperCase()},${SECONDARY}`,
    });

    expect(getAllServerUrls()).toEqual([PRIMARY, SECONDARY]);
  });

  it('keeps the first spelling of a repeated URL', () => {
    setConfig({ VITE_SERVER_URL: `${PRIMARY}/`, VITE_SLAVE_SERVER_URL: PRIMARY });

    // The first spelling wins, so state, localStorage and built links keep using what
    // the deployment configured rather than a later duplicate's variant.
    expect(getAllServerUrls()).toEqual([`${PRIMARY}/`]);
  });

  it('still returns one entry when nothing is configured (default fallback)', () => {
    expect(getAllServerUrls().length).toBe(1);
  });
});
