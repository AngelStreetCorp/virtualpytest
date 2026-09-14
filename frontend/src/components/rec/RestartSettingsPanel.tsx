import { Box, Typography, IconButton, Slide, Paper, Select, MenuItem, Collapse, CircularProgress, Button } from '@mui/material';
import { Close as CloseIcon, ExpandMore as ExpandMoreIcon, ExpandLess as ExpandLessIcon, VolumeUp as AudioIcon } from '@mui/icons-material';
import React, { useState } from 'react';

import { getLanguageName } from '../../utils/recUtils';

interface RestartSettingsPanelProps {
  open: boolean;
  onClose: () => void;
  // All data and functions now come from useRestart hook
  restartHookData: {
    analysisResults: any;
    translationResults: Record<string, any>;
    isTranslating: boolean;
    currentLanguage: string;
    translateToLanguage: (language: string) => Promise<void>;
    generateDubbedVersion?: (language: string, transcript: string, videoId: string) => Promise<void>;
    dubbedAudioUrls: Record<string, { gtts: string; edge: string }>;
    isDubbing?: boolean;
    videoId?: string;
    audioTimingOffset: number;
    isApplyingTiming: boolean;
    applyAudioTiming: (offsetMs: number) => Promise<void>;
  };
}

export const RestartSettingsPanel: React.FC<RestartSettingsPanelProps> = ({
  open,
  onClose,
  restartHookData,
}) => {
  // Extract data from hook
  const {
    analysisResults,
    translationResults,
    isTranslating,
    currentLanguage,
    translateToLanguage,
    dubbedAudioUrls,
    audioTimingOffset,
    isApplyingTiming,
    applyAudioTiming,
  } = restartHookData;
  // UI state only
  const [isVideoSummaryExpanded, setIsVideoSummaryExpanded] = useState(false);
  const [isTranscriptExpanded, setIsTranscriptExpanded] = useState(false);
  const [isFrameAnalysisExpanded, setIsFrameAnalysisExpanded] = useState(false);
  const [selectedTiming, setSelectedTiming] = useState(0);

  const currentTranslation = translationResults[currentLanguage] ?? null;

  return (
    <Slide direction="left" in={open} mountOnEnter unmountOnExit>
      <Paper
        sx={{
          position: 'absolute',
          top: 0,
          right: 0,
          width: 350,
          height: '100%',
          zIndex: 1000040,
          backgroundColor: 'rgba(0, 0, 0, 0.95)',
          color: '#ffffff',
          p: 3,
          overflowY: 'auto',
        }}
      >
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
          <Typography variant="h6" sx={{ fontSize: '1.1rem' }}>Settings</Typography>
          <IconButton onClick={onClose} sx={{ color: '#ffffff', p: 0.5 }}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </Box>

        {/* Global Language Selector */}
        <Box sx={{ 
          pb: 1.5, 
          mb: 1.5, 
          borderBottom: '1px solid rgba(255,255,255,0.2)' 
        }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography 
              variant="subtitle2" 
              sx={{ 
                fontSize: '0.85rem', 
                fontWeight: 600,
                minWidth: 'fit-content'
              }}
            >
              Language:
            </Typography>
            <Select
              value={currentLanguage}
              onChange={(e) => translateToLanguage(e.target.value)}
              size="small"
              disabled={isTranslating}
              sx={{ 
                minWidth: 120, 
                minHeight: 28,
                fontSize: '0.75rem',
                color: '#ffffff', 
                '& .MuiOutlinedInput-notchedOutline': { borderColor: 'rgba(255,255,255,0.3)' },
                '& .MuiSelect-select': { py: 0.5 }
              }}
            >
              <MenuItem value="en" sx={{ fontSize: '0.75rem' }}>English</MenuItem>
              <MenuItem value="es" sx={{ fontSize: '0.75rem' }}>Spanish</MenuItem>
              <MenuItem value="fr" sx={{ fontSize: '0.75rem' }}>French</MenuItem>
              <MenuItem value="de" sx={{ fontSize: '0.75rem' }}>German</MenuItem>
              <MenuItem value="it" sx={{ fontSize: '0.75rem' }}>Italian</MenuItem>
              <MenuItem value="pt" sx={{ fontSize: '0.75rem' }}>Portuguese</MenuItem>
            </Select>
            {isTranslating && (
              <CircularProgress 
                size={16} 
                sx={{ 
                  color: '#ffffff',
                  ml: 1
                }} 
              />
            )}
          </Box>
        </Box>

        {/* 1. Video Summary Section */}
        <Box sx={{ 
          pb: 1.5, 
          mb: 1.5, 
          borderBottom: '1px solid rgba(255,255,255,0.2)' 
        }}>
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.8 }}>
            <Typography 
              variant="subtitle2" 
              sx={{ 
                fontSize: '0.85rem', 
                fontWeight: 600,
                flex: 1,
                cursor: 'pointer'
              }}
              onClick={() => setIsVideoSummaryExpanded(!isVideoSummaryExpanded)}
            >
              Video Summary
            </Typography>
            {analysisResults.videoDescription?.video_summary && (
              <IconButton
                onClick={() => setIsVideoSummaryExpanded(!isVideoSummaryExpanded)}
                sx={{ color: '#ffffff', p: 0.25 }}
                size="small"
              >
                {isVideoSummaryExpanded ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
              </IconButton>
            )}
          </Box>
          
          {analysisResults.videoDescription?.video_summary && (
            <Collapse in={isVideoSummaryExpanded}>
              <Box sx={{ mt: 1 }}>
                <Typography variant="body2" sx={{ 
                  p: 1.5, 
                  fontSize: '0.75rem',
                  backgroundColor: 'rgba(255,255,255,0.15)', 
                  borderRadius: 1,
                  lineHeight: 1.3,
                  borderLeft: '3px solid #4CAF50'
                }}>
                  <strong>{currentLanguage === 'en' ? 'Original Summary:' : `Translated to ${getLanguageName(currentLanguage)}:`}</strong><br />
                  {currentLanguage === 'en' ? analysisResults.videoDescription.video_summary : (currentTranslation?.summary || analysisResults.videoDescription.video_summary || 'Translating...')}
                </Typography>
              </Box>
            </Collapse>
          )}
        </Box>

        {/* 2. Audio Transcript Section */}
        <Box sx={{ 
          pb: 1.5, 
          mb: 1.5, 
          borderBottom: '1px solid rgba(255,255,255,0.2)' 
        }}>
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.8 }}>
            <Typography 
              variant="subtitle2" 
              sx={{ 
                fontSize: '0.85rem', 
                fontWeight: 600,
                flex: 1,
                cursor: 'pointer'
              }}
              onClick={() => setIsTranscriptExpanded(!isTranscriptExpanded)}
            >
              Audio Transcript
            </Typography>
            {(analysisResults.audio?.combined_transcript || (analysisResults.audio && analysisResults.audio.speech_detected)) && (
              <IconButton
                onClick={() => setIsTranscriptExpanded(!isTranscriptExpanded)}
                sx={{ color: '#ffffff', p: 0.25 }}
                size="small"
              >
                {isTranscriptExpanded ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
              </IconButton>
            )}
          </Box>
          
          <Collapse in={isTranscriptExpanded}>
            <Box sx={{ mt: 1 }}>
              <Typography variant="body2" sx={{ 
                p: 1.5, 
                fontSize: '0.75rem',
                lineHeight: 1.4,
                backgroundColor: 'rgba(255,255,255,0.1)', 
                borderRadius: 1,
                borderLeft: '3px solid #FF9800'
              }}>
                <strong>
                  {currentLanguage === 'en' 
                    ? `Original (${getLanguageName(analysisResults.audio?.detected_language || 'Unknown')})` 
                    : `Translated to ${getLanguageName(currentLanguage)}`}:
                </strong><br />
                {currentLanguage === 'en' ? (analysisResults.audio?.combined_transcript || 'No transcript available') : (currentTranslation?.transcript || analysisResults.audio?.combined_transcript || 'Translating...')}
                
                {/* Audio preview link */}
                {currentLanguage !== 'en' && dubbedAudioUrls[currentLanguage] && (
                  <Box sx={{ mt: 1.5, pt: 1.5, borderTop: '1px solid rgba(255,255,255,0.2)' }}>
                      <Typography 
                        component="a" 
                        href={dubbedAudioUrls[currentLanguage].edge}
                        target="_blank"
                        sx={{ 
                          fontSize: '0.7rem', 
                          color: '#4FC3F7', 
                          textDecoration: 'underline',
                          cursor: 'pointer',
                          '&:hover': { color: '#29B6F6' }
                        }}
                      >
                        audio.mp3
                      </Typography>
                  </Box>
                )}
              </Typography>
            </Box>
          </Collapse>
        </Box>

        {/* 3. Frame Analysis Section */}
        <Box>
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.8 }}>
            <Typography 
              variant="subtitle2" 
              sx={{ 
                fontSize: '0.85rem', 
                fontWeight: 600,
                flex: 1,
                cursor: 'pointer'
              }}
              onClick={() => setIsFrameAnalysisExpanded(!isFrameAnalysisExpanded)}
            >
              Frame Analysis
            </Typography>
            {analysisResults.videoDescription?.frame_descriptions && analysisResults.videoDescription.frame_descriptions.length > 0 && (
              <IconButton
                onClick={() => setIsFrameAnalysisExpanded(!isFrameAnalysisExpanded)}
                sx={{ color: '#ffffff', p: 0.25 }}
                size="small"
              >
                {isFrameAnalysisExpanded ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
              </IconButton>
            )}
          </Box>
          
          
          {/* Frame Analysis Content */}
          <Collapse in={isFrameAnalysisExpanded}>
            <Box sx={{ mt: 1 }}>
              {/* Frame-by-frame analysis */}
              {analysisResults.videoDescription?.frame_descriptions && analysisResults.videoDescription.frame_descriptions.length > 0 && (
                <Box sx={{ mb: 1.5 }}>
                  {/* Subtitle Language Header (shown once at top) */}
                  {analysisResults.subtitles?.frame_subtitles && analysisResults.subtitles.frame_subtitles.some((sub: string) => {
                    const subtitleMatch = sub?.match(/^Frame \d+:\s*(.+)$/);
                    const subtitleContent = subtitleMatch ? subtitleMatch[1] : sub;
                    return subtitleContent && subtitleContent !== 'No subtitles detected';
                  }) && (
                    <Typography variant="body2" sx={{ 
                      fontSize: '0.7rem',
                      color: '#FF9800',
                      fontWeight: 600,
                      mb: 1,
                      p: 1,
                      backgroundColor: 'rgba(255, 152, 0, 0.1)',
                      borderRadius: 0.5,
                      borderLeft: '3px solid #FF9800'
                    }}>
                      Subtitles ({
                        currentLanguage !== 'en' && currentTranslation?.frameSubtitles.length > 0 
                          ? `Translated to ${getLanguageName(currentLanguage)}`
                          : (analysisResults.subtitles?.detected_language || 'Unknown').toUpperCase()
                      }):
                    </Typography>
                  )}
                  
                  {analysisResults.videoDescription.frame_descriptions.map((description: string, index: number) => {
                    // Use translated content if available, otherwise use original
                    const displayDescription = currentTranslation?.frameDescriptions[index] || description;
                    const displaySubtitle = currentTranslation?.frameSubtitles[index] || analysisResults.subtitles?.frame_subtitles?.[index];
                    
                    // Parse frame description to extract frame number and content
                    const frameMatch = displayDescription.match(/^Frame (\d+):\s*(.+)$/);
                    const frameNumber = frameMatch ? frameMatch[1] : (index + 1).toString();
                    const frameContent = frameMatch ? frameMatch[2] : displayDescription;
                    
                    // Get corresponding subtitle for this frame
                    const subtitleMatch = displaySubtitle?.match(/^Frame \d+:\s*(.+)$/);
                    const subtitleContent = subtitleMatch ? subtitleMatch[1] : displaySubtitle;
                    
                    return (
                      <Box 
                        key={index}
                        sx={{ 
                          mb: 1,
                          p: 1,
                          backgroundColor: 'rgba(255,255,255,0.08)', 
                          borderRadius: 0.5,
                          borderLeft: '2px solid #2196F3'
                        }}
                      >
                        <Typography variant="body2" sx={{ 
                          fontSize: '0.7rem',
                          fontWeight: 600,
                          color: '#2196F3',
                          mb: 0.5
                        }}>
                          Frame {frameNumber}:
                        </Typography>
                        
                        {subtitleContent && subtitleContent !== 'No subtitles detected' && (
                          <Typography variant="body2" sx={{ 
                            fontSize: '0.65rem',
                            color: '#FF9800',
                            fontStyle: 'italic',
                            mb: 0.5,
                            lineHeight: 1.2
                          }}>
                            {subtitleContent}
                          </Typography>
                        )}
                        
                        <Typography variant="body2" sx={{ 
                          fontSize: '0.65rem',
                          lineHeight: 1.3,
                          color: 'rgba(255,255,255,0.9)'
                        }}>
                          {frameContent}
                        </Typography>
                      </Box>
                    );
                  })}
                </Box>
              )}
              
            </Box>
          </Collapse>
        </Box>

        {/* 4. Audio Timing Section */}
        <Box sx={{ mt: 2, pt: 1.5, borderTop: '1px solid rgba(255,255,255,0.2)' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
            <AudioIcon sx={{ fontSize: '1rem', mr: 1, color: '#FF5722' }} />
            <Typography variant="subtitle2" sx={{ fontSize: '0.85rem', fontWeight: 600 }}>
              Audio Timing
            </Typography>
          </Box>
          
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Select
              value={selectedTiming}
              onChange={(e) => setSelectedTiming(Number(e.target.value))}
              size="small"
              disabled={isApplyingTiming}
              sx={{ 
                minWidth: 100, 
                fontSize: '0.75rem',
                color: '#ffffff',
                '& .MuiOutlinedInput-notchedOutline': { borderColor: 'rgba(255,255,255,0.3)' }
              }}
            >
              <MenuItem value={-300}>-300ms</MenuItem>
              <MenuItem value={-200}>-200ms</MenuItem>
              <MenuItem value={-100}>-100ms</MenuItem>
              <MenuItem value={0}>0ms</MenuItem>
              <MenuItem value={100}>+100ms</MenuItem>
              <MenuItem value={200}>+200ms</MenuItem>
              <MenuItem value={300}>+300ms</MenuItem>
            </Select>
            
            <Button
              onClick={() => applyAudioTiming(selectedTiming)}
              disabled={isApplyingTiming || selectedTiming === audioTimingOffset}
              size="small"
              variant="outlined"
              sx={{ 
                fontSize: '0.7rem', 
                minWidth: 50,
                color: '#ffffff',
                borderColor: 'rgba(255,255,255,0.3)'
              }}
            >
              {isApplyingTiming ? <CircularProgress size={14} /> : 'OK'}
            </Button>
          </Box>
          
          {audioTimingOffset !== 0 && (
            <Typography variant="caption" sx={{ 
              fontSize: '0.65rem', 
              color: '#FF5722', 
              mt: 0.5, 
              display: 'block' 
            }}>
              Current: {audioTimingOffset > 0 ? '+' : ''}{audioTimingOffset}ms
            </Typography>
          )}
        </Box>
      </Paper>
    </Slide>
  );
};
