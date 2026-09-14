/**
 * Monitoring Types
 *
 * Shared interfaces for monitoring functionality across the application.
 * These types correspond to the backend analysis data from analyze_audio_video.py
 */

// Core monitoring analysis from analyze_audio_video.py
export interface MonitoringAnalysis {
  timestamp: string;
  filename: string;
  thumbnail: string;
  blackscreen: boolean;
  blackscreen_percentage: number;
  freeze: boolean;
  freeze_diffs: number[];
  last_3_filenames: string[];
  last_3_thumbnails: string[]; // Local paths (deprecated, use r2_images)
  audio: boolean;
  volume_percentage: number;
  mean_volume_db: number;
  macroblocks: boolean; // Macroblock/image quality detection
  quality_score: number; // Image quality score (0-100)
  has_incidents: boolean; // Pre-calculated incident status
  
  // R2 storage URLs (uploaded to R2 on detection)
  r2_images?: {
    // Freeze incidents (multiple comparison frames)
    original_urls?: string[];
    thumbnail_urls?: string[];
    original_r2_paths?: string[];
    thumbnail_r2_paths?: string[];
    // Blackscreen/Macroblocks incidents (single start + optional end)
    thumbnail_url?: string;
    thumbnail_r2_path?: string;
    closure_url?: string;
    closure_r2_path?: string;
    // Common fields
    timestamp?: string;
    time_key?: string;
    stage?: string;
  };

  // Event duration tracking (from capture_monitor.py)
  blackscreen_event_start?: string;
  blackscreen_event_duration_ms?: number;
  freeze_event_start?: string;
  freeze_event_duration_ms?: number;
  audio_event_start?: string;
  audio_event_duration_ms?: number;
  macroblocks_event_start?: string;
  macroblocks_event_duration_ms?: number;

  // Action metadata (from action_executor.py)
  last_action_executed?: string;
  last_action_timestamp?: number;
  action_params?: Record<string, any>;

  // Screen identification (Localize) - per-frame node match from capture_monitor.py.
  // Only present when DEVICE{N}_USERINTERFACE is configured for the device.
  localize?: {
    node: string | null; // matched node label, or null when unknown
    confidence: number; // 0..1
    excluded: number; // nodes confidently ruled out
    total: number; // total fingerprinted nodes considered
    state?: string | null; // named capture-side state: 'no_signal' | 'blackscreen'
    state_label?: string | null; // human label: 'No Signal' | 'Black Screen'
  };

  // Motion classification - per-frame from capture_monitor.py (detector._motion_shape + fusion
  // with the localize result). Tells live TV (full-frame motion, no UI node matched) apart from a
  // moving UI (carousel / picture-in-picture still match a node -> 'ui' with a flag).
  motion?: {
    kind: 'static' | 'full' | 'band' | 'box' | 'minor'; // raw spatial shape of the frame-to-frame diff
    state: 'live' | 'motion' | 'ui' | 'static' | 'blackscreen' | 'no_signal' | 'unknown'; // fused state
    pct: number; // % of the frame that changed vs the previous frame
    cells?: number;
    rows?: number;
    cols?: number;
    pip?: boolean; // localized motion box on a matched UI screen (picture-in-picture)
    carousel?: boolean; // horizontal motion band on a matched UI screen
  };

  // ✅ NEW: Zapping detection (nested structure) - from zapping_detector_utils.py
  zap?: {
    detected: boolean;
    id: string;
    channel_name: string;
    channel_number: string;
    program_name: string;
    program_start_time: string;
    program_end_time: string;
    blackscreen_duration_ms: number;
    transition_type?: 'freeze' | 'blackscreen'; // Actual transition kind — drives the duration label
    report_url?: string; // Per-event zap report (R2)
    detection_type: 'automatic' | 'manual';
    confidence: number;
    detected_at: string;
    audio_silence_duration: number;
    time_since_action_ms?: number; // Time from action to blackscreen start (automatic only)
    total_zap_duration_ms: number; // Backend calculated total zap duration
  };

  // ✅ NEW: Zapping cache (for real-time frontend notification)
  zap_cache?: {
    detected: boolean;
    id: string;
    channel_name: string;
    channel_number: string;
    program_name: string;
    program_start_time: string;
    program_end_time: string;
    blackscreen_duration_ms: number;
    transition_type?: 'freeze' | 'blackscreen'; // Actual transition kind — drives the duration label
    report_url?: string; // Per-event zap report (R2)
    detection_type: 'automatic' | 'manual';
    confidence: number;
    detected_at: string;
    audio_silence_duration: number;
    time_since_action_ms?: number; // Time from action to blackscreen start (automatic only)
    total_zap_duration_ms: number; // Backend calculated total zap duration
    original_frame: string; // Reference to actual event frame
  };
  
  // @deprecated Old flat structure (kept for backward compatibility)
  zapping_detected?: boolean;
  zapping_id?: string;
  zapping_channel_name?: string;
  zapping_channel_number?: string;
  zapping_program_name?: string;
  zapping_program_start_time?: string;
  zapping_program_end_time?: string;
  zapping_confidence?: number;
  zapping_blackscreen_duration_ms?: number;
  zapping_audio_silence_duration?: number;
  zapping_detection_type?: 'automatic' | 'manual';
  zapping_detected_at?: string;
}

// Subtitle analysis from backend detection (video.py) - EXACT field names
export interface SubtitleAnalysis {
  subtitles_detected: boolean; // result.subtitles_detected
  combined_extracted_text: string; // result.combined_extracted_text
  detected_language?: string; // result.detected_language
  confidence: number; // result.results[0].confidence
  detection_message?: string; // Clear message about detection status
}

// Frontend-computed subtitle trend analysis
export interface SubtitleTrendAnalysis {
  showRedIndicator: boolean;
  currentHasSubtitles: boolean;
  framesAnalyzed: number;
  noSubtitlesStreak: number;
}

// Language/subtitle menu analysis from backend AI detection - EXACT field names
export interface LanguageMenuAnalysis {
  menu_detected: boolean; // result.menu_detected
  audio_languages: string[]; // result.audio_languages (ordered list)
  subtitle_languages: string[]; // result.subtitle_languages (ordered list)
  selected_audio: number; // result.selected_audio (index or -1)
  selected_subtitle: number; // result.selected_subtitle (index or -1)
}

// Live monitoring events (zapping, etc.) - polled separately for real-time display
export interface LiveMonitoringEvent {
  event_id: string;
  event_type: 'zapping';
  timestamp: string; // ISO format
  frame_filename: string;
  detection_type: 'automatic' | 'manual';
  blackscreen_duration_ms: number;
  channel_name: string;
  channel_number: string;
  program_name: string;
  confidence: number;
  expires_at: number; // Unix timestamp
  
  // Only present for automatic zapping
  action_command?: string;
  action_timestamp?: number;
}

export interface LiveEventsResponse {
  success: boolean;
  events: LiveMonitoringEvent[];
  count: number;
}

// Alert/Incident types from backend alerts_db.py - EXACT field names
export interface Alert {
  id: string; // UUID from backend
  host_name: string; // Exact backend field name
  device_id: string; // Exact backend field name
  incident_type: string; // 'blackscreen' | 'freeze' | 'audio_loss'
  status: 'active' | 'resolved'; // Exact backend enum values
  consecutive_count: number; // Exact backend field name
  start_time: string; // ISO datetime string
  end_time?: string; // ISO datetime string (optional)
  metadata: AlertMetadata; // JSONB metadata from backend
  
  // AI Discard Analysis fields (from backend_discard service)
  checked?: boolean; // Whether AI has analyzed this alert
  check_type?: string; // Type of check performed ('ai' | 'manual')
  discard?: boolean; // Whether AI determined this is a false positive
  discard_type?: string; // Category of false positive ('brief_glitch' | 'channel_change' | etc.)
  discard_comment?: string; // AI explanation for the discard decision
  updated_at?: string; // When the discard analysis was performed
}

// Alert metadata structure (from alert_system.py)
export interface AlertMetadata {
  // Core analysis data (always present)
  blackscreen?: boolean;
  blackscreen_percentage?: number;
  freeze?: boolean;
  freeze_diffs?: number[];
  audio?: boolean;
  volume_percentage?: number;
  mean_volume_db?: number;
  last_3_filenames?: string[];
  last_3_thumbnails?: string[];

  // R2 storage URLs (uploaded to R2 on detection)
  r2_images?: {
    // Freeze incidents (multiple comparison frames)
    original_urls?: string[];
    thumbnail_urls?: string[];
    original_r2_paths?: string[];
    thumbnail_r2_paths?: string[];
    // Blackscreen/Macroblocks incidents (single start + optional end)
    thumbnail_url?: string;
    thumbnail_r2_path?: string;
    closure_url?: string;
    closure_r2_path?: string;
    // Common fields
    timestamp?: string;
    time_key?: string;
    stage?: string;
  };

  // Freeze detection details
  freeze_details?: {
    frames_compared: string[];
    frame_differences: number[];
    threshold: number;
    comparison_method: string;
  };

  // Allow additional metadata
  [key: string]: any;
}
