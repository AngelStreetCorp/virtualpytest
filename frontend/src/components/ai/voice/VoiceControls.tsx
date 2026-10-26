/**
 * Atlas voice controls (TASK-140), used by Ask AI (AICommandBar) and the Atlas chat input (ChatInput):
 *  - VoiceMessageButton: mic, records one voice message;
 *  - VoiceConversationButton: the "Voice" / "End" pill, continuous conversation;
 *  - VoiceRecordBar: replaces the input while recording (cancel · waveform · stop to edit · send);
 *  - VoiceStrip: shown during a conversation (state, live words, Stop, mode, speak toggles).
 */

import React, { useEffect, useRef, useState } from 'react';
import { Box, Button, IconButton, Popover, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material';
import {
  ArrowUpward as SendUpIcon,
  Close as CloseIcon,
  GraphicEq as VoiceIcon,
  Mic as MicIcon,
  Stop as StopIcon,
  Tune as TuneIcon,
} from '@mui/icons-material';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../../constants/typography';
import { dangerButtonSx, segmentedSx, toggleSx } from '../../common/PageChrome';
import { useVoice, VoiceCmdModel, VoicePhase, VoicePipeline, VoiceSpeed, VoiceSurface } from '../../../contexts/VoiceContext';
import { useI18n } from '../../../i18n/useI18n';
import { api } from '../../../utils/apiClient';
import { buildServerUrl } from '../../../utils/buildUrlUtils';
import { useMicLevel } from '../../../lib/voice/useMicLevel';

const PULSE = {
  '@keyframes voicePulse': {
    '0%': { boxShadow: '0 0 0 0 rgba(128,128,128,.45)' },
    '70%': { boxShadow: '0 0 0 10px rgba(128,128,128,0)' },
    '100%': { boxShadow: '0 0 0 0 rgba(128,128,128,0)' },
  },
  '@media (prefers-reduced-motion: reduce)': { animation: 'none !important' },
};

/** Mic: record one voice message. */
export const VoiceMessageButton: React.FC<{ surface: VoiceSurface; size?: number }> = ({ surface, size = 34 }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const voice = useVoice();
  const busy = voice.phase === 'recording' || voice.conversation;
  return (
    <Tooltip title={voice.supported ? t('Voice message') : t('Voice needs Chrome, Edge or Safari')}>
      <span>
        <IconButton
          aria-label={t('Record a voice message')}
          disabled={!voice.supported || busy}
          onClick={() => voice.startMessage(surface)}
          sx={{ width: size, height: size, color: P.accentText, border: '1px solid', borderColor: `${P.accent}66`, '&:hover': { bgcolor: P.hoverBg } }}
        >
          <MicIcon sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} />
        </IconButton>
      </span>
    </Tooltip>
  );
};

/** The "Voice" pill: start / end a voice conversation. */
export const VoiceConversationButton: React.FC<{ surface: VoiceSurface; compact?: boolean }> = ({ surface, compact }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const voice = useVoice();
  const on = voice.conversation;
  const label = on ? t('End') : t('Voice');
  return (
    <Tooltip title={voice.supported ? (on ? t('End the voice conversation') : t('Talk with Atlas')) : t('Voice needs Chrome, Edge or Safari')}>
      <span>
        <Button
          aria-label={on ? t('End the voice conversation') : t('Start a voice conversation')}
          aria-pressed={on}
          disabled={!voice.supported || voice.phase === 'recording'}
          onClick={() => (on ? voice.endConversation() : voice.startConversation(surface))}
          startIcon={<VoiceIcon />}
          sx={{
            ...PULSE,
            minWidth: 0,
            height: compact ? 32 : 36,
            px: compact ? 1.25 : 1.75,
            borderRadius: 999,
            textTransform: 'none',
            fontWeight: 700,
            fontSize: TYPOGRAPHY.body.size,
            bgcolor: P.accent,
            color: P.onAccent,
            boxShadow: 'none',
            animation: on && voice.phase === 'listening' ? 'voicePulse 1.6s infinite' : 'none',
            '&:hover': { bgcolor: P.accentHover, boxShadow: 'none' },
            '&.Mui-disabled': { bgcolor: P.hoverBg, color: P.textMuted },
          }}
        >
          {label}
        </Button>
      </span>
    </Tooltip>
  );
};

const DOTS = 56;

/** Replaces the input while a voice message records. */
export const VoiceRecordBar: React.FC<{ onEdit: (text: string) => void; onSend: (text: string) => void; height?: number }> = ({
  onEdit,
  onSend,
  height = 52,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const voice = useVoice();
  const level = useMicLevel(voice.phase === 'recording');
  const [history, setHistory] = useState<number[]>(() => Array(DOTS).fill(0));
  useEffect(() => { setHistory((h) => [...h.slice(1), level]); }, [level]);

  const ring = { width: height - 12, height: height - 12, border: '1px solid', borderColor: P.borderColor, color: P.textPrimary };
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%', height, px: 0.75 }}>
      <Tooltip title={t('Cancel')}>
        <IconButton aria-label={t('Cancel the recording')} onClick={voice.cancelMessage} sx={ring}>
          <CloseIcon sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} />
        </IconButton>
      </Tooltip>
      <Box aria-hidden sx={{ flex: 1, minWidth: 0, height: 24, display: 'flex', alignItems: 'center', justifyContent: 'space-between', px: 1, overflow: 'hidden' }}>
        {history.map((v, i) => (
          <Box
            key={i}
            sx={{
              width: 4,
              height: Math.max(4, Math.round(4 + v * 18)),
              borderRadius: 2,
              bgcolor: v > 0.04 ? P.textPrimary : P.textMuted,
              opacity: 0.35 + (0.65 * i) / DOTS,
              flexShrink: 0,
            }}
          />
        ))}
      </Box>
      <Typography sx={{ display: { xs: 'none', sm: 'block' }, maxWidth: '40%', color: P.textSecondary, fontSize: TYPOGRAPHY.caption.size, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {voice.interim}
      </Typography>
      <Tooltip title={t('Stop and edit the text')}>
        <IconButton aria-label={t('Stop and edit the text')} onClick={async () => onEdit(await voice.stopMessage())} sx={ring}>
          <StopIcon sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} />
        </IconButton>
      </Tooltip>
      <Tooltip title={t('Send')}>
        <IconButton
          aria-label={t('Send the voice message')}
          onClick={async () => { const text = await voice.stopMessage(); await voice.dispatch(text, onSend); }}
          sx={{ width: height - 8, height: height - 8, bgcolor: P.accent, color: P.onAccent, '&:hover': { bgcolor: P.accentHover } }}
        >
          <SendUpIcon />
        </IconButton>
      </Tooltip>
    </Box>
  );
};

/** Under the input during a voice conversation. */
export const VoiceStrip: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const voice = useVoice();
  const level = useMicLevel(voice.conversation && voice.phase === 'listening');
    const stopped = voice.phase === 'stopped';
  const phaseLabel: Record<VoicePhase, string> = {
    off: t('Voice off'),
    recording: t('Recording…'),
    listening: t('Listening…'),
    working: t('Atlas is working…'),
    speaking: t('Speaking…'),
    stopped: t('Stopped'),
  };
  const line = voice.interim
    || (voice.phase === 'speaking' || voice.phase === 'listening' ? voice.lastReply : '')
    || (voice.phase === 'listening' ? t('Say a command, for example “show me the devices page”') : '');

  return (
    <Box sx={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 1, p: 1.25, borderRadius: 2, bgcolor: P.surfaceSolid, border: '1px solid', borderColor: stopped ? P.dangerText : P.accent }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
        <Box
          role="status"
          sx={{
            flexShrink: 0, height: 28, px: 1.25, display: 'flex', alignItems: 'center', borderRadius: 999,
            border: '1px solid', borderColor: stopped ? P.dangerText : P.accent, color: stopped ? P.dangerText : P.accentText,
            fontSize: TYPOGRAPHY.caption.size, fontWeight: 600, whiteSpace: 'nowrap',
          }}
        >
          {phaseLabel[voice.phase]}
        </Box>
        <Typography sx={{ flex: 1, minWidth: 0, color: voice.interim ? P.textPrimary : P.textSecondary, fontSize: TYPOGRAPHY.body.size, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {line}
        </Typography>
        {voice.phase === 'listening' && (
          <Box aria-hidden sx={{ display: 'flex', gap: '3px', alignItems: 'center', height: 20 }}>
            {[0.6, 1, 0.75, 0.9].map((k, i) => (
              <Box key={i} sx={{ width: 3, height: Math.max(4, Math.round(20 * Math.min(1, level * k * 1.6))), bgcolor: P.accent, borderRadius: 1 }} />
            ))}
          </Box>
        )}
        <Button size="small" variant="outlined" startIcon={<StopIcon />} onClick={voice.abort} sx={{ ...dangerButtonSx(P), flexShrink: 0, textTransform: 'none' }}>
          {t('Stop')}
        </Button>
      </Box>
      <Box sx={{ pt: 1, borderTop: '1px solid', borderColor: P.borderColor, display: 'flex', flexDirection: 'column', gap: 1 }}>
        <VoiceSettingsBody />
        <VoiceCommandLine />
        <Typography sx={{ color: P.textSecondary, fontSize: TYPOGRAPHY.caption.size }}>{t('Say “stop” to abort')}</Typography>
      </Box>
    </Box>
  );
};

/** Mode, what is spoken, and the test choices: how a command reaches Atlas, which model, voice speed. */
const VoiceSettingsBody: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const voice = useVoice();
  const inter = voice.prefs.mode === 'interactive';
  const fast = voice.prefs.pipeline === 'audio';
  const [quick, setQuick] = useState<string[] | null>(null);
  useEffect(() => {
    let alive = true;
    api.get(buildServerUrl('/server/agent/quick/tools'))
      .then((d: { success?: boolean; tools?: string[] }) => { if (alive && d?.success) setQuick(d.tools ?? []); })
      .catch(() => { if (alive) setQuick(null); });
    return () => { alive = false; };
  }, []);
  const label = (text: string) => (
    <Typography sx={{ color: P.textSecondary, fontSize: TYPOGRAPHY.caption.size, minWidth: 96 }}>{text}</Typography>
  );
  const row = { display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' } as const;
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
      <Box sx={row}>
        {label(t('Mode'))}
        <ToggleButtonGroup exclusive size="small" value={voice.prefs.mode} onChange={(_, m) => { if (m) voice.setMode(m); }}
          aria-label={t('Voice mode')} sx={segmentedSx(P, 'sm')}>
          <ToggleButton value="silent">{t('Silent')}</ToggleButton>
          <ToggleButton value="interactive">{t('Interactive')}</ToggleButton>
        </ToggleButtonGroup>
      </Box>
      <Box sx={row}>
        {label(t('Speak'))}
        {(['answer', 'thinking', 'questions'] as const).map((k) => (
          <Button key={k} size="small" variant="outlined" disabled={!inter} aria-pressed={voice.prefs.speak[k]}
            onClick={() => voice.toggleSpeak(k)}
            sx={{ ...toggleSx(P, voice.prefs.speak[k]), textTransform: 'none', minWidth: 0, py: 0.25 }}>
            {k === 'answer' ? t('Answer') : k === 'thinking' ? t('Thinking') : t('Questions')}
          </Button>
        ))}
      </Box>
      <Box sx={row}>
        {label(t('Voice speed'))}
        <ToggleButtonGroup exclusive size="small" value={voice.prefs.speed}
          onChange={(_, v: VoiceSpeed | null) => { if (v) voice.setPref('speed', v); }} aria-label={t('Voice speed')} sx={segmentedSx(P, 'sm')}>
          <ToggleButton value={1.2}>1.2×</ToggleButton>
          <ToggleButton value={1.5}>1.5×</ToggleButton>
          <ToggleButton value={2}>2×</ToggleButton>
        </ToggleButtonGroup>
      </Box>
      <Box sx={{ borderTop: '1px solid', borderColor: P.borderColor, pt: 1.25, display: 'flex', flexDirection: 'column', gap: 1.25 }}>
        <Box sx={row}>
          {label(t('Command path'))}
          <ToggleButtonGroup exclusive size="small" value={voice.prefs.pipeline}
            onChange={(_, v: VoicePipeline | null) => { if (v) voice.setPref('pipeline', v); }} aria-label={t('Command path')} sx={segmentedSx(P, 'sm')}>
            <ToggleButton value="atlas">{t('Words → Atlas')}</ToggleButton>
            <ToggleButton value="audio">{t('Audio → Atlas')}</ToggleButton>
          </ToggleButtonGroup>
          {fast && (
            <ToggleButtonGroup exclusive size="small" value={voice.prefs.cmdModel}
              onChange={(_, v: VoiceCmdModel | null) => { if (v) voice.setPref('cmdModel', v); }} aria-label={t('Model')} sx={segmentedSx(P, 'sm')}>
              <ToggleButton value="voxtral">Voxtral Small</ToggleButton>{/* i18n-ignore product name */}
              <ToggleButton value="gemini-lite">Gemini 3.5 Flash-Lite</ToggleButton>{/* i18n-ignore product name */}
            </ToggleButtonGroup>
          )}
        </Box>
        <Box sx={{ ...row, alignItems: 'flex-start' }}>
          {label(t('Quick commands'))}
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, flex: 1, minWidth: 0 }}>
            {quick === null && <Typography sx={{ color: P.textSecondary, fontSize: TYPOGRAPHY.caption.size }}>{t('not available')}</Typography>}
            {quick?.map((q) => (
              <Box key={q} sx={{ px: 1, py: 0.25, borderRadius: 999, border: '1px solid', borderColor: P.borderColor, color: P.textPrimary,
                fontSize: TYPOGRAPHY.caption.size, fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                {q}
              </Box>
            ))}
          </Box>
        </Box>
      </Box>
    </Box>
  );
};

/** Gear next to the mic: the voice settings in a popover. */
export const VoiceSettingsButton: React.FC<{ size?: number }> = ({ size = 34 }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  return (
    <>
      <Tooltip title={t('Voice settings')}>
        <IconButton ref={anchor} aria-label={t('Voice settings')} onClick={() => setOpen(true)}
          sx={{ width: size, height: size, color: P.textSecondary, '&:hover': { bgcolor: P.hoverBg } }}>
          <TuneIcon sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} />
        </IconButton>
      </Tooltip>
      <Popover open={open} anchorEl={anchor.current} onClose={() => setOpen(false)}
        anchorOrigin={{ vertical: 'top', horizontal: 'right' }} transformOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        sx={{ zIndex: 10001 }}
        slotProps={{ paper: { sx: { p: 2, width: 460, bgcolor: P.surfaceSolid, border: '1px solid', borderColor: P.borderColor, maxWidth: 'calc(100vw - 32px)' } } }}>
        <VoiceSettingsBody />
      </Popover>
    </>
  );
};

/** What the last fast-path command did, with model, time and cost, to compare the two models. */
export const VoiceCommandLine: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { lastCommand: c } = useVoice();
  if (!c) return null;
  const what = c.tool ? `${c.tool}${c.args && Object.keys(c.args).length ? ` ${Object.values(c.args).map(String).join(' ')}` : ''}` : '';
  const result = { hint: t('sent to Atlas to run'), abort: t('stopped'), atlas: t('sent to Atlas'), drone: t('drone command'), error: t('error') }[c.result];
  const bad = c.result === 'error';
  const parts = [
    c.pipeline === 'audio' ? t('audio') : t('text'),
    c.model === 'gemini-lite' ? 'Gemini 3.5 Flash-Lite' : 'Voxtral Small',
    c.latencyMs !== undefined ? `${(c.latencyMs / 1000).toFixed(2)} s` : '',
    c.costUsd !== undefined ? `$${c.costUsd.toFixed(5)}` : '',
  ].filter(Boolean).join(' · ');
  return (
    <Typography sx={{ color: bad ? P.dangerText : P.textSecondary, fontSize: TYPOGRAPHY.caption.size, fontFamily: 'monospace', overflowWrap: 'anywhere' }}>
      {what ? `${what} → ` : ''}{result}{c.detail ? ` (${c.detail.slice(0, 120)})` : ''} · {parts}
    </Typography>
  );
};

/** One line under the input when the mic is unavailable. */
export const VoiceError: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { error } = useVoice();
  if (!error) return null;
  return (
    <Typography role="alert" sx={{ color: P.dangerText, fontSize: TYPOGRAPHY.caption.size }}>
      {error === 'blocked'
        ? t('The microphone is blocked. Allow it in the browser address bar, then try again.')
        : t('Voice needs Chrome, Edge or Safari')}
    </Typography>
  );
};
