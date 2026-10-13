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
  Drawer,
  IconButton,
  InputAdornment,
  LinearProgress,
  MenuItem,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
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
import { useAgentChatPalette } from '../constants/agentChatTheme';

type Palette = ReturnType<typeof useAgentChatPalette>;
type CoverageFilter = 'all' | 'gaps' | 'covered';
type CoverageSort = 'coverage' | 'name';

/** Threshold colour from the app palette: ≥80% green, ≥50% amber, else red. */
const pctColor = (pct: number, P: Palette) => (pct >= 80 ? P.success : pct >= 50 ? P.warning : P.error);

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

const getRowBorderColor = (passRate: number, testcaseCount: number, palette: ReturnType<typeof useAgentChatPalette>): string => {
  if (testcaseCount === 0) return palette.textMuted;
  if (passRate >= 0.8) return palette.success;
  if (passRate >= 0.5) return palette.warning;
  return palette.error;
};

const fmt = (rate: number) => `${Math.round(rate * 100)}%`;

/** P1 red / P2 amber / P3 muted — outlined tag, readable in both themes. */
const PriorityTag: React.FC<{ priority: string; P: Palette }> = ({ priority, P }) => {
  const c = priority === 'P1' ? P.error : priority === 'P2' ? P.warning : P.textSecondary;
  return (
    <Box component="span" sx={{ display: 'inline-block', fontSize: '0.68rem', fontWeight: 600, lineHeight: 1.6, px: 0.75, borderRadius: 1, color: c, border: `1px solid ${c}66` }}>
      {priority}
    </Box>
  );
};

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
  const [filter, setFilter] = useState<CoverageFilter>('all');
  const [sortBy, setSortBy] = useState<CoverageSort>('coverage');
  const P = useAgentChatPalette();

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
      if (n.has(category)) n.delete(category);
      else n.add(category);
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
      const linked = (coverageCounts[req.requirement_id]?.total_count ?? 0) > 0;
      if (filter === 'gaps' && linked) continue;
      if (filter === 'covered' && !linked) continue;
      const cat = req.category || 'uncategorized';
      if (!grouped[cat]) grouped[cat] = [];
      grouped[cat].push(req);
    }
    return grouped;
  }, [requirements, searchQuery, filter, coverageCounts]);

  // Every requirement per category, unfiltered — category stats never depend on the search/filter.
  const allByCategory = useMemo(() => {
    const grouped: Record<string, Requirement[]> = {};
    for (const req of requirements) {
      const cat = req.category || 'uncategorized';
      (grouped[cat] ||= []).push(req);
    }
    return grouped;
  }, [requirements]);

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

  const sortedCategories = useMemo(() => {
    const entries = Object.entries(reqsByCategory);
    if (sortBy === 'name') return entries.sort(([a], [b]) => a.localeCompare(b));
    return entries.sort(([a], [b]) => getCatStats(a, allByCategory[a] || []).pct - getCatStats(b, allByCategory[b] || []).pct || a.localeCompare(b));
  }, [reqsByCategory, sortBy, getCatStats, allByCategory]);

  const getSortedFilteredReqs = useCallback((reqs: Requirement[]): Requirement[] => {
    return [...reqs].sort((a, b) => (PRIORITY_ORDER[a.priority] ?? 9) - (PRIORITY_ORDER[b.priority] ?? 9));
  }, []);

  return (
    <Box>
      {/* ZONE 1 — Sticky health strip: KPI cards, overall bar, toolbar */}
      <Box sx={{ position: 'sticky', top: 0, zIndex: 100, bgcolor: 'background.default', mb: 1.5, pb: 1.5, pt: 0.5 }}>
        <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 1, mb: 1.25 }}>
          {[
            { label: 'Requirements', value: String(stats.total) },
            {
              label: 'Covered',
              value: String(stats.covered),
              extra: stats.total ? `${Math.round((stats.covered / stats.total) * 100)}%` : undefined,
              color: P.success,
            },
            { label: 'Tests linked', value: String(stats.totalTests) },
            {
              label: 'Gaps · no test',
              value: String(stats.gaps),
              color: stats.gaps > 0 ? P.error : undefined,
              onClick: stats.gaps > 0 ? () => setFilter(filter === 'gaps' ? 'all' : 'gaps') : undefined,
              active: filter === 'gaps',
            },
            ...(stats.avgPassRate !== null
              ? [{ label: 'Avg pass rate', value: fmt(stats.avgPassRate), color: pctColor(stats.avgPassRate * 100, P) }]
              : []),
          ].map((k: any) => (
            <Box
              key={k.label}
              onClick={k.onClick}
              title={k.onClick ? (k.active ? 'Show all requirements' : 'Show only requirements without a test') : undefined}
              sx={{
                px: 1.5, py: 1, borderRadius: 2, bgcolor: P.surface,
                border: `1px solid ${k.active ? k.color : P.borderColor}`,
                cursor: k.onClick ? 'pointer' : 'default',
                transition: 'border-color 0.15s',
                '&:hover': k.onClick ? { borderColor: k.color } : undefined,
              }}
            >
              <Typography sx={{ fontSize: '0.72rem', color: P.textMuted }}>{k.label}</Typography>
              <Typography sx={{ fontSize: '1.35rem', fontWeight: 600, lineHeight: 1.25, color: k.color || P.textPrimary }}>
                {k.value}
                {k.extra && <Box component="span" sx={{ fontSize: '0.75rem', fontWeight: 400, color: P.textMuted, ml: 0.75 }}>{k.extra}</Box>}
              </Typography>
            </Box>
          ))}
        </Box>

        {stats.total > 0 && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, mb: 1.25 }}>
            <Typography sx={{ fontSize: '0.75rem', color: P.textSecondary }}>Overall</Typography>
            <LinearProgress
              variant="determinate"
              value={(stats.covered / stats.total) * 100}
              sx={{ flex: 1, height: 6, borderRadius: 3, bgcolor: P.hoverBg, '& .MuiLinearProgress-bar': { bgcolor: P.accent, borderRadius: 3 } }}
            />
            <Typography sx={{ fontSize: '0.75rem', color: P.textSecondary, fontVariantNumeric: 'tabular-nums' }}>
              {stats.covered} / {stats.total}
            </Typography>
          </Box>
        )}

        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          <TextField
            size="small"
            placeholder="Search requirements"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            sx={{ minWidth: 240, '& .MuiInputBase-root': { height: 32, fontSize: '0.85rem', borderRadius: 1.5 } }}
            InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }}
          />
          <ToggleButtonGroup
            size="small"
            exclusive
            value={filter}
            onChange={(_, v) => v && setFilter(v)}
            sx={{
              bgcolor: P.hoverBg, p: 0.375, borderRadius: 2, gap: 0.375,
              '& .MuiToggleButton-root': {
                border: '1px solid transparent !important', borderRadius: '6px !important',
                textTransform: 'none', fontSize: 12, fontWeight: 500, color: P.textSecondary, py: 0.25, px: 1.5,
              },
              '& .MuiToggleButton-root.Mui-selected': {
                bgcolor: P.surface, color: P.accentText, fontWeight: 600,
                borderColor: `${P.borderColor} !important`, '&:hover': { bgcolor: P.surface },
              },
            }}
          >
            <ToggleButton value="all">All</ToggleButton>
            <ToggleButton value="gaps">Gaps</ToggleButton>
            <ToggleButton value="covered">Covered</ToggleButton>
          </ToggleButtonGroup>
          <Box sx={{ flex: 1 }} />
          <Typography sx={{ fontSize: '0.75rem', color: P.textMuted }}>Sort</Typography>
          <Select
            size="small"
            value={sortBy}
            onChange={e => setSortBy(e.target.value as CoverageSort)}
            sx={{ height: 32, fontSize: '0.8rem', borderRadius: 1.5 }}
          >
            <MenuItem value="coverage">Lowest coverage first</MenuItem>
            <MenuItem value="name">Name</MenuItem>
          </Select>
        </Box>
      </Box>

      {isLoading && <Box display="flex" justifyContent="center" p={4}><CircularProgress sx={{ color: P.accent }} /></Box>}

      {/* ZONE 2 — Coverage matrix: one list, a row per category */}
      {!isLoading && (
        <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 2, overflow: 'hidden', bgcolor: P.surface }}>
          {sortedCategories.map(([category, reqs], catIndex) => {
            const catReqs = allByCategory[category] || reqs;
            const { covered, pct, totalTests, avgPr } = getCatStats(category, catReqs);
            const isExpanded = expandedCategories.has(category);
            const isCatLoading = loadingCategories.has(category);
            const visible = getSortedFilteredReqs(reqs);
            const gaps = catReqs.length - covered;
            const color = pctColor(pct, P);

            return (
              <Box key={category} sx={{ borderTop: catIndex === 0 ? 'none' : `1px solid ${P.borderColor}` }}>
                {/* Category header */}
                <Box
                  sx={{
                    display: 'grid',
                    gridTemplateColumns: '20px 150px minmax(80px, 1fr) 44px 64px 72px 80px 72px',
                    alignItems: 'center', columnGap: 1.5, px: 1.5, py: 1.1, cursor: 'pointer',
                    bgcolor: isExpanded ? P.hoverBg : 'transparent',
                    '&:hover': { bgcolor: P.hoverBg },
                  }}
                  onClick={() => toggleCategory(category)}
                >
                  {isCatLoading
                    ? <CircularProgress size={14} sx={{ color: P.accent }} />
                    : isExpanded ? <ExpandMoreIcon fontSize="small" sx={{ color: P.textMuted }} /> : <ChevronRightIcon fontSize="small" sx={{ color: P.textMuted }} />}
                  <Typography noWrap sx={{ fontSize: '0.88rem', fontWeight: 600, textTransform: 'capitalize' }}>{category}</Typography>
                  <LinearProgress
                    variant="determinate"
                    value={pct}
                    sx={{ height: 6, borderRadius: 3, bgcolor: P.hoverBg, '& .MuiLinearProgress-bar': { bgcolor: color, borderRadius: 3 } }}
                  />
                  <Typography sx={{ fontSize: '0.78rem', fontWeight: 600, color, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {Math.round(pct)}%
                  </Typography>
                  <Typography sx={{ fontSize: '0.78rem', color: P.textSecondary, fontVariantNumeric: 'tabular-nums' }} title="Requirements with at least one linked test">
                    {covered}/{catReqs.length}
                  </Typography>
                  <Typography sx={{ fontSize: '0.78rem', color: P.textSecondary }}>
                    {totalTests} test{totalTests === 1 ? '' : 's'}
                  </Typography>
                  <Box>
                    {gaps > 0 && (
                      <Box component="span" sx={{ fontSize: '0.7rem', fontWeight: 600, px: 1, py: 0.25, borderRadius: 999, color: P.error, bgcolor: `${P.error}1a` }}>
                        {gaps} gap{gaps === 1 ? '' : 's'}
                      </Box>
                    )}
                  </Box>
                  <Box>
                    {avgPr !== null && (
                      <Typography sx={{ fontSize: '0.75rem', fontWeight: 600, color: pctColor(avgPr * 100, P) }} title="Average pass rate of the linked tests">
                        {fmt(avgPr)} pass
                      </Typography>
                    )}
                  </Box>
                </Box>

                {/* Expanded table */}
                {isExpanded && (
                  <Box sx={{ borderTop: `1px solid ${P.borderColor}` }}>
                    {isCatLoading ? (
                      <Box display="flex" justifyContent="center" p={2}><CircularProgress size={20} /></Box>
                    ) : (
                      <Table size="small" sx={{ width: '100%', tableLayout: 'fixed', '& td, & th': { borderColor: P.borderColor }, '& th': { fontSize: '0.7rem', color: P.textMuted, py: 0.75, bgcolor: P.hoverBg, backgroundColor: `${P.hoverBg} !important` } }}>
                        <TableHead>
                          <TableRow>
                            <TableCell sx={{ pl: 5.5 }}>Requirement</TableCell>
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
                                  '&:hover': { backgroundColor: P.hoverBg },
                                }}
                              >
                                <TableCell sx={{ overflow: 'hidden', pl: 2.5 }}>
                                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                    <Tooltip title={tc === 0 ? 'No linked test' : data ? `Pass rate ${fmt(pr)}` : 'Linked'}>
                                      <Box sx={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, bgcolor: tc === 0 ? P.textMuted : data ? pctColor(pr * 100, P) : P.accent }} />
                                    </Tooltip>
                                    <Typography variant="caption" fontWeight="bold" sx={{ fontFamily: 'monospace', flexShrink: 0 }}>
                                      {req.requirement_code}
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                      {req.requirement_name}
                                    </Typography>
                                  </Box>
                                </TableCell>
                                <TableCell>
                                  <PriorityTag priority={req.priority} P={P} />
                                </TableCell>
                                <TableCell>
                                  <Typography variant="caption" color={tc === 0 ? 'text.disabled' : 'text.primary'}>{tc === 0 ? '—' : tc}</Typography>
                                </TableCell>
                                <TableCell>
                                  {tc === 0 ? (
                                    <Typography variant="caption" color="text.disabled">—</Typography>
                                  ) : data ? (
                                    <Typography variant="caption" sx={{ fontWeight: 600, color: pctColor(pr * 100, P) }}>{fmt(pr)}</Typography>
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
              </Box>
            );
          })}
          {sortedCategories.length === 0 && (
            <Typography sx={{ p: 3, textAlign: 'center', fontSize: '0.85rem', color: P.textMuted }}>
              No requirements match. Change the search or the filter.
            </Typography>
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
              {selectedReq && <Box sx={{ mt: 0.75 }}><PriorityTag priority={selectedReq.priority} P={P} /></Box>}
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
                <Box sx={{ display: 'flex', gap: 3, mb: 2, p: 1.5, bgcolor: P.hoverBg, borderRadius: 2 }}>
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
                          sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, p: 0.75, border: 1, borderColor: 'divider', borderRadius: 1, borderLeft: `3px solid ${getRowBorderColor(tc.pass_rate, tc.execution_count, P)}` }}
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
