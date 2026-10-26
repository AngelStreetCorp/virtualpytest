import { Edit } from '@mui/icons-material';
import { Box, ButtonBase, Tooltip } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { BG_CUSTOM, BG_NONE, LIBRARY_PRESETS, libraryThumbUrl, presetUrl, presetsFor, tintColour, tintFilter } from '../../constants/themeBackgrounds';
import { FONT_SIZE_SCALE, TYPOGRAPHY } from '../../constants/typography';
import { useTheme } from '../../contexts/ThemeContext';
import { useI18n } from '../../i18n/useI18n';

export interface BackgroundChoice {
  id: string;
  label: string;
  url: string | null;
  filter: string;
}

/** The library as swatch choices, for the dialog's Library grid. */
export const LIBRARY_CHOICES: BackgroundChoice[] = LIBRARY_PRESETS.map((p) => ({ id: p.id, label: p.name, url: libraryThumbUrl(p.id), filter: 'none' }));

/** The current mode's choices (TASK-136): None, its two images (tinted live), the chosen library image if any, and the user's image if stored. */
export const useBackgroundChoices = (): BackgroundChoice[] => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const { actualMode, backgrounds, customImageUrl } = useTheme();
  const tint = backgrounds[actualMode].tint;
  const colour = tintColour(tint, P.accent);
  return [
    { id: BG_NONE, label: t('None'), url: null, filter: 'none' },
    ...presetsFor(actualMode).map((p) => ({ id: p.id, label: p.name, url: presetUrl(p.id), filter: tintFilter(p, colour) })),
    ...LIBRARY_CHOICES.filter((c) => c.id === backgrounds[actualMode].img),
    ...(customImageUrl ? [{ id: BG_CUSTOM, label: t('Your image'), url: customImageUrl, filter: 'none' }] : []),
  ];
};

/** The image (or "None") inside a choice button; the tint sits on this layer, never on the ring. */
export const BackgroundSwatch: React.FC<{ choice: BackgroundChoice }> = ({ choice }) => {
  const P = useAgentChatPalette();
  return (
    <Box
      sx={{
        width: '100%',
        height: '100%',
        borderRadius: 0.5,
        display: 'grid',
        placeItems: 'center',
        fontSize: TYPOGRAPHY.microMeta.size,
        fontFamily: 'inherit',
        fontWeight: 400,
        color: P.textMuted,
        ...(choice.url
          ? { backgroundImage: `url("${choice.url}")`, backgroundSize: 'cover', backgroundPosition: 'center', filter: choice.filter }
          : { bgcolor: P.surface }),
      }}
    >
      {choice.url ? null : choice.label}
    </Box>
  );
};

/** The round pencil on the corner of a menu button (Colours: Edit your theme; Background: Edit background). */
export const EditPen: React.FC<{ label: string; onClick: () => void }> = ({ label, onClick }) => {
  const P = useAgentChatPalette();
  return (
    <Tooltip title={label} placement="bottom">
      <ButtonBase
        onClick={(e) => {
          e.stopPropagation();
          onClick();
        }}
        aria-label={label}
        sx={{
          position: 'absolute',
          top: -4,
          right: -4,
          width: 20,
          height: 20,
          borderRadius: '50%',
          bgcolor: P.surface,
          border: `1px solid ${P.borderColor}`,
          color: P.textSecondary,
          '& svg': { fontSize: FONT_SIZE_SCALE.sm },
        }}
      >
        <Edit />
      </ButtonBase>
    </Tooltip>
  );
};
