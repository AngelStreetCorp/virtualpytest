import { Box, Tooltip } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { FONT_SIZE_SCALE } from '../../constants/typography';
import { profileShortName } from '../../hooks/useDeviceFilters';
import { MonitorProfileCard } from '../common/MonitorProfileCard';

/**
 * Short outline tag naming the monitoring profile a device runs (TASK-90), so tiles that
 * share a model can be told apart. Lives in a header row (tile header, stream modal),
 * muted so the device name and the favourite star stay the loudest things there.
 * Hovering shows the shared profile card directly (description, services with their units,
 * collapsed device list), no click needed. Colours come from the active theme, never a fixed hex.
 */
export const MonitorProfileBadge: React.FC<{ profile?: string | null; services?: Record<string, boolean> }> = ({ profile, services }) => {
  const P = useAgentChatPalette();
  if (!profile) return null;
  return (
    <Tooltip
      title={<MonitorProfileCard profile={profile} services={services} />}
      arrow
      placement="bottom"
      enterDelay={250}
      componentsProps={{
        tooltip: { sx: { p: 0, maxWidth: 'none', backgroundColor: P.surfaceSolid, color: P.textPrimary, border: `1px solid ${P.borderColor}`, boxShadow: '0 8px 24px rgba(0, 0, 0, 0.35)' } },
        arrow: { sx: { color: P.surfaceSolid } },
      }}
    >
      <Box
        data-testid="monitor-profile-badge"
        component="span"
        sx={{
          flexShrink: 0,
          px: 0.625,
          borderRadius: 0.5,
          border: `1px solid ${P.borderColor}`,
          color: P.textMuted,
          fontSize: FONT_SIZE_SCALE.xxs,
          fontWeight: 500,
          lineHeight: 1.4,
          whiteSpace: 'nowrap',
        }}
      >
        {profileShortName(profile)}
      </Box>
    </Tooltip>
  );
};
