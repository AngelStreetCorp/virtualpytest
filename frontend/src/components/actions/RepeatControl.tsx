import { Settings as SettingsIcon } from '@mui/icons-material';
import {
  Box,
  Button,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Popover,
  Select,
  TextField,
  Tooltip,
} from '@mui/material';
import React from 'react';

import type { Action, RepeatUntil, UINavigationNode } from '../../types/pages/Navigation_Types';
import type {
  ModelReferences,
  Verification,
  Verifications,
} from '../../types/verification/Verification_Types';
import { VerificationsList } from '../verification/VerificationsList';

interface RepeatControlProps {
  action: Action;
  index: number;
  onUpdateAction: (index: number, updates: Partial<Action>) => void;
  nodes: UINavigationNode[];
  availableVerifications: Verifications;
  modelReferences: ModelReferences;
  model: string;
  disabled?: boolean;
}

// Sensible defaults when the user first switches an action to "Until ...".
// poll_wait_ms is intentionally NOT exposed in the UI — it's internal pacing;
// the backend also defaults it to 500ms when absent.
const DEFAULT_REPEAT_UNTIL: RepeatUntil = {
  condition: 'appears',
  match: 'all',
  source: 'node',
  verifications: [],
  max_iterations: 10,
  poll_wait_ms: 500,
};

const fieldSx = {
  '& .MuiInputBase-input': { padding: '3px 6px', fontSize: '0.75rem' },
  '& .MuiSelect-select': { padding: '3px 6px', fontSize: '0.75rem' },
};

type RepeatMode = 'count' | 'until_appears' | 'until_disappears';

/**
 * Compact "Repeat" control for a single action. Replaces the old plain
 * "Iterations" field. The Repeat dropdown carries the mode AND the condition:
 *   - Count            → fixed iterations (writes `action.iterator`).
 *   - Until appears    → re-run until verifications pass.
 *   - Until disappears → re-run until verifications fail.
 * (writes `action.repeat_until`; see RepeatUntil in Navigation_Types.)
 *
 * The row stays one line. For Node source the condition's verifications come
 * from the picked node (with an inline "All must pass" selector). For ad-hoc
 * Verifications a gear opens a popover with the verification list (which owns
 * its own "All must pass" selector).
 */
export const RepeatControl: React.FC<RepeatControlProps> = ({
  action,
  index,
  onUpdateAction,
  nodes,
  availableVerifications,
  modelReferences,
  model,
  disabled = false,
}) => {
  const [anchorEl, setAnchorEl] = React.useState<HTMLElement | null>(null);
  const ru = action.repeat_until;
  const mode: RepeatMode = !ru
    ? 'count'
    : ru.condition === 'disappears'
      ? 'until_disappears'
      : 'until_appears';

  const patchRu = (patch: Partial<RepeatUntil>) => {
    const base = ru || DEFAULT_REPEAT_UNTIL;
    onUpdateAction(index, { repeat_until: { ...base, ...patch } });
  };

  const handleModeChange = (next: RepeatMode) => {
    if (next === 'count') {
      onUpdateAction(index, { repeat_until: undefined });
      return;
    }
    const condition = next === 'until_disappears' ? 'disappears' : 'appears';
    const base = ru || DEFAULT_REPEAT_UNTIL;
    onUpdateAction(index, { repeat_until: { ...base, condition } });
  };

  // Snapshot the picked node's verifications into the rule. The backend only
  // reads `verifications`; `target_node_id` is kept for display / re-edit.
  const handleNodeChange = (nodeId: string) => {
    const node = nodes.find((n) => n.id === nodeId);
    const nodeVerifs = (node?.data?.verifications as Verification[]) || [];
    patchRu({
      target_node_id: nodeId,
      verifications: JSON.parse(JSON.stringify(nodeVerifs)),
    });
  };

  const handleSourceChange = (source: 'node' | 'verifications') => {
    if (source === 'node') {
      patchRu({ source, verifications: [] });
    } else {
      patchRu({ source, target_node_id: undefined });
    }
  };

  const verifCount = ru?.verifications?.length || 0;

  return (
    <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center', flexWrap: 'nowrap' }}>
      {/* Mode + condition combined */}
      <FormControl size="small" sx={{ width: 150 }}>
        <InputLabel>Repeat</InputLabel>
        <Select
          label="Repeat"
          value={mode}
          disabled={disabled}
          onChange={(e) => handleModeChange(e.target.value as RepeatMode)}
          sx={fieldSx}
        >
          <MenuItem value="count" sx={{ fontSize: '0.75rem' }}>
            Count
          </MenuItem>
          <MenuItem value="until_appears" sx={{ fontSize: '0.75rem' }}>
            Until appears
          </MenuItem>
          <MenuItem value="until_disappears" sx={{ fontSize: '0.75rem' }}>
            Until disappears
          </MenuItem>
        </Select>
      </FormControl>

      {mode === 'count' ? (
        <TextField
          autoComplete="off"
          label="Iterations"
          type="number"
          size="small"
          disabled={disabled}
          value={action.iterator || 1}
          onChange={(e) => {
            const value = parseInt(e.target.value);
            const clamped = isNaN(value) ? 1 : Math.max(1, Math.min(100, value));
            onUpdateAction(index, { iterator: clamped });
          }}
          inputProps={{ min: 1, max: 100, step: 1 }}
          sx={{ width: 90, ...fieldSx }}
        />
      ) : (
        <>
          {/* Source: Node | Verifications */}
          <FormControl size="small" sx={{ width: 105 }}>
            <InputLabel>Wait for</InputLabel>
            <Select
              label="Wait for"
              value={ru?.source || 'node'}
              disabled={disabled}
              onChange={(e) =>
                handleSourceChange(e.target.value as 'node' | 'verifications')
              }
              sx={fieldSx}
            >
              <MenuItem value="node" sx={{ fontSize: '0.75rem' }}>
                Node
              </MenuItem>
              <MenuItem value="verifications" sx={{ fontSize: '0.75rem' }}>
                Verifs
              </MenuItem>
            </Select>
          </FormControl>

          {ru?.source === 'node' ? (
            <>
              {/* Node picker */}
              <FormControl size="small" sx={{ width: 150 }}>
                <InputLabel>Node</InputLabel>
                <Select
                  label="Node"
                  value={ru?.target_node_id || ''}
                  disabled={disabled}
                  onChange={(e) => handleNodeChange(e.target.value)}
                  sx={fieldSx}
                >
                  {nodes.length === 0 && (
                    <MenuItem disabled value="" sx={{ fontSize: '0.75rem', fontStyle: 'italic' }}>
                      No nodes
                    </MenuItem>
                  )}
                  {nodes
                    .slice()
                    .sort((a, b) =>
                      (a.data?.label || a.id)
                        .toLowerCase()
                        .localeCompare((b.data?.label || b.id).toLowerCase()),
                    )
                    .map((n) => (
                      <MenuItem key={n.id} value={n.id} sx={{ fontSize: '0.75rem' }}>
                        {n.data?.label || n.id}
                      </MenuItem>
                    ))}
                </Select>
              </FormControl>

              {/* All-must-pass selector (inline; no modal for node source) */}
              <FormControl size="small" sx={{ width: 130 }}>
                <InputLabel>Pass</InputLabel>
                <Select
                  label="Pass"
                  value={ru?.match || 'all'}
                  disabled={disabled}
                  onChange={(e) => patchRu({ match: e.target.value as 'all' | 'any' })}
                  sx={fieldSx}
                >
                  <MenuItem value="all" sx={{ fontSize: '0.75rem' }}>
                    All must pass
                  </MenuItem>
                  <MenuItem value="any" sx={{ fontSize: '0.75rem' }}>
                    Any passes
                  </MenuItem>
                </Select>
              </FormControl>
            </>
          ) : (
            <>
              {/* Ad-hoc verifications — gear opens the list popover */}
              <Tooltip title="Edit verifications">
                <span>
                  <IconButton
                    size="small"
                    disabled={disabled}
                    onClick={(e) => setAnchorEl(e.currentTarget)}
                    sx={{ p: 0.5, width: 28, height: 28 }}
                  >
                    <SettingsIcon sx={{ fontSize: '1rem' }} />
                  </IconButton>
                </span>
              </Tooltip>
              <Box sx={{ fontSize: '0.7rem', color: 'text.secondary', whiteSpace: 'nowrap' }}>
                {verifCount} verif{verifCount === 1 ? '' : 's'}
              </Box>

              <Popover
                open={Boolean(anchorEl)}
                anchorEl={anchorEl}
                onClose={() => setAnchorEl(null)}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
              >
                <Box sx={{ p: 1.5, width: 420, maxWidth: '90vw' }}>
                  <VerificationsList
                    verifications={ru?.verifications || []}
                    availableVerifications={availableVerifications}
                    onVerificationsChange={(next) => patchRu({ verifications: next })}
                    loading={false}
                    model={model}
                    testResults={[]}
                    onReferenceSelected={() => {}}
                    modelReferences={modelReferences}
                    referencesLoading={false}
                    showCollapsible={false}
                    title=""
                    onTest={undefined}
                    referenceReadOnly={true}
                    passCondition={ru?.match || 'all'}
                    onPassConditionChange={(c) => patchRu({ match: c })}
                  />
                  <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 1 }}>
                    <Button size="small" onClick={() => setAnchorEl(null)}>
                      Done
                    </Button>
                  </Box>
                </Box>
              </Popover>
            </>
          )}

          {/* Max iterations */}
          <TextField
            autoComplete="off"
            label="Max"
            type="number"
            size="small"
            disabled={disabled}
            value={ru?.max_iterations || 10}
            onChange={(e) => {
              const value = parseInt(e.target.value);
              const clamped = isNaN(value) ? 1 : Math.max(1, Math.min(100, value));
              patchRu({ max_iterations: clamped });
            }}
            inputProps={{ min: 1, max: 100, step: 1 }}
            sx={{ width: 70, ...fieldSx }}
          />
        </>
      )}
    </Box>
  );
};
