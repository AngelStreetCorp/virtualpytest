/**
 * Colours of the companion strip and its cards. The strip sits on the live video, which is dark in both
 * app themes, so it always takes the dark palette (UI_STYLE.md tokens), never the light one.
 */
import { AGENT_CHAT_PALETTE } from '../../../frontend/src/constants/agentChatTheme';

export const O = AGENT_CHAT_PALETTE;
/** The strip itself: the page background, 90 % opaque over the video. */
export const OVERLAY_BG = `${O.background}e6`;
/** A tinted pill (entity chips, speaker chips). */
export const chipSx = { color: O.textPrimary, backgroundColor: O.hoverBg, border: `1px solid ${O.borderColor}`, fontSize: 11 };
