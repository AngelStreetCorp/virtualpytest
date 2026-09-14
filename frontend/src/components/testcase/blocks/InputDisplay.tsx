/**
 * InputDisplay Component
 * 
 * Universal component to display block input parameters
 * Works for: action, verification, navigation, standard blocks
 */

import React, { useState } from 'react';
import { Box, Typography, Chip, Collapse, IconButton, Tooltip } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import LinkIcon from '@mui/icons-material/Link';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import { useTheme } from '../../../contexts/ThemeContext';

// Metadata fields to hide from parameter display
const HIDDEN_METADATA_FIELDS = ['description', 'default', 'required', 'optional', 'placeholder', 'hidden'];

// Commands that dump entire device - don't need area parameter
const DUMP_COMMANDS = ['getMenuInfo', 'dumpWindowHierarchy', 'dumpUI', 'getUIElements'];

interface InputDisplayProps {
  params?: Record<string, any>;
  paramLinks?: Record<string, {
    sourceBlockId: string;
    sourceOutputName: string;
    sourceOutputType: string;
  }>;
  onDrop?: (paramKey: string, dragData: { blockId: string; outputName: string; outputType: string }) => void;
  onUnlink?: (paramKey: string) => void;
  draggedOutput?: { blockId: string; outputName: string; outputType: string } | null;
  command?: string; // ✅ Add command to know which params to hide
  onConfigureClick?: () => void; // ✅ NEW: Callback to open config dialog
}

export const InputDisplay: React.FC<InputDisplayProps> = ({
  params,
  paramLinks,
  onDrop,
  onUnlink,
  draggedOutput,
  command,
  onConfigureClick, // ✅ NEW
}) => {
  // ✅ ALWAYS call hooks at the top level - before any early returns
  const { actualMode } = useTheme();
  const [expanded, setExpanded] = useState(false);
  const [copiedParam, setCopiedParam] = useState<string | null>(null);

  // Filter out metadata fields and command-specific hidden params
  const isDumpCommand = command && DUMP_COMMANDS.includes(command);
  const displayParams = params 
    ? Object.entries(params).filter(([key]) => {
        // Always hide metadata fields
        if (HIDDEN_METADATA_FIELDS.includes(key)) return false;
        
        // Hide 'area' for dump commands (they scan the entire device)
        if (isDumpCommand && key === 'area') return false;
        
        return true;
      })
    : [];

  // Early return AFTER all hooks
  if (displayParams.length === 0) {
    return null;
  }

  const handleCopyParam = (key: string, value: any, e: React.MouseEvent) => {
    e.stopPropagation();
    const textToCopy = `${key}: ${typeof value === 'object' ? JSON.stringify(value) : String(value)}`;
    navigator.clipboard.writeText(textToCopy);
    setCopiedParam(key);
    setTimeout(() => setCopiedParam(null), 2000);
  };

  return (
    <Box sx={{ mb: 1 }} onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
      <Box
        onClick={() => setExpanded(!expanded)}
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 0.5,
          cursor: 'pointer',
          py: 0.5,
          px: 1,
          background: actualMode === 'dark' 
            ? 'linear-gradient(135deg, rgba(139, 92, 246, 0.15) 0%, rgba(139, 92, 246, 0.08) 100%)'
            : 'linear-gradient(135deg, rgba(139, 92, 246, 0.12) 0%, rgba(139, 92, 246, 0.06) 100%)',
          borderRadius: 1,
          border: '2px solid',
          borderColor: actualMode === 'dark' ? 'rgba(139, 92, 246, 0.4)' : 'rgba(139, 92, 246, 0.3)',
          boxShadow: actualMode === 'dark'
            ? '0 2px 8px rgba(139, 92, 246, 0.15), inset 0 1px 0 rgba(255, 255, 255, 0.1)'
            : '0 2px 8px rgba(139, 92, 246, 0.1), inset 0 1px 0 rgba(255, 255, 255, 0.5)',
          transition: 'all 0.2s ease-in-out',
          '&:hover': {
            bgcolor: actualMode === 'dark' ? 'rgba(139, 92, 246, 0.2)' : 'rgba(139, 92, 246, 0.15)',
            borderColor: actualMode === 'dark' ? 'rgba(139, 92, 246, 0.6)' : 'rgba(139, 92, 246, 0.5)',
            boxShadow: actualMode === 'dark'
              ? '0 4px 12px rgba(139, 92, 246, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.15)'
              : '0 4px 12px rgba(139, 92, 246, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.6)',
            transform: 'translateY(-1px)',
          },
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flex: 1, minWidth: 0 }}>
          <Typography fontSize={13} fontWeight="bold" color="#8b5cf6" sx={{ flexShrink: 0 }}>
            Inputs ({displayParams.length})
          </Typography>
        </Box>
        {expanded ? <ExpandLessIcon sx={{ fontSize: 16, color: '#8b5cf6', flexShrink: 0 }} /> : <ExpandMoreIcon sx={{ fontSize: 16, color: '#8b5cf6', flexShrink: 0 }} />}
      </Box>
      
      <Collapse in={expanded}>
        <Box sx={{ mt: 0.5, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          {displayParams.map(([key, value]) => {
            const link = paramLinks?.[key];
            const isLinked = Boolean(link);
            
            // Extract actual value from object structure
            let actualValue = value;
            if (typeof value === 'object' && value !== null) {
              actualValue = (value as any).value !== undefined ? (value as any).value : value;
              
              if (typeof actualValue === 'object' && actualValue !== null) {
                const filtered: Record<string, any> = {};
                Object.entries(actualValue).forEach(([k, v]) => {
                  if (!HIDDEN_METADATA_FIELDS.includes(k)) {
                    filtered[k] = v;
                  }
                });
                if (Object.keys(filtered).length === 0 && (value as any).value !== undefined) {
                  actualValue = (value as any).value;
                } else {
                  actualValue = filtered;
                }
              }
            }
            
            const displayValue = typeof actualValue === 'object' 
              ? JSON.stringify(actualValue) 
              : String(actualValue);
            
            return (
              <Box 
                key={key} 
                sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}
                onDragOver={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  if (draggedOutput && onDrop) {
                    onDrop(key, draggedOutput);
                  }
                }}
              >
                <Chip
                  label={isLinked && link
                    ? `${key} ← ${link.sourceOutputName}` 
                    : `${key}: ${displayValue.substring(0, 30)}${displayValue.length > 30 ? '...' : ''}`
                  }
                  size="small"
                  icon={isLinked ? <LinkIcon sx={{ fontSize: 12, color: '#10b981' }} /> : undefined}
                  onClick={(e) => {
                    e.stopPropagation(); // ✅ Prevent block selection
                    console.log('[@InputDisplay] Chip clicked:', { key, isLinked, onConfigureClick: !!onConfigureClick });
                    if (!isLinked && onConfigureClick) {
                      // ✅ Open config dialog for editing parameters
                      console.log('[@InputDisplay] Calling onConfigureClick');
                      onConfigureClick();
                    }
                  }}
                  onDelete={isLinked && onUnlink ? () => onUnlink(key) : undefined}
                  sx={{ 
                    fontSize: 16, 
                    height: 26,
                    flex: 1,
                    bgcolor: isLinked 
                      ? (actualMode === 'dark' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(16, 185, 129, 0.1)')
                      : (actualMode === 'dark' ? 'rgba(139, 92, 246, 0.1)' : 'rgba(139, 92, 246, 0.08)'),
                    borderColor: isLinked ? '#10b981' : '#8b5cf6',
                    cursor: 'pointer',
                    '&:hover': {
                      bgcolor: isLinked
                        ? (actualMode === 'dark' ? 'rgba(16, 185, 129, 0.25)' : 'rgba(16, 185, 129, 0.2)')
                        : (actualMode === 'dark' ? 'rgba(139, 92, 246, 0.2)' : 'rgba(139, 92, 246, 0.15)'),
                    }
                  }}
                  variant="outlined"
                />
                
                <Tooltip title={copiedParam === key ? "Copied!" : "Copy value"}>
                  <IconButton
                    size="small"
                    onClick={(e) => handleCopyParam(key, actualValue, e)}
                    sx={{
                      padding: '2px',
                      color: copiedParam === key ? '#10b981' : '#8b5cf6',
                      '&:hover': {
                        backgroundColor: 'rgba(139, 92, 246, 0.1)',
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
    </Box>
  );
};

