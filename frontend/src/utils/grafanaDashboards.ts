/** The Grafana dashboards the Grafana page lists (and the ticket form offers as a target). */
export interface GrafanaDashboardInfo {
  title: string;
  uid: string;
  slug: string;
}

// Only dashboards every deployment has. Customer- or project-specific ones (FullZap, per-project
// quality) are provisioned by that deployment's own Grafana and must not be listed here.
export const GRAFANA_DASHBOARDS: GrafanaDashboardInfo[] = [
  {
    title: 'Server Monitoring',
    uid: 'system-monitoring',
    slug: 'system-monitoring'
  },
  {
    title: 'Service Status',
    uid: 'system-service-status',
    slug: 'system-service-status'
  },
  {
    title: 'Host Monitoring',
    uid: 'fe85e054-7760-4133-8118-3dfe663dee66',
    slug: 'system-host-monitoring'
  },
  {
    title: 'Device Alerts',
    uid: 'device-alerts-dashboard',
    slug: 'device-alerts-dashboard'
  },
  {
    title: 'Script Results',
    uid: '2a3b060a-7820-4a6e-aa2a-adcbf5408bd3',
    slug: 'script-results'
  },
  {
    title: 'AV Check Results',
    uid: 'av-check-results',
    slug: 'av-check-results'
  },
  {
    title: 'Navigation Metrics',
    uid: '9369e579-7f7a-47ec-ae06-f3a49e530b4f',
    slug: 'navigation-metrics'
  }
];
