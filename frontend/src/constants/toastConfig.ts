/**
 * Centralized Toast/Snackbar Configuration
 * 
 * Use these constants to ensure consistent positioning across the app.
 * All toasts will appear in the same location (top-left, below header).
 * 
 * Usage example:
 * ```tsx
 * import { TOAST_POSITION, TOAST_AUTO_HIDE_DURATION } from '../constants/toastConfig';
 * 
 * <Snackbar
 *   open={open}
 *   autoHideDuration={TOAST_AUTO_HIDE_DURATION.success}
 *   onClose={handleClose}
 *   anchorOrigin={TOAST_POSITION.anchorOrigin}
 *   sx={TOAST_POSITION.sx}
 * >
 *   <Alert severity="success">Success message</Alert>
 * </Snackbar>
 * ```
 */

export const TOAST_POSITION = {
  anchorOrigin: { 
    vertical: 'top' as const, 
    horizontal: 'left' as const 
  },
  sx: {
    top: '110px !important', // Below header (header is ~60px)
    left: '45% !important',
  },
};

export const TOAST_AUTO_HIDE_DURATION = {
  success: 3000,
  error: 4000,
  info: 4000,
  warning: 4000,
};

