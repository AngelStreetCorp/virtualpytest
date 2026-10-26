import { Box, Typography } from '@mui/material';
import React, { useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { AppIcon } from '../../constants/icons';
import { FONT_SIZE_SCALE } from '../../constants/typography';
import { useProfileDevices } from '../../hooks/useProfileDevices';
import { PROFILE_SERVICES, profileOneLiner, profileServicesFallback, profileTitle } from '../../utils/monitorProfileInfo';

interface Props {
  profile: string;
  /** Host-supplied title and description (Settings has them); fall back to the built-in names. */
  title?: string;
  description?: string;
  /** {img|audio|subtitle|archiver|kpi|avq: bool}; omitted when the host does not report them. */
  services?: Record<string, boolean>;
  /** Fill the parent (Settings). Default: size to the widest line, every line on one line (hover card). */
  fluid?: boolean;
}

/**
 * What a monitoring profile is: title, one line, a badge per service (accent = on, muted = off) with what it does
 * and its real systemd unit, and a collapsed list of the devices using it. Shared by the badge hover card and Settings.
 */
export const MonitorProfileCard: React.FC<Props> = ({ profile, title, description, services: reported, fluid = false }) => {
  const P = useAgentChatPalette();
  const services = reported ?? profileServicesFallback(profile);
  const [showDevices, setShowDevices] = useState(false);
  const devices = useProfileDevices()[profile] ?? [];
  const mono = { fontFamily: 'monospace', fontSize: FONT_SIZE_SCALE.xs } as const;
  const rows = services ? PROFILE_SERVICES.filter((s) => s.key in services) : [];
  return (
    <Box data-testid="monitor-profile-card" sx={{ px: 1.75, py: 1.5, width: fluid ? '100%' : 'max-content', maxWidth: '90vw' }}>
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.75 }}>
        <Typography variant="subtitle2" noWrap sx={{ color: P.textPrimary }}>{title || profileTitle(profile)}</Typography>
        <Typography component="span" sx={{ color: P.textMuted, ...mono }}>- {profile}</Typography>
      </Box>
      <Typography variant="caption" noWrap={!fluid} display="block" sx={{ color: P.textSecondary, mb: rows.length ? 1.25 : 0 }}>
        {description || profileOneLiner(profile)}
      </Typography>
      {rows.length > 0 && (
        <Box sx={{ display: 'grid', gridTemplateColumns: 'max-content 1fr max-content', columnGap: 1.25, rowGap: 0.5, alignItems: 'center' }}>
          {rows.map((s) => {
            const on = services?.[s.key];
            return (
              <React.Fragment key={s.key}>
                <Typography
                  component="span"
                  sx={{
                    justifySelf: 'start',
                    px: 0.75,
                    borderRadius: 999,
                    fontSize: FONT_SIZE_SCALE.xxs,
                    lineHeight: 1.5,
                    color: on ? P.accentText : P.textMuted,
                    border: `1px solid ${on ? P.accent : P.borderColor}`,
                    backgroundColor: on ? `${P.accent}1f` : 'transparent',
                  }}
                >
                  {s.label}
                </Typography>
                <Typography variant="caption" noWrap={!fluid} sx={{ color: P.textMuted }}>{on ? s.does : ''}</Typography>
                <Typography component="span" sx={{ color: P.textMuted, justifySelf: 'end', ...mono }}>{s.unit}</Typography>
              </React.Fragment>
            );
          })}
        </Box>
      )}
      <Box sx={{ borderTop: `1px solid ${P.borderColor}`, pt: 1, mt: 1.25 }}>
        <Box
          component="button"
          type="button"
          onClick={() => setShowDevices((v) => !v)}
          aria-expanded={showDevices}
          sx={{ all: 'unset', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 0.5, color: P.accentText }}
        >
          <AppIcon name={showDevices ? 'expand' : 'chevron'} />
          <Typography variant="caption" sx={{ color: 'inherit' }}>
            {devices.length === 1 ? '1 device' : `${devices.length} devices`}
          </Typography>
        </Box>
        {showDevices && (
          // width 0 + minWidth 100%: the chips wrap inside the width the other lines set instead of widening the card
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.75, maxHeight: 96, overflowY: 'auto', ...(fluid ? {} : { width: 0, minWidth: '100%' }) }}>
            {devices.map((d) => (
              <Typography key={d} variant="caption" sx={{ color: P.textSecondary, border: `1px solid ${P.borderColor}`, borderRadius: 0.5, px: 0.5, whiteSpace: 'nowrap' }}>{d}</Typography>
            ))}
          </Box>
        )}
      </Box>
    </Box>
  );
};
