import { DarkMode, LightMode } from '@mui/icons-material';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Slider,
  ToggleButton,
  ToggleButtonGroup,
  TextField,
  Typography,
} from '@mui/material';
import React, { useEffect, useMemo, useRef, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TONES, Tone, ContrastIssue, contrastWarnings, derivePalettes, isHex, readableOn } from '../../constants/themeEngine';
import { BG_CUSTOM, CARD_TRANSPARENCY_MAX, findPreset, presetUrl } from '../../constants/themeBackgrounds';
import { useTheme } from '../../contexts/ThemeContext';
import { useI18n } from '../../i18n/useI18n';

import { segmentedSx } from './PageChrome';
import { TYPOGRAPHY } from '../../constants/typography';

/** Normalize a user-typed hex string: strip invalid chars, prepend # if missing, cap at 7. */
const normalizeHex = (v: string): string => {
  const stripped = v.replace(/[^0-9a-fA-F]/g, '');
  const limited = stripped.slice(0, 6);
  return v.startsWith('#') ? `#${limited}` : `#${limited}`;
};

/** Font colour used for the compact hex value fields (Accent / Background). */
const HEX_FONT_COLOR = '#7376d4';

interface Props {
  open: boolean;
  onClose: () => void;
}

/** Create / edit the user's one colour theme, with a live preview drawn from the derived palette. */
const ColourThemeDialog: React.FC<Props> = ({ open, onClose }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const { customColourTheme, saveCustomColourTheme, actualMode, colourThemes, activeColourThemeId, backgrounds, updateModeBackground, customImageUrl } = useTheme();
  const cardTransparency = backgrounds[actualMode].cardTransparency;
  const startCardTransparency = useRef(cardTransparency);
  const bgPreset = findPreset(backgrounds[actualMode].img);
  const bgUrl = backgrounds[actualMode].img === BG_CUSTOM ? customImageUrl : bgPreset ? presetUrl(bgPreset.id) : null;
  // Card transparency applies live to the app and to the preview cards; Cancel puts it back.
  const seedAccent = (colourThemes.find((c) => c.id === activeColourThemeId) ?? colourThemes[0]).accent;

  const [accent, setAccent] = useState(seedAccent);
  const [tone, setTone] = useState<Tone>('neutral');
  const [background, setBackground] = useState('');
  const [previewMode, setPreviewMode] = useState<'dark' | 'light'>('dark');
  // Reset only when the dialog opens (refs/deps kept minimal on purpose).
  useEffect(() => {
    if (!open) return;
    setAccent(customColourTheme?.accent ?? seedAccent);
    setTone(customColourTheme?.tone ?? 'neutral');
    setBackground(customColourTheme?.background ?? '');
    setPreviewMode(actualMode);
    startCardTransparency.current = cardTransparency;
  }, [open]);
  const validAccent = isHex(accent);
  const bgSet = background !== '';
  const validBg = !bgSet || isHex(background);
  const palettes = useMemo(
    () => derivePalettes({ accent: validAccent ? accent : seedAccent, tone, background: bgSet && isHex(background) ? background : undefined }),
    [accent, tone, validAccent, background],
  );
  const Q = palettes[previewMode];
  // The image and card transparency belong to the mode you are on; the other mode's preview stays opaque.
  const showImage = bgUrl !== null && previewMode === actualMode;
  const cardAlpha = showImage ? 1 - cardTransparency / 100 : 1;
  const cardBg = (c: string) => (cardAlpha < 1 ? `color-mix(in srgb, ${c} ${Math.round(cardAlpha * 100)}%, transparent)` : c);
  const warnings = contrastWarnings(palettes);
  const canSave = validAccent && validBg;

  const save = () => {
    if (!canSave) return;
    saveCustomColourTheme({
      name: 'custom',
      accent: accent.toLowerCase(),
      tone,
      ...(bgSet ? { background: background.toLowerCase() } : {}),
    });
    onClose();
  };
  const cancel = () => {
    updateModeBackground({ cardTransparency: startCardTransparency.current });
    onClose();
  };
  const toneLabel = (v: Tone) => (v === 'neutral' ? t('Neutral') : v === 'warm' ? t('Warm') : t('Cool'));

  return (
    <Dialog open={open} onClose={cancel} maxWidth="sm" fullWidth>
      <DialogTitle>{t('Edit your theme')}</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', gap: 2.5, flexWrap: 'wrap', pt: 0.5 }}>
          <Box sx={{ flex: '1 1 200px', display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Box>
              <Typography variant="caption" color="text.secondary">
                {t('Accent')}
              </Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                <input
                  type="color"
                  aria-label={t('Accent')}
                  value={validAccent ? accent : seedAccent}
                  onChange={(e) => setAccent(e.target.value)}
                  style={{ width: 36, height: 28, padding: 0, border: `1px solid ${P.borderColor}`, borderRadius: 6, background: 'none', cursor: 'pointer' }}
                />
                <TextField
                  value={accent}
                  onChange={(e) => setAccent(normalizeHex(e.target.value))}
                  size="small"
                  error={!validAccent}
                  inputProps={{ maxLength: 7, style: { fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size, color: HEX_FONT_COLOR }, 'aria-label': t('Accent') }}
                  sx={{ width: 96 }}
                />
              </Box>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                {t('Background')}
              </Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                <input
                  type="color"
                  aria-label={t('Background')}
                  value={bgSet && isHex(background) ? background : palettes.dark.background}
                  onChange={(e) => setBackground(e.target.value)}
                  style={{ width: 36, height: 28, padding: 0, border: `1px solid ${P.borderColor}`, borderRadius: 6, background: 'none', cursor: 'pointer' }}
                />
                <TextField
                  value={background}
                  placeholder={palettes.dark.background}
                  onChange={(e) => setBackground(normalizeHex(e.target.value.trim()))}
                  size="small"
                  error={!validBg}
                  inputProps={{ maxLength: 7, style: { fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size, color: HEX_FONT_COLOR }, 'aria-label': t('Background') }}
                  sx={{ width: 96 }}
                />
                <Button size="small" onClick={() => setBackground('')} disabled={!bgSet}>
                  {t('Auto')}
                </Button>
              </Box>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                {t('Tone')}
              </Typography>
              <Box sx={{ mt: 0.5 }}>
                <ToggleButtonGroup
                  exclusive
                  size="small"
                  value={tone}
                  onChange={(_, v: Tone | null) => v && setTone(v)}
                  sx={segmentedSx(P, 'sm')}
                >
                  {TONES.map((v) => (
                    <ToggleButton key={v} value={v}>
                      {toneLabel(v)}
                    </ToggleButton>
                  ))}
                </ToggleButtonGroup>
              </Box>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                {t('Card transparency')}
              </Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 0.5 }}>
                <Slider
                  size="small"
                  min={0}
                  max={CARD_TRANSPARENCY_MAX}
                  value={cardTransparency}
                  onChange={(_, v) => updateModeBackground({ cardTransparency: v as number })}
                  aria-label={t('Card transparency')}
                />
                <Typography sx={{ width: 40, flexShrink: 0, textAlign: 'right', fontSize: TYPOGRAPHY.caption.size }}>{cardTransparency} %</Typography>
              </Box>
              {!showImage && (
                <Typography variant="caption" color="text.secondary">
                  {t('Cards show the image behind them. Pick an image in Edit background to see it.')}
                </Typography>
              )}
            </Box>
            {warnings.map((w: ContrastIssue) => (
              <Typography key={w} variant="caption" sx={{ color: P.warning }}>
                {w === 'button'
                  ? t('The button text may be hard to read on this accent colour.')
                  : w === 'accent'
                    ? t('This accent colour is almost invisible on a light page.')
                    : t('Body text may be hard to read on this background.')}
              </Typography>
            ))}
          </Box>

          <Box sx={{ flex: '1 1 240px', display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <Typography variant="caption" color="text.secondary">
                {t('Preview')}
              </Typography>
              <ToggleButtonGroup
                exclusive
                size="small"
                value={previewMode}
                onChange={(_, v: 'dark' | 'light' | null) => v && setPreviewMode(v)}
                sx={segmentedSx(P, 'sm')}
              >
                <ToggleButton value="light" aria-label={t('Light')}>
                  <LightMode sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
                </ToggleButton>
                <ToggleButton value="dark" aria-label={t('Dark')}>
                  <DarkMode sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
                </ToggleButton>
              </ToggleButtonGroup>
            </Box>
            <Box
              data-testid="theme-preview"
              sx={{
                position: 'relative',
                bgcolor: Q.background,
                ...(showImage ? { backgroundImage: `url(${bgUrl})`, backgroundSize: 'cover', backgroundPosition: 'center' } : {}),
                border: `1px solid ${Q.borderColor}`,
                borderRadius: 2,
                overflow: 'hidden',
                color: Q.textPrimary,
              }}
            >
              <Box sx={{ position: 'relative', bgcolor: cardBg(Q.surface), borderBottom: `1px solid ${Q.borderColor}`, px: 1.5, py: 0.75, display: 'flex', alignItems: 'center', gap: 1 }}>
                <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: Q.accent }} />
                <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, fontWeight: 600, color: Q.textPrimary }}>{t('My theme')}</Typography>
                <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: Q.accentText, ml: 'auto' }}>{t('Dashboard')}</Typography>
              </Box>
              <Box sx={{ position: 'relative', p: 1.25, display: 'flex', flexDirection: 'column', gap: 1 }}>
                {[
                  { label: t('Online'), color: Q.success },
                  { label: t('Failed'), color: Q.error },
                ].map((c) => (
                  <Box key={c.label} sx={{ bgcolor: cardBg(Q.surface), border: `1px solid ${Q.borderColor}`, borderRadius: 1.5, px: 1.25, py: 0.75 }}>
                    <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: Q.textSecondary }}>{t('Device')}</Typography>
                    <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, fontWeight: 600, color: c.color }}>{c.label}</Typography>
                  </Box>
                ))}
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <Box sx={{ bgcolor: Q.accent, color: readableOn(Q.accent), borderRadius: 1, px: 1.5, py: 0.5, fontSize: TYPOGRAPHY.caption.size, fontWeight: 600 }}>
                    {t('Run')}
                  </Box>
                  <Box sx={{ border: `1px solid ${Q.accent}`, color: Q.accentText, borderRadius: 1, px: 1.5, py: 0.5, fontSize: TYPOGRAPHY.caption.size, fontWeight: 600 }}>
                    {t('Cancel')}
                  </Box>
                </Box>
              </Box>
            </Box>
          </Box>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={cancel}>{t('Cancel')}</Button>
        <Button variant="contained" onClick={save} disabled={!canSave}>
          {t('Save')}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default ColourThemeDialog;
