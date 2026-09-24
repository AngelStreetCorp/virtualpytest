/**
 * The integrations grid shown at the top of /docs/integrations.
 *
 * Fourteen entries, rendered three to a row by IntegrationsGridView. `logo` is the URL of a mark
 * under `public/vendor/`, which is the one place marks live: the farm pair is served
 * straight out of `vendor/farm/`, the same two files DeviceFarmBadge puts on every farm
 * device preview, so a logo is never stored twice. Each file carries its own fill, picked
 * to stay legible on both themes; `brand` here only tints the card's backing tile.
 *
 * Every vendor has its mark today. A new one added without one gets `logo: null` and falls
 * back to a monogram tile of the same shape — a missing asset, not a design choice. Drop a
 * `<slug>-mark.svg` into `public/vendor/integrations/`, point `logo` at it, and the tile
 * disappears.
 *
 * Everything here is `live` right now, so the grid renders no status chip. Add one entry
 * that is not and the chips and their legend come back on their own.
 *
 * `status` is what the code actually does, not what the roadmap hopes for. Keep it
 * honest — the chip is the only thing on this page telling a reader whether they can
 * use the integration today.
 */

export type IntegrationStatus = 'live' | 'planned';

export interface Integration {
  name: string;
  /** URL of the mark under `public/vendor/`, or null to render a monogram tile. */
  logo: string | null;
  /** Official brand hex — tints the card's backing tile and hover border, nothing else. */
  brand: string;
  /** One sentence. It sits under the name in a narrow card, so keep it short. */
  description: string;
  status: IntegrationStatus;
  /** Docs route the card links to. */
  href: string;
}

export const INTEGRATIONS: Integration[] = [
  {
    name: 'Jira',
    logo: '/vendor/integrations/jira-mark.svg',
    brand: '#0052CC',
    description: 'Your tickets on a read-only board inside VirtualPyTest.',
    status: 'live',
    href: '/docs/integrations/jira-setup',
  },
  {
    name: 'Slack',
    logo: '/vendor/integrations/slack-mark.svg',
    brand: '#36C5F0',
    description: 'AI Agent conversations mirrored into a channel, a thread per chat.',
    status: 'live',
    href: '/docs/integrations/slack-setup',
  },
  {
    name: 'Grafana',
    logo: '/vendor/integrations/grafana-mark.svg',
    brand: '#F46800',
    description: 'Built-in dashboards for KPIs, device health and test analytics.',
    status: 'live',
    href: '/docs/features/analytics',
  },
  {
    name: 'Sauce Labs',
    logo: '/vendor/farm/saucelabs-mark.svg',
    brand: '#3DDC91',
    description: 'A leased cloud phone driven like one on your desk — same panel, same scripts.',
    status: 'live',
    href: '/docs/integrations/device-farms',
  },
  {
    name: 'BrowserStack',
    logo: '/vendor/farm/browserstack-mark.svg',
    brand: '#FE5000',
    description: 'The same farm device, allocated from BrowserStack\'s cloud instead.',
    status: 'live',
    href: '/docs/integrations/device-farms',
  },
  {
    name: 'Appium',
    logo: '/vendor/integrations/appium-mark.svg',
    brand: '#EE376D',
    description: 'Drives every phone and tablet, on a desk or in a farm.',
    status: 'live',
    href: '/docs/features/unified-controller',
  },
  {
    name: 'Playwright',
    logo: '/vendor/integrations/playwright-mark.svg',
    brand: '#2EAD33',
    description: 'Drives the web hosts headless, a browser session per script.',
    status: 'live',
    href: '/docs/features/unified-controller',
  },
  {
    name: 'GitHub Actions',
    logo: '/vendor/integrations/githubactions-mark.svg',
    brand: '#2088FF',
    description: 'Launch CI runs and read their results without leaving the app.',
    status: 'live',
    href: '/docs/features/cicd',
  },
  {
    name: 'Postman',
    logo: '/vendor/integrations/postman-mark.svg',
    brand: '#FF6C37',
    description: 'A published collection covering the whole REST API.',
    status: 'live',
    href: '/docs/api',
  },
  {
    name: 'Langfuse',
    logo: '/vendor/integrations/langfuse-mark.svg',
    brand: '#4E9CFF',
    description: 'Traces, latency and cost for every AI run.',
    status: 'live',
    href: '/docs/features/ai-test',
  },
  {
    name: 'OpenRouter',
    logo: '/vendor/integrations/openrouter-mark.svg',
    brand: '#8B5CF6',
    description: 'One key for every frontier model the AI agent calls.',
    status: 'live',
    href: '/docs/features/ai-test',
  },
  {
    name: 'Supabase',
    logo: '/vendor/integrations/supabase-mark.svg',
    brand: '#3FCF8E',
    description: 'Postgres, auth and storage behind the whole platform.',
    status: 'live',
    href: '/docs/get-started/supabase',
  },
  {
    name: 'Cloudflare R2',
    logo: '/vendor/integrations/cloudflare-mark.svg',
    brand: '#F38020',
    description: 'Stores every screenshot and capture video, S3-compatible.',
    status: 'live',
    href: '/docs/get-started/cloud-setup',
  },
  {
    name: 'MinIO',
    logo: '/vendor/integrations/minio-mark.svg',
    brand: '#C72E49',
    description: 'The same S3 storage when you stay on your own metal.',
    status: 'live',
    href: '/docs/get-started/cloud-setup',
  },
];

export const STATUS_LABEL: Record<IntegrationStatus, string> = {
  live: 'Live',
  planned: 'Planned',
};
