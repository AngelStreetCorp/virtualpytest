import { Box, Typography } from '@mui/material';
import React, { useState } from 'react';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { profileShortName } from '../../../hooks/useDeviceFilters';
import { useProfileDevices } from '../../../hooks/useProfileDevices';
import { MonitorProfileCard } from '../../common/MonitorProfileCard';
import type { MonitorProfileInfo } from './plan';

/**
 * Every monitoring profile of this host: a one-line list on the left (the column sizes to its widest row)
 * and the shared profile card on the right.
 */
export const MonitorProfileCatalogue: React.FC<{ profiles: MonitorProfileInfo[] }> = ({ profiles }) => {
  const P = useAgentChatPalette();
  const counts = useProfileDevices();
  const [selected, setSelected] = useState<string>(profiles[0]?.name ?? '');
  const current = profiles.find((p) => p.name === selected) ?? profiles[0];
  if (!current) return null;
  return (
    <Box data-testid="monitor-profile-catalogue" sx={{ display: 'grid', gridTemplateColumns: 'max-content minmax(0, 1fr)', gap: 1.5, alignItems: 'start' }}>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
        {profiles.map((p) => {
          const on = p.name === current.name;
          return (
            <Box
              key={p.name}
              component="button"
              type="button"
              onClick={() => setSelected(p.name)}
              sx={{
                all: 'unset',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 1,
                px: 1,
                py: 0.5,
                borderRadius: 1,
                whiteSpace: 'nowrap',
                border: `1px solid ${on ? P.accent : P.borderColor}`,
                backgroundColor: on ? `${P.accent}26` : 'transparent',
                '&:hover': { backgroundColor: on ? `${P.accent}26` : P.hoverBg },
              }}
            >
              <Typography component="span" variant="caption" sx={{ color: P.textMuted, border: `1px solid ${P.borderColor}`, borderRadius: 0.5, px: 0.5 }}>
                {profileShortName(p.name)}
              </Typography>
              <Typography component="span" variant="body2" sx={{ color: on ? P.accentText : P.textPrimary }}>{p.title}</Typography>
              <Typography component="span" variant="caption" sx={{ color: P.textMuted, ml: 'auto', pl: 1 }}>{counts[p.name]?.length ?? 0}</Typography>
            </Box>
          );
        })}
      </Box>
      <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 1, backgroundColor: P.surface }}>
        <MonitorProfileCard profile={current.name} title={current.title} description={current.description} services={current.services} fluid />
      </Box>
    </Box>
  );
};
