import { useToastContext } from '../contexts/ToastContext';

/**
 * Custom hook for toast notifications
 * Provides easy access to toast functions with predefined colors:
 * - Error / Warning / Success: the palette's status colours
 * - Info: the gold accent (no blue, UI_STYLE §2)
 */
export const useToast = () => {
  return useToastContext();
};

export default useToast;
