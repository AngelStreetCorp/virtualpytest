import React, { useState } from 'react';
import { Box, Typography, IconButton, Menu, MenuItem, CircularProgress } from '@mui/material';
import { Headphones, Language } from '@mui/icons-material';

interface TranscriptOverlayProps {
  transcriptText: string;
  selectedLanguage?: string;
  availableLanguages?: string[];
  availableDubbedLanguages?: string[];
  onLanguageChange?: (language: string) => void;
  isTranslating?: boolean;
  show: boolean;
  hasMp3?: boolean;
  mp3Url?: string | null;
}

export const TranscriptOverlay: React.FC<TranscriptOverlayProps> = ({
  transcriptText,
  selectedLanguage = 'original',
  availableLanguages = ['original'],
  availableDubbedLanguages = [],
  onLanguageChange,
  isTranslating = false,
  show,
  hasMp3,
  mp3Url,
}) => {
  const [languageMenuAnchor, setLanguageMenuAnchor] = useState<null | HTMLElement>(null);
  
  if (!show || !transcriptText) {
    return null;
  }

  const handleMp3Click = () => {
    if (mp3Url) {
      window.open(mp3Url, '_blank');
    }
  };
  
  const handleLanguageClick = (event: React.MouseEvent<HTMLElement>) => {
    setLanguageMenuAnchor(event.currentTarget);
  };

  const handleLanguageClose = () => {
    setLanguageMenuAnchor(null);
  };

  const handleLanguageSelect = (language: string) => {
    if (onLanguageChange) {
      onLanguageChange(language);
    }
    setLanguageMenuAnchor(null);
  };
  
  const languageNames: { [key: string]: string } = {
    'original': 'Original',
    'en': 'English',
    'fr': 'Français',
    'es': 'Español',
    'de': 'Deutsch',
    'it': 'Italiano'
  };
  
  const allLanguages = ['original', 'fr', 'en', 'es', 'de', 'it'];

  return (
    <>
      {isTranslating && (
        <Box
          sx={{
            position: 'fixed',
            top: 200,
            right: 16,
            zIndex: 1250,
            backgroundColor: 'rgba(0, 0, 0, 0.85)',
            color: 'white',
            padding: '12px 16px',
            borderRadius: '8px',
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
          }}
        >
          <CircularProgress size={20} sx={{ color: '#2196f3' }} />
          <Typography variant="caption" sx={{ fontSize: '13px', fontWeight: 500 }}>
            🤖 AI translating...
          </Typography>
        </Box>
      )}
      
      {hasMp3 && mp3Url && (
        <IconButton
          onClick={handleMp3Click}
          title="Download MP3"
          sx={{
            position: 'fixed',
            top: 140,
            right: 56,
            backgroundColor: 'rgba(0, 0, 0, 0.7)',
            color: 'white',
            zIndex: 1250,
            '&:hover': { backgroundColor: 'rgba(0, 0, 0, 0.85)' },
          }}
        >
          <Headphones />
        </IconButton>
      )}

      <IconButton
        onClick={handleLanguageClick}
        disabled={isTranslating}
        title="Language (Audio + Subtitles)"
        sx={{
          position: 'fixed',
          top: 140,
          right: 50,
          backgroundColor: 'rgba(33, 150, 243, 0.8)',
          color: 'white',
          zIndex: 1250,
          '&:hover': { backgroundColor: 'rgba(33, 150, 243, 0.95)' },
          '&.Mui-disabled': { backgroundColor: 'rgba(33, 150, 243, 0.5)', color: 'rgba(255, 255, 255, 0.5)' },
        }}
      >
        <Language />
      </IconButton>
      
      <Menu
        anchorEl={languageMenuAnchor}
        open={Boolean(languageMenuAnchor)}
        onClose={handleLanguageClose}
        sx={{
          '& .MuiPaper-root': {
            backgroundColor: 'rgba(0, 0, 0, 0.9)',
            color: 'white',
          },
        }}
      >
        {allLanguages.map((lang) => {
          const isCached = availableLanguages.includes(lang);
          const hasAudio = availableDubbedLanguages.includes(lang) || lang === 'original';
          return (
            <MenuItem
              key={lang}
              onClick={() => handleLanguageSelect(lang)}
              selected={lang === selectedLanguage}
              sx={{
                '&:hover': { backgroundColor: 'rgba(255, 255, 255, 0.1)' },
                '&.Mui-selected': {
                  backgroundColor: 'rgba(33, 150, 243, 0.3)',
                  '&:hover': { backgroundColor: 'rgba(33, 150, 243, 0.4)' },
                },
              }}
            >
              {languageNames[lang] || lang.toUpperCase()}
              {lang === selectedLanguage && ' ✓'}
              {!isCached && lang !== 'original' && ' 🤖'}
              {hasAudio && ' 🎤'}
            </MenuItem>
          );
        })}
      </Menu>

      <Box
        sx={{
          position: 'fixed',
          bottom: 80,
          left: '50%',
          transform: 'translateX(-50%)',
          backgroundColor: 'rgba(0, 0, 0, 0.85)',
          color: 'white',
          px: 2,
          py: 1,
          borderRadius: 1,
          maxWidth: 'calc(100% - 80px)',
          width: 'fit-content',
          display: 'inline-flex',
          textAlign: 'center',
          border: '1px solid rgba(255, 255, 255, 0.3)',
          boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
          zIndex: 1250,
        }}
      >
        <Typography 
          variant="body1" 
          sx={{ 
            fontWeight: 500, 
            lineHeight: 1.3,
            fontSize: '0.95rem',
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {transcriptText}
        </Typography>
      </Box>
    </>
  );
};
