import { Box } from '@mui/material';
import React from 'react';

import { useDeviceData } from '../../contexts/device/DeviceDataContext';
import { Action } from '../../types/pages/Navigation_Types';

import { ActionItem } from './ActionItem';

interface ActionsListProps {
  actions: Action[];
  onActionsUpdate: (actions: Action[]) => void;
  onRunAction?: (index: number) => void;
  runDisabled?: boolean;
  runningActionIndex?: number | null;
  runStatusByIndex?: Record<number, 'success' | 'failure'>;
  disabled?: boolean;
}

export type { ActionsListProps };

export const ActionsList: React.FC<ActionsListProps> = ({
  actions,
  onActionsUpdate,
  onRunAction,
  runDisabled = false,
  runningActionIndex = null,
  runStatusByIndex = {},
  disabled = false,
}) => {
  const { getAvailableActions } = useDeviceData();
  const availableActions = getAvailableActions();

  const handleActionSelect = (index: number, actionId: string) => {
    // Find the selected action from available actions by ID
    let selectedAction: any = undefined;

    for (const [, actions] of Object.entries(availableActions)) {
      if (!Array.isArray(actions)) continue;
      const action = actions.find((a) => a.id === actionId);
      if (action) {
        selectedAction = action;
        break;
      }
    }

    if (!selectedAction) {
      console.warn('[ActionsList] No action found for ID:', actionId);
      return;
    }

    const updatedActions = actions.map((action, i) => {
      if (i === index) {
        const newAction = {
          ...action,
          command: selectedAction.command,
          params: { ...selectedAction.params },
          device_model: selectedAction.device_model,
          action_type: selectedAction.action_type,
          verification_type: selectedAction.verification_type || (selectedAction as any).verification_type,
        };
        return newAction;
      }
      return action;
    });
    onActionsUpdate(updatedActions);
  };

  const handleUpdateAction = (index: number, updates: Partial<Action>) => {
    const updatedActions = actions.map((action, i) => {
      if (i === index) {
        return { ...action, ...updates } as Action;
      }
      return action;
    });
    onActionsUpdate(updatedActions);
  };

  const handleRemoveAction = (index: number) => {
    const updatedActions = actions.filter((_, i) => i !== index);
    onActionsUpdate(updatedActions);
  };

  const handleMoveUp = (index: number) => {
    if (index === 0) return;
    const updatedActions = [...actions];
    [updatedActions[index - 1], updatedActions[index]] = [
      updatedActions[index],
      updatedActions[index - 1],
    ];
    onActionsUpdate(updatedActions);
  };

  const handleMoveDown = (index: number) => {
    if (index === actions.length - 1) return;
    const updatedActions = [...actions];
    [updatedActions[index], updatedActions[index + 1]] = [
      updatedActions[index + 1],
      updatedActions[index],
    ];
    onActionsUpdate(updatedActions);
  };

  return (
    <Box>
      {actions.map((action, index) => (
        <ActionItem
          key={index}
          action={action}
          index={index}
          availableActions={availableActions}
          onActionSelect={handleActionSelect}
          onUpdateAction={handleUpdateAction}
          onRemoveAction={handleRemoveAction}
          onMoveUp={handleMoveUp}
          onMoveDown={handleMoveDown}
          onRun={onRunAction}
          canRun={Boolean(action.command) && !runDisabled}
          isRunning={runningActionIndex === index}
          runStatus={runStatusByIndex[index] || null}
          disabled={disabled}
          canMoveUp={index > 0}
          canMoveDown={index < actions.length - 1}
        />
      ))}
    </Box>
  );
};
