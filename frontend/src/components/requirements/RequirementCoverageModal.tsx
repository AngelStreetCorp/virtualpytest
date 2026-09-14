/**
 * Requirement Coverage Modal
 * 
 * Shows detailed coverage information for a requirement including:
 * - Linked testcases grouped by userinterface
 * - Execution stats and pass rates
 * - Quick access to testcases
 */

import React, { useState, useEffect } from 'react';
import {
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
  Chip,
  IconButton,
  CircularProgress,
  Alert,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Divider,
  Tooltip,
} from '@mui/material';
import {
  Close as CloseIcon,
  ExpandMore as ExpandMoreIcon,
  OpenInNew as OpenInNewIcon,
  LinkOff as UnlinkIcon,
  Add as AddIcon,
  CheckCircle as CheckIcon,
  Error as ErrorIcon,
  Warning as WarningIcon,
  Code as ScriptIcon,
} from '@mui/icons-material';
import { RequirementCoverage } from '../../hooks/pages/useRequirements';
import { useConfirmDialog } from '../../hooks/useConfirmDialog';
import { StyledDialog } from '../common/StyledDialog';
import { ConfirmDialog } from '../common/ConfirmDialog';

interface RequirementCoverageModalProps {
  open: boolean;
  onClose: () => void;
  requirementId: string;
  requirementCode: string;
  requirementName: string;
  getCoverage: (requirementId: string) => Promise<RequirementCoverage | null>;
  onUnlinkTestcase: (testcaseId: string, requirementId: string) => Promise<{ success: boolean; error?: string }>;
  onOpenLinkDialog: () => void;
  onNavigateToTestcase?: (testcaseId: string) => void;
}

export const RequirementCoverageModal: React.FC<RequirementCoverageModalProps> = ({
  open,
  onClose,
  requirementId,
  requirementCode,
  requirementName,
  getCoverage,
  onUnlinkTestcase,
  onOpenLinkDialog,
  onNavigateToTestcase,
}) => {
  const [coverage, setCoverage] = useState<RequirementCoverage | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedUIs, setExpandedUIs] = useState<Set<string>>(new Set());

  // Confirmation dialog
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  // Load coverage data when modal opens
  useEffect(() => {
    if (open && requirementId) {
      loadCoverage();
    }
  }, [open, requirementId]);

  const loadCoverage = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getCoverage(requirementId);
      if (data) {
        setCoverage(data);
        // Expand all UIs by default
        const uiNames = Object.keys(data.testcases_by_ui);
        setExpandedUIs(new Set(uiNames));
      } else {
        setError('Failed to load coverage data');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setIsLoading(false);
    }
  };

  const handleUnlink = async (testcaseId: string) => {
    confirm({
      title: 'Unlink Testcase',
      message: 'Are you sure you want to unlink this testcase?',
      confirmColor: 'error',
      confirmText: 'Unlink',
      cancelText: 'Cancel',
      onConfirm: async () => {
        const result = await onUnlinkTestcase(testcaseId, requirementId);
        if (result.success) {
          // Reload coverage
          loadCoverage();
        } else {
          alert(`Failed to unlink: ${result.error}`);
        }
      },
    });
  };

  const handleOpenTestcase = (testcaseId: string) => {
    if (onNavigateToTestcase) {
      onNavigateToTestcase(testcaseId);
    } else {
      // Open in new tab (fallback)
      window.open(`/testcases/${testcaseId}`, '_blank');
    }
  };

  const toggleUIExpansion = (uiName: string) => {
    setExpandedUIs(prev => {
      const newSet = new Set(prev);
      if (newSet.has(uiName)) {
        newSet.delete(uiName);
      } else {
        newSet.add(uiName);
      }
      return newSet;
    });
  };

  const getStatusIcon = (passRate: number, executionCount: number) => {
    if (executionCount === 0) {
      return <WarningIcon color="warning" fontSize="small" />;
    }
    if (passRate >= 0.8) {
      return <CheckIcon color="success" fontSize="small" />;
    }
    return <ErrorIcon color="error" fontSize="small" />;
  };

  const formatPassRate = (passRate: number) => {
    return `${Math.round(passRate * 100)}%`;
  };

  const formatTimeAgo = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
  };

  return (
    <StyledDialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" justifyContent="space-between">
          <Box>
            <Typography variant="h6">Coverage: {requirementCode}</Typography>
            <Typography variant="body2" color="textSecondary">{requirementName}</Typography>
          </Box>
          <IconButton onClick={onClose} size="small">
            <CloseIcon />
          </IconButton>
        </Box>
      </DialogTitle>

      <DialogContent dividers>
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

        {coverage && !isLoading && (
          <Box>
            {/* Summary */}
            <Box sx={{ mb: 3, p: 2, bgcolor: 'background.default', borderRadius: 1 }}>
              <Typography variant="subtitle2" gutterBottom>Summary</Typography>
              <Box display="flex" gap={3} flexWrap="wrap">
                <Box>
                  <Typography variant="caption" color="textSecondary">Test Cases</Typography>
                  <Typography variant="h6">{coverage.coverage_summary.total_testcases}</Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="textSecondary">Scripts</Typography>
                  <Typography variant="h6">{coverage.coverage_summary.total_scripts}</Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="textSecondary">Pass Rate</Typography>
                  <Typography variant="h6" color={coverage.coverage_summary.pass_rate >= 0.8 ? 'success.main' : 'error.main'}>
                    {formatPassRate(coverage.coverage_summary.pass_rate)}
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="textSecondary">Total Executions</Typography>
                  <Typography variant="h6">{coverage.coverage_summary.execution_count}</Typography>
                </Box>
              </Box>
            </Box>

            {/* Scripts section */}
            {coverage.scripts.length > 0 && (
              <Box mb={3}>
                <Typography variant="subtitle2" mb={1}>
                  Linked Scripts
                </Typography>
                <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1, overflow: 'hidden' }}>
                  {coverage.scripts.map((script, index) => (
                    <Box key={script.script_name}>
                      {index > 0 && <Divider />}
                      <Box display="flex" alignItems="center" gap={2} px={2} py={1}>
                        <ScriptIcon fontSize="small" color="primary" />
                        <Box flex={1}>
                          <Typography variant="body2" fontWeight="medium" sx={{ fontFamily: 'monospace' }}>
                            {script.script_name}
                          </Typography>
                          <Box display="flex" gap={2} mt={0.25}>
                            <Chip label={script.coverage_type} size="small" variant="outlined" sx={{ height: 16, fontSize: '0.6rem' }} />
                            {script.execution_count > 0 ? (
                              <Typography variant="caption" color="textSecondary">
                                {script.pass_count}/{script.execution_count} runs passed
                                {script.last_execution && ` · last ${formatTimeAgo(script.last_execution.started_at)}`}
                              </Typography>
                            ) : (
                              <Typography variant="caption" color="text.disabled">not yet executed</Typography>
                            )}
                          </Box>
                        </Box>
                        {getStatusIcon(script.pass_rate, script.execution_count)}
                      </Box>
                    </Box>
                  ))}
                </Box>
              </Box>
            )}

            {/* Test Cases section */}
            <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
              <Typography variant="subtitle2">Linked Test Cases by User Interface</Typography>
              <Button variant="contained" size="small" startIcon={<AddIcon />} onClick={onOpenLinkDialog}>
                Link Test Case
              </Button>
            </Box>

            {Object.keys(coverage.testcases_by_ui).length === 0 ? (
              <Alert severity="info">
                No test cases linked yet. Click "Link Test Case" to add coverage.
              </Alert>
            ) : (
              Object.entries(coverage.testcases_by_ui).map(([uiName, testcases]) => (
                <Accordion
                  key={uiName}
                  expanded={expandedUIs.has(uiName)}
                  onChange={() => toggleUIExpansion(uiName)}
                  sx={{ mb: 1 }}
                >
                  <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Box display="flex" alignItems="center" gap={2} width="100%">
                      <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
                        {uiName}
                      </Typography>
                      <Chip label={`${testcases.length} TC`} size="small" />
                      {testcases.length > 0 && (
                        <Typography variant="caption" color="textSecondary">
                          {formatPassRate(
                            testcases.reduce((sum, tc) => sum + tc.pass_rate, 0) / testcases.length
                          )} avg pass rate
                        </Typography>
                      )}
                    </Box>
                  </AccordionSummary>
                  <AccordionDetails>
                    <Box>
                      {testcases.map((tc, index) => (
                        <Box key={tc.testcase_id}>
                          {index > 0 && <Divider sx={{ my: 1 }} />}
                          <Box display="flex" alignItems="flex-start" gap={2}>
                            <Box sx={{ pt: 0.5 }}>
                              {getStatusIcon(tc.pass_rate, tc.execution_count)}
                            </Box>
                            <Box flex={1}>
                              <Typography variant="body2" fontWeight="medium">
                                {tc.testcase_name}
                              </Typography>
                              {tc.description && (
                                <Typography variant="caption" color="textSecondary" display="block">
                                  {tc.description}
                                </Typography>
                              )}
                              <Box display="flex" gap={2} mt={0.5}>
                                <Typography variant="caption" color="textSecondary">
                                  Pass: {tc.pass_count}/{tc.execution_count} runs
                                </Typography>
                                {tc.last_execution && (
                                  <Typography variant="caption" color="textSecondary">
                                    Last: {tc.last_execution.success ? '✅' : '❌'} {formatTimeAgo(tc.last_execution.started_at)}
                                  </Typography>
                                )}
                              </Box>
                            </Box>
                            <Box display="flex" gap={0.5}>
                              <Tooltip title="Open test case">
                                <IconButton size="small" onClick={() => handleOpenTestcase(tc.testcase_id)}>
                                  <OpenInNewIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                              <Tooltip title="Unlink">
                                <IconButton size="small" onClick={() => handleUnlink(tc.testcase_id)} color="error">
                                  <UnlinkIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            </Box>
                          </Box>
                        </Box>
                      ))}
                    </Box>
                  </AccordionDetails>
                </Accordion>
              ))
            )}
          </Box>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>Close</Button>
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


