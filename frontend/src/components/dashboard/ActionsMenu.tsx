import { MoreVert as MoreIcon } from '@mui/icons-material';
import { CircularProgress, Divider, IconButton, ListItemIcon, ListItemText, ListSubheader, Menu, MenuItem, Tooltip } from '@mui/material';
import React, { useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { neutralButtonSx } from '../common/PageChrome';

export interface ActionItem {
  key: string;
  /** Subheader above the first item of each group (a divider separates groups). */
  group?: string;
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  /** Replaces the icon with a spinner while the action runs. */
  busy?: boolean;
  /** Reboot / power: the fixed danger colour, as the loose icon had. */
  danger?: boolean;
}

/** ONE "more actions" (⋮) button with a menu; replaces a row of loose action icons in a card header. */
export const ActionsMenu: React.FC<{ items: ActionItem[]; label: string; testId?: string }> = ({ items, label, testId }) => {
  const P = useAgentChatPalette();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  if (items.length === 0) return null;
  const close = () => setAnchor(null);
  return (
    <>
      <Tooltip title={label}>
        <IconButton size="small" aria-label={label} aria-haspopup="menu" data-testid={testId} onClick={(e) => setAnchor(e.currentTarget)} sx={neutralButtonSx(P)}>
          <MoreIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={close} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} transformOrigin={{ vertical: 'top', horizontal: 'right' }}>
        {items.flatMap((item, i) => {
          const startsGroup = item.group !== undefined && item.group !== items[i - 1]?.group;
          const nodes: React.ReactNode[] = [];
          if (startsGroup) {
            if (i > 0) nodes.push(<Divider key={`${item.key}-divider`} />);
            nodes.push(
              <ListSubheader key={`${item.key}-group`} sx={{ bgcolor: 'transparent', color: P.textMuted, lineHeight: 2, fontSize: TYPOGRAPHY.caption.size }}>
                {item.group}
              </ListSubheader>,
            );
          }
          nodes.push(
            <MenuItem
              key={item.key}
              disabled={item.disabled}
              onClick={() => {
                close();
                item.onClick();
              }}
              sx={{ color: item.danger ? P.error : P.textPrimary }}
            >
              <ListItemIcon sx={{ color: item.danger ? P.error : P.textSecondary, minWidth: 32 }}>
                {item.busy ? <CircularProgress size={16} color="inherit" /> : item.icon}
              </ListItemIcon>
              <ListItemText primaryTypographyProps={{ fontSize: TYPOGRAPHY.body.size }}>{item.label}</ListItemText>
            </MenuItem>,
          );
          return nodes;
        })}
      </Menu>
    </>
  );
};
