// Export all web hooks from organized structure

// Auth Hooks
export * from './auth';

// AI Agent Hooks
export * from './aiagent';

// Core Hooks
export * from './useToast';
export { usePersistedState } from './usePersistedState';

// Controller Hooks
export * from './controller';

// Monitoring Hooks
export * from './monitoring';

// Validation Hooks
export * from './validation';

// Script Hooks
export * from './script';

// Storage Hooks (R2 URL management)
export * from './storage';

// Page Hooks (domain-specific for pages)
export * from './pages/useUserInterface';
export * from './pages/useRec';

export { useUserSession } from './useUserSession';
export { useToast } from './useToast';
export { useVerification } from './verification/useVerification';
export { useVerificationEditor } from './verification/useVerificationEditor';
export { useAction } from './actions/useAction';
export { useStreamCoordinates } from './useStreamCoordinates';

// Navigation hooks

// Component hooks
export { useHostData, useHostControl } from './useHostManager';
export { useDevicePanels } from './useDevicePanels';

// Page hooks
export { useRec } from './pages/useRec';
