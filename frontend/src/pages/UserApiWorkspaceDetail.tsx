import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Box,
  Card,
  CardContent,
  Typography,
  Button,
  Checkbox,
  CircularProgress,
  Alert,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Chip,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  DialogTitle,
  DialogContent,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  IconButton,
  Tooltip,
  Snackbar,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  TextField,
  DialogActions,
} from '@mui/material';
import {
  ArrowBack,
  ExpandMore,
  PlayArrow,
  Close,
  ContentCopy,
  Search,
} from '@mui/icons-material';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { StyledDialog } from '../components/common/StyledDialog';
import { discoverServerIdentity, getAccessTokenForServer } from '../lib/serverIdentity';
import { unauthenticatedFetch } from '../utils/pristineFetch';

interface Request {
  id: string;
  name: string;
  fullName: string;
  method: string;
  path: string;
  description: string;
}

interface RunnerEnvironment {
  id: string;
  name: string;
  serverUrl: string;
  teamId: string;
  jwtToken: string;
}

interface Collection {
  id: string;
  name: string;
  description: string;
  requestCount: number;
  requests?: Request[];
}

interface Workspace {
  id: string;
  name: string;
  description: string;
  postmanApiKey?: string;
  workspaceId?: string;
  teamId?: string;
}

const emptyEnvironment = (): RunnerEnvironment => ({
  id: crypto.randomUUID(),
  name: 'My VPT server',
  serverUrl: '',
  teamId: '',
  jwtToken: '',
});

const UserApiWorkspaceDetail: React.FC = () => {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const navigate = useNavigate();
  
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [environments, setEnvironments] = useState<RunnerEnvironment[]>([]);
  const [selectedEnvironment, setSelectedEnvironment] = useState<string>('');
  const [environmentDraft, setEnvironmentDraft] = useState<RunnerEnvironment>(emptyEnvironment);
  const [selectedRequests, setSelectedRequests] = useState<Set<string>>(new Set());
  const [expandedCollections, setExpandedCollections] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [loadingRequests, setLoadingRequests] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [testResult, setTestResult] = useState<any>(null);
  const [showResultsDialog, setShowResultsDialog] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [snackbarMessage, setSnackbarMessage] = useState<string>('');
  const [showSnackbar, setShowSnackbar] = useState(false);
  const [selectedResponse, setSelectedResponse] = useState<any>(null);
  const [showResponseDialog, setShowResponseDialog] = useState(false);
  const [showEnvironmentDialog, setShowEnvironmentDialog] = useState(false);
  const [creatingEnvironment, setCreatingEnvironment] = useState(false);
  const [filterText, setFilterText] = useState('');

  // Runner environments belong to this browser/user, never to the shared Postman workspace.
  useEffect(() => {
    if (!workspaceId) return;
    const storageKey = `vpt-postman-environments:${workspaceId}`;
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || '[]') as Array<Omit<RunnerEnvironment, 'jwtToken'>>;
      if (saved.length) {
        const restored = saved.map(env => ({ ...env, jwtToken: '' }));
        setEnvironments(restored);
        const selectedId = localStorage.getItem(`${storageKey}:selected`);
        setSelectedEnvironment(restored.some(env => env.id === selectedId) ? selectedId! : restored[0].id);
      } else {
        const initial = emptyEnvironment();
        setEnvironments([initial]);
        setSelectedEnvironment(initial.id);
      }
    } catch {
      const initial = emptyEnvironment();
      setEnvironments([initial]);
      setSelectedEnvironment(initial.id);
    }
  }, [workspaceId]);

  const persistEnvironments = (items: RunnerEnvironment[], selectedId: string) => {
    if (!workspaceId) return;
    const storageKey = `vpt-postman-environments:${workspaceId}`;
    localStorage.setItem(storageKey, JSON.stringify(items.map(env => ({
      id: env.id, name: env.name, serverUrl: env.serverUrl, teamId: env.teamId,
    }))));
    localStorage.setItem(`${storageKey}:selected`, selectedId);
  };

  const openEnvironmentEditor = (createNew = false) => {
    setCreatingEnvironment(createNew);
    setEnvironmentDraft(createNew
      ? emptyEnvironment()
      : environments.find(env => env.id === selectedEnvironment) || emptyEnvironment());
    setShowEnvironmentDialog(true);
  };

  const saveEnvironment = () => {
    const updated = creatingEnvironment
      ? [...environments, environmentDraft]
      : environments.map(env => env.id === environmentDraft.id ? environmentDraft : env);
    setEnvironments(updated);
    setSelectedEnvironment(environmentDraft.id);
    persistEnvironments(updated, environmentDraft.id);
    setShowEnvironmentDialog(false);
  };

  const deleteEnvironment = () => {
    const updated = environments.filter(env => env.id !== selectedEnvironment);
    const next = updated[0] || emptyEnvironment();
    const nextItems = updated.length ? updated : [next];
    setEnvironments(nextItems);
    setSelectedEnvironment(next.id);
    persistEnvironments(nextItems, next.id);
    setShowEnvironmentDialog(false);
  };

  useEffect(() => {
    loadWorkspaceAndCollections();
  }, [workspaceId]);

  const loadWorkspaceAndCollections = async () => {
    setLoading(true);
    setError(null);

    try {
      // Load workspaces to get workspace details
      const wsResponse = await fetch(buildServerUrl('/server/postman/workspaces'));
      const wsData = await wsResponse.json();
      
      if (wsData.success) {
        const ws = wsData.workspaces.find((w: Workspace) => w.id === workspaceId);
        if (ws) {
          setWorkspace(ws);
        } else {
          setError('Workspace not found');
          return;
        }
      }

      // Load collections
      const collResponse = await fetch(buildServerUrl(`/server/postman/workspaces/${workspaceId}/collections`));
      const collData = await collResponse.json();
      
      if (collData.success) {
        setCollections(collData.collections);
      } else {
        setError(collData.error || 'Failed to load collections');
      }
    } catch (err) {
      setError('Error connecting to server');
      console.error('Error loading workspace:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadCollectionRequests = async (collectionId: string, expand = true) => {
    setLoadingRequests(prev => new Set(prev).add(collectionId));
    
    try {
      const response = await fetch(buildServerUrl(`/server/postman/collections/${collectionId}/requests?workspace_id=${workspaceId}`));
      const data = await response.json();
      
      if (data.success) {
        // Update collection with requests
        setCollections(prev =>
          prev.map(coll =>
            coll.id === collectionId
              ? { ...coll, requests: data.requests }
              : coll
          )
        );
        
        // Expand the collection
        if (expand) {
          setExpandedCollections(prev => new Set(prev).add(collectionId));
        }
        
        return data.requests;
      }
    } catch (err) {
      console.error('Error loading requests:', err);
    } finally {
      setLoadingRequests(prev => {
        const newSet = new Set(prev);
        newSet.delete(collectionId);
        return newSet;
      });
    }
    return null;
  };

  const handleCollectionToggle = (collectionId: string) => {
    const collection = collections.find(c => c.id === collectionId);
    
    if (!collection) return;
    
    // If not yet loaded, load requests first
    if (!collection.requests) {
      loadCollectionRequests(collectionId, true);
    } else {
      // Toggle expansion
      setExpandedCollections(prev => {
        const newSet = new Set(prev);
        if (newSet.has(collectionId)) {
          newSet.delete(collectionId);
        } else {
          newSet.add(collectionId);
        }
        return newSet;
      });
    }
  };

  const handleRequestToggle = (requestId: string) => {
    setSelectedRequests(prev => {
      const newSet = new Set(prev);
      if (newSet.has(requestId)) {
        newSet.delete(requestId);
      } else {
        newSet.add(requestId);
      }
      return newSet;
    });
  };

  const handleCollectionSelectAll = async (collectionId: string) => {
    const collection = collections.find(c => c.id === collectionId);
    if (!collection) return;
    
    let requests = collection.requests;
    
    // Load requests if not already loaded
    if (!requests) {
      requests = await loadCollectionRequests(collectionId, false);
    }
    
    if (!requests) return;
    
    const collectionRequestIds = requests.map((r: Request) => r.id);
    
    setSelectedRequests(prev => {
      const newSet = new Set(prev);
      // Check if all are currently selected
      const allSelected = collectionRequestIds.every((id: string) => prev.has(id));
      
      if (allSelected) {
        // Deselect all
        collectionRequestIds.forEach((id: string) => newSet.delete(id));
      } else {
        // Select all
        collectionRequestIds.forEach((id: string) => newSet.add(id));
      }
      return newSet;
    });
  };

  const handleRunTests = async () => {
    if (selectedRequests.size === 0) {
      setSnackbarMessage('Please select at least one endpoint to test');
      setShowSnackbar(true);
      return;
    }

    const environment = environments.find(env => env.id === selectedEnvironment);
    if (!environment?.serverUrl.trim()) {
      setSnackbarMessage('Configure a backend URL before running requests.');
      setShowSnackbar(true);
      setShowEnvironmentDialog(true);
      return;
    }

    let baseUrl: URL;
    try {
      baseUrl = new URL(environment.serverUrl.trim());
      const isLocal = ['localhost', '127.0.0.1', '[::1]'].includes(baseUrl.hostname);
      if (!['http:', 'https:'].includes(baseUrl.protocol) || baseUrl.username || baseUrl.password || (baseUrl.protocol === 'http:' && !isLocal)) {
        throw new Error('Use an HTTPS backend URL. HTTP is allowed only for localhost development.');
      }
      baseUrl.pathname = `${baseUrl.pathname.replace(/\/+$/, '')}/`;
    } catch (err) {
      setSnackbarMessage(err instanceof Error ? err.message : 'Enter a valid backend URL, including https://.');
      setShowSnackbar(true);
      setShowEnvironmentDialog(true);
      return;
    }

    setRunning(true);
    setTestResult(null);
    const selected: Array<{ request: Request; collectionId: string }> = [];
    collections.forEach(collection => collection.requests?.forEach(request => {
      if (selectedRequests.has(request.id)) selected.push({ request, collectionId: collection.id });
    }));

    if (!selected.length) {
      setTestResult({ success: false, error: 'Selected requests are not loaded. Expand their collection and try again.' });
      setRunning(false);
      return;
    }

    const replaceVariables = (value: unknown): unknown => {
      if (typeof value === 'string') {
        return value.replace(/\{\{([\w.-]+)\}\}/g, (_match, key: string) => {
          const values: Record<string, string> = {
            server_url: baseUrl.origin,
            team_id: environment.teamId,
            jwt_token: environment.jwtToken,
          };
          return values[key] ?? `{{${key}}}`;
        });
      }
      if (Array.isArray(value)) return value.map(replaceVariables);
      if (value && typeof value === 'object') {
        return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, replaceVariables(item)]));
      }
      return value;
    };

    try {
      // Reuse a session only when the target server advertises its own Supabase
      // identity. Never send this app's service X-API-Key to a user target.
      let targetJwt = environment.jwtToken;
      if (!targetJwt) {
        const authInfo = await discoverServerIdentity(baseUrl.origin);
        if (authInfo?.identity && authInfo.anonKey) targetJwt = (await getAccessTokenForServer(baseUrl.origin)) || '';
      }
      const results: any[] = [];
      for (const { request, collectionId } of selected) {
        const startedAt = performance.now();
        try {
          const definitionResponse = await fetch(buildServerUrl(
            `/server/postman/requests/${encodeURIComponent(request.id)}/definition?workspace_id=${encodeURIComponent(workspaceId || '')}&collection_id=${encodeURIComponent(collectionId)}`
          ));
          const definitionData = await definitionResponse.json();
          if (!definitionResponse.ok || !definitionData.success) throw new Error(definitionData.error || 'Could not load request definition');
          const definition = definitionData.request;
          const originalUrl = String(definition.url || request.path || '');
          const hasServerVariable = /\{\{server_url\}\}/i.test(originalUrl);
          const substitutedUrl = String(replaceVariables(originalUrl));
          const parsedUrl = new URL(substitutedUrl, baseUrl);
          // OpenAPI imports may contain a sample server URL. Keep its route and query,
          // but always direct the request to the user's explicitly selected backend.
          const targetUrl = hasServerVariable || parsedUrl.origin === baseUrl.origin
            ? parsedUrl
            : new URL(`${parsedUrl.pathname}${parsedUrl.search}${parsedUrl.hash}`, baseUrl);
          if (targetUrl.origin !== baseUrl.origin) throw new Error('Request URL does not match the selected backend environment.');
          for (const [key, value] of targetUrl.searchParams.entries()) {
            if (value.includes('{{')) targetUrl.searchParams.delete(key);
          }
          if (environment.teamId) targetUrl.searchParams.set('team_id', environment.teamId);
          if (/%7B%7B/i.test(`${targetUrl.pathname}${targetUrl.search}`)) {
            throw new Error('This request has unresolved variables. Set the required values in the environment.');
          }

          const headers = new Headers();
          Object.entries(definition.headers || {}).forEach(([key, value]) => {
            const normalizedKey = key.toLowerCase();
            if (['host', 'cookie', 'origin', 'referer', 'content-length', 'connection', 'x-api-key', 'authorization'].includes(normalizedKey)) return;
            const substituted = String(replaceVariables(value));
            if (!substituted.includes('{{')) headers.set(key, substituted);
          });
          if (targetJwt) headers.set('Authorization', `Bearer ${targetJwt}`);

          const body = replaceVariables(definition.body);
          if (body !== undefined && body !== null && !['GET', 'HEAD'].includes(String(definition.method || request.method).toUpperCase())) {
            if (typeof body === 'object') {
              headers.set('Content-Type', headers.get('Content-Type') || 'application/json');
            }
          }
          // Bypass installFetchAuth: it must not attach this VPT site's JWT, public
          // key, or auto-sign token to a backend selected by the user.
          const response = await unauthenticatedFetch(targetUrl, {
            method: String(definition.method || request.method).toUpperCase(),
            headers,
            body: body === undefined || body === null || ['GET', 'HEAD'].includes(String(definition.method || request.method).toUpperCase())
              ? undefined
              : typeof body === 'string' ? body : JSON.stringify(body),
            mode: 'cors',
            credentials: 'omit',
            redirect: 'error',
          });
          const responseText = await response.text();
          let responseBody: unknown = responseText;
          try { responseBody = responseText ? JSON.parse(responseText) : null; } catch { /* keep text response */ }
          results.push({
            name: request.name,
            method: String(definition.method || request.method).toUpperCase(),
            path: `${targetUrl.pathname}${targetUrl.search}`,
            status: response.ok ? 'pass' : 'fail',
            statusCode: response.status,
            duration: Math.round(performance.now() - startedAt),
            response: responseBody,
          });
        } catch (err) {
          const message = err instanceof TypeError
            ? `Could not reach ${baseUrl.origin}. Check the URL and allow this app's origin in the target server's CORS_ALLOWED_ORIGINS.`
            : err instanceof Error ? err.message : 'Request failed';
          results.push({ name: request.name, method: request.method, path: request.path, status: 'error', statusCode: 0, error: message });
        }
      }
      const passed = results.filter(result => result.status === 'pass').length;
      setTestResult({ success: true, message: `Completed ${results.length} requests against ${baseUrl.origin}`, results, passed, total: results.length });
      setShowResultsDialog(true);
    } catch (err) {
      console.error('Error running requests:', err);
      setTestResult({ success: false, error: err instanceof Error ? err.message : 'Failed to run requests' });
    } finally {
      setRunning(false);
    }
  };

  const handleCopyResponse = (response: any, index: number) => {
    const textToCopy = typeof response === 'string' ? response : JSON.stringify(response, null, 2);
    navigator.clipboard.writeText(textToCopy);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const handleViewResponse = (response: any) => {
    setSelectedResponse(response);
    setShowResponseDialog(true);
  };

  if (loading) {
    return (
      <Box sx={{ 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center', 
        position: 'fixed',
        top: 64,
        left: 38,
        right: 38,
        bottom: 35,
        overflow: 'hidden'
      }}>
        <CircularProgress />
      </Box>
    );
  }

  if (!workspace) {
    return (
      <Box sx={{ 
        p: 2,
        position: 'fixed',
        top: 64,
        left: 38,
        right: 38,
        bottom: 35,
        overflow: 'hidden'
      }}>
        <Alert severity="error">Workspace not found</Alert>
        <Button startIcon={<ArrowBack />} onClick={() => navigate('/api/workspaces')} sx={{ mt: 1 }}>
          Back to Workspaces
        </Button>
      </Box>
    );
  }

  return (
    <Box sx={{ 
      display: 'flex', 
      flexDirection: 'column', 
      position: 'fixed',
      top: 64,
      left: 38,
      right: 38,
      bottom: 35,
      overflow: 'hidden'
    }}>
      {/* Ultra-Compact Header with All Controls */}
      <Box 
        sx={{ 
          px: 3, 
          py: 0.5, 
          flexShrink: 0,
          bgcolor: 'background.default',
          borderBottom: 1,
          borderColor: 'divider',
          boxShadow: 1
        }}
      >
        {/* Single Line Header */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1 }}>
          <Button
            startIcon={<ArrowBack />}
            onClick={() => navigate('/api/workspaces')}
            size="small"
          >
            Back
          </Button>
          
          <Typography variant="h6">
            {workspace.name}
          </Typography>

          <TextField
            size="small"
            placeholder="Filter collections..."
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            autoComplete="off"
            InputProps={{
              startAdornment: <Search fontSize="small" sx={{ mr: 1, color: 'text.secondary' }} />,
            }}
            sx={{ minWidth: 180 }}
          />

          <Typography variant="caption" color="text.secondary">
            {collections.length} collections
          </Typography>

          <Box sx={{ flex: 1 }} />

          <FormControl size="small" sx={{ minWidth: 180, mt: 0.5 }}>
            <InputLabel>Environment</InputLabel>
            <Select
              value={selectedEnvironment}
              label="Environment"
              onChange={(e) => {
                setSelectedEnvironment(e.target.value);
                if (workspaceId) localStorage.setItem(`vpt-postman-environments:${workspaceId}:selected`, e.target.value);
              }}
            >
              {environments.map((env) => (
                <MenuItem key={env.id} value={env.id}>{env.name}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button size="small" variant="outlined" onClick={() => openEnvironmentEditor()} sx={{ textTransform: 'none' }}>
            Configure target
          </Button>
          <Button size="small" onClick={() => openEnvironmentEditor(true)} sx={{ textTransform: 'none' }}>
            Add environment
          </Button>

          <Button
            variant="contained"
            startIcon={running ? <CircularProgress size={16} /> : <PlayArrow />}
            onClick={handleRunTests}
            disabled={selectedRequests.size === 0 || running}
          >
            Run ({selectedRequests.size})
          </Button>
        </Box>

        {error && (
          <Alert severity="error" sx={{ mt: 1 }}>
            {error}
          </Alert>
        )}

        {testResult && (
          <Alert 
            severity={testResult.success ? 'success' : 'error'} 
            sx={{ mt: 1 }} 
            onClose={() => setTestResult(null)}
            action={
              testResult.results && (
                <Button color="inherit" size="small" onClick={() => setShowResultsDialog(true)}>
                  View Details
                </Button>
              )
            }
          >
            {testResult.success ? testResult.message : testResult.error}
            {testResult.note && (
              <Typography variant="caption" display="block" sx={{ mt: 1 }}>
                {testResult.note}
              </Typography>
            )}
          </Alert>
        )}

        <StyledDialog
          open={showResultsDialog}
          onClose={() => setShowResultsDialog(false)}
          maxWidth="lg"
          fullWidth
        >
          <DialogTitle sx={{ m: 0, p: 1, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 2 }}>
              <Typography variant="h6">Test Results</Typography>
              <Typography variant="subtitle2" color="text.secondary">
                {testResult?.passed}/{testResult?.total} Passed
              </Typography>
            </Box>
            <IconButton
              aria-label="close"
              onClick={() => setShowResultsDialog(false)}
              size="small"
            >
              <Close />
            </IconButton>
          </DialogTitle>
          <DialogContent dividers sx={{ p: 0 }}>
            {testResult?.results && (
              <TableContainer sx={{ maxHeight: '60vh' }}>
                <Table size="small" stickyHeader>
                  <TableHead>
                    <TableRow>
                      <TableCell>Method</TableCell>
                      <TableCell>Path</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell>Code</TableCell>
                      <TableCell>Time</TableCell>
                      <TableCell>Response/Error</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {testResult.results.map((result: any, index: number) => (
                      <TableRow 
                        key={index} 
                        sx={{ '&:hover': { bgcolor: 'transparent !important' } }}
                      >
                        <TableCell>
                          <Chip 
                            label={result.method} 
                            size="small" 
                            variant="outlined"
                            color={
                              result.method === 'GET' ? 'success' :
                              result.method === 'POST' ? 'primary' :
                              'default'
                            }
                            sx={{ fontSize: '0.7rem', height: 20 }}
                          />
                        </TableCell>
                        <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.85rem' }}>
                          {result.path}
                        </TableCell>
                        <TableCell>
                          <Chip 
                            label={result.status} 
                            color={result.status === 'pass' ? 'success' : 'error'} 
                            size="small" 
                            sx={{ height: 20 }}
                          />
                        </TableCell>
                        <TableCell>{result.statusCode || '-'}</TableCell>
                        <TableCell>{result.duration ? `${result.duration}ms` : '-'}</TableCell>
                        <TableCell>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <Box 
                              sx={{ 
                                flex: 1,
                                overflow: 'hidden', 
                                textOverflow: 'ellipsis', 
                                whiteSpace: 'nowrap',
                                fontFamily: 'monospace',
                                fontSize: '0.8rem',
                                cursor: 'pointer',
                                '&:hover': { textDecoration: 'underline' }
                              }}
                              onClick={() => handleViewResponse(result.error || result.response)}
                            >
                              {result.error || (typeof result.response === 'string' ? result.response : JSON.stringify(result.response))}
                            </Box>
                            <Tooltip title={copiedIndex === index ? "Copied!" : "Copy response"}>
                              <IconButton 
                                size="small" 
                                onClick={() => handleCopyResponse(result.error || result.response, index)}
                                sx={{ flexShrink: 0 }}
                              >
                                <ContentCopy fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          </Box>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </DialogContent>
        </StyledDialog>

        {/* Response Detail Dialog */}
        <StyledDialog
          open={showResponseDialog}
          onClose={() => setShowResponseDialog(false)}
          maxWidth="md"
          fullWidth
        >
          <DialogTitle sx={{ m: 0, p: 2, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Typography variant="h6">Response Details</Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Tooltip title="Copy response">
                <IconButton
                  size="small"
                  onClick={() => {
                    const textToCopy = typeof selectedResponse === 'string' ? selectedResponse : JSON.stringify(selectedResponse, null, 2);
                    navigator.clipboard.writeText(textToCopy);
                    setSnackbarMessage('Response copied to clipboard');
                    setShowSnackbar(true);
                  }}
                >
                  <ContentCopy />
                </IconButton>
              </Tooltip>
              <IconButton
                size="small"
                onClick={() => setShowResponseDialog(false)}
              >
                <Close />
              </IconButton>
            </Box>
          </DialogTitle>
          <DialogContent dividers sx={{ p: 2 }}>
            <Box
              component="pre"
              sx={{
                m: 0,
                p: 2,
                bgcolor: 'grey.900',
                color: 'common.white',
                borderRadius: 1,
                overflow: 'auto',
                fontFamily: 'monospace',
                fontSize: '0.875rem',
                lineHeight: 1.5,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word'
              }}
            >
              {typeof selectedResponse === 'string' 
                ? selectedResponse 
                : JSON.stringify(selectedResponse, null, 2)}
            </Box>
          </DialogContent>
        </StyledDialog>

        {/* User-managed runner environment */}
        <StyledDialog
          open={showEnvironmentDialog}
          onClose={() => setShowEnvironmentDialog(false)}
          maxWidth="sm"
          fullWidth
        >
          <DialogTitle>{creatingEnvironment ? 'Add environment' : 'Configure environment'}</DialogTitle>
          <DialogContent dividers>
            <Box sx={{ display: 'grid', gap: 2, pt: 1 }}>
              <TextField
                label="Environment name"
                value={environmentDraft.name}
                onChange={(event) => setEnvironmentDraft({ ...environmentDraft, name: event.target.value })}
                fullWidth
              />
              <TextField
                label="Backend URL"
                placeholder="https://api.example.com"
                helperText="Requests run from this browser directly to this URL. Use HTTPS, except for localhost development."
                value={environmentDraft.serverUrl}
                onChange={(event) => setEnvironmentDraft({ ...environmentDraft, serverUrl: event.target.value })}
                fullWidth
              />
              <TextField
                label="Team ID (optional)"
                value={environmentDraft.teamId}
                onChange={(event) => setEnvironmentDraft({ ...environmentDraft, teamId: event.target.value })}
                fullWidth
              />
              <TextField
                label="Bearer JWT (optional)"
                type="password"
                autoComplete="new-password"
                helperText="If the target uses Supabase and this app has a session for that server, its token is used automatically. Do not enter the shared X-API-Key; that is a service credential."
                value={environmentDraft.jwtToken}
                onChange={(event) => setEnvironmentDraft({ ...environmentDraft, jwtToken: event.target.value })}
                fullWidth
              />
              <Alert severity="info">
                The backend URL and team ID are stored in this browser. A JWT is kept only in page memory and is not saved. For cross-origin targets, configure the target server's CORS_ALLOWED_ORIGINS to include <code>{window.location.origin}</code>.
              </Alert>
            </Box>
          </DialogContent>
          <DialogActions sx={{ justifyContent: 'space-between' }}>
            <Box>
              {!creatingEnvironment && environments.length > 1 && (
                <Button color="error" onClick={deleteEnvironment}>Delete environment</Button>
              )}
            </Box>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button onClick={() => setShowEnvironmentDialog(false)}>Cancel</Button>
              <Button variant="contained" onClick={saveEnvironment} disabled={!environmentDraft.name.trim()}>
                Save environment
              </Button>
            </Box>
          </DialogActions>
        </StyledDialog>

        {/* Snackbar for notifications */}
        <Snackbar
          open={showSnackbar}
          autoHideDuration={4000}
          onClose={() => setShowSnackbar(false)}
          message={snackbarMessage}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        />
      </Box>

      {/* Scrollable Collections Area */}
      <Box sx={{ 
        flex: 1, 
        overflow: 'auto', 
        overflowX: 'hidden',
        px: 3, 
        py: 0.5, 
        minHeight: 0,
        maxHeight: '100%'
      }}>
        {collections.length === 0 && (
          <Card>
            <CardContent>
              <Typography variant="body1" color="text.secondary" align="center">
                No collections found in this workspace.
              </Typography>
            </CardContent>
          </Card>
        )}

        {collections.filter(collection => {
          const search = filterText.toLowerCase();
          if (!search) return true;
          return (
            collection.name.toLowerCase().includes(search) || 
            (collection.requests && collection.requests.some(r => 
              r.name.toLowerCase().includes(search) || 
              r.path.toLowerCase().includes(search)
            ))
          );
        }).map((collection) => {
        const isExpanded = expandedCollections.has(collection.id);
        const isLoadingRequests = loadingRequests.has(collection.id);
        const allSelected = collection.requests?.every(r => selectedRequests.has(r.id)) || false;
        const someSelected = collection.requests?.some(r => selectedRequests.has(r.id)) || false;

        return (
          <Accordion
            key={collection.id}
            expanded={isExpanded}
            onChange={() => handleCollectionToggle(collection.id)}
            disableGutters
            elevation={1}
            sx={{ 
              mb: 0.5,
              '&:before': { display: 'none' },
              '&.Mui-expanded': { 
                margin: '0 0 4px 0',
                minHeight: 'unset'
              }
            }}
          >
              <AccordionSummary 
                expandIcon={<ExpandMore />}
                sx={{ 
                  minHeight: 36,
                  py: 0.5,
                  '&.Mui-expanded': { minHeight: 36 },
                  '& .MuiAccordionSummary-content': { my: 0 },
                  '& .MuiAccordionSummary-content.Mui-expanded': { my: 0 }
                }}
              >
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, width: '100%' }}>
                {collection.requestCount > 0 && (
                  <Checkbox
                    checked={allSelected}
                    indeterminate={someSelected && !allSelected}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCollectionSelectAll(collection.id);
                    }}
                    size="small"
                  />
                )}
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography variant="body2" sx={{ fontWeight: 600, fontSize: '0.9rem' }}>
                    {collection.name}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem', lineHeight: 1 }}>
                    {collection.description || 'VirtualPyTest Server API collection. Select routes to test against your configured backend.'}
                  </Typography>
                </Box>
                <Chip
                  label={`${collection.requestCount} endpoints`}
                  size="small"
                  color="primary"
                  variant="outlined"
                  sx={{ height: 22, fontSize: '0.7rem' }}
                />
              </Box>
            </AccordionSummary>
            <AccordionDetails sx={{ p: 0.5, pt: 0 }}>
              {isLoadingRequests && (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 1 }}>
                  <CircularProgress size={20} />
                </Box>
              )}
              
              {collection.requests && (
                <List dense disablePadding>
                  {collection.requests.map((request) => (
                    <ListItem key={request.id} disablePadding>
                      <ListItemButton 
                        onClick={() => handleRequestToggle(request.id)} 
                        sx={{ 
                          py: 0.25,
                          minHeight: 26,
                          '&:hover': { bgcolor: 'action.hover' }
                        }}
                      >
                        <ListItemIcon sx={{ minWidth: 36 }}>
                          <Checkbox
                            checked={selectedRequests.has(request.id)}
                            edge="start"
                            tabIndex={-1}
                            disableRipple
                            size="small"
                          />
                        </ListItemIcon>
                        <ListItemText
                          primary={
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                              <Chip
                                label={request.method}
                                size="small"
                                color={
                                  request.method === 'GET' ? 'success' :
                                  request.method === 'POST' ? 'primary' :
                                  request.method === 'PUT' ? 'warning' :
                                  request.method === 'DELETE' ? 'error' :
                                  'default'
                                }
                                sx={{ 
                                  minWidth: 45, 
                                  height: 16, 
                                  fontFamily: 'monospace', 
                                  fontSize: '0.6rem',
                                  fontWeight: 600,
                                  '& .MuiChip-label': { px: 0.75, py: 0 }
                                }}
                              />
                              <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.8rem', lineHeight: 1.3 }}>
                                {request.path}
                              </Typography>
                            </Box>
                          }
                          secondary={
                            <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem', lineHeight: 1.2 }}>
                              {request.name}
                            </Typography>
                          }
                          sx={{ my: 0 }}
                        />
                      </ListItemButton>
                    </ListItem>
                  ))}
                </List>
              )}
            </AccordionDetails>
          </Accordion>
        );
      })}
      </Box>
    </Box>
  );
};

export default UserApiWorkspaceDetail;
