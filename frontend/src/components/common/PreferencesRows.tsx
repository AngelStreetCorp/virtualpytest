import {
  DarkMode,
  Edit,
  ExpandMore,
  LightMode,
  DesktopWindowsOutlined,
} from "@mui/icons-material";
import {
  Box,
  ButtonBase,
  Collapse,
  Divider,
  Tooltip,
  Typography,
} from "@mui/material";
import React, { useEffect, useState } from "react";

import { useAgentChatPalette } from "../../constants/agentChatTheme";
import { FONT_IDS, FONT_NAMES, FONT_STACKS } from "../../constants/themeFonts";
import { CUSTOM_ID, type UserNavHover } from "../../constants/themeStore";
import { SIZE_IDS, SIZE_LABELS, SIZE_NAMES, SizeId } from "../../constants/typography";
import { useTheme } from "../../contexts/ThemeContext";
import { LANGUAGES } from "../../i18n";
import { useI18n } from "../../i18n/useI18n";

import BackgroundDialog from "./BackgroundDialog";
import { BackgroundSwatch, EditPen, useBackgroundChoices } from "./BackgroundPicker";
import ColourThemeDialog from "./ColourThemeDialog";
import { TYPOGRAPHY } from '../../constants/typography';

const THEME_OPTIONS = [
  { mode: "light", label: "Light", Icon: LightMode },
  { mode: "dark", label: "Dark", Icon: DarkMode },
  { mode: "system", label: "System", Icon: DesktopWindowsOutlined },
] as const;

// BUG-0572: segment buttons in the Theme/Colours/Background/Font/Size/Language/Navbar rows are
// 30 px tall and share the row width equally (TASK-136: same columns in every row; four
// Background choices fill the same total width as three Theme buttons).
const SEGMENT_HEIGHT = 30;
/** Label column, wide enough for "Background" / "Arrière-plan" / "Hintergrund". */
const LABEL_WIDTH = 76;
const SEGMENT_ICON_FONT = TYPOGRAPHY.microMeta.size;
const SIZE_SEGMENT_ICON_FONT = TYPOGRAPHY.caption.size;

// Selected = the app's gold accent, as in the top bar (accentText is the darker gold that stays
// readable on the light menu's white).
const segmentSx = (selected: boolean, gold: string) => {
  return {
    flex: "1 1 0",
    minWidth: 0,
    height: SEGMENT_HEIGHT,
    border: "1px solid",
    borderColor: selected ? gold : "divider",
    borderRadius: 1,
    color: selected ? gold : "text.secondary",
    bgcolor: selected ? "action.selected" : "transparent",
    fontFamily: "monospace",
    fontSize: TYPOGRAPHY.caption.size,
    fontWeight: 700,
    "&:hover": { borderColor: gold },
    "& svg": { fontSize: SEGMENT_ICON_FONT },
  } as const;
};

// The Size row shows S / M / L text labels. fontFamily is inherited (not monospace)
// so the letters render cleanly at the same caption font size as the other rows.
const sizeSegmentSx = (selected: boolean, gold: string) => {
  return {
    ...segmentSx(selected, gold),
    fontFamily: "inherit",
    "& svg": { fontSize: SIZE_SEGMENT_ICON_FONT },
  } as const;
};

const FONT_SAMPLE = "Aa";

/** Tiny marks for the three navbar hover styles. Names live in the tooltip. */
const NavHoverMark: React.FC<{ kind: UserNavHover }> = ({ kind }) => {
  const stroke = {
    fill: "none",
    stroke: "currentColor",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  if (kind === "underline") {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden>
        <path {...stroke} strokeWidth="1.6" opacity="0.55" d="M7 8.5h10" />
        <path {...stroke} strokeWidth="2.6" d="M5 16.5h14" />
      </svg>
    );
  }
  if (kind === "bracket") {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden>
        <path {...stroke} strokeWidth="2" d="M11 5H5.5V11" />
        <path {...stroke} strokeWidth="2" d="M13 19h5.5V13" />
      </svg>
    );
  }
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden>
      <rect
        {...stroke}
        strokeWidth="1.7"
        x="6.5"
        y="4"
        width="11"
        height="8"
        rx="1.5"
      />
      <path
        {...stroke}
        strokeWidth="1.7"
        opacity="0.7"
        d="M8 17.5c1.2 1.2 2.6 1.8 4 1.8s2.8-.6 4-1.8"
      />
    </svg>
  );
};

const Row: React.FC<{ label: string; children: React.ReactNode }> = ({
  label,
  children,
}) => (
  <Box sx={{ display: "flex", alignItems: "center", gap: 1, py: 0.5 }}>
    <Typography
      variant="caption"
      color="text.secondary"
      sx={{ width: LABEL_WIDTH, flexShrink: 0 }}
    >
      {label}
    </Typography>
    <Box sx={{ display: "flex", gap: 0.5, flex: 1, minWidth: 0 }}>{children}</Box>
  </Box>
);

/**
 * Theme and Colours stay visible. Font, Language and Navbar sit in a collapsed block under them —
 * used at the bottom of the Settings dropdown, the login-page menu and the phone More menu, so
 * there is never a menu in a menu.
 */
export const PreferencesRows: React.FC<{ showDivider?: boolean }> = ({
  showDivider = true,
}) => {
  const {
    mode,
    setMode,
    colourThemes,
    activeColourThemeId,
    selectColourTheme,
    customColourTheme,
    refreshColourThemes,
    font,
    setUserFont,
    userNavHover,
    setUserNavHover,
    size,
    setUserSize,
    actualMode,
    backgrounds,
    updateModeBackground,
  } = useTheme();
  const backgroundChoices = useBackgroundChoices();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [bgDialogOpen, setBgDialogOpen] = useState(false);
  const [extrasOpen, setExtrasOpen] = useState(false);
  // The menu opening is the moment a signed-in user may now be allowed to read the install's themes.
  useEffect(() => {
    refreshColourThemes();
  }, [refreshColourThemes]);
  const { t, lang, setLanguage } = useI18n();
  const P = useAgentChatPalette();

  const NAV_HOVER_OPTIONS: ReadonlyArray<{
    value: UserNavHover;
    label: string;
  }> = [
    { value: "underline", label: t("Underline") },
    { value: "bracket", label: t("Bracket") },
    { value: "magnetic", label: t("Magnetic") },
  ];

  return (
    <Box
      // 264 px: label column 76 px, padding 10 px each side, 8 px label→segment gap:
      // 264 - 20 - 76 - 8 = 160 px of buttons, ≈ 50 px each for three, ≈ 37 px for the
      // four Background choices (TASK-136).
      sx={{ px: 1.25, pb: 0.75, minWidth: 264 }}
      onClick={(event) => event.stopPropagation()}
    >
      {showDivider && <Divider sx={{ mx: -2, mt: 0.5, mb: 0.5 }} />}
      <Row label={t("Theme")}>
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
      <Row label={t("Colours")}>
        {colourThemes.map((theme) => {
          const isCustom = theme.id === CUSTOM_ID;
          const selected = activeColourThemeId === theme.id;
          return (
            <Box
              key={theme.id}
              sx={{ position: "relative", flex: 1, display: "flex" }}
            >
              <Tooltip
                title={theme.id === "gold" ? t("Gold") : theme.name}
                placement="bottom"
              >
                <ButtonBase
                  onClick={() => selectColourTheme(theme.id)}
                  aria-label={theme.name}
                  aria-pressed={selected}
                  sx={{ ...segmentSx(selected, P.accentText), width: "100%" }}
                >
                  <Box
                    sx={{
                      width: 10,
                      height: 10,
                      borderRadius: "50%",
                      bgcolor: theme.accent,
                    }}
                  />
                </ButtonBase>
              </Tooltip>
              {isCustom && (
                <EditPen label={t("Edit your theme")} onClick={() => setDialogOpen(true)} />
              )}
            </Box>
          );
        })}
        {!customColourTheme && (
          <Tooltip title={t("My theme")} placement="bottom">
            <ButtonBase
              onClick={() => setDialogOpen(true)}
              aria-label={t("My theme")}
              sx={{ ...segmentSx(false, P.accentText), borderStyle: "dashed", flex: 1 }}
            >
              <Edit />
            </ButtonBase>
          </Tooltip>
        )}
      </Row>
      <Row label={t("Background")}>
        {backgroundChoices.map((choice, i) => {
          const selected = backgrounds[actualMode].img === choice.id;
          return (
            <Box key={choice.id} sx={{ position: "relative", flex: 1, display: "flex", minWidth: 0 }}>
              <Tooltip title={choice.label} placement="bottom">
                <ButtonBase
                  onClick={() => updateModeBackground({ img: choice.id })}
                  aria-label={choice.label}
                  aria-pressed={selected}
                  sx={{ ...segmentSx(selected, P.accentText), width: "100%", p: "3px", fontFamily: "inherit" }}
                >
                  <BackgroundSwatch choice={choice} />
                </ButtonBase>
              </Tooltip>
              {i === backgroundChoices.length - 1 && (
                <EditPen label={t("Edit background")} onClick={() => setBgDialogOpen(true)} />
              )}
            </Box>
          );
        })}
      </Row>
      <Box
        sx={{
          mt: 1.25,
          pt: 0.75,
          borderTop: "1px solid",
          borderColor: "divider",
        }}
      >
        <ButtonBase
          onClick={() => setExtrasOpen((open) => !open)}
          aria-expanded={extrasOpen}
          aria-label={extrasOpen ? t("Collapse") : t("Expand")}
          sx={{
            width: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-start",
            gap: 1.5,
            py: 0.5,
            borderRadius: 1,
            color: "text.secondary",
          }}
        >
          <Typography
            variant="caption"
            sx={{ width: LABEL_WIDTH, flexShrink: 0, textAlign: "left" }}
          >
            {extrasOpen ? t("Less") : t("More")}
          </Typography>
          <ExpandMore
            sx={{
              fontSize: TYPOGRAPHY.cardTitle.size,
              transform: extrasOpen ? "rotate(180deg)" : "none",
              transition: "transform 180ms",
            }}
          />
        </ButtonBase>
        <Collapse in={extrasOpen}>
          <Row label={t("Font")}>
            {FONT_IDS.map((id) => (
              <Tooltip key={id} title={FONT_NAMES[id]} placement="bottom">
                <ButtonBase
                  onClick={() => setUserFont(id)}
                  aria-label={FONT_NAMES[id]}
                  aria-pressed={font === id}
                  sx={{
                    ...segmentSx(font === id, P.accentText),
                    fontFamily: FONT_STACKS[id],
                    fontSize: TYPOGRAPHY.navbarItem.size,
                  }}
                >
                  {FONT_SAMPLE}
                </ButtonBase>
              </Tooltip>
            ))}
          </Row>
          <Row label={t("Size")}>
            {SIZE_IDS.map((id: SizeId) => (
              <Tooltip key={id} title={SIZE_NAMES[id]} placement="bottom">
                <ButtonBase
                  onClick={() => setUserSize(id)}
                  aria-label={SIZE_NAMES[id]}
                  aria-pressed={size === id}
                  sx={sizeSegmentSx(size === id, P.accentText)}
                >
                  {SIZE_LABELS[id]}
                </ButtonBase>
              </Tooltip>
            ))}
          </Row>
          <Row label={t("Language")}>
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
          <Row label={t("Navbar")}>
            {NAV_HOVER_OPTIONS.map(({ value, label }) => (
              <Tooltip key={value} title={label} placement="top">
                <ButtonBase
                  onClick={() => setUserNavHover(value)}
                  aria-label={label}
                  aria-pressed={userNavHover === value}
                  sx={segmentSx(userNavHover === value, P.accentText)}
                >
                  <NavHoverMark kind={value} />
                </ButtonBase>
              </Tooltip>
            ))}
          </Row>
        </Collapse>
      </Box>
      <ColourThemeDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
      />
      <BackgroundDialog open={bgDialogOpen} onClose={() => setBgDialogOpen(false)} />

    </Box>
  );
};

export default PreferencesRows;
