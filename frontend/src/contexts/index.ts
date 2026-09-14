// Navigation Contexts (clean unified architecture)
export { NavigationProvider, NavigationEditorProvider } from './navigation';

// Host Manager Context (split into Data + Control for render-perf reasons)
export { HostManagerProvider } from './HostManagerProvider';
export { HostDataContext } from './HostDataContext';
export type { HostDataContextType } from './HostDataContext';
export { HostControlContext } from './HostControlContext';
export type { HostControlContextType } from './HostControlContext';
export { useHostData, useHostControl } from '../hooks/useHostManager';

// Other Contexts
export { CustomThemeProvider as ThemeProvider, useTheme } from './ThemeContext';
export { ToastProvider, useToastContext as useToast } from './ToastContext';
