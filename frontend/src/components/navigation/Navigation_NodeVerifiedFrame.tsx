import { Box, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';

interface Props {
  verifiedFrameUrl?: string | null;
  verifiedAt?: string | null;
}

/** Age of an ISO timestamp as "5 minutes ago" (t/tn, fr/de in the catalogs). */
const useAge = (iso?: string | null): string | null => {
  const { tn } = useI18n();
  if (!iso) return null;
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return tn(s, '{count} second ago', '{count} seconds ago');
  const m = Math.round(s / 60);
  if (m < 60) return tn(m, '{count} minute ago', '{count} minutes ago');
  const h = Math.round(m / 60);
  if (h < 24) return tn(h, '{count} hour ago', '{count} hours ago');
  const d = Math.round(h / 24);
  return tn(d, '{count} day ago', '{count} days ago');
};

/** Last frame that passed this node's verification. The node card already shows the
 *  stored screenshot, so only the verified frame is shown here. Renders nothing without one. */
export const NodeVerifiedFrame: React.FC<Props> = ({ verifiedFrameUrl, verifiedAt }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const age = useAge(verifiedAt);

  if (!verifiedFrameUrl) return null;

  return (
    <Box sx={{ mb: 1 }}>
      <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, mb: 0.25 }}>
        {age ? `${t('Last verified')} · ${age}` : t('Last verified')}
      </Typography>
      <Box
        component="img"
        src={verifiedFrameUrl}
        alt={t('Last verified')}
        sx={{
          width: '100%',
          maxHeight: 160,
          objectFit: 'contain',
          display: 'block',
          borderRadius: '4px',
          border: `1px solid ${P.borderColor}`,
          backgroundColor: P.surface,
        }}
      />
    </Box>
  );
};

export default NodeVerifiedFrame;
