import { Box, Typography, CircularProgress, Alert, IconButton, Tooltip } from '@mui/material';
import { Settings as SettingsIcon, Assessment as ReportIcon } from '@mui/icons-material';
import React, { useRef, useState, useMemo } from 'react';

import { useRestart } from '../../hooks/pages/useRestart';
import { Host, Device } from '../../types/common/Host_Types';

import { RestartSettingsPanel } from './RestartSettingsPanel';
import { RestartSubtitleOverlay } from './RestartSubtitleOverlay';


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
  const getIcon = (state: string) => {
    switch (state) {
      case 'completed': return '✓';
      case 'error': return '✗';
      case 'loading': return <CircularProgress size={12} sx={{ color: 'white' }} />;
      default: return '○';
    }
  };

  const getColor = (state: string) => {
    switch (state) {
      case 'completed': return '#4CAF50';
      case 'error': return '#f44336';
      case 'loading': return '#2196F3';
      default: return 'rgba(255, 255, 255, 0.5)';
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
        border: '1px solid rgba(255, 255, 255, 0.2)',
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
              fontSize: '11px',
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
        backgroundColor: '#000000',
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
            color: 'white',
            gap: 2,
          }}
        >
          <CircularProgress sx={{ color: 'white' }} />
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
            color: 'white',
            gap: 2,
            p: 3,
          }}
        >
          <Alert severity="error" sx={{ backgroundColor: 'rgba(211, 47, 47, 0.1)' }}>
            <Typography color="white">Failed to generate restart video</Typography>
            <Typography variant="caption" color="white" sx={{ opacity: 0.8 }}>
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
                color: '#ffffff',
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
                color: '#ffffff',
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