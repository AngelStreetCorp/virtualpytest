/**
 * Navbar configuration — single source of truth for the nav menu, the
 * Settings > Page Visibility table, and the Workspaces > Pages tab.
 *
 * The full route path (`NavigationItem.path`) is the universal visibility
 * key across all three layers — env-level (`VITE_NAV_*`), admin settings,
 * and per-workspace `hidden_pages`. No aliasing, no segment stripping.
 */
import { isValidElement, type ReactElement } from 'react';
import {
  AccountTree as TreeIcon,
  Apps as AllIntegrationsIcon,
  Assessment as ReportsIcon,
  Assignment as RequirementIcon,
  Bolt as BoltIcon,
  Build as BuildIcon,
  Speed as QualityIcon,
  Bookmarks as RunManagementIcon,
  BarChart as AnalyticsIcon,
  Campaign as CampaignIcon,
  CloudUpload as CodeDeployIcon,
  Dashboard as DashboardIcon,
  GridView as HeatmapIcon,
  Link as LinkIcon,
  Memory as ModelIcon,
  PlayArrow as RunIcon,
  RocketLaunch as AgentIcon,
  Science as TestIcon,
  TrendingUp as CoverageIcon,
  Terminal as TerminalIcon,
  TouchApp as TouchAppIcon,
  Visibility as MonitorIcon,
  Warning as IncidentIcon,
  // Docs menu: outlined set. The docs left rail (DocsNav) reads these same icon elements from DOCS_ITEMS.

  ApiOutlined,
  AutoAwesomeOutlined,
  BugReportOutlined,
  BuildOutlined,
  ExtensionOutlined,
  HelpOutlineOutlined,
  HomeOutlined,
  MenuBookOutlined,
  MovieOutlined,
  NewReleasesOutlined,
  PhotoLibraryOutlined,
  RocketLaunchOutlined,
  SecurityOutlined,
} from '@mui/icons-material';


import type {
  NavigationGroupedItem,
  NavigationItem,
} from '../types/pages/Navigation_Types';
import { featureNavItems } from './features';

export type NavItem = NavigationItem;
export type NavGroup = NavigationGroupedItem;

// ─── Standalone top-level buttons ─────────────────────────────────────────────
// These render as plain <Button> elements (not dropdowns).

export interface NavStandaloneItem {
  label: string;
  path: string;
  // Custom match predicate for highlighting (defaults to exact path match).
  matchPrefix?: boolean;
}

export const DASHBOARD_ITEM: NavStandaloneItem = { label: 'Dashboard', path: '/' };
export const DEVICE_ITEM: NavStandaloneItem = { label: 'Device', path: '/device-control' };
export const INTERFACE_ITEM: NavStandaloneItem = {
  label: 'Interface',
  path: '/configuration/interface',
  matchPrefix: true,
};

// ─── AI ───────────────────────────────────────────────────────────────────────

export const AI_AGENT_ITEMS: NavItem[] = [
  {
    label: 'Chat Agent',
    path: '/ai-agent',
    icon: <AgentIcon fontSize="small" />,
  },
  {
    label: 'Agent Dashboard',
    path: '/agent-dashboard',
    icon: <DashboardIcon fontSize="small" />,
  },
  // Optional features append their own entries (docs/technical/FEATURES.md)
  ...featureNavItems('ai'),
];

// ─── Test (grouped: Build / Plan / Execute / Report) ──────────────────────────

export const TEST_GROUPS: NavGroup[] = [
  {
    sectionLabel: 'Build',
    items: [
      { label: 'Test Builder', path: '/builder/test-builder', icon: <TreeIcon fontSize="small" /> },
      {
        label: 'Campaign Builder',
        path: '/builder/campaign-builder',
        icon: <BuildIcon fontSize="small" />,
      },
      // Optional feature builders append here (docs/technical/FEATURES.md)
      ...featureNavItems('test-build'),
    ],
  },
  {
    sectionLabel: 'Plan',
    items: [
      { label: 'Test Cases', path: '/test-plan/test-cases', icon: <TestIcon fontSize="small" /> },
      { label: 'Campaigns', path: '/test-plan/campaigns', icon: <CampaignIcon fontSize="small" /> },
      {
        label: 'Requirements',
        path: '/test-plan/requirements',
        icon: <RequirementIcon fontSize="small" />,
      },
      {
        label: 'Coverage',
        path: '/test-plan/coverage',
        icon: <CoverageIcon fontSize="small" />,
      },
    ],
  },
  {
    sectionLabel: 'Execute',
    items: [
      {
        label: 'Run Tests',
        path: '/test-execution/run-tests',
        icon: <RunIcon fontSize="small" />,
      },
      {
        label: 'Monitor Tests',
        path: '/test-execution/monitor-tests',
        icon: <MonitorIcon fontSize="small" />,
      },
      {
        label: 'Build Campaign',
        path: '/test-execution/build-campaign',
        icon: <CampaignIcon fontSize="small" />,
      },
      // Optional feature runners append here (docs/technical/FEATURES.md)
      ...featureNavItems('test-execute'),
    ],
  },
  {
    sectionLabel: 'Report',
    items: [
      {
        label: 'Test Reports',
        path: '/test-results/reports',
        icon: <ReportsIcon fontSize="small" />,
      },
      { label: 'Quality', path: '/test-results/quality', icon: <QualityIcon fontSize="small" /> },
      {
        label: 'Run Management',
        path: '/test-results/run-management',
        icon: <RunManagementIcon fontSize="small" />,
      },
      {
        label: 'Model Reports',
        path: '/test-results/model-reports',
        icon: <ModelIcon fontSize="small" />,
      },
      {
        label: 'Dependency Report',
        path: '/test-results/dependency-report',
        icon: <LinkIcon fontSize="small" />,
      },
      // Optional feature reports append here (docs/technical/FEATURES.md)
      ...featureNavItems('test-report'),
    ],
  },
];

// ─── Monitoring ───────────────────────────────────────────────────────────────

export const MONITORING_ITEMS: NavItem[] = [
  {
    label: 'Analytics',
    path: '/monitoring/analytics',
    icon: <AnalyticsIcon fontSize="small" />,
  },
  {
    label: 'Incidents',
    path: '/monitoring/incidents',
    icon: <IncidentIcon fontSize="small" />,
  },
  {
    label: 'Heatmap',
    path: '/monitoring/heatmap',
    icon: <HeatmapIcon fontSize="small" />,
  },
  {
    label: 'Timeline',
    path: '/monitoring/timeline',
    icon: <HeatmapIcon fontSize="small" />,
  },
  {
    label: 'AI Queue',
    path: '/monitoring/ai-queue',
    icon: <DashboardIcon fontSize="small" />,
  },
  {
    label: 'AI usage',
    path: '/monitoring/ai-usage',
    icon: <AnalyticsIcon fontSize="small" />,
  },
  {
    // One page, two tabs: Matches (was Matcher history, /match-runs) and Coverage.
    label: 'Localize monitoring',
    path: '/monitoring/localize',
    icon: <TouchAppIcon fontSize="small" />,
  },
  ...featureNavItems('monitoring'),
];

// ─── Docs ─────────────────────────────────────────────────────────────────────

export const DOCS_ITEMS: NavItem[] = [
  // The Docs menu is the single source of truth for the docs section order, labels and icons:
  // the docs left rail (components/docs/DocsNav.tsx) and the manifest titles follow it.
  {
    label: 'Home',
    path: '/docs',
    icon: <HomeOutlined fontSize="small" />,
  },
  {
    label: 'Get Started',
    path: '/docs/get-started',
    icon: <RocketLaunchOutlined fontSize="small" />,
  },
  {
    label: 'Release Note',
    path: '/docs/release_note',
    icon: <NewReleasesOutlined fontSize="small" />,
  },
  {
    label: 'Bugs',
    path: '/docs/bugs',
    icon: <BugReportOutlined fontSize="small" />,
  },
  {
    label: 'FAQ',
    path: '/docs/faq',
    icon: <HelpOutlineOutlined fontSize="small" />,
  },
  {
    label: 'Features',
    path: '/docs/features',
    icon: <AutoAwesomeOutlined fontSize="small" />,
  },
  {
    label: 'Integrations',
    path: '/docs/integrations',
    icon: <ExtensionOutlined fontSize="small" />,
  },
  {
    label: 'User Guide',
    path: '/docs/user-guide',
    icon: <MenuBookOutlined fontSize="small" />,
  },
  {
    label: 'Technical Docs',
    path: '/docs/technical',
    icon: <BuildOutlined fontSize="small" />,
  },
  {
    label: 'Security Reports',
    path: '/docs/security',
    icon: <SecurityOutlined fontSize="small" />,
  },
  {
    label: 'API Reference',
    path: '/docs/api',
    icon: <ApiOutlined fontSize="small" />,
  },
  {
    label: 'Screenshots',
    path: '/docs/screenshots',
    icon: <PhotoLibraryOutlined fontSize="small" />,
  },
  {
    label: 'Videos',
    path: '/docs/videos',
    icon: <MovieOutlined fontSize="small" />,
  },
  ...featureNavItems('docs'),
];

/** Menu icon of a top-level docs section (`/docs/<section>`; `root` is Home), or null. Shared with the docs rail and page header. */
export const docsSectionIcon = (section: string): ReactElement | null => {
  const icon = DOCS_ITEMS.find((i) => i.path === (section === 'root' ? '/docs' : `/docs/${section}`))?.icon;
  return isValidElement(icon) ? icon : null;
};

// ─── Integrations (Plugins) ───────────────────────────────────────────────────
// Items here are static (label/path/icon). Runtime values such as the Slack
// URL or the conditional Langfuse external URL are applied in Navigation_Bar
// via `buildIntegrationsItems()`.

// Vendor marks live in public/vendor/integrations (the same files /docs/integrations draws).
const vendorMark = (slug: string, name: string) => (
  <img
    src={`/vendor/integrations/${slug}-mark.svg`}
    alt=""
    aria-label={name}
    width={20}
    height={20}
    style={{ display: 'block', objectFit: 'contain' }}
  />
);

export const INTEGRATIONS_ITEMS: NavItem[] = [
  {
    label: 'Integrations',
    path: '/integrations',
    icon: <AllIntegrationsIcon fontSize="small" />,
  },
  {
    label: 'Grafana',
    path: '/grafana-dashboard',
    icon: vendorMark('grafana', 'Grafana'),
  },
  {
    label: 'Langfuse',
    path: '/langfuse-dashboard',
    icon: vendorMark('langfuse', 'Langfuse'),
  },
  {
    label: 'Postman',
    path: '/api/workspaces',
    icon: vendorMark('postman', 'Postman'),
    externalHref: 'https://martian-zodiac-279215.postman.co/workspace/virtualpytest~4e7a465c-a542-4440-8903-48787f03942a',
  },
  {
    label: 'Jira',
    path: '/integrations/jira',
    icon: vendorMark('jira', 'Jira'),
  },
  {
    label: 'TestRail',
    path: '/integrations/testrail',
    icon: vendorMark('testrail', 'TestRail'),
  },
  {
    label: 'Slack',
    path: '/integrations/slack',
    icon: vendorMark('slack', 'Slack'),
    external: true,
  },
  // Plugins a feature ships (GitLab's own page) belong with the integrations they sit next to,
  // not under Monitoring — Monitoring is for the platform's own telemetry.
  ...featureNavItems('plugins'),
  // The map of everything VirtualPyTest connects to, live and planned. The entries
  // above deep-link into one tool each; this one is the way in for a tool that has no
  // page of its own (the device farms, Appium, Playwright, the storage backends).
  {
    label: 'Integrations documentation',
    path: '/docs/integrations',
    icon: <MenuBookOutlined fontSize="small" />,
  },
];

/**
 * Apply runtime values (fetched slackUrl, optional Langfuse env URL) to the
 * static integrations list.
 *
 * - Slack is always external; its `href` is injected from the backend config.
 * - Langfuse becomes external only when `VITE_LANGFUSE_URL` is set; otherwise
 *   it stays as an internal link to `/langfuse-dashboard` (the config page).
 * - TestRail keeps its configuration page link and shows an external shortcut
 *   to the configured instance URL.
 * - Grafana keeps its embedded dashboard page link and shows an external
 *   shortcut to the Grafana dashboards list when `VITE_GRAFANA_URL` is set.
 * - Zammad keeps its page link and shows a shortcut to its web UI (the feature's public_url).
 * - GitLab keeps its page link and shows a shortcut to the connected instance.
 *   The URL is per server (each VPT server stores its own instance), so it is
 *   refetched on `vpt:server-changed` rather than read once at mount.
 */
export interface IntegrationLinkParams {
  slackUrl: string;
  langfuseUrl?: string;
  testrailInstanceUrl?: string;
  grafanaUrl?: string;
  gitlabUrl?: string;
  zammadUrl?: string;
}

/**
 * The runtime value for ONE item, split out from buildIntegrationsItems so it can be tested
 * directly: under vitest `virtual:vpt-features` is stubbed to `features = []` (component tests
 * exercise core pages only), so a feature-contributed item like GitLab never exists in
 * INTEGRATIONS_ITEMS during a test run and mapping over the list would prove nothing.
 *
 * Unknown items come back unchanged, so a feature can add a nav entry without touching this.
 */
export function applyIntegrationLink(item: NavItem, params: IntegrationLinkParams): NavItem {
  if (item.label === 'Slack') {
    return { ...item, href: params.slackUrl };
  }
  if (item.label === 'Langfuse' && params.langfuseUrl) {
    return { ...item, external: true, href: params.langfuseUrl };
  }
  if (item.label === 'Grafana' && params.grafanaUrl) {
    return { ...item, externalHref: `${params.grafanaUrl}/dashboards` };
  }
  if (item.label === 'TestRail' && params.testrailInstanceUrl) {
    return { ...item, externalHref: params.testrailInstanceUrl };
  }
  if (item.label === 'GitLab' && params.gitlabUrl) {
    return { ...item, externalHref: params.gitlabUrl };
  }
  if (item.label === 'Zammad' && params.zammadUrl) {
    return { ...item, externalHref: params.zammadUrl };
  }
  return item;
}

export function buildIntegrationsItems(params: IntegrationLinkParams): NavItem[] {
  return INTEGRATIONS_ITEMS.map((item) => applyIntegrationLink(item, params));
}

// ─── Configuration (Settings dropdown) ────────────────────────────────────────

export const CONFIGURATION_ITEMS: NavItem[] = [
  {
    label: 'Logs',
    path: '/configuration/logs',
    icon: <TerminalIcon fontSize="small" />,
  },
  {
    label: 'Models',
    path: '/configuration/models',
    icon: <ModelIcon fontSize="small" />,
  },
  {
    label: 'Settings',
    path: '/configuration/settings',
    icon: <BuildIcon fontSize="small" />,
  },
  {
    label: 'Platform update',
    path: '/configuration/platform-update',
    icon: <CodeDeployIcon fontSize="small" />,
  },
  {
    label: 'Run Command',
    path: '/configuration/run-command',
    icon: <TerminalIcon fontSize="small" />,
  },
  {
    label: 'Status',
    path: '/status',
    icon: <BoltIcon fontSize="small" />,
  },
  // BUG-0569 / BUG-0571: matcher history moved to Monitoring (see
  // MONITORING_ITEMS above).  Settings no longer hosts it, and the
  // empty-object stub that used to live here is the reason the Settings
  // nav crashed (`requiredPermissionForPath({})` -> path.startsWith
  // threw and took the whole top bar down).  The defensive guards in
  // Navigation_Dropdown and auth.requiredPermissionForPath also tolerate
  // malformed rows, so the page survives, but the stub itself is gone.
  ...featureNavItems('settings'),
];

// ─── Flat list for Settings > Page Visibility and Workspaces > Pages ─────────

export interface FlatNavEntry {
  /** Display label. */
  label: string;
  /** Section / dropdown this item lives in (e.g. "Plugins", "Test › Plan"). */
  section: string;
  /** Full route path — the universal visibility key. */
  path: string;
}

function toFlatEntries(section: string, items: NavItem[]): FlatNavEntry[] {
  return items.map((item) => ({
    label: item.label,
    section,
    path: item.path,
  }));
}

/**
 * Flat list of every navbar-controllable item, grouped by the navbar section
 * it belongs to. The `path` of each entry is the key used for visibility
 * everywhere (env `VITE_NAV_*`, admin settings, workspace `hidden_pages`).
 */
export const ALL_NAV_ITEMS: FlatNavEntry[] = [
  { label: DEVICE_ITEM.label, section: 'Top', path: DEVICE_ITEM.path },
  ...toFlatEntries('AI', AI_AGENT_ITEMS),
  ...TEST_GROUPS.flatMap((g) => toFlatEntries(`Test › ${g.sectionLabel}`, g.items)),
  { label: INTERFACE_ITEM.label, section: 'Top', path: INTERFACE_ITEM.path },
  ...toFlatEntries('Monitoring', MONITORING_ITEMS),
  ...toFlatEntries('Docs', DOCS_ITEMS),
  ...toFlatEntries('Plugins', INTEGRATIONS_ITEMS),
  ...toFlatEntries('Settings', CONFIGURATION_ITEMS),
];
