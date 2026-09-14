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
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { ApiOutlined, Add, Refresh, OpenInNew } from '@mui/icons-material';
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
          <ApiOutlined sx={{ fontSize: 32, color: 'primary.main' }} />
          <Typography variant="h4">API Testing Workspaces</Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button
            variant="outlined"
            startIcon={<Refresh />}
            onClick={loadWorkspaces}
          >
            Refresh
          </Button>
          <Button
            variant="contained"
            startIcon={<Add />}
            onClick={() => {
              alert('To add a workspace, edit backend_server/config/postman/postman_config.json');
            }}
          >
            Add Workspace
          </Button>
        </Box>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {workspaces.length === 0 && !error && (
        <Alert severity="warning" sx={{ maxWidth: 600, mx: 'auto' }}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            No API workspaces configured
          </Typography>
          <Typography variant="body2" sx={{ mb: 2 }}>
            To test your APIs with Postman, you need to configure at least one workspace.
          </Typography>
          <Typography variant="body2" component="div" sx={{ mb: 1 }}>
            <strong>Steps to configure:</strong>
          </Typography>
          <ol style={{ marginTop: 4, marginBottom: 8, paddingLeft: 20 }}>
            <li>
              <Typography variant="body2">
                Get your Postman API key from{' '}
                <a href="https://postman.co/settings/me/api-keys" target="_blank" rel="noopener noreferrer">
                  Postman Settings
                </a>
              </Typography>
            </li>
            <li>
              <Typography variant="body2">
                Edit <code>backend_server/config/postman/postman_config.json</code>
              </Typography>
            </li>
            <li>
              <Typography variant="body2">
                Add your workspace configuration with your API key
              </Typography>
            </li>
            <li>
              <Typography variant="body2">
                Refresh this page
              </Typography>
            </li>
          </ol>
          <Typography variant="caption" color="text.secondary">
            Example: See the config file for the JSON structure needed.
          </Typography>
        </Alert>
      )}

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

                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  {workspace.description || 'No description'}
                </Typography>

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
                    View & Test Endpoints
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

