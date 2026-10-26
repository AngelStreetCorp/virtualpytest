import { Check as CheckIcon, ErrorOutline as ErrorIcon } from '@mui/icons-material';
import { Box, Button, ButtonBase, MenuItem, TextField, Typography } from '@mui/material';
import React, { useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import { buildServerUrl } from '../../utils/buildUrlUtils';

/** The picker value for "not a screen of this tree". */
export const UNKNOWN = '__unknown__';

export interface CorrectionNode {
  node_id: string;
  label: string;
}

export interface CorrectionAnswer {
  ok: boolean;
  text: string;
  verdictId?: string;
}

interface CorrectionContext {
  userinterfaceName?: string | null;
  /** The live frame's fingerprint (with regions) the matcher compared. */
  liveFingerprint: unknown;
  /** The node that claimed the frame; null when nothing was named. */
  claimedNodeId: string | null;
  frameUrl?: string | null;
  hostName?: string | null;
  deviceId?: string | null;
  /** Label of a node id, for the confirmation text. */
  labelOf: (id: string) => string;
}

/**
 * "Wrong screen?" correction (TASK-104 goal 11, TASK-137 goal 7): POST /localize/verdict with the true
 * node (or Unknown), and Undo. Shared by the Localize popover and the Live results run rows.
 */
export const useLocalizeCorrection = (ctx: CorrectionContext) => {
  const { t } = useI18n();
  const [answered, setAnswered] = useState<CorrectionAnswer | null>(null);

  const save = async (pick: string) => {
    const unknown = pick === UNKNOWN;
    if (unknown && !ctx.claimedNodeId) {
      setAnswered({ ok: true, text: t('Nothing to correct: no screen claimed this frame') });
      return;
    }
    try {
      const resp = await fetch(buildServerUrl('/server/navigation/localize/verdict'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          userinterface_name: ctx.userinterfaceName,
          live_fingerprint: ctx.liveFingerprint ?? null,
          wrong_node_id: ctx.claimedNodeId,
          true_node_id: unknown ? null : pick,
          frame_url: ctx.frameUrl ?? null,
          host_name: ctx.hostName,
          device_id: ctx.deviceId,
        }),
      });
      const data = await resp.json();
      if (!data.success) {
        setAnswered({ ok: false, text: data.error || t('The correction was not saved') });
        return;
      }
      setAnswered({
        ok: true,
        verdictId: data.id,
        text:
          data.action === 'add_sample'
            ? t('Added this frame to {label}', { label: data.label ?? ctx.labelOf(pick) })
            : t('Marked as an unknown screen'),
      });
    } catch (e) {
      setAnswered({ ok: false, text: e instanceof Error ? e.message : t('The correction was not saved') });
    }
  };

  const undo = async () => {
    if (!answered?.verdictId) return;
    try {
      const resp = await fetch(buildServerUrl(`/server/navigation/localize/verdict/${answered.verdictId}/undo`), {
        method: 'POST',
      });
      const data = await resp.json();
      setAnswered(
        data.success ? { ok: true, text: t('Undone: the matcher is back as it was') } : { ok: false, text: data.error || t('Undo failed') },
      );
    } catch (e) {
      setAnswered({ ok: false, text: e instanceof Error ? e.message : t('Undo failed') });
    }
  };

  return { answered, setAnswered, save, undo };
};

interface QuestionProps {
  /** Nodes listed first (the matcher's ranked screens). */
  primary: CorrectionNode[];
  /** The rest of the tree, shown muted. */
  others: CorrectionNode[];
  onSave: (pick: string) => void;
  onCancel: () => void;
  /** Draw the top border (inside the Localize popover). */
  bordered?: boolean;
}

/** "Which screen was it?": Unknown screen first, then the candidates, then the rest of the tree. */
export const LocalizeCorrectionQuestion: React.FC<QuestionProps> = ({ primary, others, onSave, onCancel, bordered = true }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [pick, setPick] = useState<string>(UNKNOWN);
  return (
    <Box
      sx={{
        borderTop: bordered ? `1px solid ${P.borderColor}` : undefined,
        px: bordered ? 1.75 : 0,
        py: 1.375,
        display: 'flex',
        flexDirection: 'column',
        gap: 1,
      }}
    >
      <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, fontWeight: 600 }}>{t('Which screen was it?')}</Typography>
      <TextField
        select
        size="small"
        value={pick}
        onChange={(e) => setPick(e.target.value)}
        SelectProps={{ MenuProps: { PaperProps: { sx: { maxHeight: 320 } } } }}
        sx={{ '& .MuiInputBase-root': { fontSize: TYPOGRAPHY.caption.size } }}
      >
        <MenuItem value={UNKNOWN} sx={{ fontSize: TYPOGRAPHY.caption.size }}>
          {t('Unknown screen (not in this tree)')}
        </MenuItem>
        {primary.map((r) => (
          <MenuItem key={r.node_id} value={r.node_id} sx={{ fontSize: TYPOGRAPHY.caption.size }}>
            {r.label}
          </MenuItem>
        ))}
        {others.map((n) => (
          <MenuItem key={n.node_id} value={n.node_id} sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>
            {n.label}
          </MenuItem>
        ))}
      </TextField>
      <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
        <Button size="small" onClick={onCancel} sx={{ color: P.textSecondary }}>
          {t('Cancel')}
        </Button>
        <Button size="small" variant="contained" onClick={() => onSave(pick)}>
          {t('Save')}
        </Button>
      </Box>
    </Box>
  );
};

/** The confirmation line with Undo. `bordered` = the full-width strip inside the popover. */
export const LocalizeCorrectionBanner: React.FC<{ answered: CorrectionAnswer; onUndo: () => void; bordered?: boolean }> = ({
  answered,
  onUndo,
  bordered = true,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  return (
    <Box
      sx={{
        borderTop: bordered ? `1px solid ${P.borderColor}` : undefined,
        px: bordered ? 1.75 : 0.75,
        py: bordered ? 1 : 0.5,
        borderRadius: bordered ? 0 : 1,
        display: 'flex',
        alignItems: 'center',
        gap: 0.75,
        background: `${answered.ok ? P.success : P.error}1f`,
        color: answered.ok ? P.success : P.error,
      }}
    >
      {answered.ok ? <CheckIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} /> : <ErrorIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />}
      <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, flex: 1 }}>{answered.text}</Typography>
      {answered.verdictId && (
        <ButtonBase onClick={onUndo} sx={{ fontSize: TYPOGRAPHY.caption.size, textDecoration: 'underline', color: 'inherit' }}>
          {t('Undo')}
        </ButtonBase>
      )}
    </Box>
  );
};
