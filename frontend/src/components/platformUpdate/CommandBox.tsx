import React, { useState } from 'react';
import { Box, Button, Typography } from '@mui/material';

import { AppIcon } from '../../constants/icons';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import { neutralButtonSx } from '../common/PageChrome';

interface Props {
  /** The exact text to copy (a root command, a public key, an authorized_keys line). The app never runs it. */
  text: string;
  /** Small caption above the box (machine name, what it is). */
  caption?: string;
  /** Extra line under the caption (why this is needed). */
  hint?: string;
}

/** A command or key in a monospace box with a Copy button (TASK-128). Shared by the prerequisites rows and the Settings dialog. */
export const CommandBox: React.FC<Props> = ({ text, caption, hint }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <Box sx={{ mb: 1 }}>
      {caption ? <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, fontWeight: 600, color: P.textPrimary }}>{caption}</Typography> : null}
      {hint ? <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, mb: 0.5 }}>{hint}</Typography> : null}
      <Box sx={{ display: 'flex', gap: 1, alignItems: 'flex-start' }}>
        <Box
          component="pre"
          data-testid="command-box"
          sx={{
            m: 0, p: 1, flex: 1, minWidth: 0, bgcolor: P.hoverBg, borderRadius: 1, fontSize: TYPOGRAPHY.caption.size, fontFamily: 'monospace',
            whiteSpace: 'pre-wrap', wordBreak: 'break-all', color: P.textPrimary,
          }}
        >
          {text}
        </Box>
        <Button size="small" variant="outlined" sx={neutralButtonSx(P)} startIcon={<AppIcon name="copy" />} onClick={() => void copy()}>
          {copied ? t('Copied') : t('Copy')}
        </Button>
      </Box>
    </Box>
  );
};
