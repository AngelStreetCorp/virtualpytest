/**
 * Navbar configuration — single source of truth for the nav menu, the
 * Settings > Page Visibility table, and the Workspaces > Pages tab.
 *
 * The full route path (`NavigationItem.path`) is the universal visibility
 * key across all three layers — env-level (`VITE_NAV_*`), admin settings,
 * and per-workspace `hidden_pages`. No aliasing, no segment stripping.
 */
import {
  AccountTree as TreeIcon,
  Api as ApiIcon,
  Apps as AllIntegrationsIcon,
  Assessment as ReportsIcon,
  Assignment as RequirementIcon,
  Build as BuildIcon,
  BugReport as TestingIcon,
  BarChart as AnalyticsIcon,
  Campaign as CampaignIcon,
  CloudUpload as CodeDeployIcon,
  Dashboard as DashboardIcon,
  Extension as IntegrationIcon,
  GridView as HeatmapIcon,
  HelpOutline as FaqIcon,
  Insights as LangfuseIcon,
  Link as LinkIcon,
  LocalPostOffice as PostmanIcon,
  Memory as ModelIcon,
  NewReleases as ReleaseNoteIcon,
  PhotoLibrary as ScreenshotsIcon,
  PlayArrow as RunIcon,
  ReportProblem as BugIcon,
  RocketLaunch as AgentIcon,
  Science as TestIcon,
  Security as SecurityIcon,
  TrendingUp as CoverageIcon,
  Terminal as TerminalIcon,
  VideoLibrary as VideosIcon,
  Visibility as MonitorIcon,
  Warning as IncidentIcon,
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
    label: 'AI Queue',
    path: '/monitoring/ai-queue',
    icon: <DashboardIcon fontSize="small" />,
  },
  ...featureNavItems('monitoring'),
];

// ─── Docs ─────────────────────────────────────────────────────────────────────

export const DOCS_ITEMS: NavItem[] = [
  {
    label: 'Get Started',
    path: '/docs/get-started',
    icon: <RunIcon fontSize="small" />,
  },
  {
    label: 'Release Note',
    path: '/docs/release_note',
    icon: <ReleaseNoteIcon fontSize="small" />,
  },
  {
    label: 'FAQ',
    path: '/docs/faq',
    icon: <FaqIcon fontSize="small" />,
  },
  {
    label: 'Features',
    path: '/docs/features',
    icon: <TestingIcon fontSize="small" />,
  },
  {
    label: 'Bugs',
    path: '/docs/bugs',
    icon: <BugIcon fontSize="small" />,
  },
  {
    label: 'Integrations',
    path: '/docs/integrations',
    icon: <IntegrationIcon fontSize="small" />,
  },
  {
    label: 'User Guide',
    path: '/docs/user-guide',
    icon: <RequirementIcon fontSize="small" />,
  },
  {
    label: 'Technical Docs',
    path: '/docs/technical',
    icon: <BuildIcon fontSize="small" />,
  },
  {
    label: 'Security Reports',
    path: '/docs/security',
    icon: <SecurityIcon fontSize="small" />,
  },
  {
    label: 'API Reference',
    path: '/docs/api',
    icon: <ApiIcon fontSize="small" />,
  },
  {
    label: 'Screenshots',
    path: '/docs/screenshots',
    icon: <ScreenshotsIcon fontSize="small" />,
  },
  {
    label: 'Videos',
    path: '/docs/videos',
    icon: <VideosIcon fontSize="small" />,
  },
  ...featureNavItems('docs'),
];

// ─── Integrations (Plugins) ───────────────────────────────────────────────────
// Items here are static (label/path/icon). Runtime values such as the Slack
// URL or the conditional Langfuse external URL are applied in Navigation_Bar
// via `buildIntegrationsItems()`.

export const INTEGRATIONS_ITEMS: NavItem[] = [
  {
    label: 'Grafana',
    path: '/grafana-dashboard',
    icon: <DashboardIcon fontSize="small" />,
  },
  {
    label: 'Langfuse',
    path: '/langfuse-dashboard',
    icon: <LangfuseIcon fontSize="small" />,
  },
  {
    label: 'Postman',
    path: '/api/workspaces',
    icon: <PostmanIcon fontSize="small" />,
  },
  {
    label: 'Jira',
    path: '/integrations/jira',
    icon: <IntegrationIcon fontSize="small" />,
  },
  {
    label: 'TestRail',
    path: '/integrations/testrail',
    icon: <IntegrationIcon fontSize="small" />,
  },
  {
    label: 'Slack',
    path: '/integrations/slack',
    icon: <IntegrationIcon fontSize="small" />,
    external: true,
  },
  // The map of everything VirtualPyTest connects to, live and planned. The entries
  // above deep-link into one tool each; this one is the way in for a tool that has no
  // page of its own (the device farms, Appium, Playwright, the storage backends).
  {
    label: 'All integrations',
    path: '/docs/integrations',
    icon: <AllIntegrationsIcon fontSize="small" />,
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
 */
export function buildIntegrationsItems(params: {
  slackUrl: string;
  langfuseUrl?: string;
  testrailInstanceUrl?: string;
}): NavItem[] {
  return INTEGRATIONS_ITEMS.map((item) => {
    if (item.label === 'Slack') {
      return { ...item, href: params.slackUrl };
    }
    if (item.label === 'Langfuse' && params.langfuseUrl) {
      return { ...item, external: true, href: params.langfuseUrl };
    }
    if (item.label === 'TestRail' && params.testrailInstanceUrl) {
      return { ...item, externalHref: params.testrailInstanceUrl };
    }
    return item;
  });
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
    label: 'Code Deployment',
    path: '/configuration/code-deployment',
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
    icon: <TestingIcon fontSize="small" />,
  },
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
