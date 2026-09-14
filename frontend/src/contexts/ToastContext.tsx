import React, { createContext, useContext, ReactNode, useEffect, useCallback } from 'react';
import toast, { Toaster } from 'react-hot-toast';

// Toast configuration with predefined colors
const TOAST_COLORS = {
  error: '#ef4444', // Red
  warning: '#f97316', // Orange
  success: '#22c55e', // Green
  info: '#3b82f6', // Blue
} as const;

// Toast context interface
interface ToastContextType {
  // `id` lets callers dedupe a toast: repeated calls with the same id replace
  // the existing toast instead of stacking a new one (react-hot-toast behavior).
  showError: (message: string, options?: { duration?: number; id?: string }) => void;
  showWarning: (message: string, options?: { duration?: number; id?: string }) => void;
  showSuccess: (message: string, options?: { duration?: number; id?: string }) => void;
  showInfo: (message: string, options?: { duration?: number; id?: string }) => void;
}

// Create context
const ToastContext = createContext<ToastContextType | undefined>(undefined);

const getBaseToastStyle = () => ({
  width: 'fit-content',
  maxWidth: 'min(92vw, 900px)',
  whiteSpace: 'nowrap' as const,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  fontSize: '14px',
  fontWeight: '500',
  padding: '12px 16px',
  borderRadius: '8px',
  boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
});

// Toast provider component
export const ToastProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const showError = useCallback((message: string, options?: { duration?: number; id?: string }) => {
    toast.error(message, {
      id: options?.id,
      duration: options?.duration || 4000,
      style: {
        ...getBaseToastStyle(),
        background: '#fef2f2',
        color: TOAST_COLORS.error,
        border: `1px solid ${TOAST_COLORS.error}`,
      },
      iconTheme: {
        primary: TOAST_COLORS.error,
        secondary: '#fef2f2',
      },
    });
  }, []);

  const showWarning = useCallback((message: string, options?: { duration?: number; id?: string }) => {
    toast(message, {
      id: options?.id,
      duration: options?.duration || 4000,
      icon: '⚠️',
      style: {
        ...getBaseToastStyle(),
        background: '#fffbeb',
        color: TOAST_COLORS.warning,
        border: `1px solid ${TOAST_COLORS.warning}`,
      },
    });
  }, []);

  const showSuccess = useCallback((message: string, options?: { duration?: number; id?: string }) => {
    toast.success(message, {
      id: options?.id,
      duration: options?.duration || 3000,
      style: {
        ...getBaseToastStyle(),
        background: '#f0fdf4',
        color: TOAST_COLORS.success,
        border: `1px solid ${TOAST_COLORS.success}`,
      },
      iconTheme: {
        primary: TOAST_COLORS.success,
        secondary: '#f0fdf4',
      },
    });
  }, []);

  const showInfo = useCallback((message: string, options?: { duration?: number; id?: string }) => {
    toast(message, {
      id: options?.id,
      duration: options?.duration || 3000,
      icon: 'ℹ️',
      style: {
        ...getBaseToastStyle(),
        background: '#eff6ff',
        color: TOAST_COLORS.info,
        border: `1px solid ${TOAST_COLORS.info}`,
      },
    });
  }, []);

  // Generic show function for AI integration
  const showToast = useCallback((message: string, severity: 'info' | 'success' | 'warning' | 'error') => {
    switch (severity) {
      case 'error': showError(message); break;
      case 'warning': showWarning(message); break;
      case 'success': showSuccess(message); break;
      default: showInfo(message);
    }
  }, [showError, showWarning, showSuccess, showInfo]);

  // Listen for AI toast events
  useEffect(() => {
    const handleAIToast = (e: CustomEvent<{ message: string; severity: string }>) => {
      console.log('🤖 AI Toast:', e.detail);
      showToast(e.detail.message, e.detail.severity as any);
    };

    window.addEventListener('ai-toast', handleAIToast as EventListener);
    return () => window.removeEventListener('ai-toast', handleAIToast as EventListener);
  }, [showToast]);

  const contextValue: ToastContextType = {
    showError,
    showWarning,
    showSuccess,
    showInfo,
  };

  return (
    <ToastContext.Provider value={contextValue}>
      {children}
      <Toaster
        position="top-right"
        reverseOrder={false}
        gutter={8}
        containerClassName=""
        containerStyle={{}}
        toastOptions={{
          className: '',
          duration: 4000,
          style: {
            ...getBaseToastStyle(),
            background: '#fff',
            color: '#363636',
          },
        }}
      />
    </ToastContext.Provider>
  );
};

// Custom hook to use toast context
export const useToastContext = (): ToastContextType => {
  const context = useContext(ToastContext);
  if (context === undefined) {
    throw new Error('useToastContext must be used within a ToastProvider');
  }
  return context;
};

export default ToastProvider;
