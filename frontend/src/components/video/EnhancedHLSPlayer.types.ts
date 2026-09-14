import { Host } from '../../types/common/Host_Types';
import { MonitoringAnalysis, SubtitleAnalysis, LanguageMenuAnalysis } from '../../types/pages/Monitoring_Types';

export interface ArchiveMetadata {
  total_segments: number;
  total_duration_seconds: number;
  window_hours: number;
  segments_per_window: number;
  manifests: Array<{
    name: string;
    window_index: number;
    chunk_index: number;
    start_segment: number;
    end_segment: number;
    start_time_seconds: number;
    end_time_seconds: number;
    duration_seconds: number;
    created?: number;  // Unix timestamp of chunk creation
  }>;
}

// Timed segment from Whisper (word-level timestamps)
export interface TimedSegment {
  start: number;  // Start time in seconds (relative to chunk start)
  end: number;    // End time in seconds (relative to chunk start)
  text: string;   // Text for this segment
  translations?: Record<string, string>;  // Optional translations
}

// Legacy transcript format (6-second segments)
export interface TranscriptSegment {
  segment_num: number;
  relative_seconds: number;
  language: string;
  transcript: string;
  enhanced_transcript?: string;
  confidence: number;
  manifest_window: number;
  translations?: Record<string, string>;
}

export interface TranscriptDataLegacy {
  capture_folder: string;
  sample_interval_seconds: number;
  total_duration_seconds: number;
  segments: TranscriptSegment[];
  last_update: string;
  total_samples: number;
}

// 10-minute transcript format with timed segments
export interface MinuteMetadata {
  minute: number;
  time_range: string;
  has_text: boolean;
  text_length?: number;
  word_count?: number;
  segment_count?: number;
  language?: string;
  confidence?: number;
  error?: string;
}

export interface TranscriptData10Min {
  capture_folder: string;
  hour: number;
  chunk_index: number;
  chunk_duration_minutes: number;
  language: string;
  transcript: string;
  confidence: number;
  transcription_time_seconds: number;
  timestamp: string;
  mp3_file: string;
  translations?: Record<string, string>;
  segments?: TimedSegment[];
  minute_metadata?: MinuteMetadata[];
}

export type TranscriptData = TranscriptDataLegacy | TranscriptData10Min;

export interface ErrorTrendData {
  blackscreenConsecutive: number;
  freezeConsecutive: number;
  audioLossConsecutive: number;
  macroblocksConsecutive: number;
  hasWarning: boolean;
  hasError: boolean;
}

export interface EnhancedHLSPlayerProps {
  deviceId: string;
  hostName: string;
  host?: Host;
  streamUrl?: string;
  width?: string | number;
  height?: string | number;
  muted?: boolean;
  className?: string;
  isLiveMode?: boolean;
  quality?: 'low' | 'sd' | 'hd' | 'hd_plus';
  shouldPause?: boolean;
  onPlayerReady?: () => void;
  onVideoTimeUpdate?: (time: number) => void;
  onVideoPause?: () => void;
  onCurrentSegmentChange?: (segmentUrl: string) => void;
  
  // Opt-in: right-rail running transcript feed in live mode (TASK-05).
  // Off by default so existing players keep their current layout.
  showLiveTranscriptRail?: boolean;

  monitoringMode?: boolean;
  monitoringAnalysis?: MonitoringAnalysis | null;
  subtitleAnalysis?: SubtitleAnalysis | null;
  languageMenuAnalysis?: LanguageMenuAnalysis | null;
  aiDescription?: string | null;
  errorTrendData?: ErrorTrendData | null;
  analysisTimestamp?: string | null;
  isAIAnalyzing?: boolean;
  
  // Translation support (optional - for integration with external translation systems)
  transcriptTranslations?: Record<string, string[]>;  // language -> array of translated segments

  // External archive seek (e.g. clicking the AVQ timeline). `time` is archive
  // global seconds (time-of-day: h*3600+m*60+s). `nonce` retriggers identical times.
  archiveSeek?: { time: number; nonce: number } | null;

  // Hide the built-in bottom scrubber/timeline overlay (AVQ L2 drives seeking
  // from its own 24h timeline instead).
  hideTimelineOverlay?: boolean;

  // Freeze on the seeked frame in archive mode: don't auto-play, and pause again
  // if playback starts (AVQ frame inspector — click a time, hold that still frame).
  freezeArchiveFrame?: boolean;
}
