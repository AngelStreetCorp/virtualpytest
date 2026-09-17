import { DesktopWindows as DesktopWindowsIcon } from '@mui/icons-material';
import { Box, Typography } from '@mui/material';
import React from 'react';

interface DesktopOnlyPlaceholderProps {
  title: string;
}

/**
 * Simple placeholder shown on mobile web for pages that only have a dense,
 * desktop-oriented layout today. Swap this out once a real mobile-specific
 * design exists for the page.
 */
const DesktopOnlyPlaceholder: React.FC<DesktopOnlyPlaceholderProps> = ({ title }) => (
  <Box
    sx={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      py: 8,
      px: 3,
      textAlign: 'center',
    }}
  >
    <DesktopWindowsIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 2 }} />
    <Typography variant="h6" color="text.secondary" gutterBottom>
      {title}
    </Typography>
    <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 400 }}>
      This page isn't optimized for mobile yet — please use a desktop browser for the full
      experience.
    </Typography>
  </Box>
);

export default DesktopOnlyPlaceholder;
