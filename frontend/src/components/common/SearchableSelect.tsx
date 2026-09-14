import {
  Box,
  FormControl,
  InputLabel,
  ListSubheader,
  MenuItem,
  Select,
  TextField,
  InputAdornment,
} from '@mui/material';
import { Search as SearchIcon } from '@mui/icons-material';
import React, { useMemo, useState } from 'react';

export interface SearchableSelectOption {
  value: string;
  label: string;
  icon?: React.ReactNode;
}

interface SearchableSelectProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: SearchableSelectOption[];
  disabled?: boolean;
  // Shown as a single disabled row when there are no options at all
  // (e.g. "No text references available").
  emptyText?: string;
  // FormControl styles — width/flex live here, same as a plain Select.
  sx?: any;
  // Extra styles merged into '& .MuiSelect-select' (font size / padding).
  inputSx?: any;
  // Search box only appears above this option count; tiny lists don't need it.
  searchThreshold?: number;
}

/**
 * Drop-in replacement for the small Select dropdowns used for reference /
 * key pickers. Adds a sticky search box at the top of the menu: typing
 * filters the options live, Enter picks the top match, ArrowDown moves
 * focus into the list. Selection value/onChange semantics are identical
 * to the plain MUI Select it replaces.
 */
export const SearchableSelect: React.FC<SearchableSelectProps> = ({
  label,
  value,
  onChange,
  options,
  disabled = false,
  emptyText = 'No options available',
  sx,
  inputSx,
  searchThreshold = 5,
}) => {
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState(false);

  const showSearch = options.length > searchThreshold;

  const matches = useMemo(() => {
    if (!search) return options;
    const needle = search.toLowerCase();
    return options.filter((o) => o.label.toLowerCase().includes(needle));
  }, [options, search]);

  // Keep the selected option rendered even when the search filters it out —
  // otherwise MUI logs an out-of-range value warning and clears the display.
  const visible = useMemo(() => {
    if (!value) return matches;
    if (matches.some((o) => o.value === value)) return matches;
    const selected = options.find((o) => o.value === value);
    return selected ? [...matches, selected] : matches;
  }, [matches, options, value]);

  const handleClose = () => {
    setOpen(false);
    setSearch('');
  };

  const pick = (next: string) => {
    onChange(next);
    handleClose();
  };

  return (
    <FormControl size="small" sx={sx}>
      <InputLabel>{label}</InputLabel>
      <Select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        label={label}
        size="small"
        disabled={disabled}
        open={open}
        onOpen={() => setOpen(true)}
        onClose={handleClose}
        // autoFocus:false lets the search box keep focus when the menu opens.
        MenuProps={{
          autoFocus: !showSearch,
          PaperProps: { sx: { maxHeight: 360 } },
        }}
        sx={{
          '& .MuiSelect-select': {
            fontSize: '0.8rem',
            py: 0.5,
            ...inputSx,
          },
        }}
        renderValue={(selected) => {
          const opt = options.find((o) => o.value === selected);
          if (!opt) return selected as string;
          return (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              {opt.icon}
              <span>{opt.label}</span>
            </Box>
          );
        }}
      >
        {showSearch && (
          <ListSubheader sx={{ px: 1, py: 0.5, lineHeight: 'normal' }}>
            <TextField
              size="small"
              autoFocus
              fullWidth
              placeholder="Type to filter…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon sx={{ fontSize: '1rem' }} />
                  </InputAdornment>
                ),
              }}
              inputProps={{ 'aria-label': `Filter ${label}` }}
              sx={{ '& .MuiInputBase-input': { fontSize: '0.8rem', py: 0.5 } }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  // Enter picks the top match (true matches only — not the
                  // selected option appended to dodge the MUI warning).
                  if (matches.length > 0) pick(matches[0].value);
                  e.preventDefault();
                  e.stopPropagation();
                  return;
                }
                // Arrows move focus into the list; Escape closes the menu.
                // Everything else must NOT reach the Select, whose built-in
                // typeahead would steal focus from the search box.
                if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Escape') {
                  e.stopPropagation();
                }
              }}
            />
          </ListSubheader>
        )}
        {visible.map((opt) => (
          <MenuItem key={opt.value} value={opt.value} sx={{ fontSize: '0.75rem' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              {opt.icon}
              <span>{opt.label}</span>
            </Box>
          </MenuItem>
        ))}
        {options.length === 0 && (
          <MenuItem disabled value="" sx={{ fontSize: '0.75rem', fontStyle: 'italic' }}>
            {emptyText}
          </MenuItem>
        )}
        {options.length > 0 && visible.length === 0 && (
          <MenuItem disabled value="" sx={{ fontSize: '0.75rem', fontStyle: 'italic' }}>
            No matches
          </MenuItem>
        )}
      </Select>
    </FormControl>
  );
};
