import { Box, Button, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { goldButtonSx } from '../common/PageChrome';
import { TYPOGRAPHY } from '../../constants/typography';

/** One-line, fixed-height (56) shell shared by the Device page's mode bars (Tags, Group, Quality). */
export const ModeBar: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const P = useAgentChatPalette();
  return (
    <Box
      sx={{
        display: 'flex',
        flexWrap: 'nowrap',
        alignItems: 'center',
        gap: 1.5,
        height: 56,
        px: 1.5,
        bgcolor: P.surface,
        border: `1px solid ${P.borderColor}`,
        borderRadius: 1,
        overflow: 'hidden',
        userSelect: 'none',
        WebkitUserSelect: 'none',
        WebkitTouchCallout: 'none',
      }}
    >
      {children}
    </Box>
  );
};

interface ModeBarActionsProps {
  count: number;
  /** Total selectable devices; omit to show "N selected". */
  total?: number;
  onSelectAll?: () => void;
  selectAllDisabled?: boolean;
  onClear: () => void;
  clearDisabled?: boolean;
  actionLabel: React.ReactNode;
  onAction: () => void;
  actionDisabled?: boolean;
  actionStartIcon?: React.ReactNode;
}

/** Right-aligned, fixed order: count, Select all, Clear, one gold action. */
export const ModeBarActions: React.FC<ModeBarActionsProps> = ({
  count, total, onSelectAll, selectAllDisabled, onClear, clearDisabled, actionLabel, onAction, actionDisabled, actionStartIcon,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const textBtn = { textTransform: 'none', fontWeight: 600, fontSize: TYPOGRAPHY.body.size, color: P.accentText, flexShrink: 0, '&.Mui-disabled': { color: P.textMuted } } as const;
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexShrink: 0, ml: 'auto' }}>
      <Typography
        variant="caption"
        sx={{ color: P.textSecondary, whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums', minWidth: 96, textAlign: 'right' }}
      >
        {total === undefined ? t('{n} selected', { n: count }) : t('{n} of {m} selected', { n: count, m: total })}
      </Typography>
      {onSelectAll && (
        <Button size="small" onClick={onSelectAll} disabled={selectAllDisabled} sx={textBtn}>{t('Select all')}</Button>
      )}
      <Button size="small" onClick={onClear} disabled={clearDisabled ?? count === 0} sx={textBtn}>{t('Clear')}</Button>
      <Button
        size="small"
        variant="contained"
        onClick={onAction}
        disabled={actionDisabled}
        startIcon={actionStartIcon}
        sx={{ ...goldButtonSx(P), height: 36, flexShrink: 0, whiteSpace: 'nowrap' }}
      >
        {actionLabel}
      </Button>
    </Box>
  );
};
