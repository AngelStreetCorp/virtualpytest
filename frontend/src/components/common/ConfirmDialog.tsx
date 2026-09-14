import { DialogTitle, DialogContent, DialogActions, Button, Typography } from '@mui/material';
import React from 'react';

import { StyledDialog } from './StyledDialog';

interface ConfirmDialogProps {
  open: boolean;
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  confirmColor?: 'primary' | 'error' | 'warning' | 'info' | 'success';
  onConfirm: () => void;
  onCancel: () => void;
  /** Optional dismiss handler — shown as a separate "Cancel" button when onCancel has a different action (e.g., "Run on N Available"). */
  onDismiss?: () => void;
}

/**
 * Reusable confirmation dialog component
 * Replaces window.confirm() with a Material-UI dialog
 */
export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  open,
  title = 'Confirm Action',
  message,
  confirmText = 'OK',
  cancelText = 'Cancel',
  confirmColor = 'primary',
  onConfirm,
  onCancel,
  onDismiss,
}) => {
  return (
    <StyledDialog
      open={open}
      onClose={onDismiss || onCancel}
      maxWidth="xs"
      fullWidth
    >
      <DialogTitle sx={{ pb: 1 }}>{title}</DialogTitle>
      <DialogContent>
        <Typography sx={{ whiteSpace: 'pre-line' }}>{message}</Typography>
      </DialogContent>
      <DialogActions sx={{ pt: 1, pb: 2, px: 3, gap: 1 }}>
        {onDismiss && (
          <Button onClick={onDismiss} size="small">
            Cancel
          </Button>
        )}
        <Button onClick={onCancel} size="small" variant="outlined">
          {cancelText}
        </Button>
        <Button onClick={onConfirm} variant="contained" color={confirmColor} size="small">
          {confirmText}
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};

