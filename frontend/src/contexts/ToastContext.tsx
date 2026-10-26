import React, { createContext, useContext, ReactNode, useEffect, useCallback } from 'react';
import toast, { Toaster } from 'react-hot-toast';
import { Box } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { notificationStore, notify, registerToastRenderer, type NotificationCategory, type NotificationScope, type NotificationSeverity } from './notificationStore';
import { DigestToastBody } from '../components/notifications/DigestToastBody';
import { DIGEST_TOAST_ID, type DigestSelection } from '../components/notifications/notificationDigestLogic';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { pillToastStyle, TOAST_PILL } from '../constants/toastStyle';
import { TYPOGRAPHY } from '../constants/typography';
import { useI18n } from '../i18n/useI18n';

// Toast configuration with predefined colors

/** A toast's click target: `to` is an in-app path, `onClick` runs instead. The label is the button text. */
export interface ToastAction {
  label: string;
  to?: string;
  onClick?: () => void;
}

export interface ToastOptions {
  duration?: number;
  /** Dedupes the toast, and (TASK-142) also writes it to the notification history under this id. */
  id?: string;
  action?: ToastAction;
  /** Notification category (TASK-145). Default `action`: an error from something the user just did. */
  category?: NotificationCategory;
  /** Page that shows the cause, for the bell entry. Default: the toast action's `to`, else the current page. */
  to?: string;
  scope?: NotificationScope;
}

// Toast context interface
interface ToastContextType {
  showError: (message: string, options?: ToastOptions) => void;
  showWarning: (message: string, options?: ToastOptions) => void;
  showSuccess: (message: string, options?: ToastOptions) => void;
  showInfo: (message: string, options?: ToastOptions) => void;
  /** TASK-166: the 24 h digest — one small pill, with the problems behind a caret. */
  showDigest: (selection: DigestSelection) => void;
}

/** Toast body: the whole text is clickable and keyboard reachable when the toast has an action. */
const ToastBody: React.FC<{ message: string; action: ToastAction; toastId: string; notifId?: string }> = ({ message, action, toastId, notifId }) => {
  const P = useAgentChatPalette();
  const navigate = useNavigate();
  const { t } = useI18n();
  const run = () => {
    if (notifId) notificationStore.markRead(notifId);
    toast.dismiss(toastId);
    if (action.onClick) action.onClick();
    else if (action.to) navigate(action.to);
  };
  // Skip = never again: the toast goes, and so does the bell entry; a producer that re-fires the id stays silent.
  const skip = () => {
    toast.dismiss(toastId);
    if (notifId) notificationStore.dismiss(notifId);
  };
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
      <Box
        role="link"
        tabIndex={0}
        onClick={run}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            run();
          }
        }}
        sx={{ cursor: 'pointer', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', '&:hover': { textDecoration: 'underline' }, '&:focus-visible': { outline: `2px solid ${P.accentText}`, outlineOffset: 2 } }}
      >
        {message}
      </Box>
      <Box
        role="button"
        tabIndex={0}
        onClick={skip}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            skip();
          }
        }}
        sx={{ flexShrink: 0, cursor: 'pointer', fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, '&:hover': { color: P.textPrimary }, '&:focus-visible': { outline: `2px solid ${P.accentText}`, outlineOffset: 2 } }}
      >
        {t('Skip')}
      </Box>
    </Box>
  );
};

// Create context
const ToastContext = createContext<ToastContextType | undefined>(undefined);

/** Every toast is the same small pill (TASK-166): one line, plain text, no icon. */
const getBaseToastStyle = () => ({ ...TOAST_PILL });

// Toast provider component
export const ToastProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  // Toasts follow the theme: a small pill in the status colour (info = gold, never blue).
  const P = useAgentChatPalette();
  // Message node (clickable when the toast has an action) + history entry when it has an id.
  const body = useCallback((severity: NotificationSeverity, message: string, options?: ToastOptions): React.ReactNode | ((t: { id: string }) => React.ReactNode) => {
    if (options?.id && (severity === 'success' || severity === 'info')) {
      notificationStore.add({ id: options.id, severity, message, to: options.action?.to, ts: Date.now() });
    }
    const action = options?.action;
    if (!action) return message;
    return (t: { id: string }) => <ToastBody message={message} action={action} toastId={t.id} notifId={options?.id} />;
  }, []);

  const renderError = useCallback((message: string, options?: ToastOptions) => {
    toast(body('error', message, options) as any, {
      id: options?.id,
      duration: options?.duration || 4000,
      icon: null,
      style: pillToastStyle(P.error, P.surfaceSolid),
    });
  }, [P, body]);

  const renderWarning = useCallback((message: string, options?: ToastOptions) => {
    toast(body('warning', message, options) as any, {
      id: options?.id,
      duration: options?.duration || 4000,
      icon: null,
      style: pillToastStyle(P.warning, P.surfaceSolid),
    });
  }, [P, body]);

  // Every error is a notification (contract #43): recorded for the bell and toasted only as the preferences say.
  // The id is the episode key; without one the same text on the same page is the same problem.
  const route = useCallback((severity: 'error' | 'warning', message: string, options?: ToastOptions) => {
    const to = options?.to ?? options?.action?.to ?? `${window.location.pathname}${window.location.search}`;
    notify({
      id: options?.id ?? `${options?.category ?? 'action'}:${to}:${message}`,
      category: options?.category ?? 'action',
      severity,
      message,
      to,
      scope: options?.scope,
      action: options?.action,
      duration: options?.duration,
    });
  }, []);
  const showError = useCallback((message: string, options?: ToastOptions) => route('error', message, options), [route]);
  const showWarning = useCallback((message: string, options?: ToastOptions) => route('warning', message, options), [route]);

  useEffect(() => {
    registerToastRenderer((n) => {
      const o: ToastOptions = { id: n.id, action: n.action, duration: n.duration };
      if (n.severity === 'error') renderError(n.message, o);
      else renderWarning(n.message, o);
    });
    return () => registerToastRenderer(null);
  }, [renderError, renderWarning]);

  const showSuccess = useCallback((message: string, options?: ToastOptions) => {
    toast(body('success', message, options) as any, {
      id: options?.id,
      duration: options?.duration || 3000,
      icon: null,
      style: pillToastStyle(P.success, P.surfaceSolid),
    });
  }, [P, body]);

  const showInfo = useCallback((message: string, options?: ToastOptions) => {
    toast(body('info', message, options) as any, {
      id: options?.id,
      duration: options?.duration || 3000,
      icon: null,
      style: pillToastStyle(P.accentText, P.surfaceSolid),
    });
  }, [P, body]);

  /** TASK-166: the 24 h digest. It is a summary of the history, so it adds no bell entry of its own. */
  const showDigest = useCallback((selection: DigestSelection) => {
    const color = selection.severity === 'error' ? P.error : P.warning;
    toast(<DigestToastBody selection={selection} onDismiss={() => toast.dismiss(DIGEST_TOAST_ID)} />, {
      id: DIGEST_TOAST_ID,
      duration: 12000,
      icon: null,
      position: 'top-right',
      // The caret opens a small list under the pill, so the bar must not clip it — and it must
      // paint above the toasts that come after it, or the list is covered.
      style: { ...pillToastStyle(color, P.surfaceSolid), overflow: 'visible' },
    });
  }, [P]);

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
    showDigest,
  };

  return (
    <ToastContext.Provider value={contextValue}>
      {children}
      <Toaster
        position="top-right"
        reverseOrder={false}
        gutter={8}
        containerClassName=""
        containerStyle={{ top: 72 }}
        toastOptions={{
          className: '',
          duration: 4000,
          style: {
            ...getBaseToastStyle(),
            background: P.surfaceSolid,
            color: P.textPrimary,
            border: `1px solid ${P.borderColor}`,
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
