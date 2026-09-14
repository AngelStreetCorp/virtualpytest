import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Box, CircularProgress, Typography, Alert } from '@mui/material';
import { supabase } from '../../lib/supabase';

/**
 * Auth Callback Component
 * Handles the OAuth redirect after successful authentication
 * Processes the session from URL hash parameters
 */
export const AuthCallback: React.FC = () => {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const handleAuthCallback = async () => {
      try {
        console.log('[@AuthCallback] Processing OAuth callback...');
        console.log('[@AuthCallback] URL:', window.location.href);
        
        // Supabase automatically processes the hash fragment
        // We just need to check if it worked
        const { data: { session }, error: sessionError } = await supabase.auth.getSession();
        
        if (sessionError) {
          console.error('[@AuthCallback] Session error:', sessionError);
          setError(sessionError.message);
          // Redirect to login after showing error
          setTimeout(() => navigate('/login', { replace: true }), 3000);
          return;
        }

        if (session) {
          console.log('[@AuthCallback] Session obtained successfully:', session.user.email);
          // Session is ready, redirect to home
          setTimeout(() => navigate('/', { replace: true }), 1000);
        } else {
          console.warn('[@AuthCallback] No session found after callback');
          setError('No session found. Please try again.');
          setTimeout(() => navigate('/login', { replace: true }), 3000);
        }
      } catch (err: any) {
        console.error('[@AuthCallback] Error processing callback:', err);
        setError(err.message || 'Failed to complete sign in');
        setTimeout(() => navigate('/login', { replace: true }), 3000);
      }
    };

    handleAuthCallback();
  }, [navigate]);

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '80vh',
        gap: 2,
      }}
    >
      {error ? (
        <Alert severity="error" sx={{ maxWidth: 500 }}>
          {error}
        </Alert>
      ) : (
        <>
          <CircularProgress size={60} />
          <Typography variant="h6" color="text.secondary">
            Completing sign in...
          </Typography>
        </>
      )}
    </Box>
  );
};

