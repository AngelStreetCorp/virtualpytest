import { Box, Chip, Tooltip, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { useI18n } from '../../../i18n/useI18n';

export interface GroupModelBadge {
  /** The exact model name (e.g. `fire_tv_fireos`). Drives the chip key
   *  and the visible label. */
  model: string;
  /** Members of this model currently in the group selection (bar) or
   *  marked `included: true` (modal). Drives the selected-vs-empty chip
   *  styling; not rendered as text. */
  count: number;
  /** When `false` the chip is greyed and clicks are ignored; an
   *  explanatory tooltip is shown instead. The bar uses it to signal a
   *  non-compatible target with the chosen remote; the modal uses it for
   *  the per-member `chosenProfile !== remoteProfile` condition. */
  enabled: boolean;
  /** Optional reason for the disable state — surfaced in the tooltip. */
  disabledReason?: string;
}

interface GroupModelBadgeRowProps {
  badges: GroupModelBadge[];
  onToggle: (model: string) => void;
  /** Aria-label prefix so the chip's tooltip / accessibility name hints
   *  at the action. The modal passes a different label from the bar. */
  label: string;
  /** Optional leading caption (e.g. "Models" in the modal header). */
  caption?: string;
}

/**
 * Per-model filter chips in the group select bar and the group modal
 * header. One chip per model currently displayed in the group; the chip
 * label is the bare model name. Clicking a chip toggles every member of
 * that model in / out of the group. A chip switches between an outlined
 * accent state (zero members in the group) and a filled accent state
 * (one or more members in the group) so the operator can read selection
 * without an inline count.
 *
 * A chip goes grey when at least one member of that model can't be
 * reached on the displayed remote — the bar surfaces a pool-level
 * incompatibility, the modal surfaces a per-member
 * `chosenProfile !== remoteProfile` mismatch.
 */
export const GroupModelBadgeRow: React.FC<GroupModelBadgeRowProps> = ({ badges, onToggle, label, caption }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();

  if (badges.length === 0) return null;

  return (
    <Box
      sx={{
        display: 'flex',
        // The bar is one line (TASK-… operator request); chips stay on
        // a single row inside the strip. If there are more chips than
        // fit, the strip becomes a horizontal scroller — never wraps to
        // a second row, which would push the Clear / Control buttons
        // off the row.
        flexWrap: 'nowrap',
        alignItems: 'center',
        gap: 0.75,
        rowGap: 0.5,
        flex: '1 1 auto',
        minWidth: 0,
        overflowX: 'auto',
        overflowY: 'hidden',
        // Hide the scrollbar visually — overflow is still reachable via
        // horizontal swipe / trackpad; a visible scrollbar would shift
        // the row height.
        scrollbarWidth: 'none',
        '&::-webkit-scrollbar': { display: 'none' },
      }}
    >
      {caption && (
        <Typography variant="caption" sx={{ color: P.textMuted, mr: 0.5, fontWeight: 600 }}>
          {caption}
        </Typography>
      )}
      {badges.map(({ model, count, enabled, disabledReason }) => {
        const all = count > 0;
        // Operator asked to drop the "(N)" suffix — chip just reads the
        // model name. Count is still used to drive the selected-vs-empty
        // styling below (filled accent border when at least one of the
        // model's members is in the group) so the toggle feedback is
        // not lost.
        const chipLabel = model;
        const tooltip = !enabled
          ? (disabledReason ?? t('Some {model} targets are not compatible with the chosen remote', { model }))
          : all
            ? t('Click to remove every {model} from the group', { model })
            : t('Click to add every {model} to the group', { model });
        return (
          <Tooltip key={model} title={tooltip}>
            <span>
              <Chip
                size="small"
                label={chipLabel}
                aria-label={
                  // Screen readers get the count back; the visible
                  // label is just the model name at the operator's
                  // request.
                  count > 0
                    ? `${label} ${model}, ${count} in group`
                    : `${label} ${model}, none in group`
                }
                onClick={enabled ? () => onToggle(model) : undefined}
                sx={{
                  height: 24,
                  fontSize: '0.72rem',
                  fontFamily: 'monospace',
                  fontWeight: 600,
                  cursor: enabled ? 'pointer' : 'not-allowed',
                  // Never let the chip compress — if the strip
                  // overflows it scrolls, the chip stays full-size so
                  // the model name never truncates.
                  flexShrink: 0,
                  borderColor: enabled ? P.accent : P.borderColor,
                  // Filled when at least one of this model's devices
                  // is in the group, outlined when empty. Replaces the
                  // "(N)" suffix as the selection-state signal so the
                  // chip stays readable without an inline count.
                  bgcolor: !enabled
                    ? `${P.hoverBg}80`
                    : count > 0
                      ? P.accent
                      : `${P.accent}22`,
                  // Selected chip is filled with P.accent (gold #d4a574);
                  // using P.accentText (also #d4a574 in dark mode) makes
                  // the label invisible on its own background. Switch to
                  // a fixed dark colour in that state — same convention
                  // the rest of the app uses for gold-on-gold accents
                  // (PageChrome goldButtonSx, primary action buttons…).
                  //
                  // Unselected chip is a 13% gold tint over the dark bar
                  // surface; P.accentText on that tint lands at ~4.5:1 in
                  // dark mode — passes WCAG AA barely and reads as dim.
                  // BUG-0461 only fixed the selected branch; the operator
                  // asked for the unselected branch too. P.textPrimary
                  // (#f0f0f0 in dark, #141414 in light) gives ~9.5:1 in
                  // dark and ~7:1 in light, and keeps the gold tint so
                  // the chip still reads as a gold-accented filter.
                  color: !enabled
                    ? P.textMuted
                    : count > 0
                      ? '#1a1a1a'
                      : P.textPrimary,
                  opacity: enabled ? 1 : 0.6,
                  '&:hover': enabled
                    ? count > 0
                      ? { filter: 'brightness(1.1)' }
                      : { borderColor: P.accent, bgcolor: `${P.accent}40` }
                    : undefined,
                }}
              />
            </span>
          </Tooltip>
        );
      })}
    </Box>
  );
};
