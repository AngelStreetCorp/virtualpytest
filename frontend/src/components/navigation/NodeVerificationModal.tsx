import React, { useState, useEffect } from 'react';
import {
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
  Alert,
  Chip,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Grid,
  Card,
  CardContent,
  IconButton,
} from '@mui/material';
import {
  CheckCircle as CheckIcon,
  Error as ErrorIcon,
  Close as CloseIcon,
  Save as SaveIcon,
  ExpandMore as ExpandMoreIcon,
  ImageNotSupported as NoImageIcon,
  ArrowBack as BackIcon,
} from '@mui/icons-material';
import { StyledDialog } from '../common/StyledDialog';
import { R2Image } from '../common/R2Image';

interface NodeVerificationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCancel?: () => void;
  suggestions: any[];
  onApprove: (approvedVerifications: any[]) => Promise<any>;
  isUpdating: boolean;
}

export const NodeVerificationModal: React.FC<NodeVerificationModalProps> = ({
  isOpen,
  onClose,
  onCancel,
  suggestions,
  onApprove,
  isUpdating
}) => {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // Reset to grid view when modal opens
  useEffect(() => {
    if (isOpen) {
      setSelectedNodeId(null);
    }
  }, [isOpen]);

  const handleSave = async () => {
    // Save ALL nodes that have data (screenshot or verification)
    const approvedVerifications = suggestions
      .filter(s => s.screenshot_url || s.suggested_verification?.found)
      .map(s => ({
        node_id: s.node_id,
        verification: s.suggested_verification?.found ? s.suggested_verification : null,
        screenshot_url: s.screenshot_url || null
      }));

    await onApprove(approvedVerifications);
    onClose();
  };

  // Count nodes with data
  const nodesWithScreenshot = suggestions.filter(s => s.screenshot_url).length;
  const nodesWithVerification = suggestions.filter(s => s.suggested_verification?.found).length;
  const totalNodesToSave = suggestions.filter(s => s.screenshot_url || s.suggested_verification?.found).length;

  const selectedSuggestion = suggestions.find(s => s.node_id === selectedNodeId);

  return (
    <StyledDialog
      open={isOpen}
      onClose={onClose}
      maxWidth="xl"
      fullWidth
      PaperProps={{
        sx: {
          maxHeight: '90vh',
          height: '90vh',
          bgcolor: 'background.paper'
        }
      }}
    >
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, borderBottom: '1px solid', borderColor: 'divider', pb: 1 }}>
        {selectedNodeId && (
          <IconButton size="small" onClick={() => setSelectedNodeId(null)} sx={{ mr: 1 }}>
            <BackIcon />
          </IconButton>
        )}
        <CheckIcon />
        {selectedNodeId ? selectedSuggestion?.node_label : 'Node Verification Review'}
        <Box sx={{ ml: 'auto', display: 'flex', gap: 1, alignItems: 'center' }}>
          <Chip 
            label={`${nodesWithScreenshot} screenshots`} 
            size="small" 
            color={nodesWithScreenshot > 0 ? 'primary' : 'default'}
          />
          <Chip 
            label={`${nodesWithVerification} verifications`} 
            size="small" 
            color={nodesWithVerification > 0 ? 'success' : 'default'}
          />
        </Box>
      </DialogTitle>

      <DialogContent sx={{ p: 0, overflow: 'auto', flex: 1, display: 'flex', flexDirection: 'column' }}>
        {/* GRID VIEW */}
        {!selectedNodeId && (
          <Box sx={{ p: 3 }}>
            <Grid container spacing={2}>
              {suggestions.map((suggestion) => {
                const hasScreenshot = !!suggestion.screenshot_url;
                const hasVerification = suggestion.suggested_verification?.found;
                
                return (
                  <Grid item xs={12} sm={6} md={4} lg={3} xl={2.4} key={suggestion.node_id}>
                    <Card 
                      sx={{ 
                        cursor: 'pointer',
                        height: '100%',
                        border: '1px solid',
                        borderColor: 'divider',
                        transition: 'all 0.2s',
                        '&:hover': {
                          borderColor: 'primary.main',
                          bgcolor: 'action.hover',
                          transform: 'translateY(-2px)',
                          boxShadow: 2
                        }
                      }}
                      onClick={() => setSelectedNodeId(suggestion.node_id)}
                    >
                      <CardContent sx={{ p: 1.5, '&:last-child': { pb: 1.5 } }}>
                        <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }} noWrap>
                          {suggestion.node_label}
                        </Typography>
                        
                        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                            {hasScreenshot ? (
                              <CheckIcon fontSize="small" sx={{ fontSize: 14, color: 'success.main' }} />
                            ) : (
                              <NoImageIcon fontSize="small" sx={{ fontSize: 14, color: 'action.disabled' }} />
                            )}
                            <Typography variant="caption" color={hasScreenshot ? 'text.primary' : 'text.disabled'}>
                              Screenshot
                            </Typography>
                          </Box>
                          
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                            {hasVerification ? (
                              <CheckIcon fontSize="small" sx={{ fontSize: 14, color: 'success.main' }} />
                            ) : suggestion.suggested_verification?.skipped ? (
                              <CheckIcon fontSize="small" sx={{ fontSize: 14, color: 'action.disabled' }} />
                            ) : (
                              <ErrorIcon fontSize="small" sx={{ fontSize: 14, color: 'error.main' }} />
                            )}
                            <Typography 
                              variant="caption" 
                              color={hasVerification ? 'text.primary' : suggestion.suggested_verification?.skipped ? 'text.disabled' : 'error.main'} 
                              noWrap
                            >
                              {hasVerification ? 'Found' : suggestion.suggested_verification?.skipped ? 'Skipped' : 'Not found'}
                            </Typography>
                          </Box>
                        </Box>
                      </CardContent>
                    </Card>
                  </Grid>
                );
              })}
            </Grid>
          </Box>
        )}

        {/* DETAIL VIEW */}
        {selectedNodeId && selectedSuggestion && (
          <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Grid container spacing={3}>
              {/* LEFT: Screenshot */}
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom sx={{ fontWeight: 600 }}>
                  Screenshot
                </Typography>
                {selectedSuggestion.screenshot_url ? (
                  <R2Image
                    src={selectedSuggestion.screenshot_url}
                    alt={selectedSuggestion.node_label}
                    sx={{
                      width: '100%',
                      maxHeight: 400,
                      objectFit: 'contain',
                      borderRadius: 1,
                      border: '1px solid',
                      borderColor: 'divider',
                      bgcolor: 'background.default'
                    }}
                  />
                ) : (
                  <Alert severity="warning" icon={<NoImageIcon />}>
                    No screenshot available
                  </Alert>
                )}
              </Grid>

              {/* RIGHT: Verification + Dump */}
              <Grid item xs={12} md={6}>
                {/* Verification */}
                <Typography variant="subtitle2" gutterBottom sx={{ fontWeight: 600 }}>
                  Suggested Verification
                </Typography>
                
                {selectedSuggestion.suggested_verification?.found ? (
                  <Box sx={{ mb: 1.5, p: 1.5, bgcolor: 'background.default', borderRadius: 1, border: '1px solid', borderColor: 'divider' }}>
                    {/* TV/OCR Format: {text, area} */}
                    {selectedSuggestion.suggested_verification.text !== undefined ? (
                      <>
                        <Typography variant="body2" sx={{ fontFamily: 'monospace', mb: 1 }}>
                          <strong>Text:</strong> {selectedSuggestion.suggested_verification.text}
                        </Typography>
                        {selectedSuggestion.suggested_verification.area && (
                          <Typography variant="body2" sx={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>
                            <strong>Area:</strong> {JSON.stringify(selectedSuggestion.suggested_verification.area, null, 2)}
                          </Typography>
                        )}
                      </>
                    ) : (
                      /* Mobile/Web Format: {method, type, params} */
                      <>
                        <Typography variant="body2" sx={{ fontFamily: 'monospace', mb: 1 }}>
                          <strong>Method:</strong> {selectedSuggestion.suggested_verification.method}
                        </Typography>
                        <Typography variant="body2" sx={{ fontFamily: 'monospace', mb: 1 }}>
                          <strong>Type:</strong> {selectedSuggestion.suggested_verification.type}
                        </Typography>
                        <Typography variant="body2" sx={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>
                          <strong>Value:</strong> {JSON.stringify(selectedSuggestion.suggested_verification.params, null, 2)}
                        </Typography>
                      </>
                    )}
                    <Chip 
                      label="Will be saved" 
                      size="small" 
                      color="success" 
                      sx={{ mt: 1 }}
                    />
                  </Box>
                ) : selectedSuggestion.suggested_verification?.skipped ? (
                  <Alert severity="info" sx={{ mb: 1.5 }}>
                    <Typography variant="body2">
                      Verification skipped - {selectedSuggestion.suggested_verification.reason || 'screenshot-only node'}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      This node only has a screenshot, no UI dump was captured.
                    </Typography>
                  </Alert>
                ) : (
                  <Alert severity="error" sx={{ mb: 1.5 }}>
                    <Typography variant="body2">
                      No unique element found for this node.
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      You may need to manually add verification after generation.
                    </Typography>
                  </Alert>
                )}

                {/* Dump (OCR for TV, XML for Mobile/Web) */}
                <Accordion>
                  <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                      {selectedSuggestion.dump?.dump_type?.toLowerCase() === 'ocr' ? 'OCR Dump' : 'XML Dump'}
                    </Typography>
                  </AccordionSummary>
                  <AccordionDetails sx={{ p: 0 }}>
                    {selectedSuggestion.dump ? (
                      <Box 
                        sx={{ 
                          maxHeight: 300, 
                          overflow: 'auto', 
                          bgcolor: 'background.default',
                          p: 1,
                          borderRadius: 1,
                          border: '1px solid',
                          borderColor: 'divider'
                        }}
                      >
                        {/* OCR Dump (TV) - Show formatted list */}
                        {selectedSuggestion.dump?.dump_type?.toLowerCase() === 'ocr' ? (
                          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                            {selectedSuggestion.dump.elements && selectedSuggestion.dump.elements.length > 0 ? (
                              <Box 
                                component="pre" 
                                sx={{ 
                                  fontFamily: 'monospace',
                                  fontSize: '0.7rem',
                                  margin: 0,
                                  whiteSpace: 'pre-wrap',
                                  lineHeight: 1.6
                                }}
                              >
                                {`Total Elements: ${selectedSuggestion.dump.elements.length}\n${selectedSuggestion.dump.elements.map((elem: any, idx: number) => {
                                  const area = elem.area || {};
                                  const parts = [`[${idx + 1}] text: ${elem.text}`];
                                  parts.push(`area: x=${area.x || 0}, y=${area.y || 0}, w=${area.w || 0}, h=${area.h || 0}`);
                                  if (elem.confidence) {
                                    parts.push(`confidence: ${elem.confidence}`);
                                  }
                                  return parts.join(', ');
                                }).join('\n')}`}
                              </Box>
                            ) : (
                              <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem', fontStyle: 'italic' }}>
                                &lt;empty dump&gt;
                              </Typography>
                            )}
                          </Box>
                        ) : (
                          /* XML Dump (Mobile/Web) - Show as text */
                        <Typography 
                          variant="caption" 
                          component="pre" 
                          sx={{ 
                            fontFamily: 'monospace',
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                            fontSize: '0.7rem'
                          }}
                        >
                            {typeof selectedSuggestion.dump === 'string' 
                              ? selectedSuggestion.dump 
                              : JSON.stringify(selectedSuggestion.dump, null, 2)
                            }
                        </Typography>
                        )}
                      </Box>
                    ) : (
                      <Alert severity="info">
                        No dump data available
                      </Alert>
                    )}
                  </AccordionDetails>
                </Accordion>
              </Grid>
            </Grid>
          </Box>
        )}
      </DialogContent>

      <DialogActions sx={{ p: 1, gap: 1, borderTop: '1px solid', borderColor: 'divider', justifyContent: 'space-between' }}>
        <Typography variant="caption" color="text.secondary">
          {totalNodesToSave} / {suggestions.length} nodes
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button
            onClick={() => {
              if (onCancel) {
                onCancel();
              } else {
                onClose();
              }
            }}
            variant="outlined"
            startIcon={<CloseIcon />}
            disabled={isUpdating}
          >
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            variant="contained"
            color="primary"
            startIcon={<SaveIcon />}
            disabled={isUpdating || totalNodesToSave === 0}
          >
            {isUpdating ? 'Saving...' : `Save ${totalNodesToSave > 0 ? `(${totalNodesToSave})` : ''}`}
          </Button>
        </Box>
      </DialogActions>
    </StyledDialog>
  );
};
