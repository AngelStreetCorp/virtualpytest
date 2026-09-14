import React, { useState, useEffect } from 'react';
import {
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  TextField,
  Box,
  Typography,
  Chip,
  CircularProgress,
  Alert,
  Switch,
  FormControlLabel,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { StyledDialog } from '../../common/StyledDialog';
import { buildServerUrl } from '../../../utils/buildUrlUtils';

interface ApiCallConfigModalProps {
  open: boolean;
  onClose: () => void;
  onSave: (config: ApiCallConfig) => void;
  initialConfig?: Partial<ApiCallConfig>;
}

interface ApiCallConfig {
  workspace_id: string;
  workspace_name: string;
  collection_id: string;
  collection_name: string;
  request_id: string;
  request_name: string;
  method: string;
  path_preview: string;
  environment_id?: string;
  environment_name?: string;
  store_response_as?: string;
  fail_on_error?: boolean;
  timeout_ms?: number;
}

interface Workspace {
  id: string;
  name: string;
  description?: string;
}

interface Collection {
  id: string;
  name: string;
  description?: string;
  requestCount: number;
}

interface Request {
  id: string;
  name: string;
  fullName: string;
  method: string;
  path: string;
  description?: string;
}

interface Environment {
  id: string;
  name: string;
  workspaceId: string;
  variables: Array<{
    key: string;
    value: any;
    type?: 'default' | 'secret';
  }>;
}

export const ApiCallConfigModal: React.FC<ApiCallConfigModalProps> = ({
  open,
  onClose,
  onSave,
  initialConfig,
}) => {
  // Form state
  const [workspaceId, setWorkspaceId] = useState(initialConfig?.workspace_id || '');
  const [collectionId, setCollectionId] = useState(initialConfig?.collection_id || '');
  const [requestId, setRequestId] = useState(initialConfig?.request_id || '');
  const [environmentId, setEnvironmentId] = useState(initialConfig?.environment_id || '');
  const [storeResponseAs, setStoreResponseAs] = useState(initialConfig?.store_response_as || 'api_response');
  const [failOnError, setFailOnError] = useState(initialConfig?.fail_on_error !== false);
  const [timeoutMs, setTimeoutMs] = useState(initialConfig?.timeout_ms || 5000);
  
  // Data state
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [requests, setRequests] = useState<Request[]>([]);
  const [environments, setEnvironments] = useState<Environment[]>([]);
  
  // Loading state
  const [loadingWorkspaces, setLoadingWorkspaces] = useState(false);
  const [loadingCollections, setLoadingCollections] = useState(false);
  const [loadingRequests, setLoadingRequests] = useState(false);
  const [loadingEnvironments, setLoadingEnvironments] = useState(false);
  
  // Error state
  const [error, setError] = useState<string | null>(null);
  
  // Load workspaces on mount
  useEffect(() => {
    if (open) {
      loadWorkspaces();
    }
  }, [open]);
  
  // Load collections when workspace changes
  useEffect(() => {
    if (workspaceId) {
      loadCollections(workspaceId);
      loadEnvironments(workspaceId);
    } else {
      setCollections([]);
      setEnvironments([]);
      setCollectionId('');
      setEnvironmentId('');
    }
  }, [workspaceId]);
  
  // Load requests when collection changes
  useEffect(() => {
    if (collectionId && workspaceId) {
      loadRequests(workspaceId, collectionId);
    } else {
      setRequests([]);
      setRequestId('');
    }
  }, [collectionId]);
  
  const loadWorkspaces = async () => {
    setLoadingWorkspaces(true);
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
      setLoadingWorkspaces(false);
    }
  };
  
  const loadCollections = async (wsId: string) => {
    setLoadingCollections(true);
    
    try {
      const response = await fetch(buildServerUrl(`/server/postman/workspaces/${wsId}/collections`));
      const data = await response.json();
      
      if (data.success) {
        setCollections(data.collections);
      }
    } catch (err) {
      console.error('Error loading collections:', err);
    } finally {
      setLoadingCollections(false);
    }
  };
  
  const loadRequests = async (wsId: string, collId: string) => {
    setLoadingRequests(true);
    
    try {
      const response = await fetch(buildServerUrl(`/server/postman/collections/${collId}/requests?workspace_id=${wsId}`));
      const data = await response.json();
      
      if (data.success) {
        setRequests(data.requests);
      }
    } catch (err) {
      console.error('Error loading requests:', err);
    } finally {
      setLoadingRequests(false);
    }
  };
  
  const loadEnvironments = async (wsId: string) => {
    setLoadingEnvironments(true);
    
    try {
      const response = await fetch(buildServerUrl(`/server/postman/environments?workspaceId=${wsId}`));
      const data = await response.json();
      
      if (data.success) {
        setEnvironments(data.environments);
      }
    } catch (err) {
      console.error('Error loading environments:', err);
    } finally {
      setLoadingEnvironments(false);
    }
  };
  
  const handleSave = () => {
    // Validate
    if (!workspaceId || !collectionId || !requestId) {
      setError('Please select workspace, collection, and request');
      return;
    }
    
    // Find names
    const workspace = workspaces.find(w => w.id === workspaceId);
    const collection = collections.find(c => c.id === collectionId);
    const request = requests.find(r => r.id === requestId);
    const environment = environments.find(e => e.id === environmentId);
    
    if (!workspace || !collection || !request) {
      setError('Invalid selection');
      return;
    }
    
    const config: ApiCallConfig = {
      workspace_id: workspaceId,
      workspace_name: workspace.name,
      collection_id: collectionId,
      collection_name: collection.name,
      request_id: requestId,
      request_name: request.name,
      method: request.method,
      path_preview: request.path,
      environment_id: environmentId || undefined,
      environment_name: environment?.name || undefined,
      store_response_as: storeResponseAs || 'api_response',
      fail_on_error: failOnError,
      timeout_ms: timeoutMs,
    };
    
    onSave(config);
    onClose();
  };
  
  const selectedRequest = requests.find(r => r.id === requestId);
  const selectedEnvironment = environments.find(e => e.id === environmentId);
  
  // Get method color
  const getMethodColor = (method: string) => {
    switch (method?.toUpperCase()) {
      case 'GET': return 'success';
      case 'POST': return 'primary';
      case 'PUT': return 'warning';
      case 'DELETE': return 'error';
      case 'PATCH': return 'info';
      default: return 'default';
    }
  };
  
  return (
    <StyledDialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
    >
      <DialogTitle>Configure API Call</DialogTitle>
      
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {error && (
            <Alert severity="error" onClose={() => setError(null)}>
              {error}
            </Alert>
          )}
          
          {/* Workspace Selector */}
          <FormControl fullWidth required>
            <InputLabel>Workspace</InputLabel>
            <Select
              value={workspaceId}
              label="Workspace"
              onChange={(e) => setWorkspaceId(e.target.value)}
              disabled={loadingWorkspaces}
            >
              {loadingWorkspaces ? (
                <MenuItem disabled>
                  <CircularProgress size={20} sx={{ mr: 1 }} />
                  Loading...
                </MenuItem>
              ) : (
                workspaces.map((ws) => (
                  <MenuItem key={ws.id} value={ws.id}>
                    {ws.name}
                  </MenuItem>
                ))
              )}
            </Select>
          </FormControl>
          
          {/* Collection Selector */}
          <FormControl fullWidth required disabled={!workspaceId}>
            <InputLabel>Collection</InputLabel>
            <Select
              value={collectionId}
              label="Collection"
              onChange={(e) => setCollectionId(e.target.value)}
              disabled={!workspaceId || loadingCollections}
            >
              {loadingCollections ? (
                <MenuItem disabled>
                  <CircularProgress size={20} sx={{ mr: 1 }} />
                  Loading...
                </MenuItem>
              ) : (
                collections.map((coll) => (
                  <MenuItem key={coll.id} value={coll.id}>
                    <Box>
                      <Typography variant="body2">{coll.name}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {coll.requestCount} endpoints
                      </Typography>
                    </Box>
                  </MenuItem>
                ))
              )}
            </Select>
          </FormControl>
          
          {/* Request Selector */}
          <FormControl fullWidth required disabled={!collectionId}>
            <InputLabel>Request</InputLabel>
            <Select
              value={requestId}
              label="Request"
              onChange={(e) => setRequestId(e.target.value)}
              disabled={!collectionId || loadingRequests}
            >
              {loadingRequests ? (
                <MenuItem disabled>
                  <CircularProgress size={20} sx={{ mr: 1 }} />
                  Loading...
                </MenuItem>
              ) : (
                requests.map((req) => (
                  <MenuItem key={req.id} value={req.id}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                      <Chip
                        label={req.method}
                        size="small"
                        color={getMethodColor(req.method)}
                        sx={{ fontFamily: 'monospace', fontSize: '0.7rem', minWidth: 50, height: 20 }}
                      />
                      <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography variant="body2" noWrap>{req.name}</Typography>
                        <Typography variant="caption" color="text.secondary" fontFamily="monospace" noWrap>
                          {req.path}
                        </Typography>
                      </Box>
                    </Box>
                  </MenuItem>
                ))
              )}
            </Select>
          </FormControl>
          
          {/* Environment Selector (Optional) */}
          <FormControl fullWidth disabled={!workspaceId}>
            <InputLabel>Environment (Optional)</InputLabel>
            <Select
              value={environmentId}
              label="Environment (Optional)"
              onChange={(e) => setEnvironmentId(e.target.value)}
              disabled={!workspaceId || loadingEnvironments}
            >
              <MenuItem value="">
                <em>None</em>
              </MenuItem>
              {loadingEnvironments ? (
                <MenuItem disabled>
                  <CircularProgress size={20} sx={{ mr: 1 }} />
                  Loading...
                </MenuItem>
              ) : (
                environments.map((env) => (
                  <MenuItem key={env.id} value={env.id}>
                    {env.name} ({env.variables.length} variables)
                  </MenuItem>
                ))
              )}
            </Select>
          </FormControl>
          
          {/* Request Preview */}
          {selectedRequest && (
            <Box sx={{ 
              p: 2, 
              bgcolor: 'grey.900', 
              color: 'common.white',
              borderRadius: 1,
              fontFamily: 'monospace',
              fontSize: '0.875rem'
            }}>
              <Typography variant="subtitle2" sx={{ mb: 1, color: 'grey.400' }}>
                Request Preview
              </Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                <Chip
                  label={selectedRequest.method}
                  size="small"
                  color={getMethodColor(selectedRequest.method)}
                  sx={{ fontFamily: 'monospace' }}
                />
                <Typography>{selectedRequest.path}</Typography>
              </Box>
              
              {selectedEnvironment && selectedEnvironment.variables.length > 0 && (
                <>
                  <Typography variant="caption" sx={{ color: 'grey.400', display: 'block', mt: 1 }}>
                    Variables to be substituted from context:
                  </Typography>
                  <Box component="ul" sx={{ m: 0, pl: 2, mt: 0.5 }}>
                    {selectedEnvironment.variables.slice(0, 5).map((v) => (
                      <li key={v.key}>
                        <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
                          {v.key} → from context
                        </Typography>
                      </li>
                    ))}
                    {selectedEnvironment.variables.length > 5 && (
                      <li>
                        <Typography variant="caption" color="text.secondary">
                          ... +{selectedEnvironment.variables.length - 5} more
                        </Typography>
                      </li>
                    )}
                  </Box>
                </>
              )}
            </Box>
          )}
          
          {/* Advanced Options */}
          <Accordion>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2">Advanced Options</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <TextField
                  label="Store Response As"
                  value={storeResponseAs}
                  onChange={(e) => setStoreResponseAs(e.target.value)}
                  helperText="Variable name to store API response in context"
                  size="small"
                  fullWidth
                />
                
                <FormControlLabel
                  control={
                    <Switch
                      checked={failOnError}
                      onChange={(e) => setFailOnError(e.target.checked)}
                    />
                  }
                  label="Fail on HTTP error (status >= 400)"
                />
                
                <TextField
                  label="Timeout (milliseconds)"
                  type="number"
                  value={timeoutMs}
                  onChange={(e) => setTimeoutMs(parseInt(e.target.value) || 5000)}
                  size="small"
                  fullWidth
                  inputProps={{ min: 1000, max: 60000, step: 1000 }}
                />
              </Box>
            </AccordionDetails>
          </Accordion>
        </Box>
      </DialogContent>
      
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button 
          onClick={handleSave} 
          variant="contained"
          disabled={!workspaceId || !collectionId || !requestId}
        >
          Save
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};

