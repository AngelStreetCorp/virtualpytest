import { OpenInNew as OpenInNewIcon } from '@mui/icons-material';
import { Box, Link, Typography } from '@mui/material';
import React from 'react';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';

export interface LocalizeCheck {
  verdict: 'true' | 'false' | 'unknown';
  confidence?: number;
  best_match?: { node_id: string; label: string; confidence: number } | null;
  reason?: string;
  excluded_count?: number;
  total?: number;
  dhash?: string | null;
  focus?: { kind?: string; x?: number; y?: number; label?: string } | null;
  // Public URL of the frame captured during this localize run — lets the user open
  // exactly what was localized in a new tab (shown on success AND failure).
  frame_url?: string;
}

/**
 * Localize cross-check shown under a node's verification result, in PLAIN language:
 * does the live screen match the screenshot captured for this node? Success (green) /
 * Failed (red) — same yes/no semantics as a verification. On failure we name the screen
 * it looked like instead. Internal signals (dhash / focus geometry / excluded counts) are
 * intentionally NOT surfaced — the user captured a screenshot, they only need "match or not".
 */
export const LocalizeCheckFooter: React.FC<{ check?: LocalizeCheck | null }> = ({ check }) => {
  const P = useAgentChatPalette();
  if (!check) return null;

  const isOn = check.verdict === 'true';
  const conf = check.confidence != null ? ` (${Math.round(check.confidence * 100)}%)` : '';

  return (
    <Box
      sx={{
        p: 1,
        mt: 1,
        bgcolor: isOn ? `${P.success}1f` : `${P.error}1f`,
        color: P.textPrimary,
        borderRadius: 1,
        border: `1px solid ${isOn ? P.success : P.error}`,
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
        <Typography variant="caption" sx={{ fontWeight: 'bold', display: 'block', lineHeight: 1.3 }}>
          {isOn ? `Localize Success — ${conf}` : 'Localize Failed'}
        </Typography>
        {check.frame_url && (
          <Link
            href={check.frame_url}
            target="_blank"
            rel="noopener noreferrer"
            underline="hover"
            sx={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 0.25,
              fontSize: TYPOGRAPHY.caption.size,
              fontWeight: 500,
              color: 'inherit',
              flexShrink: 0,
            }}
          >
            View frame
            <OpenInNewIcon sx={{ fontSize: TYPOGRAPHY.body.size }} />
          </Link>
        )}
      </Box>
      {!isOn && check.best_match && (
        <Typography variant="caption" sx={{ display: 'block', opacity: 0.85, lineHeight: 1.3 }}>
          Looks like “{check.best_match.label}” ({Math.round(check.best_match.confidence * 100)}%)
        </Typography>
      )}
    </Box>
  );
};

export default LocalizeCheckFooter;
