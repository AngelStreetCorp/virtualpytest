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
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { ApiOutlined, Refresh, OpenInNew } from '@mui/icons-material';
import { buildServerUrl } from '../utils/buildUrlUtils';

interface Workspace {
  id: string;
  name: string;
  description: string;
  workspaceId: string;
  postmanUrl?: string;
}

const UserApiWorkspaces: React.FC = () => {
  const navigate = useNavigate();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [guideOpen, setGuideOpen] = useState(false);
  const [guide, setGuide] = useState<string | null>(null);
  const [guideError, setGuideError] = useState<string | null>(null);

  const openGuide = async () => {
    setGuideOpen(true);
    if (guide) return;
    try {
      const response = await fetch(buildServerUrl('/server/postman/guide'));
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || 'Failed to load guide');
      setGuide(data.content);
    } catch (err) {
      setGuideError(err instanceof Error ? err.message : 'Failed to load guide');
    }
  };

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

  useEffect(() => {
    loadWorkspaces();
  }, []);

  const handleViewWorkspace = (workspaceId: string) => {
    navigate(`/api/workspace/${workspaceId}`);
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography variant="h4">Postman</Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button
            variant="outlined"
            startIcon={<Refresh />}
            onClick={loadWorkspaces}
          >
            Refresh
          </Button>
        </Box>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {workspaces.length === 0 && !error && (
        <Alert severity="warning" sx={{ width: '100%', maxWidth: 1100, mx: 'auto', boxSizing: 'border-box' }}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            No API workspaces configured
          </Typography>
          <Typography variant="body2" sx={{ mb: 2 }}>
            The shared Postman workspace is not configured on this server.
          </Typography>
          <Typography variant="body2" component="div" sx={{ mb: 1 }}>
            <strong>Steps to configure:</strong>
          </Typography>
          <ol style={{ marginTop: 4, marginBottom: 8, paddingLeft: 20 }}>
            <li>
              <Typography variant="body2">
                Set <code>POSTMAN_API_KEY</code> in the backend server environment. This key stays server-side; VPT users do not need their own Postman key.
              </Typography>
            </li>
            <li>
              <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>
                Copy <code>backend_server/config/postman/postman_config.json.example</code> to <code>backend_server/config/postman/postman_config.json</code>. The shared workspace ID is already provided.
              </Typography>
            </li>
            <li>
              <Typography variant="body2">
                Restart the backend server, then refresh this page.
              </Typography>
            </li>
            <li>
              <Typography variant="body2">
                Refresh this page
              </Typography>
            </li>
          </ol>
          <Typography variant="caption" color="text.secondary">
            The example file shows the workspace configuration.{' '}
            <Button size="small" onClick={openGuide} sx={{ verticalAlign: 'baseline', p: 0, minWidth: 0, textTransform: 'none' }}>
              Read the full configuration guide
            </Button>
          </Typography>
        </Alert>
      )}

      <Dialog open={guideOpen} onClose={() => setGuideOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Postman configuration guide</DialogTitle>
        <DialogContent dividers>
          {guideError ? (
            <Alert severity="error">{guideError}</Alert>
          ) : guide ? (
            <Typography component="pre" sx={{ m: 0, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontFamily: 'monospace', fontSize: '0.85rem' }}>
              {guide}
            </Typography>
          ) : (
            <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}><CircularProgress /></Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setGuideOpen(false)}>Close</Button>
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
                    <ApiOutlined color="primary" />
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

                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Typography variant="caption" color="text.secondary">
                    Workspace ID:
                  </Typography>
                  <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
                    {workspace.workspaceId}
                  </Typography>
                </Box>

                <Box sx={{ mt: 2, pt: 2, borderTop: '1px solid', borderColor: 'divider' }}>
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
  );
};

export default UserApiWorkspaces;
