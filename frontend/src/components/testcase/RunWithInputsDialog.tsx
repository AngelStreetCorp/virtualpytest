/**
 * RunWithInputsDialog — collect run-time values for a parameterized testcase.
 *
 * Shown before executing a testcase whose scriptConfig declares non-protected
 * inputs. Each input gets a typed editor pre-filled with its default (node →
 * node dropdown when navNodes are available, number → numeric field, anything
 * else → text). Running with the defaults is one click. The caller stamps the
 * returned values onto the graph with stampInputValues before POSTing.
 */

import { PlayArrow as RunIcon } from '@mui/icons-material';
import {
  Button,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
} from '@mui/material';
import React, { useEffect, useState } from 'react';

import { StyledDialog } from '../common/StyledDialog';
import { ScriptInput } from '../../types/testcase/TestCase_Types';

interface NavNodeOption {
  node_id?: string;
  label?: string;
  node_type?: string;
}

interface RunWithInputsDialogProps {
  open: boolean;
  /** Non-protected inputs only — the caller filters out host_name & co. */
  inputs: ScriptInput[];
  /** Nodes for 'node'-typed inputs; when absent they fall back to free text. */
  navNodes?: NavNodeOption[];
  testcaseName?: string;
  onRun: (values: Record<string, string>) => void;
  onCancel: () => void;
}

const defaultsOf = (inputs: ScriptInput[]): Record<string, string> =>
  Object.fromEntries(inputs.map((input) => [input.name, input.default != null ? String(input.default) : '']));

export const RunWithInputsDialog: React.FC<RunWithInputsDialogProps> = ({
  open,
  inputs,
  navNodes,
  testcaseName,
  onRun,
  onCancel,
}) => {
  const [values, setValues] = useState<Record<string, string>>({});

  // Re-seed from defaults each time the dialog opens (or the input set changes).
  useEffect(() => {
    if (open) setValues(defaultsOf(inputs));
  }, [open, inputs]);

  const missingRequired = inputs.some((input) => input.required && !(values[input.name] ?? '').trim());

  const nodeOptions = (navNodes || []).filter((n) => n.label && n.node_type !== 'entry');

  const renderField = (input: ScriptInput) => {
    const value = values[input.name] ?? '';
    const onChange = (next: string) => setValues((prev) => ({ ...prev, [input.name]: next }));
    const common = {
      key: input.name,
      size: 'small' as const,
      fullWidth: true,
      label: input.name,
      required: input.required,
      error: input.required && !value.trim(),
      helperText: input.description || undefined,
      value,
    };

    if (input.type === 'node' && nodeOptions.length > 0) {
      return (
        <TextField {...common} select onChange={(e) => onChange(e.target.value)}>
          {nodeOptions.map((n) => (
            <MenuItem key={n.node_id || n.label} value={n.label!}>
              {n.label}
            </MenuItem>
          ))}
        </TextField>
      );
    }
    return (
      <TextField
        {...common}
        type={input.type === 'number' ? 'number' : 'text'}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  };

  return (
    <StyledDialog
      open={open}
      onClose={onCancel}
      maxWidth="xs"
      fullWidth
    >
      <DialogTitle>Run {testcaseName ? `"${testcaseName}"` : 'test'} with inputs</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {inputs.map(renderField)}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>Cancel</Button>
        <Button
          variant="contained"
          startIcon={<RunIcon />}
          disabled={missingRequired}
          onClick={() => onRun(values)}
        >
          Run
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};
