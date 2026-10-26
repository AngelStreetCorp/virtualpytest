import { describe, expect, it } from 'vitest';

import { applyIntegrationLink } from '../../frontend/src/config/navItems';
import type { NavItem } from '../../frontend/src/config/navItems';

/**
 * The GitLab nav item is contributed by the feature (featureNavItems('plugins')), and under
 * vitest `virtual:vpt-features` is stubbed to `features = []` on purpose — component tests
 * exercise core pages only. So this drives applyIntegrationLink with a synthetic item rather
 * than looking for a real one in INTEGRATIONS_ITEMS, which would never be there.
 */
const gitlabItem: NavItem = { label: 'GitLab', path: '/monitoring/gitlab' };
const base = { slackUrl: 'https://slack.com' };

describe('GitLab integration shortcut', () => {
  it('adds a shortcut to the instance while keeping the page link', () => {
    const item = applyIntegrationLink(gitlabItem, { ...base, gitlabUrl: 'http://gitlab.internal' });
    expect(item.externalHref).toBe('http://gitlab.internal');
    // The shortcut is an addition, not a replacement: the item stays an internal route.
    expect(item.path).toBe('/monitoring/gitlab');
    expect(item.external).toBeUndefined();
  });

  it('adds no shortcut when the server has no GitLab instance configured', () => {
    expect(applyIntegrationLink(gitlabItem, { ...base }).externalHref).toBeUndefined();
  });

  it('treats an empty URL as "not configured" rather than linking to nothing', () => {
    expect(applyIntegrationLink(gitlabItem, { ...base, gitlabUrl: '' }).externalHref).toBeUndefined();
  });

  it('leaves the other integrations alone', () => {
    const grafana = applyIntegrationLink(
      { label: 'Grafana', path: '/grafana-dashboard' },
      { ...base, gitlabUrl: 'http://gitlab.internal', grafanaUrl: 'http://grafana.local' },
    );
    expect(grafana.externalHref).toBe('http://grafana.local/dashboards');

    const slack = applyIntegrationLink({ label: 'Slack', path: '/integrations/slack' }, base);
    expect(slack.href).toBe('https://slack.com');
  });
});