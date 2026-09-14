import React, { useState, useEffect } from 'react';
import { 
  DialogTitle, 
  DialogContent, 
  DialogActions, 
  TextField, 
  Button, 
  Box,
  Typography,
  Alert,
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
import ErrorIcon from '@mui/icons-material/Error';
import CloseIcon from '@mui/icons-material/Close';
import { buildServerUrl } from '../../../utils/buildUrlUtils';
import { api } from '../../../utils/apiClient';
import { getErrorMessage } from '../../../utils/testcase/testCaseHelpers';
import { TestCaseSelector } from '../TestCaseSelector';
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

interface TestCaseBuilderDialogsProps {
  // Save Dialog
  saveDialogOpen: boolean;
  setSaveDialogOpen: (open: boolean) => void;
  testcaseName: string;
  setTestcaseName: (name: string) => void;
  testcaseDescription: string;
  setTestcaseDescription: (desc: string) => void;
  testcaseEnvironment: string;
  setTestcaseEnvironment: (env: string) => void;
  currentTestcaseId: string | null;
  currentVersion?: number | null;
  handleSave: () => Promise<{ success: boolean; error?: string }> | void;
  // NEW: Folder and Tags
  testcaseFolder?: string;
  setTestcaseFolder?: (folder: string) => void;
  testcaseTags?: string[];
  setTestcaseTags?: (tags: string[]) => void;
  
  // Load Dialog
  loadDialogOpen: boolean;
  setLoadDialogOpen: (open: boolean) => void;
  availableTestcases: any[]; // DEPRECATED: Now loaded in TestCaseSelector, kept for backward compatibility
  handleLoad: (testcaseId: string) => void;
  handleDelete?: (testcaseId: string, testcaseName: string) => Promise<void>;
  testCasesOnly?: boolean; // If true, only show test cases (no scripts)
  // Note: availableTestcases parameter is deprecated but kept for backward compatibility
  
  // Edit Dialog
  editDialogOpen: boolean;
  setEditDialogOpen: (open: boolean) => void;
  editingNode: any;
  editFormData: Record<string, any>;
  setEditFormData: (data: Record<string, any>) => void;
  handleSaveEdit: () => void;
  
  // AI Generate Confirmation Dialog
  aiGenerateConfirmOpen?: boolean;
  setAiGenerateConfirmOpen?: (open: boolean) => void;
  handleConfirmAIGenerate?: () => void;
}

export const TestCaseBuilderDialogs: React.FC<TestCaseBuilderDialogsProps> = ({
  saveDialogOpen,
  setSaveDialogOpen,
  testcaseName,
  setTestcaseName,
  testcaseDescription,
  setTestcaseDescription,
  testcaseEnvironment,
  setTestcaseEnvironment,
  currentTestcaseId,
  currentVersion,
  handleSave,
  loadDialogOpen,
  setLoadDialogOpen,
  handleLoad,
  handleDelete,
  testCasesOnly = true, // Default to true for TestCaseBuilder
  editDialogOpen,
  setEditDialogOpen,
  editingNode,
  editFormData,
  setEditFormData,
  handleSaveEdit,
  aiGenerateConfirmOpen,
  setAiGenerateConfirmOpen,
  handleConfirmAIGenerate,
  testcaseFolder = 'Root',
  setTestcaseFolder = () => {},
  testcaseTags = [],
  setTestcaseTags = () => {},
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
      const data = await api.get(buildServerUrl('/server/testcase/folders-tags'));
      if (data.success) {
        setAvailableFolders(data.folders || []);
        setAvailableTags(data.tags || []);
      }
    } catch (error) {
      console.error('Error loading folders and tags:', getErrorMessage(error));
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
      console.error('Error saving test case:', getErrorMessage(error));
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
          {currentTestcaseId ? 'Update Test Case' : 'Save Test Case'}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Chip 
              label={(testcaseEnvironment || 'dev').toUpperCase()} 
              color={getEnvironmentColor(testcaseEnvironment || 'dev')} 
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
            label="Test Case Name"
            fullWidth
            value={testcaseName}
            onChange={(e) => setTestcaseName(e.target.value)}
            sx={{ mb: 2 }}
          />
          <TextField
            margin="dense"
            label="Description"
            fullWidth
            multiline
            rows={3}
            value={testcaseDescription}
            onChange={(e) => setTestcaseDescription(e.target.value)}
            sx={{ mb: 2 }}
          />
          <FormControl fullWidth margin="dense">
            <InputLabel>Environment</InputLabel>
            <Select
              value={testcaseEnvironment}
              label="Environment"
              onChange={(e) => setTestcaseEnvironment(e.target.value)}
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
            value={testcaseFolder}
            onChange={(_, newValue) => {
              setTestcaseFolder(newValue || 'Root');
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
            value={testcaseTags}
            onChange={(_, newValue) => {
              setTestcaseTags(newValue);
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
                helperText="Tags help organize and filter test cases"
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
            disabled={!testcaseName.trim() || saveStatus === 'loading'}
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
                : currentTestcaseId ? 'Update' : 'Save'
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
          Load Test Case
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
          <TestCaseSelector
            onLoad={handleLoad}
            onDelete={handleDelete}
            selectedTestCaseId={currentTestcaseId}
            testCasesOnly={testCasesOnly}
          />
        </DialogContent>
      </StyledDialog>
      
      {/* Edit Node Dialog */}
      <StyledDialog 
        open={editDialogOpen} 
        onClose={() => setEditDialogOpen(false)} 
        maxWidth="sm" 
        fullWidth
      >
        <DialogTitle sx={{ borderBottom: 1, borderColor: 'divider', pb: 2 }}>
          Edit {editingNode?.type || 'Node'}
        </DialogTitle>
        <DialogContent sx={{ pt: 3 }}>
          {editingNode && (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {Object.entries(editFormData).map(([key, value]) => (
                <TextField
                  key={key}
                  label={key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                  value={value || ''}
                  onChange={(e) => setEditFormData({ ...editFormData, [key]: e.target.value })}
                  fullWidth
                  multiline={typeof value === 'string' && value.length > 50}
                  rows={typeof value === 'string' && value.length > 50 ? 3 : 1}
                />
              ))}
            </Box>
          )}
        </DialogContent>
        <DialogActions sx={{ borderTop: 1, borderColor: 'divider', pt: 2, pb: 2, px: 3 }}>
          <Button onClick={() => setEditDialogOpen(false)} variant="outlined">
            Cancel
          </Button>
          <Button onClick={handleSaveEdit} variant="contained">
            Save
          </Button>
        </DialogActions>
      </StyledDialog>
      
      {/* AI Generate Confirmation Dialog */}
      {aiGenerateConfirmOpen !== undefined && setAiGenerateConfirmOpen && handleConfirmAIGenerate && (
        <StyledDialog 
          open={aiGenerateConfirmOpen} 
          onClose={() => setAiGenerateConfirmOpen(false)}
          maxWidth="sm"
          fullWidth
          sx={{
            '& .MuiDialog-paper': {
              borderColor: 'warning.main',
            }
          }}
        >
          <DialogTitle sx={{ borderBottom: 1, borderColor: 'divider', pb: 2 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <ErrorIcon color="warning" />
              Unsaved Changes
            </Box>
          </DialogTitle>
          <DialogContent sx={{ pt: 3 }}>
            <Alert severity="warning" sx={{ mb: 2 }}>
              <Typography variant="body2">
                You have an existing test case with unsaved changes. 
                Generating a new AI test case will <strong>replace</strong> the current graph.
              </Typography>
            </Alert>
            <Typography variant="body2" color="text.secondary">
              <strong>Options:</strong>
            </Typography>
            <Box component="ul" sx={{ mt: 1, ml: 2 }}>
              <Typography component="li" variant="body2" color="text.secondary">
                <strong>Cancel</strong> - Save your current work first
              </Typography>
              <Typography component="li" variant="body2" color="text.secondary">
                <strong>Continue</strong> - Replace current graph (changes will be lost)
              </Typography>
            </Box>
          </DialogContent>
          <DialogActions sx={{ borderTop: 1, borderColor: 'divider', pt: 2, pb: 2, px: 3 }}>
            <Button 
              onClick={() => setAiGenerateConfirmOpen(false)} 
              variant="outlined"
            >
              Cancel
            </Button>
            <Button 
              onClick={handleConfirmAIGenerate} 
              variant="contained" 
              color="warning"
            >
              Continue & Replace
            </Button>
          </DialogActions>
        </StyledDialog>
      )}
    </>
  );
};

