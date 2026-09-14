import { AppBar, Toolbar, Typography, Box } from '@mui/material';
import React from 'react';

import { useBranding } from '../../contexts/BrandingContext';
import { isAuthEnabled } from '../../lib/supabase';
import ThemeToggle from './ThemeToggle';

const Header: React.FC = () => {
  const { branding } = useBranding();

  return (
    <>
    {!isAuthEnabled ? (
      <Box
        role="alert"
        sx={{ bgcolor: 'warning.main', color: 'warning.contrastText', px: 2, py: 0.25, fontSize: '0.75rem', textAlign: 'center' }}
      >
        Open mode: authentication is disabled, every visitor is admin. Do not expose this deployment to the
        internet. See docs/get-started/production-checklist.md.
      </Box>
    ) : null}
    <AppBar 
      position="static" 
      elevation={1} 
      sx={{ 
        borderRadius: '0 !important',
        borderTopLeftRadius: '0 !important',
        borderTopRightRadius: '0 !important',
        borderBottomLeftRadius: '0 !important',
        borderBottomRightRadius: '0 !important',
        '& .MuiPaper-root': {
          borderRadius: '0 !important',
        }
      }}
    >
      <Toolbar sx={{ minHeight: { xs: 36, sm: 40, md: 64 }, px: { xs: 1, sm: 2 } }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexGrow: 1 }}>
          {branding.logoUrl ? (
            <Box
              component="img"
              src={branding.logoUrl}
              alt={`${branding.name} logo`}
              sx={{ height: { xs: 18, sm: 22, md: 28 }, width: 'auto', maxWidth: 160, objectFit: 'contain' }}
            />
          ) : null}
          {branding.showProjectName ? (
            <Typography variant="h6" component="div" sx={{ fontSize: { xs: '0.85rem', sm: '1rem', md: '1.25rem' } }}>
              {branding.name}
            </Typography>
          ) : null}
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center' }}>
          <ThemeToggle />
        </Box>
      </Toolbar>
    </AppBar>
    </>
  );
};

export default Header;
