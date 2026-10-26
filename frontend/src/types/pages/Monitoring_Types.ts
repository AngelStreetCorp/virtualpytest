/**
 * Monitoring Types
 *
 * Shared interfaces for monitoring functionality across the application.
 * These types correspond to the backend analysis data from analyze_audio_video.py
 */

// Core monitoring analysis from analyze_audio_video.py
// One thing a profile analyzer saw in a frame
export interface ProfileObservation {
  label: string; // e.g. 'car'
  track_id?: number; // same object across frames
  conf?: number; // 0..1
  bbox: [number, number, number, number]; // x, y, w, h (pixels of frame_size; all values <= 1 = fractions)
  attrs?: Record<string, string | number>; // e.g. { colour: 'red' }
  votes?: string; // '2/3': votes cast so far / votes needed for the track's verdict (profiles with track.votes > 1)
  shape?: { ellipse: [number, number, number, number, number] }; // [cx, cy, ax, ay, angle_deg] in frame pixels (ax, ay = full axis lengths)
  verdict?: string | null; // null while the track is still voting
  probs?: Record<string, number>; // class probabilities of the verdict attribute so far
  /**
   * Centre velocity of the track in px/s ([vx, vy]), as the tracker measured it (BUG-0836).
   * The overlay is drawn on a live video, which is later than the frame these boxes came from, so a
   * moving object has moved on since. The client advances each box by v x age to keep it on its
   * object. Absent for a tracker that cannot estimate motion, or for an object that has not moved.
   */
  v?: [number, number];
}

// The web overlay of a profile, as the profile manifest's `ui` block (the monitor copies it into every frame JSON)
export type ProfileUiColour = 'green' | 'red' | 'amber' | 'grey' | 'blue' | 'purple' | 'white' | 'black' | 'yellow' | 'brown';
export interface ProfileUi {
  title: string;
  headline?: { kpi: string; label: string; unit?: '%' | 'min' };
  // the stat row under the headline: "Eggs 253 · Detections 82". `kpi` reads a KPI, `observations`
  // reads the number of detections in the analysed frame (not a KPI — it is the observations list).
  stats?: { label: string; kpi?: string; observations?: boolean }[];
  counters?: { kpi: string; items: { key: string; colour: ProfileUiColour; label?: string }[] };
  box?: { shape?: 'rect' | 'ellipse'; badge?: 'none' | 'votes'; colour_by?: 'none' | 'verdict' };
  focus_panel?: { crop?: boolean; probs?: boolean; title?: string };
  // a badge on the picture while this event is in progress (ad_meter: AD)
  state_badge?: { event: string; label: string; colour?: ProfileUiColour };
  // top-right HUD of a vehicle: fields of the frame's `telemetry`, in order; a field without a value is not drawn
  hud?: ProfileHudItem[];
}

export interface ProfileHudItem {
  key: string;
  label: string;
  format?: 'number' | 'battery' | 'duration' | 'latlon'; // latlon: key = lat, key2 = lon
  key2?: string;
  short?: string; // label in the narrow HUD (default: first three letters)
  unit?: string;
  decimals?: number;
  warn_above?: number;
  warn_below?: number;
}

// A vehicle's reading attached to the frame (drone profile): units %, degrees C, metres, m/s, seconds; absent keys = not reported
export interface ProfileTelemetry {
  ok: boolean; // false: no telemetry (the reading is older than a few seconds)
  age?: number;
  bat?: number;
  temp?: number;
  alt?: number;
  spd?: number;
  yaw?: number;
  ft?: number;
  fly?: boolean;
  x?: number;
  y?: number;
  lat?: number;
  lon?: number;
  fix?: number;
  [key: string]: number | boolean | undefined;
}

// The item checked last, for the "last checked" panel
export interface ProfileFocus {
  track_id: number;
  check: number; // vote number of this check
  checks: number; // votes needed
  verdict: string | null;
  final: boolean;
  probs: Record<string, number>;
  crop: string | null; // file name in the device's metadata folder
}

// A profile event in progress (start = unix seconds)
export interface ProfileEvent {
  start: number;
  duration_ms: number;
}

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

  // Generic profile output (TASK-90). tv_app writes profile='tv_app' with empty values; frames from before
  // the change have none of these. Boxes are drawn by ProfileOverlay for every profile except tv_app.
  profile?: string;
  frame_size?: [number, number]; // [w, h] of the analysed frame; observation bboxes are in these pixels
  observations?: ProfileObservation[];
  events?: Record<string, ProfileEvent>;
  kpis?: Record<string, number | Record<string, number>>;
  incidents?: Record<string, { active: boolean; value: number }>; // profile incidents as evaluated by the monitor
  ui?: ProfileUi;
  focus?: ProfileFocus | null;
  telemetry?: ProfileTelemetry;
  /**
   * When the analysed frame was CAPTURED, as opposed to `timestamp`, which is when the analysis of it
   * finished (BUG-0836). Everything the overlay draws is `now - captured_at` old, so this is what the
   * client needs to move each box forward onto its object and to tell the operator how far behind the
   * picture is. Written by the sampled profile analyzers; absent on tv_app frames and on old frames.
   */
  captured_at?: string;
  
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
    // Which matcher layer answered: 'rule' (deterministic dHash/focus) today, 'cv'
    // and 'model' reserved. Absent on frames written before tiers were reported.
    tier?: string;
    // identify_screen's own abstain reason, passed through verbatim (the writer
    // never re-derives it), and the abstain door it maps to: '1'..'6' | 'unknown'.
    // Both absent when the matcher produced no reason (a clean match).
    reason?: string;
    door?: string;
    // Motion-gate skip: 'live' (full-frame motion) or 'motion' (band / minor > 1%).
    // When present, the cached `node` is served with `confidence: 0` and Tier-2
    // fields are absent. Absent on a fresh matcher run.
    gate_skip?: string;
    // Localize v3 (TASK-104): the one verdict the button and MCP give too.
    kind?: 'signal' | 'live' | 'node' | 'overlay' | 'known_screen' | 'app' | 'unknown';
    verdict?: { kind: 'signal' | 'live' | 'node' | 'overlay' | 'known_screen' | 'app' | 'unknown'; label: string; node_id?: string | null; confidence?: number; evidence?: Record<string, unknown> };
    // Tier 2 (screen_state_cv) — only present on a fresh matcher run (the gate
    // must be open to read the frame). Each arm abstains honestly on its own
    // missing input, so 'unknown' is a real answer (we DID look, the answer
    // was unknowable), and a missing field means the cascade did not run for
    // this frame at all.
    loaded?: 'yes' | 'no' | 'unknown';
    overlay?: 'none' | 'popup' | 'tooltip' | 'keyboard' | 'notification' | 'unknown';
    playback?: 'playing' | 'paused' | 'stopped' | 'not_applicable' | 'unknown';
    error?: 'none' | 'visible' | 'unknown';
    // Free-text brand label from the userinterface row. Absent on a row that
    // has no company metadata (NULL = unknown). When present, it is also
    // used as a brand-aware extra keyword to the Tier-2 `error` arm.
    userinterface_company?: string;
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
    mask?: number; // changed 4x4 cells, row-major bits (bit 0 = top-left, bit 15 = bottom-right)
    bbox?: [number, number, number, number] | null; // changed area, frame fractions [x0, y0, x1, y1]
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
  incident_type: string; // 'blackscreen' | 'freeze' | 'no_signal' | 'audio_loss'
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
  // Last key sent to the device before the alert (TASK-158); absent when the host recorded none
  seconds_since_last_key?: number;
  last_key_source?: string; // 'script' | 'take_control' | 'remote' | 'probe' | 'unknown'
  last_key_actor?: string | null;
  last_key_name?: string | null;
  probe?: { key: string; outcome: string; detail: string; at: string };
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
