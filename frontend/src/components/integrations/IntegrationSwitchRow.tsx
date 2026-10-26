import { Box, Switch, Typography } from '@mui/material';
import { TYPOGRAPHY } from '../../constants/typography';
import React from 'react';
import { useAgentChatPalette } from '../../constants/agentChatTheme';

interface Props {
  checked: boolean;
  onChange: (checked: boolean) => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  disabled?: boolean;
}

/** On/off setting row: switch on the left, 600 title, muted description. The label never flips with the state. */
const IntegrationSwitchRow: React.FC<Props> = ({ checked, onChange, title, description, disabled }) => {
  const P = useAgentChatPalette();
  return (
    <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5 }}>
      <Switch checked={checked} disabled={disabled} onChange={(_e, v) => onChange(v)} sx={{ mt: -0.25, flexShrink: 0 }} />
      <Box sx={{ minWidth: 0 }}>
        <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.body.size }}>{title}</Typography>
        {description && <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{description}</Typography>}
      </Box>
    </Box>
  );
};

export default IntegrationSwitchRow;
