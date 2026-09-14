/**
 * InlineActionConfig
 *
 * Renders an Action block's config directly INSIDE the block — no modal. An
 * action block is a CONTAINER: it holds an ordered SEQUENCE of actions
 * (e.g. press OK → wait → volume up), exactly like an edge's action_set. Reuses
 * ActionsList/ActionItem (the same components Edit-Edge uses); ActionsList
 * sources the available commands from DeviceDataContext, so the per-action
 * command dropdown is populated without any toolbox enumeration.
 *
 * ActionsList itself has no "add" affordance (the edge dialog seeds rows), so
 * this wrapper provides the Add button and writes the whole sequence back to the
 * node on every change.
 */

import React, { useState } from 'react';
import { Box, Button } from '@mui/material';
import { Add as AddIcon } from '@mui/icons-material';

import { ActionsList } from '../../actions';
import { useAction } from '../../../hooks/actions/useAction';
import { useDeviceData } from '../../../contexts/device/DeviceDataContext';
import { useTestCaseBuilder } from '../../../contexts/testcase/TestCaseBuilderContext';
import { resolveParamsVariables } from '../../../utils/variableResolutionUtils';
import { ActionBlockData } from '../../../types/testcase/TestCase_Types';

interface InlineActionConfigProps {
  data: ActionBlockData;
  onUpdate: (partial: Partial<ActionBlockData>) => void;
}

export const InlineActionConfig: React.FC<InlineActionConfigProps> = ({ data, onUpdate }) => {
  const actions = data.actions || [];

  const { currentHost } = useDeviceData();
  const { executeActions } = useAction();
  let scriptInputs: any[] = [];
  let scriptVariables: any[] = [];
  try {
    const ctx = useTestCaseBuilder();
    scriptInputs = ctx.scriptInputs;
    scriptVariables = ctx.scriptVariables;
  } catch {
    // Outside provider — run without variable resolution context.
  }

  // Per-item Run state: which row is executing, and the last result per row.
  const [runningActionIndex, setRunningActionIndex] = useState<number | null>(null);
  const [runStatusByIndex, setRunStatusByIndex] = useState<
    Record<number, 'success' | 'failure'>
  >({});

  // Run a single action with the exact item shape UniversalBlock.handleExecute
  // builds (command, name, resolved params, action_type, …).
  const handleRun = async (index: number) => {
    const it: any = actions[index];
    if (!it?.command || !currentHost) return;
    setRunningActionIndex(index);
    try {
      const item = {
        command: it.command,
        name: it.label || it.command,
        params: resolveParamsVariables(it.params || {}, scriptInputs, scriptVariables),
        action_type: it.action_type,
        verification_type: it.verification_type,
        threshold: it.threshold,
        reference: it.reference,
      };
      const result = await executeActions([item] as any, [], []);
      setRunStatusByIndex((prev) => ({ ...prev, [index]: result.success ? 'success' : 'failure' }));
    } catch {
      setRunStatusByIndex((prev) => ({ ...prev, [index]: 'failure' }));
    } finally {
      setRunningActionIndex(null);
    }
  };

  // An action block must keep at least one action — ignore an edit that would
  // empty the sequence (so the user never sees an empty block / can't delete
  // the last row).
  const handleUpdate = (next: any[]) => {
    if (next.length === 0) return;
    onUpdate({ actions: next });
  };

  const handleAdd = () => {
    handleUpdate([...actions, { command: '', params: {} }]);
  };

  return (
    // nodrag: keep clicks/drags inside the editor from starting a node drag.
    <Box className="nodrag">
      <ActionsList
        actions={actions as any}
        onActionsUpdate={handleUpdate}
        // Per-item Run — only when a device is controlled (else undefined hides
        // the run affordance).
        onRunAction={currentHost ? (index: number) => void handleRun(index) : undefined}
        runningActionIndex={runningActionIndex}
        runStatusByIndex={runStatusByIndex}
      />
      <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 0.5 }}>
        <Button
          size="small"
          variant="outlined"
          startIcon={<AddIcon />}
          onClick={handleAdd}
          sx={{ minWidth: 'auto', fontSize: '0.75rem', py: 0.25 }}
        >
          Add action
        </Button>
      </Box>
    </Box>
  );
};
