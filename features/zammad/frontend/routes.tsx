/**
 * Zammad feature - frontend entry (docs/technical/FEATURES.md).
 * Imported by the vpt-features Vite plugin only when the feature is enabled, so with
 * DISABLED_FEATURES=zammad neither the page, the dialog nor their strings reach the bundle.
 */
import { BugReport as BugIcon } from '@mui/icons-material';
import React from 'react';

import type { FeatureDefinition } from '../../../frontend/src/config/features';
import { ReportIncidentHost } from './ReportIncidentHost';
import { isReportEnabled, openReportIncident } from './reportIncident';
import { ZammadMark } from './ZammadMark';
import SupportTicketsToggle from './SupportTicketsToggle';

const ZammadPage = React.lazy(() => import('./ZammadPage'));

const feature: FeatureDefinition = {
  routes: [
    { path: '/integrations/zammad', element: <ZammadPage /> },
  ],
  nav: [
    {
      // Plugins: Zammad is a third-party system VPT connects to, like GitLab / Jira / Slack.
      section: 'plugins',
      label: 'Zammad',
      path: '/integrations/zammad',
      icon: <ZammadMark fontSize={20} />,
    },
    {
      // An action, not a page: opens the dialog. Shown only while the Enabled switch is on.
      section: 'settings',
      label: 'Open a ticket',
      path: '/action/report-incident',
      icon: <BugIcon fontSize="small" />,
      onSelect: () => openReportIncident(),
      isVisible: isReportEnabled,
    },
  ],
  // The dialog lives in the host; core mounts it once under the providers.
  // The on/off switch lives in Settings -> Features -> Feature Toggles, not on the Zammad page.
  settingsToggles: [SupportTicketsToggle],
  appOverlays: [ReportIncidentHost],
  translations: {
    fr: () => import('./locales/fr.json'),
    de: () => import('./locales/de.json'),
  },
};

export default feature;
