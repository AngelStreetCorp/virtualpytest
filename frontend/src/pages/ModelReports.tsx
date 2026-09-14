import {
  Memory as ModelIcon,
  PlayArrow as ActionIcon,
  Visibility as VerificationIcon,
  FilterList as FilterIcon,
} from '@mui/icons-material';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Chip,
  CircularProgress,
  Alert,
  ToggleButton,
  ToggleButtonGroup,
  FormControl,
  Select,
  MenuItem,
  SelectChangeEvent,
  IconButton,
  Link,
} from '@mui/material';
import { ExpandMore, ExpandLess, OpenInNew } from '@mui/icons-material';
import React, { useState, useEffect, useMemo } from 'react';

import { useExecutionResults, ExecutionResult } from '../hooks/pages/useExecutionResults';
import { useUserInterface } from '../hooks/pages/useUserInterface';
import { useMetrics } from '../hooks/navigation/useMetrics';
import { buildServerUrl } from '../utils/buildUrlUtils';

type FilterType = 'all' | 'action' | 'verification';

const ModelReports: React.FC = () => {
  const { getAllExecutionResults } = useExecutionResults();
  const { getAllUserInterfaces } = useUserInterface();
  const metricsHook = useMetrics();
  const [executionResults, setExecutionResults] = useState<ExecutionResult[]>([]);
  const [userInterfaces, setUserInterfaces] = useState<any[]>([]);
  const [selectedUserInterface, setSelectedUserInterface] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [treeToInterfaceMap, setTreeToInterfaceMap] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState<FilterType>('all');
  const [showFailuresOnly, setShowFailuresOnly] = useState(false);
  const [showUnexecutedOnly, setShowUnexecutedOnly] = useState(false);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

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

  // Load execution results and user interfaces on component mount
  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true);
        setError(null);

        // Load user interfaces first
        const interfaces = await getAllUserInterfaces();

        // Create mapping from tree_id to userinterface_name
        const treeToUIMap: Record<string, string> = {};
        
        interfaces.forEach((ui) => {
          if (ui.root_tree?.id) {
            treeToUIMap[ui.root_tree.id] = ui.name;
            // treeNameMap[ui.root_tree.id] = ui.root_tree.name || 'Root Tree';
          }
          // Also map any nested trees if they exist (cast to any to handle potential nested_trees)
          const uiWithNested = ui as any;
          if (uiWithNested.nested_trees && Array.isArray(uiWithNested.nested_trees)) {
            uiWithNested.nested_trees.forEach((nestedTree: any) => {
              if (nestedTree.id) {
                treeToUIMap[nestedTree.id] = ui.name;
                // treeNameMap[nestedTree.id] = nestedTree.name || 'Nested Tree';
              }
            });
          }
        });

        setUserInterfaces(interfaces);
        setTreeToInterfaceMap(treeToUIMap);
        
        // Don't auto-select - let user choose explicitly to avoid race conditions
      } catch (err) {
        console.error('[@component:ModelReports] Error loading data:', err);
        setError(err instanceof Error ? err.message : 'Failed to load data');
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, []); // Only run once on mount

  // Load execution results and metrics when user interface changes
  useEffect(() => {
    const loadExecutionResultsForInterface = async () => {
      if (!selectedUserInterface || userInterfaces.length === 0 || Object.keys(treeToInterfaceMap).length === 0) {
        return;
      }
      
      try {
        setLoading(true);
        setError(null);
        
        const selectedUI = userInterfaces.find(ui => ui.name === selectedUserInterface);
        if (selectedUI?.root_tree?.id) {
          console.log(`[@ModelReports] Loading data for interface: ${selectedUserInterface}, tree: ${selectedUI.root_tree.id}`);
          
          // Build an extended tree map that includes all nested trees
          const extendedTreeMap: Record<string, string> = { ...treeToInterfaceMap };
          
          // Fetch metrics and hierarchy info in a single call
          try {
            const response = await fetch(
              buildServerUrl(`/server/metrics/tree/${selectedUI.root_tree.id}`)
            );
            if (response.ok) {
              const metricsData = await response.json();
              if (metricsData.success && metricsData.hierarchy_info?.trees) {
                // Map all tree IDs in the hierarchy to this interface
                metricsData.hierarchy_info.trees.forEach((tree: any) => {
                  if (tree.tree_id) {
                    extendedTreeMap[tree.tree_id] = selectedUserInterface;
                    console.log(`[@ModelReports] Mapped tree ${tree.tree_id} (${tree.name}) to interface ${selectedUserInterface}`);
                  }
                });
                
                // Also fetch metrics for the tree (this will update the metricsHook state)
                await metricsHook.fetchMetrics(selectedUI.root_tree.id);
              }
            }
          } catch (hierarchyErr) {
            console.warn('[@ModelReports] Failed to fetch tree hierarchy, using root tree only:', hierarchyErr);
            // Still try to fetch metrics even if hierarchy fetch fails
            await metricsHook.fetchMetrics(selectedUI.root_tree.id);
          }
          
          // Load execution results and filter using the extended tree map
          const results = await getAllExecutionResults();
          const filteredResults = results.filter(result => 
            extendedTreeMap[result.tree_id] === selectedUserInterface
          );
          
          console.log(`[@ModelReports] Filtered ${results.length} results to ${filteredResults.length} for interface ${selectedUserInterface}`);
          console.log(`[@ModelReports] Extended tree map has ${Object.keys(extendedTreeMap).length} tree IDs mapped`);
          setExecutionResults(filteredResults);
        }
      } catch (err) {
        console.error('[@component:ModelReports] Error loading execution results:', err);
        setError(err instanceof Error ? err.message : 'Failed to load execution results');
      } finally {
        setLoading(false);
      }
    };

    // Only run if we have all the necessary data
    if (selectedUserInterface && userInterfaces.length > 0 && Object.keys(treeToInterfaceMap).length > 0) {
      loadExecutionResultsForInterface();
    }
  }, [selectedUserInterface, userInterfaces, treeToInterfaceMap]);

  // Transform execution results into direction-specific entries for display
  const transformedResults = useMemo(() => {
    const entries: Array<{
      id: string;
      execution_type: 'action' | 'verification';
      tree_id: string;
      element_id: string;
      element_name: string;
      action_set_id?: string;
      direction_label?: string;
      executed_at: string;
    }> = [];

    // Group execution results by element and direction
    const elementGroups = new Map<string, any[]>();
    
    executionResults.forEach(result => {
      let groupKey: string;
      
      if (result.execution_type === 'action' && result.action_set_id) {
        // For actions: group by edge_id + action_set_id (direction-specific)
        groupKey = `${result.edge_id}#${result.action_set_id}`;
      } else if (result.execution_type === 'action') {
        // For legacy actions without action_set_id: group by edge_id only
        groupKey = result.edge_id || 'unknown';
      } else {
        // For verifications: group by node_id
        groupKey = result.node_id || 'unknown';
      }
      
      if (!elementGroups.has(groupKey)) {
        elementGroups.set(groupKey, []);
      }
      elementGroups.get(groupKey)!.push(result);
    });

    // Create display entries from groups
    elementGroups.forEach((results, groupKey) => {
      const firstResult = results[0];
      const isAction = firstResult.execution_type === 'action';
      
      let elementName = 'Unknown';
      let directionLabel = '';
      
      // Always use the backend-provided element_name which is already correctly formatted
      elementName = firstResult.element_name || (isAction ? 'Unknown Edge' : 'Unknown Node');
      
      // For bidirectional edges, the direction is already included in element_name
      if (isAction && firstResult.action_set_id) {
        directionLabel = elementName;
      }

      entries.push({
        id: groupKey,
        execution_type: firstResult.execution_type,
        tree_id: firstResult.tree_id,
        element_id: isAction ? firstResult.edge_id : firstResult.node_id,
        element_name: elementName,
        action_set_id: firstResult.action_set_id,
        direction_label: directionLabel,
        executed_at: results[results.length - 1].executed_at // Most recent execution
      });
    });

    return entries;
  }, [executionResults]);

  // Filter transformed results based on execution type and additional filters
  const filteredResults = transformedResults.filter((result: any) => {
    // Filter by execution type
    if (filter !== 'all' && result.execution_type !== filter) return false;
    
    // Get metrics for additional filtering
    let metrics = null;
    if (result.execution_type === 'action' && result.action_set_id) {
      metrics = metricsHook.getEdgeDirectionMetrics(result.element_id, result.action_set_id);
    } else if (result.execution_type === 'action') {
      metrics = metricsHook.getEdgeMetrics(result.element_id);
    } else {
      metrics = metricsHook.getNodeMetrics(result.element_id);
    }
    
    // Hide edges with volume = 0 (unexecuted edge directions)
    if (result.execution_type === 'action') {
      const volume = metrics?.volume || 0;
      if (volume === 0) return false; // Hide unexecuted edges
    }
    
    // Filter by failure rate (not 100% success)
    if (showFailuresOnly) {
      const successRate = metrics?.success_rate || 0;
      if (successRate >= 1.0) return false; // Hide 100% success rate items
    }
    
    // Filter by unexecuted (volume = 0)
    if (showUnexecutedOnly) {
      const volume = metrics?.volume || 0;
      if (volume > 0) return false; // Hide items with volume > 0
    }
    
    return true;
  }); // Note: Dependencies handled by React's automatic dependency detection

  // Calculate stats based on filtered results and their metrics
  const totalElements = filteredResults.length;
  
  // Calculate aggregated stats from metrics
  const { totalVolume, totalSuccessful, totalExecutionTime, thisWeekCount } = useMemo(() => {
    let volume = 0;
    let successful = 0;
    let executionTime = 0;
    let weekCount = 0;
    
    const oneWeekAgo = new Date();
    oneWeekAgo.setDate(oneWeekAgo.getDate() - 7);
    
    filteredResults.forEach((result: any) => {
      let metrics = null;
      
      if (result.execution_type === 'action' && result.action_set_id) {
        // Get direction-specific metrics
        metrics = metricsHook.getEdgeDirectionMetrics(result.element_id, result.action_set_id);
      } else if (result.execution_type === 'action') {
        // Get general edge metrics
        metrics = metricsHook.getEdgeMetrics(result.element_id);
      } else {
        // Get node metrics
        metrics = metricsHook.getNodeMetrics(result.element_id);
      }
      
      if (metrics) {
        volume += metrics.volume || 0;
        successful += Math.round((metrics.volume || 0) * (metrics.success_rate || 0));
        // Edge metric carries avg_action_time, node metric carries avg_verification_time;
        // for the report's "total execution time" rollup either is the right field for that row.
        const t = ('avg_action_time' in metrics ? metrics.avg_action_time : metrics.avg_verification_time) || 0;
        executionTime += t * (metrics.volume || 0);
      }
      
      // Count this week executions (approximate based on last execution date)
      if (new Date(result.executed_at) >= oneWeekAgo) {
        weekCount += metrics?.volume || 0;
      }
    });
    
    return {
      totalVolume: volume,
      totalSuccessful: successful,
      totalExecutionTime: executionTime,
      thisWeekCount: weekCount
    };
  }, [filteredResults, metricsHook]);

  const successRate = totalVolume > 0 ? ((totalSuccessful / totalVolume) * 100).toFixed(1) : 'N/A';
  const avgDuration = totalVolume > 0 ? formatDuration(totalExecutionTime / totalVolume) : 'N/A';

  // Separate by execution type (for current interface stats)
  const actionExecutions = executionResults.filter((result) => result.execution_type === 'action');
  const verificationExecutions = executionResults.filter(
    (result) => result.execution_type === 'verification',
  );

  // Handle filter change
  const handleFilterChange = (_event: React.MouseEvent<HTMLElement>, newFilter: FilterType) => {
    if (newFilter !== null) {
      setFilter(newFilter);
    }
  };

  // Handle user interface selection change
  const handleUserInterfaceChange = (event: SelectChangeEvent) => {
    setSelectedUserInterface(event.target.value);
  };

  // Format duration helper
  function formatDuration(ms: number): string {
    if (ms < 1000) return `${Math.round(ms)}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    const minutes = Math.floor(ms / 60000);
    const seconds = ((ms % 60000) / 1000).toFixed(1);
    return `${minutes}m ${seconds}s`;
  }

  // Format date helper - compact single line format
  function formatDate(dateString: string): string {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-GB', { 
      day: '2-digit', 
      month: '2-digit', 
      year: 'numeric' 
    }) + ', ' + date.toLocaleTimeString('en-GB', { 
      hour: '2-digit', 
      minute: '2-digit', 
      second: '2-digit',
      hour12: false 
    });
  }

  // Loading state component
  const LoadingState = () => (
    <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
      <CircularProgress />
    </Box>
  );


  return (
    <Box>
      <Box sx={{ mb: 1 }}>
        <Typography variant="h4" sx={{ mb: 1 }}>
          Model Analysis Reports
        </Typography>

        
        {/* User Interface Selector */}
        <FormControl size="small" sx={{ minWidth: 250, zIndex: 9999, position: 'relative' }}>
          <Select
            value={selectedUserInterface}
            onChange={handleUserInterfaceChange}
            disabled={userInterfaces.length === 0}
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
                Select a user interface to analyze...
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

      {/* Show content only when user interface is selected */}
      {!selectedUserInterface ? (
        <Card>
          <CardContent sx={{ py: 6, textAlign: 'center' }}>
            <ModelIcon sx={{ fontSize: 64, color: 'text.secondary', mb: 1 }} />
            <Typography variant="h6" color="text.secondary" gutterBottom>
              Select User Interface to Analyze
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Choose a user interface from the dropdown above to view model performance metrics, 
              confidence scores, and execution data for nodes and edges.
            </Typography>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Quick Stats */}
          <Box sx={{ mb: 1 }}>
            <Card>
              <CardContent sx={{ py: 0.5 }}>
                <Box display="flex" alignItems="center" justifyContent="space-between">
                  <Box display="flex" alignItems="center" gap={1}>
                    <ModelIcon color="primary" />
                    <Typography variant="h6" sx={{ my: 0 }}>Execution Stats</Typography>
                  </Box>

              <Box display="flex" alignItems="center" gap={2}>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">
                    {filter === 'all' ? 'Total Elements' : 'Filtered Elements'}
                  </Typography>
                  <Typography variant="body2" fontWeight="bold">
                    {totalElements}
                  </Typography>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">Total Executions</Typography>
                  <Typography variant="body2" fontWeight="bold">
                    {totalVolume}
                  </Typography>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">This Week</Typography>
                  <Typography variant="body2" fontWeight="bold">
                    {thisWeekCount}
                  </Typography>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">Success Rate</Typography>
                  <Typography variant="body2" fontWeight="bold">
                    {successRate}%
                  </Typography>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">Duration</Typography>
                  <Typography variant="body2" fontWeight="bold">
                    {avgDuration}
                  </Typography>
                </Box>
                {filter === 'all' && (
                  <>
                    <Box display="flex" alignItems="center" gap={1}>
                      <Typography variant="body2">Edges</Typography>
                      <Typography variant="body2" fontWeight="bold">
                        {actionExecutions.length}
                      </Typography>
                    </Box>
                    <Box display="flex" alignItems="center" gap={1}>
                      <Typography variant="body2">Nodes</Typography>
                      <Typography variant="body2" fontWeight="bold">
                        {verificationExecutions.length}
                      </Typography>
                    </Box>
                  </>
                )}
              </Box>
            </Box>
          </CardContent>
        </Card>
      </Box>

      {/* Recent Execution Results */}
      <Card>
        <CardContent>
          <Box display="flex" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
            <Typography variant="h6" sx={{ my: 0 }}>Recent Execution Results</Typography>

            {/* Filter Toggle Buttons */}
            <Box display="flex" alignItems="center" gap={1}>
              <FilterIcon fontSize="small" color="action" />
              
              {/* Failure and Unexecuted Filters */}
              <ToggleButton
                value="failures"
                selected={showFailuresOnly}
                onChange={() => setShowFailuresOnly(!showFailuresOnly)}
                size="small"
                sx={{ minWidth: 'auto', px: 1 }}
              >
                <Typography variant="caption" sx={{ fontSize: '0.7rem' }}>
                  ≠100%
                </Typography>
              </ToggleButton>
              
              <ToggleButton
                value="unexecuted"
                selected={showUnexecutedOnly}
                onChange={() => setShowUnexecutedOnly(!showUnexecutedOnly)}
                size="small"
                sx={{ minWidth: 'auto', px: 1 }}
              >
                <Typography variant="caption" sx={{ fontSize: '0.7rem' }}>
                  Vol=0
                </Typography>
              </ToggleButton>
              
              {/* Divider */}
              <Box sx={{ width: 1, height: 24, backgroundColor: 'divider', mx: 0.5 }} />
              
              <ToggleButtonGroup
                value={filter}
                exclusive
                onChange={handleFilterChange}
                size="small"
                aria-label="execution type filter"
              >
                <ToggleButton value="all" aria-label="all executions">
                  All
                </ToggleButton>
                <ToggleButton value="action" aria-label="edge executions">
                  <ActionIcon fontSize="small" sx={{ mr: 0.5 }} />
                  Edges
                </ToggleButton>
                <ToggleButton value="verification" aria-label="node executions">
                  <VerificationIcon fontSize="small" sx={{ mr: 0.5 }} />
                  Nodes
                </ToggleButton>
              </ToggleButtonGroup>
            </Box>
          </Box>

          <TableContainer component={Paper} variant="outlined">
            <Table size="small" sx={{ '& .MuiTableRow-root': { height: '36px' } }}>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ py: 1, px: 0.5, width: 40 }}>
                    {/* Expand column */}
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    <strong>Type</strong>
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    <strong>Interface</strong>
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    <strong>Name</strong>
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    <strong>Success</strong>
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    <strong>Volume</strong>
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    <strong>Duration</strong>
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    <strong>Confidence</strong>
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    <strong>Executed</strong>
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    <strong>Report</strong>
                  </TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {loading ? (
                  <TableRow>
                    <TableCell colSpan={10}>
                      <LoadingState />
                    </TableCell>
                  </TableRow>
                ) : filteredResults.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={10} sx={{ textAlign: 'center', py: 4 }}>
                      <Typography variant="body2" color="textSecondary">
                        {filter === 'all'
                          ? 'No execution results available yet'
                          : `No ${filter === 'action' ? 'edge' : 'node'} execution results available yet`}
                      </Typography>
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredResults.map((result: any) => {
                    // Get metrics for this element using direction-specific lookup
                    const isAction = result.execution_type === 'action';
                    let metrics = null;
                    
                    if (isAction && result.action_set_id) {
                      // Get direction-specific metrics
                      metrics = metricsHook.getEdgeDirectionMetrics(result.element_id, result.action_set_id);
                    } else if (isAction) {
                      // Get general edge metrics (legacy)
                      metrics = metricsHook.getEdgeMetrics(result.element_id);
                    } else {
                      // Get node metrics
                      metrics = metricsHook.getNodeMetrics(result.element_id);
                    }
                    
                    const isExpanded = expandedRows.has(result.id);
                    const reportUrl = executionResults.find(er => 
                      (er.edge_id === result.element_id || er.node_id === result.element_id) &&
                      er.script_report_url
                    )?.script_report_url;

                    return (
                      <React.Fragment key={result.id}>
                        <TableRow
                          sx={{
                            '&:hover': {
                              backgroundColor: 'rgba(0, 0, 0, 0.04) !important',
                            },
                          }}
                        >
                          <TableCell sx={{ py: 0.5, px: 0.5, width: 40 }}>
                            <IconButton
                              size="small"
                              onClick={() => toggleRowExpansion(result.id)}
                              sx={{ p: 0.5 }}
                            >
                              {isExpanded ? <ExpandLess /> : <ExpandMore />}
                            </IconButton>
                          </TableCell>
                          <TableCell sx={{ py: 0.5 }}>
                            <Chip
                              icon={
                                result.execution_type === 'action' ? (
                                  <ActionIcon />
                                ) : (
                                  <VerificationIcon />
                                )
                              }
                              label={result.execution_type === 'action' ? 'Edge' : 'Node'}
                              size="small"
                              variant="outlined"
                              color={result.execution_type === 'action' ? 'primary' : 'secondary'}
                            />
                          </TableCell>
                        <TableCell sx={{ py: 0.5 }}>
                          {treeToInterfaceMap[result.tree_id] || 'Unknown'}
                        </TableCell>
                        <TableCell sx={{ py: 0.5 }}>{result.element_name}</TableCell>
                        <TableCell sx={{ py: 0.5 }}>
                          <Typography variant="body2" sx={{ 
                            color: (metrics?.volume || 0) === 0 ? 'text.secondary' : 
                                   (metrics?.success_rate || 0) >= 0.8 ? 'success.main' : 
                                   (metrics?.success_rate || 0) >= 0.5 ? 'warning.main' : 'error.main'
                          }}>
                            {(metrics?.volume || 0) === 0 ? 'N/A' : `${((metrics?.success_rate || 0) * 100).toFixed(0)}%`}
                          </Typography>
                        </TableCell>
                        <TableCell sx={{ py: 0.5 }}>
                          <Typography variant="body2">
                            {metrics?.volume || 0}
                          </Typography>
                        </TableCell>
                        <TableCell sx={{ py: 0.5 }}>
                          <Typography variant="body2">
                            {(() => {
                              if (!metrics) return 'N/A';
                              const t = 'avg_action_time' in metrics ? metrics.avg_action_time : metrics.avg_verification_time;
                              return t ? formatDuration(t) : 'N/A';
                            })()}
                          </Typography>
                        </TableCell>
                        <TableCell sx={{ py: 0.5 }}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <Typography 
                              variant="body2" 
                              sx={{ 
                                fontWeight: 'bold',
                                fontSize: '0.9rem',
                                color: (metrics?.volume || 0) === 0 ? 'text.secondary' : 
                                       (metrics?.confidence || 0) >= 0.7 ? 'success.main' : 
                                       (metrics?.confidence || 0) >= 0.5 ? 'warning.main' : 'error.main'
                              }}
                            >
                              {(metrics?.volume || 0) === 0 ? 'N/A' : `${metrics?.confidence ? Math.round(metrics.confidence * 10) : 0}/10`}
                            </Typography>
                          </Box>
                        </TableCell>
                        <TableCell sx={{ py: 0.5 }}>
                          <Typography variant="body2" sx={{ fontSize: '0.75rem', whiteSpace: 'nowrap' }}>
                            {formatDate(result.executed_at)}
                          </Typography>
                        </TableCell>
                        <TableCell sx={{ py: 0.5 }}>
                          {reportUrl ? (
                            <Link
                              href={reportUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}
                            >
                              Report
                              <OpenInNew sx={{ fontSize: 14 }} />
                            </Link>
                          ) : (
                            <Typography variant="body2" color="text.secondary">
                              N/A
                            </Typography>
                          )}
                        </TableCell>
                      </TableRow>
                      
                      {/* Expandable Details Row */}
                      {isExpanded && (
                        <TableRow sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
                          <TableCell sx={{ py: 0, border: 0 }} colSpan={10}>
                            <Box sx={{ py: 1, px: 2 }}>
                              <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                                {result.execution_type === 'action' 
                                  ? `Executing command 'press_key' with params: {key: '${result.action_set_id?.includes('home') ? 'HOME' : result.action_set_id?.includes('back') ? 'BACK' : 'OK'}', wait_time: 1500}`
                                  : `waitForElementToAppear Type: adb element: ${result.element_name?.toLowerCase().replace(' ', '_')}`
                                }
                              </Typography>
                            </Box>
                          </TableCell>
                        </TableRow>
                      )}
                    </React.Fragment>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>
      </>
      )}
    </Box>
  );
};

export default ModelReports;

