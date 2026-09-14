import { Refresh as RefreshIcon, Search as SearchIcon, Clear as ClearIcon } from '@mui/icons-material';
import {
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
          {isRestarting ? 'Restarting...' : 'Restart'}
        </Button>
      )}

      <FormControl size="small" sx={{ width: 200, flexShrink: 0 }}>
        <Select
          multiple
          value={targetFilter}
          onChange={(e: SelectChangeEvent<string[]>) => onTargetFilterChange(e.target.value as string[])}
          onClose={() => setTargetSearch('')}
          displayEmpty
          renderValue={(selected) => renderSelectedValues(selected as string[], targetPlaceholder)}
          MenuProps={MENU_PROPS}
          sx={{ '& .MuiSelect-select': { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }}
        >
          {/* Search box pinned at the top of the dropdown. ListSubheader keeps
              Select from treating it as a selectable option; stopping keydown
              propagation prevents Select's type-ahead from stealing keystrokes
              and closing the menu. */}
          <ListSubheader sx={{ p: 1, lineHeight: 'unset', bgcolor: 'background.paper' }}>
            <TextField
              size="small"
              autoFocus
              fullWidth
              placeholder="Search targets..."
              value={targetSearch}
              onChange={(e) => setTargetSearch(e.target.value)}
              onKeyDown={(e) => e.stopPropagation()}
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
          </ListSubheader>
          {/* Select-all / clear row. Also a ListSubheader so Select ignores it
              for selection/type-ahead. Buttons act on the visible options. */}
          <ListSubheader
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 0.5,
              px: 1,
              py: 0.25,
              lineHeight: 'unset',
              borderBottom: '1px solid',
              borderColor: 'divider',
              bgcolor: 'background.paper',
            }}
          >
            <Button
              size="small"
              onClick={handleSelectAllVisible}
              disabled={visibleTargetOptions.length === 0 || allVisibleSelected}
              sx={{ minWidth: 0, px: 1, fontSize: '0.7rem' }}
            >
              Select all
            </Button>
            <Button
              size="small"
              onClick={handleClearVisible}
              disabled={visibleTargetOptions.every((option) => !targetFilter.includes(option))}
              sx={{ minWidth: 0, px: 1, fontSize: '0.7rem' }}
            >
              Clear
            </Button>
          </ListSubheader>
          {visibleTargetOptions.length === 0 ? (
            <MenuItem disabled dense>
              <ListItemText
                primary="No matching targets"
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

      <FormControl size="small" sx={{ width: 140, flexShrink: 0 }}>
        <Select
          multiple
          value={deviceModelFilter}
          onChange={(e: SelectChangeEvent<string[]>) => onDeviceModelFilterChange(e.target.value as string[])}
          displayEmpty
          renderValue={(selected) => renderSelectedValues(selected as string[], 'All Models')}
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
        <FormControl size="small" sx={{ width: 140, flexShrink: 0 }}>
          <Select
            multiple
            value={flagFilter}
            onChange={(e: SelectChangeEvent<string[]>) => onFlagFilterChange(e.target.value as string[])}
            displayEmpty
            renderValue={(selected) => {
              const sel = selected as string[];
              if (sel.length === 0) return 'All Tags';
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
                  Match
                </Typography>
                <ToggleButtonGroup
                  size="small"
                  exclusive
                  value={flagMatchMode}
                  onChange={(_e, mode: FlagMatchMode | null) => {
                    if (mode) onFlagMatchModeChange(mode);
                  }}
                >
                  <ToggleButton value="AND" sx={{ py: 0, px: 1, fontSize: '0.65rem', lineHeight: 1.6 }}>
                    AND
                  </ToggleButton>
                  <ToggleButton value="OR" sx={{ py: 0, px: 1, fontSize: '0.65rem', lineHeight: 1.6 }}>
                    OR
                  </ToggleButton>
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
        label="Clear"
        size="small"
        variant="outlined"
        onClick={onClearFilters}
        sx={{ height: 32, flexShrink: 0, visibility: hasActiveFilters ? 'visible' : 'hidden' }}
      />
    </Stack>
  );
};
