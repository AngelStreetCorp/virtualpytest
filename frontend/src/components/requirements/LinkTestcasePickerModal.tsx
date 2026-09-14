/**
 * Link Testcase Picker Modal
 * 
 * Allows user to select which testcases to link to a requirement.
 * Features:
 * - Filter by userinterface
 * - Search by name/description
 * - Checkbox selection
 * - Shows which testcases are already linked
 */

import React, { useState, useEffect } from 'react';
import {
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
  TextField,
  InputAdornment,
  Checkbox,
  CircularProgress,
  Alert,
  Chip,
  IconButton,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material';
import {
  Close as CloseIcon,
  Search as SearchIcon,
  Clear as ClearIcon,
} from '@mui/icons-material';
import { TestcaseWithLink } from '../../hooks/pages/useRequirements';
import { useConfirmDialog } from '../../hooks/useConfirmDialog';
import { ConfirmDialog } from '../common/ConfirmDialog';
import { StyledDialog } from '../common/StyledDialog';

interface LinkTestcasePickerModalProps {
  open: boolean;
  onClose: () => void;
  requirementId: string;
  requirementCode: string;
  requirementName: string;
  getAvailableTestcases: (requirementId: string, userinterfaceName?: string) => Promise<TestcaseWithLink[]>;
  onLinkTestcases: (requirementId: string, testcaseIds: string[], coverageType: string) => Promise<{ success: boolean; error?: string }>;
  onSuccess?: () => void;
}

export const LinkTestcasePickerModal: React.FC<LinkTestcasePickerModalProps> = ({
  open,
  onClose,
  requirementId,
  requirementCode,
  requirementName,
  getAvailableTestcases,
  onLinkTestcases,
  onSuccess,
}) => {
  const [testcases, setTestcases] = useState<TestcaseWithLink[]>([]);
  const [filteredTestcases, setFilteredTestcases] = useState<TestcaseWithLink[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedUI, setSelectedUI] = useState<string>('');
  const [selectedTestcaseIds, setSelectedTestcaseIds] = useState<Set<string>>(new Set());
  const [isSaving, setIsSaving] = useState(false);

  // Confirmation dialog
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  // Get unique UI names from testcases
  const uniqueUIs = Array.from(new Set(testcases.map(tc => tc.userinterface_name).filter(Boolean))).sort();

  // Load testcases when modal opens
  useEffect(() => {
    if (open && requirementId) {
      loadTestcases();
    }
  }, [open, requirementId, selectedUI]);

  // Filter testcases by search query
  useEffect(() => {
    let filtered = testcases;

    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(tc =>
        tc.testcase_name.toLowerCase().includes(query) ||
        (tc.description && tc.description.toLowerCase().includes(query))
      );
    }

    setFilteredTestcases(filtered);
  }, [testcases, searchQuery]);

  const loadTestcases = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getAvailableTestcases(requirementId, selectedUI || undefined);
      setTestcases(data);
      
      // Pre-select already linked testcases
      const linkedIds = new Set(data.filter(tc => tc.is_linked).map(tc => tc.testcase_id));
      setSelectedTestcaseIds(linkedIds);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setIsLoading(false);
    }
  };

  const handleToggleTestcase = (testcaseId: string, currentlyLinked: boolean) => {
    setSelectedTestcaseIds(prev => {
      const newSet = new Set(prev);
      if (newSet.has(testcaseId)) {
        // Only allow unlinking if it was already linked (don't uncheck new selections accidentally)
        if (!currentlyLinked) {
          // Not currently linked, so just uncheck
          newSet.delete(testcaseId);
        } else {
          // Currently linked, so confirm before unlinking
          confirm({
            title: 'Unlink Testcase',
            message: 'Unlink this testcase?',
            confirmColor: 'warning',
            confirmText: 'Unlink',
            cancelText: 'Cancel',
            onConfirm: () => {
              const updatedSet = new Set(prev);
              updatedSet.delete(testcaseId);
              setSelectedTestcaseIds(updatedSet);
            },
          });
        }
      } else {
        newSet.add(testcaseId);
      }
      return newSet;
    });
  };

  const handleSave = async () => {
    // Find which testcases need to be linked (selected but not currently linked)
    const testcasesToLink = filteredTestcases.filter(
      tc => selectedTestcaseIds.has(tc.testcase_id) && !tc.is_linked
    ).map(tc => tc.testcase_id);

    if (testcasesToLink.length === 0) {
      alert('No new testcases to link');
      return;
    }

    setIsSaving(true);
    try {
      const result = await onLinkTestcases(requirementId, testcasesToLink, 'full');
      if (result.success) {
        if (onSuccess) onSuccess();
        onClose();
      } else {
        alert(`Failed to link testcases: ${result.error}`);
      }
    } catch (err) {
      alert(`Error: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setIsSaving(false);
    }
  };

  const selectedCount = selectedTestcaseIds.size;
  const linkedCount = testcases.filter(tc => tc.is_linked).length;
  const newLinksCount = Array.from(selectedTestcaseIds).filter(
    id => !testcases.find(tc => tc.testcase_id === id)?.is_linked
  ).length;

  return (
    <StyledDialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" justifyContent="space-between">
          <Box>
            <Typography variant="h6">Link Testcases to {requirementCode}</Typography>
            <Typography variant="body2" color="textSecondary">{requirementName}</Typography>
          </Box>
          <IconButton onClick={onClose} size="small">
            <CloseIcon />
          </IconButton>
        </Box>
      </DialogTitle>

      <DialogContent dividers>
        {/* Filters */}
        <Box sx={{ mb: 2, display: 'flex', gap: 2 }}>
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>User Interface</InputLabel>
            <Select
              value={selectedUI}
              onChange={(e) => setSelectedUI(e.target.value)}
              label="User Interface"
            >
              <MenuItem value="">All</MenuItem>
              {uniqueUIs.map(ui => (
                <MenuItem key={ui} value={ui}>{ui}</MenuItem>
              ))}
            </Select>
          </FormControl>

          <TextField
            size="small"
            placeholder="Search testcases..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            sx={{ flex: 1 }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
              endAdornment: searchQuery && (
                <InputAdornment position="end">
                  <IconButton size="small" onClick={() => setSearchQuery('')}>
                    <ClearIcon fontSize="small" />
                  </IconButton>
                </InputAdornment>
              ),
            }}
          />
        </Box>

        {/* Status */}
        <Box sx={{ mb: 2, display: 'flex', gap: 2, alignItems: 'center' }}>
          <Typography variant="body2" color="textSecondary">
            Already Linked: <strong>{linkedCount}</strong>
          </Typography>
          {newLinksCount > 0 && (
            <Chip label={`${newLinksCount} new to link`} size="small" color="primary" />
          )}
        </Box>

        {isLoading && (
          <Box display="flex" justifyContent="center" p={4}>
            <CircularProgress />
          </Box>
        )}

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {!isLoading && (
          <Box>
            {filteredTestcases.length === 0 ? (
              <Alert severity="info">
                {searchQuery
                  ? `No testcases found matching "${searchQuery}"`
                  : 'No testcases available'}
              </Alert>
            ) : (
              <Box sx={{ maxHeight: 400, overflowY: 'auto' }}>
                {filteredTestcases.map((tc) => (
                  <Box
                    key={tc.testcase_id}
                    sx={{
                      p: 1.5,
                      borderBottom: '1px solid',
                      borderColor: 'divider',
                      '&:hover': {
                        bgcolor: 'action.hover',
                      },
                    }}
                  >
                    <Box display="flex" alignItems="flex-start" gap={1}>
                      <Checkbox
                        checked={selectedTestcaseIds.has(tc.testcase_id)}
                        onChange={() => handleToggleTestcase(tc.testcase_id, tc.is_linked)}
                        sx={{ mt: -0.5 }}
                      />
                      <Box flex={1}>
                        <Box display="flex" alignItems="center" gap={1}>
                          <Typography variant="body2" fontWeight="medium">
                            {tc.testcase_name}
                          </Typography>
                          {tc.is_linked && (
                            <Chip label="✅ Linked" size="small" color="success" />
                          )}
                        </Box>
                        {tc.description && (
                          <Typography variant="caption" color="textSecondary" display="block">
                            {tc.description}
                          </Typography>
                        )}
                        {tc.userinterface_name && (
                          <Chip
                            label={tc.userinterface_name}
                            size="small"
                            sx={{ mt: 0.5 }}
                          />
                        )}
                      </Box>
                    </Box>
                  </Box>
                ))}
              </Box>
            )}
          </Box>
        )}

        {/* Summary */}
        {!isLoading && filteredTestcases.length > 0 && (
          <Box sx={{ mt: 2, p: 1, bgcolor: 'background.default', borderRadius: 1 }}>
            <Typography variant="caption" color="textSecondary">
              Selected: {selectedCount} testcase{selectedCount !== 1 ? 's' : ''}
              {newLinksCount > 0 && ` (${newLinksCount} new)`}
            </Typography>
          </Box>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose} disabled={isSaving}>Cancel</Button>
        <Button
          onClick={handleSave}
          variant="contained"
          disabled={isSaving || newLinksCount === 0}
        >
          {isSaving ? <CircularProgress size={20} /> : `Link ${newLinksCount} Testcase${newLinksCount !== 1 ? 's' : ''}`}
        </Button>
      </DialogActions>

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
    </StyledDialog>
  );
};

