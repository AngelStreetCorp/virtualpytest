/**
 * Shared Toolbox Search Box
 * 
 * Reusable search component for TestCase and Campaign builder toolboxes.
 * Provides consistent search functionality with icon adornments and clear button.
 */

import React from 'react';
import { Box, TextField, IconButton, InputAdornment } from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import ClearIcon from '@mui/icons-material/Clear';

interface ToolboxSearchBoxProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}

export const ToolboxSearchBox: React.FC<ToolboxSearchBoxProps> = ({
  value,
  onChange,
  placeholder = 'Search...',
}) => {
  return (
    <Box sx={{ p: 1, borderBottom: 1, borderColor: 'divider' }}>
      <TextField
        size="small"
        fullWidth
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        InputProps={{
          startAdornment: (
            <InputAdornment position="start">
              <SearchIcon fontSize="small" />
            </InputAdornment>
          ),
          endAdornment: value && (
            <InputAdornment position="end">
              <IconButton
                size="small"
                onClick={() => onChange('')}
                edge="end"
              >
                <ClearIcon fontSize="small" />
              </IconButton>
            </InputAdornment>
          ),
          sx: { fontSize: '0.875rem' }
        }}
        sx={{
          '& .MuiOutlinedInput-root': {
            '&:hover fieldset': {
              borderColor: 'primary.main',
            },
          },
        }}
      />
    </Box>
  );
};

