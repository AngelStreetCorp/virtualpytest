/**
 * BUG-0590: the REC tile and Take Control modal let noVNC fit the server's real framebuffer
 * (`?scale=true` -> `rfb.scaleViewport` in vnc_lite.html) instead of shrinking a fixed
 * 1440x847 box with a CSS transform, which cropped Windows desktops at other resolutions.
 * These tests pin the URL rewriting: the password / cache-bust params and any `#fragment`
 * must survive, and the flag must be idempotent.
 */
import { describe, expect, it } from 'vitest';

import { withVncViewportScale } from './vncUtils';

describe('withVncViewportScale', () => {
  it('adds the first query parameter when the URL has none', () => {
    expect(withVncViewportScale('https://example.test/vnc_lite.html')).toBe(
      'https://example.test/vnc_lite.html?scale=true',
    );
  });

  it('appends to an existing query string (cache-bust + password already there)', () => {
    expect(
      withVncViewportScale(
        'https://example.test/vnc_lite.html?_vpt=abc&password=p%40ss',
      ),
    ).toBe('https://example.test/vnc_lite.html?_vpt=abc&password=p%40ss&scale=true');
  });

  it('keeps a hash fragment after the query string', () => {
    expect(
      withVncViewportScale('https://example.test/vnc_lite.html?path=/host/x/websockify#password=abc'),
    ).toBe(
      'https://example.test/vnc_lite.html?path=/host/x/websockify&scale=true#password=abc',
    );
  });

  it('does not add a second scale parameter', () => {
    const url = 'https://example.test/vnc_lite.html?_vpt=abc&scale=true';
    expect(withVncViewportScale(url)).toBe(url);
  });

  it('overrides an explicit scale=false rather than duplicating it', () => {
    expect(withVncViewportScale('https://example.test/vnc_lite.html?scale=false&_vpt=abc')).toBe(
      'https://example.test/vnc_lite.html?scale=true&_vpt=abc',
    );
  });
});
