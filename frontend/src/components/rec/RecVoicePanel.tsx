import BlockIcon from '@mui/icons-material/Block';
import CheckIcon from '@mui/icons-material/Check';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import MicIcon from '@mui/icons-material/Mic';
import StopIcon from '@mui/icons-material/Stop';
import { Box, Button, FormControlLabel, Switch, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useDeviceVoice, VoicePhase } from '../../hooks/voice/useDeviceVoice';
import { useI18n } from '../../i18n/useI18n';
import { Device, Host } from '../../types/common/Host_Types';
import { dangerButtonSx, neutralButtonSx, primaryButtonSx } from '../common/PageChrome';
import { RecOverlayPanel } from './RecOverlayPanel';

interface RecVoicePanelProps {
  host: Host;
  device: Device;
  isControlActive: boolean;
  onClose: () => void;
}

const time = (at: number): string => new Date(at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

/**
 * Voice control of the device in Take Control (Actions > Voice). Continuous: say a command, hear it read back, see it
 * done. Stop closes the microphone and stops the device; Abort cancels the command being processed.
 */
export const RecVoicePanel: React.FC<RecVoicePanelProps> = ({ host, device, isControlActive, onClose }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const voice = useDeviceVoice(host, isControlActive ? device.device_id : null);

  const status: Record<VoicePhase, string> = {
    off: t('Microphone off'),
    listening: t('Listening…'),
    working: t('Working…'),
    speaking: t('Reading back…'),
  };
  const live = voice.phase !== 'off';

  return (
    <RecOverlayPanel title={`${t('Voice')} · ${device.device_name || device.device_id}`} onClose={onClose}>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }} aria-live="polite">
          <MicIcon fontSize="small" sx={{ color: live ? P.accentText : P.textMuted }} />
          <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: live ? P.textPrimary : P.textMuted, fontWeight: 600 }}>
            {status[voice.phase]}
          </Typography>
          {voice.interim && (
            <Typography noWrap sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, minWidth: 0 }}>
              “{voice.interim}”
            </Typography>
          )}
        </Box>

        {!voice.supported && (
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.error }}>{t('This browser has no speech recognition')}</Typography>
        )}

        <Box sx={{ display: 'flex', gap: 0.75 }}>
          {voice.listening && voice.phase !== 'off' ? (
            <Button size="small" variant="outlined" startIcon={<StopIcon />} onClick={() => void voice.stop()} sx={{ ...dangerButtonSx(P), flex: 1 }}>
              {t('Stop')}
            </Button>
          ) : (
            <Button size="small" variant="contained" startIcon={<MicIcon />} disabled={!voice.supported} onClick={voice.start} sx={{ ...primaryButtonSx(P), flex: 1 }}>
              {t('Start listening')}
            </Button>
          )}
          <Button size="small" variant="outlined" startIcon={<BlockIcon />} onClick={() => void voice.abort()} sx={{ ...neutralButtonSx(P), flex: 1 }}>
            {t('Abort')}
          </Button>
        </Box>
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
          {t('Stop closes the microphone and stops the device. Abort cancels the command being processed.')}
        </Typography>

        <Box sx={{ display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 1.5, rowGap: 0.25 }}>
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{t('Heard')}</Typography>
          <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textPrimary, minHeight: 20 }}>{voice.current?.heard ? `“${voice.current.heard}”` : '—'}</Typography>
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{t('Sent')}</Typography>
          <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textPrimary, minHeight: 20 }}>{voice.current?.sent || '—'}</Typography>
        </Box>

        <Box sx={{ borderTop: `1px solid ${P.borderColor}`, pt: 1 }}>
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, mb: 0.5 }}>{t('Last 3 commands')}</Typography>
          {voice.history.length === 0 && <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textMuted }}>{t('Nothing yet')}</Typography>}
          {voice.history.map((h) => (
            <Box key={h.at} sx={{ display: 'flex', alignItems: 'center', gap: 0.75, py: 0.25 }}>
              {h.ok ? <CheckIcon fontSize="small" sx={{ color: P.textSecondary }} /> : <ErrorOutlineIcon fontSize="small" sx={{ color: P.error }} />}
              <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>{time(h.at)}</Typography>
              <Typography noWrap sx={{ fontSize: TYPOGRAPHY.body.size, color: h.ok ? P.textPrimary : P.error, minWidth: 0 }}>
                “{h.heard}” → {h.sent}
              </Typography>
            </Box>
          ))}
        </Box>

        {voice.error && <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.error }}>{voice.error}</Typography>}

        <Box sx={{ display: 'flex', gap: 2 }}>
          <FormControlLabel
            control={<Switch size="small" checked={voice.prefs.beep} onChange={(_, v) => voice.setPref('beep', v)} />}
            label={<Typography sx={{ fontSize: TYPOGRAPHY.caption.size }}>{t('Beep')}</Typography>}
          />
          <FormControlLabel
            control={<Switch size="small" checked={voice.prefs.speak} onChange={(_, v) => voice.setPref('speak', v)} />}
            label={<Typography sx={{ fontSize: TYPOGRAPHY.caption.size }}>{t('Read back')}</Typography>}
          />
        </Box>
      </Box>
    </RecOverlayPanel>
  );
};

export default RecVoicePanel;
