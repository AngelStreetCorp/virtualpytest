/**
 * OutputDisplay Component
 * 
 * Universal component to display block output data/results
 * Works for: action, verification, navigation, standard blocks
 */

import React, { useState } from 'react';
import { Box, Typography, Chip, Collapse, IconButton, Tooltip, Dialog, DialogTitle, DialogContent, DialogActions, Button, Badge } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CallMadeIcon from '@mui/icons-material/CallMade'; // ✅ NEW: Outgoing link icon
import { useTheme } from '../../../contexts/ThemeContext';

// ✅ NEW: Information about where this output is linked to
interface LinkedTo {
  targetType: 'variable' | 'output' | 'metadata' | 'input';
  targetName: string;
  targetId?: string;
}

interface OutputDisplayProps {
  blockOutputs?: Array<{ name: string; type: string; value?: any }>;
  onDragStart?: (output: { blockId: string; outputName: string; outputType: string }) => void;
  onDragEnd?: () => void;
  blockId?: string;
  // ✅ NEW: Track what each output is linked to
  linkedTo?: Record<string, LinkedTo[]>; // { "parsed_data": [{ targetType: 'variable', targetName: 'info' }] }
}

export const OutputDisplay: React.FC<OutputDisplayProps> = ({
  blockOutputs,
  onDragStart,
  onDragEnd,
  blockId,
  linkedTo = {}, // ✅ NEW: Default to empty object
}) => {
  // ✅ ALWAYS call hooks at the top level - before any early returns
  const { actualMode } = useTheme();
  const [expanded, setExpanded] = useState(false);
  const [copiedOutput, setCopiedOutput] = useState<string | null>(null);
  const [viewDialogOpen, setViewDialogOpen] = useState(false);
  const [viewDialogData, setViewDialogData] = useState<{ name: string; value: any } | null>(null);

  // ✅ NEW: Helper to format linked targets for tooltip
  const getLinkedToTooltip = (outputName: string): string => {
    const links = linkedTo[outputName];
    if (!links || links.length === 0) {
      return '';
    }
    
    if (links.length === 1) {
      const link = links[0];
      const typeLabel = link.targetType.toUpperCase();
      return `Linked to ${typeLabel}: ${link.targetName}`;
    }
    
    // Multiple links
    const lines = links.map(link => {
      const typeLabel = link.targetType.toUpperCase();
      return `  • ${typeLabel}: ${link.targetName}`;
    });
    return `Linked to (${links.length}):\n${lines.join('\n')}`;
  };
  
  // ✅ NEW: Get link badge count
  const getLinkCount = (outputName: string): number => {
    const links = linkedTo[outputName];
    return links ? links.length : 0;
  };

  // Early return AFTER all hooks
  if (!blockOutputs || blockOutputs.length === 0) {
    return null;
  }

  const handleCopyOutput = (output: { name: string; type: string; value?: any }, e: React.MouseEvent) => {
    e.stopPropagation();
    const textToCopy = output.value !== undefined 
      ? `${output.name}: ${typeof output.value === 'object' ? JSON.stringify(output.value, null, 2) : String(output.value)}`
      : `${output.name}: ${output.type}`;
    navigator.clipboard.writeText(textToCopy);
    setCopiedOutput(output.name);
    setTimeout(() => setCopiedOutput(null), 2000);
  };

  const getValueType = (value: any): string => {
    if (value === null) return 'null';
    if (value === undefined) return 'undefined';
    if (Array.isArray(value)) return 'array';
    if (typeof value === 'object') return 'dict';
    if (typeof value === 'number') return Number.isInteger(value) ? 'int' : 'float';
    return typeof value; // string, boolean, etc.
  };

  const handleViewOutput = (output: { name: string; value?: any }, e: React.MouseEvent) => {
    e.stopPropagation();
    console.log('[@OutputDisplay] handleViewOutput called:', { 
      name: output.name, 
      hasValue: output.value !== undefined,
      value: output.value 
    });
    console.log('[@OutputDisplay] Setting dialog data and opening...');
    setViewDialogData({ name: output.name, value: output.value });
    setViewDialogOpen(true);
    console.log('[@OutputDisplay] Dialog state set to open, viewDialogOpen should be true');
    // Debug: Check state after a tick
    setTimeout(() => {
      console.log('[@OutputDisplay] Dialog open state after timeout:', viewDialogOpen);
    }, 100);
  };

  return (
    <Box onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
      <Box
        onClick={() => setExpanded(!expanded)}
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          py: 0.5,
          px: 1,
          background: actualMode === 'dark' 
            ? 'linear-gradient(135deg, rgba(249, 115, 22, 0.15) 0%, rgba(249, 115, 22, 0.08) 100%)'
            : 'linear-gradient(135deg, rgba(249, 115, 22, 0.12) 0%, rgba(249, 115, 22, 0.06) 100%)',
          borderRadius: 1,
          border: '2px solid',
          borderColor: actualMode === 'dark' ? 'rgba(249, 115, 22, 0.4)' : 'rgba(249, 115, 22, 0.3)',
          boxShadow: actualMode === 'dark'
            ? '0 2px 8px rgba(249, 115, 22, 0.15), inset 0 1px 0 rgba(255, 255, 255, 0.1)'
            : '0 2px 8px rgba(249, 115, 22, 0.1), inset 0 1px 0 rgba(255, 255, 255, 0.5)',
          transition: 'all 0.2s ease-in-out',
          '&:hover': {
            bgcolor: actualMode === 'dark' ? 'rgba(249, 115, 22, 0.2)' : 'rgba(249, 115, 22, 0.15)',
            borderColor: actualMode === 'dark' ? 'rgba(249, 115, 22, 0.6)' : 'rgba(249, 115, 22, 0.5)',
            boxShadow: actualMode === 'dark'
              ? '0 4px 12px rgba(249, 115, 22, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.15)'
              : '0 4px 12px rgba(249, 115, 22, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.6)',
            transform: 'translateY(-1px)',
          },
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flex: 1, minWidth: 0 }}>
          <Typography fontSize={13} fontWeight="bold" color="#f97316" sx={{ flexShrink: 0 }}>
            Outputs ({blockOutputs.length})
          </Typography>
        </Box>
        {expanded ? <ExpandLessIcon sx={{ fontSize: 16, color: '#f97316', flexShrink: 0 }} /> : <ExpandMoreIcon sx={{ fontSize: 16, color: '#f97316', flexShrink: 0 }} />}
      </Box>
      
      <Collapse in={expanded}>
        <Box sx={{ mt: 0.5, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          {blockOutputs.map((output) => {
            const hasValue = output.value !== undefined;
            const displayValue = hasValue
              ? typeof output.value === 'object'
                ? JSON.stringify(output.value, null, 2)
                : String(output.value)
              : output.type;
            
            return (
              <Box key={output.name} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <Tooltip 
                  title={
                    <>
                      {hasValue 
                        ? "Click to view • Drag to link to inputs" 
                        : (blockId && onDragStart ? "Drag to link to inputs" : "")
                      }
                      {getLinkCount(output.name) > 0 && (
                        <>
                          <br />
                          <strong>{getLinkedToTooltip(output.name)}</strong>
                        </>
                      )}
                    </>
                  }
                  placement="left"
                >
                  <Badge
                    badgeContent={getLinkCount(output.name)}
                    color="warning" // ✅ Orange badge (not green)
                    overlap="circular"
                    anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
                    sx={{
                      flex: 1,
                      '& .MuiBadge-badge': {
                        fontSize: '0.6rem',
                        height: '16px',
                        minWidth: '16px',
                        backgroundColor: '#f97316', // ✅ Orange (output color)
                        color: 'white',
                        fontWeight: 'bold',
                      }
                    }}
                  >
                    <Chip
                      className="nodrag"
                      icon={getLinkCount(output.name) > 0 ? <CallMadeIcon sx={{ fontSize: 12 }} /> : undefined}
                      label={hasValue ? `${output.name}: ${displayValue.substring(0, 30)}${displayValue.length > 30 ? '...' : ''}` : `${output.name}: ${output.type}`}
                      size="small"
                    onClick={(e) => {
                      console.log('[@OutputDisplay] Chip onClick:', { 
                        hasValue, 
                        outputName: output.name,
                        defaultPrevented: e.defaultPrevented,
                        value: output.value
                      });
                      e.stopPropagation(); // Prevent block selection
                      
                      // Only handle click if has value and not dragging
                      if (hasValue && !e.defaultPrevented) {
                        console.log('[@OutputDisplay] Calling handleViewOutput for:', output.name);
                        handleViewOutput(output, e);
                      } else if (!hasValue) {
                        console.log('[@OutputDisplay] No value to display. Execute block first.');
                      }
                    }}
                    onMouseDown={(e) => {
                      // ✅ CRITICAL: Always stop mouseDown from propagating to parent to prevent block drag
                      console.log('[@OutputDisplay] MouseDown - preventing propagation');
                      e.stopPropagation();
                      // Don't preventDefault - it blocks the drag from starting!
                    }}
                    onMouseMove={(e) => {
                      // Stop mouse move from propagating to prevent block hover effects
                      if (blockId && onDragStart) {
                        e.stopPropagation();
                      }
                    }}
                    draggable={Boolean(blockId && onDragStart)}
                    onDragStart={(e) => {
                      console.log('[@OutputDisplay] Drag START:', output.name);
                      e.stopPropagation(); // ✅ Prevent block drag
                      
                      if (blockId && onDragStart) {
                        const dragData = {
                          blockId: blockId,
                          outputName: output.name,
                          outputType: output.type
                        };
                        onDragStart(dragData);
                        e.dataTransfer.setData('application/json', JSON.stringify(dragData));
                        e.dataTransfer.effectAllowed = 'link';
                        
                        // Create a custom drag image with chip styling
                        const dragImg = document.createElement('div');
                        dragImg.textContent = `🔗 ${output.name}`;
                        dragImg.style.position = 'absolute';
                        dragImg.style.top = '-1000px';
                        dragImg.style.padding = '4px 12px';
                        dragImg.style.backgroundColor = 'rgba(0, 0, 0, 0.9)';
                        dragImg.style.color = '#f97316';
                        dragImg.style.borderRadius = '16px'; // Rounded like MUI Chip
                        dragImg.style.fontSize = '11px';
                        dragImg.style.fontWeight = '500';
                        dragImg.style.border = '2px solid #f97316';
                        dragImg.style.boxShadow = '0 4px 12px rgba(249, 115, 22, 0.4)';
                        dragImg.style.whiteSpace = 'nowrap';
                        document.body.appendChild(dragImg);
                        e.dataTransfer.setDragImage(dragImg, 20, 10);
                        setTimeout(() => document.body.removeChild(dragImg), 0);
                      }
                    }}
                    onDrag={(e) => {
                      e.stopPropagation(); // ✅ Prevent block drag during drag
                    }}
                    onDragEnd={(e) => {
                      console.log('[@OutputDisplay] Drag END:', output.name);
                      e.stopPropagation(); // ✅ Prevent block drag on end
                      if (onDragEnd) {
                        onDragEnd();
                      }
                    }}
                      sx={{ 
                        fontSize: 16, 
                        height: 26,
                        flex: 1,
                        bgcolor: actualMode === 'dark' ? 'rgba(249, 115, 22, 0.1)' : 'rgba(249, 115, 22, 0.08)',
                        borderColor: '#f97316', // ✅ Always orange (output color)
                        borderWidth: getLinkCount(output.name) > 0 ? '2px' : '1px', // ✅ Thicker when linked
                        fontWeight: getLinkCount(output.name) > 0 ? 600 : 400, // ✅ Bolder when linked
                        cursor: blockId && onDragStart ? 'grab' : (hasValue ? 'pointer' : 'default'),
                        '&:hover': {
                          bgcolor: actualMode === 'dark' ? 'rgba(249, 115, 22, 0.2)' : 'rgba(249, 115, 22, 0.15)',
                        },
                        '&:active': {
                          cursor: blockId && onDragStart ? 'grabbing' : (hasValue ? 'pointer' : 'default'),
                        }
                      }}
                      variant="outlined"
                    />
                  </Badge>
                </Tooltip>
                
                <Tooltip title={copiedOutput === output.name ? "Copied!" : "Copy output"}>
                  <IconButton
                    size="small"
                    onClick={(e) => handleCopyOutput(output, e)}
                    sx={{
                      padding: '2px',
                      color: copiedOutput === output.name ? '#10b981' : '#f97316',
                      '&:hover': {
                        backgroundColor: 'rgba(249, 115, 22, 0.1)',
                      },
                    }}
                  >
                    <ContentCopyIcon sx={{ fontSize: 12 }} />
                  </IconButton>
                </Tooltip>
              </Box>
            );
          })}
        </Box>
      </Collapse>
      
      {/* View Value Dialog */}
      <Dialog 
        open={viewDialogOpen} 
        onClose={() => setViewDialogOpen(false)}
        maxWidth="md"
        fullWidth
        PaperProps={{
          sx: {
            borderRadius: 2,
            border: '2px solid',
            borderColor: actualMode === 'dark' ? 'rgba(249, 115, 22, 0.5)' : 'rgba(249, 115, 22, 0.4)',
            background: actualMode === 'dark'
              ? 'linear-gradient(135deg, rgba(30, 30, 30, 0.98) 0%, rgba(40, 40, 40, 0.98) 100%)'
              : 'linear-gradient(135deg, rgba(255, 255, 255, 0.98) 0%, rgba(248, 248, 248, 0.98) 100%)',
            boxShadow: actualMode === 'dark'
              ? '0 8px 32px rgba(249, 115, 22, 0.3)'
              : '0 8px 32px rgba(249, 115, 22, 0.2)',
          }
        }}
      >
        <DialogTitle
          sx={{
            background: actualMode === 'dark'
              ? 'linear-gradient(135deg, rgba(30, 30, 30, 0.5) 0%, rgba(40, 40, 40, 0.5) 100%)'
              : 'linear-gradient(135deg, rgba(248, 248, 248, 0.5) 0%, rgba(255, 255, 255, 0.5) 100%)',
            borderBottom: '2px solid',
            borderColor: actualMode === 'dark' ? 'rgba(249, 115, 22, 0.3)' : 'rgba(249, 115, 22, 0.2)',
            color: actualMode === 'dark' ? '#ffffff' : '#1f2937',
            fontWeight: 600,
            fontSize: '1.1rem',
            py: 2,
            mb: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span>{viewDialogData?.name}</span>
          {viewDialogData && (
            <Chip
              label={getValueType(viewDialogData.value)}
              size="small"
              sx={{
                fontSize: '0.7rem',
                height: '20px',
                fontWeight: 500,
                textTransform: 'uppercase',
                bgcolor: 'transparent',
                color: actualMode === 'dark' ? '#ffffff' : '#1f2937',
                border: '1px solid',
                borderColor: actualMode === 'dark' ? 'rgba(249, 115, 22, 0.4)' : 'rgba(249, 115, 22, 0.3)',
              }}
            />
          )}
        </DialogTitle>
        <DialogContent sx={{ pt: 2 }}>
          <Box
            sx={{
              background: actualMode === 'dark' 
                ? 'linear-gradient(135deg, rgba(0, 0, 0, 0.4) 0%, rgba(20, 20, 20, 0.4) 100%)'
                : 'linear-gradient(135deg, rgba(0, 0, 0, 0.05) 0%, rgba(240, 240, 240, 0.5) 100%)',
              borderRadius: 2,
              border: '1px solid',
              borderColor: actualMode === 'dark' ? 'rgba(249, 115, 22, 0.2)' : 'rgba(249, 115, 22, 0.15)',
              p: 2.5,
              color: actualMode === 'dark' ? '#ffffff' : '#1f2937',
              fontFamily: 'monospace',
              fontSize: '0.875rem',
              maxHeight: '400px',
              overflowY: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              boxShadow: actualMode === 'dark'
                ? 'inset 0 2px 8px rgba(0, 0, 0, 0.3)'
                : 'inset 0 2px 8px rgba(0, 0, 0, 0.08)',
              '&::-webkit-scrollbar': {
                width: '8px',
              },
              '&::-webkit-scrollbar-track': {
                background: actualMode === 'dark' ? 'rgba(0, 0, 0, 0.2)' : 'rgba(0, 0, 0, 0.05)',
                borderRadius: '4px',
              },
              '&::-webkit-scrollbar-thumb': {
                background: actualMode === 'dark' ? 'rgba(249, 115, 22, 0.4)' : 'rgba(249, 115, 22, 0.3)',
                borderRadius: '4px',
                '&:hover': {
                  background: actualMode === 'dark' ? 'rgba(249, 115, 22, 0.6)' : 'rgba(249, 115, 22, 0.5)',
                },
              },
            }}
          >
            {viewDialogData && (
              viewDialogData.value !== undefined
                ? (typeof viewDialogData.value === 'object'
                    ? JSON.stringify(viewDialogData.value, null, 2)
                    : String(viewDialogData.value))
                : 'No value available'
            )}
          </Box>
        </DialogContent>
        <DialogActions
          sx={{
            borderTop: '1px solid',
            borderColor: actualMode === 'dark' ? 'rgba(249, 115, 22, 0.2)' : 'rgba(249, 115, 22, 0.15)',
            px: 3,
            py: 2,
            gap: 1,
          }}
        >
          <Button 
            onClick={() => {
              if (viewDialogData && viewDialogData.value !== undefined) {
                const textToCopy = typeof viewDialogData.value === 'object'
                  ? JSON.stringify(viewDialogData.value, null, 2)
                  : String(viewDialogData.value);
                navigator.clipboard.writeText(textToCopy);
              }
            }}
            variant="outlined"
            sx={{
              borderColor: actualMode === 'dark' ? 'rgba(249, 115, 22, 0.5)' : 'rgba(249, 115, 22, 0.4)',
              color: actualMode === 'dark' ? '#ffffff' : '#1f2937',
              '&:hover': {
                borderColor: actualMode === 'dark' ? 'rgba(249, 115, 22, 0.7)' : 'rgba(249, 115, 22, 0.6)',
                backgroundColor: 'rgba(249, 115, 22, 0.1)',
              },
            }}
          >
            Copy
          </Button>
          <Button 
            onClick={() => setViewDialogOpen(false)}
            variant="outlined"
            sx={{
              borderColor: actualMode === 'dark' ? 'rgba(249, 115, 22, 0.5)' : 'rgba(249, 115, 22, 0.4)',
              color: actualMode === 'dark' ? '#ffffff' : '#1f2937',
              '&:hover': {
                borderColor: actualMode === 'dark' ? 'rgba(249, 115, 22, 0.7)' : 'rgba(249, 115, 22, 0.6)',
                backgroundColor: 'rgba(249, 115, 22, 0.1)',
              },
            }}
          >
            Close
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

