import React, { useState, useEffect } from 'react';
import {
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Box,
  Typography,
  CircularProgress,
} from '@mui/material';
import { NavigationBlockData, NavigationForm } from '../../../types/testcase/TestCase_Types';
import { useTestCaseBuilder } from '../../../contexts/testcase/TestCaseBuilderContext';
import { StyledDialog } from '../../common/StyledDialog';

interface NavigationConfigDialogProps {
  open: boolean;
  initialData?: NavigationBlockData;
  onSave: (data: NavigationBlockData) => void;
  onCancel: () => void;
}

export const NavigationConfigDialog: React.FC<NavigationConfigDialogProps> = ({
  open,
  initialData,
  onSave,
  onCancel,
}) => {
  // Try to get available nodes from context (if available)
  // This allows the component to work both within and outside TestCaseBuilderProvider
  let contextData: any = null;
  try {
    contextData = useTestCaseBuilder();
  } catch (error) {
    // Context not available
    // Continue with empty array
  }
  
  const availableNodes = contextData?.availableNodes || [];
  const isLoadingOptions = contextData?.isLoadingOptions || false;
  
  const [formData, setFormData] = useState<NavigationForm>({
    target_node_label: initialData?.target_node_label || '',
    target_node_id: initialData?.target_node_id || '',
    isValid: false,
  });

  // Get available nodes from context
  const isLoading = isLoadingOptions;

  useEffect(() => {
    // Validate form
    const isValid = Boolean(formData.target_node_label);
    setFormData((prev) => ({ ...prev, isValid }));
  }, [formData.target_node_label]);

  const handleNodeChange = (nodeId: string) => {
    const selectedNode = availableNodes.find((node: any) => node.node_id === nodeId);
    setFormData((prev) => ({
      ...prev,
      target_node_id: nodeId,
      target_node_label: selectedNode?.label || nodeId,
    }));
  };

  const handleSave = () => {
    const { isValid: _isValid, ...dataToSave } = formData;
    onSave(dataToSave);
  };

  return (
    <StyledDialog open={open} onClose={onCancel} maxWidth="sm" fullWidth>
      <DialogTitle>Configure Navigation Block</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 2 }}>
          <Typography variant="body2" color="text.secondary">
            Select the destination node for navigation
          </Typography>

          {isLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
              <CircularProgress size={24} />
            </Box>
          ) : (
            <FormControl fullWidth>
              <InputLabel>Target Node</InputLabel>
              <Select
                value={formData.target_node_id}
                label="Target Node"
                onChange={(e) => handleNodeChange(e.target.value)}
              >
                {availableNodes.map((node: any) => (
                  <MenuItem key={node.node_id} value={node.node_id}>
                    {node.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>Cancel</Button>
        <Button onClick={handleSave} variant="contained" disabled={!formData.isValid || isLoading}>
          Save
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};

