import { describe, expect, it } from 'vitest';

import { toPublicGitLabUrl } from '../../frontend/src/utils/gitlabUrl';

/**
 * The instance lives at an address only the VPT server can reach, so the browser is handed the
 * same-origin `/gitlab` path the proxy VM serves instead. Rewriting is a prefix strip against the
 * configured base — including GitLab's own `web_url` for a project, which is a different absolute
 * address for the same instance and would otherwise time out for anyone off-LAN.
 */
describe('toPublicGitLabUrl', () => {
  it('maps a bare instance to the public root', () => {
    expect(toPublicGitLabUrl('http://192.0.2.10/gitlab')).toBe('/gitlab');
    expect(toPublicGitLabUrl('http://192.0.2.10/gitlab/')).toBe('/gitlab');
  });

  it('keeps the deep path of a project web_url', () => {
    expect(
      toPublicGitLabUrl('http://192.0.2.10/gitlab', 'http://192.0.2.10/gitlab/root/overlay'),
    ).toBe('/gitlab/root/overlay');
  });

  it('works when the instance is configured at its own root (no /gitlab suffix)', () => {
    expect(
      toPublicGitLabUrl('http://gitlab.internal', 'http://gitlab.internal/root/overlay'),
    ).toBe('/gitlab/root/overlay');
  });

  it('never leaks the internal address into the result', () => {
    const url = toPublicGitLabUrl('http://192.0.2.10/gitlab', 'http://192.0.2.10/gitlab/root/x');
    expect(url).not.toContain('192.0.2.10');
    expect(url.startsWith('/gitlab')).toBe(true);
  });

  it('returns nothing when no instance is configured, so no link is offered', () => {
    expect(toPublicGitLabUrl('')).toBe('');
    expect(toPublicGitLabUrl(undefined)).toBe('');
    expect(toPublicGitLabUrl(null)).toBe('');
    // A web_url with no base is meaningless — do not invent a path out of it.
    expect(toPublicGitLabUrl('', 'http://192.0.2.10/gitlab/root/x')).toBe('');
  });

  it('falls back to the root for a target that is not on this instance', () => {
    // A web_url left over from a previously configured instance must not be spliced into the
    // current one; string surgery on an unrelated origin is how you get a 404 that looks valid.
    expect(
      toPublicGitLabUrl('http://192.0.2.10/gitlab', 'http://old-instance.local/gitlab/root/x'),
    ).toBe('/gitlab');
  });
});