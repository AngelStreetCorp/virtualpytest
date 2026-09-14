import {
  Clear as ClearIcon,
  ExpandLess,
  ExpandMore,
  Memory as ModelIcon,
  PlayArrow as ActionIcon,
  Search as SearchIcon,
  Verified as VerificationIcon,
} from '@mui/icons-material';
import {
  Alert,
  Box,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Collapse,
  FormControl,
  IconButton,
  InputAdornment,
  MenuItem,
  Paper,
  Select,
  SelectChangeEvent,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import React, { useState, useEffect } from 'react';

import { 
  useDependency,
  type ScriptNodeDependency,
  type ScriptEdgeDependency,
  type NodeScriptDependency,
  type EdgeScriptDependency,
} from '../hooks/pages/useDependency';
import { useUserInterface } from '../hooks/pages/useUserInterface';

const DependencyReport: React.FC = () => {
  const { loadDependencyData, loading, error, setError } = useDependency();
  const { getAllUserInterfaces } = useUserInterface();

  const [activeTab, setActiveTab] = useState(0);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  // User interface selection state
  const [userInterfaces, setUserInterfaces] = useState<any[]>([]);
  const [selectedUserInterface, setSelectedUserInterface] = useState<string>('');
  const [loadingInterfaces, setLoadingInterfaces] = useState(true);

  // Data states
  const [scriptNodeDependencies, setScriptNodeDependencies] = useState<ScriptNodeDependency[]>([]);
  const [scriptEdgeDependencies, setScriptEdgeDependencies] = useState<ScriptEdgeDependency[]>([]);
  const [nodeScriptDependencies, setNodeScriptDependencies] = useState<NodeScriptDependency[]>([]);
  const [edgeScriptDependencies, setEdgeScriptDependencies] = useState<EdgeScriptDependency[]>([]);

  // Filter states
  const [scriptNodeFilter, setScriptNodeFilter] = useState('');
  const [scriptEdgeFilter, setScriptEdgeFilter] = useState('');
  const [nodeScriptFilter, setNodeScriptFilter] = useState('');
  const [edgeScriptFilter, setEdgeScriptFilter] = useState('');

  // Toggle row expansion
  const toggleRowExpansion = (rowId: string) => {
    const newExpanded = new Set(expandedRows);
    if (newExpanded.has(rowId)) {
      newExpanded.delete(rowId);
    } else {
      newExpanded.add(rowId);
    }
    setExpandedRows(newExpanded);
  };

  // Load user interfaces on mount
  useEffect(() => {
    const loadInterfaces = async () => {
      try {
        setLoadingInterfaces(true);
        const interfaces = await getAllUserInterfaces();
        setUserInterfaces(interfaces);
      } catch (err) {
        console.error('[@component:DependencyReport] Error loading user interfaces:', err);
        setError(err instanceof Error ? err.message : 'Failed to load user interfaces');
      } finally {
        setLoadingInterfaces(false);
      }
    };

    loadInterfaces();
  }, [getAllUserInterfaces, setError]);

  // Load dependency data when user interface is selected
  useEffect(() => {
    if (!selectedUserInterface) {
      // Clear data when no interface selected
      setScriptNodeDependencies([]);
      setScriptEdgeDependencies([]);
      setNodeScriptDependencies([]);
      setEdgeScriptDependencies([]);
      return;
    }

    const loadData = async () => {
      try {
        const dependencyData = await loadDependencyData(selectedUserInterface);
        setScriptNodeDependencies(dependencyData.scriptNodeDependencies);
        setScriptEdgeDependencies(dependencyData.scriptEdgeDependencies);
        setNodeScriptDependencies(dependencyData.nodeScriptDependencies);
        setEdgeScriptDependencies(dependencyData.edgeScriptDependencies);
      } catch (err) {
        console.error('[@component:DependencyReport] Error loading dependency data:', err);
        // Error is already handled by the hook
      }
    };

    loadData();
  }, [selectedUserInterface, loadDependencyData]);

  // Handle user interface selection change
  const handleUserInterfaceChange = (event: SelectChangeEvent) => {
    setSelectedUserInterface(event.target.value);
  };

  // Filter functions
  const filteredScriptNodeDependencies = scriptNodeDependencies.filter(
    (script) =>
      script.script_name.toLowerCase().includes(scriptNodeFilter.toLowerCase()) ||
      (script.userinterface_name &&
        script.userinterface_name.toLowerCase().includes(scriptNodeFilter.toLowerCase())),
  );

  const filteredScriptEdgeDependencies = scriptEdgeDependencies.filter(
    (script) =>
      script.script_name.toLowerCase().includes(scriptEdgeFilter.toLowerCase()) ||
      (script.userinterface_name &&
        script.userinterface_name.toLowerCase().includes(scriptEdgeFilter.toLowerCase())),
  );

  const filteredNodeScriptDependencies = nodeScriptDependencies.filter(
    (node) =>
      node.node_name.toLowerCase().includes(nodeScriptFilter.toLowerCase()) ||
      node.tree_name.toLowerCase().includes(nodeScriptFilter.toLowerCase()),
  );

  const filteredEdgeScriptDependencies = edgeScriptDependencies.filter(
    (edge) =>
      edge.edge_name.toLowerCase().includes(edgeScriptFilter.toLowerCase()) ||
      edge.tree_name.toLowerCase().includes(edgeScriptFilter.toLowerCase()),
  );

  // Helper functions
  const getSuccessRateColor = (rate: number) => {
    if (rate >= 80) return 'success';
    if (rate >= 60) return 'warning';
    return 'error';
  };

  // Loading state component
  const LoadingState = () => (
    <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
      <CircularProgress />
    </Box>
  );

  // Empty state component
  const EmptyState = ({ message }: { message: string }) => (
    <TableRow>
      <TableCell colSpan={10} sx={{ textAlign: 'center', py: 4 }}>
        <Typography variant="body2" color="textSecondary">
          {message}
        </Typography>
      </TableCell>
    </TableRow>
  );

  // Search field component
  const SearchField = ({
    value,
    onChange,
    placeholder,
  }: {
    value: string;
    onChange: (value: string) => void;
    placeholder: string;
  }) => (
    <TextField
      size="small"
      placeholder={placeholder}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      InputProps={{
        startAdornment: (
          <InputAdornment position="start">
            <SearchIcon />
          </InputAdornment>
        ),
        endAdornment: value && (
          <InputAdornment position="end">
            <IconButton size="small" onClick={() => onChange('')}>
              <ClearIcon />
            </IconButton>
          </InputAdornment>
        ),
      }}
      sx={{ minWidth: 250 }}
    />
  );

  return (
    <Box>
      <Box sx={{ mb: 1 }}>
        <Typography variant="h4" sx={{ mb: 1 }}>
          Dependency Report
        </Typography>

        {/* User Interface Selector */}
        <FormControl size="small" sx={{ minWidth: 250, zIndex: 9999, position: 'relative' }}>
          <Select
            value={selectedUserInterface}
            onChange={handleUserInterfaceChange}
            disabled={loadingInterfaces || userInterfaces.length === 0}
            displayEmpty
            renderValue={(value) => {
              if (!value) {
                return (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, fontStyle: 'italic', opacity: 0.6 }}>
                    <ModelIcon fontSize="small" />
                    Select user interface...
                  </Box>
                );
              }
              return (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <ModelIcon fontSize="small" />
                  {value}
                </Box>
              );
            }}
          >
            <MenuItem value="">
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, fontStyle: 'italic', opacity: 0.6 }}>
                <ModelIcon fontSize="small" />
                Select a user interface...
              </Box>
            </MenuItem>
            {userInterfaces.map((ui) => (
              <MenuItem key={ui.id} value={ui.name}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <ModelIcon fontSize="small" />
                  {ui.name}
                </Box>
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Show empty state when no interface selected */}
      {!selectedUserInterface ? (
        <Card>
          <CardContent sx={{ py: 6, textAlign: 'center' }}>
            <ModelIcon sx={{ fontSize: 64, color: 'text.secondary', mb: 1 }} />
            <Typography variant="h6" color="text.secondary" gutterBottom>
              Select User Interface to Analyze
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Choose a user interface from the dropdown above to view dependency analysis between scripts, nodes, and edges.
            </Typography>
          </CardContent>
        </Card>
      ) : (
      <Card>
        <CardContent>
          <Tabs value={activeTab} onChange={(_, newValue) => setActiveTab(newValue)}>
            <Tab label="Script → Nodes" />
            <Tab label="Script → Edges" />
            <Tab label="Node → Scripts" />
            <Tab label="Edge → Scripts" />
          </Tabs>

          {/* Tab 1: Script → Nodes */}
          {activeTab === 0 && (
            <Box sx={{ mt: 2 }}>
              <Box
                sx={{
                  mb: 2,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <Typography variant="h6">
                  Script → Node Dependencies ({filteredScriptNodeDependencies.length})
                </Typography>
                <SearchField
                  value={scriptNodeFilter}
                  onChange={setScriptNodeFilter}
                  placeholder="Search scripts..."
                />
              </Box>

              <TableContainer component={Paper} variant="outlined">
                <Table
                  size="small"
                  sx={{
                    '& .MuiTableRow-root:hover': { backgroundColor: 'transparent !important' },
                  }}
                >
                  <TableHead>
                    <TableRow>
                      <TableCell width="50"></TableCell>
                      <TableCell>
                        <strong>Script</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Interface</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Nodes Used</strong>
                      </TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {loading ? (
                      <TableRow>
                        <TableCell colSpan={4}>
                          <LoadingState />
                        </TableCell>
                      </TableRow>
                    ) : filteredScriptNodeDependencies.length === 0 ? (
                      <EmptyState message="No script-node dependencies found" />
                    ) : (
                      filteredScriptNodeDependencies.map((script) => (
                        <React.Fragment key={script.script_result_id}>
                          <TableRow
                            sx={{
                              '&:hover': {
                                backgroundColor: 'transparent !important',
                              },
                            }}
                          >
                            <TableCell>
                              <IconButton
                                size="small"
                                onClick={() =>
                                  toggleRowExpansion(`script-node-${script.script_result_id}`)
                                }
                              >
                                {expandedRows.has(`script-node-${script.script_result_id}`) ? (
                                  <ExpandLess />
                                ) : (
                                  <ExpandMore />
                                )}
                              </IconButton>
                            </TableCell>
                            <TableCell>
                              <Typography variant="body2" fontWeight="medium">
                                {script.script_name}
                              </Typography>
                            </TableCell>
                            <TableCell>{script.userinterface_name || 'N/A'}</TableCell>
                            <TableCell>
                              <Typography variant="body2" color="textSecondary">
                                {script.nodes.length} nodes
                              </Typography>
                            </TableCell>
                          </TableRow>
                          <TableRow>
                            <TableCell colSpan={4} sx={{ p: 0, border: 0 }}>
                              <Collapse
                                in={expandedRows.has(`script-node-${script.script_result_id}`)}
                              >
                                <Box sx={{ pl: 7, pr: 2, py: 1, backgroundColor: 'rgba(0, 0, 0, 0.02)' }}>
                                  <Table
                                    size="small"
                                    sx={{
                                      '& .MuiTableRow-root:hover': {
                                        backgroundColor: 'transparent !important',
                                      },
                                      tableLayout: 'fixed',
                                    }}
                                  >
                                    <TableHead>
                                      <TableRow sx={{ backgroundColor: 'rgba(255, 255, 255, 0.05)' }}>
                                        <TableCell width="40%" sx={{ py: 0.5, color: 'rgba(255, 255, 255, 0.7)', fontSize: '0.75rem', fontWeight: 500 }}>Node</TableCell>
                                        <TableCell width="30%" sx={{ py: 0.5, color: 'rgba(255, 255, 255, 0.7)', fontSize: '0.75rem', fontWeight: 500, textAlign: 'center' }}>Executions</TableCell>
                                        <TableCell width="30%" sx={{ py: 0.5, color: 'rgba(255, 255, 255, 0.7)', fontSize: '0.75rem', fontWeight: 500, textAlign: 'center' }}>Success Rate</TableCell>
                                      </TableRow>
                                    </TableHead>
                                    <TableBody>
                                      {script.nodes.map((node) => (
                                        <TableRow
                                          key={node.node_id}
                                          sx={{
                                            '&:hover': {
                                              backgroundColor: 'transparent !important',
                                            },
                                          }}
                                        >
                                          <TableCell sx={{ py: 0.5 }}>
                                            <Box
                                              sx={{ display: 'flex', alignItems: 'center', gap: 1 }}
                                            >
                                              <VerificationIcon
                                                fontSize="small"
                                                color="secondary"
                                              />
                                              {node.node_name}
                                            </Box>
                                          </TableCell>
                                          <TableCell sx={{ py: 0.5, textAlign: 'center' }}>{node.execution_count}</TableCell>
                                          <TableCell sx={{ py: 0.5, textAlign: 'center' }}>
                                            <Chip
                                              label={`${node.success_rate.toFixed(1)}%`}
                                              color={getSuccessRateColor(node.success_rate)}
                                              size="small"
                                              variant="outlined"
                                            />
                                          </TableCell>
                                        </TableRow>
                                      ))}
                                    </TableBody>
                                  </Table>
                                </Box>
                              </Collapse>
                            </TableCell>
                          </TableRow>
                        </React.Fragment>
                      ))
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            </Box>
          )}

          {/* Tab 2: Script → Edges */}
          {activeTab === 1 && (
            <Box sx={{ mt: 2 }}>
              <Box
                sx={{
                  mb: 2,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <Typography variant="h6">
                  Script → Edge Dependencies ({filteredScriptEdgeDependencies.length})
                </Typography>
                <SearchField
                  value={scriptEdgeFilter}
                  onChange={setScriptEdgeFilter}
                  placeholder="Search scripts..."
                />
              </Box>

              <TableContainer component={Paper} variant="outlined">
                <Table
                  size="small"
                  sx={{
                    '& .MuiTableRow-root:hover': { backgroundColor: 'transparent !important' },
                  }}
                >
                  <TableHead>
                    <TableRow>
                      <TableCell width="50"></TableCell>
                      <TableCell>
                        <strong>Script</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Interface</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Edges Used</strong>
                      </TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {loading ? (
                      <TableRow>
                        <TableCell colSpan={4}>
                          <LoadingState />
                        </TableCell>
                      </TableRow>
                    ) : filteredScriptEdgeDependencies.length === 0 ? (
                      <EmptyState message="No script-edge dependencies found" />
                    ) : (
                      filteredScriptEdgeDependencies.map((script) => (
                        <React.Fragment key={script.script_result_id}>
                          <TableRow
                            sx={{
                              '&:hover': {
                                backgroundColor: 'transparent !important',
                              },
                            }}
                          >
                            <TableCell>
                              <IconButton
                                size="small"
                                onClick={() =>
                                  toggleRowExpansion(`script-edge-${script.script_result_id}`)
                                }
                              >
                                {expandedRows.has(`script-edge-${script.script_result_id}`) ? (
                                  <ExpandLess />
                                ) : (
                                  <ExpandMore />
                                )}
                              </IconButton>
                            </TableCell>
                            <TableCell>
                              <Typography variant="body2" fontWeight="medium">
                                {script.script_name}
                              </Typography>
                            </TableCell>
                            <TableCell>{script.userinterface_name || 'N/A'}</TableCell>
                            <TableCell>
                              <Typography variant="body2" color="textSecondary">
                                {script.edges.length} edges
                              </Typography>
                            </TableCell>
                          </TableRow>
                          <TableRow>
                            <TableCell colSpan={4} sx={{ p: 0, border: 0 }}>
                              <Collapse
                                in={expandedRows.has(`script-edge-${script.script_result_id}`)}
                              >
                                <Box sx={{ pl: 7, pr: 2, py: 1, backgroundColor: 'rgba(0, 0, 0, 0.02)' }}>
                                  <Table
                                    size="small"
                                    sx={{
                                      '& .MuiTableRow-root:hover': {
                                        backgroundColor: 'transparent !important',
                                      },
                                      tableLayout: 'fixed',
                                    }}
                                  >
                                    <TableHead>
                                      <TableRow sx={{ backgroundColor: 'rgba(255, 255, 255, 0.05)' }}>
                                        <TableCell width="40%" sx={{ py: 0.5, color: 'rgba(255, 255, 255, 0.7)', fontSize: '0.75rem', fontWeight: 500 }}>Edge</TableCell>
                                        <TableCell width="30%" sx={{ py: 0.5, color: 'rgba(255, 255, 255, 0.7)', fontSize: '0.75rem', fontWeight: 500, textAlign: 'center' }}>Executions</TableCell>
                                        <TableCell width="30%" sx={{ py: 0.5, color: 'rgba(255, 255, 255, 0.7)', fontSize: '0.75rem', fontWeight: 500, textAlign: 'center' }}>Success Rate</TableCell>
                                      </TableRow>
                                    </TableHead>
                                    <TableBody>
                                      {script.edges.map((edge) => (
                                        <TableRow
                                          key={edge.edge_id}
                                          sx={{
                                            '&:hover': {
                                              backgroundColor: 'transparent !important',
                                            },
                                          }}
                                        >
                                          <TableCell sx={{ py: 0.5 }}>
                                            <Box
                                              sx={{ display: 'flex', alignItems: 'center', gap: 1 }}
                                            >
                                              <ActionIcon fontSize="small" color="primary" />
                                              {edge.edge_name}
                                            </Box>
                                          </TableCell>
                                          <TableCell sx={{ py: 0.5, textAlign: 'center' }}>{edge.execution_count}</TableCell>
                                          <TableCell sx={{ py: 0.5, textAlign: 'center' }}>
                                            <Chip
                                              label={`${edge.success_rate.toFixed(1)}%`}
                                              color={getSuccessRateColor(edge.success_rate)}
                                              size="small"
                                              variant="outlined"
                                            />
                                          </TableCell>
                                        </TableRow>
                                      ))}
                                    </TableBody>
                                  </Table>
                                </Box>
                              </Collapse>
                            </TableCell>
                          </TableRow>
                        </React.Fragment>
                      ))
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            </Box>
          )}

          {/* Tab 3: Node → Scripts */}
          {activeTab === 2 && (
            <Box sx={{ mt: 2 }}>
              <Box
                sx={{
                  mb: 2,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <Typography variant="h6">
                  Node → Script Dependencies ({filteredNodeScriptDependencies.length})
                </Typography>
                <SearchField
                  value={nodeScriptFilter}
                  onChange={setNodeScriptFilter}
                  placeholder="Search nodes..."
                />
              </Box>

              <TableContainer component={Paper} variant="outlined">
                <Table
                  size="small"
                  sx={{
                    '& .MuiTableRow-root:hover': { backgroundColor: 'transparent !important' },
                  }}
                >
                  <TableHead>
                    <TableRow>
                      <TableCell width="50"></TableCell>
                      <TableCell>
                        <strong>Node</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Interface</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Overall Success Rate</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Used by Scripts</strong>
                      </TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {loading ? (
                      <TableRow>
                        <TableCell colSpan={5}>
                          <LoadingState />
                        </TableCell>
                      </TableRow>
                    ) : filteredNodeScriptDependencies.length === 0 ? (
                      <EmptyState message="No node-script dependencies found" />
                    ) : (
                      filteredNodeScriptDependencies.map((node) => (
                        <React.Fragment key={node.node_id}>
                          <TableRow
                            sx={{
                              '&:hover': {
                                backgroundColor: 'transparent !important',
                              },
                            }}
                          >
                            <TableCell>
                              <IconButton
                                size="small"
                                onClick={() => toggleRowExpansion(`node-script-${node.node_id}`)}
                              >
                                {expandedRows.has(`node-script-${node.node_id}`) ? (
                                  <ExpandLess />
                                ) : (
                                  <ExpandMore />
                                )}
                              </IconButton>
                            </TableCell>
                            <TableCell>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <VerificationIcon fontSize="small" color="secondary" />
                                <Typography variant="body2" fontWeight="medium">
                                  {node.node_name}
                                </Typography>
                              </Box>
                            </TableCell>
                            <TableCell>{node.tree_name}</TableCell>
                            <TableCell>
                              <Chip
                                label={`${node.overall_success_rate.toFixed(1)}%`}
                                color={getSuccessRateColor(node.overall_success_rate)}
                                size="small"
                                variant="outlined"
                              />
                            </TableCell>
                            <TableCell>
                              <Typography variant="body2" color="textSecondary">
                                {node.scripts.length} unique scripts
                              </Typography>
                            </TableCell>
                          </TableRow>
                          <TableRow>
                            <TableCell colSpan={5} sx={{ p: 0, border: 0 }}>
                              <Collapse in={expandedRows.has(`node-script-${node.node_id}`)}>
                                <Box sx={{ pl: 7, pr: 2, py: 1, backgroundColor: 'rgba(0, 0, 0, 0.02)' }}>
                                  <Table
                                    size="small"
                                    sx={{
                                      '& .MuiTableRow-root:hover': {
                                        backgroundColor: 'transparent !important',
                                      },
                                      tableLayout: 'fixed',
                                    }}
                                  >
                                    <TableHead>
                                      <TableRow sx={{ backgroundColor: 'rgba(255, 255, 255, 0.05)' }}>
                                        <TableCell width="40%" sx={{ py: 0.5, color: 'rgba(255, 255, 255, 0.7)', fontSize: '0.75rem', fontWeight: 500 }}>Script</TableCell>
                                        <TableCell width="30%" sx={{ py: 0.5, color: 'rgba(255, 255, 255, 0.7)', fontSize: '0.75rem', fontWeight: 500, textAlign: 'center' }}>Executions</TableCell>
                                        <TableCell width="30%" sx={{ py: 0.5, color: 'rgba(255, 255, 255, 0.7)', fontSize: '0.75rem', fontWeight: 500, textAlign: 'center' }}>Success Rate</TableCell>
                                      </TableRow>
                                    </TableHead>
                                    <TableBody>
                                      {node.scripts.map((script) => (
                                        <TableRow
                                          key={script.script_result_id}
                                          sx={{
                                            '&:hover': {
                                              backgroundColor: 'transparent !important',
                                            },
                                          }}
                                        >
                                          <TableCell sx={{ py: 0.5 }}>{script.script_name}</TableCell>
                                          <TableCell sx={{ py: 0.5, textAlign: 'center' }}>{script.execution_count}</TableCell>
                                          <TableCell sx={{ py: 0.5, textAlign: 'center' }}>
                                            <Chip
                                              label={`${script.success_rate.toFixed(1)}%`}
                                              color={getSuccessRateColor(script.success_rate)}
                                              size="small"
                                              variant="outlined"
                                            />
                                          </TableCell>
                                        </TableRow>
                                      ))}
                                    </TableBody>
                                  </Table>
                                </Box>
                              </Collapse>
                            </TableCell>
                          </TableRow>
                        </React.Fragment>
                      ))
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            </Box>
          )}

          {/* Tab 4: Edge → Scripts */}
          {activeTab === 3 && (
            <Box sx={{ mt: 2 }}>
              <Box
                sx={{
                  mb: 2,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <Typography variant="h6">
                  Edge → Script Dependencies ({filteredEdgeScriptDependencies.length})
                </Typography>
                <SearchField
                  value={edgeScriptFilter}
                  onChange={setEdgeScriptFilter}
                  placeholder="Search edges..."
                />
              </Box>

              <TableContainer component={Paper} variant="outlined">
                <Table
                  size="small"
                  sx={{
                    '& .MuiTableRow-root:hover': { backgroundColor: 'transparent !important' },
                  }}
                >
                  <TableHead>
                    <TableRow>
                      <TableCell width="50"></TableCell>
                      <TableCell>
                        <strong>Edge</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Interface</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Overall Success Rate</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Used by Scripts</strong>
                      </TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {loading ? (
                      <TableRow>
                        <TableCell colSpan={5}>
                          <LoadingState />
                        </TableCell>
                      </TableRow>
                    ) : filteredEdgeScriptDependencies.length === 0 ? (
                      <EmptyState message="No edge-script dependencies found" />
                    ) : (
                      filteredEdgeScriptDependencies.map((edge) => (
                        <React.Fragment key={edge.edge_id}>
                          <TableRow
                            sx={{
                              '&:hover': {
                                backgroundColor: 'transparent !important',
                              },
                            }}
                          >
                            <TableCell>
                              <IconButton
                                size="small"
                                onClick={() => toggleRowExpansion(`edge-script-${edge.edge_id}`)}
                              >
                                {expandedRows.has(`edge-script-${edge.edge_id}`) ? (
                                  <ExpandLess />
                                ) : (
                                  <ExpandMore />
                                )}
                              </IconButton>
                            </TableCell>
                            <TableCell>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <ActionIcon fontSize="small" color="primary" />
                                <Typography variant="body2" fontWeight="medium">
                                  {edge.edge_name}
                                </Typography>
                              </Box>
                            </TableCell>
                            <TableCell>{edge.tree_name}</TableCell>
                            <TableCell>
                              <Chip
                                label={`${edge.overall_success_rate.toFixed(1)}%`}
                                color={getSuccessRateColor(edge.overall_success_rate)}
                                size="small"
                                variant="outlined"
                              />
                            </TableCell>
                            <TableCell>
                              <Typography variant="body2" color="textSecondary">
                                {edge.scripts.length} unique scripts
                              </Typography>
                            </TableCell>
                          </TableRow>
                          <TableRow>
                            <TableCell colSpan={5} sx={{ p: 0, border: 0 }}>
                              <Collapse in={expandedRows.has(`edge-script-${edge.edge_id}`)}>
                                <Box sx={{ pl: 7, pr: 2, py: 1, backgroundColor: 'rgba(0, 0, 0, 0.02)' }}>
                                  <Table
                                    size="small"
                                    sx={{
                                      '& .MuiTableRow-root:hover': {
                                        backgroundColor: 'transparent !important',
                                      },
                                      tableLayout: 'fixed',
                                    }}
                                  >
                                    <TableHead>
                                      <TableRow sx={{ backgroundColor: 'rgba(255, 255, 255, 0.05)' }}>
                                        <TableCell width="40%" sx={{ py: 0.5, color: 'rgba(255, 255, 255, 0.7)', fontSize: '0.75rem', fontWeight: 500 }}>Script</TableCell>
                                        <TableCell width="30%" sx={{ py: 0.5, color: 'rgba(255, 255, 255, 0.7)', fontSize: '0.75rem', fontWeight: 500, textAlign: 'center' }}>Executions</TableCell>
                                        <TableCell width="30%" sx={{ py: 0.5, color: 'rgba(255, 255, 255, 0.7)', fontSize: '0.75rem', fontWeight: 500, textAlign: 'center' }}>Success Rate</TableCell>
                                      </TableRow>
                                    </TableHead>
                                    <TableBody>
                                      {edge.scripts.map((script) => (
                                        <TableRow
                                          key={script.script_result_id}
                                          sx={{
                                            '&:hover': {
                                              backgroundColor: 'transparent !important',
                                            },
                                          }}
                                        >
                                          <TableCell sx={{ py: 0.5 }}>{script.script_name}</TableCell>
                                          <TableCell sx={{ py: 0.5, textAlign: 'center' }}>{script.execution_count}</TableCell>
                                          <TableCell sx={{ py: 0.5, textAlign: 'center' }}>
                                            <Chip
                                              label={`${script.success_rate.toFixed(1)}%`}
                                              color={getSuccessRateColor(script.success_rate)}
                                              size="small"
                                              variant="outlined"
                                            />
                                          </TableCell>
                                        </TableRow>
                                      ))}
                                    </TableBody>
                                  </Table>
                                </Box>
                              </Collapse>
                            </TableCell>
                          </TableRow>
                        </React.Fragment>
                      ))
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            </Box>
          )}
        </CardContent>
      </Card>
      )}
    </Box>
  );
};

export default DependencyReport;
