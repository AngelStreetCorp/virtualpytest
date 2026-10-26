import { Box, Button, Popover, Tooltip, Typography } from '@mui/material';
import ExpandLessOutlinedIcon from '@mui/icons-material/ExpandLessOutlined';
import ExpandMoreOutlinedIcon from '@mui/icons-material/ExpandMoreOutlined';
import React, { useState } from 'react';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { GRID_VIEWS, customPageSize, devicePageLayouts, layoutsForCount } from '../../../constants/deviceLayouts';
import { useI18n } from '../../../i18n/useI18n';
import type { DeviceView, ViewId } from '../../../types/pages/deviceLayout.types';

import { LayoutGlyph } from './LayoutGlyph';
import { TYPOGRAPHY } from '../../../constants/typography';

interface ViewMenuProps {
  view: DeviceView;
  onChange: (id: ViewId) => void;
  onResetOrder?: () => void;
  /** Phones: only the scrolling grid sizes. */
  gridOnly?: boolean;
  /** Group tile: only the layouts (no page size). */
  layoutsOnly?: boolean;
  /** Group tile: offer only the layouts that suit this many devices. */
  itemCount?: number;
  /** Custom grid, remembered. Default 4×4. */
  customShape?: { cols: number; rows: number };
  onCustomShape?: (cols: number, rows: number) => void;
}

/** One View control: Grid 12/24/custom (scrolls) and the layouts that fit the screen. */
export const ViewMenu: React.FC<ViewMenuProps> = ({
  view,
  onChange,
  onResetOrder,
  gridOnly,
  layoutsOnly,
  itemCount,
  customShape,
  onCustomShape,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [colsText, setColsText] = useState(String(customShape?.cols ?? 4));
  const [rowsText, setRowsText] = useState(String(customShape?.rows ?? 4));
  const pick = (id: ViewId) => {
    onChange(id);
    setAnchor(null);
  };

  const open = (el: HTMLElement) => {
    setColsText(String(customShape?.cols ?? 4));
    setRowsText(String(customShape?.rows ?? 4));
    setAnchor(el);
  };

  const option = (v: DeviceView, caption: React.ReactNode, shortcut?: number) => (
    <Tooltip key={v.id} title={t(v.label)} placement="top">
      <Box
        component="button"
        role="menuitemradio"
        aria-checked={v.id === view.id}
        aria-label={t(v.label)}
        onClick={() => pick(v.id)}
        sx={{
          display: 'grid',
          justifyItems: 'center',
          gap: 0.5,
          p: 1,
          cursor: 'pointer',
          color: 'inherit',
          font: 'inherit',
          borderRadius: 1,
          border: `1px solid ${v.id === view.id ? P.accent : P.borderColor}`,
          bgcolor: v.id === view.id ? `${P.accent}26` : P.background,
          '&:hover': { borderColor: P.accent },
          '&:focus-visible': { outline: `2px solid ${P.accent}`, outlineOffset: 2 },
        }}
      >
        <LayoutGlyph view={v} active={v.id === view.id} />
        {caption}
        {shortcut !== undefined && (
          <Typography component="span" sx={{ fontFamily: 'monospace', fontSize: TYPOGRAPHY.microMeta.size, color: P.textMuted }}>
            {shortcut}
          </Typography>
        )}
      </Box>
    </Tooltip>
  );

  const sectionTitle = (text: string) => (
    <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, fontWeight: 600, color: P.textMuted, mb: 0.75 }}>{text}</Typography>
  );

  /** Custom view caps each axis at 9 so a tile stays wide enough to read. */
  const CUSTOM_AXIS_MIN = 1;
  const CUSTOM_AXIS_MAX = 9;

  /** Clamp + commit a single-axis value. Empty stays empty until the user
   *  finishes editing. */
  const clamp = (n: number) => Math.max(CUSTOM_AXIS_MIN, Math.min(CUSTOM_AXIS_MAX, n));

  const setAxis = (axis: 'cols' | 'rows', raw: string) => {
    // Accept only single digits 1-9. Strip anything else; if the result is
    // empty, keep it (so the user can re-type) and DON'T apply yet.
    const digits = raw.replace(/\D+/g, '');
    const next = digits.length === 0 ? '' : clamp(Number(digits[0])).toString();
    if (axis === 'cols') {
      setColsText(next);
      if (next) applyCustom(next, rowsText);
    } else {
      setRowsText(next);
      if (next) applyCustom(colsText, next);
    }
  };

  const stepAxis = (axis: 'cols' | 'rows', delta: number) => {
    const current = axis === 'cols' ? colsText : rowsText;
    const base = /^\d+$/.test(current) ? Number(current) : CUSTOM_AXIS_MIN;
    const next = clamp(base + delta).toString();
    if (axis === 'cols') {
      setColsText(next);
      applyCustom(next, rowsText);
    } else {
      setRowsText(next);
      applyCustom(colsText, next);
    }
  };

  const applyCustom = (colsRaw: string, rowsRaw: string) => {
    if (!/^\d+$/.test(colsRaw) || !/^\d+$/.test(rowsRaw) || !onCustomShape) return;
    const cols = clamp(Number(colsRaw));
    const rows = clamp(Number(rowsRaw));
    if (customPageSize(cols, rows) === null) return;
    onCustomShape(cols, rows);
  };

  const customValid = /^\d+$/.test(colsText) && /^\d+$/.test(rowsText)
    && Number(colsText) >= CUSTOM_AXIS_MIN && Number(colsText) <= CUSTOM_AXIS_MAX
    && Number(rowsText) >= CUSTOM_AXIS_MIN && Number(rowsText) <= CUSTOM_AXIS_MAX
    && customPageSize(Number(colsText), Number(rowsText)) !== null;
  const customActive = view.kind === 'grid' && view.id === 'gridCustom';
  const buttonLabel = customActive ? `${view.glyph.cols}×${view.glyph.rows}` : t(view.label);

  const fieldSx = {
    width: 32,
    height: 22,
    p: 0,
    textAlign: 'center' as const,
    fontFamily: 'monospace',
    fontSize: TYPOGRAPHY.caption.size,
    fontWeight: 600,
    color: P.textPrimary,
    bgcolor: P.inputBg,
    border: `1px solid ${P.borderColor}`,
    borderRadius: '4px',
    '&:focus-visible': { outline: `2px solid ${P.accent}`, outlineOffset: 2 },
    // Hide the native number-input spin buttons — we have our own tick
    // buttons beside the field, and the native ones look out of place.
    '&::-webkit-inner-spin-button, &::-webkit-outer-spin-button': {
      WebkitAppearance: 'none',
      margin: 0,
    },
    MozAppearance: 'textfield',
  };

  /** One input + up/down tick. 14 px wide, native size disabled, ticks
   *  step by 1 and clamp to [1, 9]. The button is its own focusable
   *  target so a screen reader reads "Columns: 4, increment, decrement". */
  const axisField = (
    axis: 'cols' | 'rows',
    label: string,
  ) => {
    const value = axis === 'cols' ? colsText : rowsText;
    return (
      <Box
        component="input"
        aria-label={label}
        type="number"
        inputMode="numeric"
        min={CUSTOM_AXIS_MIN}
        max={CUSTOM_AXIS_MAX}
        step={1}
        value={value}
        placeholder="4"
        onClick={(e: React.MouseEvent) => e.stopPropagation()}
        onFocus={(e: React.FocusEvent<HTMLInputElement>) => e.target.select()}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setAxis(axis, e.target.value)}
        onBlur={() => {
          // On blur, if the value is empty, restore the saved shape; if it's
          // out of range, clamp it visibly.
          if (!/^\d+$/.test(value)) {
            const restore = String(customShape?.[axis] ?? 4);
            if (axis === 'cols') setColsText(restore); else setRowsText(restore);
          }
        }}
        sx={fieldSx}
      />
    );
  };

  const tickButtons = (
    axis: 'cols' | 'rows',
    label: string,
  ) => {
    const value = axis === 'cols' ? colsText : rowsText;
    const numeric = /^\d+$/.test(value) ? Number(value) : null;
    const atMin = numeric !== null && numeric <= CUSTOM_AXIS_MIN;
    const atMax = numeric !== null && numeric >= CUSTOM_AXIS_MAX;
    const tickSx = {
      width: 16,
      height: 10,
      p: 0,
      minWidth: 0,
      minHeight: 0,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      cursor: atMin || atMax ? 'not-allowed' : 'pointer',
      color: atMin || atMax ? P.textMuted : P.textSecondary,
      opacity: atMin || atMax ? 0.55 : 1,
      bgcolor: 'transparent',
      border: 0,
      borderLeft: `1px solid ${P.borderColor}`,
      lineHeight: 1,
      '&:hover': (atMin || atMax) ? {} : { color: P.accent, bgcolor: `${P.accent}14` },
      '&:focus-visible': { outline: `2px solid ${P.accent}`, outlineOffset: -2 },
    };
    return (
      <Box
        aria-label={`${label} tick`}
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'stretch',
          justifyContent: 'center',
          height: 22,
          border: `1px solid ${P.borderColor}`,
          borderRadius: '4px',
          overflow: 'hidden',
          ml: -0.75,
          bgcolor: P.inputBg,
        }}
      >
        <Box
          component="button"
          type="button"
          aria-label={`${label} increment`}
          tabIndex={atMax ? -1 : 0}
          disabled={atMax}
          onClick={(e: React.MouseEvent) => {
            e.stopPropagation();
            if (!atMax) stepAxis(axis, +1);
          }}
          sx={tickSx}
        >
          <ExpandLessOutlinedIcon sx={{ fontSize: '0.625rem' /* ui-ok: no-literal-font-size — 10 px chevron for ±1 stepper */ }} aria-hidden />
        </Box>
        <Box
          component="button"
          type="button"
          aria-label={`${label} decrement`}
          tabIndex={atMin ? -1 : 0}
          disabled={atMin}
          onClick={(e: React.MouseEvent) => {
            e.stopPropagation();
            if (!atMin) stepAxis(axis, -1);
          }}
          sx={{ ...tickSx, borderTop: `1px solid ${P.borderColor}`, borderLeft: 0 }}
        >
          <ExpandMoreOutlinedIcon sx={{ fontSize: '0.625rem' /* ui-ok: no-literal-font-size — 10 px chevron for ±1 stepper */ }} aria-hidden />
        </Box>
      </Box>
    );
  };

  const layouts = itemCount ? layoutsForCount(itemCount) : devicePageLayouts();

  return (
    <>
      <Button
        size="small"
        variant="outlined"
        onClick={(e) => open(e.currentTarget)}
        aria-haspopup="menu"
        aria-expanded={Boolean(anchor)}
        aria-label={t('View')}
        sx={{ height: 32, flexShrink: 0, gap: 1, textTransform: 'none', whiteSpace: 'nowrap' }}
      >
        <Typography component="span" sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textMuted }}>
          {t('View')}
        </Typography>
        <LayoutGlyph view={view} active width={28} />
        <Typography component="span" sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textPrimary }}>
          {buttonLabel}
        </Typography>
      </Button>
      <Popover
        open={Boolean(anchor)}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        slotProps={{ paper: { sx: { p: 1.5, width: 'min(470px, calc(100vw - 32px))' } } }}
      >
        <Box role="menu" aria-label={t('View')}>
          {!layoutsOnly && (
            <Box sx={{ mb: gridOnly ? 0 : 1.5 }}>
              {sectionTitle(t('Grid · scrolls · devices per page'))}
              <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1 }}>
                {GRID_VIEWS.filter((v) => !v.custom).map((v) =>
                  option(
                    v,
                    <Typography component="span" sx={{ fontFamily: 'monospace', fontWeight: 600, fontSize: TYPOGRAPHY.body.size }}>
                      {v.pageSize}
                    </Typography>,
                  ),
                )}
                {onCustomShape && (
                  <Box
                    role="menuitemradio"
                    aria-checked={customActive}
                    aria-label={t('Custom')}
                    onClick={() => applyCustom(colsText, rowsText)}
                    sx={{
                      display: 'grid',
                      justifyItems: 'center',
                      alignContent: 'center',
                      gap: 0.5,
                      p: 1,
                      cursor: 'pointer',
                      borderRadius: 1,
                      border: `1px solid ${customActive ? P.accent : P.borderColor}`,
                      bgcolor: customActive ? `${P.accent}26` : P.background,
                      '&:hover': { borderColor: P.accent },
                    }}
                  >
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, height: 30 }}>
                      {axisField('cols', t('Columns'))}
                      {tickButtons('cols', t('Columns'))}
                      <Typography component="span" sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>×</Typography>
                      {axisField('rows', t('Rows'))}
                      {tickButtons('rows', t('Rows'))}
                    </Box>
                    <Typography
                      component="span"
                      sx={{
                        fontFamily: 'monospace',
                        fontWeight: 600,
                        fontSize: TYPOGRAPHY.body.size,
                        color: customValid ? P.textPrimary : P.error,
                      }}
                    >
                      {customValid ? t('Custom') : t('Max 100')}
                    </Typography>
                  </Box>
                )}
              </Box>
            </Box>
          )}
          {!gridOnly && (
            <Box sx={{ pt: layoutsOnly ? 0 : 1.5, borderTop: layoutsOnly ? 0 : `1px solid ${P.borderColor}` }}>
              {sectionTitle(t('Layout · fits the screen'))}
              <Box sx={{ display: 'grid', gridTemplateColumns: `repeat(${itemCount ? 5 : 4}, 1fr)`, gap: 1 }}>
                {layouts.map((v, i) =>
                  option(
                    v,
                    <Typography component="span" sx={{ fontSize: TYPOGRAPHY.microMeta.size, color: P.textSecondary, textAlign: 'center' }}>
                      {t(v.label)}
                    </Typography>,
                    layoutsOnly ? undefined : i + 1,
                  ),
                )}
              </Box>
            </Box>
          )}
          {onResetOrder && view.kind === 'layout' && (
            <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 1 }}>
              <Tooltip title={t('Drag a stream onto another to swap them. Reset puts them back in their default order.')}>
                <Button
                  size="small"
                  onClick={() => {
                    onResetOrder();
                    setAnchor(null);
                  }}
                  sx={{ textTransform: 'none', color: P.accentText }}
                >
                  {t('Reset order')}
                </Button>
              </Tooltip>
            </Box>
          )}
        </Box>
      </Popover>
    </>
  );
};
