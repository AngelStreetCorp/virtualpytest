'use client';

import {
  DialogTitle,
  DialogContent,
  Typography,
  Box,
  LinearProgress,
  Chip,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import React from 'react';

import { StyledDialog } from '../common/StyledDialog';
import { useValidation } from '../../hooks/validation';

interface ValidationProgressClientProps {
  treeId: string;
  selectedHost?: any;
  selectedDeviceId?: string | null;
}

export const ValidationProgressClient: React.FC<ValidationProgressClientProps> = ({
  treeId,
  selectedHost,
  selectedDeviceId,
}) => {
  const validation = useValidation(treeId, selectedHost, selectedDeviceId);

  // Only show progress dialog when validation is running
  if (!validation.isValidating) {
    return null;
  }

  const { progress, currentMessage, currentStep, totalSteps, recentSteps } = validation;
  const hasProgress = typeof progress === 'number';
  const stepLabel =
    currentStep != null && totalSteps != null
      ? `Step ${currentStep} / ${totalSteps}`
      : totalSteps != null
        ? `0 / ${totalSteps}`
        : 'Preparing…';

  return (
    <StyledDialog open={validation.isValidating} disableEscapeKeyDown maxWidth="sm" fullWidth>
      <DialogTitle>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography variant="h6">Running Validation</Typography>
          <Chip label="In Progress" color="primary" size="small" variant="outlined" />
        </Box>
      </DialogTitle>

      <DialogContent>
        <Box sx={{ py: 1, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
              <Typography variant="subtitle2">{stepLabel}</Typography>
              {hasProgress && (
                <Typography variant="subtitle2" color="text.secondary">
                  {Math.round(progress as number)}%
                </Typography>
              )}
            </Box>
            <LinearProgress
              variant={hasProgress ? 'determinate' : 'indeterminate'}
              value={hasProgress ? (progress as number) : undefined}
            />
          </Box>

          <Typography variant="body2" color="text.primary">
            {currentMessage || 'Waiting for the first transition…'}
          </Typography>

          {recentSteps && recentSteps.length > 0 && (
            <Box>
              <Typography variant="caption" color="text.secondary">
                Recent steps
              </Typography>
              <List dense disablePadding>
                {recentSteps.map((step, idx) => (
                  <ListItem key={`${step.from_node}-${step.to_node}-${idx}`} disableGutters sx={{ py: 0.25 }}>
                    <ListItemIcon sx={{ minWidth: 28 }}>
                      {step.success ? (
                        <CheckCircleIcon fontSize="small" color="success" />
                      ) : (
                        <CancelIcon fontSize="small" color="error" />
                      )}
                    </ListItemIcon>
                    <ListItemText
                      primary={`${step.from_node} → ${step.to_node}`}
                      secondary={!step.success && step.error ? step.error : undefined}
                      primaryTypographyProps={{ variant: 'body2' }}
                      secondaryTypographyProps={{ variant: 'caption', color: 'error' }}
                    />
                  </ListItem>
                ))}
              </List>
            </Box>
          )}
        </Box>
      </DialogContent>
    </StyledDialog>
  );
};

export default ValidationProgressClient;
