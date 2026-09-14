/**
 * Unified Verification Types
 *
 * Simple, standard verification format used across the entire application.
 * A verification is a verification - same everywhere it's used.
 */

// =====================================================
// VERIFICATION PARAMETER TYPES
// =====================================================

// Area coordinates for image references
export interface ReferenceArea {
  x: number;
  y: number;
  width: number;
  height: number;
  // Optional fuzzy search coordinates
  fx?: number;
  fy?: number;
  fwidth?: number;
  fheight?: number;
  // Optional focus-detection params (learned when an image reference is captured
  // with "Focus"). Opaque to the frontend; the backend produces/consumes it.
  // See docs/agent/devices/image.md (Focus detection section).
  focus?: {
    hue: number;
    hue_tol: number;
    sat_min: number;
    val_min: number;
    band_frac: number;
    region: number[];
    threshold: number;
    ref_coverage?: number;
  };
}

// Image verification parameters
export interface ImageVerificationParams {
  image_path?: string; // Required for waitForImage*; absent for waitForIcon* (built-in glyph)
  threshold?: number; // Optional: match threshold (0.0 to 1.0), default 0.8
  timeout?: number; // Optional: timeout in whole seconds (1-60), default 1
  area?: ReferenceArea; // Optional: area to search within
  image_filter?: 'none' | 'greyscale' | 'binary'; // Optional: filter to apply, default 'none'
  reference_name?: string; // Optional: reference name for UI display (same as image_path usually)
  area_modified?: boolean; // Optional: flag indicating area has been modified
  check_focus?: boolean; // Optional: also verify the element is focused/selected (see docs/agent/devices/image.md)
  // waitForIconToAppear / waitForIconToDisappear: which built-in transport glyph
  // to shape-match (play | pause | stop | fast_forward | rewind | question_mark).
  icon?: string;
}

// Text verification parameters
export interface TextVerificationParams {
  text: string; // Required: text pattern to search for
  // OCR match-score threshold (0.0–1.0). Default 0.8 mirrors image. 1.0 =
  // exact substring after normalization; lower values accept difflib-scored
  // partial matches (one-char OCR misreads in short strings ≈ 0.875). Floor
  // 0.7 enforced both in the UI input and server-side in the controller.
  threshold?: number;
  confidence?: number; // Deprecated — historical, not consumed by the backend.
  timeout?: number; // Optional: timeout in whole seconds (1-60), default 10
  case_sensitive?: boolean; // Optional: case sensitive matching, default false
  area?: ReferenceArea; // Optional: area to search within
  image_filter?: 'none' | 'greyscale' | 'binary'; // Optional: filter to apply
  reference_name?: string; // Optional: reference name for UI display
  text_modified?: boolean; // Optional: flag indicating text has been modified
  area_modified?: boolean; // Optional: flag indicating area has been modified
  check_focus?: boolean; // Optional: also verify the element is focused/selected — same as image (see docs/agent/devices/image.md)
}

// ADB verification parameters
export interface AdbVerificationParams {
  search_term: string; // Required: element search term
  timeout?: number; // Optional: timeout in whole seconds (0-60), default 0 (single check)
}

// Appium verification parameters
export interface AppiumVerificationParams {
  search_term: string; // Required: element search term
  timeout?: number; // Optional: timeout in whole seconds (0-60), default 0 (single check)
}

// Web verification parameters (Playwright)
export interface WebVerificationParams {
  search_term: string; // Required: element search term (text, selector, aria-label)
  timeout?: number; // Optional: timeout in whole seconds (0-60), default 10
  check_interval?: number; // Optional: interval between checks in seconds, default 1
}

// Audio verification parameters
export interface AudioVerificationParams {
  // For detect_silence command
  threshold?: number; // Optional: silence threshold percentage
  duration?: number; // Optional: analysis duration in seconds
  timeout?: number; // Optional: timeout in whole seconds (0-60)
  audio_file?: string; // Optional: audio file path

  // For verify_audio_playing command
  min_level?: number; // Optional: minimum audio level percentage

  // For verify_audio_contains_frequency command
  target_freq?: number; // Required for frequency verification: target frequency in Hz
  tolerance?: number; // Optional: frequency tolerance in Hz
}

// Video verification parameters
export interface VideoVerificationParams {
  // For motion detection commands
  motion_threshold?: number; // Optional: motion threshold percentage
  duration?: number; // Optional: analysis duration in seconds
  timeout?: number; // Optional: timeout in whole seconds (0-60)
  area?: ReferenceArea; // Optional: area to search within

  // For color verification
  color?: string; // Required for color verification: color name or hex
  tolerance?: number; // Optional: color matching tolerance

  // For screen state verification
  expected_state?: string; // Required for state verification: expected state name

  // For video change detection
  threshold?: number; // Optional: change threshold percentage
  
  // UI-specific flags
  area_modified?: boolean; // Optional: flag indicating area has been modified
}

// Union type for all verification parameters
export type VerificationParams =
  | ImageVerificationParams
  | TextVerificationParams
  | AdbVerificationParams
  | AppiumVerificationParams
  | WebVerificationParams
  | AudioVerificationParams
  | VideoVerificationParams;

// =====================================================
// VERIFICATION INTERFACES
// =====================================================

// Base verification interface
interface BaseVerification {
  command: string; // Required: command to execute
  verification_type: 'text' | 'image' | 'adb' | 'appium' | 'web' | 'audio' | 'video'; // Required: type of verification

  // Result state (optional, populated after execution)
  success?: boolean;
  message?: string;
  error?: string;
  threshold?: number;
  resultType?: 'PASS' | 'FAIL' | 'ERROR';
  sourceImageUrl?: string; // TODO: Rename to image_source_url for consistency
  referenceImageUrl?: string;
  resultOverlayUrl?: string; // Added: overlay image URL for visual analysis
  // HTML evidence reports (failure: why it didn't match; success: false-positive review)
  debug_report_url?: string;
  success_report_url?: string;
  // Focus detection result (present only when the reference has area.focus)
  focusScore?: number; // accent coverage measured in the live frame (0.0-1.0)
  focusThreshold?: number; // min coverage required to count as focused
  extractedText?: string;
  searchedText?: string;
  imageFilter?: 'none' | 'greyscale' | 'binary';
  // Language detection for text verifications
  detectedLanguage?: string;
  ocrConfidence?: number; // OCR confidence score (0.0 to 1.0)
  languageConfidence?: number;

  // ADB-specific result data
  search_term?: string;
  wait_time?: number;
  total_matches?: number;
  matches?: Array<{
    element_id: number;
    matched_attribute: string;
    matched_value: string;
    match_reason: string;
    search_term: string;
    case_match: string;
    all_matches: Array<{
      attribute: string;
      value: string;
      reason: string;
    }>;
    full_element: {
      id: number;
      text: string;
      resourceId: string;
      contentDesc: string;
      className: string;
      bounds: string;
      clickable: boolean;
      enabled: boolean;
      tag?: string;
    };
  }>;
}

// Specific verification types with typed parameters
export interface ImageVerification extends BaseVerification {
  verification_type: 'image';
  params: ImageVerificationParams;
}

export interface TextVerification extends BaseVerification {
  verification_type: 'text';
  params: TextVerificationParams;
}

export interface AdbVerification extends BaseVerification {
  verification_type: 'adb';
  params: AdbVerificationParams;
}

export interface AppiumVerification extends BaseVerification {
  verification_type: 'appium';
  params: AppiumVerificationParams;
}

export interface WebVerification extends BaseVerification {
  verification_type: 'web';
  params: WebVerificationParams;
}

export interface AudioVerification extends BaseVerification {
  verification_type: 'audio';
  params: AudioVerificationParams;
}

export interface VideoVerification extends BaseVerification {
  verification_type: 'video';
  params: VideoVerificationParams;
}

// Unified verification type (discriminated union)
export type Verification =
  | ImageVerification
  | TextVerification
  | AdbVerification
  | AppiumVerification
  | WebVerification
  | AudioVerification
  | VideoVerification;

// Verifications grouped by verification type
export interface Verifications {
  [verificationType: string]: Verification[]; // Verification type as category
}

// =====================================================
// REFERENCE TYPES
// =====================================================

// Individual reference item
export interface Reference {
  type: 'image' | 'text';
  url: string;
  area: ReferenceArea;
  created_at: string;
  updated_at: string;
  name?: string; // Original name for display (added to support UI)
  // Text reference specific fields
  text?: string;
  // True when this row is shared across model-compatible userinterfaces. Origin
  // UI is recorded server-side in userinterface_name (not surfaced here today).
  shared?: boolean;
}

// References organized by filename within a model
export interface ModelReferences {
  [filename: string]: Reference;
}

// Complete resource configuration structure
export interface ResourceConfig {
  resources: {
    [deviceModel: string]: ModelReferences;
  };
}

// Extended reference with computed fields for frontend use
export interface ReferenceImage extends Reference {
  name: string; // Computed from filename
  model: string; // Computed from context
  filename: string; // Added for convenience
}
