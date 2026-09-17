/**
 * Per-server sign-in (TASK-18).
 *
 * Shown when the user picks a server backed by a Supabase they have no session for.
 * Deliberately minimal — email + password only. Sign-up, password reset and OAuth stay
 * on the full LoginPage: this dialog exists to unblock a server switch, not to be a
 * second account-management surface.
 *
 * Signing in here signs the user in to every server sharing that identity, because
 * sessions are keyed by Supabase identity rather than by server.
 */
import React, { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
} from '@mui/material';

import { getServerAuthInfo, signInToServer } from '../../lib/serverIdentity';

interface ServerAuthDialogProps {
  open: boolean;
  /** Server the user is trying to switch to. */
  serverUrl: string;
  /** Human name for the title, when the picker knows one. */
  serverName?: string;
  onCancel: () => void;
  /** Called after a successful sign-in, so the caller can complete the switch. */
  onAuthenticated: () => void;
}

export const ServerAuthDialog: React.FC<ServerAuthDialogProps> = ({
  open,
  serverUrl,
  serverName,
  onCancel,
  onAuthenticated,
}) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Reset on open, driven by `open` alone: the fields must not be cleared by an
  // unrelated re-render while the user is typing.
  useEffect(() => {
    if (open) {
      setEmail('');
      setPassword('');
      setError('');
      setSubmitting(false);
    }
  }, [open]);

  const identity = getServerAuthInfo(serverUrl)?.identity;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (submitting) return;

    setSubmitting(true);
    setError('');
    const { error: signInError } = await signInToServer(serverUrl, email, password);
    setSubmitting(false);

    if (signInError) {
      setError(signInError);
      return;
    }
    onAuthenticated();
  };

  return (
    <Dialog open={open} onClose={onCancel} maxWidth="xs" fullWidth>
      <form onSubmit={handleSubmit}>
        <DialogTitle sx={{ pb: 0.5 }}>
          Sign in to {serverName || serverUrl.replace(/^https?:\/\//, '')}
        </DialogTitle>
        <DialogContent>
          {identity && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 2 }}>
              {identity.replace(/^https?:\/\//, '')}
            </Typography>
          )}
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <TextField
              label="Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              size="small"
              autoFocus
              required
              fullWidth
            />
            <TextField
              label="Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              size="small"
              required
              fullWidth
            />
          </Box>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" variant="contained" disabled={submitting || !email || !password}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
};
