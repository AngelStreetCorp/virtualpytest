import { Box, Typography } from '@mui/material';
import React from 'react';

import { TYPOGRAPHY } from '../../constants/typography';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';

/** Shown in a block that reads a device when its picker has none chosen yet. */
export const NoDevice: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  return (
    <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.body.size, py: 1 }}>
      {t('Choose a device in the device picker above.')}
    </Typography>
  );
};

/** A block the viewer may not use: no data, no error, the reason. */
export const LockedBlock: React.FC<{ missing: string[] }> = ({ missing }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  return (
    <Box sx={{ py: 2, textAlign: 'center' }} data-testid="block-locked">
      <Typography sx={{ color: P.textSecondary, fontSize: TYPOGRAPHY.body.size, fontWeight: 600 }}>
        {t('You do not have access to this block')}
      </Typography>
      <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size, mt: 0.5 }}>
        {t('Needs {permission}. Ask a team admin.', { permission: missing.join(', ') })}
      </Typography>
    </Box>
  );
};

/** A block whose type this build does not know (a page saved by a newer server). */
export const UnknownBlock: React.FC<{ type: string }> = ({ type }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  return (
    <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size }}>
      {t('Unknown block type {type}. Update the app.', { type })}
    </Typography>
  );
};
