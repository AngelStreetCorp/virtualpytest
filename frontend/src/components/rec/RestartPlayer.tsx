import { AppIcon } from '../../constants/icons';
import { Box, Typography, CircularProgress, Alert, IconButton, Tooltip } from '@mui/material';
import { Settings as SettingsIcon, Assessment as ReportIcon } from '@mui/icons-material';
import React, { useRef, useState, useMemo } from 'react';

import { useRestart } from '../../hooks/pages/useRestart';
import { Host, Device } from '../../types/common/Host_Types';
import { useAgentChatPalette } from '../../constants/agentChatTheme';

import { RestartSettingsPanel } from './RestartSettingsPanel';
import { RestartSubtitleOverlay } from './RestartSubtitleOverlay';
import { TYPOGRAPHY } from '../../constants/typography';


// Analysis Progress Component
interface AnalysisProgressProps {
  progress: {
    video: 'idle' | 'loading' | 'completed' | 'error';
    audio: 'idle' | 'loading' | 'completed' | 'error';
    subtitles: 'idle' | 'loading' | 'completed' | 'error';
    summary: 'idle' | 'loading' | 'completed' | 'error';
  };
}

const AnalysisProgress: React.FC<AnalysisProgressProps> = ({ progress }) => {
  const P = useAgentChatPalette();
  const getIcon = (state: string) => {
    switch (state) {
      case 'completed': return <AppIcon name="success" />;
      case 'error': return <AppIcon name="error" />;
      case 'loading': return <CircularProgress size={12} sx={{ color: P.textPrimary }} />;
      default: return '○';
    }
  };

  const getColor = (state: string) => {
    switch (state) {
      case 'completed': return P.success;
      case 'error': return P.error;
      case 'loading': return P.accentText;
      default: return P.textMuted;
    }
  };

  return (
    <Box
      sx={{
        position: 'absolute',
        top: 16,
        right: 16,
        zIndex: 1000030,
        backgroundColor: 'rgba(0, 0, 0, 0.8)',
        borderRadius: 2,
        padding: 1.5,
        minWidth: 120,
        border: `1px solid ${P.borderColor}`,
      }}
    >
      {[
        { key: 'audio', label: 'Audio' },
        { key: 'subtitles', label: 'Subtitles' },
        { key: 'summary', label: 'Summary' },
      ].map(({ key, label }) => (
        <Box key={key} sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
          <Box sx={{ width: 16, height: 16, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            {getIcon(progress[key as keyof typeof progress])}
          </Box>
          <Typography
            variant="caption"
            sx={{
              color: getColor(progress[key as keyof typeof progress]),
              fontSize: TYPOGRAPHY.microMeta.size,
              fontWeight: 500,
            }}
          >
            {label}
          </Typography>
        </Box>
      ))}
    </Box>
  );
};

interface RestartPlayerProps {
  host: Host;
  device: Device;
  includeAudioAnalysis?: boolean;
}

export const RestartPlayer: React.FC<RestartPlayerProps> = ({ host, device, includeAudioAnalysis }) => {

  const P = useAgentChatPalette();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  
  
  const restartHookData = useRestart({ 
    host, 
    device, 
    includeAudioAnalysis 
  });
  
  const { 
    videoUrl, 
    isGenerating, 
    isReady, 
    error, 
    analysisResults, 
    isAnalysisComplete, 
    reportUrl, 
    analysisProgress,
    dubbedVideos,
    currentLanguage,
    translationResults
  } = restartHookData;

  // Smart video source selection - use dubbed video if available, otherwise original
  const currentVideoUrl = useMemo(() => {
    if (currentLanguage === 'en') return videoUrl; // Always use original for English
    return dubbedVideos[currentLanguage] || videoUrl; // Use dubbed if available, fallback to original
  }, [currentLanguage, videoUrl, dubbedVideos]);

  // Smart subtitle selection - use translated subtitles if available, otherwise original
  const currentSubtitles = useMemo(() => {
    if (currentLanguage === 'en') {
      return analysisResults.subtitles?.frame_subtitles; // Use original for English
    }
    // Use translated subtitles if available, fallback to original
    return translationResults[currentLanguage]?.frameSubtitles || analysisResults.subtitles?.frame_subtitles;
  }, [currentLanguage, translationResults, analysisResults.subtitles?.frame_subtitles]);

  // Dubbing is now handled by RestartSettingsPanel after translation completes

  return (
    <Box
      sx={{
        position: 'relative',
        width: '100%',
        height: '100%',
        backgroundColor: P.background,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
        '& .MuiCard-root': {
          height: '100%',
          borderRadius: 0,
          border: 'none',
        },
      }}
    >
      {/* Video generation loading state */}
      {isGenerating && (
        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            color: P.textPrimary,
            gap: 2,
          }}
        >
          <CircularProgress sx={{ color: P.textPrimary }} />
          <Typography>Generating restart video...</Typography>
        </Box>
      )}

      {/* Error state */}
      {error && !isGenerating && (
        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            color: P.textPrimary,
            gap: 2,
            p: 3,
          }}
        >
          <Alert severity="error" sx={{ backgroundColor: `${P.error}1f` }}>
            <Typography sx={{ color: P.textPrimary }}>Failed to generate restart video</Typography>
            <Typography variant="caption" sx={{ color: P.textPrimary, opacity: 0.8 }}>
              {error}
            </Typography>
          </Alert>
        </Box>
      )}

      {/* Simple video player - ready state (FAST LAUNCH) */}
      {isReady && currentVideoUrl && !isGenerating && (
        <video
          ref={videoRef}
          src={currentVideoUrl}
          controls
          autoPlay
          muted={false}
          preload="auto"
          onError={(e) => console.error('[@component:RestartPlayer] Video error:', e)}
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: '100%',
            height: '100%',
            objectFit: 'contain',
            objectPosition: 'top center',
            zIndex: 1,
          }}
        />
      )}

      {/* Subtitle overlay */}
      {currentSubtitles && (
        <RestartSubtitleOverlay
          videoRef={videoRef}
          frameSubtitles={currentSubtitles}
        />
      )}

      {/* Analysis Progress Indicator (shows after video appears, until analysis complete) */}
      {isReady && includeAudioAnalysis && !isAnalysisComplete && (
        <AnalysisProgress progress={analysisProgress} />
      )}

      {/* Settings and Report Buttons (appears when everything is complete) */}
      {isReady && !isGenerating && (!includeAudioAnalysis || isAnalysisComplete) && (
        <Box sx={{ position: 'absolute', top: 16, right: 16, zIndex: 1000030, display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Tooltip title="Link Report" placement="left">
            <IconButton
              onClick={() => {
                // Open report in new tab using dynamic URL from backend
                if (reportUrl) {
                  window.open(reportUrl, '_blank');
                } else {
                  console.warn('Report URL not available yet - analysis may still be in progress');
                }
              }}
              disabled={!reportUrl}
              sx={{
                backgroundColor: 'rgba(0, 0, 0, 0.7)',
                color: P.textPrimary,
                '&:hover': { backgroundColor: 'rgba(0, 0, 0, 0.9)' },
              }}
            >
              <ReportIcon />
            </IconButton>
          </Tooltip>

          <Tooltip title="Settings" placement="left">
            <IconButton
              onClick={() => setSettingsOpen(true)}
              sx={{
                backgroundColor: 'rgba(0, 0, 0, 0.7)',
                color: P.textPrimary,
                '&:hover': { backgroundColor: 'rgba(0, 0, 0, 0.9)' },
              }}
            >
              <SettingsIcon />
            </IconButton>
          </Tooltip>
        </Box>
      )}

      {/* Settings Panel */}
      <RestartSettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        restartHookData={restartHookData}
      />
    </Box>
  );
};