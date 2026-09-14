import {
  Add as AddIcon,
  Edit as EditIcon,
  Link as LinkIcon,
  Search as SearchIcon,
  Clear as ClearIcon,
  ExpandMore as ExpandIcon,
  BarChart as StatsIcon,
  Refresh as RefreshIcon,
  CheckCircle as CheckCircleIcon,
  Warning as WarningIcon,
  Error as ErrorCircleIcon,
} from '@mui/icons-material';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Button,
  Grid,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Chip,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Alert,
  CircularProgress,
  DialogTitle,
  DialogContent,
  DialogActions,
  Tooltip,
  InputAdornment,
} from '@mui/material';
import React, { useState } from 'react';
import { useRequirements, Requirement, RequirementCoverage } from '../hooks/pages/useRequirements';
import { RequirementCoverageModal } from '../components/requirements/RequirementCoverageModal';
import { LinkTestcasePickerModal } from '../components/requirements/LinkTestcasePickerModal';
import { StyledDialog } from '../components/common/StyledDialog';

const Requirements: React.FC = () => {
  const {
    requirements,
    isLoading,
    error,
    createRequirement,
    updateRequirement,
    filters,
    setFilters,
    categories,
    priorities,
    appTypes,
    deviceModels,
    refreshRequirements,
    getRequirementCoverage,
    getAvailableTestcases,
    linkMultipleTestcases,
    unlinkTestcase,
    coverageCounts,
  } = useRequirements();

  const [searchQuery, setSearchQuery] = useState('');
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [selectedRequirement, setSelectedRequirement] = useState<Requirement | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [formError, setFormError] = useState<string | null>(null);
  const [coverageCache, setCoverageCache] = useState<Record<string, RequirementCoverage>>({});
  const [loadingCoverage, setLoadingCoverage] = useState<Set<string>>(new Set());
  
  // Coverage modal state
  const [coverageModalOpen, setCoverageModalOpen] = useState(false);
  const [coverageRequirement, setCoverageRequirement] = useState<{ id: string; code: string; name: string } | null>(null);
  
  // Link testcase picker modal state
  const [linkPickerOpen, setLinkPickerOpen] = useState(false);
  const [linkRequirement, setLinkRequirement] = useState<{ id: string; code: string; name: string } | null>(null);

  // Create/Edit form state
  const [formData, setFormData] = useState({
    requirement_code: '',
    requirement_name: '',
    category: '',
    priority: 'P2',
    description: '',
    acceptance_criteria: [] as string[],
    app_type: 'all',
    device_model: 'all',
    status: 'active',
  });

  const handleCreateOpen = () => {
    setFormData({
      requirement_code: '',
      requirement_name: '',
      category: '',
      priority: 'P2',
      description: '',
      acceptance_criteria: [],
      app_type: 'all',
      device_model: 'all',
      status: 'active',
    });
    setCreateDialogOpen(true);
  };

  const handleEditOpen = (requirement: Requirement) => {
    setSelectedRequirement(requirement);
    setFormData({
      requirement_code: requirement.requirement_code,
      requirement_name: requirement.requirement_name,
      category: requirement.category || '',
      priority: requirement.priority,
      description: requirement.description || '',
      acceptance_criteria: requirement.acceptance_criteria || [],
      app_type: requirement.app_type,
      device_model: requirement.device_model,
      status: requirement.status,
    });
    setEditDialogOpen(true);
  };

  const handleCreate = async () => {
    setFormError(null);
    const result = await createRequirement(formData);
    if (result.success) {
      setCreateDialogOpen(false);
      refreshRequirements();
    } else {
      setFormError(result.error || 'Failed to create requirement');
    }
  };

  const handleEdit = async () => {
    if (!selectedRequirement) return;
    setFormError(null);
    const result = await updateRequirement(selectedRequirement.requirement_id, formData);
    if (result.success) {
      setEditDialogOpen(false);
      refreshRequirements();
    } else {
      setFormError(result.error || 'Failed to update requirement');
    }
  };

  // Filter requirements by search query
  const filteredRequirements = requirements.filter(req => {
    if (!searchQuery) return true;
    const query = searchQuery.toLowerCase();
    return (
      req.requirement_code.toLowerCase().includes(query) ||
      req.requirement_name.toLowerCase().includes(query) ||
      (req.description && req.description.toLowerCase().includes(query))
    );
  });

  // Calculate stats
  const totalReqs = requirements.length;
  const p1Count = requirements.filter(r => r.priority === 'P1').length;
  const p2Count = requirements.filter(r => r.priority === 'P2').length;
  const p3Count = requirements.filter(r => r.priority === 'P3').length;
  const activeCount = requirements.filter(r => r.status === 'active').length;
  const uncoveredCount = requirements.filter(r => !coverageCounts[r.requirement_id] || coverageCounts[r.requirement_id].total_count === 0).length;

  // Get priority color
  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'P1': return 'error';
      case 'P2': return 'warning';
      case 'P3': return 'info';
      default: return 'default';
    }
  };

  // Toggle row expansion and lazy-load coverage
  const toggleRowExpansion = (requirementId: string) => {
    setExpandedRows(prev => {
      const newSet = new Set(prev);
      if (newSet.has(requirementId)) {
        newSet.delete(requirementId);
      } else {
        newSet.add(requirementId);
        // Fetch coverage if not cached
        if (!coverageCache[requirementId] && !loadingCoverage.has(requirementId)) {
          setLoadingCoverage(s => new Set(s).add(requirementId));
          getRequirementCoverage(requirementId).then(cov => {
            if (cov) setCoverageCache(c => ({ ...c, [requirementId]: cov }));
            setLoadingCoverage(s => { const n = new Set(s); n.delete(requirementId); return n; });
          });
        }
      }
      return newSet;
    });
  };

  // Open coverage modal
  const handleOpenCoverage = (req: Requirement) => {
    setCoverageRequirement({
      id: req.requirement_id,
      code: req.requirement_code,
      name: req.requirement_name,
    });
    setCoverageModalOpen(true);
  };

  // Open link testcase picker from coverage modal
  const handleOpenLinkPickerFromCoverage = () => {
    if (coverageRequirement) {
      setLinkRequirement(coverageRequirement);
      setCoverageModalOpen(false);
      setLinkPickerOpen(true);
    }
  };

  // Open link testcase picker directly
  const handleOpenLinkPicker = (req: Requirement) => {
    setLinkRequirement({
      id: req.requirement_id,
      code: req.requirement_code,
      name: req.requirement_name,
    });
    setLinkPickerOpen(true);
  };

  // Get coverage badge for a requirement (computed once per row)
  const getCoverageBadge = (requirementId: string) => {
    const coverage = coverageCounts[requirementId];
    if (!coverage || coverage.total_count === 0) {
      return { icon: <ErrorCircleIcon />, color: 'error' as const, text: 'no coverage', borderColor: '#f44336' };
    }
    const { testcase_count, script_count } = coverage;
    let label: string;
    if (testcase_count > 0 && script_count > 0) {
      label = `${testcase_count} TC, ${script_count} scripts`;
    } else if (script_count > 0) {
      label = `${script_count} script${script_count !== 1 ? 's' : ''}`;
    } else {
      label = `${testcase_count} TC`;
    }
    const color = testcase_count >= 2 ? 'success' as const : 'warning' as const;
    const icon = testcase_count >= 2 ? <CheckCircleIcon /> : <WarningIcon />;
    const borderColor = testcase_count >= 2 ? '#4caf50' : '#ff9800';
    return { icon, color, text: label, borderColor };
  };

  return (
    <Box>
      {/* Quick Stats */}
      <Box sx={{ mb: 1 }}>
        <Card>
          <CardContent sx={{ py: 0.5 }}>
            <Box display="flex" alignItems="center" justifyContent="space-between">
              <Box display="flex" alignItems="center" gap={1}>
                <StatsIcon color="primary" />
                <Typography variant="h6" sx={{ my: 0 }}>Requirements</Typography>
              </Box>
              <Box display="flex" alignItems="center" gap={4}>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">Total</Typography>
                  <Typography variant="body2" fontWeight="bold">
                    {totalReqs}
                  </Typography>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">Active</Typography>
                  <Typography variant="body2" fontWeight="bold" color="success.main">
                    {activeCount}
                  </Typography>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Typography variant="body2">No coverage</Typography>
                  <Typography variant="body2" fontWeight="bold" color={uncoveredCount > 0 ? 'error.main' : 'text.primary'}>
                    {uncoveredCount}
                  </Typography>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Tooltip title="Critical priority">
                    <Chip label={`P1: ${p1Count}`} size="small" color="error" />
                  </Tooltip>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Tooltip title="High priority">
                    <Chip label={`P2: ${p2Count}`} size="small" color="warning" />
                  </Tooltip>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Tooltip title="Medium priority">
                    <Chip label={`P3: ${p3Count}`} size="small" color="info" />
                  </Tooltip>
                </Box>
              </Box>
            </Box>
          </CardContent>
        </Card>
      </Box>

      {/* Actions Bar & Filters */}
      <Box sx={{ display: 'flex', gap: 2, mb: 1, flexWrap: 'wrap', alignItems: 'center' }}>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={handleCreateOpen}
          size="small"
        >
          Create Requirement
        </Button>
        <TextField
          size="small"
          placeholder="Search requirements..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          sx={{ minWidth: 250 }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
            endAdornment: searchQuery && (
              <InputAdornment position="end">
                <IconButton size="small" onClick={() => setSearchQuery('')}>
                  <ClearIcon fontSize="small" />
                </IconButton>
              </InputAdornment>
            ),
          }}
        />
        <FormControl size="small" sx={{ minWidth: 150 }}>
          <InputLabel>Category</InputLabel>
          <Select
            value={filters.category || ''}
            onChange={(e) => setFilters({ ...filters, category: e.target.value || undefined })}
            label="Category"
          >
            <MenuItem value="">All</MenuItem>
            {categories.map(cat => (
              <MenuItem key={cat} value={cat}>{cat}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 120 }}>
          <InputLabel>Priority</InputLabel>
          <Select
            value={filters.priority || ''}
            onChange={(e) => setFilters({ ...filters, priority: e.target.value || undefined })}
            label="Priority"
          >
            <MenuItem value="">All</MenuItem>
            {priorities.map(pri => (
              <MenuItem key={pri} value={pri}>{pri}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 150 }}>
          <InputLabel>Model</InputLabel>
          <Select
            value={filters.device_model || ''}
            onChange={(e) => setFilters({ ...filters, device_model: e.target.value || undefined })}
            label="Model"
          >
            <MenuItem value="">All</MenuItem>
            {deviceModels.map(model => (
              <MenuItem key={model} value={model}>{model}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <Box sx={{ ml: 'auto' }}>
          <Tooltip title="Refresh">
            <IconButton size="small" onClick={() => refreshRequirements()}>
              <RefreshIcon />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>

      {/* Results count */}
      {searchQuery && (
        <Box sx={{ mb: 1 }}>
          <Typography variant="caption" color="textSecondary">
            Showing {filteredRequirements.length} of {totalReqs} requirement{totalReqs !== 1 ? 's' : ''}
          </Typography>
        </Box>
      )}

      {/* Error Display */}
      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      {/* Loading State */}
      {isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
          <CircularProgress />
        </Box>
      )}

      {/* Requirements Table */}
      {!isLoading && (
        <Card>
          <CardContent>
            <TableContainer>
              <Table size="small" sx={{ 
                '& .MuiTableRow-root': { height: '40px' },
                '& .MuiTableCell-root': { 
                  px: 1, 
                  py: 0.5,
                  fontSize: '0.875rem',
                  whiteSpace: 'nowrap',
                }
              }}>
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ py: 1, width: 40 }}></TableCell>
                    <TableCell sx={{ py: 1 }}>
                      <strong>Code</strong>
                    </TableCell>
                    <TableCell sx={{ py: 1 }}>
                      <strong>Name</strong>
                    </TableCell>
                    <TableCell sx={{ py: 1 }}>
                      <strong>Category</strong>
                    </TableCell>
                    <TableCell sx={{ py: 1 }}>
                      <Tooltip title="P1 = Critical, P2 = High, P3 = Medium">
                        <strong>Priority</strong>
                      </Tooltip>
                    </TableCell>
                    <TableCell sx={{ py: 1 }}>
                      <Tooltip title="Test coverage status">
                        <strong>Coverage</strong>
                      </Tooltip>
                    </TableCell>
                    <TableCell sx={{ py: 1 }}>
                      <strong>Status</strong>
                    </TableCell>
                    <TableCell sx={{ py: 1 }} align="right">
                      <strong>Actions</strong>
                    </TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {filteredRequirements.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={8} align="center">
                        <Typography variant="body2" color="textSecondary" sx={{ py: 4 }}>
                          {searchQuery 
                            ? `No requirements found matching "${searchQuery}"`
                            : 'No requirements found. Create your first requirement to get started.'}
                        </Typography>
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredRequirements.map((req) => {
                      const badge = getCoverageBadge(req.requirement_id);
                      return (<React.Fragment key={req.requirement_id}>
                        <TableRow
                          hover
                          sx={{
                            '& > td:first-of-type': { borderLeft: `3px solid ${badge.borderColor}` },
                          }}
                        >
                          <TableCell sx={{ py: 0.5 }}>
                            <IconButton 
                              size="small" 
                              onClick={() => toggleRowExpansion(req.requirement_id)}
                              sx={{ p: 0 }}
                            >
                              <ExpandIcon 
                                fontSize="small" 
                                sx={{ 
                                  transform: expandedRows.has(req.requirement_id) ? 'rotate(180deg)' : 'rotate(0deg)',
                                  transition: 'transform 0.2s'
                                }}
                              />
                            </IconButton>
                          </TableCell>
                          <TableCell sx={{ py: 0.5 }}>
                            <Typography variant="body2" fontWeight="medium">
                              {req.requirement_code}
                            </Typography>
                          </TableCell>
                          <TableCell sx={{ py: 0.5 }}>
                            <Typography variant="body2">{req.requirement_name}</Typography>
                          </TableCell>
                          <TableCell sx={{ py: 0.5 }}>
                            <Chip label={req.category || 'none'} size="small" />
                          </TableCell>
                          <TableCell sx={{ py: 0.5 }}>
                            <Chip
                              label={req.priority}
                              size="small"
                              color={getPriorityColor(req.priority) as any}
                            />
                          </TableCell>
                          <TableCell sx={{ py: 0.5 }}>
                            <Tooltip title="Click to view coverage details">
                              <Chip
                                icon={badge.icon}
                                label={badge.text}
                                size="small"
                                color={badge.color}
                                onClick={() => handleOpenCoverage(req)}
                                sx={{ cursor: 'pointer' }}
                              />
                            </Tooltip>
                          </TableCell>
                          <TableCell sx={{ py: 0.5 }}>
                            <Chip
                              label={req.status}
                              size="small"
                              color={req.status === 'active' ? 'success' : 'default'}
                            />
                          </TableCell>
                          <TableCell sx={{ py: 0.5 }} align="right">
                            <Box sx={{ display: 'flex', gap: 0.5, justifyContent: 'flex-end' }}>
                              <Tooltip title="Edit requirement">
                                <IconButton size="small" onClick={() => handleEditOpen(req)} sx={{ p: 0.5 }}>
                                  <EditIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                              <Tooltip title="Link testcases">
                                <IconButton size="small" onClick={() => handleOpenLinkPicker(req)} sx={{ p: 0.5 }}>
                                  <LinkIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            </Box>
                          </TableCell>
                        </TableRow>
                        {/* Expanded row — compact linked items */}
                        {expandedRows.has(req.requirement_id) && (
                          <TableRow>
                            <TableCell style={{ paddingBottom: 0, paddingTop: 0 }} colSpan={8}>
                              <Box sx={{ py: 0.75, px: 2, display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap', bgcolor: 'action.hover' }}>
                                {loadingCoverage.has(req.requirement_id) ? (
                                  <CircularProgress size={12} />
                                ) : coverageCache[req.requirement_id] ? (
                                  <>
                                    {coverageCache[req.requirement_id].scripts.map(s => (
                                      <Chip key={s.script_name} label={s.script_name} size="small" variant="outlined" sx={{ height: 18, fontSize: '0.65rem' }} />
                                    ))}
                                    {Object.values(coverageCache[req.requirement_id].testcases_by_ui).flat().map(tc => (
                                      <Chip key={tc.testcase_id} label={tc.testcase_name} size="small" color="primary" variant="outlined" sx={{ height: 18, fontSize: '0.65rem' }} />
                                    ))}
                                    {coverageCache[req.requirement_id].scripts.length === 0 &&
                                      coverageCache[req.requirement_id].coverage_summary.total_testcases === 0 && (
                                      <Typography variant="caption" color="text.secondary" fontStyle="italic">No linked items</Typography>
                                    )}
                                  </>
                                ) : null}
                              </Box>
                            </TableCell>
                          </TableRow>
                        )}
                      </React.Fragment>
                    )})
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </CardContent>
        </Card>
      )}

      {/* Create Dialog */}
      <StyledDialog open={createDialogOpen} onClose={() => { setCreateDialogOpen(false); setFormError(null); }} maxWidth="md" fullWidth>
        <DialogTitle>Create New Requirement</DialogTitle>
        <DialogContent>
          {formError && <Alert severity="error" sx={{ mb: 1, mt: 1 }}>{formError}</Alert>}
          <Grid container spacing={2} sx={{ mt: 0 }}>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label="Requirement Code"
                placeholder="REQ_PLAYBACK_001"
                value={formData.requirement_code}
                onChange={(e) => setFormData({ ...formData, requirement_code: e.target.value })}
                required
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label="Requirement Name"
                placeholder="Basic Video Playback"
                value={formData.requirement_name}
                onChange={(e) => setFormData({ ...formData, requirement_name: e.target.value })}
                required
              />
            </Grid>
            <Grid item xs={12} sm={4}>
              <FormControl fullWidth>
                <InputLabel>Category</InputLabel>
                <Select
                  value={formData.category}
                  onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                  label="Category"
                >
                  {categories.map(cat => (
                    <MenuItem key={cat} value={cat}>{cat}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} sm={4}>
              <FormControl fullWidth>
                <InputLabel>Priority</InputLabel>
                <Select
                  value={formData.priority}
                  onChange={(e) => setFormData({ ...formData, priority: e.target.value })}
                  label="Priority"
                >
                  {priorities.map(pri => (
                    <MenuItem key={pri} value={pri}>{pri}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} sm={4}>
              <FormControl fullWidth>
                <InputLabel>Status</InputLabel>
                <Select
                  value={formData.status}
                  onChange={(e) => setFormData({ ...formData, status: e.target.value })}
                  label="Status"
                >
                  <MenuItem value="active">Active</MenuItem>
                  <MenuItem value="draft">Draft</MenuItem>
                  <MenuItem value="deprecated">Deprecated</MenuItem>
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel>App Type</InputLabel>
                <Select
                  value={formData.app_type}
                  onChange={(e) => setFormData({ ...formData, app_type: e.target.value })}
                  label="App Type"
                >
                  {appTypes.map(type => (
                    <MenuItem key={type} value={type}>{type}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel>Device Model</InputLabel>
                <Select
                  value={formData.device_model}
                  onChange={(e) => setFormData({ ...formData, device_model: e.target.value })}
                  label="Device Model"
                >
                  {deviceModels.map(model => (
                    <MenuItem key={model} value={model}>{model}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                multiline
                rows={3}
                label="Description"
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              />
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleCreate} variant="contained">Create</Button>
        </DialogActions>
      </StyledDialog>

      {/* Edit Dialog */}
      <StyledDialog open={editDialogOpen} onClose={() => { setEditDialogOpen(false); setFormError(null); }} maxWidth="md" fullWidth>
        <DialogTitle>Edit Requirement</DialogTitle>
        <DialogContent>
          {formError && <Alert severity="error" sx={{ mb: 1, mt: 1 }}>{formError}</Alert>}
          <Grid container spacing={2} sx={{ mt: 0 }}>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Requirement Code"
                value={formData.requirement_code}
                disabled
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Requirement Name"
                value={formData.requirement_name}
                onChange={(e) => setFormData({ ...formData, requirement_name: e.target.value })}
              />
            </Grid>
            <Grid item xs={12} sm={4}>
              <FormControl fullWidth>
                <InputLabel>Priority</InputLabel>
                <Select
                  value={formData.priority}
                  onChange={(e) => setFormData({ ...formData, priority: e.target.value })}
                  label="Priority"
                >
                  {priorities.map(pri => (
                    <MenuItem key={pri} value={pri}>{pri}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} sm={4}>
              <FormControl fullWidth>
                <InputLabel>Status</InputLabel>
                <Select
                  value={formData.status}
                  onChange={(e) => setFormData({ ...formData, status: e.target.value })}
                  label="Status"
                >
                  <MenuItem value="active">Active</MenuItem>
                  <MenuItem value="draft">Draft</MenuItem>
                  <MenuItem value="deprecated">Deprecated</MenuItem>
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                multiline
                rows={3}
                label="Description"
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              />
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleEdit} variant="contained">Save</Button>
        </DialogActions>
      </StyledDialog>

      {/* Coverage Modal */}
      {coverageRequirement && (
        <RequirementCoverageModal
          open={coverageModalOpen}
          onClose={() => setCoverageModalOpen(false)}
          requirementId={coverageRequirement.id}
          requirementCode={coverageRequirement.code}
          requirementName={coverageRequirement.name}
          getCoverage={getRequirementCoverage}
          onUnlinkTestcase={unlinkTestcase}
          onOpenLinkDialog={handleOpenLinkPickerFromCoverage}
        />
      )}

      {/* Link Testcase Picker Modal */}
      {linkRequirement && (
        <LinkTestcasePickerModal
          open={linkPickerOpen}
          onClose={() => setLinkPickerOpen(false)}
          requirementId={linkRequirement.id}
          requirementCode={linkRequirement.code}
          requirementName={linkRequirement.name}
          getAvailableTestcases={getAvailableTestcases}
          onLinkTestcases={linkMultipleTestcases}
          onSuccess={() => {
            refreshRequirements();
            // Reopen coverage modal if it was open
            if (coverageRequirement) {
              setCoverageModalOpen(true);
            }
          }}
        />
      )}
    </Box>
  );
};

export default Requirements;

