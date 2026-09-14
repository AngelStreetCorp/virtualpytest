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

interface Request {
  id: string;
  name: string;
  fullName: string;
  method: string;
  path: string;
  description: string;
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

interface EnvironmentVariable {
  key: string;
  value: any;
  type?: 'default' | 'secret';
}

interface Environment {
  id: string;
  name: string;
  workspaceId: string;
  variables: EnvironmentVariable[];
}

const UserApiWorkspaceDetail: React.FC = () => {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const navigate = useNavigate();
  
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [selectedEnvironment, setSelectedEnvironment] = useState<string>('');
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
  const [filterText, setFilterText] = useState('');

  // Auto-select first environment when environments load
  useEffect(() => {
    if (environments.length > 0 && !selectedEnvironment) {
      setSelectedEnvironment(environments[0].id);
    }
  }, [environments, selectedEnvironment]);

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

      // Load environments for this workspace
      const envResponse = await fetch(buildServerUrl(`/server/postman/environments?workspaceId=${workspaceId}`));
      const envData = await envResponse.json();
      
      if (envData.success) {
        setEnvironments(envData.environments);
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

    setRunning(true);
    setTestResult(null);

    try {
      // Gather selected endpoints
      const endpoints: any[] = [];
      
      collections.forEach(collection => {
        if (collection.requests) {
          collection.requests.forEach(request => {
            if (selectedRequests.has(request.id)) {
              endpoints.push({
                method: request.method,
                path: request.path,
                name: request.name,
              });
            }
          });
        }
      });

      if (endpoints.length === 0) {
        setRunning(false);
        setSnackbarMessage('Error: Selected endpoints could not be found in the loaded collections. Please try reloading the page.');
        setShowSnackbar(true);
        return;
      }

      const response = await fetch(buildServerUrl('/server/postman/test'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspaceId,
          workspaceName: workspace?.name,
          environmentId: selectedEnvironment || undefined,
          endpoints,
        }),
      });

      const data = await response.json();
      setTestResult(data);
      if (data.success && data.results) {
        setShowResultsDialog(true);
      }
    } catch (err) {
      console.error('Error running tests:', err);
      setTestResult({ success: false, error: 'Failed to run tests' });
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

          {/* Environment Selector */}
          {environments.length > 0 && (
            <>
              <FormControl size="small" sx={{ minWidth: 200, mt: 0.5 }}>
                <InputLabel>Environment</InputLabel>
                <Select
                  value={selectedEnvironment}
                  label="Environment"
                  onChange={(e) => setSelectedEnvironment(e.target.value)}
                >
                  {environments.map((env) => (
                    <MenuItem key={env.id} value={env.id}>
                      {env.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>

              {selectedEnvironment && (
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => setShowEnvironmentDialog(true)}
                  sx={{ textTransform: 'none' }}
                >
                  View Variables ({environments.find(e => e.id === selectedEnvironment)?.variables?.length || 0})
                </Button>
              )}
            </>
          )}

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

        {/* Environment Variables Dialog */}
        <StyledDialog
          open={showEnvironmentDialog}
          onClose={() => setShowEnvironmentDialog(false)}
          maxWidth="md"
          fullWidth
        >
          <DialogTitle sx={{ m: 0, p: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
              Environment Variables - {environments.find(e => e.id === selectedEnvironment)?.name}
            </Typography>
            <IconButton
              size="small"
              onClick={() => setShowEnvironmentDialog(false)}
            >
              <Close />
            </IconButton>
          </DialogTitle>
          <DialogContent dividers sx={{ p: 0, bgcolor: 'transparent' }}>
            <TableContainer sx={{ 
              bgcolor: 'transparent',
              border: '2px solid',
              borderColor: 'divider'
            }}>
              <Table size="small" sx={{ bgcolor: 'transparent' }}>
                <TableHead>
                  <TableRow sx={{ 
                    bgcolor: 'transparent',
                    '&:hover': { bgcolor: 'transparent !important' }
                  }}>
                    <TableCell sx={{ 
                      fontWeight: 600, 
                      width: '30%',
                      bgcolor: 'transparent',
                      borderColor: 'divider',
                      color: 'text.secondary'
                    }}>Variable</TableCell>
                    <TableCell sx={{ 
                      fontWeight: 600,
                      bgcolor: 'transparent',
                      borderColor: 'divider',
                      color: 'text.secondary'
                    }}>Value</TableCell>
                    <TableCell sx={{ 
                      fontWeight: 600, 
                      width: '10%',
                      bgcolor: 'transparent',
                      borderColor: 'divider',
                      color: 'text.secondary'
                    }}>Type</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {environments.find(e => e.id === selectedEnvironment)?.variables?.map((variable, index) => (
                    <TableRow key={index} sx={{ 
                      bgcolor: 'transparent',
                      '&:hover': { bgcolor: 'rgba(255, 255, 255, 0.03) !important' }
                    }}>
                      <TableCell sx={{ 
                        fontFamily: 'monospace', 
                        fontSize: '0.85rem',
                        bgcolor: 'transparent',
                        borderColor: 'divider'
                      }}>
                        {variable.key}
                      </TableCell>
                      <TableCell sx={{ 
                        fontFamily: 'monospace', 
                        fontSize: '0.85rem',
                        bgcolor: 'transparent',
                        borderColor: 'divider'
                      }}>
                        {variable.type === 'secret' ? (
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <Typography sx={{ fontFamily: 'monospace', letterSpacing: 2 }}>
                              {'•'.repeat(40)}
                            </Typography>
                            <Tooltip title="Secret value - masked for security">
                              <Chip label="🔒" size="small" sx={{ height: 18, fontSize: '0.7rem' }} />
                            </Tooltip>
                          </Box>
                        ) : (
                          variable.value || <em style={{ color: '#888' }}>null</em>
                        )}
                      </TableCell>
                      <TableCell sx={{
                        bgcolor: 'transparent',
                        borderColor: 'divider'
                      }}>
                        <Chip
                          label={variable.type === 'secret' ? 'secret' : 'default'}
                          size="small"
                          color={variable.type === 'secret' ? 'error' : 'default'}
                          variant="outlined"
                          sx={{ height: 20, fontSize: '0.65rem' }}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </DialogContent>
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
                    {collection.description || 'No description'}
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

