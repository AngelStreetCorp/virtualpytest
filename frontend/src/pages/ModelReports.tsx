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
  Alert,
  ToggleButton,
  ToggleButtonGroup,
  FormControl,
  Select,
  MenuItem,
  SelectChangeEvent,
  IconButton,
  Link,
  TableSortLabel,
} from '@mui/material';
import { ExpandMore, ExpandLess, OpenInNew } from '@mui/icons-material';
import React, { useState, useEffect, useMemo } from 'react';

import { useExecutionResults, ExecutionResult } from '../hooks/pages/useExecutionResults';
import { useUserInterface } from '../hooks/pages/useUserInterface';
import { useMetrics } from '../hooks/navigation/useMetrics';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { PageTitle, StatTiles, pageSurfaceSx, rateColor, segmentedSx } from '../components/common/PageChrome';
import { TableRowsSkeleton, ValueSkeleton } from '../components/common/ReportSkeleton';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { TYPOGRAPHY } from '../constants/typography';

type FilterType = 'all' | 'action' | 'verification';

type SortKey = 'type' | 'name' | 'success' | 'volume' | 'duration' | 'confidence' | 'executed';

const ModelReports: React.FC = () => {
  const P = useAgentChatPalette();
  const { getAllExecutionResults } = useExecutionResults();
  const { getAllUserInterfaces } = useUserInterface();
  const metricsHook = useMetrics();
  const [executionResults, setExecutionResults] = useState<ExecutionResult[]>([]);
  const [userInterfaces, setUserInterfaces] = useState<any[]>([]);
  const [selectedUserInterface, setSelectedUserInterface] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [treeToInterfaceMap, setTreeToInterfaceMap] = useState<Record<string, string>>({});
  const [selectedVariant, setSelectedVariant] = useState<string>(''); // '' = base runs
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' } | null>(null);
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
                await metricsHook.fetchMetrics(selectedUI.root_tree.id, selectedVariant);
              }
            }
          } catch (hierarchyErr) {
            console.warn('[@ModelReports] Failed to fetch tree hierarchy, using root tree only:', hierarchyErr);
            // Still try to fetch metrics even if hierarchy fetch fails
            await metricsHook.fetchMetrics(selectedUI.root_tree.id, selectedVariant);
          }
          
          // Load execution results and filter using the extended tree map
          const results = await getAllExecutionResults(
            Object.keys(extendedTreeMap).filter(id => extendedTreeMap[id] === selectedUserInterface),
          );
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
  }, [selectedUserInterface, selectedVariant, userInterfaces, treeToInterfaceMap]);

  // Variants this interface has runs for; base runs have no variant.
  const variants = useMemo(
    () => Array.from(new Set(executionResults.map(r => (r.variant || '').toLowerCase()).filter(Boolean))).sort(),
    [executionResults],
  );
  const variantResults = useMemo(
    () => executionResults.filter(r => (r.variant || '').toLowerCase() === selectedVariant),
    [executionResults, selectedVariant],
  );

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
    
    variantResults.forEach(result => {
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
  }, [variantResults]);

  // Filter transformed results based on execution type and additional filters
  const passesFilters = (result: any, applyTypeFilter: boolean) => {
    // Filter by execution type
    if (applyTypeFilter && filter !== 'all' && result.execution_type !== filter) return false;
    
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
      // Executed at least once and not always successful; never-executed items are the Vol=0 filter.
      if ((metrics?.volume || 0) === 0 || (metrics?.success_rate || 0) >= 1.0) return false;
    }
    
    // Filter by unexecuted (volume = 0)
    if (showUnexecutedOnly) {
      const volume = metrics?.volume || 0;
      if (volume > 0) return false; // Hide items with volume > 0
    }
    
    return true;
  };
  const filteredResults = transformedResults.filter((r: any) => passesFilters(r, true));

  const metricsFor = (r: any) =>
    r.execution_type === 'action' && r.action_set_id
      ? metricsHook.getEdgeDirectionMetrics(r.element_id, r.action_set_id)
      : r.execution_type === 'action'
        ? metricsHook.getEdgeMetrics(r.element_id)
        : metricsHook.getNodeMetrics(r.element_id);

  // Rows that were never executed sort below executed ones in either direction.
  const sortValue = (r: any, key: SortKey): number | string => {
    const m: any = metricsFor(r);
    const ran = (m?.volume || 0) > 0;
    switch (key) {
      case 'type': return r.execution_type;
      case 'name': return (r.element_name || '').toLowerCase();
      case 'volume': return m?.volume || 0;
      case 'success': return ran ? m.success_rate || 0 : -1;
      case 'confidence': return ran ? m.confidence || 0 : -1;
      case 'duration': return (m && ('avg_action_time' in m ? m.avg_action_time : m.avg_verification_time)) || -1;
      case 'executed': return new Date(r.executed_at).getTime();
    }
  };
  const sortedResults = sort
    ? [...filteredResults].sort((a: any, b: any) => {
        const x = sortValue(a, sort.key);
        const y = sortValue(b, sort.key);
        const c = typeof x === 'string' ? x.localeCompare(y as string) : (x as number) - (y as number);
        return sort.dir === 'asc' ? c : -c;
      })
    : filteredResults;
  const sortCell = (key: SortKey, label: string) => (
    <TableSortLabel
      active={sort?.key === key}
      direction={sort?.key === key ? sort.dir : 'asc'}
      onClick={() =>
        setSort(sort?.key === key ? (sort.dir === 'asc' ? { key, dir: 'desc' } : null) : { key, dir: 'asc' })
      }
    >
      <strong>{label}</strong>
    </TableSortLabel>
  );

  // Calculate stats based on filtered results and their metrics
  // Calculate aggregated stats from metrics
  const { totalVolume, totalSuccessful, totalExecutionTime } = useMemo(() => {
    let volume = 0;
    let successful = 0;
    let executionTime = 0;
    
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
    });
    
    return {
      totalVolume: volume,
      totalSuccessful: successful,
      totalExecutionTime: executionTime
    };
  }, [filteredResults, metricsHook]);

  // `null` means "nothing to compute from" — true before the first load lands and on an empty
  // result set alike. That is neither a rate of zero nor a failure, so it must not fall through
  // the rate thresholds into the error colour (UI_STYLE §10 S6): `Number('N/A')` is `NaN`, and
  // every comparison against `NaN` is false, so `rateColor` returned `P.error`.
  const successRate: number | null =
    totalVolume > 0 ? (totalSuccessful / totalVolume) * 100 : null;
  const avgDuration: string | null =
    totalVolume > 0 ? formatDuration(totalExecutionTime / totalVolume) : null;

  // Every number in the tile row is unknown while the first load is in flight, so each value
  // slot takes a grey bar and the labels stay readable — the page does not greet the user with
  // a row of 0s.
  const tileValue = (node: React.ReactNode, width = 44) =>
    loading ? <ValueSkeleton width={width} height={22} /> : node;

  // Separate by execution type (for current interface stats)
    // The Edges / Nodes tiles ignore the type switch so both stay visible; the other filters still apply.
  const countable = transformedResults.filter((r: any) => passesFilters(r, false));
  const uniqueEdges = countable.filter((r: any) => r.execution_type === 'action').length;
  const uniqueNodes = countable.filter((r: any) => r.execution_type !== 'action').length;

  // Handle filter change
  const handleFilterChange = (_event: React.MouseEvent<HTMLElement>, newFilter: FilterType) => {
    if (newFilter !== null) {
      setFilter(newFilter);
    }
  };

  // Handle user interface selection change
  const handleUserInterfaceChange = (event: SelectChangeEvent) => {
    setSelectedUserInterface(event.target.value);
    setSelectedVariant('');
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

  return (
    <Box sx={pageSurfaceSx(P)}>
      <Box sx={{ mb: 1 }}>
        <PageTitle title="Model Analysis Reports" subtitle="How reliably each node and edge of an interface's navigation model executes" />

        {/* User Interface Selector */}
        <FormControl size="small" sx={{ minWidth: 250 }}>
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
        {selectedUserInterface && (
          <FormControl size="small" sx={{ minWidth: 160, ml: 1 }}>
            <Select
              value={selectedVariant}
              onChange={(e: SelectChangeEvent) => setSelectedVariant(e.target.value)}
              displayEmpty
              renderValue={(v) => (v ? `Variant: ${v}` : 'Base (no variant)')}
              aria-label="variant"
            >
              <MenuItem value="">Base (no variant)</MenuItem>
              {variants.map(v => (
                <MenuItem key={v} value={v}>
                  {v}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        )}
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
            <ModelIcon sx={{ fontSize: TYPOGRAPHY.displayKpi.size, color: P.accentText, mb: 1 }} />
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
          <StatTiles
            tiles={[
              { label: 'Executions', value: tileValue(totalVolume, 34) },
              {
                label: 'Success rate',
                value: tileValue(successRate === null ? '—' : `${successRate.toFixed(1)}%`, 56),
                color: successRate === null ? P.textMuted : rateColor(successRate, P),
              },
              { label: 'Avg duration', value: tileValue(avgDuration ?? '—', 48) },
              { label: 'Edges', value: tileValue(uniqueEdges, 34) },
              { label: 'Nodes', value: tileValue(uniqueNodes, 34) },
            ]}
          />

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
                title="Only elements executed with a success rate below 100%"
                sx={{ minWidth: 'auto', px: 1, textTransform: 'none', borderRadius: 2, '&.Mui-selected': { color: P.accentText, bgcolor: `${P.accent}26`, borderColor: P.accent } }}
              >
                <Typography variant="caption" sx={{ fontSize: TYPOGRAPHY.caption.size }}>
                  &lt;100%
                </Typography>
              </ToggleButton>
              
              <ToggleButton
                value="unexecuted"
                selected={showUnexecutedOnly}
                onChange={() => setShowUnexecutedOnly(!showUnexecutedOnly)}
                size="small"
                title="Only elements never executed"
                sx={{ minWidth: 'auto', px: 1, textTransform: 'none', borderRadius: 2, '&.Mui-selected': { color: P.accentText, bgcolor: `${P.accent}26`, borderColor: P.accent } }}
              >
                <Typography variant="caption" sx={{ fontSize: TYPOGRAPHY.caption.size }}>
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
                sx={segmentedSx(P, 'sm')}
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
            <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 1000, '& .MuiTableCell-root': { overflowWrap: 'anywhere' }, '& .MuiTableHead-root .MuiTableCell-root': { whiteSpace: 'nowrap', overflowWrap: 'normal' }, '& .MuiTableRow-root': { height: '36px' } }}>
<colgroup><col style={{ width: 40 }} /><col style={{ width: 100 }} /><col /><col style={{ width: 115 }} /><col style={{ width: 85 }} /><col style={{ width: 120 }} /><col style={{ width: 140 }} /><col style={{ width: 150 }} /><col style={{ width: 80 }} /></colgroup>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ py: 1, px: 0.5, width: 40 }}>
                    {/* Expand column */}
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    {sortCell('type', 'Type')}
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    {sortCell('name', 'Name')}
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    {sortCell('success', 'Success')}
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    {sortCell('volume', 'Count')}
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    {sortCell('duration', 'Duration')}
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    {sortCell('confidence', 'Confidence')}
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    {sortCell('executed', 'Executed')}
                  </TableCell>
                  <TableCell sx={{ py: 1 }}>
                    <strong>Report</strong>
                  </TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {loading ? (
                  /* Same shape as the live table: 10 columns, the expand control first and the
                     Report action last, both icon-sized. */
                  <TableRowsSkeleton
                    rows={8}
                    widths={[null, '56%', '64%', '72%', '64%', '68%', '70%', '74%', null]}
                    rowHeight={46}
                  />
                ) : filteredResults.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={9} sx={{ textAlign: 'center', py: 4 }}>
                      <Typography variant="body2" color="textSecondary">
                        {filter === 'all'
                          ? 'No execution results available yet'
                          : `No ${filter === 'action' ? 'edge' : 'node'} execution results available yet`}
                      </Typography>
                    </TableCell>
                  </TableRow>
                ) : (
                  sortedResults.map((result: any) => {
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
                              backgroundColor: `${P.hoverBg} !important`,
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
                              label={result.execution_type === 'action' ? 'Edge' : 'Node'}
                              size="small"
                              variant="outlined"
                              sx={{ height: 22, fontSize: TYPOGRAPHY.caption.size, borderColor: P.borderColor, color: P.textSecondary }}
                            />
                          </TableCell>
                        <TableCell sx={{ py: 0.5 }}>{result.element_name}</TableCell>
                        <TableCell sx={{ py: 0.5 }}>
                          <Typography variant="body2" sx={{ 
                            color: (metrics?.volume || 0) === 0 ? 'text.secondary' : 
                                   rateColor((metrics?.success_rate || 0) * 100, P)
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
                                fontSize: TYPOGRAPHY.navbarItem.size,
                                color: (metrics?.volume || 0) === 0 ? 'text.secondary' : 
                                       (metrics?.confidence || 0) >= 0.7 ? P.success : (metrics?.confidence || 0) >= 0.5 ? P.warning : P.error
                              }}
                            >
                              {(metrics?.volume || 0) === 0 ? 'N/A' : `${metrics?.confidence ? Math.round(metrics.confidence * 10) : 0}/10`}
                            </Typography>
                          </Box>
                        </TableCell>
                        <TableCell sx={{ py: 0.5 }}>
                          <Typography variant="body2" sx={{ fontSize: TYPOGRAPHY.caption.size, whiteSpace: 'nowrap' }}>
                            {formatDate(result.executed_at)}
                          </Typography>
                        </TableCell>
                        <TableCell sx={{ py: 0.5 }}>
                          {reportUrl ? (
                            <Link
                              href={reportUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              aria-label="Report"
                              title="Report"
                              sx={{ display: 'inline-flex', alignItems: 'center', color: P.accentText }}
                            >
                              <OpenInNew sx={{ fontSize: TYPOGRAPHY.body.size }} />
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
                          <TableCell sx={{ py: 0, border: 0 }} colSpan={9}>
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

