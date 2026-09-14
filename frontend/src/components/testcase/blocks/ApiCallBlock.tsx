import React, { useState } from 'react';
import { Box, Typography, IconButton, Chip, CircularProgress, Tooltip } from '@mui/material';
import { Handle, Position, NodeProps } from 'reactflow';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import CheckIcon from '@mui/icons-material/Check';
import CloseIcon from '@mui/icons-material/Close';
import EditIcon from '@mui/icons-material/Edit';
import PublicIcon from '@mui/icons-material/Public';
import { useTheme } from '../../../contexts/ThemeContext';
import { useToastContext } from '../../../contexts/ToastContext';
import { useTestCaseBuilder } from '../../../contexts/testcase/TestCaseBuilderContext';
import { BlockExecutionState } from '../../../hooks/testcase/useExecutionState';
import { OutputDisplay } from './OutputDisplay';
import { buildServerUrl } from '../../../utils/buildUrlUtils';

/**
 * ApiCallBlock - Compact block for API calls
 * 
 * Visual Design:
 * - Icon (🌐) + Request name in header
 * - Method badge + truncated path
 * - Environment badge
 * - Simplified output display
 * 
 * Opens ApiCallConfigModal when edited
 */
export const ApiCallBlock: React.FC<NodeProps & { 
  executionState?: BlockExecutionState 
}> = ({ data, selected, dragging, id }) => {
  const executionState = data.executionState as BlockExecutionState | undefined;
  const { actualMode } = useTheme();
  const { showSuccess, showError } = useToastContext();
  const { updateBlock, nodes } = useTestCaseBuilder();
  
  // Get context data for variable substitution (future enhancement)
  const context: Record<string, any> = {};
  
  const [isExecuting, setIsExecuting] = useState(false);
  const [animateHandle, setAnimateHandle] = useState<'success' | 'failure' | null>(null);
  
  // Extract API block params
  const requestName = data.params?.request_name || 'API Call';
  const method = data.params?.method || 'GET';
  const pathPreview = data.params?.path_preview || '/...';
  const environmentName = data.params?.environment_name || '';
  
  // Determine if block is configured
  const isConfigured = Boolean(
    data.params?.workspace_id && 
    data.params?.collection_id && 
    data.params?.request_id
  );
  
  // Method color mapping
  const getMethodColor = (method: string) => {
    switch (method.toUpperCase()) {
      case 'GET': return 'success';
      case 'POST': return 'primary';
      case 'PUT': return 'warning';
      case 'DELETE': return 'error';
      case 'PATCH': return 'info';
      default: return 'default';
    }
  };
  
  // Open config modal
  const handleEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    const event = new CustomEvent('openApiBlockConfig', { detail: { blockId: id } });
    window.dispatchEvent(event);
  };
  
  // Execute API call using existing /server/postman/test endpoint
  const handleExecute = async (e: React.MouseEvent) => {
    e.stopPropagation();
    
    if (!isConfigured) {
      showError('API call not configured');
      return;
    }
    
    setIsExecuting(true);
    const startTime = Date.now();
    
    try {
      const { workspace_id, environment_id, method, path_preview, request_name } = data.params;
      
      // Call existing /server/postman/test endpoint
      const response = await fetch(buildServerUrl('/server/postman/test'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspaceId: workspace_id,
          environmentId: environment_id || undefined,
          endpoints: [{
            method: method,
            path: path_preview,
            name: request_name
          }]
        })
      });
      
      const result = await response.json();
      const duration = Date.now() - startTime;
      
      if (result.success && result.results && result.results.length > 0) {
        const apiResult = result.results[0];
        
        if (apiResult.status === 'pass') {
          // Update block outputs with response data
          if (data.blockOutputs && context) {
            const updatedOutputs = data.blockOutputs.map((output: any) => {
              if (output.name === 'response') return { ...output, value: apiResult.response };
              if (output.name === 'status_code') return { ...output, value: apiResult.statusCode };
              if (output.name === 'headers') return { ...output, value: apiResult.headers || {} };
              return output;
            });
            updateBlock(id as string, { blockOutputs: updatedOutputs });
          }
          
          setAnimateHandle('success');
          showSuccess(`✓ ${method} ${path_preview} → ${apiResult.statusCode} (${duration}ms)`);
          setTimeout(() => setAnimateHandle(null), 2000);
        } else {
          setAnimateHandle('failure');
          showError(`✗ ${method} ${path_preview}\n${apiResult.error || 'Request failed'}`);
          setTimeout(() => setAnimateHandle(null), 2000);
        }
      } else {
        throw new Error(result.error || 'API test failed');
      }
    } catch (error) {
      const duration = Date.now() - startTime;
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      setAnimateHandle('failure');
      showError(`✗ API call failed (${duration}ms)\n${errorMessage}`);
      setTimeout(() => setAnimateHandle(null), 2000);
    } finally {
      setIsExecuting(false);
    }
  };
  
  // Calculate linked outputs
  const calculateLinkedTo = (): Record<string, Array<{ targetType: 'variable' | 'output' | 'metadata' | 'input'; targetName: string }>> => {
    const linkedTo: Record<string, Array<{ targetType: 'variable' | 'output' | 'metadata' | 'input'; targetName: string }>> = {};
    
    // Check other blocks' paramLinks
    nodes?.forEach((node: any) => {
      if (node.id !== id && node.data?.paramLinks) {
        Object.entries(node.data.paramLinks).forEach(([paramKey, linkInfo]: [string, any]) => {
          if (linkInfo.sourceBlockId === id) {
            const outputName = linkInfo.sourceOutputName;
            if (!linkedTo[outputName]) linkedTo[outputName] = [];
            linkedTo[outputName].push({ 
              targetType: 'input', 
              targetName: `${node.data?.label || node.id}.${paramKey}` 
            });
          }
        });
      }
    });
    
    return linkedTo;
  };
  
  const [, setDraggedOutput] = useState<{blockId: string, outputName: string, outputType: string} | null>(null);
  
  // Get execution state styling
  const getExecutionStyling = () => {
    const state = executionState || (isExecuting ? { status: 'executing' as const } : null);
    
    if (!state) return {};
    
    switch (state.status) {
      case 'executing':
        return {
          border: '3px solid #3b82f6',
          boxShadow: '0 0 20px rgba(59, 130, 246, 0.6)',
          animation: 'executePulse 1.5s ease-in-out infinite',
        };
      case 'success':
        return {
          border: '4px solid #10b981',
          boxShadow: '0 0 15px rgba(16, 185, 129, 0.5)',
        };
      case 'failure':
        return {
          border: '4px solid #ef4444',
          boxShadow: '0 0 15px rgba(239, 68, 68, 0.5)',
        };
      case 'error':
        return {
          border: '2px solid #f59e0b',
          boxShadow: '0 0 10px rgba(245, 158, 11, 0.3)',
        };
      default:
        return {};
    }
  };
  
  // Render output handles
  const renderOutputHandles = () => {
    const outputs = ['success', 'failure'];
    
    return outputs.map((output, idx) => {
      const handleColor = output === 'success' ? '#10b981' : '#ef4444';
      const isLeft = idx === 0;
      const isAnimating = animateHandle === output;
      const isActive = executionState?.status === output;
      
      const content = output === 'success' 
        ? <CheckIcon sx={{ fontSize: isActive ? 32 : 24 }} /> 
        : <CloseIcon sx={{ fontSize: isActive ? 32 : 24 }} />;
      
      const handleHeight = isActive ? 34 : 28;
      const bottomOffset = isActive ? -36 : -32;
      
      return (
        <Handle
          key={output}
          type="source"
          position={Position.Bottom}
          id={output}
          style={{
            left: isLeft ? '0%' : '50%',
            right: isLeft ? '50%' : '0%',
            background: handleColor,
            width: 'auto',
            height: handleHeight,
            borderRadius: isLeft ? '0 0 0 4px' : '0 0 4px 0',
            borderLeft: isActive ? '4px solid white' : '2px solid white',
            borderRight: isActive ? '4px solid white' : '2px solid white',
            borderBottom: isActive ? '4px solid white' : '2px solid white',
            borderTop: 'none',
            bottom: bottomOffset,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'white',
            fontWeight: 'bold',
            fontSize: 16,
            cursor: 'pointer',
            boxShadow: isActive ? `0 0 20px ${handleColor}` : 'none',
            transition: 'all 0.3s ease',
            transform: 'none',
          }}
        >
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              pointerEvents: 'none',
              animation: isAnimating ? 'pulse 0.5s ease-in-out 3' : 'none',
              '@keyframes pulse': {
                '0%, 100%': { transform: 'scale(1)' },
                '50%': { transform: 'scale(1.2)' },
              },
            }}
          >
            {content}
          </Box>
        </Handle>
      );
    });
  };
  
  return (
    <Box
      sx={{
        width: 340,
        minHeight: 100,
        maxHeight: 280,
        border: selected ? '3px solid #fbbf24' : '2px solid #06b6d4', // cyan for API blocks
        ...getExecutionStyling(),
        borderRadius: 2,
        background: actualMode === 'dark' ? '#1f2937' : '#ffffff',
        boxShadow: 2,
        cursor: 'pointer',
        opacity: dragging ? 0.5 : 1,
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'visible',
      }}
    >
      {/* Duration Badge */}
      {executionState?.duration !== undefined && ['success', 'failure', 'error'].includes(executionState.status) && (
        <Box
          sx={{
            position: 'absolute',
            top: -28,
            right: 0,
            zIndex: 10,
            backgroundColor: 
              executionState.status === 'success' ? '#10b981' :
              executionState.status === 'failure' ? '#ef4444' : '#f59e0b',
            color: 'white',
            borderRadius: 1,
            px: 1,
            py: 0.5,
            fontSize: 18,
            fontWeight: 'bold',
            fontFamily: 'monospace',
          }}
        >
          {(executionState.duration / 1000).toFixed(2)}s
        </Box>
      )}
      
      {/* Header with Icon */}
      <Box
        sx={{
          background: '#06b6d4', // cyan
          p: 1,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          justifyContent: 'space-between',
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: 1 }}>
          <PublicIcon sx={{ color: 'white', fontSize: 20 }} />
          <Typography 
            color="white" 
            fontWeight="bold" 
            fontSize={16}
            sx={{ 
              flex: 1,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap'
            }}
          >
            {data.label || requestName}
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <IconButton
            size="small"
            onClick={handleEdit}
            sx={{
              color: 'white',
              padding: '4px',
              '&:hover': {
                backgroundColor: 'rgba(255, 255, 255, 0.2)',
              },
            }}
          >
            <EditIcon fontSize="small" />
          </IconButton>
          {isConfigured && (
            <Tooltip title="Execute API call">
              <IconButton
                size="small"
                onClick={handleExecute}
                disabled={isExecuting}
                sx={{
                  color: 'white',
                  padding: '4px',
                  '&:hover': {
                    backgroundColor: 'rgba(255, 255, 255, 0.2)',
                  },
                }}
              >
                {isExecuting ? <CircularProgress size={16} sx={{ color: 'white' }} /> : <PlayArrowIcon fontSize="small" />}
              </IconButton>
            </Tooltip>
          )}
        </Box>
      </Box>
      
      {/* Content - Compact API Info */}
      <Box sx={{ p: 1.5, flex: 1, overflowY: 'auto' }}>
        {isConfigured ? (
          <>
            {/* Method + Path */}
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <Chip
                label={method}
                size="small"
                color={getMethodColor(method)}
                sx={{ 
                  fontFamily: 'monospace', 
                  fontSize: '0.7rem',
                  fontWeight: 600,
                  minWidth: 50,
                  height: 22
                }}
              />
              <Typography 
                fontSize={13} 
                fontFamily="monospace"
                sx={{ 
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  flex: 1
                }}
              >
                {pathPreview}
              </Typography>
            </Box>
            
            {/* Environment Badge */}
            {environmentName && (
              <Chip
                label={environmentName}
                size="small"
                variant="outlined"
                sx={{ fontSize: '0.65rem', height: 20, mb: 1 }}
              />
            )}
            
            {/* Output Display */}
            <OutputDisplay
              blockOutputs={data.blockOutputs}
              blockId={id as string}
              linkedTo={calculateLinkedTo()}
              onDragStart={(dragData) => setDraggedOutput(dragData)}
              onDragEnd={() => setDraggedOutput(null)}
            />
          </>
        ) : (
          <Typography fontSize={12} color="text.secondary">
            Click edit icon to configure API call
          </Typography>
        )}
      </Box>
      
      {/* Input Handle */}
      <Handle
        type="target"
        position={Position.Top}
        id="input"
        style={{
          background: '#06b6d4',
          width: 20,
          height: 20,
          borderRadius: '50%',
          border: '2px solid white',
          top: -10,
        }}
      />
      
      {/* Output Handles */}
      {renderOutputHandles()}
    </Box>
  );
};

