import { Add as AddIcon } from '@mui/icons-material';
import { Box, Button } from '@mui/material';
import React, { useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { AppIcon } from '../../constants/icons';
import { TYPOGRAPHY } from '../../constants/typography';
import { CompactListRow, humanizeCommand } from '../common/CompactListRow';

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
  // Compact rows (Edit edge dialog): one summary line per action that opens
  // its editor on click, plus an "Add action" footer when onAdd is given.
  compact?: boolean;
  onAdd?: () => void;
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
  compact = false,
  onAdd,
}) => {
  const P = useAgentChatPalette();
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());
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
    setExpandedRows(new Set());
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

  if (compact) {
    const allActions = Object.values(availableActions).flat() as any[];
    const toggleRow = (index: number) =>
      setExpandedRows((prev) => {
        const next = new Set(prev);
        if (next.has(index)) next.delete(index);
        else next.add(index);
        return next;
      });
    return (
      <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 1 }}>
        {actions.map((action, index) => {
          const params: any = action.params || {};
          const known = allActions.filter((a) => a.command === action.command);
          const def =
            known.find((a) => a.params?.key && a.params.key === params.key) ||
            known.find((a) => a.params?.direction && a.params.direction === params.direction) ||
            known[0];
          // Warn only once the device's action list is loaded: an empty list means "not known yet".
          const supported = !action.command || allActions.length === 0 || known.length > 0;
          const detail = params.key || params.text || params.element_id || params.package || params.url || '';
          const label = def?.label || humanizeCommand(action.command);
          const title = action.command
            ? `${label}${detail && !String(label).includes(String(detail)) ? ` · ${detail}` : ''}`
            : 'New action';
          const iterations = action.iterator;
          const meta = [
            params.wait_time ? `wait ${Math.round(params.wait_time / 100) / 10} s` : null,
            action.repeat_until ? 'repeat until' : iterations && iterations > 1 ? `×${iterations}` : null,
            action.continue_on_fail ? 'optional' : null,
          ]
            .filter(Boolean)
            .join(' · ');
          return (
            <CompactListRow
              key={index}
              first={index === 0}
              title={title}
              meta={meta || undefined}
              warning={supported ? undefined : 'not on this device'}
              leading={
                <Box
                  sx={{ width: 28, height: 28, borderRadius: 1, bgcolor: P.hoverBg, color: P.textSecondary, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                >
                  <AppIcon name={action.action_type === 'verification' ? 'image' : action.action_type === 'web' ? 'globe' : 'device'} />
                </Box>
              }
              expanded={!action.command || expandedRows.has(index)}
              onToggle={() => toggleRow(index)}
              onRun={onRunAction ? () => onRunAction(index) : undefined}
              canRun={Boolean(action.command) && !runDisabled}
              isRunning={runningActionIndex === index}
              runStatus={runStatusByIndex[index] || null}
              onRemove={() => handleRemoveAction(index)}
              disabled={disabled}
            >
              <ActionItem
                bare
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
            </CompactListRow>
          );
        })}
        {onAdd && (
          <Box sx={{ borderTop: actions.length ? `1px solid ${P.borderColor}` : 'none', px: 0.5, py: 0.25 }}>
            <Button
              size="small"
              startIcon={<AddIcon />}
              onClick={onAdd}
              disabled={disabled}
              sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, textTransform: 'none' }}
            >
              Add action
            </Button>
          </Box>
        )}
      </Box>
    );
  }

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
