import CloseIcon from '@mui/icons-material/Close';
import React, { useState } from 'react';
import {
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
  IconButton,
} from '@mui/material';
import { ActionBlockData } from '../../../types/testcase/TestCase_Types';
import { ActionsList } from '../../actions';
import { getZIndex } from '../../../utils/zIndexUtils';
import { StyledDialog } from '../../common/StyledDialog';

interface ActionConfigDialogProps {
  open: boolean;
  initialData?: ActionBlockData;
  onSave: (data: ActionBlockData) => void;
  onCancel: () => void;
}

export const ActionConfigDialog: React.FC<ActionConfigDialogProps> = ({
  open,
  initialData,
  onSave,
  onCancel,
}) => {
  // Store single action in an array for ActionsList component
  const [actions, setActions] = useState<any[]>([
    initialData || { command: '', params: { wait_time: 500 } }
  ]);

  const handleSave = () => {
    // Save the first (and only) action
    if (actions.length > 0 && actions[0].command) {
      onSave(actions[0]);
    }
  };

  const isValid = actions.length > 0 && Boolean(actions[0].command);

  return (
    <StyledDialog 
      open={open} 
      onClose={onCancel} 
      maxWidth="md" 
      fullWidth
      sx={{ zIndex: getZIndex('NAVIGATION_DIALOGS') }}
    >
      <DialogTitle sx={{ borderBottom: 0, borderColor: 'divider', pb: 0 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography variant="h6">Configure Action</Typography>
          <IconButton onClick={onCancel} size="small">
            <CloseIcon />
          </IconButton>
        </Box>
      </DialogTitle>

      <DialogContent sx={{ py: 0 }}>
        {/* Reuse ActionsList component from Navigation Editor */}
        <Box
          sx={{
            border: '0px solid',
            borderColor: 'divider',
            borderRadius: 1,
            p: 0.5,
          }}
        >
          <ActionsList
            actions={actions}
            onActionsUpdate={setActions}
          />
        </Box>
      </DialogContent>

      <DialogActions sx={{ borderTop: 0, borderColor: 'divider', pt: 0, pb: 0.5, px: 3 }}>
        <Button onClick={onCancel} variant="outlined">
          Cancel
        </Button>
        <Button onClick={handleSave} variant="contained" disabled={!isValid}>
          Save
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};
