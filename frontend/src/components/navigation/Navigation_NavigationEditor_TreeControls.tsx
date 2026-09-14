import { Box, FormControl, InputLabel, Select, MenuItem, ListSubheader, Button, Typography } from '@mui/material';
import React from 'react';

import { NavigationEditorTreeControlsProps } from '../../types/pages/NavigationHeader_Types';

export const NavigationEditorTreeControls: React.FC<NavigationEditorTreeControlsProps> = ({
  focusNodeId,
  availableFocusNodes,
  // Depth control is hidden in the UI but the prop remains wired so the
  // underlying logic stays intact for future re-introduction.
  maxDisplayDepth: _maxDisplayDepth,
  totalNodes,
  visibleNodes,
  onFocusNodeChange,
  onDepthChange: _onDepthChange,
  onResetFocus,
}) => {
  // Ensure availableFocusNodes is an array. Entries span the whole interface
  // (root + every subtree); each carries a composite `value` (`treeId::nodeId`)
  // and a `groupLabel` naming the owning tree.
  const safeNodes = Array.isArray(availableFocusNodes) ? availableFocusNodes : [];

  // Render the dropdown items grouped by their owning tree. Nodes arrive
  // contiguous per tree, so emit a (non-selectable) ListSubheader whenever the
  // group changes.
  const focusItems = React.useMemo(() => {
    const items: React.ReactNode[] = [];
    let lastGroup: string | null = null;
    safeNodes.forEach((node: any) => {
      const value = node.value ?? node.id;
      const group = node.groupLabel ?? null;
      if (group && group !== lastGroup) {
        items.push(
          <ListSubheader key={`group-${group}`} sx={{ fontSize: '0.7rem', lineHeight: '24px' }}>
            {group}
          </ListSubheader>,
        );
        lastGroup = group;
      }
      items.push(
        <MenuItem key={value} value={value} sx={{ fontSize: '0.75rem' }}>
          {node.label || node.id}
        </MenuItem>,
      );
    });
    return items;
  }, [safeNodes]);

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        '& .MuiFormControl-root': {
          minWidth: '70px !important',
          marginRight: '8px',
        },
        '& .MuiButton-root': {
          fontSize: '0.75rem',
          minWidth: 'auto',
          padding: '4px 8px',
        },
        '& .MuiTypography-root': {
          fontSize: '0.75rem',
          whiteSpace: 'nowrap',
        },
      }}
    >
      {/* Focus Node Selection */}
      <FormControl size="small">
        <InputLabel id="focus-node-label">Focus</InputLabel>
        <Select
          labelId="focus-node-label"
          value={focusNodeId || ''}
          onChange={(e) => onFocusNodeChange(e.target.value || null)}
          label="Focus"
          sx={{ height: 32, fontSize: '0.75rem' }}
        >
          <MenuItem value="">
            <em>None</em>
          </MenuItem>
          {focusItems}
        </Select>
      </FormControl>

      {/* Reset Focus Button */}
      <Button onClick={onResetFocus} size="small" variant="outlined" sx={{ fontSize: '0.75rem' }}>
        Reset
      </Button>

      {/* Node Count Display */}
      <Typography variant="caption" sx={{ ml: 1 }}>
        {visibleNodes}/{totalNodes} nodes
      </Typography>
    </Box>
  );
};

export default NavigationEditorTreeControls;
