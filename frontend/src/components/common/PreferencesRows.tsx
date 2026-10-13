import { DarkMode, LightMode, SettingsBrightness } from '@mui/icons-material';
import { Box, ButtonBase, Divider, Tooltip, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useTheme } from '../../contexts/ThemeContext';
import { LANGUAGES } from '../../i18n';
import { useI18n } from '../../i18n/useI18n';

const THEME_OPTIONS = [
  { mode: 'light', label: 'Light', Icon: LightMode },
  { mode: 'dark', label: 'Dark', Icon: DarkMode },
  { mode: 'system', label: 'System', Icon: SettingsBrightness },
] as const;

// Selected = the app's gold accent, as in the top bar (accentText is the darker gold that stays
// readable on the light menu's white).
const segmentSx = (selected: boolean, gold: string) =>
  ({
    flex: 1,
    height: 32,
    border: '1px solid',
    borderColor: selected ? gold : 'divider',
    borderRadius: 1,
    color: selected ? gold : 'text.secondary',
    bgcolor: selected ? 'action.selected' : 'transparent',
    fontFamily: 'monospace',
    fontSize: '0.75rem',
    fontWeight: 700,
    '&:hover': { borderColor: gold },
    '& svg': { fontSize: '1.1rem' },
  }) as const;

const Row: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 0.75 }}>
    <Typography variant="caption" color="text.secondary" sx={{ width: 76, flexShrink: 0 }}>
      {label}
    </Typography>
    <Box sx={{ display: 'flex', gap: 0.75, flex: 1 }}>{children}</Box>
  </Box>
);

/**
 * Theme (3 icons) and Language (EN / FR / DE) as two horizontal rows — used at the bottom of the
 * Settings dropdown, the login-page menu and the phone More menu, so there is never a menu in a menu.
 */
export const PreferencesRows: React.FC<{ showDivider?: boolean }> = ({ showDivider = true }) => {
  const { mode, setMode } = useTheme();
  const { t, lang, setLanguage } = useI18n();
  const P = useAgentChatPalette();
  return (
    <Box sx={{ px: 2, pb: 1 }} onClick={(event) => event.stopPropagation()}>
      {showDivider && <Divider sx={{ mx: -2, mt: 0.5, mb: 0.5 }} />}
      <Row label={t('Theme')}>
        {THEME_OPTIONS.map(({ mode: value, label, Icon }) => (
          <Tooltip key={value} title={t(label)} placement="top">
            <ButtonBase
              onClick={() => setMode(value)}
              aria-label={t(label)}
              aria-pressed={mode === value}
              sx={segmentSx(mode === value, P.accentText)}
            >
              <Icon />
            </ButtonBase>
          </Tooltip>
        ))}
      </Row>
      <Row label={t('Language')}>
        {LANGUAGES.map((l) => (
          <Tooltip key={l.code} title={l.name} placement="bottom">
            <ButtonBase
              onClick={() => setLanguage(l.code)}
              aria-label={l.name}
              aria-pressed={lang === l.code}
              sx={segmentSx(lang === l.code, P.accentText)}
            >
              {l.short}
            </ButtonBase>
          </Tooltip>
        ))}
      </Row>
    </Box>
  );
};

export default PreferencesRows;
