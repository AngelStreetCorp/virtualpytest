/**
 * Run Management: the TASK-42 bookkeeping pages as one page with tabs — run groups,
 * milestones, labels, defects, custom reports and manual runs. The tab lives in the URL
 * (`/test-results/run-management?tab=labels`); the old list URLs redirect here, and the
 * detail pages (a group, a milestone, a manual session) keep their own URLs.
 *
 * Each tab opens with one muted sentence saying what it is for.
 */

import { Box, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import React from 'react';
import { useSearchParams } from 'react-router-dom';

import { PageTitle, pageSurfaceSx, segmentedSx } from '../components/common/PageChrome';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { useReportPermissions } from '../hooks/reports/useRunManagement';
import { useI18n } from '../i18n/useI18n';
import { RUN_MANAGEMENT_TABS, type RunManagementTab } from '../types/reports';
import CustomReportBuilder from './CustomReportBuilder';
import Defects from './Defects';
import ManualRun from './ManualRun';
import Milestones from './Milestones';
import RunGroups from './RunGroups';
import RunLabels from './RunLabels';
import { TYPOGRAPHY } from '../constants/typography';

type Translate = ReturnType<typeof useI18n>['t'];

const buildTabs = (t: Translate): Array<{ key: RunManagementTab; label: string; help: string; body: React.FC }> => [
  {
    key: 'groups',
    label: t('Groups'),
    help: t('A folder of finished runs showing the latest result per test, with Rerun failures.'),
    body: RunGroups,
  },
  {
    key: 'milestones',
    label: t('Milestones'),
    help: t('A dated target (e.g. a release) you attach runs to, to see what was tested for it.'),
    body: Milestones,
  },
  {
    key: 'labels',
    label: t('Labels'),
    help: t('Free tags you put on runs (e.g. nightly, hotfix) to filter Test Reports.'),
    body: RunLabels,
  },
  {
    key: 'defects',
    label: t('Defects'),
    help: t('Bugs found by runs, tracked here and optionally pushed to Jira.'),
    body: Defects,
  },
  {
    key: 'custom-reports',
    label: t('Custom reports'),
    help: t('Saved Test Reports filters you can reopen and export to CSV.'),
    body: CustomReportBuilder,
  },
  {
    key: 'manual',
    label: t('Manual runs'),
    help: t("A person walks a test case's steps on a device and marks each step pass or fail; the result appears in Test Reports."),
    body: ManualRun,
  },
];

const isTab = (value: string | null): value is RunManagementTab =>
  (RUN_MANAGEMENT_TABS as readonly string[]).includes(value ?? '');

const RunManagement: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { canRunManual } = useReportPermissions();
  const [searchParams, setSearchParams] = useSearchParams();

  // Manual runs need their own permission; without it the tab is not offered.
  const tabs = buildTabs(t).filter((tab) => tab.key !== 'manual' || canRunManual);
  const raw = searchParams.get('tab');
  const current = tabs.find((tab) => isTab(raw) && tab.key === raw) ?? tabs[0];

  const selectTab = (next: RunManagementTab | null) => {
    if (!next || next === current.key) return;
    setSearchParams({ tab: next }, { replace: true });
  };

  const Body = current.body;
  return (
    <Box sx={{ ...(pageSurfaceSx(P) as object), py: 2, px: { xs: 1, sm: 0 }, minWidth: 0 }}>
      <PageTitle
        title={t('Run Management')}
        subtitle={t('Organise finished runs: group, tag, track bugs, save reports, run tests by hand')}
        right={
          <ToggleButtonGroup
            exclusive
            size="small"
            value={current.key}
            onChange={(_, next) => selectTab(next)}
            sx={{ ...(segmentedSx(P) as object), flexWrap: 'wrap' }}
            aria-label={t('Run management view')}
          >
            {tabs.map(({ key, label }) => (
              <ToggleButton key={key} value={key} data-testid={`run-management-tab-${key}`}>
                {label}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        }
      />
      <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textSecondary, mb: 2 }} data-testid="run-management-help">
        {current.help}
      </Typography>
      <Body key={current.key} />
    </Box>
  );
};

export default RunManagement;
