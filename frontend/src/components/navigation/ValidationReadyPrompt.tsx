import React from 'react';
import {
  Box,
  Paper,
  Typography,
  Button,
  IconButton,
  keyframes
} from '@mui/material';
import {
  PlayArrow as StartIcon,
  Close as CancelIcon
} from '@mui/icons-material';
import { useAgentChatPalette } from '../../constants/agentChatTheme';

interface ValidationReadyPromptProps {
  nodesCreated: number;
  edgesCreated: number;
  onStartValidation: () => void;
  onCancel: () => void;
}

// Blinking animation for Start Validation button
const blink = keyframes`
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
`;

export const ValidationReadyPrompt: React.FC<ValidationReadyPromptProps> = ({
  nodesCreated,
  edgesCreated,
  onStartValidation,
  onCancel
}) => {
  const P = useAgentChatPalette();
  return (
    <Paper
      elevation={8}
      sx={{
        position: 'fixed',
        top: 80,
        right: 20,
        width: 320,
        p: 2,
        zIndex: 1300,
        bgcolor: 'background.paper',
        border: '2px solid',
        borderColor: P.accent,
        borderRadius: 2
      }}
    >
      {/* Close button */}
      <IconButton
        onClick={onCancel}
        size="small"
        sx={{
          position: 'absolute',
          top: 8,
          right: 8
        }}
      >
        <CancelIcon fontSize="small" />
      </IconButton>

      {/* Header */}
      <Typography variant="h6" sx={{ mb: 2, pr: 3 }}>
        ✅ Preview
      </Typography>

      {/* Stats */}
      <Box sx={{ mb: 2, p: 1.5, bgcolor: `${P.success}0d`, borderRadius: 1 }}>
        <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
          📊 {nodesCreated} nodes created
        </Typography>
        <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
          📊 {edgesCreated} edges created
        </Typography>
      </Box>

      {/* Actions */}
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        <Button
          variant="contained"
          size="large"
          fullWidth
          startIcon={<StartIcon />}
          onClick={onStartValidation}
          sx={{
            animation: `${blink} 1.5s ease-in-out infinite`,
            fontSize: '1rem',
            fontWeight: 'bold'
          }}
        >
          Start Validation
        </Button>
        
        <Button
          variant="outlined"
          size="small"
          fullWidth
          onClick={onCancel}
          color="error"
        >
          Cancel
        </Button>
      </Box>
    </Paper>
  );
};

