import React from 'react';
import { Box, CircularProgress, Typography } from '@mui/material';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { profileTitle, type MonitorProfileInfo, type MonitorProfileStatus } from './plan';
import { TYPOGRAPHY } from '../../../constants/typography';

interface Props {
  status: MonitorProfileStatus;
  profiles: MonitorProfileInfo[];
  applying: boolean;
}

/** Saved vs running profile per device, and what the last apply did. Colour + icon + word, never colour alone. */
export const MonitorProfileStatusCard: React.FC<Props> = ({ status, profiles, applying }) => {
  const P = useAgentChatPalette();
  const result = status.result;
  const mono = { fontFamily: 'monospace', fontSize: TYPOGRAPHY.body.size } as const;
  const line = (icon: React.ReactNode, color: string, text: React.ReactNode, key: string) => (
    <Box key={key} sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.75, color }}>
      <Box sx={{ display: 'flex', mt: '2px' }}>{icon}</Box>
      <Typography variant="body2" sx={{ color }}>{text}</Typography>
    </Box>
  );
  const names = (units: string[]) => units.map((u) => <span key={u} style={mono}>{u} </span>);
  const devices = Object.keys(status.saved);
  return (
    <Box data-testid="monitor-profile-status" sx={{ minHeight: 56 }}>
      <Typography variant="caption" sx={{ color: P.textMuted }}>Monitoring profiles on this host</Typography>
      <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 1, mt: 0.5 }}>
        {devices.map((d, i) => {
          const running = status.applied?.[d];
          const mismatch = status.mismatch.includes(d);
          return (
            <Box key={d} sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1.5, py: 0.75, flexWrap: 'wrap',
              borderBottom: i < devices.length - 1 ? `1px solid ${P.borderColor}` : 0 }}>
              <span style={{ ...mono, minWidth: 72 }}>{d}</span>
              <Typography variant="body2">{profileTitle(status.saved[d], profiles)}</Typography>
              {mismatch ? (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, color: P.warning }}>
                  <WarningAmberIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
                  <Typography variant="body2" sx={{ color: P.warning }}>
                    Saved, running {running ? profileTitle(running, profiles) : 'unknown'}
                  </Typography>
                </Box>
              ) : (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, color: P.success }}>
                  <CheckCircleOutlineIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
                  <Typography variant="body2" sx={{ color: P.success }}>Running</Typography>
                </Box>
              )}
            </Box>
          );
        })}
      </Box>

      <Box sx={{ mt: 1, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
        {applying && line(<CircularProgress size={14} />, P.textSecondary, 'Applying: restarting the monitor services…', 'applying')}
        {!applying && result?.state === 'done' && (
          <>
            {result.error && line(<ErrorOutlineIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />, P.error, `Failed: ${result.error}`, 'err')}
            {!!result.restarted?.length && line(<CheckCircleOutlineIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />, P.success,
              <>Restarted {names(result.restarted)}</>, 'ok')}
            {!!result.failed?.length && line(<ErrorOutlineIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />, P.error,
              <>Restart failed for {names(result.failed)}; it is retried at the next save</>, 'failed')}
            {!!result.not_running?.length && line(<WarningAmberIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />, P.warning,
              <>{names(result.not_running)} not running on this host, so not restarted. It picks the profile up when started</>, 'idle')}
            {(result.fallbacks ?? []).map((f) => line(<WarningAmberIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />, P.warning,
              <><span style={mono}>{f.device}</span> asks for <span style={mono}>{f.requested}</span> but {f.reason}
                {f.kind === 'model_missing' ? ': left out of monitoring until it is there' : `: runs as ${f.effective}`}</>, `fb-${f.device}`))}
            {!result.error && !result.restarted?.length && !result.failed?.length && !result.not_running?.length
              && line(<CheckCircleOutlineIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />, P.textSecondary, 'Nothing needed a restart', 'none')}
          </>
        )}
      </Box>
    </Box>
  );
};
