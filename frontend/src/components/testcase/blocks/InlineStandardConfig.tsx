/**
 * InlineStandardConfig
 *
 * A Standard block's inline config: pick which standard operation (sleep /
 * set_variable / condition / …) from a dropdown directly on the block, then
 * edit its params inline via DynamicParamForm. This is the generic-block
 * equivalent of the old per-op toolbox items — one "Standard" block that
 * "summons" the individual operation inside it.
 *
 * The operation list + param schemas come from the builder context
 * (useBuilder().standardBlocks, loaded after taking control). Writes
 * command / action_type / params / paramSchema back to the node.
 */

import React, { useMemo } from 'react';
import { Box, MenuItem, TextField } from '@mui/material';

import { useBuilder } from '../../../contexts/builder/useBuilder';
import { DynamicParamForm } from '../dialogs/DynamicParamForm';

interface InlineStandardConfigProps {
  data: any;
  onUpdate: (partial: any) => void;
}

export const InlineStandardConfig: React.FC<InlineStandardConfigProps> = ({ data, onUpdate }) => {
  let standardBlocks: any[] = [];
  try {
    standardBlocks = useBuilder().standardBlocks || [];
  } catch {
    // Outside provider — render an empty picker.
  }
  const ops = useMemo(
    () => standardBlocks.filter((b) => b.category !== 'api'),
    [standardBlocks],
  );

  const selected = ops.find((o) => o.command === data.command);
  // Prefer the schema stored on the block; fall back to the op definition.
  const schema =
    (data.paramSchema && Object.keys(data.paramSchema).length ? data.paramSchema : selected?.params) || {};

  const handlePick = (command: string) => {
    const op = ops.find((o) => o.command === command);
    const defaults: Record<string, any> = {};
    Object.entries(op?.params || {}).forEach(([k, s]: [string, any]) => {
      if (s && typeof s === 'object' && 'default' in s) defaults[k] = s.default;
    });
    onUpdate({
      command,
      action_type: 'standard_block',
      params: defaults,
      paramSchema: op?.params || {},
    });
  };

  return (
    // nodrag: keep clicks inside the editor from starting a node drag.
    <Box className="nodrag" onClick={(e) => e.stopPropagation()}>
      <TextField
        select
        fullWidth
        size="small"
        label="Operation"
        value={data.command || ''}
        onChange={(e) => handlePick(e.target.value)}
        disabled={!ops.length}
        helperText={!ops.length ? 'Take control to load operations' : undefined}
      >
        {ops.map((o) => (
          <MenuItem key={o.command} value={o.command} sx={{ fontSize: '0.8rem' }}>
            {o.label || o.description || o.command}
          </MenuItem>
        ))}
      </TextField>

      {data.command && Object.keys(schema).length > 0 && (
        <Box sx={{ mt: 1 }}>
          <DynamicParamForm
            params={schema}
            values={data.params || {}}
            onChange={(name, val) =>
              onUpdate({ params: { ...(data.params || {}), [name]: val } })
            }
          />
        </Box>
      )}
    </Box>
  );
};
