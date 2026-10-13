import { DialogTitle, DialogContent, DialogActions, Button, Typography } from '@mui/material';
import React from 'react';

import { StyledDialog } from './StyledDialog';
import { useI18n } from '../../i18n/useI18n';

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
  title,
  message,
  confirmText,
  cancelText,
  confirmColor = 'primary',
  onConfirm,
  onCancel,
  onDismiss,
}) => {
  const { t } = useI18n();
  return (
    <StyledDialog
      open={open}
      onClose={onDismiss || onCancel}
      maxWidth="xs"
      fullWidth
    >
      <DialogTitle sx={{ pb: 1 }}>{title !== undefined ? t(title) : t('Confirm Action')}</DialogTitle>
      <DialogContent>
        <Typography sx={{ whiteSpace: 'pre-line' }}>{message}</Typography>
      </DialogContent>
      <DialogActions sx={{ pt: 1, pb: 2, px: 3, gap: 1 }}>
        {onDismiss && (
          <Button onClick={onDismiss} size="small">
            {t('Cancel')}
          </Button>
        )}
        <Button onClick={onCancel} size="small" variant="outlined">
          {cancelText !== undefined ? t(cancelText) : t('Cancel')}
        </Button>
        <Button onClick={onConfirm} variant="contained" color={confirmColor} size="small">
          {confirmText !== undefined ? t(confirmText) : t('OK')}
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};

