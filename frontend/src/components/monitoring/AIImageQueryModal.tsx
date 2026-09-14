import { Close as CloseIcon, Send as SendIcon } from '@mui/icons-material';
import { Box, TextField, Button, CircularProgress, Typography, IconButton } from '@mui/material';
import React, { useState } from 'react';

import { buildServerUrl, resolveImageSourceUrl } from '../../utils/buildUrlUtils';
import { Host, Device } from '../../types/common/Host_Types';

interface AIImageQueryModalProps {
  isVisible: boolean;
  imageUrl: string | null;
  host: Host;
  device: Device;
  onClose: () => void;
}

export const AIImageQueryModal: React.FC<AIImageQueryModalProps> = ({
  isVisible,
  imageUrl,
  host,
  device,
  onClose,
}) => {
  const [query, setQuery] = useState('');
  const [response, setResponse] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  if (!isVisible || !imageUrl) return null;

  const normalizedImageUrl = resolveImageSourceUrl(host, imageUrl, device?.device_id);

  const handleSubmit = async () => {
    if (!query.trim()) return;
    
    setIsLoading(true);
    try {
      const res = await fetch(buildServerUrl('/server/verification/video/analyzeImageAI'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          host_name: host.host_name,
          device_id: device?.device_id || 'device1',
          image_source_url: normalizedImageUrl,
          query: query.trim(),
        }),
      });
      
      const result = await res.json();
      setResponse(result.response || 'No response');
    } catch (error) {
      setResponse('Error: Could not analyze image');
    }
    setIsLoading(false);
  };

  const handleClose = () => {
    setQuery('');
    setResponse('');
    onClose();
  };

  return (
    <Box
      sx={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000100,
        backgroundColor: 'rgba(0, 0, 0, 0.9)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        p: 2,
      }}
      onClick={handleClose}
    >
      <Box
        sx={{
          maxWidth: '800px',
          width: '100%',
          backgroundColor: '#1a1a1a',
          borderRadius: 2,
          p: 1,
          display: 'flex',
          flexDirection: 'column',
          gap: 1,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography variant="h6" sx={{ color: '#fff' }}>Ask AI</Typography>
          <IconButton onClick={handleClose} size="small" sx={{ color: '#fff' }}>
            <CloseIcon />
          </IconButton>
        </Box>

        {/* Image */}
        <Box
          component="img"
          src={normalizedImageUrl}
          sx={{
            width: '100%',
            maxHeight: '400px',
            objectFit: 'contain',
            borderRadius: 1,
            border: '1px solid rgba(255,255,255,0.1)',
          }}
        />

        {/* Query Input */}
        <Box sx={{ display: 'flex', gap: 1 }}>
          <TextField
            fullWidth
            size="small"
            placeholder="Ask about this image..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSubmit();
              }
            }}
            disabled={isLoading}
            sx={{
              '& .MuiOutlinedInput-root': {
                backgroundColor: 'rgba(0, 0, 0, 0.5)',
                '& fieldset': { borderColor: '#444' },
                '&:hover fieldset': { borderColor: '#666' },
                '&.Mui-focused fieldset': { borderColor: '#2196f3' },
              },
              '& .MuiInputBase-input': {
                color: '#fff',
                '&::placeholder': { color: '#888', opacity: 1 },
              },
            }}
          />
          <Button
            variant="contained"
            onClick={handleSubmit}
            disabled={!query.trim() || isLoading}
            startIcon={isLoading ? <CircularProgress size={16} /> : <SendIcon />}
            sx={{ minWidth: '100px' }}
          >
            {isLoading ? 'Asking...' : 'Ask'}
          </Button>
        </Box>

        {/* Response */}
        {response && (
          <Box
            sx={{
              p: 2,
              backgroundColor: 'rgba(33, 150, 243, 0.1)',
              borderRadius: 1,
              border: '1px solid rgba(33, 150, 243, 0.3)',
            }}
          >
            <Typography variant="body2" sx={{ color: '#fff', whiteSpace: 'pre-wrap' }}>
              {response}
            </Typography>
          </Box>
        )}
      </Box>
    </Box>
  );
};
