/**
 * Shared Userinterface Selector Component
 * 
 * Provides a dropdown to select userinterface from compatible options.
 * Used across:
 * - AI Execution Panel (live execution)
 * - Test Case Editor (execute modal)
 * - Run Tests (script parameters)
 */

import React, { useState, useEffect } from 'react';
import { FormControl, InputLabel, Select, MenuItem, Chip, CircularProgress, SelectChangeEvent, useTheme } from '@mui/material';
import { useUserInterface } from '../../hooks/pages/useUserInterface';
import { AGENT_CHAT_PALETTE } from '../../constants/agentChatTheme';

interface UserinterfaceSelectorProps {
  deviceModel?: string;  // Device model to find compatible interfaces for (undefined = show all)
  compatibleInterfaces?: string[];  // Pre-filtered list (e.g., from test case)
  value?: string;
  // mode identifies WHICH row a shared name refers to when includeProd is on
  // (dev and prod rows share one name). Ignored (always dev) otherwise.
  mode?: 'dev' | 'prod';
  // onChange keeps its old single-arg shape for existing consumers; when
  // includeProd is on, the selected entry's mode arrives as the 2nd arg.
  onChange: (userinterface: string, mode?: 'dev' | 'prod') => void;
  // Opt-in: also list published prod versions (gold chip). Default off — prod
  // rows are filtered out so the other consumers see exactly today's list.
  includeProd?: boolean;
  label?: string;
  disabled?: boolean;
  size?: 'small' | 'medium';
  fullWidth?: boolean;
  sx?: any;
  dropdownStyles?: any;  // Shared dropdown styles for consistency
  disableAutoSelect?: boolean;  // Disable auto-selection of first interface
}

interface UserinterfaceOption {
  id: string;
  name: string;
  mode: 'dev' | 'prod';
}

// Select values must be unique — dev and prod share a name, so the option
// value is a composite key.
const optionKey = (name: string, mode: 'dev' | 'prod') => `${mode}:${name}`;

export const UserinterfaceSelector: React.FC<UserinterfaceSelectorProps> = ({
  deviceModel,
  compatibleInterfaces,
  value = '',
  mode = 'dev',
  onChange,
  includeProd = false,
  label = 'Userinterface',
  disabled = false,
  size = 'medium',
  fullWidth = true,
  sx = {},
  dropdownStyles,
  disableAutoSelect = false
}) => {
  const theme = useTheme();
  const isDarkMode = theme.palette.mode === 'dark';
  const PALETTE = AGENT_CHAT_PALETTE;

  // Use shared dropdown styles if provided, otherwise create local styles
  const styles = dropdownStyles || {
    select: {
      height: size === 'small' ? 32 : 40,
      fontSize: size === 'small' ? '0.85rem' : '0.875rem',
      bgcolor: isDarkMode ? PALETTE.inputBg : '#fff',
      borderRadius: 1.5,
      '& .MuiOutlinedInput-notchedOutline': {
        borderColor: isDarkMode ? PALETTE.borderColor : 'grey.300',
      },
      '&:hover .MuiOutlinedInput-notchedOutline': {
        borderColor: PALETTE.accent,
      },
      '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
        borderColor: PALETTE.accent,
      },
      '& .MuiSelect-select': {
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        py: size === 'small' ? 0.5 : 0.75,
      },
    },
    menuProps: {
      PaperProps: {
        sx: {
          bgcolor: isDarkMode ? PALETTE.surface : '#fff',
          border: '1px solid',
          borderColor: isDarkMode ? PALETTE.borderColor : 'grey.200',
          boxShadow: PALETTE.cardShadow,
        }
      }
    },
    menuItemPlaceholder: {
      fontSize: size === 'small' ? '0.85rem' : '0.875rem',
      py: size === 'small' ? 0.75 : 1,
      color: 'text.secondary',
    },
    menuItem: {
      fontSize: size === 'small' ? '0.85rem' : '0.875rem',
      py: size === 'small' ? 0.75 : 1,
      color: 'text.primary',
      '&:hover': { bgcolor: isDarkMode ? PALETTE.hoverBg : 'grey.100' },
      '&.Mui-selected': { bgcolor: isDarkMode ? PALETTE.hoverBg : 'grey.100' },
    },
  };
  const [interfaces, setInterfaces] = useState<UserinterfaceOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { getCompatibleInterfaces, getAllUserInterfaces } = useUserInterface();

  useEffect(() => {
    const fetchInterfaces = async () => {
      // If pre-filtered list provided, use it directly
      if (compatibleInterfaces && compatibleInterfaces.length > 0) {
        const options: UserinterfaceOption[] = compatibleInterfaces.map(name => ({
          id: name,
          name: name,
          mode: 'dev' as const
        }));
        console.log('[@UserinterfaceSelector] Setting interfaces from compatibleInterfaces:', options);
        console.log('[@UserinterfaceSelector] Current value:', value);
        setInterfaces(options);
        setError(null); // Clear any previous error

        const noValue = !value || value.trim() === '';
        const onlyOne = options.length === 1;
        // A single option is unambiguous: preselect it even when the current
        // value is a stale/unrelated default or auto-select is disabled.
        if (
          onChange &&
          ((onlyOne && value !== options[0].name) || (noValue && !disableAutoSelect))
        ) {
          console.log('[@UserinterfaceSelector] Auto-selecting interface:', options[0].name);
          onChange(options[0].name);
        }
        return;
      }

      try {
        setLoading(true);
        setError(null);

        let interfacesList: any[];

        if (deviceModel && deviceModel !== 'unknown') {
          // Fetch compatible interfaces for specific device model
          console.log('[@UserinterfaceSelector] Fetching compatible interfaces for device model:', deviceModel);
          interfacesList = await getCompatibleInterfaces(deviceModel);
        } else {
          // Fetch all interfaces when no device is selected
          console.log('[@UserinterfaceSelector] No device selected - fetching all interfaces');
          const allInterfaces = await getAllUserInterfaces();
          interfacesList = allInterfaces;
        }

        if (interfacesList && interfacesList.length > 0) {
          // Prod rows share their dev source's name. Without includeProd they
          // are filtered out so every existing consumer sees exactly the old
          // list; with it, each published interface shows a second gold entry.
          const options: UserinterfaceOption[] = interfacesList
            .filter((iface: any) => includeProd || (iface.mode || 'dev') !== 'prod')
            .map((iface: any) => ({
              id: iface.id,
              name: iface.name,
              mode: ((iface.mode || 'dev') === 'prod' ? 'prod' : 'dev') as 'dev' | 'prod'
            }));
          setInterfaces(options);
          console.log(`[@UserinterfaceSelector] Loaded ${options.length} interfaces`);

          const noValue = !value || value.trim() === '';
          const onlyOne = options.length === 1;
          // Auto-select prefers a dev entry (prod is an explicit choice).
          const first = options.find((o) => o.mode === 'dev') || options[0];
          // Single option is unambiguous — always preselect it (even over a
          // stale default). Otherwise keep the original behavior: auto-select
          // the first only when a device is selected and not disabled.
          if (
            onChange &&
            ((onlyOne && value !== first.name) ||
              (noValue && deviceModel && !disableAutoSelect))
          ) {
            console.log('[@UserinterfaceSelector] Auto-selecting interface:', first.name);
            onChange(first.name, first.mode);
          }
        } else {
          setError('No interfaces found');
          setInterfaces([]);
        }
      } catch (err) {
        console.error('[@UserinterfaceSelector] Error fetching interfaces:', err);
        setError('Failed to load interfaces');
        setInterfaces([]);
      } finally {
        setLoading(false);
      }
    };

    fetchInterfaces();
     
  }, [deviceModel, compatibleInterfaces]); // getCompatibleInterfaces, getAllUserInterfaces excluded to prevent unnecessary re-fetches

  const handleChange = (event: SelectChangeEvent<string>) => {
    const raw = event.target.value;
    if (!raw) {
      onChange('');
      return;
    }
    // Option values are composite ("dev:stb_tv" / "prod:stb_tv") so dev and
    // prod entries sharing a name stay distinct in the Select.
    const sep = raw.indexOf(':');
    const selMode = (raw.slice(0, sep) === 'prod' ? 'prod' : 'dev') as 'dev' | 'prod';
    onChange(raw.slice(sep + 1), selMode);
  };

  const selectedKey = value ? optionKey(value, includeProd ? mode : 'dev') : '';

  if (loading) {
    return (
      <FormControl size={size} fullWidth={fullWidth} disabled sx={sx}>
        <InputLabel>{label}</InputLabel>
        <Select
          value=""
          label={label}
          disabled
          startAdornment={<CircularProgress size={16} sx={{ mr: 1 }} />}
          sx={{ ...styles.select, ...sx }}
        >
          <MenuItem value="" sx={styles.menuItemPlaceholder}>
            Loading...
          </MenuItem>
        </Select>
      </FormControl>
    );
  }

  if (error || interfaces.length === 0) {
    return (
      <FormControl size={size} fullWidth={fullWidth} disabled sx={sx}>
        <InputLabel>{label}</InputLabel>
        <Select value="" label={label} disabled sx={{ ...styles.select, ...sx }}>
          <MenuItem value="" sx={styles.menuItemPlaceholder}>
            {error || 'No compatible interfaces'}
          </MenuItem>
        </Select>
      </FormControl>
    );
  }
  
  return (
    <FormControl size={size} fullWidth={fullWidth} disabled={disabled} sx={sx}>
      <InputLabel>{label}</InputLabel>
      <Select
        value={selectedKey}
        onChange={handleChange}
        label={label}
        sx={{ ...styles.select, ...sx }}
        MenuProps={styles.menuProps}
      >
        <MenuItem value="" sx={styles.menuItemPlaceholder}>
          <em>Select Interface...</em>
        </MenuItem>
        {interfaces.map((iface) => (
          <MenuItem
            key={`${iface.mode}:${iface.id}`}
            value={optionKey(iface.name, iface.mode)}
            sx={styles.menuItem}
          >
            {iface.name}
            {iface.mode === 'prod' && (
              <Chip
                label="prod"
                size="small"
                sx={{
                  ml: 0.75,
                  height: 16,
                  bgcolor: '#b8860b',
                  color: '#fff',
                  '& .MuiChip-label': { px: 0.5, fontSize: '0.6rem', fontWeight: 600 },
                }}
              />
            )}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
};
