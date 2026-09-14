import React from 'react';
import { Box, Select, MenuItem, FormControl, InputLabel, TextField, Typography } from '@mui/material';
import { Info } from '@mui/icons-material';

interface CronPattern {
  label: string;
  value: string;
  description: string;
}

const CRON_PATTERNS: CronPattern[] = [
  { label: 'Every 1 minute', value: '*/1 * * * *', description: 'Runs 60 times per hour' },
  { label: 'Every 5 minutes', value: '*/5 * * * *', description: 'Runs 12 times per hour' },
  { label: 'Every 10 minutes', value: '*/10 * * * *', description: 'Runs 6 times per hour' },
  { label: 'Every 15 minutes', value: '*/15 * * * *', description: 'Runs 4 times per hour' },
  { label: 'Every 30 minutes', value: '*/30 * * * *', description: 'Runs twice per hour' },
  { label: 'Every hour', value: '0 * * * *', description: 'Runs at :00 past every hour' },
  { label: 'Every 2 hours', value: '0 */2 * * *', description: 'Runs at :00 every 2 hours' },
  { label: 'Every 6 hours', value: '0 */6 * * *', description: 'Runs 4 times per day' },
  { label: 'Daily at midnight', value: '0 0 * * *', description: 'Runs once per day at 00:00' },
  { label: 'Daily at 2am', value: '0 2 * * *', description: 'Runs once per day at 02:00' },
  { label: 'Daily at 10am', value: '0 10 * * *', description: 'Runs once per day at 10:00' },
  { label: 'Weekdays at 9am', value: '0 9 * * 1-5', description: 'Mon-Fri at 09:00' },
  { label: 'Business hours (hourly)', value: '0 9-17 * * 1-5', description: 'Every hour 9am-5pm, Mon-Fri' },
  { label: 'Weekly on Monday', value: '0 0 * * 1', description: 'Every Monday at midnight' },
  { label: 'Weekly on Sunday', value: '0 0 * * 0', description: 'Every Sunday at midnight' },
  { label: 'Custom', value: 'custom', description: 'Custom expression' },
];

interface CronHelperProps {
  value: string;
  onChange: (value: string) => void;
  error?: string;
  size?: 'small' | 'medium';
  disablePortal?: boolean;
}

export const CronHelper: React.FC<CronHelperProps> = ({
  value,
  onChange,
  error,
  size = 'small',
  disablePortal = false,
}) => {
  // Find matching preset for current cron expression
  const matchedPattern = CRON_PATTERNS.find(p => p.value === value && p.value !== 'custom');
  const selectedPreset = matchedPattern ? matchedPattern.value : 'custom';
  
  const handlePresetChange = (newValue: string) => {
    if (newValue !== 'custom') {
      // User selected a preset - update cron expression
      onChange(newValue);
    }
    // If 'custom' selected, keep current cron expression (no change)
  };
  
  const handleCronChange = (newValue: string) => {
    // User manually edited cron - onChange will trigger re-render
    // and useEffect will auto-sync the preset dropdown
    onChange(newValue);
  };
  
  return (
    <Box sx={{ display: 'flex', gap: 1, alignItems: 'flex-start', flexWrap: 'wrap' }}>
      {/* Preset Dropdown - always visible */}
      <FormControl size={size} sx={{ minWidth: 200 }}>
        <InputLabel>Pattern</InputLabel>
        <Select
          value={selectedPreset}
          label="Pattern"
          onChange={(e) => handlePresetChange(e.target.value)}
          MenuProps={{ disablePortal }}
        >
          {CRON_PATTERNS.map((pattern) => (
            <MenuItem key={pattern.label} value={pattern.value}>
              <Box>
                <Typography variant="body2">{pattern.label}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {pattern.description}
                </Typography>
              </Box>
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      
      {/* Cron Expression TextField - always visible and editable */}
      <TextField
        size={size}
        label="Cron Expression"
        value={value}
        onChange={(e) => handleCronChange(e.target.value)}
        error={!!error}
        helperText={error || 'Editable - presets auto-sync'}
        placeholder="*/10 * * * *"
        sx={{ minWidth: 150 }}
        inputProps={{
          style: { fontFamily: 'monospace' }
        }}
      />
      
      {/* Help link when custom */}
      {selectedPreset === 'custom' && (
        <Typography 
          variant="caption" 
          sx={{ 
            mt: size === 'small' ? 1 : 1.5, 
            display: 'flex', 
            alignItems: 'center', 
            gap: 0.5,
            color: 'text.secondary'
          }}
        >
          <Info sx={{ fontSize: 12 }} />
          <a href="https://crontab.guru" target="_blank" rel="noopener noreferrer" style={{ color: 'inherit' }}>
            crontab.guru
          </a>
        </Typography>
      )}
    </Box>
  );
};
