import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Card,
  CardContent,
  Container,
  Typography,
  Stack,
  Divider,
  CircularProgress,
  Alert,
  TextField,
  Link,
  Tabs,
  Tab,
} from '@mui/material';
import { GitHub as GitHubIcon, Google as GoogleIcon, Email as EmailIcon } from '@mui/icons-material';
import { useAuth } from '../../hooks/auth/useAuth';
import { isAuthEnabled } from '../../lib/supabase';
import { useBranding } from '../../contexts/BrandingContext';

export const LoginPage: React.FC = () => {
  const { signInWithGoogle, signInWithGithub, signInWithEmail, signUpWithEmail, resetPassword, isAuthenticated, isLoading } = useAuth();
  const navigate = useNavigate();
  const { branding } = useBranding();
  
  const [tab, setTab] = useState<'login' | 'signup' | 'reset'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Redirect if already authenticated OR if auth is disabled
  useEffect(() => {
    if (isAuthenticated || !isAuthEnabled) {
      navigate('/');
    }
  }, [isAuthenticated, navigate]);

  const handleGoogleSignIn = async () => {
    try {
      setError('');
      await signInWithGoogle();
    } catch (error: any) {
      setError(error.message || 'Google sign-in failed');
    }
  };

  const handleGithubSignIn = async () => {
    try {
      setError('');
      await signInWithGithub();
    } catch (error: any) {
      setError(error.message || 'GitHub sign-in failed');
    }
  };

  const handleEmailLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);

    try {
      await signInWithEmail(email, password);
      // Success - will redirect via useEffect
    } catch (error: any) {
      setError(error.message || 'Login failed');
    } finally {
      setSubmitting(false);
    }
  };

  const handleEmailSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setSubmitting(true);

    try {
      await signUpWithEmail(email, password, fullName);
      setSuccess('Account created! Check your email to verify your account.');
      setEmail('');
      setPassword('');
      setFullName('');
    } catch (error: any) {
      setError(error.message || 'Signup failed');
    } finally {
      setSubmitting(false);
    }
  };

  const handlePasswordReset = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setSubmitting(true);

    try {
      await resetPassword(email);
      setSuccess('Password reset email sent! Check your inbox.');
      setEmail('');
    } catch (error: any) {
      setError(error.message || 'Password reset failed');
    } finally {
      setSubmitting(false);
    }
  };

  // If auth is disabled, show setup instructions
  if (!isAuthEnabled) {
    return (
      <Container maxWidth="sm">
        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: '80vh',
          }}
        >
          <Card sx={{ width: '100%', maxWidth: 450 }}>
            <CardContent sx={{ p: 4 }}>
              <Box sx={{ textAlign: 'center', mb: 4 }}>
                <Typography variant="h4" component="h1" gutterBottom fontWeight="bold">
                  Authentication Disabled
                </Typography>
              </Box>

              <Alert severity="info" sx={{ mb: 3 }}>
                Supabase credentials not configured. The app is running without authentication.
              </Alert>

              <Typography variant="body1" paragraph>
                To enable authentication, add these variables to <code>frontend/.env</code>:
              </Typography>

              <Box sx={{ bgcolor: 'grey.100', p: 2, borderRadius: 1, fontFamily: 'monospace', fontSize: '0.9rem' }}>
                VITE_SUPABASE_URL=https://your-project.supabase.co<br />
                VITE_SUPABASE_ANON_KEY=your-anon-key-here
              </Box>

              <Box sx={{ mt: 3, textAlign: 'center' }}>
                <Button variant="contained" onClick={() => navigate('/')}>
                  Go to Dashboard
                </Button>
              </Box>

              <Box sx={{ mt: 3 }}>
                <Typography variant="caption" color="text.secondary">
                  See <code>SUPABASE_AUTH_SETUP.md</code> for full setup instructions
                </Typography>
              </Box>
            </CardContent>
          </Card>
        </Box>
      </Container>
    );
  }

  if (isLoading) {
    return (
      <Container maxWidth="sm">
        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: '80vh',
          }}
        >
          <CircularProgress />
        </Box>
      </Container>
    );
  }

  return (
    <Container maxWidth="sm">
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'flex-start',
          pt: { xs: 3, sm: 8 },
          pb: 2,
        }}
      >
        <Card sx={{ width: '100%', maxWidth: 450 }}>
          <CardContent sx={{ p: 3 }}>
            <Box sx={{ textAlign: 'center', mb: 2 }}>
              {branding.showProjectName ? (
                <Typography variant="h4" component="h1" gutterBottom fontWeight="bold">
                  {branding.name}
                </Typography>
              ) : (
                // The wordmark logo stands in for the title (VITE_SHOW_PROJECT_NAME=false)
                <Box
                  component="img"
                  src={branding.logoUrl}
                  alt={`${branding.name} logo`}
                  sx={{ height: 48, width: 'auto', maxWidth: '80%', objectFit: 'contain', mb: 1 }}
                />
              )}
            </Box>

            {error && <Alert severity="error" sx={{ mb: 0.5 }}>{error}</Alert>}
            {success && <Alert severity="success" sx={{ mb: 0.5 }}>{success}</Alert>}

            <Tabs value={tab} onChange={(_, v) => { setTab(v); setError(''); setSuccess(''); }} sx={{ mb: 2 }}>
              <Tab label="Login" value="login" />
              <Tab label="Sign Up" value="signup" />
              <Tab label="Reset Password" value="reset" />
            </Tabs>

            {tab === 'login' && (
              <Box component="form" onSubmit={handleEmailLogin}>
                <Stack spacing={1.5}>
                  <TextField
                    label="Email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    fullWidth
                    size="small"
                    autoComplete="email"
                    InputLabelProps={{ shrink: true }}
                  />
                  <TextField
                    label="Password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    fullWidth
                    size="small"
                    autoComplete="current-password"
                    InputLabelProps={{ shrink: true }}
                  />
                  <Button
                    type="submit"
                    variant="contained"
                    fullWidth
                    disabled={submitting}
                    startIcon={<EmailIcon />}
                    sx={{ mt: 1 }}
                  >
                    {submitting ? 'Signing in...' : 'Sign in with Email'}
                  </Button>
                </Stack>
              </Box>
            )}

            {tab === 'signup' && (
              <Box component="form" onSubmit={handleEmailSignup}>
                <Stack spacing={1.5}>
                  <TextField
                    label="Full Name"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    fullWidth
                    size="small"
                    autoComplete="name"
                    InputLabelProps={{ shrink: true }}
                  />
                  <TextField
                    label="Email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    fullWidth
                    size="small"
                    autoComplete="email"
                    InputLabelProps={{ shrink: true }}
                  />
                  <TextField
                    label="Password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    fullWidth
                    size="small"
                    autoComplete="new-password"
                    helperText="Minimum 6 characters"
                    InputLabelProps={{ shrink: true }}
                  />
                  <Button
                    type="submit"
                    variant="contained"
                    fullWidth
                    disabled={submitting}
                    startIcon={<EmailIcon />}
                    sx={{ mt: 1 }}
                  >
                    {submitting ? 'Creating account...' : 'Create Account'}
                  </Button>
                </Stack>
              </Box>
            )}

            {tab === 'reset' && (
              <Box component="form" onSubmit={handlePasswordReset}>
                <Stack spacing={1.5}>
                  <TextField
                    label="Email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    fullWidth
                    size="small"
                    autoComplete="email"
                    helperText="We'll send you a password reset link"
                    InputLabelProps={{ shrink: true }}
                  />
                  <Button
                    type="submit"
                    variant="contained"
                    fullWidth
                    disabled={submitting}
                    startIcon={<EmailIcon />}
                    sx={{ mt: 1 }}
                  >
                    {submitting ? 'Sending...' : 'Send Reset Link'}
                  </Button>
                </Stack>
              </Box>
            )}

            <Divider sx={{ my: 2 }}>or continue with</Divider>

            <Stack direction="row" spacing={2} justifyContent="center">
              <Button
                variant="outlined"
                onClick={handleGoogleSignIn}
                sx={{
                  minWidth: 120,
                  py: 1.5,
                  borderColor: 'divider',
                  '&:hover': {
                    borderColor: 'primary.main',
                    backgroundColor: 'action.hover',
                  },
                }}
              >
                <GoogleIcon sx={{ fontSize: 24 }} />
              </Button>

              <Button
                variant="outlined"
                onClick={handleGithubSignIn}
                sx={{
                  minWidth: 120,
                  py: 1.5,
                  borderColor: 'divider',
                  '&:hover': {
                    borderColor: 'primary.main',
                    backgroundColor: 'action.hover',
                  },
                }}
              >
                <GitHubIcon sx={{ fontSize: 24 }} />
              </Button>
            </Stack>

            {tab === 'login' && (
              <Box sx={{ mt: 2, textAlign: 'center' }}>
                <Link
                  component="button"
                  variant="body2"
                  onClick={() => setTab('signup')}
                  sx={{ cursor: 'pointer' }}
                >
                  Don't have an account? Create Account
                </Link>
              </Box>
            )}

            {tab === 'signup' && (
              <Box sx={{ mt: 2, textAlign: 'center' }}>
                <Link
                  component="button"
                  variant="body2"
                  onClick={() => setTab('login')}
                  sx={{ cursor: 'pointer' }}
                >
                  Already have an account? Sign in
                </Link>
              </Box>
            )}
          </CardContent>
        </Card>
      </Box>
    </Container>
  );
};
