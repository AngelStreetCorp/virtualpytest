import {
  Bolt as BoltIcon,
  DragIndicator as DragIcon,
  ExpandMore as ExpandMoreIcon,
  Star as StarIcon,
} from '@mui/icons-material';
import { Box, Chip, Divider, Popover, Tooltip, Typography } from '@mui/material';
import React, { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import {
  ALL_CATEGORIES,
  CategoryId,
  useQuickfilterConfig,
} from '../../hooks/useQuickfilterConfig';
import { hasNonDefaultProfile, profileShortName } from '../../hooks/useDeviceFilters';

/** How many chips fit in the badge row before the row caps at 2 lines. */
const MAX_ROW_HEIGHT_PX = 60; // ≈ 2 lines @ 26 px chip + 8 px row gap

/** Categories the row can render, plus their display name (used in tooltips). */
const CATEGORY_LABEL: Record<CategoryId, string> = {
  profiles: 'Profiles',
  models: 'Models',
  tags: 'Tags',
  favorites: 'Favorites',
};

export interface QuickfilterBadgeAreaProps {
  // Profiles
  uniqueProfiles: string[];
  profileCounts: Record<string, number>;
  profileFilter: string[];
  onProfileFilterChange: (value: string[]) => void;

  // Models
  uniqueDeviceModels: string[];
  deviceModelCounts: Record<string, number>;
  deviceModelFilter: string[];
  onDeviceModelFilterChange: (value: string[]) => void;

  // Tags — driven by the same `flagFilter` the toolbar's Tags dropdown writes to.
  uniqueFlags: string[];
  flagCounts: Record<string, number>;
  flagFilter: string[];
  onFlagFilterChange: (value: string[]) => void;

  // Favorites — a derived toggle on the target filter (favorite targets only).
  // The favorites chip in the row is built from the same source so a star set
  // in the toolbar lights up here. The toggle is implemented by the parent (it
  // needs the live `targetFilter` to clear-or-fill) and passed as a callback.
  favoriteTargetOptions: string[];
  onFavoritesToggle?: () => void;

  // Layout
  isMobile?: boolean;
}

interface RenderedChip {
  key: string;
  label: string;
  count?: number;
  selected: boolean;
  star?: boolean;
  onToggle: () => void;
  tooltip: string;
}

/**
 * Reserved row under the device-control toolbar (TASK-120). Up to 2 lines of
 * filter chips for whichever categories the user enabled (Profiles / Models /
 * Targets / Favorites), with a `+N more` chip when the row would overflow and a
 * gear icon to configure. Replaces the profile-only `DeviceProfileChips`.
 *
 * The chip toggles write to the same filter store `useDeviceFilters` exposes,
 * so the dropdowns in the toolbar stay in sync. The chips are the visual
 * shortcut; the dropdowns are the keyboard / multi-select path.
 */
export const QuickfilterBadgeArea: React.FC<QuickfilterBadgeAreaProps> = ({
  uniqueProfiles,
  profileCounts,
  profileFilter,
  onProfileFilterChange,
  uniqueDeviceModels,
  deviceModelCounts,
  deviceModelFilter,
  onDeviceModelFilterChange,
  uniqueFlags,
  flagCounts,
  flagFilter,
  onFlagFilterChange,
  favoriteTargetOptions,
  onFavoritesToggle,
  isMobile = false,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { categories, toggleCategory, reorder, clear } = useQuickfilterConfig();

  // ----- Build the flat chip list in the user's chosen order ------------------
  const toggleProfile = useCallback(
    (profile: string) =>
      onProfileFilterChange(
        profileFilter.includes(profile)
          ? profileFilter.filter((p) => p !== profile)
          : [...profileFilter, profile],
      ),
    [profileFilter, onProfileFilterChange],
  );
  const toggleModel = useCallback(
    (model: string) =>
      onDeviceModelFilterChange(
        deviceModelFilter.includes(model)
          ? deviceModelFilter.filter((m) => m !== model)
          : [...deviceModelFilter, model],
      ),
    [deviceModelFilter, onDeviceModelFilterChange],
  );
  const toggleTag = useCallback(
    (flag: string) =>
      onFlagFilterChange(
        flagFilter.includes(flag)
          ? flagFilter.filter((f) => f !== flag)
          : [...flagFilter, flag],
      ),
    [flagFilter, onFlagFilterChange],
  );
  // Favorites is a derived toggle on the target filter: clicking the chip clears
  // or fills the target filter with the favorite targets. The toolbar's
  // `handleToggleFavorites` (DeviceFilterBar) owns the actual mutation logic so
  // the chip and the dropdown's "Favorites" chip stay in sync — the parent passes
  // a callback that performs the same logic.
  const allFavoritesSelected = favoriteTargetOptions.length > 0;
  const toggleFavorites = useCallback(() => {
    onFavoritesToggle?.();
  }, [onFavoritesToggle]);

  const chipRows = useMemo<{ id: CategoryId; chips: RenderedChip[] }[]>(() => {
    const rows: { id: CategoryId; chips: RenderedChip[] }[] = [];

    for (const id of categories) {
      if (id === 'profiles') {
        // Skip the profiles row when every device is on the default profile
        // (same behaviour DeviceProfileChips had). The default carries no
        // filter meaning, so a single tv_app chip would just be visual noise.
        if (!hasNonDefaultProfile(uniqueProfiles)) continue;
        const chips: RenderedChip[] = uniqueProfiles.map((profile) => ({
          key: `profile:${profile}`,
          label: profileShortName(profile),
          count: profileCounts[profile] ?? 0,
          selected: profileFilter.includes(profile),
          onToggle: () => toggleProfile(profile),
          tooltip: profileFilter.includes(profile)
            ? t('Click to stop filtering on {profile}', { profile: profileShortName(profile) })
            : t('Click to show only {profile}', { profile: profileShortName(profile) }),
        }));
        rows.push({ id, chips });
      } else if (id === 'models') {
        const chips: RenderedChip[] = uniqueDeviceModels.map((model) => ({
          key: `model:${model}`,
          label: model,
          count: deviceModelCounts[model] ?? 0,
          selected: deviceModelFilter.includes(model),
          onToggle: () => toggleModel(model),
          tooltip: deviceModelFilter.includes(model)
            ? t('Click to stop filtering on {model}', { model })
            : t('Click to show only {model}', { model }),
        }));
        rows.push({ id, chips });
      } else if (id === 'tags') {
        // Skip the tags row when no device has a tag — same "nothing useful" rule
        // as profiles: a single empty-tags chip is visual noise.
        if (uniqueFlags.length === 0) continue;
        const chips: RenderedChip[] = uniqueFlags.map((flag) => ({
          key: `tag:${flag}`,
          label: flag,
          count: flagCounts[flag] ?? 0,
          selected: flagFilter.includes(flag),
          onToggle: () => toggleTag(flag),
          tooltip: flagFilter.includes(flag)
            ? t('Click to stop filtering on {tag}', { tag: flag })
            : t('Click to show only {tag}', { tag: flag }),
        }));
        rows.push({ id, chips });
      } else if (id === 'favorites') {
        if (favoriteTargetOptions.length === 0) continue; // no favorites yet — skip the row
        const chips: RenderedChip[] = [
          {
            key: 'favorites:all',
            label: t('Favorites'),
            count: favoriteTargetOptions.length,
            selected: allFavoritesSelected,
            star: true,
            onToggle: toggleFavorites,
            tooltip: allFavoritesSelected
              ? t('Click to clear the favorites filter')
              : t('Click to filter on your favorites'),
          },
        ];
        rows.push({ id, chips });
      }
    }
    return rows;
  }, [
    categories,
    uniqueProfiles,
    profileCounts,
    profileFilter,
    toggleProfile,
    uniqueDeviceModels,
    deviceModelCounts,
    deviceModelFilter,
    toggleModel,
    uniqueFlags,
    flagCounts,
    flagFilter,
    toggleTag,
    favoriteTargetOptions,
    allFavoritesSelected,
    toggleFavorites,
    t,
  ]);

  // Flatten for measurement and overflow handling. Each chip carries its row id
  // so we can re-attach the first-of-row extra margin when re-rendering.
  const flatChips = useMemo(
    () => chipRows.flatMap((row, rowIdx) => row.chips.map((chip) => ({ ...chip, rowIdx }))),
    [chipRows],
  );
  // (totalChipCount removed — the row always renders regardless of how
  // many chips exist. The bolt is the only entry point to the configure
  // popover, so even an empty selection needs to keep the row visible.)

  // ----- Measure overflow: hide chips from the right until 2 lines fit --------
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chipRefs = useRef<Map<string, HTMLElement>>(new Map());
  const [hiddenKeys, setHiddenKeys] = useState<Set<string>>(() => new Set());

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    // Reset all chips to visible for measurement.
    chipRefs.current.forEach((el) => {
      el.dataset.qfHidden = '';
    });
    // Force layout
    void container.offsetHeight;
    if (container.scrollHeight <= MAX_ROW_HEIGHT_PX) {
      // Everything fits — no overflow.
      if (hiddenKeys.size !== 0) setHiddenKeys(new Set());
      return;
    }
    // Walk right-to-left; hide each chip and re-measure until the row fits.
    const next = new Set<string>();
    const keys = flatChips.map((c) => c.key);
    for (let i = keys.length - 1; i >= 0; i--) {
      const el = chipRefs.current.get(keys[i]);
      if (!el) continue;
      el.dataset.qfHidden = 'true';
      next.add(keys[i]);
      if (container.scrollHeight <= MAX_ROW_HEIGHT_PX) break;
    }
    setHiddenKeys(next);
  }, [flatChips, hiddenKeys.size]);

  const hiddenChips = useMemo(
    () => flatChips.filter((c) => hiddenKeys.has(c.key)),
    [flatChips, hiddenKeys],
  );
  const overflowCount = hiddenChips.length;

  // ----- Popovers (overflow chip + configure) ----------------------------------
  const [overflowAnchor, setOverflowAnchor] = useState<HTMLElement | null>(null);
  const [configAnchor, setConfigAnchor] = useState<HTMLElement | null>(null);
  const closePopovers = useCallback(() => {
    setOverflowAnchor(null);
    setConfigAnchor(null);
  }, []);

  // The row is ALWAYS rendered (the bolt is the only entry point to the
  // configure popover — if we hid the row, an empty selection would trap the
  // user with no way back). Hooks above must run on every render — keep this
  // a comment rather than an early return.

  return (
    <Box
      data-testid="quickfilter-badge-area"
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        // Keep the row reserved so the grid below never shifts when chips come
        // and go. Min height covers one line; the 2-line cap kicks in when
        // there's overflow and the overflow chip eats the second line.
        minHeight: 56,
        // Top + bottom 1px lines so the row reads as a contained band even
        // when the user has cleared every category (the bolt alone was a
        // confusing blob of "what is this empty space"). Subtle borderColor
        // matches the in-popover Divider above; no rectangle outline so the
        // row still feels open to the toolbar / grid chrome on either side.
        borderTop: `1px solid ${P.borderColor}`,
        borderBottom: `1px solid ${P.borderColor}`,
        // Tiny horizontal padding so the bolt isn't glued to the left edge.
        // (No vertical padding — minHeight: 56 + box-sizing: border-box keeps
        // the row at exactly 56 px so the reserved slot in Rec.tsx doesn't
        // push the grid below.)
        px: 0.5,
      }}>
      {/* Bolt — both the row marker AND the trigger for the configure popover.
          The handler here opens the popover anchored to the bolt itself. */}
      <Tooltip
        title={t('Quickfilters — click to pick which categories appear here')}
        placement="bottom-start"
      >
        <Box
          component="button"
          data-testid="quickfilter-marker"
          onClick={(e) => setConfigAnchor(e.currentTarget)}
          sx={{
            width: 28,
            height: 28,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: '6px',
            color: P.accentText,
            backgroundColor: `${P.accent}26`,
            border: 'none',
            cursor: 'pointer',
            flexShrink: 0,
            '&:hover': { backgroundColor: `${P.accent}40` },
            '&:focus-visible': { outline: `2px solid ${P.accent}`, outlineOffset: 1 },
          }}
        >
          <BoltIcon sx={{ fontSize: 18 }} />  {/* ui-ok: no-literal-font-size — icon size, intentionally fixed px */}
        </Box>
      </Tooltip>

      {/* Wrapping chip strip — capped at 2 lines via `maxHeight + overflow:hidden`.
          On mobile we keep the row a single horizontal scroller so chips never
          wrap into 5+ lines (the same fallback `DeviceProfileChips` had).
          Each chip carries a data-qf-hidden attribute set by the layout effect
          above; we read it as the visibility rule below. */}
      <Box
        ref={containerRef}
        data-testid="quickfilter-chips"
        sx={{
          display: 'flex',
          flexWrap: isMobile ? 'nowrap' : 'wrap',
          alignItems: 'center',
          gap: '6px 8px',
          flex: 1,
          minWidth: 0,
          maxHeight: 100, // 2 lines × (26 chip + 8 row gap) + small grace
          overflowX: isMobile ? 'auto' : 'hidden',
          overflowY: 'hidden',
          paddingRight: 0.5,
          scrollbarWidth: 'none',
          '&::-webkit-scrollbar': { display: 'none' },
          // Subtle "new group" hint: first chip of every category after the first.
          // `+6px` left margin on a chip whose preceding sibling belongs to a
          // different category, so the eye reads the boundary without a divider.
          '& [data-qf-chip]:not([data-qf-first-in-row="true"])': {
            // no per-chip selector here — handled inline below via data attrs
          },
          '& [data-qf-chip][data-qf-hidden="true"]': {
            display: 'none !important',
          },
        }}
      >
        {flatChips.map((chip, i) => {
          const prev = flatChips[i - 1];
          const firstInRow = i === 0 || prev.rowIdx !== chip.rowIdx;
          return (
            <Tooltip key={chip.key} title={chip.tooltip}>
              <Chip
                // Use a span wrapper so Tooltip can attach without breaking
                // the Chip's click target.
                data-qf-chip=""
                data-qf-first-in-row={firstInRow ? 'true' : 'false'}
                ref={(el: HTMLElement | null) => {
                  if (el) chipRefs.current.set(chip.key, el);
                  else chipRefs.current.delete(chip.key);
                }}
                size="small"
                label={
                  <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
                    {chip.star && (
                      <StarIcon
                        fontSize="inherit"
                        sx={{ color: chip.selected ? P.onAccent : P.gold, mr: 0.25 }}
                      />
                    )}
                    <span>{chip.label}</span>
                    {chip.count !== undefined && (
                      <span
                        style={{
                          color: chip.selected ? P.onAccent : P.accentText,
                          fontWeight: 700,
                          opacity: chip.selected ? 0.75 : 1,
                          marginLeft: 2,
                        }}
                      >
                        {chip.count}
                      </span>
                    )}
                  </Box>
                }
                onClick={chip.onToggle}
                sx={{
                  height: 26,
                  fontSize: TYPOGRAPHY.caption.size,
                  fontFamily: 'monospace',
                  fontWeight: 600,
                  cursor: 'pointer',
                  flexShrink: 0,
                  border: `1px solid ${P.accent}`,
                  bgcolor: chip.selected ? P.accent : `${P.accent}22`,
                  color: chip.selected ? P.onAccent : P.textPrimary,
                  // Subtle category boundary — +6px before the first chip of
                  // every category after the first. Done via a `data-qf-first-in-row`
                  // attribute rather than `.cat-start` class so a chip can
                  // re-classify when categories reorder without a remount.
                  marginLeft: firstInRow && i !== 0 ? '6px !important' : 0,
                  // MUI paints a grey focus/hover layer over a clickable chip;
                  // keep the selected gold.
                  '&:hover, &:focus, &.Mui-focusVisible': chip.selected
                    ? { bgcolor: P.accent, filter: 'brightness(1.1)' }
                    : { borderColor: P.accent, bgcolor: `${P.accent}40` },
                }}
              />
            </Tooltip>
          );
        })}
      </Box>

      {/* Overflow chip — only when something is clipped. */}
      {overflowCount > 0 && (
        <Tooltip title={t('Show {count} more hidden badges', { count: overflowCount })}>
          <Chip
            data-testid="quickfilter-overflow"
            size="small"
            label={
              <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
                <span>{`+${overflowCount}`}</span>
                <span>{t('more')}</span>
                <ExpandMoreIcon fontSize="inherit" />
              </Box>
            }
            onClick={(e) => setOverflowAnchor(e.currentTarget)}
            sx={{
              height: 26,
              fontFamily: 'monospace',
              fontWeight: 600,
              fontSize: TYPOGRAPHY.caption.size,
              flexShrink: 0,
              border: `1px solid ${P.borderColor}`,
              bgcolor: P.hoverBg,
              color: P.textSecondary,
              '&:hover': { bgcolor: P.inputBg, color: P.textPrimary },
            }}
          />
        </Tooltip>
      )}

      {/* (The bolt icon on the left is the only entry point — no separate gear.) */}

      {/* Overflow popover — list of hidden chips, each clickable. */}
      <Popover
        open={Boolean(overflowAnchor)}
        anchorEl={overflowAnchor}
        onClose={closePopovers}
        anchorOrigin={{ vertical: 'center', horizontal: 'right' }}
        transformOrigin={{ vertical: 'center', horizontal: 'left' }}
        slotProps={{
          paper: {
            sx: {
              mt: 0.5,
              p: 1.25,
              minWidth: 220,
              maxWidth: 360,
              borderRadius: '10px',
              border: `1px solid ${P.borderColor}`,
              backgroundColor: P.surface,
            },
          },
        }}
      >
        <Typography
          variant="caption"
          sx={{ color: P.textSecondary, fontWeight: 600, display: 'block', mb: 0.75, ml: 0.5 }}
        >
          {t('{count} hidden badges', { count: overflowCount })}
        </Typography>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75 }}>
          {hiddenChips.map((chip) => (
            <Chip
              key={chip.key}
              size="small"
              label={
                <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
                  {chip.star && (
                    <StarIcon
                      fontSize="inherit"
                      sx={{ color: chip.selected ? P.onAccent : P.gold }}
                    />
                  )}
                  <span>{chip.label}</span>
                  {chip.count !== undefined && (
                    <span style={{ color: P.accentText, fontWeight: 700, marginLeft: 2 }}>{chip.count}</span>
                  )}
                </Box>
              }
              onClick={() => {
                chip.onToggle();
                closePopovers();
              }}
              sx={{
                height: 26,
                fontSize: TYPOGRAPHY.caption.size,
                fontFamily: 'monospace',
                fontWeight: 600,
                cursor: 'pointer',
                flexShrink: 0,
                border: `1px solid ${P.accent}`,
                bgcolor: chip.selected ? P.accent : `${P.accent}22`,
                color: chip.selected ? P.onAccent : P.textPrimary,
                '&:hover': {
                  bgcolor: chip.selected ? P.accent : `${P.accent}40`,
                  filter: chip.selected ? 'brightness(1.1)' : undefined,
                },
              }}
            />
          ))}
        </Box>
      </Popover>

      {/* Configure popover — 4 checkboxes + drag-to-reorder. */}
      <Popover
        open={Boolean(configAnchor)}
        anchorEl={configAnchor}
        onClose={closePopovers}
        anchorOrigin={{ vertical: 'center', horizontal: 'right' }}
        transformOrigin={{ vertical: 'center', horizontal: 'left' }}
        slotProps={{
          paper: {
            sx: {
              mt: 0.5,
              p: 1.25,
              minWidth: 280,
              borderRadius: '10px',
              border: `1px solid ${P.borderColor}`,
              backgroundColor: P.surface,
            },
          },
        }}
      >
        <Typography
          variant="caption"
          sx={{ color: P.textSecondary, fontWeight: 600, display: 'block', mb: 1, ml: 0.5 }}
        >
          {t('Show in quickfilters')}
        </Typography>
        {ALL_CATEGORIES.map((id, idx) => {
          const checked = categories.includes(id);
          const position = categories.indexOf(id);
          const total = countCategory(id, {
            uniqueProfiles,
            uniqueDeviceModels,
            uniqueFlags,
            favoriteTargetOptions,
          });
          return (
            <React.Fragment key={id}>
              {idx > 0 && <Divider sx={{ borderColor: P.borderColor, my: 0.25 }} />}
              <Box
                data-testid={`quickfilter-config-row-${id}`}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 0.75,
                  px: 1,
                  py: 0.5,
                  borderRadius: '6px',
                  cursor: 'pointer',
                  '&:hover': { backgroundColor: P.hoverBg },
                }}
                onClick={() => toggleCategory(id)}
              >
                <DragIcon fontSize="inherit" sx={{ color: P.textMuted, cursor: 'grab' }} />
                <Box
                  component="input"
                  type="checkbox"
                  checked={checked}
                  readOnly
                  sx={{ accentColor: P.accent, width: 16, height: 16, cursor: 'pointer' }}
                />
                <Typography
                  component="span"
                  sx={{ flex: 1, fontSize: TYPOGRAPHY.listItem.size, color: P.textPrimary }}
                >
                  {CATEGORY_LABEL[id]}
                </Typography>
                <Typography
                  component="span"
                  sx={{
                    fontSize: TYPOGRAPHY.caption.size,
                    fontFamily: 'monospace',
                    color: P.textSecondary,
                    backgroundColor: P.hoverBg,
                    px: 0.75,
                    py: 0.25,
                    borderRadius: 999,
                  }}
                >
                  {total}
                </Typography>
                {checked && position > 0 && (
                  <Box
                    component="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      reorder(position, position - 1);
                    }}
                    aria-label={t('Move up')}
                    sx={{
                      background: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                      color: P.textMuted,
                      fontSize: TYPOGRAPHY.caption.size,
                      lineHeight: 1,
                      p: 0.25,
                      '&:hover': { color: P.textPrimary },
                    }}
                  >
                    ▲
                  </Box>
                )}
                {checked && position < categories.length - 1 && (
                  <Box
                    component="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      reorder(position, position + 1);
                    }}
                    aria-label={t('Move down')}
                    sx={{
                      background: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                      color: P.textMuted,
                      fontSize: TYPOGRAPHY.caption.size,
                      lineHeight: 1,
                      p: 0.25,
                      '&:hover': { color: P.textPrimary },
                    }}
                  >
                    ▼
                  </Box>
                )}
              </Box>
            </React.Fragment>
          );
        })}
        <Box
          sx={{
            mt: 1,
            pt: 1,
            borderTop: `1px solid ${P.borderColor}`,
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            fontSize: TYPOGRAPHY.caption.size,
            color: P.textMuted,
          }}
        >
          <Box
            component="button"
            onClick={clear}
            sx={{
              background: 'transparent',
              border: 'none',
              color: P.accentText,
              fontSize: TYPOGRAPHY.caption.size,
              cursor: 'pointer',
              px: 0.75,
              py: 0.25,
              borderRadius: '4px',
              '&:hover': { backgroundColor: P.hoverBg },
            }}
          >
            {t('Clear')}
          </Box>
        </Box>
      </Popover>
    </Box>
  );
};

/** Count chips each category would render — shown next to its checkbox in the configure popover. */
const countCategory = (
  id: CategoryId,
  ctx: {
    uniqueProfiles: string[];
    uniqueDeviceModels: string[];
    uniqueFlags: string[];
    favoriteTargetOptions: string[];
  },
): number => {
  switch (id) {
    case 'profiles':
      return ctx.uniqueProfiles.length;
    case 'models':
      return ctx.uniqueDeviceModels.length;
    case 'tags':
      return ctx.uniqueFlags.length;
    case 'favorites':
      return ctx.favoriteTargetOptions.length;
  }
};

// (MenuItem/ListSubheader were imported for future "click to scroll to a category"
// behaviour; trimmed — add back when needed.)