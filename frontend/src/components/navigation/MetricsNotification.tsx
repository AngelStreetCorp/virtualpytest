/**
 * Minimalist Metrics Notification Component
 * Small toast at bottom right - click to view details
 */

import React, { useState } from 'react';
import { Snackbar, Alert, Box, IconButton, Tooltip, Fab } from '@mui/material';
import { Warning, Error, Close } from '@mui/icons-material';

import { MetricsNotificationData } from '../../types/navigation/Metrics_Types';

export interface MetricsNotificationProps {
  notificationData: MetricsNotificationData;
  onViewDetails: () => void;
  onClose?: () => void;
  autoHideDuration?: number;
}

export const MetricsNotification: React.FC<MetricsNotificationProps> = ({
  notificationData,
  onViewDetails,
  autoHideDuration = 6000, // 6 seconds
}) => {
  const [isMinimized, setIsMinimized] = useState(false);

  if (!notificationData.show) {
    return null;
  }

  const handleClick = () => {
    // Click on toast opens modal
    onViewDetails();
  };

  const handleMinimize = (event: React.MouseEvent) => {
    event.stopPropagation(); // Prevent triggering the main click handler
    setIsMinimized(true);
  };

  const handleRestore = () => {
    setIsMinimized(false);
  };


  const getIcon = () => {
    switch (notificationData.severity) {
      case 'error':
        return <Error fontSize="small" />;
      case 'warning':
        return <Warning fontSize="small" />;
      default:
        return null;
    }
  };


  // Show minimized icon if minimized
  if (isMinimized) {
    return (
      <Tooltip title="Click to restore notification" placement="left">
        <Fab
          size="small"
          color={notificationData.severity === 'error' ? 'error' : 'warning'}
          onClick={handleRestore}
          sx={{
            position: 'fixed',
            bottom: 20,
            right: 20,
            zIndex: 1400,
            width: 40,
            height: 40,
            '&:hover': {
              transform: 'scale(1.1)',
            },
            transition: 'all 0.2s ease-in-out',
          }}
        >
          {getIcon()}
        </Fab>
      </Tooltip>
    );
  }

  // Show full toast
  return (
    <Snackbar
      open={notificationData.show && !isMinimized}
      autoHideDuration={autoHideDuration}
      onClose={() => setIsMinimized(true)}
      anchorOrigin={{ 
        vertical: 'bottom', 
        horizontal: 'right' 
      }}
      sx={{
        marginBottom: '20px',
        marginRight: '20px',
        zIndex: 1400,
      }}
    >
      <Alert
        severity={notificationData.severity}
        onClick={handleClick}
        icon={getIcon()}
        sx={{
          cursor: 'pointer',
          // Single-line layout: let the alert grow to fit Score + Pass + runs +
          // below-90 on one row instead of wrapping inside a 280px cap.
          minWidth: '200px',
          maxWidth: 'none',
          width: 'max-content',
          whiteSpace: 'nowrap',
          fontSize: '0.8rem',
          padding: '4px 12px',
          '& .MuiAlert-message': {
            padding: '4px 0',
            fontSize: '0.8rem',
          },
          '& .MuiAlert-icon': {
            padding: '4px 0',
            marginRight: '8px',
          },
          '& .MuiAlert-action': {
            padding: '0',
            marginRight: '0',
          },
          '&:hover': {
            transform: 'scale(1.02)',
            boxShadow: (theme) => theme.shadows[4],
          },
          transition: 'all 0.2s ease-in-out',
          borderRadius: '8px',
        }}
      >
        <Box sx={{ 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'space-between',
          width: '100%'
        }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: 1 }}>
            {/* Confidence Score - Emphasized */}
            <Tooltip title="Tree confidence score (0–10). Weighted average of node + edge confidence." placement="top">
              <Box sx={{
                fontSize: '0.75rem',
                fontWeight: 'bold',
                color: notificationData.severity === 'error' ? '#ef4444' : '#f59e0b',
                padding: '2px 6px',
                borderRadius: '4px',
                backgroundColor: 'rgba(255,255,255,0.2)',
                border: '1px solid rgba(255,255,255,0.3)',
                whiteSpace: 'nowrap',
              }}>
                Score {Math.round(notificationData.global_confidence * 10)}/10
              </Box>
            </Tooltip>

            {/* Pass rate, run volume, low-confidence count — explicitly labelled
                so the toast is readable without needing to open the modal. */}
            <Box sx={{ fontSize: '0.75rem', fontWeight: 400, opacity: 0.9 }}>
              Pass {notificationData.global_success_rate
                ? `${(notificationData.global_success_rate * 100).toFixed(0)}%`
                : '0%'}
              {notificationData.total_volume && notificationData.total_volume > 0
                ? ` · ${notificationData.total_volume} runs`
                : ''}
              {' · '}{notificationData.low_confidence_count} below 90%
            </Box>
          </Box>
          
          {/* Close/Minimize button */}
          <Tooltip title="Minimize" placement="top">
            <IconButton
              size="small"
              onClick={handleMinimize}
              sx={{
                padding: '2px',
                marginLeft: '8px',
                opacity: 0.7,
                '&:hover': {
                  opacity: 1,
                  backgroundColor: 'rgba(255, 255, 255, 0.1)',
                },
              }}
            >
              <Close fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      </Alert>
    </Snackbar>
  );
};
