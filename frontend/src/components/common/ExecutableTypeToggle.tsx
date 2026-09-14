import React from 'react';
import { Box, Chip } from '@mui/material';

type ToggleColor = 'primary' | 'secondary' | 'success' | 'default';

export interface ExecutableTypeToggleOption {
  id: string;
  label: string;
  color: ToggleColor;
}

interface ExecutableTypeToggleProps {
  options: ExecutableTypeToggleOption[];
  value: string | null;
  onChange: (id: string) => void;
}

export const ExecutableTypeToggle: React.FC<ExecutableTypeToggleProps> = ({
  options,
  value,
  onChange,
}) => {
  if (options.length === 0) {
    return null;
  }

  return (
    <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'nowrap', alignItems: 'center' }}>
      {options.map((option) => {
        const selected = value === option.id;
        return (
          <Chip
            key={option.id}
            label={option.label}
            size="small"
            color={option.color}
            variant={selected ? 'filled' : 'outlined'}
            clickable
            onClick={() => onChange(option.id)}
            sx={{
              height: '22px',
              minWidth: '34px',
              fontSize: '0.68rem',
              fontWeight: 600,
            }}
          />
        );
      })}
    </Box>
  );
};
