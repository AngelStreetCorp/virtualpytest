import { Tune as TuneIcon, ExpandMore as ExpandMoreIcon, Refresh as RefreshIcon, Search as SearchIcon, Clear as ClearIcon } from '@mui/icons-material';
import { TargetDropdown, TARGET_ROW_SX, TARGET_CHECKBOX_SX, renderSelectedValues } from './TargetDropdown';
import {
  Box,
  Stack,
  Typography,
  Button,
  FormControl,
  Select,
  MenuItem,
  Checkbox,
  ListItemText,
  ListSubheader,
  ToggleButton,
  ToggleButtonGroup,
  Chip,
  CircularProgress,
  SelectChangeEvent,
  TextField,
  InputAdornment,
  IconButton,
  Popover,
} from '@mui/material';
import React, { useMemo, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { DeviceKey } from '../../hooks/useDeviceFavorites';
import { hasNonDefaultProfile, narrowFilterOptions, profileShortName, type ReachableFilterOptions } from '../../hooks/useDeviceFilters';
import { useI18n } from '../../i18n/useI18n';
import { TYPOGRAPHY } from '../../constants/typography';

export type FlagMatchMode = 'AND' | 'OR';

export interface DeviceFilterBarProps {
  targetFilter: string[];
  onTargetFilterChange: (value: string[]) => void;
  deviceModelFilter: string[];
  onDeviceModelFilterChange: (value: string[]) => void;
  flagFilter: string[];
  onFlagFilterChange: (value: string[]) => void;
  // Monitoring profile (TASK-90). The select only renders when a device runs a
  // non-default profile (or one is already picked), so a fleet of tv_app devices
  // keeps the bar exactly as it was.
  profileFilter?: string[];
  onProfileFilterChange?: (value: string[]) => void;
  uniqueProfiles?: string[];
  // AND = device must carry every selected tag; OR = any one tag. Defaults to
  // 'AND'. Surfaced as a small toggle inside the tag dropdown.
  flagMatchMode?: FlagMatchMode;
  onFlagMatchModeChange?: (mode: FlagMatchMode) => void;
  targetOptions: string[];
  // Target label -> the (host, device) it stands for. Favorites (TASK-99) are keyed by device,
  // the targets are labels; without this map the bar shows no stars.
  targetKeys?: Record<string, DeviceKey>;
  uniqueDeviceModels: string[];
  uniqueFlags: string[];
  hasActiveFilters: boolean;
  onClearFilters: () => void;
  onRestart?: () => void;
  isRestarting?: boolean;
  disableRestart?: boolean;
  isMobile?: boolean;
  targetPlaceholder?: string;
  /**
   * Values that survive the *other* filters (BUG-0829). The parent passes the
   * option lists narrowed to what the current selection can still reach; this
   * bar applies them to its own lists so no control ever offers a combination
   * that empties the grid. Omitted (Dashboard bootstrap, tests) = show
   * everything, which is the pre-BUG-0829 behaviour.
   */
  reachableOptions?: Partial<ReachableFilterOptions>;
}

const MENU_PROPS = {
  PaperProps: { sx: { maxHeight: 300 } },
};

// Slightly smaller than the default 1rem so the dropdowns sit just above the "View" switch.
const FILTER_SELECT_SX = {
  fontSize: TYPOGRAPHY.body.size,
  '& .MuiSelect-select': { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: TYPOGRAPHY.body.size, py: '6px' },
};

export const DeviceFilterBar: React.FC<DeviceFilterBarProps> = ({
  targetFilter,
  onTargetFilterChange,
  deviceModelFilter,
  onDeviceModelFilterChange,
  flagFilter,
  onFlagFilterChange,
  profileFilter = [],
  onProfileFilterChange,
  uniqueProfiles = [],
  flagMatchMode = 'AND',
  onFlagMatchModeChange,
  targetOptions,
  targetKeys,
  uniqueDeviceModels,
  uniqueFlags,
  hasActiveFilters,
  onClearFilters,
  onRestart,
  isRestarting = false,
  disableRestart = false,
  isMobile = false,
  targetPlaceholder = 'All Targets',
  reachableOptions,
}) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();

  // Drop what the current selection can no longer reach (BUG-0829). Each axis
  // keeps its own selected values so a pick stays removable, and the incoming
  // (sorted) order is preserved.
  //
  // Targets are deliberately NOT narrowed. The target filter is a union, so
  // picking another target can only widen the result — it is never a dead end,
  // and BUG-0822 gave the bar under the search box one absolute meaning
  // ("Select all" takes every target, "Clear" drops every target). Narrowing
  // the target list would quietly break that rule while fixing nothing. Only
  // the three AND axes below can empty the grid, so only they are narrowed.
  const models = useMemo(
    () => narrowFilterOptions(uniqueDeviceModels, reachableOptions?.models ?? uniqueDeviceModels, deviceModelFilter),
    [uniqueDeviceModels, reachableOptions?.models, deviceModelFilter],
  );
  const profiles = useMemo(
    () => narrowFilterOptions(uniqueProfiles, reachableOptions?.profiles ?? uniqueProfiles, profileFilter),
    [uniqueProfiles, reachableOptions?.profiles, profileFilter],
  );
  const flags = useMemo(
    () => narrowFilterOptions(uniqueFlags, reachableOptions?.flags ?? uniqueFlags, flagFilter),
    [uniqueFlags, reachableOptions?.flags, flagFilter],
  );

  const [moreAnchor, setMoreAnchor] = useState<HTMLElement | null>(null);
  const moreActiveCount =
    (deviceModelFilter.length > 0 ? 1 : 0) + (profileFilter.length > 0 ? 1 : 0) + (flagFilter.length > 0 ? 1 : 0);

  // Desktop "More" popover: a category rail (Models / Profiles / Tags) on the left and the
  // checkbox list of the active category on the right, same shape as the Targets popover.
  const [moreCategory, setMoreCategory] = useState<'models' | 'profiles' | 'tags'>('models');
  const moreCategories = [
    { key: 'models' as const, label: t('Models'), options: models, selected: deviceModelFilter, onChange: onDeviceModelFilterChange },
    ...(onProfileFilterChange && (hasNonDefaultProfile(profiles) || profileFilter.length > 0)
      ? [{ key: 'profiles' as const, label: t('Profiles'), options: profiles, selected: profileFilter, onChange: onProfileFilterChange }]
      : []),
    { key: 'tags' as const, label: t('Tags'), options: flags, selected: flagFilter, onChange: onFlagFilterChange },
  ];
  const activeCategory = moreCategories.find((c) => c.key === moreCategory) ?? moreCategories[0];
  const [moreSearch, setMoreSearch] = useState('');
  const moreVisible = useMemo(() => {
    const q = moreSearch.trim().toLowerCase();
    return q ? activeCategory.options.filter((o) => (activeCategory.key === 'profiles' ? `${o} ${profileShortName(o)}` : o).toLowerCase().includes(q)) : activeCategory.options;
  }, [activeCategory, moreSearch]);

  // Models / Profiles / Tags: inline on mobile, inside the "More" popover on desktop so the
  // header row stays one line however many filters are added (Projects will join them).
  const renderSecondary = (stacked: boolean) => (
    <>
      <FormControl size="small" sx={stacked ? { width: '100%' } : { width: 200, flexShrink: 0 }}>
        <Select
          multiple
          value={deviceModelFilter}
          onChange={(e: SelectChangeEvent<string[]>) => onDeviceModelFilterChange(e.target.value as string[])}
          displayEmpty
          renderValue={(selected) => renderSelectedValues(selected as string[], t('All Models'), (n) => t('{count} models', { count: n }))}
          MenuProps={MENU_PROPS}
          sx={FILTER_SELECT_SX}
        >
          {models.map((model) => (
            <MenuItem key={model} value={model} dense sx={TARGET_ROW_SX}>
              <Checkbox size="small" checked={deviceModelFilter.includes(model)} sx={TARGET_CHECKBOX_SX} />
              <ListItemText primary={model} primaryTypographyProps={{ variant: 'body2' }} />
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {onProfileFilterChange && (hasNonDefaultProfile(profiles) || profileFilter.length > 0) && (
        <FormControl size="small" sx={stacked ? { width: '100%' } : { width: 200, flexShrink: 0 }}>
          <Select
            multiple
            value={profileFilter}
            onChange={(e: SelectChangeEvent<string[]>) => onProfileFilterChange(e.target.value as string[])}
            displayEmpty
            renderValue={(selected) => renderSelectedValues((selected as string[]).map(profileShortName), t('All Profiles'), (n) => t('{count} profiles', { count: n }))}
            MenuProps={MENU_PROPS}
            sx={FILTER_SELECT_SX}
          >
            {profiles.map((profile) => (
              <MenuItem key={profile} value={profile} dense sx={TARGET_ROW_SX}>
                <Checkbox size="small" checked={profileFilter.includes(profile)} sx={TARGET_CHECKBOX_SX} />
                <ListItemText primary={profileShortName(profile)} primaryTypographyProps={{ variant: 'body2' }} />
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      )}

      {!isMobile && (
        <FormControl size="small" sx={stacked ? { width: '100%' } : { width: 200, flexShrink: 0 }}>
          <Select
            multiple
            value={flagFilter}
            onChange={(e: SelectChangeEvent<string[]>) => onFlagFilterChange(e.target.value as string[])}
            displayEmpty
            renderValue={(selected) => {
              const sel = selected as string[];
              if (sel.length === 0) return t('All Tags');
              // Make the active combinator visible on the closed control so
              // users know whether they're seeing "all-of" or "any-of".
              return sel.length > 2
                ? <span title={sel.join(` ${flagMatchMode.toLowerCase()} `)}>{t('{count} tags', { count: sel.length })}</span>
                : sel.join(` ${flagMatchMode.toLowerCase()} `);
            }}
            MenuProps={MENU_PROPS}
            sx={FILTER_SELECT_SX}
          >
            {/* AND/OR combinator — only meaningful with 2+ tags. Lives inside
                the dropdown so it costs no horizontal row space. Must be a
                ListSubheader (not a raw Box) so Select treats it as a
                non-selectable header and still renders the tag items below. */}
            {onFlagMatchModeChange && (
              <ListSubheader
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => e.stopPropagation()}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 1,
                  px: 1.5,
                  py: 0.5,
                  lineHeight: 'unset',
                  borderBottom: '1px solid',
                  borderColor: 'divider',
                }}
              >
                <Typography variant="caption" color="textSecondary">
                  {t('Match')}
                </Typography>
                <ToggleButtonGroup
                  size="small"
                  exclusive
                  value={flagMatchMode}
                  onChange={(_e, mode: FlagMatchMode | null) => {
                    if (mode) onFlagMatchModeChange(mode);
                  }}
                >
                  {/* i18n-ignore */}
                  <ToggleButton value="AND" sx={{ py: 0, px: 1, fontSize: TYPOGRAPHY.microMeta.size, lineHeight: 1.6 }}>AND</ToggleButton>
                  {/* i18n-ignore */}
                  <ToggleButton value="OR" sx={{ py: 0, px: 1, fontSize: TYPOGRAPHY.microMeta.size, lineHeight: 1.6 }}>OR</ToggleButton>
                </ToggleButtonGroup>
              </ListSubheader>
            )}
            {flags.map((flag) => (
              <MenuItem key={flag} value={flag} dense sx={TARGET_ROW_SX}>
                <Checkbox size="small" checked={flagFilter.includes(flag)} sx={TARGET_CHECKBOX_SX} />
                <ListItemText primary={flag} primaryTypographyProps={{ variant: 'body2' }} />
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      )}

    </>
  );

  return (
    <Stack
      direction="row"
      spacing={1}
      sx={{
        alignItems: 'center',
        width: isMobile ? '100%' : 'auto',
        flexWrap: 'nowrap',
        overflowX: isMobile ? 'auto' : 'visible',
        pb: isMobile ? 0.5 : 0,
        '&::-webkit-scrollbar': { display: 'none' },
      }}
    >
      {onRestart && !isMobile && (
        <Button
          variant="outlined"
          size="small"
          startIcon={isRestarting ? <CircularProgress size={16} /> : <RefreshIcon />}
          onClick={onRestart}
          disabled={isRestarting || disableRestart}
          sx={{ height: 32, minWidth: 110, flexShrink: 0 }}
        >
          {isRestarting ? t('Restarting...') : t('Restart')}
        </Button>
      )}

      <TargetDropdown
        selected={targetFilter}
        onChange={onTargetFilterChange}
        options={targetOptions}
        keys={targetKeys}
        placeholder={targetPlaceholder}
      />

      {isMobile ? (
        renderSecondary(false)
      ) : (
        <>
          <Button
            variant="outlined"
            size="small"
            onClick={(e) => setMoreAnchor(e.currentTarget)}
            startIcon={<TuneIcon fontSize="small" />}
            endIcon={<ExpandMoreIcon fontSize="small" />}
            sx={{
              height: 40,
              flexShrink: 0,
              textTransform: 'none',
              color: moreActiveCount > 0 ? P.accentText : P.textSecondary,
              borderColor: moreActiveCount > 0 ? P.accent : P.borderColor,
            }}
          >
            {moreActiveCount > 0 ? `${t('More')} ${moreActiveCount}` : t('More')}
          </Button>
          <Popover
            open={!!moreAnchor}
            anchorEl={moreAnchor}
            onClose={() => { setMoreAnchor(null); setMoreSearch(''); }}
            anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
            transformOrigin={{ vertical: 'top', horizontal: 'right' }}
            slotProps={{ paper: { sx: { width: 460, maxWidth: 'calc(100vw - 16px)', height: 'min(420px, 70vh)', display: 'flex', flexDirection: 'column', overflow: 'hidden' } } }}
          >
            <Box sx={{ p: 1, pb: 0.5, flexShrink: 0 }}>
              <TextField
                size="small"
                autoFocus
                fullWidth
                placeholder={t('Search...')}
                value={moreSearch}
                onChange={(e) => setMoreSearch(e.target.value)}
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchIcon fontSize="small" sx={{ color: 'text.secondary' }} />
                    </InputAdornment>
                  ),
                  endAdornment: moreSearch ? (
                    <InputAdornment position="end">
                      <IconButton size="small" edge="end" onClick={() => setMoreSearch('')}>
                        <ClearIcon fontSize="small" />
                      </IconButton>
                    </InputAdornment>
                  ) : undefined,
                }}
              />
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, px: 1, pb: 0.5, flexShrink: 0, borderBottom: '1px solid', borderColor: 'divider' }}>
              <Button
                size="small"
                onClick={() => activeCategory.onChange(Array.from(new Set([...activeCategory.selected, ...moreVisible])))}
                disabled={moreVisible.length === 0 || moreVisible.every((o) => activeCategory.selected.includes(o))}
                sx={{ minWidth: 0, px: 1, fontSize: TYPOGRAPHY.caption.size }}
              >
                {t('Select all')}
              </Button>
              <Button
                size="small"
                onClick={() => activeCategory.onChange(activeCategory.selected.filter((o) => !moreVisible.includes(o)))}
                disabled={moreVisible.every((o) => !activeCategory.selected.includes(o))}
                sx={{ minWidth: 0, px: 1, fontSize: TYPOGRAPHY.caption.size }}
              >
                {t('Clear')}
              </Button>
              {activeCategory.key === 'tags' && onFlagMatchModeChange && (
                <Box sx={{ ml: 'auto', display: 'flex', alignItems: 'center', gap: 0.75 }}>
                  <Typography variant="caption" color="textSecondary">
                    {t('Match')}
                  </Typography>
                  <ToggleButtonGroup
                    size="small"
                    exclusive
                    value={flagMatchMode}
                    onChange={(_e, mode: FlagMatchMode | null) => {
                      if (mode) onFlagMatchModeChange(mode);
                    }}
                  >
                    {/* i18n-ignore */}
                    <ToggleButton value="AND" sx={{ py: 0, px: 1, fontSize: TYPOGRAPHY.microMeta.size, lineHeight: 1.6 }}>AND</ToggleButton>
                    {/* i18n-ignore */}
                    <ToggleButton value="OR" sx={{ py: 0, px: 1, fontSize: TYPOGRAPHY.microMeta.size, lineHeight: 1.6 }}>OR</ToggleButton>
                  </ToggleButtonGroup>
                </Box>
              )}
            </Box>
            <Box sx={{ display: 'flex', flex: 1, minHeight: 0 }}>
              <Box sx={{ width: 150, flexShrink: 0, overflowY: 'auto', borderRight: '1px solid', borderColor: 'divider' }}>
                {moreCategories.map((c) => {
                  const active = activeCategory.key === c.key;
                  return (
                    <Box
                      key={c.key}
                      role="button"
                      tabIndex={0}
                      onClick={() => setMoreCategory(c.key)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          setMoreCategory(c.key);
                        }
                      }}
                      sx={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 0.75,
                        px: 1.25,
                        py: 0.4,
                        cursor: 'pointer',
                        borderLeft: '2px solid',
                        borderLeftColor: active ? 'primary.main' : 'transparent',
                        bgcolor: active ? 'action.selected' : 'transparent',
                        '&:hover': { bgcolor: 'action.hover' },
                      }}
                    >
                      <Typography component="span" sx={{ flex: 1, minWidth: 0, fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size }}>
                        {c.label}
                      </Typography>
                      <Typography
                        component="span"
                        sx={{
                          flexShrink: 0,
                          px: 0.5,
                          borderRadius: 0.75,
                          bgcolor: c.selected.length > 0 ? 'primary.main' : 'action.selected',
                          color: c.selected.length > 0 ? 'primary.contrastText' : 'text.secondary',
                          fontFamily: 'monospace',
                          fontSize: TYPOGRAPHY.microMeta.size,
                          lineHeight: 1.6,
                        }}
                      >
                        {c.selected.length}/{c.options.length}
                      </Typography>
                    </Box>
                  );
                })}
              </Box>
              <Box sx={{ flex: 1, minWidth: 0, overflowY: 'auto' }}>
                {moreVisible.length === 0 ? (
                  <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
                    {t('No matches')}
                  </Typography>
                ) : (
                  moreVisible.map((opt) => (
                    <MenuItem
                      key={opt}
                      dense
                      sx={TARGET_ROW_SX}
                      onClick={() =>
                        activeCategory.onChange(
                          activeCategory.selected.includes(opt)
                            ? activeCategory.selected.filter((v) => v !== opt)
                            : [...activeCategory.selected, opt],
                        )
                      }
                    >
                      <Checkbox size="small" checked={activeCategory.selected.includes(opt)} sx={TARGET_CHECKBOX_SX} />
                      <ListItemText primary={activeCategory.key === 'profiles' ? profileShortName(opt) : opt} primaryTypographyProps={{ variant: 'body2' }} />
                    </MenuItem>
                  ))
                )}
              </Box>
            </Box>
          </Popover>
        </>
      )}

      <Chip
        label={t('Clear')}
        size="small"
        variant="outlined"
        onClick={onClearFilters}
        sx={{ height: 32, flexShrink: 0, visibility: hasActiveFilters ? 'visible' : 'hidden' }}
      />
    </Stack>
  );
};
