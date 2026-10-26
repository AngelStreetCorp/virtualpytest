/** Live results | Screens taught switch for the Localize monitoring page; sits at the right of the page title. */
import { Box, ToggleButton, ToggleButtonGroup } from '@mui/material';
import React from 'react';
import { useSearchParams } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { segmentedSx } from '../common/PageChrome';

export type LocalizeTab = 'matches' | 'coverage';

export const useLocalizeTab = (): LocalizeTab => {
  const [params] = useSearchParams();
  return params.get('tab') === 'coverage' ? 'coverage' : 'matches';
};

export const LocalizeTabs: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [, setParams] = useSearchParams();
  const tab = useLocalizeTab();
  return (
    <ToggleButtonGroup
      size="small"
      exclusive
      value={tab}
      onChange={(_, v: LocalizeTab | null) => v && setParams({ tab: v }, { replace: true })}
      sx={segmentedSx(P)}
    >
      <ToggleButton value="matches">{t('Live results')}</ToggleButton>
      <ToggleButton value="coverage">{t('Screens taught')}</ToggleButton>
    </ToggleButtonGroup>
  );
};

/** Page subtitle shared by both tabs: what Localize is (once), then what this tab answers. */
export const LocalizeIntro: React.FC<{ answers: string }> = ({ answers }) => {
  const { t } = useI18n();
  return (
    <>
      <Box component="span" sx={{ display: 'block' }}>
        {t("Localize looks at a device's screen and names which screen of its app it is on, so tests can start from anywhere.")}
      </Box>
      <Box component="span" sx={{ display: 'block' }}>{answers}</Box>
    </>
  );
};
