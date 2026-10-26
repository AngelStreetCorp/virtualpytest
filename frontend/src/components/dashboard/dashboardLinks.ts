import { REPORT_ROUTES } from '../../types/reports';

import type { DashRange } from './dashboardTypes';

/**
 * Where each dashboard number leads. The dashboard is view-only: every row and number is a link to
 * an existing page that answers the follow-up. Only query params those pages read are used.
 */
export const DASH_LINKS = {
  /** Script results, optionally narrowed to one verdict and the dashboard's time range (TestReports reads both). */
  reports: (opts: { status?: 'passed' | 'failed' | 'aborted'; range?: DashRange } = {}): string => {
    const q = new URLSearchParams();
    if (opts.status) q.set('status', opts.status);
    if (opts.range) q.set('range', opts.range);
    const s = q.toString();
    return `/test-results/reports${s ? `?${s}` : ''}`;
  },
  report: (resultId: string): string => REPORT_ROUTES.summary('script', resultId),
  flaky: (): string => REPORT_ROUTES.quality('flaky'),
  running: '/run/monitor',
  deployments: '/run/deployments',
  devices: '/device-control',
  /** Device Control with the user's starred devices selected (Rec reads `favorites=1` into the shared target filter). */
  favourites: '/device-control?favorites=1',
  /** Device Control focused on one device (Rec reads `device=<host>/<device_id>` into the shared target filter). */
  device: (host: string, deviceId: string): string => `/device-control?device=${encodeURIComponent(`${host}/${deviceId}`)}`,
  /** Device Control narrowed to every device of one host (Rec reads `host=<host>` into the shared target filter). */
  host: (host: string): string => `/device-control?host=${encodeURIComponent(host)}`,
  /** Hosts, services, storage and lease state of the platform. */
  status: '/status',
  incidents: '/monitoring/incidents',
  aiUsage: '/monitoring/ai-usage',
} as const;
