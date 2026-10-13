/**
 * Custom icon set used in the rec header and a few other places where the
 * default Material Symbols look too literal (a robot, a bar+search, four
 * diagonal arrows). These four PNGs are the project standard now — any
 * new use of "camera / AI / fullscreen / AVQ" should pull from here, not
 * from `@mui/icons-material`.
 *
 * Each component matches the MUI Icon API (`fontSize`, `sx`, `className`,
 * `color`, `htmlColor`, `title`, `style`) so it drops into the same spots
 * — IconButton, Button.startIcon, Tooltip children, the feature-link list.
 *
 * The four source PNGs live in `frontend/src/assets/icons/`; Vite bundles
 * them so a tree-shake will drop any unused ones.
 */
import React from 'react';
import { Box, SxProps, Theme } from '@mui/material';

import cameraPng from '../../../assets/icons/camera.png';
import askAiSparklesPng from '../../../assets/icons/ask-ai-sparkles.png';
import fullscreenPng from '../../../assets/icons/fullscreen.png';
import avqActivityPng from '../../../assets/icons/avq-activity.png';

/** MUI-aligned props. Everything else passes through to the underlying <img>. */
export type CustomIconProps = Omit<React.ImgHTMLAttributes<HTMLImageElement>, 'src' | 'alt'> & {
  /** Mirrors MUI's `fontSize`. Default `medium`. */
  fontSize?: 'inherit' | 'small' | 'medium' | 'large';
  /** MUI `sx` for theming, sizing, color. */
  sx?: SxProps<Theme>;
};

// Match MUI's default 24/20/35 sizing so existing IconButton/Badge wrappers
// don't visually shift when we swap the icon.
const SIZES = {
  inherit: '1em',
  small: 20,
  medium: 24,
  large: 35,
} as const;

/**
 * The source artwork is centred on a 256px canvas with generous transparent
 * padding. Without compensating for that padding, a nominal 24px PNG paints at
 * only about 10px beside a true 24px MUI glyph. Keep the layout box MUI-sized
 * and scale only the image pixels so buttons and labels retain their spacing.
 */
const makeIcon = (
  src: string,
  displayName: string,
  visualScale: number,
): React.FC<CustomIconProps> => {
  const Component: React.FC<CustomIconProps> = ({
    sx,
    fontSize = 'medium',
    style,
    ...rest
  }) => (
    <Box
      component="img"
      src={src}
      alt=""
      draggable={false}
      sx={[
        {
          width: '1em',
          height: '1em',
          fontSize: SIZES[fontSize],
          display: 'inline-block',
          verticalAlign: 'middle',
          userSelect: 'none',
          flexShrink: 0,
          transform: `scale(${visualScale})`,
          transformOrigin: 'center',
        },
        ...(Array.isArray(sx) ? sx : sx ? [sx] : []),
      ]}
      style={style}
      {...rest}
    />
  );
  Component.displayName = displayName;
  return Component;
};

/** Screenshot / camera. Replaces `@mui/icons-material/CameraAlt`. */
export const CameraIcon = makeIcon(cameraPng, 'CameraIcon', 2.1);

/** AI / sparkles. Replaces `@mui/icons-material/SmartToy` everywhere AI is
 *  shown (rec header "Ask AI" button, AI Agent toggle, AI Settings, AI debug
 *  pages, agent dashboard, alerts viewer, AIGenerationModal, …). */
export const AIIcon = makeIcon(askAiSparklesPng, 'AIIcon', 2.05);

/** Open-in-fullscreen. Replaces `@mui/icons-material/OpenInFull` in every
 *  rec / controller / verification / editor surface. */
export const FullscreenIcon = makeIcon(fullscreenPng, 'FullscreenIcon', 2.3);

/** Audio/Video Quality activity. Replaces `@mui/icons-material/QueryStats` in
 *  the AVQ device link. */
export const AvqActivityIcon = makeIcon(avqActivityPng, 'AvqActivityIcon', 2.15);

export { AvqActivityIcon as QualityIcon };
export { AIIcon as AskAIIcon };
