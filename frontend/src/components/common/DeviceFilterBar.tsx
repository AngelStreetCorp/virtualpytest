import { Refresh as RefreshIcon, Search as SearchIcon, Clear as ClearIcon } from '@mui/icons-material';
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
} from '@mui/material';
import React, { useMemo, useState } from 'react';

import { useI18n } from '../../i18n/useI18n';

export type FlagMatchMode = 'AND' | 'OR';

export interface DeviceFilterBarProps {
  targetFilter: string[];
  onTargetFilterChange: (value: string[]) => void;
  deviceModelFilter: string[];
  onDeviceModelFilterChange: (value: string[]) => void;
  flagFilter: string[];
  onFlagFilterChange: (value: string[]) => void;
  // AND = device must carry every selected tag; OR = any one tag. Defaults to
  // 'AND'. Surfaced as a small toggle inside the tag dropdown.
  flagMatchMode?: FlagMatchMode;
  onFlagMatchModeChange?: (mode: FlagMatchMode) => void;
  targetOptions: string[];
  uniqueDeviceModels: string[];
  uniqueFlags: string[];
  hasActiveFilters: boolean;
  onClearFilters: () => void;
  onRestart?: () => void;
  isRestarting?: boolean;
  disableRestart?: boolean;
  isMobile?: boolean;
  targetPlaceholder?: string;
}

const MENU_PROPS = {
  PaperProps: { sx: { maxHeight: 300 } },
};

// Targets menu carries an in-menu search box. autoFocus:false stops MUI from
// auto-focusing a MenuItem: MenuList hands `autoFocus` to the first non-header
// child, and every keystroke re-filters the list so a *different* MenuItem
// mounts with that prop and steals focus from the search box after one char.
// The TextField's own autoFocus still focuses it when the menu opens.
const TARGET_MENU_PROPS = {
  ...MENU_PROPS,
  autoFocus: false,
};

const renderSelectedValues = (selected: string[], allLabel: string) =>
  (selected as string[]).length === 0 ? allLabel : (selected as string[]).join(', ');

export const DeviceFilterBar: React.FC<DeviceFilterBarProps> = ({
  targetFilter,
  onTargetFilterChange,
  deviceModelFilter,
  onDeviceModelFilterChange,
  flagFilter,
  onFlagFilterChange,
  flagMatchMode = 'AND',
  onFlagMatchModeChange,
  targetOptions,
  uniqueDeviceModels,
  uniqueFlags,
  hasActiveFilters,
  onClearFilters,
  onRestart,
  isRestarting = false,
  disableRestart = false,
  isMobile = false,
  targetPlaceholder = 'All Targets',
}) => {
  const { t } = useI18n();
  // Free-text search lives *inside* the Targets dropdown so it costs no
  // horizontal row space. It narrows the option list shown; selection still
  // happens via the checkboxes below.
  const [targetSearch, setTargetSearch] = useState('');
  const visibleTargetOptions = useMemo(() => {
    const q = targetSearch.trim().toLowerCase();
    if (!q) return targetOptions;
    return targetOptions.filter((option) => option.toLowerCase().includes(q));
  }, [targetOptions, targetSearch]);

  // Select-all / clear act on the *visible* (searched) options only, so they
  // stay predictable when a search narrows the list. Selecting merges with the
  // current selection; clearing removes just the visible ones, preserving any
  // selection hidden by the active search.
  const allVisibleSelected =
    visibleTargetOptions.length > 0 &&
    visibleTargetOptions.every((option) => targetFilter.includes(option));

  const handleSelectAllVisible = () => {
    onTargetFilterChange(Array.from(new Set([...targetFilter, ...visibleTargetOptions])));
  };
  const handleClearVisible = () => {
    const visible = new Set(visibleTargetOptions);
    onTargetFilterChange(targetFilter.filter((option) => !visible.has(option)));
  };

  // Group targets by host so a single click can toggle every device on that
  // host. Targets are formatted as "device_name - host_name" for regular
  // devices, or just "host_name" for host-only entries (VNC desktops, *_Host);
  // the last " - " separator is the safe split point in both cases.
  const TARGET_HOST_SEP = ' - ';
  const hostGroups = useMemo(() => {
    const byHost = new Map<string, string[]>();
    targetOptions.forEach((option) => {
      const idx = option.lastIndexOf(TARGET_HOST_SEP);
      const host = idx >= 0 ? option.slice(idx + TARGET_HOST_SEP.length) : option;
      if (!byHost.has(host)) byHost.set(host, []);
      byHost.get(host)!.push(option);
    });
    // Narrow the displayed pills to hosts with at least one target that
    // matches the active search. The pill still owns the full host's target
    // list so a click toggles the complete rack even when only some targets
    // are currently visible — see handleToggleHost. Without this filter the
    // pill row contradicts the search box: typing "mf1" would still show
    // pills for vpt-pi1 / vpt-pi3 alongside the vpt-mf1 result.
    const visibleSet = new Set(visibleTargetOptions);
    return Array.from(byHost.entries())
      .filter(([, targets]) => targets.length >= 2)
      .filter(([, targets]) => targets.some((t) => visibleSet.has(t)))
      .map(([host, targets]) => ({
        host,
        targets,
        selectedCount: targets.filter((t) => targetFilter.includes(t)).length,
      }))
      .sort((a, b) => a.host.localeCompare(b.host));
  }, [targetOptions, visibleTargetOptions, targetFilter]);

  // Click toggles ALL targets on the host (not just the visible/searched
  // ones). Empty or partial → select all. Filled → deselect all.
  const handleToggleHost = (targets: string[]) => {
    const allSelected = targets.every((t) => targetFilter.includes(t));
    if (allSelected) {
      const removed = new Set(targets);
      onTargetFilterChange(targetFilter.filter((t) => !removed.has(t)));
    } else {
      onTargetFilterChange(Array.from(new Set([...targetFilter, ...targets])));
    }
  };

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

      <FormControl size="small" sx={{ width: 200, flexShrink: 0 }}>
        <Select
          multiple
          value={targetFilter}
          onChange={(e: SelectChangeEvent<string[]>) => onTargetFilterChange(e.target.value as string[])}
          onClose={() => setTargetSearch('')}
          displayEmpty
          renderValue={(selected) => renderSelectedValues(selected as string[], t(targetPlaceholder))}
          MenuProps={TARGET_MENU_PROPS}
          sx={{ '& .MuiSelect-select': { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }}
        >
          {/* Search box + select-all row pinned at the top of the dropdown, in ONE
              ListSubheader: two sticky subheaders both stick at top:0, so on scroll
              the second slid over the search box and hid it. ListSubheader keeps
              Select from treating it as a selectable option; stopping keydown
              propagation prevents Select's type-ahead from stealing keystrokes
              and closing the menu. */}
          <ListSubheader
            sx={{ p: 0, lineHeight: 'unset', bgcolor: 'background.paper', borderBottom: '1px solid', borderColor: 'divider' }}
          >
            <Box sx={{ p: 1, pb: 0.5 }}>
            <TextField
              size="small"
              autoFocus
              fullWidth
              placeholder={t('Search targets...')}
              value={targetSearch}
              onChange={(e) => setTargetSearch(e.target.value)}
              onKeyDown={(e) => {
                // Arrows move focus into the option list and Escape closes the
                // menu, so those must reach Select; anything else would feed
                // Select's type-ahead, which moves focus off the search box.
                if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Escape') {
                  e.stopPropagation();
                }
              }}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon fontSize="small" sx={{ color: 'text.secondary' }} />
                  </InputAdornment>
                ),
                endAdornment: targetSearch ? (
                  <InputAdornment position="end">
                    <IconButton size="small" edge="end" onClick={() => setTargetSearch('')}>
                      <ClearIcon fontSize="small" />
                    </IconButton>
                  </InputAdornment>
                ) : undefined,
              }}
            />
            </Box>
            {/* Select-all / clear row. Buttons act on the visible options. */}
            <Box
              onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => e.stopPropagation()}
              sx={{ display: 'flex', alignItems: 'center', gap: 0.5, px: 1, pb: 0.25 }}
            >
            <Button
              size="small"
              onClick={handleSelectAllVisible}
              disabled={visibleTargetOptions.length === 0 || allVisibleSelected}
              sx={{ minWidth: 0, px: 1, fontSize: '0.7rem' }}
            >
              {t('Select all')}
            </Button>
            <Button
              size="small"
              onClick={handleClearVisible}
              disabled={visibleTargetOptions.every((option) => !targetFilter.includes(option))}
              sx={{ minWidth: 0, px: 1, fontSize: '0.7rem' }}
            >
              {t('Clear')}
            </Button>
            </Box>
            {/* Host toggle pills. Each pill selects or deselects ALL targets
                on a host (not just visible) so "click once for the whole rack"
                works. Only shown when at least one host has 2+ targets. */}
            {hostGroups.length >= 1 && (
              <Box
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => e.stopPropagation()}
                sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, px: 1, pb: 0.75 }}
              >
                {hostGroups.map(({ host, targets, selectedCount }) => {
                  const total = targets.length;
                  const state =
                    selectedCount === 0 ? 'empty' : selectedCount === total ? 'filled' : 'mixed';
                  return (
                    <Box
                      key={host}
                      role="button"
                      tabIndex={0}
                      onClick={() => handleToggleHost(targets)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          handleToggleHost(targets);
                        }
                      }}
                      sx={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 0.5,
                        px: 0.75,
                        py: 0.25,
                        borderRadius: 1.25,
                        border: '1px solid',
                        borderColor: state === 'empty' ? 'divider' : 'primary.main',
                        bgcolor: state === 'empty' ? 'transparent' : 'action.hover',
                        cursor: 'pointer',
                        fontSize: '0.75rem',
                        '&:hover': { borderColor: 'primary.main' },
                        '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: '2px' },
                      }}
                      aria-label={`${host} ${selectedCount} of ${total} selected`}
                    >
                      <Checkbox
                        size="small"
                        checked={state === 'filled'}
                        indeterminate={state === 'mixed'}
                        sx={{ p: 0, mr: 0.25 }}
                        tabIndex={-1}
                      />
                      <Typography component="span" variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>
                        {host}
                      </Typography>
                      <Typography
                        component="span"
                        variant="caption"
                        sx={{
                          ml: 0.25,
                          px: 0.5,
                          borderRadius: 0.75,
                          bgcolor: state === 'filled' ? 'primary.main' : 'action.selected',
                          color: state === 'filled' ? 'primary.contrastText' : 'text.secondary',
                          fontFamily: 'monospace',
                          fontSize: '0.65rem',
                          lineHeight: 1.6,
                        }}
                      >
                        {`${selectedCount}/${total}`}
                      </Typography>
                    </Box>
                  );
                })}
              </Box>
            )}
          </ListSubheader>
          {visibleTargetOptions.length === 0 ? (
            <MenuItem disabled dense>
              <ListItemText
                primary={t('No matching targets')}
                primaryTypographyProps={{ variant: 'body2', color: 'text.secondary' }}
              />
            </MenuItem>
          ) : (
            visibleTargetOptions.map((option) => (
              <MenuItem key={option} value={option} dense>
                <Checkbox size="small" checked={targetFilter.includes(option)} />
                <ListItemText primary={option} primaryTypographyProps={{ variant: 'body2' }} />
              </MenuItem>
            ))
          )}
        </Select>
      </FormControl>

      <FormControl size="small" sx={{ minWidth: 140, maxWidth: 220, flexShrink: 0 }}>
        <Select
          multiple
          value={deviceModelFilter}
          onChange={(e: SelectChangeEvent<string[]>) => onDeviceModelFilterChange(e.target.value as string[])}
          displayEmpty
          renderValue={(selected) => renderSelectedValues(selected as string[], t('All Models'))}
          MenuProps={MENU_PROPS}
          sx={{ '& .MuiSelect-select': { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }}
        >
          {uniqueDeviceModels.map((model) => (
            <MenuItem key={model} value={model} dense>
              <Checkbox size="small" checked={deviceModelFilter.includes(model)} />
              <ListItemText primary={model} primaryTypographyProps={{ variant: 'body2' }} />
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {!isMobile && (
        <FormControl size="small" sx={{ minWidth: 140, maxWidth: 220, flexShrink: 0 }}>
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
              return sel.length > 1 ? sel.join(` ${flagMatchMode.toLowerCase()} `) : sel[0];
            }}
            MenuProps={MENU_PROPS}
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
                  <ToggleButton value="AND" sx={{ py: 0, px: 1, fontSize: '0.65rem', lineHeight: 1.6 }}>AND</ToggleButton>
                  {/* i18n-ignore */}
                  <ToggleButton value="OR" sx={{ py: 0, px: 1, fontSize: '0.65rem', lineHeight: 1.6 }}>OR</ToggleButton>
                </ToggleButtonGroup>
              </ListSubheader>
            )}
            {uniqueFlags.map((flag) => (
              <MenuItem key={flag} value={flag} dense>
                <Checkbox size="small" checked={flagFilter.includes(flag)} />
                <ListItemText primary={flag} primaryTypographyProps={{ variant: 'body2' }} />
              </MenuItem>
            ))}
          </Select>
        </FormControl>
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
