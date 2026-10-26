import { Box, Button, ButtonBase, Dialog, DialogActions, DialogContent, DialogTitle, Slider, Tooltip, Typography } from '@mui/material';
import React, { useEffect, useRef, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { AppIcon, StatusText } from '../../constants/icons';
import {
  BG_CUSTOM,
  BG_NONE,
  BackgroundSettings,
  DEFAULT_MODE_BACKGROUND,
  IMAGE_TRANSPARENCY_MAX,
  TINT_COLOURS,
  TINT_ORIGINAL,
  TINT_THEME,
  UploadError,
  processUpload,
} from '../../constants/themeBackgrounds';
import { TYPOGRAPHY } from '../../constants/typography';
import { MENU_ICON_SERIES } from '../../constants/uiPrefs';
import { useTheme } from '../../contexts/ThemeContext';
import { useI18n } from '../../i18n/useI18n';

import { BackgroundSwatch, LIBRARY_CHOICES, useBackgroundChoices } from './BackgroundPicker';
import { dangerButtonSx, neutralButtonSx, primaryButtonSx } from './PageChrome';

interface Props {
  open: boolean;
  onClose: () => void;
}

const LABEL_WIDTH = 150;

const DialogRow: React.FC<{ label: string; top?: boolean; children: React.ReactNode }> = ({ label, top, children }) => (
  <Box sx={{ display: 'flex', alignItems: top ? 'flex-start' : 'center', gap: 1, mb: 1.5 }}>
    <Typography sx={{ width: LABEL_WIDTH, flexShrink: 0, whiteSpace: 'nowrap', fontSize: TYPOGRAPHY.caption.size, color: 'text.secondary', pt: top ? 0.75 : 0 }}>
      {label}
    </Typography>
    <Box sx={{ flex: 1, minWidth: 0 }}>{children}</Box>
  </Box>
);

/**
 * Edit background (TASK-136): the current mode's image, tint, image and card transparency, and the
 * user's one image. Every change applies live to the page behind (no dimmed backdrop); Cancel puts
 * the settings and the image back, Save keeps them (the image is written to IndexedDB on Save only).
 */
const BackgroundDialog: React.FC<Props> = ({ open, onClose }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const {
    mode,
    actualMode,
    backgrounds,
    setBackgrounds,
    updateModeBackground,
    customImage,
    setCustomImage,
    commitCustomImage,
    menuIconColour,
    setMenuIconColour,
  } = useTheme();
  const choices = useBackgroundChoices();
  const snapshot = useRef<{ settings: BackgroundSettings; image: Blob | null; icons: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [note, setNote] = useState<UploadError | 'save' | 'small' | null>(null);
  const [busy, setBusy] = useState(false);
  const [libOpen, setLibOpen] = useState(false);

  // Snapshot only when the dialog opens.
  useEffect(() => {
    if (!open) return;
    snapshot.current = { settings: backgrounds, image: customImage, icons: menuIconColour };
    setNote(null);
    setLibOpen(false);
  }, [open]);

  const cur = backgrounds[actualMode];
  const hasImage = cur.img !== BG_NONE;

  const cancel = () => {
    if (snapshot.current) {
      setBackgrounds(snapshot.current.settings);
      setCustomImage(snapshot.current.image);
      setMenuIconColour(snapshot.current.icons);
    }
    onClose();
  };
  const save = async () => {
    if (customImage !== snapshot.current?.image) {
      setBusy(true);
      const ok = await commitCustomImage();
      setBusy(false);
      if (!ok) {
        setNote('save');
        return;
      }
    }
    onClose();
  };
  const reset = () => {
    setBackgrounds({ ...backgrounds, [actualMode]: { ...DEFAULT_MODE_BACKGROUND } });
    setMenuIconColour('default');
  };

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    const result = await processUpload(file);
    setBusy(false);
    if (typeof result === 'string') {
      setNote(result);
      return;
    }
    setNote(result.small ? 'small' : null);
    setCustomImage(result.blob);
    setBackgrounds({ ...backgrounds, customLuma: result.luma, [actualMode]: { ...cur, img: BG_CUSTOM } });
  };
  const removeImage = () => {
    setCustomImage(null);
    const rest: BackgroundSettings = { ...backgrounds };
    delete rest.customLuma;
    const clear = (m: 'light' | 'dark') => (rest[m].img === BG_CUSTOM ? { ...rest[m], img: BG_NONE } : rest[m]);
    setBackgrounds({ ...rest, light: clear('light'), dark: clear('dark') });
    setNote(null);
  };

  const noteText: Record<UploadError | 'save' | 'small', string> = {
    'not-image': t('This file is not an image.'),
    'too-big': t('The image is larger than 15 MB.'),
    unreadable: t('This image could not be read.'),
    save: t('Your browser could not store the image.'),
    small: t('Smaller than 1920 × 1080: it may look soft.'),
  };
  const title = `${t('Edit background')} · ${actualMode === 'dark' ? t('Dark') : t('Light')}${mode === 'system' ? ` (${t('system')})` : ''}`;
  // Every row is always there (same dialog height for every image); a row that does not apply is dimmed and inert.
  const dimSx = (off: boolean) => (off ? { opacity: 0.4, pointerEvents: 'none' as const } : {});
  const tintButtonSx = (on: boolean) => ({
    height: 28,
    px: 1,
    gap: 0.75,
    borderRadius: 1,
    border: '1px solid',
    borderColor: on ? P.accentText : P.borderColor,
    bgcolor: on ? P.selectedBg : 'transparent',
    color: on ? P.accentText : P.textPrimary,
    fontSize: TYPOGRAPHY.caption.size,
    flexShrink: 0,
  });

  return (
    <>
    <Dialog
      open={open}
      onClose={cancel}
      maxWidth={false}
      // Centred like the theme dialog; the page behind is the live preview, so no dimming.
      slotProps={{ backdrop: { invisible: true } }}
      PaperProps={{ sx: { width: 640, maxWidth: 'calc(100% - 32px)' } }}
    >
      <DialogTitle sx={{ pb: 0.5 }}>{title}</DialogTitle>
      <DialogContent>
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, mb: 2 }}>
          {t('Applies to the theme you are on. Changes show live behind.')}
        </Typography>
        <DialogRow label={t('Image')} top>
          <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap' }}>
            {choices.map((c) => {
              const on = cur.img === c.id;
              return (
                <Tooltip key={c.id} title={c.label} placement="bottom">
                  <ButtonBase
                    onClick={() => updateModeBackground({ img: c.id })}
                    aria-label={c.label}
                    aria-pressed={on}
                    sx={{
                      width: 64,
                      height: 38,
                      p: '3px',
                      borderRadius: 1,
                      border: '1px solid',
                      borderColor: on ? P.accentText : P.borderColor,
                      outline: on ? `1px solid ${P.accentText}` : 'none',
                      bgcolor: on ? P.selectedBg : 'transparent',
                    }}
                  >
                    <BackgroundSwatch choice={c} />
                  </ButtonBase>
                </Tooltip>
              );
            })}
            <Button
              size="small"
              variant="outlined"
              startIcon={<AppIcon name="image" />}
              onClick={() => setLibOpen(true)}
              sx={{ ...neutralButtonSx(P), height: 38 }}
            >
              {t('Library')}
            </Button>
          </Box>
        </DialogRow>
        <Box sx={dimSx(!hasImage)} aria-disabled={!hasImage}>
          <DialogRow label={t('Image tint')}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.875, flexWrap: 'nowrap' }}>
              <Tooltip title={t('The image in its own colours')} placement="bottom">
                <ButtonBase onClick={() => updateModeBackground({ tint: TINT_ORIGINAL })} aria-pressed={cur.tint === TINT_ORIGINAL} sx={tintButtonSx(cur.tint === TINT_ORIGINAL)}>
                  {t('Original')}
                </ButtonBase>
              </Tooltip>
              <Tooltip title={t('Follows the Colours choice')} placement="bottom">
                <ButtonBase onClick={() => updateModeBackground({ tint: TINT_THEME })} aria-pressed={cur.tint === TINT_THEME} sx={tintButtonSx(cur.tint === TINT_THEME)}>
                  <Box sx={{ width: 12, height: 12, borderRadius: '50%', bgcolor: P.accent }} />
                  {t('Theme')}
                </ButtonBase>
              </Tooltip>
              {TINT_COLOURS.filter((c) => c.toLowerCase() !== P.accent.toLowerCase()).map((c) => {
                const on = cur.tint.toLowerCase() === c;
                return (
                  <ButtonBase
                    key={c}
                    onClick={() => updateModeBackground({ tint: c })}
                    aria-label={c}
                    aria-pressed={on}
                    sx={{
                      width: 22,
                      height: 22,
                      flexShrink: 0,
                      borderRadius: '50%',
                      bgcolor: c,
                      outline: on ? `2px solid ${P.textPrimary}` : 'none',
                      outlineOffset: 2,
                    }}
                  />
                );
              })}
            </Box>
          </DialogRow>
        </Box>
        <Box sx={dimSx(!hasImage)} aria-disabled={!hasImage}>

            <DialogRow label={t('Image transparency')}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                <Slider
                  size="small"
                  min={0}
                  max={IMAGE_TRANSPARENCY_MAX}
                  value={cur.imageTransparency}
                  onChange={(_, v) => updateModeBackground({ imageTransparency: v as number })}
                  aria-label={t('Image transparency')}
                />
                <Typography sx={{ width: 48, flexShrink: 0, whiteSpace: 'nowrap', textAlign: 'right', fontSize: TYPOGRAPHY.caption.size }}>{cur.imageTransparency} %</Typography>
              </Box>
            </DialogRow>

        </Box>
        <DialogRow label={t('Icons')}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.875, flexWrap: 'nowrap' }}>
            <Tooltip title={t('Menu icons in the text colour')} placement="bottom">
              <ButtonBase onClick={() => setMenuIconColour('default')} aria-pressed={menuIconColour === 'default'} sx={tintButtonSx(menuIconColour === 'default')}>
                <Box sx={{ width: 12, height: 12, borderRadius: '50%', bgcolor: P.textPrimary, border: `1px solid ${P.borderColor}` }} />
                {t('Default')}
              </ButtonBase>
            </Tooltip>
            <Tooltip title={t('Menu icons in the theme colour')} placement="bottom">
              <ButtonBase onClick={() => setMenuIconColour('theme')} aria-pressed={menuIconColour === 'theme'} sx={tintButtonSx(menuIconColour === 'theme')}>
                <Box sx={{ width: 12, height: 12, borderRadius: '50%', bgcolor: P.accentText }} />
                {t('Theme')}
              </ButtonBase>
            </Tooltip>
            {MENU_ICON_SERIES.map((n) => {
              const v = `series:${n}`;
              const on = menuIconColour === v;
              return (
                <ButtonBase
                  key={v}
                  onClick={() => setMenuIconColour(v)}
                  aria-label={P.series[n]}
                  aria-pressed={on}
                  sx={{ width: 22, height: 22, flexShrink: 0, borderRadius: '50%', bgcolor: P.series[n], outline: on ? `2px solid ${P.textPrimary}` : 'none', outlineOffset: 2 }}
                />
              );
            })}
          </Box>
        </DialogRow>
        <DialogRow label={t('Your image')} top>
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            <Button
              size="small"
              variant="outlined"
              startIcon={<AppIcon name="upload" />}
              onClick={() => fileRef.current?.click()}
              disabled={busy}
              sx={neutralButtonSx(P)}
            >
              {customImage ? t('Replace') : t('Upload')}
            </Button>
            {customImage && (
              <Button size="small" variant="outlined" onClick={removeImage} disabled={busy} sx={dangerButtonSx(P)}>
                {t('Remove')}
              </Button>
            )}
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, whiteSpace: 'nowrap' }}>{t('16:9 (2560 × 1440)')}</Typography>
          </Box>
          {note && (
            <Box sx={{ mt: 0.5 }}>
              <StatusText level={note === 'small' ? 'warning' : 'error'}>{noteText[note]}</StatusText>
            </Box>
          )}
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            hidden
            onChange={(e) => {
              void onFile(e.target.files?.[0]);
              e.target.value = '';
            }}
          />
        </DialogRow>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button variant="outlined" onClick={reset} sx={neutralButtonSx(P)}>
          {t('Reset')}
        </Button>
        <Button variant="outlined" onClick={cancel} sx={neutralButtonSx(P)}>
          {t('Cancel')}
        </Button>
        <Button variant="contained" onClick={() => void save()} disabled={busy} sx={primaryButtonSx(P)}>
          {t('Save')}
        </Button>
      </DialogActions>
    </Dialog>

      {/* The library is its own fixed-size dialog: this one never grows or moves, and the page behind stays the live preview. */}
      <Dialog
        open={libOpen}
        onClose={() => setLibOpen(false)}
        maxWidth={false}
        transitionDuration={0}
        slotProps={{ backdrop: { invisible: true } }}
        PaperProps={{ sx: { width: 640, maxWidth: 'calc(100% - 32px)', height: 440, maxHeight: 'calc(100% - 32px)' } }}
      >
        <DialogTitle sx={{ pb: 1 }}>{t('Library')}</DialogTitle>
        <DialogContent sx={{ overflowY: 'scroll' }}>
          <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 1, alignContent: 'start' }}>
            {LIBRARY_CHOICES.map((c) => {
              const on = cur.img === c.id;
              return (
                <Tooltip key={c.id} title={c.label} placement="bottom">
                  <ButtonBase
                    onClick={() => updateModeBackground({ img: c.id })}
                    aria-label={c.label}
                    aria-pressed={on}
                    sx={{
                      aspectRatio: '16 / 9',
                      p: '3px',
                      borderRadius: 1,
                      border: '1px solid',
                      borderColor: on ? P.accentText : P.borderColor,
                      outline: on ? `1px solid ${P.accentText}` : 'none',
                      bgcolor: on ? P.selectedBg : P.surface,
                    }}
                  >
                    <BackgroundSwatch choice={c} />
                  </ButtonBase>
                </Tooltip>
              );
            })}
          </Box>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button variant="contained" onClick={() => setLibOpen(false)} sx={primaryButtonSx(P)}>
            {t('Close')}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
};

export default BackgroundDialog;
