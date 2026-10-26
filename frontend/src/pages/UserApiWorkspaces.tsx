import React, { useEffect, useState } from 'react';
import {
  Box,
  Card,
  CardContent,
  Typography,
  Button,
  Grid,
  Chip,
  CircularProgress,
  Alert,
  IconButton,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Link,
  TextField,
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { Refresh, OpenInNew } from '@mui/icons-material';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { PageTitle, goldButtonSx, pageSurfaceSx } from '../components/common/PageChrome';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { usePermissions } from '../hooks/auth/usePermissions';

interface Workspace {
  id: string;
  name: string;
  description: string;
  workspaceId: string;
  postmanUrl?: string;
}

/** The shared public workspace this app documents; the setup form shows it read-only. */
const SHARED_WORKSPACE_ID = '4e7a465c-a542-4440-8903-48787f03942a';
const SHARED_WORKSPACE_URL = `https://martian-zodiac-279215.postman.co/workspace/virtualpytest~${SHARED_WORKSPACE_ID}`;
const POSTMAN_API_KEYS_URL = 'https://go.postman.co/settings/me/api-keys';

const CONTENT_MAX = 1280;

/**
 * The Postman mark (simple-icons, transparent, so one file reads on the light and the dark card).
 * The same asset the Plugins nav row and the /docs/integrations grid draw from
 * (`/vendor/integrations/postman-mark.svg`) — a generic MUI glyph reads as "generic API", not Postman.
 */
const PostmanMark: React.FC<{ size?: number; decorative?: boolean }> = ({ size = 20, decorative = true }) => (
  <img
    src="/vendor/integrations/postman-mark.svg"
    alt={decorative ? '' : 'Postman'}
    aria-hidden={decorative || undefined}
    aria-label={decorative ? undefined : 'Postman'}
    width={size}
    height={size}
    style={{ display: 'block', flex: 'none', objectFit: 'contain' }}
  />
);

const UserApiWorkspaces: React.FC = () => {
  const navigate = useNavigate();
  const P = useAgentChatPalette();
  const { canAccess } = usePermissions();
  const canManage = canAccess?.('plugins.postman:manage') ?? false;
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // The setup form replaces the old configuration-guide dump: the steps were an operator's
  // markdown file rendered at 15px monospace in a full-screen dialog, which told an admin in
  // the app what he already knew and a user nothing he could act on. One field, one link,
  // one Save — and the server proves the key works before the page believes it.
  const [setupOpen, setSetupOpen] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [setupError, setSetupError] = useState<string | null>(null);

  const loadWorkspaces = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(buildServerUrl('/server/postman/workspaces'));
      const data = await response.json();

      if (data.success) {
        setWorkspaces(data.workspaces);
      } else {
        setError(data.error || 'Failed to load workspaces');
      }
    } catch (err) {
      setError('Error connecting to server');
      console.error('Error loading workspaces:', err);
    } finally {
      setLoading(false);
    }
  };

  const saveSettings = async () => {
    setSaving(true);
    setSetupError(null);
    try {
      const response = await fetch(buildServerUrl('/server/postman/settings'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: apiKey.trim(), workspace_id: SHARED_WORKSPACE_ID }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.success) {
        setSetupError(data.error || 'Could not save the Postman key');
        return;
      }
      setApiKey('');
      setSetupOpen(false);
      await loadWorkspaces();   // the card is gone the moment the key works
    } catch {
      setSetupError('Error connecting to server');
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    loadWorkspaces();
  }, []);

  const handleViewWorkspace = (workspaceId: string) => {
    navigate(`/api/workspace/${workspaceId}`);
  };

  // `configured` is "the answer has arrived and there is no workspace" — a real state, not a
  // loading one. An empty array must render the empty state, never a spinner (UI_STYLE.md §10 S6).
  const configured = workspaces.length > 0;

  return (
    <Box sx={pageSurfaceSx(P)}>
      <Box sx={{ maxWidth: CONTENT_MAX, mx: 'auto' }}>
        <PageTitle
          title="Postman"
          subtitle={
            configured
              ? `${workspaces.length} workspace${workspaces.length === 1 ? '' : 's'} · browse collections and run requests from the browser`
              : 'Browse the shared Postman workspace collections and run requests'
          }
          right={
            // Hidden while unconfigured so the empty state offers exactly one thing to click.
            configured ? (
              <Button
                variant="outlined"
                startIcon={<Refresh />}
                onClick={loadWorkspaces}
                sx={{ color: P.textPrimary }}
              >
                Refresh
              </Button>
            ) : undefined
          }
        />

        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
            <CircularProgress size={26} />
          </Box>
        )}

        {error && !loading && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {!loading && !error && !configured && (
          <Card sx={{ maxWidth: 560, mx: 'auto' }}>
            <CardContent sx={{ py: 4, textAlign: 'center' }}>
              {/* The real Postman mark at hero size, like the GitLab page's tanuki. Transparent, so it
                  reads on the light and the dark card alike and needs no framed plate. */}
              <Box sx={{ display: 'flex', justifyContent: 'center', mb: 2 }}>
                <PostmanMark size={44} />
              </Box>
              <Typography variant="h6" sx={{ mb: canManage ? 1 : 0.5, color: P.textPrimary }}>
                Connect to Postman
              </Typography>
              {!canManage && (
                <Typography variant="body2" sx={{ color: P.textMuted }}>
                  An admin has to connect this server.
                </Typography>
              )}
              {canManage && (
                <Button sx={goldButtonSx(P)} onClick={() => { setSetupError(null); setSetupOpen(true); }}>
                  Setup
                </Button>
              )}
            </CardContent>
          </Card>
        )}

        <Dialog open={setupOpen} onClose={() => !saving && setSetupOpen(false)} maxWidth="sm" fullWidth>
          <DialogTitle>Connect Postman</DialogTitle>
          <DialogContent>
            <Typography variant="body2" sx={{ color: P.textSecondary, mb: 2 }}>
              Paste a Postman API key. It stays on this server — it is never sent to a browser —
              and the server checks it against Postman before saving.
            </Typography>
            <TextField
              autoFocus
              fullWidth
              type="password"
              size="small"
              label="Postman API key"
              placeholder="PMAK-…"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && apiKey.trim() && !saving) saveSettings(); }}
              helperText={
                <Link href={POSTMAN_API_KEYS_URL} target="_blank" rel="noopener noreferrer" sx={{ color: P.accentText }}>
                  Create an API key in Postman
                </Link>
              }
            />
            <Typography variant="caption" sx={{ display: 'block', mt: 2, color: P.textMuted }}>
              Workspace{' '}
              <Link href={SHARED_WORKSPACE_URL} target="_blank" rel="noopener noreferrer" sx={{ color: P.accentText }}>
                <Box component="span" sx={{ fontFamily: 'monospace' }}>{SHARED_WORKSPACE_ID}</Box>
              </Link>
            </Typography>
            {setupError && <Alert severity="error" sx={{ mt: 2 }}>{setupError}</Alert>}
          </DialogContent>
          <DialogActions sx={{ px: 3, pb: 2 }}>
            <Button disabled={saving} onClick={() => setSetupOpen(false)} sx={{ color: P.accentText, fontWeight: 600 }}>
              Cancel
            </Button>
            <Button sx={goldButtonSx(P)} disabled={saving || !apiKey.trim()} onClick={saveSettings}>
              {saving ? 'Checking…' : 'Save'}
            </Button>
          </DialogActions>
        </Dialog>

        <Grid container spacing={3}>
          {workspaces.map((workspace) => (
            <Grid item xs={12} md={6} key={workspace.id}>
              <Card
                sx={{
                  height: '100%',
                  cursor: 'pointer',
                  transition: 'transform 0.2s, box-shadow 0.2s',
                  '&:hover': {
                    transform: 'translateY(-4px)',
                    boxShadow: 4,
                  },
                }}
                onClick={() => handleViewWorkspace(workspace.id)}
              >
                <CardContent>
                  <Box sx={{ display: 'flex', alignItems: 'start', justifyContent: 'space-between', mb: 2 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <PostmanMark size={20} />
                      <Typography variant="h6">{workspace.name}</Typography>
                    </Box>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      <Chip label="Postman" size="small" color="primary" variant="outlined" />
                      {workspace.postmanUrl && (
                        <Tooltip title="Open in Postman">
                          <IconButton
                            size="small"
                            color="primary"
                            onClick={(e) => {
                              e.stopPropagation();
                              window.open(workspace.postmanUrl, '_blank');
                            }}
                            sx={{ ml: 0.5 }}
                          >
                            <OpenInNew fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                    </Box>
                  </Box>

                  {/* The id that opens the workspace: /api/workspace/<id> and the
                      backend routes resolve the internal id. The Postman workspace
                      id is a different thing and is labelled as such, so nobody
                      copies it into the app's URL and lands on "Workspace not
                      found" (BUG-0796). */}
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Typography variant="caption" sx={{ color: P.textSecondary }}>
                      Workspace ID:
                    </Typography>
                    <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
                      {workspace.id}
                    </Typography>
                  </Box>

                  {workspace.workspaceId && workspace.workspaceId !== workspace.id && (
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                      <Typography variant="caption" sx={{ color: P.textSecondary }}>
                        Postman workspace ID:
                      </Typography>
                      <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
                        {workspace.workspaceId}
                      </Typography>
                    </Box>
                  )}

                  <Box sx={{ mt: 2, pt: 2, borderTop: `1px solid ${P.borderColor}` }}>
                    <Button
                      variant="contained"
                      size="small"
                      fullWidth
                      onClick={(e) => {
                        e.stopPropagation();
                        handleViewWorkspace(workspace.id);
                      }}
                    >
                      View
                    </Button>
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      </Box>
    </Box>
  );
};

export default UserApiWorkspaces;
