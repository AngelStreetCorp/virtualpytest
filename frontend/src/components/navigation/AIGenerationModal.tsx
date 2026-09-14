import React, { useEffect } from 'react';
import {
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
  LinearProgress,
  Chip,
  Alert,
  Paper,
  Grid,
  CircularProgress
} from '@mui/material';
import {
  SmartToy as AIIcon,
  Visibility as AnalyzeIcon,
  Navigation as NavigationIcon,
  Error as ErrorIcon,
  Cancel as CancelIcon,
  CheckCircle as ValidateIcon,
  DeleteForever as AbortIcon
} from '@mui/icons-material';
import { useGenerateModel } from '../../hooks/useGenerateModel';
import { useAIGenerationModal } from '../../hooks/navigation/useAIGenerationModal';
import { AIGenerationPhaseIndicator } from './AIGenerationPhaseIndicator';
import { Phase2IncrementalView } from './Phase2IncrementalView';
import { ContextSummary } from './ContextSummary';
import { StyledDialog } from '../common/StyledDialog';
import { useR2Url } from '../../hooks/storage/useR2Url';

interface AIGenerationModalProps {
  isOpen: boolean;
  onClose: () => void;
  treeId: string;
  selectedHost: any;
  selectedDeviceId: string;
  userinterfaceName?: string;
  onStructureCreated: (nodesCount: number, edgesCount: number, explorationId: string, explorationHostName: string) => void; // Notify parent to show ValidationReadyPrompt
  onCleanupTemp?: () => void; // Cleanup _temp nodes from frontend state
  onFinalized?: () => void; // ✅ NEW: Reload tree after finalize
}

export const AIGenerationModal: React.FC<AIGenerationModalProps> = ({
  isOpen,
  onClose,
  treeId,
  selectedHost,
  selectedDeviceId,
  userinterfaceName,
  onStructureCreated,
  onCleanupTemp,
  onFinalized
}) => {
  const {
    explorationId,
    explorationHostName,
    isExploring,
    status,
    currentStep,
    progress,
    currentAnalysis,
    explorationPlan,
    error,
    startExploration,
    continueExploration,
    cancelExploration,
    resetState,
    canStart,
    isAwaitingApproval,
    context,
    currentPhase,
    strategy,
    startNodeLabel,
    selectedNodes,
    selectedEdges,
    toggleNodeSelection,
    toggleEdgeSelection
  } = useGenerateModel({
    treeId,
    selectedHost,
    selectedDeviceId,
    userinterfaceName,
    isControlActive: true,
    onStructureCreated: async (nodesCount, edgesCount) => {
      console.log('[@AIGenerationModal:Phase1] Structure created:', nodesCount, 'nodes,', edgesCount, 'edges');
      
      // Notify parent to show ValidationReadyPrompt with exploration details
      if (explorationId && explorationHostName) {
        onStructureCreated(nodesCount, edgesCount, explorationId, explorationHostName);
      } else {
        console.error('[@AIGenerationModal:Phase1] Missing exploration details!');
      }
      
      // Close this modal - ValidationReadyPrompt will take over (user stays in current tree context)
      onClose();
    },
    onClose: () => {
      // Close modal after structure creation
      onClose();
    }
  });

  // ✅ TV DUAL-LAYER: Independent focus/screen selection
  const [selectedScreenNodes, setSelectedScreenNodes] = React.useState<Set<string>>(
    () => new Set()
  );
  
  // ✅ EDITABLE PLAN: Allow user to delete AI mistakes
  const [editedPlan, setEditedPlan] = React.useState<typeof explorationPlan | null>(null);
  
  // Use edited plan if available, otherwise use original
  const activePlan = editedPlan || explorationPlan;
  
  // R2 URL for screenshot (handles public/private mode automatically)
  const { url: screenshotR2Url } = useR2Url(currentAnalysis?.screenshot || null);
  
  // Delete item from exploration plan (corrects AI mistakes)
  const deleteItem = (rowIdx: number, itemIdx: number) => {
    if (!explorationPlan) return;
    
    const plan = editedPlan || explorationPlan;
    const newLines = plan.lines?.map((line, rIdx) => 
      rIdx === rowIdx ? line.filter((_, iIdx) => iIdx !== itemIdx) : [...line]
    ) || [];
    
    const newItems = newLines.flat();
    
    // Recalculate duplicates with new indices
    const seen = new Set<string>();
    const newDuplicatePositions: string[] = [];
    newLines.forEach((line, rIdx) => {
      line.forEach((lineItem, iIdx) => {
        const clean = lineItem.toLowerCase().replace(/[^a-z0-9]+/g, '_');
        if (seen.has(clean)) {
          newDuplicatePositions.push(`${rIdx}_${iIdx}`);
        } else {
          seen.add(clean);
        }
      });
    });
    
    setEditedPlan({...plan, items: newItems, lines: newLines, duplicate_positions: newDuplicatePositions});
  };

  // ✅ Initialize screen selection when exploration plan loads (default: all selected, excluding duplicates)
  useEffect(() => {
    if (activePlan && activePlan.items && activePlan.items.length > 0) {
      // Calculate which indices in flat items array are duplicates
      const duplicateIndices = new Set<number>();
      
      if (activePlan.duplicate_positions && activePlan.lines) {
        activePlan.duplicate_positions.forEach((posKey: string) => {
          const [rowIdx, itemIdx] = posKey.split('_').map(Number);
          
          // Convert row/item position to flat array index
          let flatIndex = 0;
          for (let r = 0; r < rowIdx; r++) {
            flatIndex += activePlan.lines![r].length;
          }
          flatIndex += itemIdx;
          
          duplicateIndices.add(flatIndex);
        });
      }
      
      // Filter out 'home' and duplicates BY INDEX (not by name!)
      const selectedItems = activePlan.items.filter((item: string, idx: number) => {
        const isHome = item.toLowerCase() === 'home' || item.toLowerCase() === 'accueil';
        const isDuplicate = duplicateIndices.has(idx);
        return !isHome && !isDuplicate;
      });
      
      setSelectedScreenNodes(new Set(selectedItems));
    }
  }, [activePlan]);

  const toggleFocusNode = (item: string) => {
    toggleNodeSelection(item);  // Toggle focus
    
    // If deselecting focus, also deselect screen (can't reach screen without focus)
    if (selectedNodes.has(item)) {
      setSelectedScreenNodes(prev => {
        const newSet = new Set(prev);
        newSet.delete(item);
        return newSet;
      });
    }
  };

  const toggleScreenNode = (item: string) => {
    setSelectedScreenNodes(prev => {
      const newSet = new Set(prev);
      const isCurrentlySelected = newSet.has(item);
      
      if (isCurrentlySelected) {
        // ✅ Always allow deselection
        newSet.delete(item);
      } else {
        // ❌ Only allow selection if focus is selected
        if (selectedNodes.has(item)) {
        newSet.add(item);
        }
        // If focus not selected, do nothing (can't select screen without focus)
      }
      return newSet;
    });
  };

  // Use custom hook for modal logic
  const {
    hasTempNodes,
    isValidating,
    isAborting,
    showCleanConfirm,
    existingNodesCount,
    existingEdgesCount,
    isCheckingTree,
    handleValidatePrevious,
    handleAbortPrevious,
    handleStart,
    handleConfirmClean,
    handleCancelClean
  } = useAIGenerationModal({
    isOpen,
    treeId,
    selectedHost,
    selectedDeviceId,
    onClose,
    onCleanupTemp,
    onFinalized,
    startExploration,
    explorationId: explorationId || undefined
  });

  // Reset state when modal closes
  useEffect(() => {
    if (!isOpen) {
      console.log('[@AIGenerationModal:Phase1] Modal closed - preserving state for potential retry');
    }
  }, [isOpen]);

  const handleCancel = async () => {
    // Call cancelExploration if we have an active exploration session
    if (explorationId) {
      await cancelExploration();
      // Clean up _temp nodes from frontend state
      onCleanupTemp?.();
    }
    
    // Explicitly reset hook state when canceling
    console.log('[@AIGenerationModal:Phase1] Resetting state on cancel');
    resetState();
    
    onClose();
  };
  
  const handleCreateStructure = async () => {
    console.log('[@AIGenerationModal:Phase1] Creating structure...');
    // Pass edited plan if user deleted items
    await continueExploration(selectedScreenNodes, editedPlan); // Phase 2a: Create nodes/edges with screen selection and edited plan
    // onStructureCreated callback will be triggered by hook, which closes this modal
  };

  const getStatusIcon = () => {
    if (isAwaitingApproval) {
      return <AnalyzeIcon color="warning" />;
    }
    switch (status) {
      case 'exploring':
        return <AIIcon color="primary" />;
      case 'completed':
        return <NavigationIcon color="success" />;
      case 'failed':
        return <ErrorIcon color="error" />;
      default:
        return <AIIcon color="primary" />;
    }
  };

  const getStatusColor = () => {
    if (isAwaitingApproval) {
      return 'warning';
    }
    switch (status) {
      case 'exploring':
        return 'primary';
      case 'completed':
        return 'success';
      case 'failed':
        return 'error';
      default:
        return 'default';
    }
  };

  return (
    <>
      <StyledDialog
        open={isOpen}
        onClose={onClose}
        maxWidth="md"
        fullWidth
        PaperProps={{
          sx: { 
            maxHeight: '90vh',
        }
      }}
    >
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <AIIcon />
        AI Interface Generation
        <Chip
          icon={getStatusIcon()}
          label={status.toUpperCase()}
          color={getStatusColor()}
          size="small"
          sx={{ ml: 'auto' }}
        />
      </DialogTitle>

      <DialogContent sx={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 2 }}>
        {/* v2.0: Phase Indicator */}
        {currentPhase && (
          <AIGenerationPhaseIndicator 
            currentPhase={currentPhase} 
            strategy={strategy} 
          />
        )}

        {/* v2.0: Context Summary */}
        {context && <ContextSummary context={context} />}

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {/* Configuration Section - Only show when not exploring */}
        {!isExploring && !isAwaitingApproval && (
          <Paper sx={{ p: 2, bgcolor: 'transparent' }}>
            <Grid container spacing={2} alignItems="center">
              <Grid item xs={12}>
                <Typography variant="body2">
                  The system will explore main navigation items
                  and their sub-items
                </Typography>
                <Typography variant="body2" sx={{ mt: 1 }}>
                  Host: {selectedHost?.host_name} | Device: {selectedDeviceId}
                </Typography>
           
              </Grid>
            </Grid>
          </Paper>
        )}

                        {/* Approval Section - Show AI plan */}
        {isAwaitingApproval && activePlan && (
          <Paper sx={{ p: 2, bgcolor: 'transparent' }}>
            <Grid container spacing={2}>
              {/* Left: Screenshot */}
              <Grid item xs={12} md={5}>
                {screenshotR2Url ? (
                  <a 
                    href={screenshotR2Url} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    style={{ display: 'block', cursor: 'pointer' }}
                  >
                    <img
                      src={screenshotR2Url}
                      alt="Initial screen"
                      style={{
                        width: '100%',
                        maxHeight: '280px',
                        objectFit: 'contain',
                        borderRadius: '4px',
                        border: '1px solid rgba(255, 255, 255, 0.12)',
                        transition: 'opacity 0.2s'
                      }}
                      onMouseOver={(e) => e.currentTarget.style.opacity = '0.8'}
                      onMouseOut={(e) => e.currentTarget.style.opacity = '1'}
                    />
                  </a>
                ) : (
                  <Box sx={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px dashed rgba(255,255,255,0.3)', borderRadius: 1 }}>
                    <Typography variant="body2" color="text.secondary">No screenshot</Typography>
                  </Box>
                )}
              </Grid>

              {/* Right: AI Plan */}
              <Grid item xs={12} md={7}>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                  {activePlan.items.length === 0 ? (
                    <Typography variant="body2" color="warning.main">No items detected - AI couldn't read screen</Typography>
                  ) : (
                    <>
                      {/* Nodes Found - Show cleaned preview */}
                      <details open>
                        <summary style={{ cursor: 'pointer', userSelect: 'none', padding: '4px 0' }}>
                          <Typography variant="body2" component="span" sx={{ fontWeight: 500 }}>
                            Nodes found ({(() => {
                              // Calculate actual node count based on strategy
                              const strategy = activePlan.strategy || 'click';
                              const items = activePlan.items || [];
                              const nonHomeItems = items.filter((item: string) => {
                                const lower = item.toLowerCase();
                                return !['home', 'accueil'].includes(lower);
                              });
                              
                              if (strategy === 'dpad_with_screenshot' || strategy === 'test_dpad_directions') {
                                // Dual-layer: each item gets focus + screen node
                                return nonHomeItems.length * 2;
                              } else {
                                // Mobile/web: one node per item
                                return nonHomeItems.length;
                              }
                            })()})
                          </Typography>
                        </summary>
                        <Box sx={{ mt: 1, pl: 2, maxHeight: 200, overflow: 'auto' }}>
                          {activePlan.lines && activePlan.lines.length > 0 ? (
                            // DPAD navigation (TV/STB) - show dual-layer chips
                            <Box sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>
                              {activePlan.lines.map((line: string[], lineIdx: number) => {
                                // Helper: Strip _duplicate* suffix for display
                                const stripDuplicateSuffix = (name: string) => name.replace(/_duplicate\d+$/i, '');
                                
                                // Generate focus and screen node data WITH ORIGINAL INDICES
                                const nodePairs: Array<{item: string, focusNode: string, screenNode: string, originalIndex: number}> = [];
                                
                                line.forEach((item, originalIdx) => {
                                  const isHome = item.toLowerCase() === 'home';
                                  const displayName = stripDuplicateSuffix(item);  // Remove _duplicate* for clean name
                                  const cleanName = displayName.toLowerCase().replace(/[^a-z0-9]+/g, '_');
                                  
                                  if (!isHome) {
                                    nodePairs.push({
                                      item: item,  // Keep full name with _duplicate* for selection tracking
                                      focusNode: `home_${cleanName}`,  // Use clean name for display
                                      screenNode: cleanName,  // Use clean name for display
                                      originalIndex: originalIdx  // ✅ Preserve original line index
                                    });
                                  }
                                });
                                
                                if (nodePairs.length === 0) return null;
                                
                                return (
                                  <Box key={lineIdx} sx={{ mb: 1.5 }}>
                                    <Typography variant="body2" sx={{ color: 'text.secondary', mb: 0.5 }}>
                                      Row {lineIdx + 1}:
                                    </Typography>
                                    
                                    {/* Focus Layer Chips */}
                                    <Box sx={{ pl: 1, mb: 0.5 }}>
                                      <Typography variant="caption" sx={{ color: 'primary.light', fontSize: '0.65rem' }}>
                                        Focus:
                                      </Typography>
                                      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
                                        {nodePairs.map((pair, idx) => {
                                          const isFocusSelected = selectedNodes.has(pair.item);
                                          const positionKey = `${lineIdx}_${pair.originalIndex}`;  // ✅ Use original index!
                                          const isDuplicate = activePlan.duplicate_positions?.includes(positionKey);
                                          return (
                                            <Box key={idx} sx={{ position: 'relative', display: 'inline-block' }}>
                                              <Chip 
                                                label={pair.focusNode}
                                                size="small"
                                                variant="outlined"
                                                onClick={isDuplicate ? undefined : () => toggleFocusNode(pair.item)}
                                                onDelete={!isDuplicate ? () => deleteItem(lineIdx, pair.originalIndex) : undefined}
                                                sx={{
                                                  cursor: isDuplicate ? 'not-allowed' : 'pointer',
                                                  opacity: isDuplicate ? 0.7 : (isFocusSelected ? 1 : 0.4),
                                                  bgcolor: isDuplicate ? 'rgba(244, 67, 54, 0.3)' : (isFocusSelected ? 'rgba(33, 150, 243, 0.2)' : 'transparent'),
                                                  borderColor: isDuplicate ? 'error.main' : (isFocusSelected ? 'primary.main' : 'grey.600'),
                                                  borderWidth: isDuplicate ? '2px' : '1px',
                                                  fontSize: '0.65rem',
                                                  '&:hover': isDuplicate ? {} : {
                                                    opacity: 0.8,
                                                    bgcolor: isFocusSelected ? 'rgba(33, 150, 243, 0.3)' : 'action.hover'
                                                  }
                                                }}
                                              />
                                            </Box>
                                          );
                                        })}
                                      </Box>
                                    </Box>
                                    
                                    {/* Screen Layer Chips */}
                                    <Box sx={{ pl: 1 }}>
                                      <Typography variant="caption" sx={{ color: 'success.light', fontSize: '0.65rem' }}>
                                        Screen:
                                      </Typography>
                                      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
                                        {nodePairs.map((pair, idx) => {
                                          const isFocusSelected = selectedNodes.has(pair.item);
                                          const isScreenSelected = selectedScreenNodes.has(pair.item);
                                          const positionKey = `${lineIdx}_${pair.originalIndex}`;  // ✅ Use original index!
                                          const isDuplicate = activePlan.duplicate_positions?.includes(positionKey);
                                          return (
                                            <Box key={idx} sx={{ position: 'relative', display: 'inline-block' }}>
                                              <Chip 
                                                label={pair.screenNode}
                                                size="small"
                                                variant="outlined"
                                                onClick={isDuplicate ? undefined : () => toggleScreenNode(pair.item)}
                                                onDelete={!isDuplicate ? () => deleteItem(lineIdx, pair.originalIndex) : undefined}
                                                sx={{
                                                  cursor: isDuplicate ? 'not-allowed' : (isFocusSelected ? 'pointer' : 'not-allowed'),
                                                  opacity: isDuplicate ? 0.7 : ((isFocusSelected && isScreenSelected) ? 1 : 0.3),
                                                  bgcolor: isDuplicate ? 'rgba(244, 67, 54, 0.3)' : ((isFocusSelected && isScreenSelected) ? 'rgba(76, 175, 80, 0.2)' : 'transparent'),
                                                  borderColor: isDuplicate ? 'error.main' : ((isFocusSelected && isScreenSelected) ? 'success.main' : 'grey.700'),
                                                  borderWidth: isDuplicate ? '2px' : '1px',
                                                  fontSize: '0.65rem',
                                                  '&:hover': isDuplicate ? {} : (isFocusSelected ? {
                                                    opacity: 0.8,
                                                    bgcolor: isScreenSelected ? 'rgba(76, 175, 80, 0.3)' : 'action.hover'
                                                  } : undefined)
                                                }}
                                              />
                                            </Box>
                                          );
                                        })}
                                      </Box>
                                    </Box>
                                  </Box>
                                );
                              })}
                            </Box>
                          ) : (
                            // Click-based navigation (mobile/web) - show cleaned node names as chips
                            // ✅ Filter out home nodes (home, Home, Accueil, etc.)
                            <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                              {activePlan.items
                                .filter((item: string) => {
                                  const lower = item.toLowerCase();
                                  return !['home', 'accueil'].includes(lower);
                                })
                                .map((item: string, idx: number) => {
                                  // Check if this is a renamed duplicate
                                  const isDuplicate = /_duplicate\d+$/i.test(item);
                                  const displayItem = item.replace(/_duplicate\d+$/i, '');  // Strip suffix for display
                                  
                                  // Generate clean node name (same logic as action sets)
                                  const cleanNodeName = displayItem.toLowerCase()
                                    .replace(/&amp;/g, ' ')
                                    .replace(/tab|register|button|screen|menu|page|currently selected/gi, ' ')
                                    .replace(/[^a-z0-9]+/g, '_')
                                    .replace(/_+/g, '_')
                                    .replace(/^_|_$/g, '');
                                  
                                  const isSelected = selectedNodes.has(item);
                                  
                                  return (
                                    <Chip 
                                      key={idx} 
                                      label={cleanNodeName} 
                                      size="small" 
                                      variant="outlined"
                                      onClick={isDuplicate ? undefined : () => toggleNodeSelection(item)}
                                      onDelete={!isDuplicate ? () => deleteItem(0, idx) : undefined}
                                      sx={{ 
                                        cursor: isDuplicate ? 'not-allowed' : 'pointer',
                                        opacity: isDuplicate ? 0.7 : (isSelected ? 1 : 0.4),
                                        bgcolor: isDuplicate ? 'rgba(244, 67, 54, 0.3)' : (isSelected ? 'primary.dark' : 'transparent'),
                                        borderColor: isDuplicate ? 'error.main' : (isSelected ? 'primary.main' : 'grey.600'),
                                        borderWidth: isDuplicate ? '2px' : '1px',
                                        '&:hover': isDuplicate ? {} : {
                                          opacity: 0.8,
                                          bgcolor: isSelected ? 'primary.dark' : 'action.hover'
                                        }
                                      }}
                                    />
                                  );
                                })}
                            </Box>
                          )}
                        </Box>
                      </details>

                      {/* Edges Found - Show bilateral action sets - OPEN BY DEFAULT */}
                      {(() => {
                        // ✅ USE BACKEND-CALCULATED EDGES (no recalculation!)
                        const edgesPreview = activePlan.edges_preview || [];
                        const strategy = activePlan.strategy || 'click';
                        
                        return (
                          <details open>
                            <summary style={{ cursor: 'pointer', userSelect: 'none', padding: '4px 0' }}>
                              <Typography variant="body2" component="span" sx={{ fontWeight: 500 }}>
                                Edge found ({edgesPreview.length})
                              </Typography>
                            </summary>
                            <Box sx={{ mt: 1, pl: 2, pr:2, maxHeight: 200, overflow: 'auto' }}>
                              {edgesPreview.map((edgePreview: any, idx: number) => {
                                const item = edgePreview.item;
                                const isSelected = selectedEdges.has(item);
                                
                                if (strategy === 'dpad_with_screenshot' || strategy === 'test_dpad_directions') {
                                  // Dual-layer edges - use backend-calculated data
                                  const horizontal = edgePreview.horizontal || {};
                                  const vertical = edgePreview.vertical || {};
                                  
                                  return (
                                    <Box 
                                      key={idx} 
                                      sx={{ 
                                        mb: 0.5, 
                                        p: 1, 
                                        bgcolor: isSelected ? 'rgba(25,118,210,0.08)' : 'rgba(255,255,255,0.02)', 
                                        borderRadius: 1, 
                                        border: '1px solid', 
                                        borderColor: isSelected ? 'primary.main' : 'rgba(255,255,255,0.05)',
                                        opacity: isSelected ? 1 : 0.4,
                                        cursor: 'pointer',
                                        transition: 'all 0.2s',
                                        '&:hover': {
                                          opacity: 0.8,
                                          bgcolor: isSelected ? 'rgba(25,118,210,0.12)' : 'rgba(255,255,255,0.05)'
                                        }
                                      }}
                                      onClick={() => toggleEdgeSelection(item)}
                                    >
                                      <Typography variant="caption" sx={{ fontWeight: 'bold', color: 'text.secondary', display: 'block', mb: 0.5 }}>
                                        {item} {!isSelected && '(skipped)'}
                                      </Typography>
                                      {/* Horizontal edges - using backend data */}
                                      <Typography variant="body2" sx={{ fontSize: '0.70rem', fontFamily: 'monospace', pl: 1 }}>
                                        {horizontal.source} → {horizontal.target}: {horizontal.forward_action}
                                      </Typography>
                                      <Typography variant="body2" sx={{ fontSize: '0.70rem', fontFamily: 'monospace', pl: 1 }}>
                                        {horizontal.target} ← {horizontal.source}: {horizontal.reverse_action}
                                      </Typography>
                                      {/* Vertical edges - using backend data */}
                                      <Typography variant="body2" sx={{ fontSize: '0.70rem', fontFamily: 'monospace', pl: 1 }}>
                                        {vertical.source} ↓ {vertical.target}: {vertical.forward_action}
                                      </Typography>
                                      <Typography variant="body2" sx={{ fontSize: '0.70rem', fontFamily: 'monospace', pl: 1 }}>
                                        {vertical.target} ↑ {vertical.source}: {vertical.reverse_action}
                                      </Typography>
                                    </Box>
                                  );
                                } else {
                                  // Mobile/web: single click edge - using backend data
                                  const click = edgePreview.click || {};
                                  
                                  return (
                                    <Box 
                                      key={idx} 
                                      sx={{ 
                                        mb: 0.5, 
                                        p: 1, 
                                        bgcolor: isSelected ? 'rgba(25,118,210,0.08)' : 'rgba(255,255,255,0.02)', 
                                        borderRadius: 1, 
                                        border: '1px solid', 
                                        borderColor: isSelected ? 'primary.main' : 'rgba(255,255,255,0.05)',
                                        opacity: isSelected ? 1 : 0.4,
                                        cursor: 'pointer',
                                        transition: 'all 0.2s',
                                        '&:hover': {
                                          opacity: 0.8,
                                          bgcolor: isSelected ? 'rgba(25,118,210,0.12)' : 'rgba(255,255,255,0.05)'
                                        }
                                      }}
                                      onClick={() => toggleEdgeSelection(item)}
                                    >
                                      <Typography variant="caption" sx={{ fontWeight: 'bold', color: 'text.secondary', display: 'block', mb: 0.5 }}>
                                        {item} {!isSelected && '(skipped)'}
                                      </Typography>
                                      <Typography variant="body2" sx={{ fontSize: '0.70rem', fontFamily: 'monospace', pl: 1 }}>
                                        {click.source} → {click.target}: {click.forward_action}
                                      </Typography>
                                      <Typography variant="body2" sx={{ fontSize: '0.70rem', fontFamily: 'monospace', pl: 1 }}>
                                        {click.target} ← {click.source}: {click.reverse_action}
                                      </Typography>
                                    </Box>
                                  );
                                }
                              })}
                            </Box>
                          </details>
                        );
                      })()}
                    </>
                  )}
                </Box>
              </Grid>
            </Grid>
          </Paper>
        )}

        {/* Exploration Progress Section - Phase 1 only */}
        {isExploring && currentPhase !== 'phase2' && (
          <Paper sx={{ p: 2, flex: 1, display: 'flex', flexDirection: 'column', bgcolor: 'transparent' }}>
            {/* Current Step */}
            <Box sx={{ mb: 2 }}>
              <Typography variant="subtitle2" color="text.secondary">
                Current Step:
              </Typography>
              <Typography variant="body2" sx={{ fontFamily: 'monospace', p: 1, borderRadius: 1 }}>
                {currentStep || 'Initializing...'}
              </Typography>
            </Box>

            {/* Progress Indicators */}
            <Box sx={{ mb: 2 }}>
              <LinearProgress variant="indeterminate" sx={{ mb: 1 }} />
              <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                <Chip label={`Nodes: ${progress.nodes_proposed}`} size="small" />
                <Chip label={`Edges: ${progress.edges_proposed}`} size="small" />
              </Box>
            </Box>
          </Paper>
        )}

        {/* v2.0: Phase 2 Incremental View */}
        {currentPhase === 'phase2' && (
          <Phase2IncrementalView 
            context={context} 
            error={error}
            selectedNodes={selectedNodes}
            onToggleNode={toggleNodeSelection}
          />
        )}
      </DialogContent>

      <DialogActions sx={{ p: 2, gap: 1, position: 'relative' }}>
        {/* Bottom-Left: Validate/Abort Previous - Show when temp nodes exist */}
        {hasTempNodes && !isExploring && !isAwaitingApproval && (
          <Box sx={{ position: 'absolute', left: 16, bottom: 16, display: 'flex', gap: 1 }}>
            <Button
              variant="contained"
              onClick={handleAbortPrevious}
              disabled={isValidating || isAborting}
              startIcon={isAborting ? <CircularProgress size={16} /> : <AbortIcon />}
              sx={{
                bgcolor: 'error.main',
                '&:hover': { bgcolor: 'error.dark' },
                textTransform: 'none'
              }}
            >
              {isAborting ? 'Aborting...' : 'Abort Previous'}
            </Button>
            <Button
              variant="contained"
              onClick={handleValidatePrevious}
              disabled={isValidating || isAborting}
              startIcon={isValidating ? <CircularProgress size={16} /> : <ValidateIcon />}
              sx={{
                bgcolor: 'success.main',
                '&:hover': { bgcolor: 'success.dark' },
                textTransform: 'none'
              }}
            >
              {isValidating ? 'Validating...' : 'Validate Previous'}
            </Button>
            
          </Box>
        )}

        {/* Phase 1: Awaiting Approval - Show Abort, Retry, Create Nodes */}
        {isAwaitingApproval && (
          <>
            <Button
              variant="outlined"
              color="error"
              onClick={handleCancel}
              startIcon={<CancelIcon />}
            >
              Abort
            </Button>
            <Button
              variant="outlined"
              color="warning"
              onClick={handleStart}
            >
              Retry
            </Button>
            <Button
              variant="contained"
              color="success"
              onClick={handleCreateStructure}
              startIcon={<NavigationIcon />}
            >
              Create Nodes/Edges
            </Button>
          </>
        )}

        {/* Initial State: Show Close and Start */}
        {!isExploring && !isAwaitingApproval && (
          <>
            <Button
              onClick={handleCancel}
              variant="outlined"
              startIcon={<CancelIcon />}
            >
              Close
            </Button>
            <Button
              onClick={handleStart}
              variant="contained"
              startIcon={<AIIcon />}
              disabled={!canStart || isCheckingTree}
            >
              {isCheckingTree ? 'Checking...' : 'Start'}
            </Button>
          </>
        )}

        {/* Exploring: Show Cancel */}
        {isExploring && (
          <Button
            onClick={handleCancel}
            variant="outlined"
            color="error"
            startIcon={<CancelIcon />}
          >
            Cancel
          </Button>
        )}
      </DialogActions>
    </StyledDialog>
    
    {/* Confirmation Dialog: Delete existing nodes/edges */}
    <StyledDialog
      open={showCleanConfirm}
      onClose={handleCancelClean}
      maxWidth="sm"
      fullWidth
    >
      <DialogTitle>Clean Tree Before AI Generation?</DialogTitle>
      <DialogContent>
        <Alert severity="warning" sx={{ mb: 2 }}>
          This tree already contains navigation data. AI generation requires a clean tree.
        </Alert>
        <Typography variant="body2" gutterBottom>
          Found existing data:
        </Typography>
        <Box sx={{ pl: 2, mb: 2 }}>
          <Typography variant="body2">• {existingNodesCount} node{existingNodesCount !== 1 ? 's' : ''} (excluding {startNodeLabel})</Typography>
          <Typography variant="body2">• {existingEdgesCount} edge{existingEdgesCount !== 1 ? 's' : ''}</Typography>
        </Box>
        <Typography variant="body2" color="text.secondary">
          Do you agree to delete all existing nodes and edges before starting AI generation?
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleCancelClean} variant="outlined">
          Cancel
        </Button>
        <Button 
          onClick={handleConfirmClean} 
          variant="contained" 
          color="error"
          disabled={isCheckingTree}
          startIcon={isCheckingTree ? <CircularProgress size={16} sx={{ color: 'inherit' }} /> : undefined}
        >
          {isCheckingTree ? 'Deleting...' : 'Delete'}
        </Button>
      </DialogActions>
    </StyledDialog>
    </>
  );
};
