import {
  Add as AddIcon,
  Close as CloseIcon,
  Delete as DeleteIcon,
  Edit as EditIcon,
  OpenInNew as OpenInNewIcon,
  Refresh as RefreshIcon,
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
} from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  Grid,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  SelectChangeEvent,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import React, { useEffect, useState } from 'react';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { StyledDialog } from '../components/common/StyledDialog';

interface JiraInstance {
  id: string;
  name: string;
  domain: string;
  email: string;
  projectKey: string;
}

interface JiraTicket {
  id: string;
  key: string;
  summary: string;
  status: string;
  priority: string;
  assignee: string;
  created: string;
  updated: string;
  issueType: string;
  url: string;
}

interface JiraStats {
  total: number;
  byStatus: Record<string, number>;
}

const JiraIntegration: React.FC = () => {
  const [instances, setInstances] = useState<JiraInstance[]>([]);
  const [selectedInstance, setSelectedInstance] = useState<string>('');
  const [tickets, setTickets] = useState<JiraTicket[]>([]);
  const [stats, setStats] = useState<JiraStats | null>(null);
  const [error, setError] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  
  // Dialog states
  const [configDialogOpen, setConfigDialogOpen] = useState(false);
  const [editingInstance, setEditingInstance] = useState<JiraInstance | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    domain: '',
    email: '',
    apiToken: '',
    projectKey: '',
  });
  const [testingConnection, setTestingConnection] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  // Load instances on mount
  useEffect(() => {
    loadInstances();
  }, []);

  // Load tickets when instance selected
  useEffect(() => {
    if (selectedInstance) {
      loadTickets();
      loadStats();
    }
  }, [selectedInstance, statusFilter]);

  const loadInstances = async () => {
    try {
      const response = await fetch(buildServerUrl('/server/integrations/jira/instances'));
      const data = await response.json();
      
      if (data.success) {
        setInstances(data.instances);
        if (data.instances.length > 0 && !selectedInstance) {
          setSelectedInstance(data.instances[0].id);
        }
      }
    } catch (err) {
      console.error('Error loading JIRA instances:', err);
      setError('Failed to load JIRA instances');
    }
  };

  const loadTickets = async () => {
    if (!selectedInstance) return;
    
    setError('');
    
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.append('status', statusFilter);
      // Add cache-busting timestamp
      params.append('_t', Date.now().toString());
      
      const response = await fetch(
        buildServerUrl(`/server/integrations/jira/${selectedInstance}/tickets?${params}`),
        {
          cache: 'no-cache',
          headers: {
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
          }
        }
      );
      const data = await response.json();
      
      if (data.success) {
        setTickets(data.tickets);
      } else {
        setError(data.error || 'Failed to load tickets');
      }
    } catch (err) {
      console.error('Error loading tickets:', err);
      setError('Failed to load tickets');
    }
  };

  const loadStats = async () => {
    if (!selectedInstance) return;
    
    try {
      const response = await fetch(buildServerUrl(`/server/integrations/jira/${selectedInstance}/stats`));
      const data = await response.json();
      
      if (data.success) {
        setStats(data.stats);
      }
    } catch (err) {
      console.error('Error loading stats:', err);
    }
  };

  const handleInstanceChange = (event: SelectChangeEvent) => {
    setSelectedInstance(event.target.value);
    setStatusFilter('');
  };

  const handleStatusFilterChange = (event: SelectChangeEvent) => {
    setStatusFilter(event.target.value);
  };

  const handleAddInstance = () => {
    setEditingInstance(null);
    setFormData({ name: '', domain: '', email: '', apiToken: '', projectKey: '' });
    setTestResult(null);
    setConfigDialogOpen(true);
  };

  const handleEditInstance = (instance: JiraInstance) => {
    setEditingInstance(instance);
    setFormData({
      name: instance.name,
      domain: instance.domain,
      email: instance.email,
      apiToken: '',
      projectKey: instance.projectKey,
    });
    setTestResult(null);
    setConfigDialogOpen(true);
  };

  const handleDeleteInstance = async (instanceId: string) => {
    if (!confirm('Are you sure you want to delete this JIRA instance?')) return;
    
    try {
      const response = await fetch(buildServerUrl(`/server/integrations/jira/instances/${instanceId}`), {
        method: 'DELETE',
      });
      const data = await response.json();
      
      if (data.success) {
        loadInstances();
        if (selectedInstance === instanceId) {
          setSelectedInstance('');
        }
      }
    } catch (err) {
      console.error('Error deleting instance:', err);
      alert('Failed to delete instance');
    }
  };

  const handleTestConnection = async () => {
    setTestingConnection(true);
    setTestResult(null);
    
    try {
      const response = await fetch(buildServerUrl('/server/integrations/jira/test/test'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });
      const data = await response.json();
      
      if (data.success) {
        setTestResult({
          success: true,
          message: `Connected successfully as ${data.user}`,
        });
      } else {
        setTestResult({
          success: false,
          message: data.error || 'Connection failed',
        });
      }
    } catch (err) {
      setTestResult({
        success: false,
        message: 'Connection test failed',
      });
    } finally {
      setTestingConnection(false);
    }
  };

  const handleSaveInstance = async () => {
    try {
      const payload = editingInstance
        ? { ...formData, id: editingInstance.id }
        : formData;
      
      const response = await fetch(buildServerUrl('/server/integrations/jira/instances'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      
      if (data.success) {
        setConfigDialogOpen(false);
        loadInstances();
      } else {
        alert(data.error || 'Failed to save instance');
      }
    } catch (err) {
      console.error('Error saving instance:', err);
      alert('Failed to save instance');
    }
  };

  const getPriorityColor = (priority: string) => {
    const priorityLower = priority.toLowerCase();
    if (priorityLower.includes('high') || priorityLower.includes('critical')) return 'error';
    if (priorityLower.includes('medium')) return 'warning';
    return 'default';
  };

  const getStatusColor = (status: string) => {
    const statusLower = status.toLowerCase();
    if (statusLower.includes('done') || statusLower.includes('closed')) return 'success';
    if (statusLower.includes('progress')) return 'primary';
    return 'default';
  };

  const selectedInstanceData = instances.find((i) => i.id === selectedInstance);

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">JIRA Integration</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={handleAddInstance}>
          Add JIRA Instance
        </Button>
      </Box>

      {/* Instance Selection */}
      {instances.length > 0 && (
        <Box sx={{ mb: 3 }}>
          <Grid container spacing={2} alignItems="center">
            <Grid item xs={12} md={4}>
              <FormControl fullWidth>
                <InputLabel>JIRA Instance</InputLabel>
                <Select value={selectedInstance} onChange={handleInstanceChange} label="JIRA Instance">
                  {instances.map((instance) => (
                    <MenuItem key={instance.id} value={instance.id}>
                      {instance.name} ({instance.domain})
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} md={3}>
              <FormControl fullWidth>
                <InputLabel>Status Filter</InputLabel>
                <Select value={statusFilter} onChange={handleStatusFilterChange} label="Status Filter">
                  <MenuItem value="">All</MenuItem>
                  <MenuItem value="Open">Open</MenuItem>
                  <MenuItem value="In Progress">In Progress</MenuItem>
                  <MenuItem value="To Do">To Do</MenuItem>
                  <MenuItem value="Done">Done</MenuItem>
                  <MenuItem value="Closed">Closed</MenuItem>
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} md={5} sx={{ display: 'flex', gap: 1 }}>
              <Button variant="outlined" startIcon={<RefreshIcon />} onClick={loadTickets}>
                Refresh
              </Button>
              {selectedInstanceData && (
                <>
                  <Button
                    variant="outlined"
                    startIcon={<EditIcon />}
                    onClick={() => handleEditInstance(selectedInstanceData)}
                  >
                    Edit
                  </Button>
                  <Button
                    variant="outlined"
                    color="error"
                    startIcon={<DeleteIcon />}
                    onClick={() => handleDeleteInstance(selectedInstance)}
                  >
                    Delete
                  </Button>
                </>
              )}
            </Grid>
          </Grid>
        </Box>
      )}

      {/* Stats Cards */}
      {stats && (
        <Grid container spacing={2} sx={{ mb: 3 }}>
          <Grid item xs={12} md={3}>
            <Card>
              <CardContent>
                <Typography color="text.secondary" gutterBottom>
                  Total Tickets
                </Typography>
                <Typography variant="h3">{stats.total}</Typography>
              </CardContent>
            </Card>
          </Grid>
          {Object.entries(stats.byStatus).map(([status, count]) => (
            <Grid item xs={6} md={2.25} key={status}>
              <Card>
                <CardContent>
                  <Typography color="text.secondary" gutterBottom>
                    {status}
                  </Typography>
                  <Typography variant="h4">{count}</Typography>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      {/* Error Display */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {/* Tickets Table */}
      {selectedInstance && tickets.length > 0 && (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Key</TableCell>
                <TableCell>Summary</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Priority</TableCell>
                <TableCell>Assignee</TableCell>
                <TableCell>Created</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {tickets.map((ticket) => (
                <TableRow 
                  key={ticket.id} 
                  hover 
                  sx={{ 
                    '&:hover': { 
                      backgroundColor: 'rgba(255, 255, 255, 0.05) !important' 
                    } 
                  }}
                >
                  <TableCell>
                    <Typography variant="body2" fontWeight="bold">
                      {ticket.key}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">{ticket.summary}</Typography>
                  </TableCell>
                  <TableCell>
                    <Chip label={ticket.issueType} size="small" />
                  </TableCell>
                  <TableCell>
                    <Chip label={ticket.status} size="small" color={getStatusColor(ticket.status)} />
                  </TableCell>
                  <TableCell>
                    <Chip label={ticket.priority} size="small" color={getPriorityColor(ticket.priority)} />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">{ticket.assignee}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">
                      {new Date(ticket.created).toLocaleDateString()}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Tooltip title="Open in JIRA">
                      <IconButton
                        size="small"
                        component="a"
                        href={ticket.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <OpenInNewIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Empty State */}
      {!selectedInstance && instances.length === 0 && (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="h6" gutterBottom>
            No JIRA instances configured
          </Typography>
          <Typography color="text.secondary" sx={{ mb: 2 }}>
            Add a JIRA instance to start tracking tickets
          </Typography>
          <Button variant="contained" startIcon={<AddIcon />} onClick={handleAddInstance}>
            Add JIRA Instance
          </Button>
        </Paper>
      )}

      {/* Configuration Dialog */}
      <StyledDialog open={configDialogOpen} onClose={() => setConfigDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          {editingInstance ? 'Edit JIRA Instance' : 'Add JIRA Instance'}
          <IconButton
            onClick={() => setConfigDialogOpen(false)}
            sx={{ position: 'absolute', right: 8, top: 8 }}
          >
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 2 }}>
            <TextField
              label="Instance Name"
              fullWidth
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="My JIRA"
            />
            <TextField
              label="JIRA Domain"
              fullWidth
              value={formData.domain}
              onChange={(e) => setFormData({ ...formData, domain: e.target.value })}
              placeholder="yourcompany.atlassian.net"
              helperText="Your JIRA domain (without https://)"
            />
            <TextField
              label="Email"
              fullWidth
              type="email"
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              placeholder="your.email@company.com"
            />
            <TextField
              label="API Token"
              fullWidth
              type="password"
              value={formData.apiToken}
              onChange={(e) => setFormData({ ...formData, apiToken: e.target.value })}
              helperText="Generate at: https://id.atlassian.com/manage/api-tokens"
            />
            <TextField
              label="Project Key"
              fullWidth
              value={formData.projectKey}
              onChange={(e) => setFormData({ ...formData, projectKey: e.target.value })}
              placeholder="PROJ"
              helperText="The project key (e.g., PROJ from PROJ-123)"
            />

            {testResult && (
              <Alert
                severity={testResult.success ? 'success' : 'error'}
                icon={testResult.success ? <CheckCircleIcon /> : <ErrorIcon />}
              >
                {testResult.message}
              </Alert>
            )}

            <Button
              variant="outlined"
              onClick={handleTestConnection}
              disabled={
                testingConnection ||
                !formData.domain ||
                !formData.email ||
                !formData.apiToken ||
                !formData.projectKey
              }
            >
              {testingConnection ? 'Testing...' : 'Test Connection'}
            </Button>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfigDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleSaveInstance}
            disabled={
              !formData.name ||
              !formData.domain ||
              !formData.email ||
              !formData.apiToken ||
              !formData.projectKey
            }
          >
            Save
          </Button>
        </DialogActions>
      </StyledDialog>
    </Box>
  );
};

export default JiraIntegration;

