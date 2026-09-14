/**
 * Coverage Dashboard Page — 3-zone design
 *
 * Zone 1: Sticky health strip (stats + filters)
 * Zone 2: Coverage matrix — categories with progress bars, expandable to compact tables
 * Zone 3: Side drawer for requirement detail
 */

import React, { useState, useMemo, useCallback } from 'react';
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Divider,
  Drawer,
  IconButton,
  InputAdornment,
  LinearProgress,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import {
  ChevronRight as ChevronRightIcon,
  Close as CloseIcon,
  ExpandMore as ExpandMoreIcon,
  LinkOff as UnlinkIcon,
  Search as SearchIcon,
} from '@mui/icons-material';
import { useRequirements, Requirement, RequirementCoverage } from '../hooks/pages/useRequirements';
import { useConfirmDialog } from '../hooks/useConfirmDialog';
import { ConfirmDialog } from '../components/common/ConfirmDialog';

interface ReqCoverageData {
  pass_rate: number;
  testcase_count: number;
  uis: string[];
}

const PRIORITY_ORDER: Record<string, number> = { P1: 0, P2: 1, P3: 2 };

const getPassRateColor = (passRate: number, testcaseCount: number): string => {
  if (testcaseCount === 0) return 'text.disabled';
  if (passRate >= 0.8) return 'success.main';
  if (passRate >= 0.5) return 'warning.main';
  return 'error.main';
};

const getRowBorderColor = (passRate: number, testcaseCount: number): string => {
  if (testcaseCount === 0) return '#666';
  if (passRate >= 0.8) return '#4caf50';
  if (passRate >= 0.5) return '#ff9800';
  return '#f44336';
};

const getLinearProgressColor = (pct: number): 'success' | 'warning' | 'error' => {
  if (pct >= 80) return 'success';
  if (pct >= 50) return 'warning';
  return 'error';
};

const getProgressTextColor = (pct: number): string => {
  if (pct >= 80) return 'success.main';
  if (pct >= 50) return 'warning.main';
  return 'error.main';
};

const getPriorityColor = (p: string): 'error' | 'warning' | 'info' | 'default' => {
  if (p === 'P1') return 'error';
  if (p === 'P2') return 'warning';
  if (p === 'P3') return 'info';
  return 'default';
};

const fmt = (rate: number) => `${Math.round(rate * 100)}%`;

const timeAgo = (ts: string) => {
  const ms = Date.now() - new Date(ts).getTime();
  const m = Math.floor(ms / 60000);
  const h = Math.floor(ms / 3600000);
  const d = Math.floor(ms / 86400000);
  if (m < 60) return `${m}m ago`;
  if (h < 24) return `${h}h ago`;
  return `${d}d ago`;
};

const Coverage: React.FC = () => {
  const {
    requirements,
    isLoading,
    getRequirementCoverage,
    unlinkTestcase,
    coverageCounts,
  } = useRequirements();

  const [searchQuery, setSearchQuery] = useState('');

  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set());
  const [categoryData, setCategoryData] = useState<Record<string, Record<string, ReqCoverageData>>>({});
  const [loadingCategories, setLoadingCategories] = useState<Set<string>>(new Set());

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedReq, setSelectedReq] = useState<Requirement | null>(null);
  const [drawerCoverage, setDrawerCoverage] = useState<RequirementCoverage | null>(null);
  const [drawerLoading, setDrawerLoading] = useState(false);

  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  const loadCategoryData = useCallback(async (category: string) => {
    if (categoryData[category]) return;
    setLoadingCategories(prev => new Set(prev).add(category));
    const reqs = requirements.filter(
      r => (r.category || 'uncategorized') === category && (coverageCounts[r.requirement_id]?.total_count ?? 0) > 0
    );
    const results: Record<string, ReqCoverageData> = {};
    await Promise.all(reqs.map(async req => {
      const cov = await getRequirementCoverage(req.requirement_id);
      if (cov) {
        results[req.requirement_id] = {
          pass_rate: cov.coverage_summary.pass_rate,
          testcase_count: cov.coverage_summary.total_testcases,
          uis: Object.keys(cov.testcases_by_ui),
        };
      }
    }));
    setCategoryData(prev => ({ ...prev, [category]: results }));
    setLoadingCategories(prev => { const n = new Set(prev); n.delete(category); return n; });
  }, [categoryData, requirements, coverageCounts, getRequirementCoverage]);

  const toggleCategory = useCallback(async (category: string) => {
    if (!expandedCategories.has(category)) await loadCategoryData(category);
    setExpandedCategories(prev => {
      const n = new Set(prev);
      n.has(category) ? n.delete(category) : n.add(category);
      return n;
    });
  }, [expandedCategories, loadCategoryData]);

  const openDrawer = useCallback(async (req: Requirement) => {
    setSelectedReq(req);
    setDrawerOpen(true);
    setDrawerLoading(true);
    setDrawerCoverage(null);
    const cov = await getRequirementCoverage(req.requirement_id);
    setDrawerCoverage(cov);
    setDrawerLoading(false);
  }, [getRequirementCoverage]);

  const handleUnlink = useCallback((testcaseId: string, req: Requirement) => {
    confirm({
      title: 'Unlink Testcase',
      message: 'Are you sure you want to unlink this testcase?',
      confirmColor: 'error',
      confirmText: 'Unlink',
      cancelText: 'Cancel',
      onConfirm: async () => {
        const result = await unlinkTestcase(testcaseId, req.requirement_id);
        if (result.success) {
          const cov = await getRequirementCoverage(req.requirement_id);
          setDrawerCoverage(cov);
          const cat = req.category || 'uncategorized';
          setCategoryData(prev => { const n = { ...prev }; delete n[cat]; return n; });
        }
      },
    });
  }, [confirm, unlinkTestcase, getRequirementCoverage]);

  const reqsByCategory = useMemo(() => {
    const grouped: Record<string, Requirement[]> = {};
    for (const req of requirements) {
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        if (!req.requirement_code.toLowerCase().includes(q) && !req.requirement_name.toLowerCase().includes(q)) continue;
      }
      const cat = req.category || 'uncategorized';
      if (!grouped[cat]) grouped[cat] = [];
      grouped[cat].push(req);
    }
    return grouped;
  }, [requirements, searchQuery]);

  const stats = useMemo(() => {
    const total = requirements.length;
    const covered = requirements.filter(r => (coverageCounts[r.requirement_id]?.total_count ?? 0) > 0).length;
    const totalTests = requirements.reduce((s, r) => s + (coverageCounts[r.requirement_id]?.testcase_count ?? 0), 0);
    let prSum = 0, prCount = 0;
    for (const catReqs of Object.values(categoryData)) {
      for (const d of Object.values(catReqs)) {
        if (d.testcase_count > 0) { prSum += d.pass_rate; prCount++; }
      }
    }
    return { total, covered, gaps: total - covered, totalTests, avgPassRate: prCount > 0 ? prSum / prCount : null };
  }, [requirements, coverageCounts, categoryData]);

  const getCatStats = useCallback((category: string, reqs: Requirement[]) => {
    const covered = reqs.filter(r => (coverageCounts[r.requirement_id]?.total_count ?? 0) > 0).length;
    const pct = reqs.length > 0 ? (covered / reqs.length) * 100 : 0;
    const totalTests = reqs.reduce((s, r) => s + (coverageCounts[r.requirement_id]?.testcase_count ?? 0), 0);
    const catData = categoryData[category];
    let avgPr: number | null = null;
    if (catData) {
      const entries = Object.values(catData).filter(d => d.testcase_count > 0);
      if (entries.length > 0) avgPr = entries.reduce((s, d) => s + d.pass_rate, 0) / entries.length;
    }
    return { covered, pct, totalTests, avgPr };
  }, [coverageCounts, categoryData]);

  const getSortedFilteredReqs = useCallback((reqs: Requirement[]): Requirement[] => {
    return [...reqs].sort((a, b) => (PRIORITY_ORDER[a.priority] ?? 9) - (PRIORITY_ORDER[b.priority] ?? 9));
  }, []);

  return (
    <Box>
      {/* ZONE 1 — Sticky health strip */}
      <Box sx={{ position: 'sticky', top: 0, zIndex: 100, bgcolor: 'background.paper', borderBottom: 1, borderColor: 'divider', mb: 1.5, pb: 1, pt: 0.5 }}>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap', mb: 1 }}>
          <Box><Typography variant="caption" color="text.secondary">Requirements</Typography><Typography variant="h6" lineHeight={1.2}>{stats.total}</Typography></Box>
          <Divider orientation="vertical" flexItem />
          <Box><Typography variant="caption" color="text.secondary">Covered</Typography><Typography variant="h6" lineHeight={1.2} color="success.main">{stats.covered}</Typography></Box>
          <Divider orientation="vertical" flexItem />
          <Box><Typography variant="caption" color="text.secondary">Tests linked</Typography><Typography variant="h6" lineHeight={1.2}>{stats.totalTests}</Typography></Box>
          <Divider orientation="vertical" flexItem />
          <Box>
            <Typography variant="caption" color="text.secondary">Gaps (0 tests)</Typography>
            <Typography variant="h6" lineHeight={1.2} color={stats.gaps > 0 ? 'error.main' : 'text.primary'}>{stats.gaps}</Typography>
          </Box>
          {stats.avgPassRate !== null && (
            <>
              <Divider orientation="vertical" flexItem />
              <Box>
                <Typography variant="caption" color="text.secondary">Avg Pass Rate</Typography>
                <Typography variant="h6" lineHeight={1.2} color={getPassRateColor(stats.avgPassRate, 1)}>{fmt(stats.avgPassRate)}</Typography>
              </Box>
            </>
          )}
        </Box>
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
          <TextField
            size="small"
            placeholder="Search requirements..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            sx={{ minWidth: 220 }}
            InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }}
          />
        </Box>
      </Box>

      {isLoading && <Box display="flex" justifyContent="center" p={4}><CircularProgress /></Box>}

      {/* ZONE 2 — Coverage matrix */}
      {!isLoading && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
          {Object.entries(reqsByCategory).map(([category, reqs]) => {
            const { covered, pct, totalTests, avgPr } = getCatStats(category, reqs);
            const isExpanded = expandedCategories.has(category);
            const isCatLoading = loadingCategories.has(category);
            const visible = getSortedFilteredReqs(reqs);

            return (
              <Paper key={category} variant="outlined" sx={{ overflow: 'hidden' }}>
                {/* Category header */}
                <Box
                  sx={{ display: 'flex', alignItems: 'center', gap: 1.5, px: 1.5, py: 1, cursor: 'pointer', '&:hover': { bgcolor: 'transparent' } }}
                  onClick={() => toggleCategory(category)}
                >
                  <IconButton size="small" sx={{ p: 0, pointerEvents: 'none' }}>
                    {isExpanded ? <ExpandMoreIcon fontSize="small" /> : <ChevronRightIcon fontSize="small" />}
                  </IconButton>
                  <Typography variant="subtitle2" sx={{ textTransform: 'capitalize', minWidth: 110 }}>{category}</Typography>
                  <Box sx={{ flex: 1, maxWidth: 260 }}>
                    <LinearProgress variant="determinate" value={pct} color={getLinearProgressColor(pct)} sx={{ height: 6, borderRadius: 3 }} />
                  </Box>
                  <Typography variant="caption" color={getProgressTextColor(pct)} sx={{ minWidth: 32 }}>
                    {Math.round(pct)}%
                  </Typography>
                  <Chip label={`${covered}/${reqs.length} reqs`} size="small" />
                  <Chip label={`${totalTests} tests`} size="small" color="primary" variant="outlined" />
                  {avgPr !== null && (
                    <Chip label={`${fmt(avgPr)} pass`} size="small" color={avgPr >= 0.8 ? 'success' : avgPr >= 0.5 ? 'warning' : 'error'} />
                  )}
                  {isCatLoading && <CircularProgress size={14} />}
                </Box>

                {/* Expanded table */}
                {isExpanded && (
                  <Box sx={{ borderTop: 1, borderColor: 'divider' }}>
                    {isCatLoading ? (
                      <Box display="flex" justifyContent="center" p={2}><CircularProgress size={20} /></Box>
                    ) : (
                      <Table size="small" sx={{ width: '100%', tableLayout: 'fixed' }}>
                        <TableHead>
                          <TableRow>
                            <TableCell>Requirement</TableCell>
                            <TableCell sx={{ width: 50 }}>Pri</TableCell>
                            <TableCell sx={{ width: 55 }}>Tests</TableCell>
                            <TableCell sx={{ width: 70 }}>Pass</TableCell>
                            <TableCell sx={{ width: 100 }}>UI</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {visible.map(req => {
                            const data = categoryData[category]?.[req.requirement_id];
                            const tc = coverageCounts[req.requirement_id]?.testcase_count ?? 0;
                            const pr = data?.pass_rate ?? 0;
                            return (
                              <TableRow
                                key={req.requirement_id}
                                onClick={() => openDrawer(req)}
                                sx={{
                                  cursor: 'pointer',
                                  opacity: tc === 0 ? 0.55 : 1,
                                  '&:hover': { backgroundColor: 'transparent' },
                                  '& > td:first-of-type': { borderLeft: `3px solid ${getRowBorderColor(pr, tc)}` },
                                }}
                              >
                                <TableCell sx={{ overflow: 'hidden' }}>
                                  <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.75 }}>
                                    <Typography variant="caption" fontWeight="bold" sx={{ fontFamily: 'monospace', flexShrink: 0 }}>
                                      {req.requirement_code}
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                      {req.requirement_name}
                                    </Typography>
                                  </Box>
                                </TableCell>
                                <TableCell>
                                  <Chip label={req.priority} size="small" color={getPriorityColor(req.priority)} sx={{ height: 18, fontSize: '0.65rem' }} />
                                </TableCell>
                                <TableCell>
                                  <Typography variant="caption" color={tc === 0 ? 'text.disabled' : 'text.primary'}>{tc === 0 ? '—' : tc}</Typography>
                                </TableCell>
                                <TableCell>
                                  {tc === 0 ? (
                                    <Typography variant="caption" color="text.disabled">—</Typography>
                                  ) : data ? (
                                    <Typography variant="caption" color={getPassRateColor(pr, tc)}>{fmt(pr)}</Typography>
                                  ) : (
                                    <CircularProgress size={10} />
                                  )}
                                </TableCell>
                                <TableCell>
                                  <Box sx={{ display: 'flex', gap: 0.25, alignItems: 'center', overflow: 'hidden' }}>
                                    {data?.uis.slice(0, 1).map(ui => (
                                      <Chip key={ui} label={ui} size="small" variant="outlined" sx={{ height: 16, fontSize: '0.6rem', maxWidth: 90 }} />
                                    ))}
                                    {(data?.uis.length ?? 0) > 1 && (
                                      <Typography variant="caption" color="text.secondary">+{(data?.uis.length ?? 0) - 1}</Typography>
                                    )}
                                  </Box>
                                </TableCell>
                              </TableRow>
                            );
                          })}
                          {visible.length === 0 && (
                            <TableRow>
                              <TableCell colSpan={5}>
                                <Typography variant="caption" color="text.secondary">No requirements match current filters.</Typography>
                              </TableCell>
                            </TableRow>
                          )}
                        </TableBody>
                      </Table>
                    )}
                  </Box>
                )}
              </Paper>
            );
          })}
          {Object.keys(reqsByCategory).length === 0 && (
            <Alert severity="info">No requirements found. Adjust your search or filters.</Alert>
          )}
        </Box>
      )}

      {/* ZONE 3 — Detail drawer */}
      <Drawer anchor="right" open={drawerOpen} onClose={() => setDrawerOpen(false)} PaperProps={{ sx: { width: 420 } }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          {/* Drawer header */}
          <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', p: 2, borderBottom: 1, borderColor: 'divider' }}>
            <Box>
              <Typography variant="subtitle1" fontWeight="bold">{selectedReq?.requirement_code}</Typography>
              <Typography variant="body2" color="text.secondary">{selectedReq?.requirement_name}</Typography>
              {selectedReq && <Chip label={selectedReq.priority} size="small" color={getPriorityColor(selectedReq.priority)} sx={{ mt: 0.5 }} />}
            </Box>
            <IconButton size="small" onClick={() => setDrawerOpen(false)}><CloseIcon fontSize="small" /></IconButton>
          </Box>

          {/* Drawer body */}
          <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
            {drawerLoading && <Box display="flex" justifyContent="center" p={4}><CircularProgress /></Box>}

            {!drawerLoading && !drawerCoverage && <Alert severity="error">Failed to load coverage data.</Alert>}

            {!drawerLoading && drawerCoverage && selectedReq && (
              <Box>
                {/* Summary */}
                <Box sx={{ display: 'flex', gap: 2, mb: 2, p: 1.5, bgcolor: 'action.hover', borderRadius: 1 }}>
                  <Box><Typography variant="caption" color="text.secondary">Test Cases</Typography><Typography variant="h6" lineHeight={1.2}>{drawerCoverage.coverage_summary.total_testcases}</Typography></Box>
                  <Box><Typography variant="caption" color="text.secondary">Executions</Typography><Typography variant="h6" lineHeight={1.2}>{drawerCoverage.coverage_summary.execution_count}</Typography></Box>
                  <Box>
                    <Typography variant="caption" color="text.secondary">Pass Rate</Typography>
                    <Typography variant="h6" lineHeight={1.2} color={getPassRateColor(drawerCoverage.coverage_summary.pass_rate, drawerCoverage.coverage_summary.total_testcases)}>
                      {drawerCoverage.coverage_summary.total_testcases > 0 ? fmt(drawerCoverage.coverage_summary.pass_rate) : '—'}
                    </Typography>
                  </Box>
                </Box>

                {/* Scripts */}
                {drawerCoverage.scripts.length > 0 && (
                  <Box mb={2}>
                    <Typography variant="caption" fontWeight="bold" color="text.secondary" sx={{ textTransform: 'uppercase', letterSpacing: 0.5 }}>Scripts</Typography>
                    <Box sx={{ mt: 0.5, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                      {drawerCoverage.scripts.map(script => (
                        <Box key={script.script_name} sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 0.75, border: 1, borderColor: 'divider', borderRadius: 1 }}>
                          <Box flex={1}>
                            <Typography variant="caption" sx={{ fontFamily: 'monospace', display: 'block' }}>{script.script_name}</Typography>
                            <Typography variant="caption" color="text.secondary">
                              {script.execution_count > 0 ? `${script.pass_count}/${script.execution_count} passed` : 'not yet run'}
                            </Typography>
                          </Box>
                          {script.execution_count > 0 && (
                            <Typography variant="caption" color={getPassRateColor(script.pass_rate, 1)}>{fmt(script.pass_rate)}</Typography>
                          )}
                        </Box>
                      ))}
                    </Box>
                  </Box>
                )}

                {/* Testcases by UI */}
                {Object.entries(drawerCoverage.testcases_by_ui).map(([uiName, testcases]) => (
                  <Box key={uiName} mb={2}>
                    <Typography variant="caption" fontWeight="bold" color="text.secondary" sx={{ textTransform: 'uppercase', letterSpacing: 0.5 }}>
                      {uiName} · {testcases.length} testcase{testcases.length !== 1 ? 's' : ''}
                    </Typography>
                    <Box sx={{ mt: 0.5, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                      {testcases.map(tc => (
                        <Box
                          key={tc.testcase_id}
                          sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, p: 0.75, border: 1, borderColor: 'divider', borderRadius: 1, borderLeft: `3px solid ${getRowBorderColor(tc.pass_rate, tc.execution_count)}` }}
                        >
                          <Box flex={1}>
                            <Typography variant="caption" fontWeight="medium" display="block">{tc.testcase_name}</Typography>
                            <Typography variant="caption" color="text.secondary">
                              {tc.execution_count > 0 ? `${tc.pass_count}/${tc.execution_count} passed` : 'not yet run'}
                              {tc.last_execution && ` · ${timeAgo(tc.last_execution.started_at)}`}
                            </Typography>
                          </Box>
                          {tc.execution_count > 0 && (
                            <Typography variant="caption" color={getPassRateColor(tc.pass_rate, tc.execution_count)}>{fmt(tc.pass_rate)}</Typography>
                          )}
                          <Tooltip title="Unlink testcase">
                            <IconButton size="small" color="error" onClick={() => handleUnlink(tc.testcase_id, selectedReq)}>
                              <UnlinkIcon sx={{ fontSize: 14 }} />
                            </IconButton>
                          </Tooltip>
                        </Box>
                      ))}
                    </Box>
                  </Box>
                ))}

                {Object.keys(drawerCoverage.testcases_by_ui).length === 0 && drawerCoverage.scripts.length === 0 && (
                  <Alert severity="info" sx={{ mt: 1 }}>No coverage linked yet.</Alert>
                )}
              </Box>
            )}
          </Box>
        </Box>
      </Drawer>

      <ConfirmDialog
        open={dialogState.open}
        title={dialogState.title}
        message={dialogState.message}
        confirmText={dialogState.confirmText}
        cancelText={dialogState.cancelText}
        confirmColor={dialogState.confirmColor}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </Box>
  );
};

export default Coverage;
