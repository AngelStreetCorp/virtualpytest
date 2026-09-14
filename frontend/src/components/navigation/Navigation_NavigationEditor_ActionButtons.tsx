import {
  Add as AddIcon,
  Save as SaveIcon,
} from '@mui/icons-material';
import { Box, Button, IconButton, CircularProgress } from '@mui/material';
import React from 'react';

import { NavigationEditorActionButtonsProps } from '../../types/pages/NavigationHeader_Types';
import { UndoRedoDiscardButtons } from '../common/UndoRedoDiscardButtons';

export const NavigationEditorActionButtons: React.FC<NavigationEditorActionButtonsProps> = ({
  // Validate button moved to the editor header next to the variant chip;
  // these props remain in the interface but are unused here.
  treeId: _treeId,
  isLocked: _isLocked,
  hasUnsavedChanges,
  isLoading,
  error,
  selectedHost: _selectedHost,
  selectedDeviceId: _selectedDeviceId,
  isControlActive: _isControlActive,
  onAddNewNode,
  onSaveToConfig,
  onDiscardChanges,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
}) => {
  const [isSaving, setIsSaving] = React.useState(false);

  const handleSaveClick = async () => {
    if (!onSaveToConfig) return;
    setIsSaving(true);
    try {
      await onSaveToConfig();
    } finally {
      setIsSaving(false);
    }
  };
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 1,
        minWidth: 0,
      }}
    >
      {/* Validate button moved to the editor header (left of the variant chip).
          See Navigation_EditorHeader.tsx. */}

      {/* Add Node Button — available regardless of take-control, mirroring
          Edit / Delete on existing nodes which also work without it. */}
      <Button
        startIcon={<AddIcon />}
        onClick={() => onAddNewNode('screen', { x: 250, y: 250 })}
        size="small"
        disabled={isLoading || !!error}
        variant="outlined"
        sx={{
          minWidth: 'auto',
          whiteSpace: 'nowrap',
          fontSize: '0.75rem',
          px: 1,
          '& .MuiButton-startIcon': { mr: 0.5 },
        }}
        title="Add Node"
      >
        Add&nbsp;Node
      </Button>

      {/* Undo/Redo/Discard Buttons */}
      <UndoRedoDiscardButtons
        onUndo={onUndo}
        onRedo={onRedo}
        onDiscard={onDiscardChanges}
        canUndo={canUndo}
        canRedo={canRedo}
        hasUnsavedChanges={hasUnsavedChanges}
        isLoading={isLoading}
        error={error}
      />

      {/* Save Button */}
      <IconButton
        onClick={handleSaveClick}
        size="small"
        title={
          hasUnsavedChanges
            ? 'Save Changes to Config'
            : 'Save to Config'
        }
        disabled={isLoading || isSaving || !!error}
        color={hasUnsavedChanges ? 'primary' : 'default'}
      >
        {isLoading || isSaving ? <CircularProgress size={20} /> : <SaveIcon />}
      </IconButton>
    </Box>
  );
};

export default NavigationEditorActionButtons;
