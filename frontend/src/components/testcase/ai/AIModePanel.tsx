import React from 'react';
import { Box, Typography, TextField, Button } from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import VisibilityIcon from '@mui/icons-material/Visibility';

interface AIModePanelProps {
  aiPrompt?: string;
  setAiPrompt?: (prompt: string) => void;
  isGenerating?: boolean;
  handleGenerateWithAI?: () => void;
  hasLastGeneration?: boolean;
  handleShowLastGeneration?: () => void;
  isControlActive?: boolean;
}

export const AIModePanel: React.FC<AIModePanelProps> = ({
  aiPrompt = '',
  setAiPrompt = () => {},
  isGenerating = false,
  handleGenerateWithAI = () => {},
  hasLastGeneration = false,
  handleShowLastGeneration = () => {},
  isControlActive = true,
}) => {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, p: 1.5, flex: 1, overflowY: 'auto' }}>
      <Typography variant="subtitle2" fontWeight="bold">
        AI Test Generator
      </Typography>
      <TextField
        multiline
        rows={6}
        placeholder={
          isControlActive
            ? "e.g., Go to live TV and verify audio is playing"
            : "Take control of the device first to enter a prompt"
        }
        value={aiPrompt}
        onChange={(e) => setAiPrompt(e.target.value)}
        size="small"
        fullWidth
        disabled={!isControlActive || isGenerating}
      />
      
      {/* Action Buttons */}
      <Box sx={{ display: 'flex', gap: 1 }}>
        <Button
          variant="contained"
          startIcon={<AutoAwesomeIcon />}
          onClick={handleGenerateWithAI}
          disabled={!isControlActive || isGenerating || !aiPrompt.trim()}
          fullWidth
          size="small"
        >
          {isGenerating ? 'Generating...' : 'Generate'}
        </Button>
        
        {hasLastGeneration && (
          <Button
            variant="outlined"
            startIcon={<VisibilityIcon />}
            onClick={handleShowLastGeneration}
            size="small"
            sx={{ minWidth: '120px' }}
          >
            View Last
          </Button>
        )}
      </Box>
      
      {/* Sample prompts */}
      <Box sx={{ mt: 1 }}>
        <Typography variant="caption" fontWeight="bold" color="text.secondary">
          Examples:
        </Typography>
        {[
          'Go to live TV and check audio',
          'Navigate to settings',
          'Play first recording'
        ].map((example, idx) => (
          <Typography
            key={idx}
            variant="caption"
            sx={{
              display: 'block',
              mt: 0.5,
              cursor: 'pointer',
              color: 'primary.main',
              '&:hover': { textDecoration: 'underline' }
            }}
            onClick={() => setAiPrompt(example)}
          >
            • {example}
          </Typography>
        ))}
      </Box>
    </Box>
  );
};

