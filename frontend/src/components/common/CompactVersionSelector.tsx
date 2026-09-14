import React from 'react';
import { Button, Menu, MenuItem } from '@mui/material';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';

export interface CompactVersionOption {
  key: string;
  label: string;
  versionNumber: number | null;
}

interface CompactVersionSelectorProps {
  valueKey: string;
  options: CompactVersionOption[];
  disabled?: boolean;
  onChange: (option: CompactVersionOption) => void;
}

export const CompactVersionSelector: React.FC<CompactVersionSelectorProps> = ({
  valueKey,
  options,
  disabled = false,
  onChange,
}) => {
  const [anchorEl, setAnchorEl] = React.useState<null | HTMLElement>(null);
  const selectedOption = options.find((option) => option.key === valueKey) || options[0];

  return (
    <>
      <Button
        size="small"
        variant="outlined"
        endIcon={<KeyboardArrowDownIcon fontSize="small" />}
        onClick={(event) => setAnchorEl(event.currentTarget)}
        disabled={disabled || options.length === 0}
        sx={{ minWidth: 96 }}
      >
        {selectedOption?.label || 'Latest'}
      </Button>
      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={() => setAnchorEl(null)}
      >
        {options.map((option) => (
          <MenuItem
            key={option.key}
            selected={option.key === valueKey}
            onClick={() => {
              setAnchorEl(null);
              onChange(option);
            }}
          >
            {option.label}
          </MenuItem>
        ))}
      </Menu>
    </>
  );
};
