import React from 'react';
import { IconButton, Tooltip } from '@mui/material';
import { Undo as UndoIcon, Redo as RedoIcon, Cancel as CancelIcon } from '@mui/icons-material';

interface UndoRedoDiscardButtonsProps {
  onUndo?: () => void;
  onRedo?: () => void;
  onDiscard?: () => void;
  canUndo?: boolean;
  canRedo?: boolean;
  hasUnsavedChanges?: boolean;
  isLoading?: boolean;
  error?: string | null;
  size?: 'small' | 'medium';
}

export const UndoRedoDiscardButtons: React.FC<UndoRedoDiscardButtonsProps> = ({
  onUndo,
  onRedo,
  onDiscard,
  canUndo = false,
  canRedo = false,
  hasUnsavedChanges = false,
  isLoading = false,
  error = null,
  size = 'small',
}) => {
  return (
    <>
      {/* Undo Button */}
      {onUndo && (
        <Tooltip title="Undo (Ctrl+Z)">
          <span>
            <IconButton
              onClick={onUndo}
              size={size}
              disabled={!canUndo || isLoading || !!error}
            >
              <UndoIcon />
            </IconButton>
          </span>
        </Tooltip>
      )}

      {/* Redo Button */}
      {onRedo && (
        <Tooltip title="Redo (Ctrl+Y)">
          <span>
            <IconButton
              onClick={onRedo}
              size={size}
              disabled={!canRedo || isLoading || !!error}
            >
              <RedoIcon />
            </IconButton>
          </span>
        </Tooltip>
      )}

      {/* Discard Button */}
      {onDiscard && (
        <Tooltip title={hasUnsavedChanges ? 'Discard Unsaved Changes' : 'No changes to discard'}>
          <span>
            <IconButton
              onClick={onDiscard}
              size={size}
              color={hasUnsavedChanges ? 'warning' : 'default'}
              disabled={!hasUnsavedChanges || isLoading || !!error}
            >
              <CancelIcon />
            </IconButton>
          </span>
        </Tooltip>
      )}
    </>
  );
};

