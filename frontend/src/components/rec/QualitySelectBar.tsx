import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, LinearProgress, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { neutralButtonSx } from '../common/PageChrome';
import { useI18n } from '../../i18n/useI18n';
import type { QualityLevel } from '../../hooks/rec/useRecQualitySwitch';
import type { QualityPhase } from '../../hooks/rec/useQualitySelection';
import { segmentedSx } from '../common/PageChrome';

import { ModeBar, ModeBarActions } from './ModeBar';
import { TYPOGRAPHY } from '../../constants/typography';

const LEVELS: { value: QualityLevel; label: string }[] = [
  { value: 'low', label: 'Low' },
  { value: 'sd', label: 'SD' },
  { value: 'hd', label: 'HD' },
  { value: 'hd_plus', label: 'HD+' },
];

interface QualitySelectBarProps {
  quality: QualityLevel;
  count: number;
  total?: number;
  phase: QualityPhase;
  okCount: number;
  failedCount: number;
  secondsLeft: number;
  onQuality: (q: QualityLevel) => void;
  onSelectAll: () => void;
  onClear: () => void;
  onApply: () => void;
  onRetry: () => void;
  onUndo: () => void;
  onClose: () => void;
}

/** Bar in the Device page's reserved mode line while bulk stream quality is on (TASK-97). */
export const QualitySelectBar: React.FC<QualitySelectBarProps> = ({
  quality, count, total, phase, okCount, failedCount, secondsLeft,
  onQuality, onSelectAll, onClear, onApply, onRetry, onUndo, onClose,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const costly = quality === 'hd' || quality === 'hd_plus';
  const level = LEVELS.find((l) => l.value === quality)?.label ?? '';

  return (
    <ModeBar>
      {phase === 'idle' && (
        <>
          <ToggleButtonGroup exclusive size="small" value={quality} onChange={(_, v) => v && onQuality(v)} sx={segmentedSx(P, 'sm')}>
            {LEVELS.map((l) => <ToggleButton key={l.value} value={l.value}>{l.label}</ToggleButton>)}
          </ToggleButtonGroup>
          <ModeBarActions
            count={count}
            total={total}
            onSelectAll={onSelectAll}
            onClear={onClear}
            actionLabel={t('Apply {quality} to {count} devices', { quality: level, count })}
            onAction={() => (costly ? setConfirmOpen(true) : onApply())}
            actionDisabled={count === 0}
          />
        </>
      )}
      {phase === 'applying' && (
        <>
          <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.body.size }}>{t('Applying {quality}', { quality: level })}</Typography>
          <LinearProgress sx={{ flex: 1, height: 6, borderRadius: 3 }} />
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{t('{n} s', { n: secondsLeft })}</Typography>
        </>
      )}
      {phase === 'done' && (
        <>
          <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 600, color: P.success }}>{t('{count} ok', { count: okCount })}</Typography>
          {failedCount > 0 && <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 600, color: P.error }}>{t('{count} failed', { count: failedCount })}</Typography>}
          <Box sx={{ flex: 1 }} />
          {failedCount > 0 && (
            <Button size="small" variant="outlined" onClick={onRetry} sx={{ ...(neutralButtonSx(P) as object),  textTransform: 'none' }}>{t('Retry failed ({count})', { count: failedCount })}</Button>
          )}
          <Button size="small" onClick={onUndo} sx={{ textTransform: 'none', color: P.accentText }}>{t('Undo')}</Button>
          <Button size="small" onClick={onClose} sx={{ textTransform: 'none', color: P.textSecondary }}>{t('Close')}</Button>
        </>
      )}
      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)}>
        <DialogTitle>{t('Set {count} devices to {quality}?', { count, quality: level })}</DialogTitle>
        <DialogContent>
          <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textSecondary }}>{t('HD ≈ 1.7× CPU per stream · ceiling ≈ 40 HD streams')}</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmOpen(false)}>{t('Cancel')}</Button>
          <Button variant="contained" onClick={() => { setConfirmOpen(false); onApply(); }}>{t('Set {count} to {quality}', { count, quality: level })}</Button>
        </DialogActions>
      </Dialog>
    </ModeBar>
  );
};
