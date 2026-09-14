import { Box, Typography, CircularProgress } from '@mui/material';
import React from 'react';

import { MonitoringAnalysis, SubtitleAnalysis, LanguageMenuAnalysis } from '../../types/pages/Monitoring_Types';
import { formatScreenVerdict } from '../../utils/screenVerdict';
import { ActionHistory } from './ActionHistory';

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
}) => {
  // Use separate data sources
  const analysis = monitoringAnalysis;
  const subtitles = subtitleAnalysis;
  const languageMenu = languageMenuAnalysis;

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
    } catch (error) {
      return 'Unknown';
    }
  };

  // Format duration (ms -> "1.5s")
  const formatDuration = (ms?: number): string => {
    if (!ms) return '0s';
    return `${(ms / 1000).toFixed(1)}s`;
  };

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

      {/* Main analysis overlay - left aligned */}
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
          <Typography variant="body2" sx={{ color: '#ffffff', mb: 0.5 }}>
            {formatTimestamp(analysisTimestamp)}
          </Typography>
        )}

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
            the SHARED formatScreenVerdict so it reads identically to the AVQ page. */}
        {analysis?.localize && (
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5 }}>
            <Typography variant="body2" sx={{ color: '#ffffff', mr: 1 }}>
              Screen:
            </Typography>
            <Typography
              variant="body2"
              sx={{ color: formatScreenVerdict(analysis.localize).color, fontWeight: 'bold' }}
            >
              {formatScreenVerdict(analysis.localize).text}
            </Typography>
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
                  fontSize: '0.85rem',
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
                      fontSize: '0.75rem',
                    }}
                  >
                    {index}: {lang}
                    {index === languageMenu.selected_audio && ' ✓'}
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
                      fontSize: '0.75rem',
                    }}
                  >
                    {index}: {lang}
                    {index === languageMenu.selected_subtitle && ' ✓'}
                  </Typography>
                ))}
              </Box>
            )}
          </Box>
        )}
      </Box>

      {/* Warning indicator - top right for 1-2 consecutive errors */}
      {consecutiveErrorCounts?.hasWarning && !consecutiveErrorCounts?.hasError && (
        <Box
          sx={{
            position: 'absolute',
            top: 16,
            right: 66, // 50px more from right edge to avoid online status
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

      {/* Error indicator - top right for 3+ consecutive errors */}
      {consecutiveErrorCounts?.hasError && (
        <Box
          sx={{
            position: 'absolute',
            top: 16,
            right: 66, // 50px more from right edge to avoid online status
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
