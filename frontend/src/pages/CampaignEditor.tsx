import {
  Add as AddIcon,
  Visibility as VisibilityIcon,
  VisibilityOff as VisibilityOffIcon,
} from '@mui/icons-material';
import {
  Box,
  Paper,
  Typography,
  Button,
  IconButton,
} from '@mui/material';
import React, { useRef, useState } from 'react';

// Reuse CampaignSelector component
import { CampaignSelector } from '../components/campaign/CampaignSelector';
import { useConfirmDialog } from '../hooks/useConfirmDialog';
import { ConfirmDialog } from '../components/common/ConfirmDialog';

import { buildServerUrl } from '../utils/buildUrlUtils';

const CampaignEditor: React.FC = () => {
  // Ref to access CampaignSelector's refresh method
  const selectorRef = useRef<{ refresh: () => void }>(null);
  const [showHidden, setShowHidden] = useState(false);
  
  // Confirmation dialog
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  // Handle campaign load - store in sessionStorage and navigate to builder
  const handleLoad = (campaignId: string) => {
    console.log('[@CampaignEditor] Loading campaign:', campaignId);
    
    // Store campaign ID to load in sessionStorage
    sessionStorage.setItem('campaign_to_load', campaignId);
    
    // Navigate to Campaign Builder (it will check sessionStorage on mount)
    window.location.href = '/builder/campaign-builder';
  };

  // Handle campaign delete
  const handleDelete = async (campaignId: string, campaignName: string) => {
    confirm({
      title: 'Confirm Delete',
      message: `Are you sure you want to delete "${campaignName}"?`,
      confirmColor: 'error',
      onConfirm: async () => {
        try {
          const response = await fetch(buildServerUrl(`/server/campaigns/deleteCampaign/${campaignId}`), {
            method: 'DELETE',
          });

          if (!response.ok) {
            throw new Error('Failed to delete campaign');
          }
          
          // After successful deletion, refresh the list
          if (selectorRef.current) {
            selectorRef.current.refresh();
          }
        } catch (err) {
          console.error('Error deleting campaign:', err);
          throw err;
        }
      },
    });
  };

  // Navigate to Campaign Builder for new campaign
  const handleCreateNew = () => {
    // Clear any stored campaign to load
    sessionStorage.removeItem('campaign_to_load');
    window.location.href = '/test-execution/build-campaign';
  };

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box display="flex" alignItems="center" gap={1}>
          <Typography variant="h4" component="h1">
            Campaign
          </Typography>
          <IconButton
            size="small"
            onClick={() => setShowHidden((current) => !current)}
            color={showHidden ? 'primary' : 'default'}
          >
            {showHidden ? <VisibilityIcon /> : <VisibilityOffIcon />}
          </IconButton>
        </Box>
        <Button variant="contained" startIcon={<AddIcon />} onClick={handleCreateNew}>
          Create Campaign
        </Button>
      </Box>

      {/* Reuse CampaignSelector component - same as dialog */}
      <Paper sx={{ p: 2, flex: 1, display: 'flex', flexDirection: 'column' }}>
        <CampaignSelector
          ref={selectorRef}
          onLoad={handleLoad}
          onDelete={handleDelete}
          selectedCampaignId={null}
          showHidden={showHidden}
        />
      </Paper>

      {/* Confirmation Dialog */}
      <ConfirmDialog
        open={dialogState.open}
        title={dialogState.title}
        message={dialogState.message}
        confirmText={dialogState.confirmText}
        cancelText={dialogState.cancelText}
        confirmColor={dialogState.confirmColor}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </Box>
  );
};

export default CampaignEditor;
