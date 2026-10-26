import React from 'react';
import { ListItemText, MenuItem, TextField } from '@mui/material';

import { DEFAULT_MONITOR_PROFILE, type MonitorProfileInfo } from './plan';

interface Props {
  label: string;
  /** '' = follow the default */
  value: string;
  onChange: (value: string) => void;
  profiles: MonitorProfileInfo[];
  /** what "Default" means here: the host's MONITOR_PROFILE for a device, tv_app for the host itself */
  defaultName: string;
  helperText?: string;
  testId?: string;
}

export const MonitorProfileSelect: React.FC<Props> = ({ label, value, onChange, profiles, defaultName, helperText, testId }) => {
  const titleOf = (name: string) => profiles.find((p) => p.name === name)?.title ?? name;
  const known = value === '' || profiles.some((p) => p.name === value);
  return (
    <TextField
      select
      fullWidth
      size="small"
      label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      helperText={helperText}
      inputProps={{ 'data-testid': testId }}
      InputLabelProps={{ shrink: true }}
      SelectProps={{
        displayEmpty: true,
        renderValue: (v) => (v === '' ? `Default (${titleOf(defaultName || DEFAULT_MONITOR_PROFILE)})` : titleOf(String(v))),
      }}
    >
      <MenuItem value="">
        <ListItemText primary={`Default (${titleOf(defaultName || DEFAULT_MONITOR_PROFILE)})`} secondary="Follows the host setting" />
      </MenuItem>
      {profiles.map((p) => (
        <MenuItem key={p.name} value={p.name} disabled={!p.usable && p.name !== value}>
          <ListItemText
            primary={p.title}
            secondary={p.usable ? p.description : `Not available: ${p.reason ?? 'cannot run on this host'}`}
            secondaryTypographyProps={{ sx: { whiteSpace: 'normal', maxWidth: 380 } }}
          />
        </MenuItem>
      ))}
      {!known && (
        <MenuItem value={value} disabled>
          <ListItemText primary={value} secondary="Not a profile on this host (runs as tv_app)" />
        </MenuItem>
      )}
    </TextField>
  );
};
