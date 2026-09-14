import { Box, Typography } from '@mui/material';
import React, { useState, useEffect } from 'react';

const FRAME_PREFIX_REGEX = /^Frame \d+: /;

interface RestartSubtitleOverlayProps {
  videoRef?: React.RefObject<HTMLVideoElement>;
  frameSubtitles?: string[];
}

export const RestartSubtitleOverlay: React.FC<RestartSubtitleOverlayProps> = ({
  videoRef,
  frameSubtitles,
}) => {
  const [currentSubtitle, setCurrentSubtitle] = useState<string>('');

  useEffect(() => {
    if (!videoRef?.current || !frameSubtitles?.length) return;

    const video = videoRef.current;
    
    const updateSubtitle = () => {
      const currentTime = Math.floor(video.currentTime);
      const subtitle = frameSubtitles[currentTime] || '';
      // Remove "Frame X: " prefix and show only the subtitle text
      const cleanSubtitle = subtitle.replace(FRAME_PREFIX_REGEX, '');
      setCurrentSubtitle(cleanSubtitle === 'No subtitles detected' ? '' : cleanSubtitle);
    };

    video.addEventListener('timeupdate', updateSubtitle);
    return () => video.removeEventListener('timeupdate', updateSubtitle);
  }, [videoRef, frameSubtitles]);

  if (!currentSubtitle) return null;

  // Simple fixed subtitle style - no customization needed
  const subtitleStyle = {
    color: '#ffff00',
    backgroundColor: 'rgba(0, 0, 0, 0.8)',
    textShadow: '2px 2px 4px rgba(0,0,0,0.8)',
  };

  return (
    <Box
      sx={{
        position: 'absolute',
        bottom: 60,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 1000020,
        maxWidth: '90%',
        textAlign: 'center',
      }}
    >
      <Typography
        variant="body1"
        sx={{
          backgroundColor: subtitleStyle.backgroundColor,
          color: subtitleStyle.color,
          p: 1.5,
          borderRadius: 1,
          fontSize: '1.1rem',
          fontWeight: 500,
          textShadow: subtitleStyle.textShadow,
        }}
      >
        {currentSubtitle}
      </Typography>
    </Box>
  );
};
