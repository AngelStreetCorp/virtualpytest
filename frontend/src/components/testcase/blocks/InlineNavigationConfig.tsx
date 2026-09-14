/**
 * InlineNavigationConfig
 *
 * A Navigation block's inline config: pick the target node from a dropdown
 * directly on the block (no modal). The node list comes from the builder
 * context's `availableNodes` (loaded for the selected userinterface). Writes
 * target_node_label + target_node_id back to the node on change.
 */

import React from 'react';
import { Box, MenuItem, TextField } from '@mui/material';

import { useTestCaseBuilder } from '../../../contexts/testcase/TestCaseBuilderContext';
import { NavigationBlockData } from '../../../types/testcase/TestCase_Types';

interface InlineNavigationConfigProps {
  data: NavigationBlockData;
  onUpdate: (partial: Partial<NavigationBlockData>) => void;
}

export const InlineNavigationConfig: React.FC<InlineNavigationConfigProps> = ({ data, onUpdate }) => {
  let contextData: any = null;
  try {
    contextData = useTestCaseBuilder();
  } catch {
    // Outside provider — render an empty picker.
  }
  const availableNodes: any[] = contextData?.availableNodes || [];

  const handleSelect = (label: string) => {
    const node = availableNodes.find((n) => (n.label || n.data?.label) === label);
    onUpdate({
      target_node_label: label,
      target_node_id: node?.id || node?.node_id,
    });
  };

  return (
    // nodrag: keep clicks inside the picker from starting a node drag.
    <Box className="nodrag" onClick={(e) => e.stopPropagation()}>
      <TextField
        select
        fullWidth
        size="small"
        label="Target node"
        value={data.target_node_label || ''}
        onChange={(e) => handleSelect(e.target.value)}
        disabled={!availableNodes.length}
        helperText={!availableNodes.length ? 'Take control + select a user interface' : undefined}
      >
        {availableNodes
          .map((n) => n.label || n.data?.label)
          .filter(Boolean)
          .map((label: string) => (
            <MenuItem key={label} value={label} sx={{ fontSize: '0.8rem' }}>
              {label}
            </MenuItem>
          ))}
      </TextField>
    </Box>
  );
};
