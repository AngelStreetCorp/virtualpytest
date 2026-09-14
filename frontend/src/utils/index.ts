// Export all web utilities from organized structure

// Navigation utilities
export * from './navigation';

// User Interface utilities (removed - no index.ts exists)

// Validation utilities (excluding conflicting functions that exist in navigation)
export { 
  getConfidenceCategory,
  calculatePathConfidence,
  getConfidenceColor,
  formatConfidenceDisplay,
  hasReliabilityIssues,
} from './validation';

// Infrastructure utilities
export * from './infrastructure';

// ZIndex utilities
export * from './zIndexUtils';


// Build URL utilities
export * from './buildUrlUtils';
