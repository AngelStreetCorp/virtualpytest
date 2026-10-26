import { Box } from '@mui/material';
import React from 'react';

import { PageTitle, StatTiles, pageSurfaceSx } from '../../../../frontend/src/components/common/PageChrome';
import { useAgentChatPalette } from '../../../../frontend/src/constants/agentChatTheme';
import { useI18n } from '../../../../frontend/src/i18n/useI18n';
import { useEnabledMods } from '../../../../frontend/src/mods/core/hooks/useEnabledMods';

import { ModCard } from './components/ModCard';

/** Settings > Mods: every installed mod, each switched on or off by this user. */
const ModsPage: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { installed, enabled, isEnabled, setEnabled } = useEnabledMods();

  return (
    <Box sx={pageSurfaceSx(P)}>
      <PageTitle
        title={t('Mods')}
        subtitle={t('Customize your experience with mods')}
      />
      <StatTiles
        centered
        tiles={[
          { label: t('Installed'), value: installed.length },
          { label: t('On'), value: enabled.length, color: enabled.length ? P.success : P.textMuted },
        ]}
      />
      <Box sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, mt: 2 }}>
        {installed.map((mod) => (
          <ModCard key={mod.id} mod={mod} enabled={isEnabled(mod.id)} onToggle={(on) => setEnabled(mod.id, on)} />
        ))}
      </Box>
    </Box>
  );
};

export default ModsPage;
