import { AppIcon } from '../../constants/icons';
import { Box, Typography, CircularProgress } from '@mui/material';
import React from 'react';

// palette: drawn on video/screenshot — this overlay sits on top of a live TV stream / screenshot
// (z-indexed boxes in Monitoring_*.tsx). Saturated hex literals stay readable on any image; do
// NOT swap them for theme tokens (dark/light) because the overlay surface is the video itself.

import { MonitoringAnalysis, SubtitleAnalysis, LanguageMenuAnalysis } from '../../types/pages/Monitoring_Types';
import { formatTimeWithMs } from '../../utils/dateUtils';
import { formatScreenVerdict, formatScreenDiagnosis } from '../../utils/screenVerdict';
import { ActionHistory } from './ActionHistory';
import { ProfileOverlay } from './ProfileOverlay';
import { TYPOGRAPHY } from '../../constants/typography';

// Language code to name mapping
const LANGUAGE_NAMES: Record<string, string> = {
  en: 'English',
  fr: 'French',
  de: 'German',
  it: 'Italian',
  es: 'Spanish',
  pt: 'Portuguese',
  nl: 'Dutch',
  ru: 'Russian',
  ja: 'Japanese',
  zh: 'Chinese',
  ko: 'Korean',
  ar: 'Arabic',
};

interface ConsecutiveErrorCounts {
  blackscreenConsecutive: number;
  freezeConsecutive: number;
  audioLossConsecutive: number;
  macroblocksConsecutive: number;
  hasWarning: boolean;
  hasError: boolean;
}

interface MonitoringOverlayProps {
  // Removed sx prop to ensure consistent positioning across all contexts (modal, panels, etc.)
  monitoringAnalysis?: MonitoringAnalysis;
  subtitleAnalysis?: SubtitleAnalysis | null;
  languageMenuAnalysis?: LanguageMenuAnalysis | null;
  consecutiveErrorCounts?: ConsecutiveErrorCounts | null;
  showSubtitles?: boolean;
  showLanguageMenu?: boolean;
  analysisTimestamp?: string;
  isAIAnalyzing?: boolean;
  audioSupported?: boolean;
  /** Resolves a file in the device's metadata folder to a URL (profile overlays: the "last checked" crop). */
  metadataUrl?: (fileName: string) => string;
  /** Fallback when the current frame JSON has no `profile` yet (host monitor_profiles). */
  profileName?: string;
  /** Capture-side FPS (frames written). Null = not measured yet. */
  fpsIn?: number | null;
  /** Playback-side FPS (decoded / received). Null = not measured yet. */
  fpsOut?: number | null;
  /**
   * ffmpeg-configured capture rate for this device (BUG-0575). Parsed on the
   * host from `-framerate N` in the live ffmpeg process cmdline and published
   * as `host.system_stats.stream_capture_fps[device_id]`. The overlay prefers
   * this as the "FPS: in" value because that is the rate ffmpeg was *told* to
   * capture at, distinct from the measured value (which depends on host load).
   */
  fpsInConfigured?: number | null;
  /**
   * The picture under the overlay IS the frame the boxes were measured on (BUG-0836): the boxes must be
   * drawn where they are, not carried forward. Set by the player that renders the analysed frame.
   */
  frameLocked?: boolean;
  /** The analysed capture, drawn under the boxes in their own coordinates when frame-locked (BUG-0913). */
  frameUrl?: string | null;
}

export const MonitoringOverlay: React.FC<MonitoringOverlayProps> = ({
  monitoringAnalysis,
  subtitleAnalysis,
  languageMenuAnalysis,
  consecutiveErrorCounts,
  showSubtitles = false,
  showLanguageMenu = false,
  analysisTimestamp,
  isAIAnalyzing = false,
  audioSupported = true,
  metadataUrl,
  profileName,
  fpsIn = null,
  fpsOut = null,
  fpsInConfigured = null,
  frameLocked,
  frameUrl,
}) => {
  // Use separate data sources
  const analysis = monitoringAnalysis;
  const subtitles = subtitleAnalysis;
  const languageMenu = languageMenuAnalysis;
  // Which matcher layer answered the Screen row, and why it abstained (null on a clean
  // match / older frame that predates the diagnosis fields).
  const screenLabel = analysis?.localize ? formatScreenVerdict(analysis.localize) : null;
  const screenDiagnosis = analysis?.localize ? formatScreenDiagnosis(analysis.localize) : null;

  // Format timestamp for display (ISO format -> HH:MM:SS)
  const formatTimestamp = (timestamp?: string): string => {
    if (!timestamp) return 'Unknown';
    
    try {
      const date = new Date(timestamp);
      if (isNaN(date.getTime())) return 'Unknown';
      
      return date.toLocaleTimeString('en-US', { 
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      });
    } catch {
      return 'Unknown';
    }
  };

  // Format duration (ms -> "1.5s")
  const formatDuration = (ms?: number): string => {
    if (!ms) return '0s';
    return `${(ms / 1000).toFixed(1)}s`;
  };

  // The effective profile name: the JSON's `profile` field when the monitor has stamped it,
  // else the device's configured profile (host.system_stats.monitor_profiles[device_id]). The
  // device config is the one the operator picked in the device settings; if the monitor hasn't
  // populated `profile` yet (cold start, first frame, monitor down), we still want the
  // profile-specific overlay so the user can see "this is a counting_cars device" instead of a
  // tv_app overlay showing the wrong metrics.
  const effectiveProfile = analysis?.profile || profileName;

  // Profiles other than tv_app (counting_cars, ...) have their own overlay: boxes, events and KPIs (TASK-90).
  // We also short-circuit on the device's configured profile so the user sees the right
  // overlay even when the JSON hasn't been populated yet (BUG-0574).
  if (effectiveProfile && effectiveProfile !== 'tv_app') {
    // ProfileOverlay expects an analysis object; if the monitor hasn't written one yet
    // (the JSON comes back empty for a cold / broken monitor) we synthesise a minimal
    // placeholder so GenericOverlay can render its title + empty-state row instead of
    // crashing on a missing `profile` field.
    const overlayAnalysis: MonitoringAnalysis = analysis ?? {
      timestamp: '',
      filename: '',
      thumbnail: '',
      blackscreen: false,
      blackscreen_percentage: 0,
      freeze: false,
      freeze_diffs: [],
      last_3_filenames: [],
      last_3_thumbnails: [],
      audio: false,
      volume_percentage: 0,
      mean_volume_db: -100,
      macroblocks: false,
      quality_score: 0,
      has_incidents: false,
      // ProfileOverlay uses these to render the title and a per-class count; an
      // empty placeholder is the documented "monitor not yet producing data" state.
      profile: effectiveProfile,
      observations: undefined,
      events: undefined,
      kpis: undefined,
      incidents: undefined,
    };
    return (
      <ProfileOverlay
        analysis={overlayAnalysis}
        analysisTimestamp={analysisTimestamp}
        metadataUrl={metadataUrl}
        fpsIn={fpsIn}
        fpsOut={fpsOut}
        fpsInConfigured={fpsInConfigured}
        profileName={profileName}
        frameLocked={frameLocked}
        frameUrl={frameUrl}
      />
    );
  }

  // Always render overlay with empty state when no analysis

  return (
    <>
      {/* AI Analyzing indicator - separate overlay at top-right */}
      {isAIAnalyzing && (
        <Box
          sx={{
            position: 'absolute',
            top: 16,
            right: 16,
            zIndex: 30,
            p: 1.5,
            borderRadius: 1,
            backgroundColor: 'rgba(0, 0, 0, 0.8)',
            pointerEvents: 'none',
            display: 'flex',
            alignItems: 'center',
            gap: 1,
          }}
        >
          <CircularProgress size={16} sx={{ color: '#00bfff' }} />
          <Typography variant="body2" sx={{ color: '#00bfff', fontWeight: 500 }}>
            AI Analyzing...
          </Typography>
        </Box>
      )}

      {/* Main analysis overlay - top-left aligned (operator's choice). */}
      <Box
        sx={{
          position: 'absolute',
          top: 16,
          left: 16,
          zIndex: 20,
          p: 2,
          borderRadius: 1,
          backgroundColor: 'rgba(0, 0, 0, 0.7)',
          pointerEvents: 'none', // Don't interfere with clicks
          // Fixed width so the box doesn't resize as variable-length content appears
          // between frames, and wide enough for each metric line to stay on ONE line.
          // nowrap is inherited by all rows; long subtitle text opts back into wrap.
          width: 400,
          whiteSpace: 'nowrap',
          // Don't spread sx prop here to maintain consistent positioning across all contexts
        }}
      >
        {analysisTimestamp && (
          // ms precision, same format as the key press cards, so press-to-screen
          // latency (KPI) can be checked by eye
          <Typography variant="body2" sx={{ color: '#ffffff', mb: 0.5, fontFamily: 'monospace' }}>
            {formatTimeWithMs(analysisTimestamp)}
          </Typography>
        )}

        <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5 }}>
          <Typography variant="body2" sx={{ color: '#ffffff', mr: 1 }}>
            Profile:
          </Typography>
          <Typography variant="body2" sx={{ color: effectiveProfile ? '#ffffff' : '#888888' }}>
            {effectiveProfile || '—'}
          </Typography>
        </Box>

        <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5 }}>
          <Typography variant="body2" sx={{ color: '#ffffff', mr: 1 }}>
            FPS:
          </Typography>
          <Typography variant="body2" sx={{ color: '#cccccc' }}>
            in{' '}
            <Typography
              component="span"
              variant="body2"
              data-testid="monitoring-fps-in-configured"
              sx={{ color: (fpsInConfigured ?? fpsIn) == null ? '#888888' : '#00ff00' }}
            >
              {(fpsInConfigured ?? fpsIn) == null ? '—' : (fpsInConfigured ?? fpsIn)}
            </Typography>
            {fpsInConfigured != null && fpsIn != null && fpsIn !== fpsInConfigured && (
              <Typography
                component="span"
                variant="body2"
                data-testid="monitoring-fps-in-measured"
                sx={{ color: '#888888', ml: 0.5 }}
              >
                (≈ {fpsIn})
              </Typography>
            )}
            {' · '}
            out{' '}
            <Typography component="span" variant="body2" sx={{ color: fpsOut == null ? '#888888' : '#00ff00' }}>
              {fpsOut == null ? '—' : fpsOut}
            </Typography>
          </Typography>
        </Box>

        {/* Blackscreen */}
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5 }}>
          <Typography variant="body2" sx={{ color: '#ffffff', mr: 1 }}>
            Blackscreen:
          </Typography>
          <Typography
            variant="body2"
            sx={{
              color: analysis?.blackscreen ? '#ff4444' : '#00ff00',
              fontWeight: analysis?.blackscreen ? 'bold' : 'normal',
            }}
          >
            {analysis?.blackscreen ? 'Yes' : 'No'}
            {analysis?.blackscreen && consecutiveErrorCounts && (
              <Typography component="span" variant="body2" sx={{ color: '#cccccc', ml: 1 }}>
                ({consecutiveErrorCounts.blackscreenConsecutive})
              </Typography>
            )}
            {analysis?.blackscreen && analysis.blackscreen_event_start && (
              <Typography component="span" variant="body2" sx={{ color: '#ffaaaa', ml: 1 }}>
                {formatTimestamp(analysis.blackscreen_event_start)}, {formatDuration(analysis.blackscreen_event_duration_ms)}
              </Typography>
            )}
            {/* Frame-change % (from the motion classifier) — a real black screen changes ~0%, so a
                high Δ next to a "Yes" exposes a false blackscreen. */}
            {analysis?.motion && (
              <Typography component="span" variant="body2" sx={{ color: '#888888', ml: 1 }}>
                Δ{analysis.motion.pct}%
              </Typography>
            )}
          </Typography>
        </Box>

        {/* Freeze */}
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5 }}>
          <Typography variant="body2" sx={{ color: '#ffffff', mr: 1 }}>
            Freeze:
          </Typography>
          <Typography
            variant="body2"
            sx={{
              color: analysis?.freeze ? '#ff4444' : '#00ff00',
              fontWeight: analysis?.freeze ? 'bold' : 'normal',
            }}
          >
            {analysis?.freeze ? 'Yes' : 'No'}
            {analysis?.freeze && consecutiveErrorCounts && (
              <Typography component="span" variant="body2" sx={{ color: '#cccccc', ml: 1 }}>
                ({consecutiveErrorCounts.freezeConsecutive})
              </Typography>
            )}
            {analysis?.freeze && analysis.freeze_event_start && (
              <Typography component="span" variant="body2" sx={{ color: '#ffaaaa', ml: 1 }}>
                {formatTimestamp(analysis.freeze_event_start)}, {formatDuration(analysis.freeze_event_duration_ms)}
              </Typography>
            )}
          </Typography>
        </Box>

        {/* Macroblocks */}
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5 }}>
          <Typography variant="body2" sx={{ color: '#ffffff', mr: 1 }}>
            Macroblocks:
          </Typography>
          <Typography
            variant="body2"
            sx={{
              color: analysis?.macroblocks ? '#ff4444' : '#00ff00',
              fontWeight: analysis?.macroblocks ? 'bold' : 'normal',
            }}
          >
            {analysis?.macroblocks ? 'Yes' : 'No'}
            {analysis?.macroblocks && consecutiveErrorCounts && (
              <Typography component="span" variant="body2" sx={{ color: '#cccccc', ml: 1 }}>
                ({consecutiveErrorCounts.macroblocksConsecutive})
              </Typography>
            )}
            {analysis?.macroblocks && analysis.macroblocks_event_start && (
              <Typography component="span" variant="body2" sx={{ color: '#ffaaaa', ml: 1 }}>
                {formatTimestamp(analysis.macroblocks_event_start)}, {formatDuration(analysis.macroblocks_event_duration_ms)}
              </Typography>
            )}
          </Typography>
        </Box>

        {/* Audio */}
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5 }}>
          <Typography variant="body2" sx={{ color: '#ffffff', mr: 1 }}>
            Audio:
          </Typography>
          <Typography
            variant="body2"
            sx={{
              color: !audioSupported ? '#9e9e9e' : analysis?.audio ? '#00ff00' : '#ff4444',
              fontWeight: !audioSupported ? 'normal' : analysis?.audio ? 'bold' : 'normal',
            }}
          >
            {!audioSupported ? 'N/A' : analysis?.audio ? 'Yes' : 'No'}
            {audioSupported &&
              typeof analysis?.mean_volume_db === 'number' &&
              analysis.mean_volume_db > -99 && (
                <Typography component="span" variant="body2" sx={{ color: '#cccccc', ml: 1 }}>
                  ({Math.round(analysis.mean_volume_db)} dB)
                </Typography>
              )}
            {audioSupported && !analysis?.audio && consecutiveErrorCounts && (
              <Typography component="span" variant="body2" sx={{ color: '#cccccc', ml: 1 }}>
                ({consecutiveErrorCounts.audioLossConsecutive})
              </Typography>
            )}
            {audioSupported && !analysis?.audio && analysis?.audio_event_start && (
              <Typography component="span" variant="body2" sx={{ color: '#ffaaaa', ml: 1 }}>
                {formatTimestamp(analysis.audio_event_start)}, {formatDuration(analysis.audio_event_duration_ms)}
              </Typography>
            )}
          </Typography>
        </Box>

        {/* Screen (Localize) - only shown when enabled for the device. Formatted via
            the SHARED formatScreenVerdict so it reads identically to the AVQ page.
            The trailing dim span is the DIAGNOSIS (which matcher layer answered, and
            why it abstained) — an operator must be able to tell a confident match from a
            guess. Grey, never red: an abstain is normal behaviour, not an error. */}
        {screenLabel && (
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5 }}>
            <Typography variant="body2" sx={{ color: '#ffffff', mr: 1 }}>
              Screen:
            </Typography>
            <Typography
              variant="body2"
              sx={{ color: screenLabel.color, fontWeight: 'bold' }}
            >
              {screenLabel.text}
            </Typography>
            {screenDiagnosis && (
              <Typography
                component="span"
                variant="body2"
                sx={{ color: screenDiagnosis.color, ml: 1, fontWeight: 'normal' }}
              >
                {[screenDiagnosis.tier, screenDiagnosis.door].filter(Boolean).join(' • ')}
              </Typography>
            )}
          </Box>
        )}

        {/* Motion - live TV vs moving UI (carousel / PiP) vs static. Only when classified. */}
        {analysis?.motion && (
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5 }}>
            <Typography variant="body2" sx={{ color: '#ffffff', mr: 1 }}>
              Motion:
            </Typography>
            <Typography
              variant="body2"
              sx={{
                color:
                  analysis.motion.state === 'live'
                    ? '#00e5ff'
                    : analysis.motion.state === 'motion'
                      ? '#66ccff'
                      : analysis.motion.state === 'blackscreen' || analysis.motion.state === 'no_signal'
                        ? '#ff4444'
                        : analysis.motion.state === 'static'
                          ? '#888888'
                          : '#cccccc',
                fontWeight: analysis.motion.state === 'live' ? 'bold' : 'normal',
              }}
            >
              {analysis.motion.state === 'ui'
                ? `ui${analysis.motion.pip ? ' • PiP' : ''}${analysis.motion.carousel ? ' • carousel' : ''}`
                : analysis.motion.state}
              <Typography component="span" variant="body2" sx={{ color: '#cccccc', ml: 1 }}>
                {analysis.motion.pct}%
              </Typography>
            </Typography>
          </Box>
        )}

        {/* Subtitles - always shown when enabled (N/A when empty) so the box
            doesn't shrink/grow as subtitles come and go between frames. */}
        {showSubtitles &&
          (subtitles?.subtitles_detected && subtitles?.combined_extracted_text ? (
            <Box sx={{ mb: 0.5 }}>
              <Typography
                variant="body2"
                sx={{
                  color: '#00ff00',
                  fontWeight: 'bold',
                  mb: 0.3,
                }}
              >
                {subtitles.detected_language
                  ? LANGUAGE_NAMES[subtitles.detected_language] || subtitles.detected_language.toUpperCase()
                  : 'Subtitles'}
                {subtitles.confidence ? ` (${Math.round(subtitles.confidence * 100)}%)` : ''}:
              </Typography>
              <Typography
                variant="body2"
                sx={{
                  color: '#cccccc',
                  ml: 1,
                  fontSize: TYPOGRAPHY.body.size,
                  fontStyle: 'italic',
                  whiteSpace: 'normal', // subtitle text may be long — allow wrapping
                }}
              >
                {subtitles.combined_extracted_text}
              </Typography>
            </Box>
          ) : (
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5 }}>
              <Typography variant="body2" sx={{ color: '#ffffff', mr: 1 }}>
                Subtitles:
              </Typography>
              <Typography variant="body2" sx={{ color: '#cccccc' }}>
                N/A
              </Typography>
            </Box>
          ))}

        {/* Language Menu - only shown when explicitly requested */}
        {showLanguageMenu && languageMenu?.menu_detected && (
          <Box sx={{ mb: 0.5 }}>
            {/* Audio Languages */}
            {languageMenu.audio_languages.length > 0 && (
              <Box sx={{ mb: 0.5 }}>
                <Typography variant="body2" sx={{ color: '#ffffff', mb: 0.3 }}>
                  Audio:
                </Typography>
                {languageMenu.audio_languages.map((lang, index) => (
                  <Typography
                    key={index}
                    variant="body2"
                    sx={{
                      color: index === languageMenu.selected_audio ? '#00ff00' : '#cccccc',
                      fontWeight: index === languageMenu.selected_audio ? 'bold' : 'normal',
                      ml: 1,
                      fontSize: TYPOGRAPHY.caption.size,
                    }}
                  >
                    {index}: {lang}
                    {index === languageMenu.selected_audio && <AppIcon name="success" />}
                  </Typography>
                ))}
              </Box>
            )}

            {/* Subtitle Languages */}
            {languageMenu.subtitle_languages.length > 0 && (
              <Box>
                <Typography variant="body2" sx={{ color: '#ffffff', mb: 0.3 }}>
                  Subtitles:
                </Typography>
                {languageMenu.subtitle_languages.map((lang, index) => (
                  <Typography
                    key={index}
                    variant="body2"
                    sx={{
                      color: index === languageMenu.selected_subtitle ? '#00ff00' : '#cccccc',
                      fontWeight: index === languageMenu.selected_subtitle ? 'bold' : 'normal',
                      ml: 1,
                      fontSize: TYPOGRAPHY.caption.size,
                    }}
                  >
                    {index}: {lang}
                    {index === languageMenu.selected_subtitle && <AppIcon name="success" />}
                  </Typography>
                ))}
              </Box>
            )}
          </Box>
        )}
      </Box>

      {/* Warning / error sit under the Localize chip (top-right of the video). */}
      {consecutiveErrorCounts?.hasWarning && !consecutiveErrorCounts?.hasError && (
        <Box
          sx={{
            position: 'absolute',
            top: 44,
            right: 6,
            zIndex: 20,
            p: 1,
            backgroundColor: 'rgba(255, 165, 0, 0.8)', // Orange
            borderRadius: 1,
            pointerEvents: 'none',
          }}
        >
          <Typography variant="caption" sx={{ color: '#ffffff', fontWeight: 'bold' }}>
            WARNING
          </Typography>
        </Box>
      )}

      {consecutiveErrorCounts?.hasError && (
        <Box
          sx={{
            position: 'absolute',
            top: 44,
            right: 6,
            zIndex: 20,
            p: 1,
            backgroundColor: 'rgba(255, 68, 68, 0.8)', // Red
            borderRadius: 1,
            pointerEvents: 'none',
          }}
        >
          <Typography variant="caption" sx={{ color: '#ffffff', fontWeight: 'bold' }}>
            ERROR
          </Typography>
        </Box>
      )}
      
      {/* Action History (includes zapping detection from frame JSON) */}
      <ActionHistory
        monitoringAnalysis={monitoringAnalysis}
      />
    </>
  );
};
