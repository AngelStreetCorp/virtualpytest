/**
 * One AI call's conversation (prompt and answer per model attempt) in a dialog over the Calls tab, so the operator never
 * leaves the page. Read from Langfuse through GET /server/ai/usage/trace/<id>.
 */
import { Close as CloseIcon } from '@mui/icons-material';
import { Box, CircularProgress, Dialog, DialogContent, DialogTitle, IconButton, Typography } from '@mui/material';
import React, { useEffect, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';

import { fetchCallTrace } from './api';
import type { CallTrace } from './api';

const asText = (v: unknown): string => {
  if (v == null) return '';
  if (typeof v === 'string') return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
};

interface Props {
  traceId: string | null;
  onClose: () => void;
}

export const TraceDialog: React.FC<Props> = ({ traceId, onClose }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [trace, setTrace] = useState<CallTrace | null>(null);
  const [error, setError] = useState('');
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    setTrace(null);
    setError('');
    setMissing(false);
    if (!traceId) return undefined;
    let live = true;
    fetchCallTrace(traceId)
      .then((r) => { if (!live) return; if (r) setTrace(r); else setMissing(true); })
      .catch((e: Error) => live && setError(e.message || t('Conversation not available')));
    return () => {
      live = false;
    };
  }, [traceId, t]);

  const block = (label: string, body: unknown, key: string) => {
    const text = asText(body);
    if (!text) return null;
    return (
      <Box key={key} sx={{ mb: 1.5 }}>
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, fontWeight: 600, mb: 0.5 }}>{label}</Typography>
        <Box component="pre" sx={{ m: 0, p: 1.25, maxHeight: 320, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: TYPOGRAPHY.caption.size, bgcolor: P.hoverBg, color: P.textPrimary, border: `1px solid ${P.borderColor}`, borderRadius: 1, fontFamily: 'inherit' }}>{text}</Box>
      </Box>
    );
  };

  return (
    <Dialog open={Boolean(traceId)} onClose={onClose} maxWidth="md" fullWidth PaperProps={{ sx: { bgcolor: P.surface, backgroundImage: 'none', border: `1px solid ${P.borderColor}` } }}>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: P.textPrimary }}>
        {t('Conversation')}
        <IconButton size="small" onClick={onClose} aria-label={t('Close')} sx={{ color: P.textSecondary }}><CloseIcon fontSize="small" /></IconButton>
      </DialogTitle>
      <DialogContent dividers>
        {!trace && !error && !missing && <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={24} /></Box>}
        {missing && <Typography sx={{ color: P.textMuted }}>{t('No conversation recorded for this call (yet).')}</Typography>}
        {error && <Typography sx={{ color: P.textSecondary }}>{error}</Typography>}
        {trace && (trace.steps.length === 0
          ? [block(t('Prompt'), trace.input, 'in'), block(t('Answer'), trace.output, 'out')]
          : trace.steps.map((s, i) => (
            <Box key={i} sx={{ mb: 2 }}>
              <Typography sx={{ fontWeight: 600, color: P.textPrimary, mb: 0.75 }}>
                {[s.name, s.model].filter(Boolean).join(' · ')}
                {s.level === 'ERROR' && <Box component="span" sx={{ color: P.error }}> · {s.status || t('Failed')}</Box>}
              </Typography>
              {block(t('Prompt'), s.input, `in${i}`)}
              {block(t('Answer'), s.output, `out${i}`)}
            </Box>
          )))}
      </DialogContent>
    </Dialog>
  );
};
