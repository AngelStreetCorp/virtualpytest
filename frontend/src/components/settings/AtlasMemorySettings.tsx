/**
 * Settings → AI: the caller's own Atlas memory (TASK-172), switched on on demand.
 *
 * The memory is per user: one markdown file per day of what this user asked and what Atlas did,
 * so the same question next time is a lookup instead of a fresh model run. Off until the user turns
 * it on here or from the AI agent page. "Clear my memory" deletes only this user's files.
 */
import { Box, Button, Card, CardContent, FormControlLabel, Switch, Typography } from '@mui/material';
import React, { useState } from 'react';

import { TYPOGRAPHY } from '../../constants/typography';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useAtlasMemory } from '../../hooks/aiagent';
import { useI18n } from '../../i18n/useI18n';
import { AppIcon } from '../../constants/icons';
import { ConfirmDialog } from '../common/ConfirmDialog';
import { dangerButtonSx } from '../common/PageChrome';

export const AtlasMemorySettings: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { status, busy, error, setEnabled, forget } = useAtlasMemory();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const unavailable = !status?.available;
  const reason = status?.reason === 'off'
    ? t('The memory is switched off on this server.')
    : status?.reason === 'no_user'
      ? t('The memory needs a signed-in user: shared logins (auto-sign, API key) have none.')
      : '';

  return (
    <Card>
      <CardContent>
        <Box display="flex" alignItems="center" gap={1} mb={0.5}>
          <AppIcon name="memory" size="md" color={P.accentText} />
          <Typography variant="h6" sx={{ flex: 1 }}>{t('Atlas memory')}</Typography>
          <FormControlLabel
            sx={{ mr: 0 }}
            control={(
              <Switch
                checked={!!status?.enabled}
                disabled={unavailable || busy}
                onChange={(e) => void setEnabled(e.target.checked)}
                inputProps={{ 'aria-label': t('Use memory') }}
              />
            )}
            label={<Typography sx={{ fontSize: TYPOGRAPHY.body.size }}>{t('Use memory')}</Typography>}
          />
        </Box>
        <Typography variant="caption" sx={{ color: P.textSecondary, display: 'block' }}>
          {t('Atlas remembers what you asked and what it did, so the same question next time is answered from memory instead of a new model run. Only for you, kept {days} days.', { days: status?.retention_days ?? 30 })}
        </Typography>
        {reason && (
          <Typography variant="caption" sx={{ color: P.textMuted, display: 'block', mt: 1 }}>{reason}</Typography>
        )}
        {error && (
          <Typography variant="caption" sx={{ color: P.error, display: 'block', mt: 1 }}>{error}</Typography>
        )}
        {!unavailable && (
          <Box display="flex" alignItems="center" gap={1} mt={1.5} flexWrap="wrap">
            <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textSecondary, flex: 1 }}>
              {t('{entries} answers kept over {days} days · {recalls} recalled', { entries: status?.entries ?? 0, days: status?.days ?? 0, recalls: status?.recalls ?? 0 })}
            </Typography>
            <Button
              size="small"
              sx={dangerButtonSx(P)}
              disabled={busy || !status?.entries}
              onClick={() => setConfirmOpen(true)}
            >
              {t('Clear my memory')}
            </Button>
          </Box>
        )}
      </CardContent>
      <ConfirmDialog
        open={confirmOpen}
        title={t('Clear my memory')}
        message={t('Delete everything Atlas remembers for you? This cannot be undone.')}
        confirmText={t('Clear')}
        confirmColor="error"
        onConfirm={() => { setConfirmOpen(false); void forget(); }}
        onCancel={() => setConfirmOpen(false)}
      />
    </Card>
  );
};
