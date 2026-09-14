import React, { useState, useEffect, useCallback } from 'react';
import {
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
  LinearProgress,
  Paper,
  CircularProgress,
  Tooltip
} from '@mui/material';
import {
  CheckCircle as CompleteIcon,
  Cancel as CancelIcon,
  Visibility as ReviewIcon
} from '@mui/icons-material';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { NodeVerificationModal } from './NodeVerificationModal';
import { useExplorationValidation, ValidationResult } from '../../hooks/exploration';
import { StyledDialog } from '../common/StyledDialog';

interface ValidationModalProps {
  isOpen: boolean;
  onClose: () => void;
  
  // Exploration details
  explorationId: string;
  explorationHostName: string;
  treeId: string;
  selectedDeviceId: string;
  
  // Callbacks
  onValidationStarted?: () => void;
  onValidationComplete?: () => void;
}

export const ValidationModal: React.FC<ValidationModalProps> = ({
  isOpen,
  onClose,
  explorationId,
  explorationHostName,
  treeId,
  selectedDeviceId,
  onValidationStarted,
  onValidationComplete
}) => {
  // ✅ USE HOOK INSTEAD OF COMPONENT STATE
  const {
    isValidating,
    isComplete,
    progress,
    results: validationResults,
    currentStep,
    error,
    startValidation: hookStartValidation,
    validateNextItem: hookValidateNextItem
  } = useExplorationValidation({
    explorationId,
    explorationHostName,
    treeId,
    selectedDeviceId
  });

  // Node verification state (still component-specific)
  const [showNodeVerificationModal, setShowNodeVerificationModal] = useState(false);
  const [nodeVerificationSuggestions, setNodeVerificationSuggestions] = useState<any[]>([]);
  const [isAnalyzingVerifications, setIsAnalyzingVerifications] = useState(false);
  const [isUpdatingNodes, setIsUpdatingNodes] = useState(false);
  const [nodeVerificationComplete, setNodeVerificationComplete] = useState(false);

  // Start validation when modal opens
  useEffect(() => {
    if (isOpen && explorationId && !isValidating && !isComplete) {
      handleStartValidation();
    }
  }, [isOpen, explorationId]);

  // Wrapper to start validation and begin polling
  const handleStartValidation = useCallback(async () => {
    const result = await hookStartValidation();
    
    if (result.success) {
      onValidationStarted?.();
      // Start validating first item
      pollValidation();
    }
  }, [hookStartValidation, onValidationStarted]);

  // Poll validation progress
  const pollValidation = useCallback(async () => {
    const result = await hookValidateNextItem();
    
    if (result.success && result.has_more_items) {
      // Continue with next item after delay
      setTimeout(() => pollValidation(), 500);
    }
  }, [hookValidateNextItem]);

  // Helper function to truncate long text
  const truncate = (text: string, maxLength: number = 50) => {
    if (!text) return '';
    return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
  };
  
  // Start node verification analysis
  const handleStartNodeVerification = useCallback(async () => {
    try {
      setIsAnalyzingVerifications(true);
      
      console.log('[@ValidationModal] Starting node verification analysis');
      
      const response = await fetch(buildServerUrl('/server/ai-generation/start-node-verification'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_id: selectedDeviceId,
          host_name: explorationHostName
        })
      });
      
      if (!response.ok) {
        throw new Error(`Failed to start node verification: ${response.status}`);
      }
      
      const data = await response.json();
      
      if (data.success) {
        setNodeVerificationSuggestions(data.suggestions || []);
        setShowNodeVerificationModal(true);
        console.log('[@ValidationModal] Got suggestions:', data.suggestions);
      } else {
        throw new Error(data.error || 'Failed to analyze node verifications');
      }
    } catch (err) {
      console.error('[@ValidationModal] Error starting node verification:', err);
    } finally {
      setIsAnalyzingVerifications(false);
    }
  }, [selectedDeviceId, explorationHostName]);
  
  // Approve node verifications
  const handleApproveNodeVerifications = useCallback(async (approvedVerifications: any[]) => {
    try {
      setIsUpdatingNodes(true);
      
      console.log('[@ValidationModal] Approving node verifications:', approvedVerifications);
      
      const response = await fetch(buildServerUrl('/server/ai-generation/approve-node-verifications'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_id: selectedDeviceId,
          host_name: explorationHostName,
          approved_verifications: approvedVerifications
        })
      });
      
      if (!response.ok) {
        throw new Error(`Failed to approve verifications: ${response.status}`);
      }
      
      const data = await response.json();
      
      if (data.success) {
        console.log('[@ValidationModal] Node verifications approved:', data.nodes_updated);
        setShowNodeVerificationModal(false);
        setNodeVerificationComplete(true);
      } else {
        throw new Error(data.error || 'Failed to update nodes');
      }
      
      return data;
    } catch (err) {
      console.error('[@ValidationModal] Error approving verifications:', err);
      return null;
    } finally {
      setIsUpdatingNodes(false);
    }
  }, [selectedDeviceId, explorationHostName]);

  // Cancel exploration
  const handleCancelExploration = useCallback(async () => {
    try {
      console.log('[@ValidationModal] Cancelling exploration...');
      
      // Call backend to clean up
      await fetch(buildServerUrl('/server/ai-generation/cancel-exploration'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_id: selectedDeviceId,
          host_name: explorationHostName,
          exploration_id: explorationId,
          tree_id: treeId
        })
      });
      
      // Close modal
      onClose();
      
    } catch (err) {
      console.error('[@ValidationModal] Error cancelling exploration:', err);
      // Close anyway
      onClose();
    }
  }, [selectedDeviceId, explorationHostName, explorationId, treeId, onClose]);

  return (
    <>
    <StyledDialog
      open={isOpen}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      PaperProps={{
        sx: {
          position: 'fixed',
          top: 20,
          right: 20,
          margin: 0,
          maxWidth: '800px',
          maxHeight: 'calc(100vh - 40px)',
          boxShadow: 3,
          borderColor: isValidating ? 'info.main' : isComplete ? 'success.main' : error ? 'error.main' : 'divider',
          borderRadius: 2,
          overflow: 'hidden'
        }
      }}
    >
      {/* Header */}
      <DialogTitle>
        {isValidating && '🔄 TESTING NAVIGATION'}
        {isComplete && '✅ TESTING COMPLETE'}
        {error && '❌ TEST ERROR'}
      </DialogTitle>

      <DialogContent sx={{ 
        maxHeight: 'calc(100vh - 200px)', 
        overflow: 'auto',
        p: 2,
        '&::-webkit-scrollbar': {
          width: '8px'
        },
        '&::-webkit-scrollbar-track': {
          background: 'transparent'
        },
        '&::-webkit-scrollbar-thumb': {
          background: 'rgba(255,255,255,0.2)',
          borderRadius: '4px'
        }
      }}>
        {error && (
          <Box sx={{ mb: 1, p: 1, bgcolor: 'error.dark', borderRadius: 1 }}>
            <Typography variant="body2" color="error.light">
              {error}
            </Typography>
          </Box>
        )}

        {/* Progress Bar */}
        {progress.total > 0 && (
          <Box sx={{ mb: 0.5, position: 'sticky', top: 0, bgcolor: 'background.paper', zIndex: 1, pb: 1 }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5, pl: 1.5 }}>
              Progress: {progress.current}/{progress.total}
            </Typography>
            <LinearProgress 
              variant="determinate" 
              value={(progress.current / progress.total) * 100}
            />
          </Box>
        )}

        {/* Summary - MOVED UP */}
        {isComplete && validationResults.length > 0 && (
          <Box sx={{ 
            mb: 2,  // Margin bottom instead of top
            p: 1, 
            bgcolor: 'action.selected', 
            borderRadius: 1, 
            border: '1px solid', 
            borderColor: 'divider',
            display: 'flex',
            alignItems: 'center',
            gap: 2
          }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
              📊 Summary:
            </Typography>
            <Typography variant="body2" sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
              <span>✅ {
                // Count successes (forward + backward for vertical only)
                validationResults.reduce((count, r) => {
                  let stepCount = r.forward.result === 'success' ? 1 : 0;
                  // Add backward only for non-horizontal (vertical edges)
                  const isHorizontal = r.forward.action === 'RIGHT' || r.forward.action === 'LEFT' || r.forward.action === 'DOWN';
                  if (!isHorizontal && r.backward.result === 'success') stepCount++;
                  return count + stepCount;
                }, 0)
              } Success</span>
              <span>•</span>
              <span>❌ {
                validationResults.reduce((count, r) => {
                  let stepCount = r.forward.result === 'failure' ? 1 : 0;
                  const isHorizontal = r.forward.action === 'RIGHT' || r.forward.action === 'LEFT' || r.forward.action === 'DOWN';
                  if (!isHorizontal && r.backward.result === 'failure') stepCount++;
                  return count + stepCount;
                }, 0)
              } Failed</span>
              <span>•</span>
              <span>⚠️ {validationResults.filter(r => r.backward.result === 'warning').length} Warnings</span>
            </Typography>
          </Box>
        )}

        {/* Results List - Compact Format - Reverse order (newest first) */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          {/* Current step (in progress) - Show first so user doesn't need to scroll */}
          {(isValidating || validationResults.length === 0) && (
            <Paper sx={{ 
              p: 1.5, 
              bgcolor: 'info.dark', 
              border: '2px solid', 
              borderColor: 'info.main',
              borderRadius: 1
            }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                <CircularProgress size={16} sx={{ color: 'info.light' }} />
                <Typography variant="body2" sx={{ fontWeight: 'bold' }}>
                  Step {Math.max(1, (progress.current || 0) + 1)} - IN PROGRESS
                </Typography>
              </Box>
              <Typography variant="caption" sx={{ fontFamily: 'monospace', display: 'block', color: 'info.light', ml: 3 }}>
                {truncate(currentStep || 'Validating...', 70)}
              </Typography>
            </Paper>
          )}
          
          {/* Completed steps - Reverse chronological order (newest first) */}
          {(() => {
            // Group results by item for TV dual-layer display
            const groupedResults: ValidationResult[][] = [];
            let currentGroup: ValidationResult[] = [];
            
            validationResults.forEach((result, idx) => {
              // Check if this is the start of a new item (horizontal/focus edge)
              const isHorizontalEdge = result.forward.action === 'RIGHT' || result.forward.action === 'LEFT' || result.forward.action === 'DOWN';
              
              if (isHorizontalEdge && currentGroup.length > 0) {
                // Save previous group and start new one
                groupedResults.push(currentGroup);
                currentGroup = [result];
              } else {
                currentGroup.push(result);
              }
              
              // Last result - save group
              if (idx === validationResults.length - 1 && currentGroup.length > 0) {
                groupedResults.push(currentGroup);
              }
            });
            
            return groupedResults.reverse().map((group, groupIndex) => (
            <Paper 
                key={groupedResults.length - 1 - groupIndex}
              sx={{ 
                p: 1.5,
                bgcolor: 'background.default',
                border: '2px solid',
                  borderColor: group.some(r => r.forward.result === 'failure' || r.backward.result === 'failure') ? 'error.main' : 'success.main',
                borderRadius: 1
              }}
            >
                {group.map((result, resultIndex) => {
                  const isHorizontal = result.forward.action === 'RIGHT' || result.forward.action === 'LEFT' || result.forward.action === 'DOWN';
                  const stepOffset = resultIndex === 0 ? 1 : 2; // .1 for first (horizontal), .2/.3 for second (vertical)
                  
                  return (
                    <React.Fragment key={resultIndex}>
                      {/* Forward action */}
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5, overflow: 'hidden' }}>
                <Typography variant="body2" sx={{ fontWeight: 'bold', minWidth: '70px', flexShrink: 0 }}>
                          Step {result.step}.{stepOffset}
                </Typography>
                <Tooltip title={`${result.sourceNode} → ${result.targetNode}`} arrow>
                  <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.85rem', color: 'text.secondary', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexShrink: 1, minWidth: 0 }}>
                    {result.sourceNode} → {result.targetNode}
                  </Typography>
                </Tooltip>
                <Tooltip title={result.forward.action} arrow>
                  <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.8rem', color: 'text.disabled', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexShrink: 1, minWidth: 0 }}>
                    {result.forward.action}
                  </Typography>
                </Tooltip>
                <Typography 
                  variant="body2" 
                  sx={{ 
                    fontWeight: 'bold',
                    ml: 'auto',
                    flexShrink: 0,
                    color: result.forward.result === 'success' ? 'success.main' : 'error.main'
                  }}
                >
                  {result.forward.result === 'success' ? '✅ SUCCESS' : '❌ FAILED'}
                </Typography>
              </Box>
              
                      {/* Backward action - only for vertical (OK/BACK) */}
                      {!isHorizontal && (
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: resultIndex < group.length - 1 ? 0.5 : 0, overflow: 'hidden' }}>
                <Typography variant="body2" sx={{ fontWeight: 'bold', minWidth: '70px', flexShrink: 0 }}>
                            Step {result.step}.{stepOffset + 1}
                </Typography>
                <Tooltip title={`${result.targetNode} → ${result.sourceNode}`} arrow>
                  <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.85rem', color: 'text.secondary', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexShrink: 1, minWidth: 0 }}>
                    {result.targetNode} → {result.sourceNode}
                  </Typography>
                </Tooltip>
                <Tooltip title={result.backward.action} arrow>
                  <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.8rem', color: 'text.disabled', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexShrink: 1, minWidth: 0 }}>
                    {result.backward.action}
                  </Typography>
                </Tooltip>
                <Typography 
                  variant="body2" 
                  sx={{ 
                    fontWeight: 'bold',
                    ml: 'auto',
                    flexShrink: 0,
                    color: result.backward.result === 'success' ? 'success.main' : 
                           result.backward.result === 'warning' ? 'warning.main' :
                           result.backward.result === 'skipped' ? 'text.secondary' : 'error.main'
                  }}
                >
                  {result.backward.result === 'success' ? '✅ SUCCESS' :
                   result.backward.result === 'warning' ? '⚠️ WARNING' :
                   result.backward.result === 'skipped' ? '⏭️ SKIPPED' : '❌ FAILED'}
                </Typography>
              </Box>
                      )}
                    </React.Fragment>
                  );
                })}
            </Paper>
            ));
          })()}
          
          {/* Pending steps */}
          {progress.total > 0 && 
           [...Array(Math.max(0, progress.total - (progress.current || 0) - 1))].map((_, index) => (
            <Paper 
              key={`pending-${index}`}
              sx={{ 
                p: 1, 
                bgcolor: 'action.hover', 
                opacity: 0.4,
                borderRadius: 1,
                border: '1px dashed',
                borderColor: 'divider'
              }}
            >
              <Typography variant="body2" color="text.secondary">
                ⏳ Step {(progress.current || 0) + index + 2} - PENDING
              </Typography>
            </Paper>
          ))}
        </Box>
      </DialogContent>

      {/* Actions */}
      <DialogActions sx={{ p: 2, gap: 1 }}>
        {/* During validation - show enabled cancel */}
        {isValidating && (
          <Button
            onClick={handleCancelExploration}
            variant="outlined"
            color="error"
            startIcon={<CancelIcon />}
          >
            Cancel
          </Button>
        )}
        
        {/* After validation complete - show Review Node Verifications or Confirm & Save */}
        {isComplete && !nodeVerificationComplete && (
          <>
            <Button
              onClick={handleCancelExploration}
              variant="outlined"
              color="error"
              startIcon={<CancelIcon />}
            >
              Cancel & Delete
            </Button>
            <Button
              onClick={handleStartNodeVerification}
              variant="contained"
              color="primary"
              startIcon={<ReviewIcon />}
              disabled={isAnalyzingVerifications}
            >
              {isAnalyzingVerifications ? 'Analyzing...' : 'Review Node Verifications'}
            </Button>
          </>
        )}
        
        {/* After node verification complete - show Confirm & Save */}
        {nodeVerificationComplete && (
          <>
            <Button
              onClick={handleCancelExploration}
              variant="outlined"
              color="error"
              startIcon={<CancelIcon />}
            >
              Cancel & Delete
            </Button>
            <Button
              onClick={() => {
                onValidationComplete?.();
              }}
              variant="contained"
              color="success"
              startIcon={<CompleteIcon />}
            >
              Confirm & Save
            </Button>
          </>
        )}
        
        {/* Error state */}
        {error && !isValidating && (
          <Button
            onClick={onClose}
            variant="contained"
            color="error"
          >
            Close
          </Button>
        )}
      </DialogActions>
    </StyledDialog>
    
    {/* Node Verification Modal */}
    <NodeVerificationModal
      isOpen={showNodeVerificationModal}
      onClose={() => setShowNodeVerificationModal(false)}
      onCancel={() => {
        setShowNodeVerificationModal(false);
        handleCancelExploration();
      }}
      suggestions={nodeVerificationSuggestions}
      onApprove={handleApproveNodeVerifications}
      isUpdating={isUpdatingNodes}
    />
    </>
  );
};

