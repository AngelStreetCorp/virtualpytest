import React, { useState, useEffect } from 'react';
import {
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Button,
  Box,
  Typography,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Chip,
  Autocomplete,
  CircularProgress,
  IconButton
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CloseIcon from '@mui/icons-material/Close';
import { buildServerUrl } from '../../../utils/buildUrlUtils';
import { CampaignSelector } from '../CampaignSelector';
import { StyledDialog } from '../../common/StyledDialog';

interface Folder {
  folder_id: number;
  name: string;
}

interface Tag {
  tag_id: number;
  name: string;
  color: string;
}

interface CampaignBuilderDialogsProps {
  // Save Dialog
  saveDialogOpen: boolean;
  setSaveDialogOpen: (open: boolean) => void;
  campaignName: string;
  setCampaignName: (name: string) => void;
  campaignDescription: string;
  setCampaignDescription: (desc: string) => void;
  campaignEnvironment: string;
  setCampaignEnvironment: (env: string) => void;
  currentCampaignId: string | null;
  currentVersion?: number | null;
  handleSave: () => void;
  // NEW: Folder and Tags
  campaignFolder?: string;
  setCampaignFolder?: (folder: string) => void;
  campaignTags?: string[];
  setCampaignTags?: (tags: string[]) => void;

  // Load Dialog
  loadDialogOpen: boolean;
  setLoadDialogOpen: (open: boolean) => void;
  availableCampaigns: any[]; // DEPRECATED: Now loaded in CampaignSelector, kept for backward compatibility
  handleLoad: (campaignId: string) => void;
  handleDelete?: (campaignId: string, campaignName: string) => Promise<void>;
  // Note: availableCampaigns parameter is deprecated but kept for backward compatibility
}

export const CampaignBuilderDialogs: React.FC<CampaignBuilderDialogsProps> = ({
  saveDialogOpen,
  setSaveDialogOpen,
  campaignName,
  setCampaignName,
  campaignDescription,
  setCampaignDescription,
  campaignEnvironment,
  setCampaignEnvironment,
  currentCampaignId,
  currentVersion,
  handleSave,
  loadDialogOpen,
  setLoadDialogOpen,
  handleLoad,
  handleDelete,
  campaignFolder = 'Root',
  setCampaignFolder = () => {},
  campaignTags = [],
  setCampaignTags = () => {},
}) => {
  // State for folders and tags
  const [availableFolders, setAvailableFolders] = useState<Folder[]>([]);
  const [availableTags, setAvailableTags] = useState<Tag[]>([]);
  const [loadingFoldersTags, setLoadingFoldersTags] = useState(false);

  // State for save button animation
  const [saveStatus, setSaveStatus] = useState<'idle' | 'loading' | 'success'>('idle');

  // Reset save status when dialog closes
  useEffect(() => {
    if (!saveDialogOpen) {
      setSaveStatus('idle');
    }
  }, [saveDialogOpen]);

  // Auto-close dialog 3 seconds after success
  useEffect(() => {
    if (saveStatus === 'success') {
      const timer = setTimeout(() => {
        setSaveDialogOpen(false);
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [saveStatus, setSaveDialogOpen]);

  // Load folders and tags when save dialog opens
  useEffect(() => {
    if (saveDialogOpen && !loadingFoldersTags && availableFolders.length === 0) {
      loadFoldersAndTags();
    }
  }, [saveDialogOpen]);

  const loadFoldersAndTags = async () => {
    setLoadingFoldersTags(true);
    try {
      // Note: buildServerUrl automatically adds team_id parameter
      const response = await fetch(buildServerUrl('/server/campaign/folders-tags'));
      const data = await response.json();

      if (data.success) {
        setAvailableFolders(data.folders || []);
        setAvailableTags(data.tags || []);
      }
    } catch (error) {
      console.error('Error loading folders and tags:', error);
    } finally {
      setLoadingFoldersTags(false);
    }
  };

  // Wrapper for handleSave with loading and success states
  const handleSaveWithAnimation = async () => {
    setSaveStatus('loading');
    try {
      await handleSave();
      setSaveStatus('success');
    } catch (error) {
      console.error('Error saving campaign:', error);
      setSaveStatus('idle');
    }
  };

  // Get environment color for chips
  const getEnvironmentColor = (env: string) => {
    switch (env) {
      case 'prod': return 'error';
      case 'test': return 'warning';
      case 'dev': return 'success';
      default: return 'default';
    }
  };

  return (
    <>
      {/* Save Dialog */}
      <StyledDialog
        open={saveDialogOpen}
        onClose={() => setSaveDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle sx={{
          borderBottom: 1,
          borderColor: 'divider',
          pb: 2,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          {currentCampaignId ? 'Update Campaign' : 'Save Campaign'}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Chip
              label={(campaignEnvironment || 'dev').toUpperCase()}
              color={getEnvironmentColor(campaignEnvironment || 'dev')}
              size="small"
              sx={{ fontWeight: 'bold' }}
            />
            <Chip
              label={`Version ${currentVersion || 1}`}
              color="primary"
              size="small"
              variant="outlined"
              sx={{ fontWeight: 'bold' }}
            />
          </Box>
        </DialogTitle>
        <DialogContent sx={{ pt: 3 }}>
          <TextField
            autoFocus
            margin="dense"
            label="Campaign Name"
            fullWidth
            value={campaignName}
            onChange={(e) => setCampaignName(e.target.value)}
            sx={{ mb: 2 }}
          />
          <TextField
            margin="dense"
            label="Description"
            fullWidth
            multiline
            rows={3}
            value={campaignDescription}
            onChange={(e) => setCampaignDescription(e.target.value)}
            sx={{ mb: 2 }}
          />
          <FormControl fullWidth margin="dense">
            <InputLabel>Environment</InputLabel>
            <Select
              value={campaignEnvironment}
              label="Environment"
              onChange={(e) => setCampaignEnvironment(e.target.value)}
            >
              <MenuItem value="dev">
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Chip label="DEV" color="success" size="small" />
                  <Typography variant="body2">Development (default)</Typography>
                </Box>
              </MenuItem>
              <MenuItem value="test">
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Chip label="TEST" color="warning" size="small" />
                  <Typography variant="body2">Testing</Typography>
                </Box>
              </MenuItem>
              <MenuItem value="prod">
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Chip label="PROD" color="error" size="small" />
                  <Typography variant="body2">Production</Typography>
                </Box>
              </MenuItem>
            </Select>
          </FormControl>

          {/* Folder Selector - Autocomplete (select or type new) */}
          <Autocomplete
            freeSolo
            value={campaignFolder}
            onChange={(_, newValue) => {
              setCampaignFolder(newValue || 'Root');
            }}
            options={availableFolders.map(f => f.name)}
            renderInput={(params) => (
              <TextField
                {...params}
                label="Folder"
                margin="dense"
                helperText="Select existing or type new folder name"
              />
            )}
            sx={{ mt: 1 }}
          />

          {/* Tag Selector - Multi-Autocomplete (select or type new) */}
          <Autocomplete
            multiple
            freeSolo
            value={campaignTags}
            onChange={(_, newValue) => {
              setCampaignTags(newValue);
            }}
            options={availableTags.map(t => t.name)}
            renderTags={(value, getTagProps) =>
              value.map((option, index) => {
                // Find tag color if exists, or use default for new tags
                const existingTag = availableTags.find(t => t.name === option);
                const color = existingTag?.color || '#9e9e9e';

                return (
                  <Chip
                    label={option}
                    {...getTagProps({ index })}
                    sx={{
                      backgroundColor: color,
                      color: 'white',
                      '& .MuiChip-deleteIcon': {
                        color: 'rgba(255, 255, 255, 0.7)',
                        '&:hover': {
                          color: 'white'
                        }
                      }
                    }}
                  />
                );
              })
            }
            renderInput={(params) => (
              <TextField
                {...params}
                label="Tags"
                margin="dense"
                placeholder="Select or type new tags..."
                helperText="Tags help organize and filter campaigns"
              />
            )}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions sx={{ borderTop: 1, borderColor: 'divider', pt: 2, pb: 2, px: 3 }}>
          <Button
            onClick={() => setSaveDialogOpen(false)}
            variant="outlined"
            disabled={saveStatus === 'loading'}
          >
            Cancel
          </Button>
          <Button
            onClick={handleSaveWithAnimation}
            variant="contained"
            disabled={!campaignName.trim() || saveStatus === 'loading'}
            sx={{
              minWidth: 120,
              bgcolor: saveStatus === 'success' ? 'success.main' : undefined,
              '&:hover': {
                bgcolor: saveStatus === 'success' ? 'success.dark' : undefined,
              },
              transition: 'all 0.3s ease-in-out'
            }}
            startIcon={
              saveStatus === 'loading' ? (
                <CircularProgress size={20} color="inherit" />
              ) : saveStatus === 'success' ? (
                <CheckCircleIcon />
              ) : undefined
            }
          >
            {saveStatus === 'loading'
              ? 'Saving...'
              : saveStatus === 'success'
                ? 'Saved!'
                : currentCampaignId ? 'Update' : 'Save'
            }
          </Button>
        </DialogActions>
      </StyledDialog>

      {/* Load Dialog - Compact with Filters */}
      <StyledDialog
        open={loadDialogOpen}
        onClose={() => setLoadDialogOpen(false)}
        maxWidth="md"  // Wider dialog for single-line layout
        fullWidth
      >
        <DialogTitle sx={{
          borderBottom: 1,
          borderColor: 'divider',
          py: 0.2,  // Compact vertical padding
          px: 2,  // Horizontal padding
          pr: 5,  // Extra right padding for close button
          mb: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}>
          Load Campaign
          <IconButton
            size="small"
            onClick={() => setLoadDialogOpen(false)}
            sx={{
              position: 'absolute',
              right: 6,
              top: 6,
              color: 'text.secondary',
            }}
          >
            <CloseIcon fontSize="small" />
          </IconButton>
        </DialogTitle>
        <DialogContent sx={{ pt: 3, pb: 1 }}>
          <CampaignSelector
            onLoad={handleLoad}
            onDelete={handleDelete}
            selectedCampaignId={currentCampaignId}
          />
        </DialogContent>
      </StyledDialog>
    </>
  );
};
