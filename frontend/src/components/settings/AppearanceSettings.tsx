import { DarkMode, DesktopWindowsOutlined, Edit, LightMode } from '@mui/icons-material';
import { Box, ButtonBase, Card, CardContent, Typography } from '@mui/material';
import React, { useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { NOTIFY_RUNS_KEY, loadFlag, saveFlag } from '../../constants/uiPrefs';
import { CUSTOM_ID } from '../../constants/themeStore';
import { TYPOGRAPHY } from '../../constants/typography';
import { useTheme } from '../../contexts/ThemeContext';
import { useI18n } from '../../i18n/useI18n';
import BackgroundDialog from '../common/BackgroundDialog';
import { BackgroundSwatch, EditPen, useBackgroundChoices } from '../common/BackgroundPicker';
import ColourThemeDialog from '../common/ColourThemeDialog';
import SettingRow from '../common/SettingRow';

const CARDS = [
  { mode: 'light', title: 'Light', help: 'Warm grey page, white cards', Icon: LightMode },
  { mode: 'dark', title: 'Dark', help: 'Low glare for long monitoring', Icon: DarkMode },
  { mode: 'system', title: 'System', help: 'Follows your operating system', Icon: DesktopWindowsOutlined },
] as const;

const SectionTitle: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Typography sx={{ fontSize: TYPOGRAPHY.cardTitle.size, fontWeight: 600, mb: 0.5 }}>{children}</Typography>
);

/** Settings → Appearance: theme cards, colour theme, Reduce motion, Notify me. */
const AppearanceSettings: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const {
    mode,
    setMode,
    actualMode,
    colourThemes,
    activeColourThemeId,
    selectColourTheme,
    customColourTheme,
    reduceMotion,
    setReduceMotion,
    motionReduced,
    backgrounds,
    updateModeBackground,
  } = useTheme();
  const backgroundChoices = useBackgroundChoices();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [bgDialogOpen, setBgDialogOpen] = useState(false);
  const [notify, setNotify] = useState(() => loadFlag(NOTIFY_RUNS_KEY));
  const [denied, setDenied] = useState(
    typeof Notification !== 'undefined' && Notification.permission === 'denied',
  );

  const onNotify = async (on: boolean) => {
    if (on && typeof Notification !== 'undefined' && Notification.permission !== 'granted') {
      const result = await Notification.requestPermission();
      if (result !== 'granted') {
        setDenied(true);
        return;
      }
    }
    setDenied(false);
    setNotify(on);
    saveFlag(NOTIFY_RUNS_KEY, on);
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
      <Card>
        <CardContent>
          <SectionTitle>{t('Theme')}</SectionTitle>
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, mb: 1.5 }}>
            {t('The header button gives the same choice.')}
          </Typography>
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(3, 1fr)' }, gap: 1.5 }}>
            {CARDS.map(({ mode: value, title, help, Icon }) => {
              const selected = mode === value;
              return (
                <ButtonBase
                  key={value}
                  onClick={() => setMode(value)}
                  aria-pressed={selected}
                  sx={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                    gap: 0.5,
                    p: 1.5,
                    textAlign: 'left',
                    border: '1px solid',
                    borderColor: selected ? P.accent : P.borderColor,
                    bgcolor: selected ? `${P.accent}26` : P.surface,
                    borderRadius: 2,
                    '&:hover': { borderColor: P.accent },
                  }}
                >
                  <Icon sx={{ color: selected ? P.accentText : P.textSecondary }} />
                  <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 600 }}>{t(title)}</Typography>
                  <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
                    {value === 'system'
                      ? actualMode === 'dark'
                        ? t('Now dark, follows the OS')
                        : t('Now light, follows the OS')
                      : t(help)}
                  </Typography>
                </ButtonBase>
              );
            })}
          </Box>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <SectionTitle>{t('Colours')}</SectionTitle>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 1 }}>
            {colourThemes.map((theme) => {
              const selected = activeColourThemeId === theme.id;
              return (
                <ButtonBase
                  key={theme.id}
                  onClick={() => selectColourTheme(theme.id)}
                  aria-pressed={selected}
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1,
                    px: 1.5,
                    py: 0.75,
                    border: '1px solid',
                    borderColor: selected ? P.accent : P.borderColor,
                    bgcolor: selected ? `${P.accent}26` : 'transparent',
                    borderRadius: 1.5,
                    fontSize: TYPOGRAPHY.body.size,
                    color: selected ? P.accentText : P.textPrimary,
                    '&:hover': { borderColor: P.accent },
                  }}
                >
                  <Box sx={{ width: 12, height: 12, borderRadius: '50%', bgcolor: theme.accent }} />
                  {theme.id === 'gold' ? t('Gold') : theme.id === CUSTOM_ID ? t('My theme') : theme.name}
                </ButtonBase>
              );
            })}
            <ButtonBase
              onClick={() => setDialogOpen(true)}
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1,
                px: 1.5,
                py: 0.75,
                border: '1px dashed',
                borderColor: P.borderColor,
                borderRadius: 1.5,
                fontSize: TYPOGRAPHY.body.size,
                color: P.textSecondary,
                '&:hover': { borderColor: P.accent },
              }}
            >
              <Edit sx={{ fontSize: TYPOGRAPHY.body.size }} />
              {customColourTheme ? t('Edit your theme') : t('My theme')}
            </ButtonBase>
          </Box>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <SectionTitle>{t('Background')}</SectionTitle>
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, mb: 1.5 }}>
            {actualMode === 'dark' ? t('For the dark theme. The light theme keeps its own.') : t('For the light theme. The dark theme keeps its own.')}
          </Typography>
          <Box sx={{ display: 'flex', gap: 1, maxWidth: 480 }}>
            {backgroundChoices.map((choice, i) => {
              const selected = backgrounds[actualMode].img === choice.id;
              return (
                <Box key={choice.id} sx={{ position: 'relative', flex: '1 1 0', minWidth: 0, display: 'flex' }}>
                  <ButtonBase
                    onClick={() => updateModeBackground({ img: choice.id })}
                    aria-label={choice.label}
                    aria-pressed={selected}
                    sx={{
                      width: '100%',
                      aspectRatio: '16 / 9',
                      p: '3px',
                      border: '1px solid',
                      borderColor: selected ? P.accent : P.borderColor,
                      bgcolor: selected ? `${P.accent}26` : 'transparent',
                      borderRadius: 1.5,
                      '&:hover': { borderColor: P.accent },
                    }}
                  >
                    <BackgroundSwatch choice={choice} />
                  </ButtonBase>
                  {i === backgroundChoices.length - 1 && <EditPen label={t('Edit background')} onClick={() => setBgDialogOpen(true)} />}
                </Box>
              );
            })}
          </Box>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <SectionTitle>{t('Layout and motion')}</SectionTitle>
          <SettingRow
            divider
            title={t('Reduce motion')}
            description={
              motionReduced && !reduceMotion
                ? t('Your operating system already asks for reduced motion, so it applies.')
                : t('Turns off page transitions and chart animations. Your operating system setting always applies.')
            }
            checked={motionReduced}
            disabled={motionReduced && !reduceMotion}
            onChange={setReduceMotion}
          />
          <SettingRow
            title={t('Notify me when my runs finish')}
            description={
              denied
                ? t('Notifications are blocked for this site in your browser settings.')
                : t('A browser notification when a run ends while this tab is in the background.')
            }
            checked={notify}
            disabled={typeof Notification === 'undefined'}
            onChange={(on) => void onNotify(on)}
          />
        </CardContent>
      </Card>
      <ColourThemeDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
      <BackgroundDialog open={bgDialogOpen} onClose={() => setBgDialogOpen(false)} />
    </Box>
  );
};

export default AppearanceSettings;
