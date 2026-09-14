/**
 * Central configuration for layout settings based on device model type
 * This ensures consistent layout behavior across components
 */


// Layout configuration for StreamViewer component
export interface StreamViewerLayoutConfig {
  minHeight: string;
  aspectRatio: string;
  objectFit: 'cover' | 'contain' | 'fill';
  isMobileModel: boolean;
}

// Layout configuration for VerificationEditor component
export interface VerificationEditorLayoutConfig {
  width: number;
  height: number;
  captureHeight: number;
  objectFit: 'cover' | 'contain';
  isMobileModel: boolean;
}

/**
 * Determines if a model name refers to a mobile device
 * @param model The model name string
 * @returns boolean indicating if this is a mobile model
 */
export const isMobileModel = (model?: string): boolean => {
  if (!model) return false;
  const modelLower = model.toLowerCase();
  return modelLower.includes('mobile');
};

/**
 * Get the appropriate StreamViewer layout configuration based on model type
 * @param model The model name string
 * @returns StreamViewerLayoutConfig with the appropriate settings
 */
export const getStreamViewerLayout = (model?: string): StreamViewerLayoutConfig => {
  const mobile = isMobileModel(model);
  return mobile
    ? {
        minHeight: '400px',
        aspectRatio: '9/16', // Portrait for mobile - revert to original working values
        objectFit: 'contain', // Use contain to maintain aspect ratio
        isMobileModel: true,
      }
    : {
        minHeight: '300px',
        aspectRatio: '16/9', // Landscape for non-mobile - revert to original working values  
        objectFit: 'contain', // Use contain to maintain aspect ratio
        isMobileModel: false,
      };
};

/**
 * Get the appropriate VerificationEditor layout configuration based on model type
 * @param model The model name string
 * @returns VerificationEditorLayoutConfig with the appropriate settings
 */
export const getVerificationEditorLayout = (model?: string): VerificationEditorLayoutConfig => {
  const mobile = isMobileModel(model);
  return mobile
    ? {
        width: 360,
        height: 510,
        captureHeight: 200,
        objectFit: 'cover',
        isMobileModel: true,
      }
    : {
        width: 640,
        height: 510,
        captureHeight: 140,
        objectFit: 'cover',
        isMobileModel: false,
      };
};
