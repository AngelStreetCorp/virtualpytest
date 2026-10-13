/**
 * Quality: one page, three tabs (flaky, slow, not executed in window). The tab lives in
 * the URL (`/test-results/quality?tab=slow`); the old per-insight URLs redirect here.
 * Each tab body keeps its own window selector (`window` URL param), reset on tab change
 * because the default window differs per tab.
 */

import { Box, ToggleButton, ToggleButtonGroup } from '@mui/material';
import React from 'react';
import { useSearchParams } from 'react-router-dom';

import { PageTitle, pageSurfaceSx, segmentedSx } from '../components/common/PageChrome';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { useI18n } from '../i18n/useI18n';
import { QUALITY_TABS, type QualityTab } from '../types/reports';
import FlakyTests from './FlakyTests';
import NeverExecuted from './NeverExecuted';
import SlowTests from './SlowTests';

type Translate = ReturnType<typeof useI18n>['t'];

const buildTabs = (t: Translate): Array<{ key: QualityTab; label: string }> => [
  { key: 'flaky', label: t('Flaky') },
  { key: 'slow', label: t('Slow') },
  { key: 'not-executed', label: t('Not executed') },
];

const isTab = (value: string | null): value is QualityTab => (QUALITY_TABS as readonly string[]).includes(value ?? '');

const Quality: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get('tab');
  const tab: QualityTab = isTab(raw) ? raw : 'flaky';

  const selectTab = (next: QualityTab | null) => {
    if (!next || next === tab) return;
    setSearchParams({ tab: next }, { replace: true });
  };

  return (
    <Box sx={{ ...(pageSurfaceSx(P) as object), py: 2, px: { xs: 1, sm: 0 }, minWidth: 0 }}>
      <PageTitle
        title={t('Quality')}
        subtitle={t('Which tests are flaky, slow or not run, over a time window')}
        right={
          <ToggleButtonGroup
            exclusive
            size="small"
            value={tab}
            onChange={(_, next) => selectTab(next)}
            sx={segmentedSx(P)}
            aria-label={t('Quality view')}
          >
            {buildTabs(t).map(({ key, label }) => (
              <ToggleButton key={key} value={key} data-testid={`quality-tab-${key}`}>
                {label}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        }
      />
      {tab === 'flaky' && <FlakyTests />}
      {tab === 'slow' && <SlowTests />}
      {tab === 'not-executed' && <NeverExecuted />}
    </Box>
  );
};

export default Quality;
