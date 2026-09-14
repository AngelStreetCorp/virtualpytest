import { useState, useCallback } from 'react';

interface ConfirmDialogState {
  open: boolean;
  title: string;
  message: string;
  confirmText: string;
  cancelText: string;
  confirmColor: 'primary' | 'error' | 'warning' | 'info' | 'success';
  onConfirm: () => void;
  onCancel?: () => void;
  /** When set, a separate "Cancel" dismiss button is shown alongside the cancel action button. */
  showDismiss?: boolean;
}

const DEFAULT_STATE: ConfirmDialogState = {
  open: false,
  title: 'Confirm Action',
  message: '',
  confirmText: 'OK',
  cancelText: 'Cancel',
  confirmColor: 'primary',
  onConfirm: () => {},
};

/**
 * Hook to manage confirmation dialog state
 * Provides a replacement for window.confirm() with Material-UI styling
 * 
 * Usage:
 * ```tsx
 * const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();
 * 
 * // In your component JSX:
 * <ConfirmDialog
 *   open={dialogState.open}
 *   title={dialogState.title}
 *   message={dialogState.message}
 *   confirmText={dialogState.confirmText}
 *   cancelText={dialogState.cancelText}
 *   confirmColor={dialogState.confirmColor}
 *   onConfirm={handleConfirm}
 *   onCancel={handleCancel}
 * />
 * 
 * // To show the dialog:
 * confirm({
 *   title: 'Delete Item',
 *   message: 'Are you sure you want to delete this item?',
 *   confirmColor: 'error',
 *   onConfirm: () => deleteItem(id)
 * });
 * ```
 */
export const useConfirmDialog = () => {
  const [dialogState, setDialogState] = useState<ConfirmDialogState>(DEFAULT_STATE);

  const confirm = useCallback((options: {
    title?: string;
    message: string;
    confirmText?: string;
    cancelText?: string;
    confirmColor?: 'primary' | 'error' | 'warning' | 'info' | 'success';
    onConfirm: () => void;
    onCancel?: () => void;
    showDismiss?: boolean;
  }) => {
    setDialogState({
      open: true,
      title: options.title || 'Confirm Action',
      message: options.message,
      confirmText: options.confirmText || 'OK',
      cancelText: options.cancelText || 'Cancel',
      confirmColor: options.confirmColor || 'primary',
      onConfirm: options.onConfirm,
      onCancel: options.onCancel,
      showDismiss: options.showDismiss,
    });
  }, []);

  // On close, only flip `open` to false — keep the title/message intact so the
  // dialog doesn't flash the default "Confirm Action" content while MUI plays
  // its close transition (content stays mounted during the fade-out).
  const handleConfirm = useCallback(() => {
    dialogState.onConfirm();
    setDialogState((prev) => ({ ...prev, open: false }));
  }, [dialogState]);

  const handleCancel = useCallback(() => {
    if (dialogState.onCancel) {
      dialogState.onCancel();
    }
    setDialogState((prev) => ({ ...prev, open: false }));
  }, [dialogState]);

  const handleDismiss = useCallback(() => {
    setDialogState((prev) => ({ ...prev, open: false }));
  }, []);

  return {
    dialogState,
    confirm,
    handleConfirm,
    handleCancel,
    handleDismiss,
  };
};

