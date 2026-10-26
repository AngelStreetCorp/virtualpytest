import { Box, Switch, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';

interface SettingRowProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Fixed label: it names the setting and never flips with its state. */
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Optional control or link on the right (a test button, a "Manage" link). */
  right?: React.ReactNode;
  disabled?: boolean;
  /** Hairline under the row, for rows stacked in a list. */
  divider?: boolean;
}

/**
 * The one on/off setting row (UI_STYLE.md "On/off settings"): switch on the left, 600 title,
 * muted description under it, optional right slot. Choosing items from a list stays a Checkbox.
 */
const SettingRow: React.FC<SettingRowProps> = ({ checked, onChange, title, description, right, disabled, divider }) => {
  const P = useAgentChatPalette();
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 1.5,
        py: 1,
        borderBottom: divider ? `1px solid ${P.borderColor}` : 'none',
        '&:last-child': divider ? { borderBottom: 'none' } : undefined,
      }}
    >
      <Switch
        size="small"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        inputProps={typeof title === 'string' ? { 'aria-label': title } : undefined}
        sx={{ mt: -0.25, flexShrink: 0 }}
      />
      <Box sx={{ flex: 1, minWidth: 0, opacity: disabled ? 0.6 : 1 }}>
        <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 600, lineHeight: 1.4 }}>{title}</Typography>
        {description && (
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, lineHeight: 1.4 }}>
            {description}
          </Typography>
        )}
      </Box>
      {right && <Box sx={{ flexShrink: 0 }}>{right}</Box>}
    </Box>
  );
};

export default SettingRow;
