import React from 'react';
import { Box, Typography, IconButton, LinearProgress, Divider, Stack } from '@mui/material';
import { 
  Close as CloseIcon, 
  SmartToy as RobotIcon,
  CheckCircleOutline,
  RadioButtonUnchecked,
  ErrorOutline
} from '@mui/icons-material';
import { useAIContext } from '../../../contexts/AIContext';

export const AgentPilotPanel: React.FC = () => {
  const { activeTask, isProcessing, executionSteps, togglePilot, isConnected } = useAIContext();

  const getStepIcon = (status: string) => {
    switch (status) {
      case 'done':
        return <CheckCircleOutline color="success" fontSize="small" />;
      case 'active':
        return <RadioButtonUnchecked color="primary" fontSize="small" sx={{ animation: 'pulse 1s infinite' }} />;
      case 'error':
        return <ErrorOutline color="error" fontSize="small" />;
      default:
        return <RadioButtonUnchecked color="disabled" fontSize="small" />;
    }
  };

  // Truncate long details
  const truncateDetail = (detail: string, maxLen = 120) => {
    if (detail.length <= maxLen) return detail;
    return detail.slice(0, maxLen) + '...';
  };

  return (
    <Box
      sx={{
        position: 'fixed',
        top: 64,
        right: 0,
        bottom: 0,
        width: 320,
        bgcolor: 'background.paper',
        borderLeft: '1px solid',
        borderColor: 'divider',
        boxShadow: '-4px 0 20px rgba(0,0,0,0.1)',
        zIndex: 1200,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden', // No scroll on outer container
        '@keyframes pulse': {
          '0%, 100%': { opacity: 1 },
          '50%': { opacity: 0.5 },
        },
      }}
    >
      {/* Header - Fixed */}
      <Box sx={{ 
        p: 2, 
        display: 'flex', 
        alignItems: 'center', 
        borderBottom: '1px solid', 
        borderColor: 'divider', 
        bgcolor: 'action.hover',
        flexShrink: 0
      }}>
        <RobotIcon sx={{ mr: 1, color: isConnected ? 'success.main' : 'text.disabled' }} />
        <Typography variant="subtitle1" fontWeight="bold" sx={{ flex: 1 }}>
          Agent Pilot
        </Typography>
        <IconButton size="small" onClick={togglePilot}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      {/* Task Status - Fixed */}
      <Box sx={{ p: 2, flexShrink: 0 }}>
        <Typography variant="caption" color="text.secondary" fontWeight="bold" sx={{ textTransform: 'uppercase' }}>
          Current Mission
        </Typography>
        <Typography variant="body2" sx={{ mt: 0.5, mb: 1, fontWeight: 500 }}>
          {activeTask || "Waiting for instructions..."}
        </Typography>
        
        {isProcessing && (
          <LinearProgress sx={{ borderRadius: 1, height: 4 }} />
        )}
      </Box>

      <Divider />

      {/* Execution Steps - ONLY this area scrolls */}
      <Box 
        sx={{ 
          flex: 1, 
          overflowY: 'auto', 
          overflowX: 'hidden',
          p: 2,
          '&::-webkit-scrollbar': { width: 6 },
          '&::-webkit-scrollbar-thumb': { bgcolor: 'divider', borderRadius: 3 },
        }}
      >
        {executionSteps.length === 0 && !activeTask && (
          <Typography variant="caption" color="text.secondary" sx={{ textAlign: 'center', display: 'block', py: 4 }}>
            Use Cmd+K to start a task
          </Typography>
        )}
        
        <Stack spacing={1.5}>
          {executionSteps.map((step) => (
            <Box key={step.id} sx={{ display: 'flex', gap: 1.5, alignItems: 'flex-start' }}>
              <Box sx={{ pt: 0.25, flexShrink: 0 }}>
                {getStepIcon(step.status)}
              </Box>
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Typography variant="body2" fontWeight={500}>{step.label}</Typography>
                {step.detail && (
                  <Typography 
                    variant="caption" 
                    color="text.secondary"
                    component="div"
                    sx={{ 
                      wordBreak: 'break-word',
                      lineHeight: 1.4,
                      mt: 0.25
                    }}
                  >
                    {truncateDetail(step.detail)}
                  </Typography>
                )}
              </Box>
            </Box>
          ))}
        </Stack>
      </Box>
    </Box>
  );
};
