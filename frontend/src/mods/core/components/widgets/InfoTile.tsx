/**
 * A small Dashboard widget body: one big `primary` value, a `secondary` line, and an
 * optional `footer` (one or more muted lines). Wires the agent-chat palette so a mod
 * just composes the text — no per-widget MUI glue. Use this for "info tile" widgets
 * (clock, weather, calendar, stocks, …) instead of hand-rolling `useAgentChatPalette`
 * + three `Typography` per mod.
 *
 * Sizes come from `TYPOGRAPHY` so the whole UI follows the user's font-scale setting
 * (UI_STYLE §10). State `loading` shows an em-dash; `error` shows `errorMessage` with a
 * thin left border in the palette's error colour so a broken tile reads as broken
 * next to the calm `textMuted` neighbours.
 *
 * The widget's title bar, frame, settings and remove controls come from `WidgetFrame`
 * (mounted by `<WidgetArea>`); this component is only the body.
 */
import { Box, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../../constants/agentChatTheme';
import { useI18n } from '../../../../i18n/useI18n';
import { TYPOGRAPHY } from '../../../../constants/typography';

export type InfoTileState = 'ok' | 'loading' | 'error';

export interface InfoTileProps {
  /** Headline value. Big, primary text colour. */
  primary?: React.ReactNode;
  /** One line under `primary`, secondary text colour. */
  secondary?: React.ReactNode;
  /** Muted line(s) at the bottom — pass a string, an array, or a `<>` fragment. */
  footer?: React.ReactNode;
  /** Default `ok`. `loading` shows `—`; `error` shows `errorMessage`. */
  state?: InfoTileState;
  /** Shown when `state === 'error'`. Falls back to a translated "unavailable" line. */
  errorMessage?: React.ReactNode;
  /** Use a monospace font for `primary` (clock face). Default `false`. */
  monospace?: boolean;
  /** Optional small title above `primary` (rarely used; `WidgetFrame` already shows the widget name). */
  title?: React.ReactNode;
}

/** Small Dashboard widget body: big value, secondary line, muted footer. */
export const InfoTile: React.FC<InfoTileProps> = ({
  primary,
  secondary,
  footer,
  state = 'ok',
  errorMessage,
  monospace = false,
  title,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();

  if (state === 'error') {
    return (
      <Box
        data-testid="info-tile-error"
        sx={{
          pl: 1,
          borderLeft: `2px solid ${P.error}`,
        }}
      >
        <Typography sx={{ ...TYPOGRAPHY.caption, color: P.textSecondary }}>
          {errorMessage ?? t('Unavailable')}
        </Typography>
      </Box>
    );
  }

  return (
    <Box>
      {title != null && (
        <Typography
          sx={{
            ...TYPOGRAPHY.microMeta,
            color: P.textMuted,
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
          }}
          noWrap
        >
          {title}
        </Typography>
      )}
      <Typography
        sx={{
          ...(monospace ? TYPOGRAPHY.code : TYPOGRAPHY.kpiValue),
          color: P.textPrimary,
          lineHeight: 1.1,
          letterSpacing: monospace ? '0.04em' : undefined,
        }}
        noWrap
      >
        {state === 'loading' ? '—' : primary}
      </Typography>
      {secondary != null && state === 'ok' && (
        <Typography sx={{ ...TYPOGRAPHY.body, color: P.textSecondary, mt: 0.25 }} noWrap>
          {secondary}
        </Typography>
      )}
      {footer != null && state === 'ok' && (
        <Typography sx={{ ...TYPOGRAPHY.caption, color: P.textMuted, mt: 0.25 }} noWrap>
          {footer}
        </Typography>
      )}
    </Box>
  );
};
