import { Lock as LockIcon } from '@mui/icons-material';
import { Box, Tooltip, Typography, alpha } from '@mui/material';
import { SxProps, Theme } from '@mui/material/styles';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';

interface DeviceLockBadgeProps {
  /**
   * Whoever holds the device: the manual-control operator, else whoever launched the run.
   * This is the ONLY thing the badge names — see the component note on why the script
   * name is deliberately not a fallback.
   */
  ownerName?: string | null;
  /** True when a script/deployment lock holds the device rather than a human one. */
  scriptLockActive?: boolean;
  /** Start time + duration, from getLockTimingLines — helps spot a stale lock. */
  timing?: { startedAt: string; duration: string } | null;
  maxChars?: number;
  sx?: SxProps<Theme>;
  textSx?: SxProps<Theme>;
}

const truncate = (value: string, maxChars: number) =>
  value.length > maxChars ? `${value.slice(0, maxChars)}…` : value;

/**
 * useDeviceLockLabel's last-resort value. It names an ACTION, not a person, and it is
 * deliberately worded as a UI hook ("take-control" = "you can take this device over"),
 * which the header renders fine as a tooltip but which reads as nonsense as somebody's
 * NAME in a bottom-left badge next to a lock icon. So it is translated here rather than
 * displayed: the lock still shows, the label just says the device is busy.
 */
const UNNAMED_OWNER_LABEL = 'take-control';
const isNamedOwner = (value?: string | null) =>
  Boolean(value) && value !== UNNAMED_OWNER_LABEL;

/**
 * Whether this owner value produces a badge at all. Callers that lay out the same corner
 * (the bottom-right script badge) need this to make room, so it is exported rather than
 * re-derived: a second copy of this rule is how the two badges drift back into each other.
 */
export const lockBadgeShows = (ownerName?: string | null): boolean => Boolean(ownerName);

/**
 * Bottom-left "this device is in use" badge (owner 2026-10-22): a blue lock plus the
 * name of the operator holding the device.
 *
 * Both call sites already knew a lock was held — the header drew a lock icon and the
 * bottom-right RunningScriptNameBadge carried the name — but neither said it where an
 * operator scanning a 12-up device grid actually looks. A locked tile was identical to a
 * free one, and the owner only appeared after you opened the device and hit Control.
 *
 * Blue because that is the colour this codebase already gives "a device is being driven"
 * (P.series[1], the status dot's script colour) — a new colour here would have read as a
 * third kind of state.
 *
 * It names the OPERATOR and never the script. Falling back to the script name looked
 * harmless and was not: on a live tile it printed the same text in both bottom corners,
 * and because RunningScriptNameBadge allows itself 85% of the width it painted straight
 * over this badge and hid the lock. The script name already has a home — bottom-right —
 * so this corner only ever carries what that one cannot say, which is who the human is.
 * A run with no owner therefore shows no badge here rather than a repeat of the right one.
 */
export const DeviceLockBadge: React.FC<DeviceLockBadgeProps> = ({
  ownerName,
  scriptLockActive = false,
  timing,
  maxChars = 24,
  sx,
  textSx,
}) => {
  const P = useAgentChatPalette();

  // Nothing held → nothing to say. Returning null here (rather than an empty chip) is what
  // keeps a free device's corner byte-for-byte what it was before this badge existed.
  const namedOwner = isNamedOwner(ownerName) ? ownerName : null;
  const label = namedOwner || (ownerName ? 'In use' : null);
  if (!label) return null;

  // series[1] is the palette's blue; light and dark derive different hexes from it, so the
  // badge follows the theme instead of pinning one blue that vanishes in one of them.
  const blue = P.series[1];

  return (
    <Tooltip
      arrow
      placement="top"
      componentsProps={{
        tooltip: { sx: { backgroundColor: P.surfaceSolid, color: P.textPrimary, border: `1px solid ${P.borderColor}` } },
        arrow: { sx: { color: P.surfaceSolid } },
      }}
      title={
        <Box sx={{ py: 0.25 }}>
          <Typography variant="caption" sx={{ display: 'block', fontWeight: 'bold' }}>
            {namedOwner
              ? `${scriptLockActive ? 'Run by' : 'Controlled by'}: ${truncate(namedOwner, maxChars * 2)}`
              : 'In use by another operator'}
          </Typography>
          {timing && (
            <>
              <Typography variant="caption" sx={{ display: 'block' }}>
                Started: {timing.startedAt}
              </Typography>
              <Typography variant="caption" sx={{ display: 'block' }}>
                Duration: {timing.duration}
              </Typography>
            </>
          )}
        </Box>
      }
    >
      <Box
        data-testid="device-lock-badge"
        sx={{
          position: 'absolute',
          left: 8,
          bottom: 8,
          zIndex: 3,
          display: 'flex',
          alignItems: 'center',
          gap: 0.5,
          px: 0.75,
          py: 0.4,
          borderRadius: 1,
          // Tinted rather than the flat black of the sibling badges: this one has to be
          // readable as "locked" from across a grid, and it must not read as a second
          // script badge when both are on screen at once.
          backgroundColor: alpha(blue, 0.22),
          border: `1px solid ${alpha(blue, 0.65)}`,
          pointerEvents: 'auto',
          maxWidth: '46%',
          ...sx,
        }}
      >
        <LockIcon
          aria-hidden="true"
          sx={{ fontSize: TYPOGRAPHY.caption.size, color: blue, flexShrink: 0 }}
        />
        <Typography
          variant="caption"
          sx={{
            color: P.textPrimary,
            fontSize: TYPOGRAPHY.caption.size,
            fontWeight: 600,
            lineHeight: 1.2,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            ...textSx,
          }}
        >
          {truncate(label, maxChars)}
        </Typography>
      </Box>
    </Tooltip>
  );
};