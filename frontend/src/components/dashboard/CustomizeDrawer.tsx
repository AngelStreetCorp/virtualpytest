import { Close as CloseIcon } from '@mui/icons-material';
import { Box, Button, Drawer, IconButton, Switch, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import { neutralButtonSx } from '../common/PageChrome';

import type { ResolvedCard } from './dashboardLayout';

interface Props {
  open: boolean;
  onClose: () => void;
  /** Already translated tab name. */
  tabTitle: string;
  cards: ResolvedCard[];
  onToggle: (id: string, on: boolean) => void;
  onReset: () => void;
  isMobile: boolean;
}

/** Per-tab customise drawer: a switch per card and a reset. Nothing else. */
export const CustomizeDrawer: React.FC<Props> = ({ open, onClose, tabTitle, cards, onToggle, onReset, isMobile }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  return (
    <Drawer
      anchor={isMobile ? 'bottom' : 'right'}
      open={open}
      onClose={onClose}
      PaperProps={{
        'data-testid': 'customize-drawer-paper',
        sx: {
          width: isMobile ? '100%' : 360,
          maxHeight: isMobile ? '80%' : '100%',
          bgcolor: P.surfaceSolid,
          color: P.textPrimary,
          // MUI tints a dark Paper with an elevation overlay: that is the default grey this drawer showed.
          backgroundImage: 'none',
          borderLeft: isMobile ? 'none' : `1px solid ${P.borderColor}`,
          borderTop: isMobile ? `1px solid ${P.borderColor}` : 'none',
          boxShadow: 'none',
        },
      } as object}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', px: 2, py: 1.5, borderBottom: `1px solid ${P.borderColor}`, bgcolor: P.surfaceSolid }}>
        <Typography sx={{ flex: 1, fontSize: TYPOGRAPHY.sectionTitle.size, fontWeight: TYPOGRAPHY.sectionTitle.weight, color: P.textPrimary }}>{t('Customize')} · {tabTitle}</Typography>
        <IconButton size="small" aria-label={t('Close')} onClick={onClose} sx={{ color: P.textSecondary }}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>
      <Box sx={{ flex: 1, overflowY: 'auto', px: 2 }}>
        {cards.map(({ def, on }) => (
          <Box key={def.id} sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 1.25, borderBottom: `1px solid ${P.borderColor}` }}>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 600, color: P.textPrimary }} noWrap>{t(def.titleKey)}</Typography>
              <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }} noWrap>{t(def.descriptionKey)}</Typography>
            </Box>
            <Switch
              size="small"
              checked={on}
              onChange={(e) => onToggle(def.id, e.target.checked)}
              inputProps={{ 'aria-label': t(def.titleKey) }}
              sx={{
                '& .MuiSwitch-switchBase': { color: P.textMuted },
                '& .MuiSwitch-switchBase.Mui-checked': { color: P.accent },
                '& .MuiSwitch-track': { bgcolor: P.borderColor, opacity: 1 },
                '& .MuiSwitch-switchBase.Mui-checked + .MuiSwitch-track': { bgcolor: P.accent, opacity: 0.45 },
              }}
            />
          </Box>
        ))}
      </Box>
      <Box sx={{ p: 2, borderTop: `1px solid ${P.borderColor}` }}>
        <Button fullWidth variant="outlined" onClick={onReset} sx={neutralButtonSx(P)}>
          {t('Reset this tab to default')}
        </Button>
      </Box>
    </Drawer>
  );
};
