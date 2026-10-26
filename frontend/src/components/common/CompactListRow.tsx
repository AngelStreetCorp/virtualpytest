import { Box, CircularProgress, IconButton, Switch, Tooltip, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { AppIcon } from '../../constants/icons';
import { TYPOGRAPHY } from '../../constants/typography';
import { dangerIconSx } from './PageChrome';

/**
 * One row of a compact editor list (Edit node verifications, Edit edge actions).
 * Collapsed: chevron · leading visual · title + one-line summary · run · delete.
 * Click the row to open `children` (the full editor) under it.
 * The parent list draws the outer border; rows only draw a top divider.
 */
export interface CompactListRowProps {
  title: React.ReactNode;
  meta?: React.ReactNode;
  /** Thumbnail or icon on the left (24-28 px high). */
  leading?: React.ReactNode;
  /** Short warning shown after the title (e.g. a missing key). */
  warning?: string;
  expanded: boolean;
  onToggle: () => void;
  onRun?: () => void;
  canRun?: boolean;
  isRunning?: boolean;
  runStatus?: 'success' | 'failure' | null;
  onRemove: () => void;
  disabled?: boolean;
  first?: boolean;
  children: React.ReactNode;
}

export const CompactListRow: React.FC<CompactListRowProps> = ({
  title,
  meta,
  leading,
  warning,
  expanded,
  onToggle,
  onRun,
  canRun = false,
  isRunning = false,
  runStatus = null,
  onRemove,
  disabled = false,
  first = false,
  children,
}) => {
  const P = useAgentChatPalette();
  const runColor = runStatus === 'success' ? P.success : runStatus === 'failure' ? P.error : undefined;

  return (
    <Box sx={{ borderTop: first ? 'none' : `1px solid ${P.borderColor}` }}>
      <Box
        role="button"
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onToggle();
          }
        }}
        sx={{
          display: 'grid',
          gridTemplateColumns: '20px auto minmax(0, 1fr) auto',
          alignItems: 'center',
          gap: 1,
          px: 1,
          py: 0.75,
          cursor: 'pointer',
          '&:hover': { bgcolor: P.hoverBg },
        }}
      >
        <Box sx={{ color: P.textMuted, display: 'flex', alignItems: 'center' }}>
          <AppIcon name={expanded ? 'expand' : 'chevron'} />
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center' }}>{leading}</Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography
            noWrap
            sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textPrimary, display: 'flex', alignItems: 'center', gap: 0.75 }}
          >
            <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {title}
            </Box>
            {warning && (
              <Box
                component="span"
                sx={{ color: P.warning, fontSize: TYPOGRAPHY.caption.size, display: 'inline-flex', alignItems: 'center', gap: 0.25, flexShrink: 0 }}
              >
                <AppIcon name="warning" /> {warning}
              </Box>
            )}
          </Typography>
          {meta && (
            <Typography
              noWrap
              sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, fontFamily: 'monospace' }}
            >
              {meta}
            </Typography>
          )}
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center' }} onClick={(e) => e.stopPropagation()}>
          {onRun && (
            <Tooltip title="Run">
              <span>
                <IconButton
                  size="small"
                  onClick={onRun}
                  disabled={!canRun || disabled}
                  sx={runColor ? { color: runColor } : undefined}
                >
                  {isRunning ? <CircularProgress size={14} /> : <AppIcon name="play" />}
                </IconButton>
              </span>
            </Tooltip>
          )}
          <Tooltip title="Remove">
            <span>
              <IconButton size="small" onClick={onRemove} disabled={disabled} sx={dangerIconSx(P)}>
                <AppIcon name="delete" />
              </IconButton>
            </span>
          </Tooltip>
        </Box>
      </Box>
      {expanded && <Box sx={{ px: 1, pb: 1, pl: 4 }}>{children}</Box>}
    </Box>
  );
};

/** Turn a command id like `waitForImageToAppear` into `Image appears`-style words. */
export const humanizeCommand = (command?: string): string => {
  if (!command) return '';
  const words = command
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .trim()
    .toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
};

/**
 * Collapsed-by-default block for secondary fields (Edit node / Edit edge "Details").
 * Closed, it shows one summary line so the values stay readable without opening it.
 */
export const DetailsSection: React.FC<{
  summary: React.ReactNode;
  title?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}> = ({ summary, title = 'Details', defaultOpen = false, children }) => {
  const P = useAgentChatPalette();
  const [open, setOpen] = React.useState(defaultOpen);
  return (
    <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 1, mb: 1 }}>
      <Box
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setOpen(!open);
          }
        }}
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          px: 1,
          py: 0.75,
          cursor: 'pointer',
          '&:hover': { bgcolor: P.hoverBg },
        }}
      >
        <Box sx={{ color: P.textMuted, display: 'flex', alignItems: 'center' }}>
          <AppIcon name={open ? 'expand' : 'chevron'} />
        </Box>
        <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textPrimary, flexShrink: 0 }}>{title}</Typography>
        {!open && (
          <Typography
            noWrap
            sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, fontFamily: 'monospace', minWidth: 0 }}
          >
            {summary}
          </Typography>
        )}
      </Box>
      {open && <Box sx={{ px: 1, pb: 1, pl: 4 }}>{children}</Box>}
    </Box>
  );
};

/** A labelled switch on one line (Live, Use fingerprint, Sibling shortcuts…). */
export const InlineSwitch: React.FC<{
  label: React.ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  tooltip?: string;
  hint?: React.ReactNode;
}> = ({ label, checked, onChange, disabled = false, tooltip, hint }) => {
  const P = useAgentChatPalette();
  const body = (
    <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
      <Switch size="small" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <Typography component="span" sx={{ fontSize: TYPOGRAPHY.body.size, color: disabled ? P.textMuted : P.textPrimary }}>
        {label}
      </Typography>
      {hint && (
        <Typography component="span" sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
          {hint}
        </Typography>
      )}
    </Box>
  );
  return tooltip ? (
    <Tooltip title={tooltip}>
      <span>{body}</span>
    </Tooltip>
  ) : (
    body
  );
};

/** Short note above a list whose items are kept but not used (fingerprint on, target node checks on). */
export const SkippedNote: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const P = useAgentChatPalette();
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 0.75,
        px: 1,
        py: 0.5,
        mb: 0.75,
        borderRadius: 1,
        border: `1px solid ${P.warning}`,
        color: P.warning,
        fontSize: TYPOGRAPHY.caption.size,
      }}
    >
      <AppIcon name="info" /> {children}
    </Box>
  );
};
