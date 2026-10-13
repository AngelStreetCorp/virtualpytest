import {
  KeyboardArrowDown as ExpandMoreIcon,
  KeyboardArrowRight as ExpandLessIcon,
  Error as IncidentIcon,
  Assessment as ScriptIcon,
  Clear as ClearIcon,
  DeleteSweep as ClearAllIcon,
  CheckCircle as PassIcon,
  Error as FailIcon,
  Person as ManualIcon,
  Comment as CommentIcon,
} from '@mui/icons-material';

import { AIIcon as AiIcon } from '../components/common/icons/CustomIcons';
import {
  Box,
  Typography,
  Card,
  CardContent,
  CircularProgress,
  Alert,
  IconButton,
  Collapse,
  Grid,
  Button,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Chip,
  ToggleButton,
  ToggleButtonGroup,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Tooltip,
} from '@mui/material';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { PageTitle, StatTiles, pageSurfaceSx, segmentedSx } from '../components/common/PageChrome';
import React, { useState, useEffect } from 'react';

import JevWhy, { analysisTypeLabel, getJev } from '../components/common/JevWhy';
import { StyledDialog } from '../components/common/StyledDialog';
import { useAIQueue, AIQueueStatus, LastAnalyzedResult } from '../hooks/pages/useAIQueue';
import { discardReason } from '../utils/discardReason';
import { formatToLocalTime } from '../utils/dateUtils';
import { getCached, setCached } from '../utils/pageCache';

type QueueView = 'incidents' | 'scripts';

const AIQueueMonitor: React.FC = () => {
  const P = useAgentChatPalette();
  const { getQueueStatus, clearQueues } = useAIQueue();
  const [queueStatus, setQueueStatus] = useState<AIQueueStatus | null>(() => getCached<AIQueueStatus>('ai-queue'));
  const [loading, setLoading] = useState(!getCached<AIQueueStatus>('ai-queue'));
  const [error, setError] = useState<string | null>(null);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set());
  const [queueView, setQueueView] = useState<QueueView>('incidents');
  const [resultFilter, setResultFilter] = useState<'discarded' | 'kept' | 'pending' | null>(null);
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [reasonFilter, setReasonFilter] = useState<string | null>(null);
  const [clearDialog, setClearDialog] = useState<{
    open: boolean;
    queueType: 'incidents' | 'scripts' | 'all';
    queueName: string;
  }>({ open: false, queueType: 'all', queueName: '' });
  const [commentModal, setCommentModal] = useState<{
    open: boolean;
    item: LastAnalyzedResult | null;
  }>({ open: false, item: null });

  const fetchStatus = async (includeItems: boolean = false) => {
    try {
      setError(null);
      const status = await getQueueStatus(includeItems);
      setQueueStatus(status);
      setCached('ai-queue', status);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch queue status');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus(true);
  }, [getQueueStatus]);

  const toggleSection = (section: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      if (next.has(section)) {
        next.delete(section);
      } else {
        next.add(section);
      }
      return next;
    });
  };

  const handleClearQueue = (queueType: 'incidents' | 'scripts' | 'all', queueName: string) => {
    setClearDialog({ open: true, queueType, queueName });
  };

  const confirmClearQueue = async () => {
    try {
      await clearQueues(clearDialog.queueType);
      setClearDialog({ open: false, queueType: 'all', queueName: '' });
      await fetchStatus(true);
    } catch (clearError) {
      console.error('Failed to clear queue:', clearError);
    }
  };

  const cancelClearQueue = () => {
    setClearDialog({ open: false, queueType: 'all', queueName: '' });
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  const selectedQueue = queueStatus?.queues[queueView];
  const selectedAnalysis = queueStatus?.analysis_24h?.[queueView];
  const hasQueues = Boolean(queueStatus && (queueStatus.queues.incidents.length > 0 || queueStatus.queues.scripts.length > 0));
  const toggleResult = (v: 'discarded' | 'kept' | 'pending') => {
    setResultFilter((cur) => (cur === v ? null : v));
    if (v === 'pending') setExpandedSections((prev) => new Set(prev).add(queueView));
  };
  const analysisItems = (selectedAnalysis?.items || []).filter(
    (i) =>
      (resultFilter !== 'discarded' || i.discard) &&
      (resultFilter !== 'kept' || !i.discard) &&
      (queueView !== 'incidents' || !typeFilter || i.incident_type === typeFilter) &&
      (!reasonFilter || discardReason(i.discard_comment) === reasonFilter),
  );

  const getCheckTypeIcon = (item: LastAnalyzedResult) => {
    if (!item.check_type) return <Typography variant="body2" color="text.disabled">-</Typography>;
    if (item.check_type === 'ai_strategy_skip') {
      return (
        <Tooltip title="Skipped by strategy">
          <Typography variant="body2" color="text.disabled" sx={{ fontStyle: 'italic' }}>Skip</Typography>
        </Tooltip>
      );
    }
    const isAI = item.check_type === 'ai' || item.check_type === 'ai_agent' || item.check_type === 'ai_and_human';
    const isHuman = item.check_type === 'ai_and_human';
    return (
      <Tooltip title={isHuman ? 'AI & Human' : isAI ? 'AI Agent' : 'Manual'}>
        <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
          {isAI && <AiIcon fontSize="small" color="primary" />}
          {(item.check_type === 'manual' || isHuman) && <ManualIcon fontSize="small" color="primary" />}
        </Box>
      </Tooltip>
    );
  };

  return (
    <Box sx={pageSurfaceSx(P)}>
      <PageTitle
        title="AI Queue Monitor"
        subtitle="What the AI triage worker analysed in the last 24 hours, and what is still waiting"
        right={
          <>
            {queueView === 'incidents' && (
              <>
                <ToggleButtonGroup exclusive size="small" value={typeFilter} onChange={(_, v) => setTypeFilter(v)} sx={segmentedSx(P, 'sm')}>
                  {['freeze', 'audio_loss', 'blackscreen'].map((t) => (
                    <ToggleButton key={t} value={t}>{t.replace('_', ' ')}</ToggleButton>
                  ))}
                </ToggleButtonGroup>
                {reasonFilter && (
                  <Chip size="small" label={`Reason: ${reasonFilter}`} onDelete={() => setReasonFilter(null)} />
                )}
              </>
            )}
            <ToggleButtonGroup
              size="small"
              exclusive
              value={queueView}
              onChange={(_, value: QueueView | null) => {
                if (value) setQueueView(value);
              }}
              sx={segmentedSx(P)}
            >
              <ToggleButton value="incidents">Incidents</ToggleButton>
              <ToggleButton value="scripts">Scripts</ToggleButton>
            </ToggleButtonGroup>
            <Button
              variant="outlined"
              color="error"
              size="small"
              startIcon={<ClearAllIcon />}
              onClick={() => handleClearQueue('all', 'All Queues')}
              disabled={!hasQueues}
              sx={{ textTransform: 'none' }}
            >
              Clear all
            </Button>
          </>
        }
      />

      {error && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {queueStatus && (
        <>
        <StatTiles
          large
          tiles={[
            { label: 'Analysed · 24h', value: selectedAnalysis?.analyzed ?? 0 },
            { label: 'Discarded', value: selectedAnalysis?.discarded ?? 0, color: (selectedAnalysis?.discarded ?? 0) > 0 ? P.warning : undefined, active: resultFilter === 'discarded', onClick: () => toggleResult('discarded'), title: 'Click to show only discarded, click again to clear' },
            { label: 'Kept', value: selectedAnalysis?.kept ?? 0, color: (selectedAnalysis?.kept ?? 0) > 0 ? P.success : undefined, active: resultFilter === 'kept', onClick: () => toggleResult('kept'), title: 'Click to show only kept, click again to clear' },
            { label: 'Pending', value: selectedQueue?.length ?? 0, color: (selectedQueue?.length ?? 0) > 0 ? P.accentText : undefined, active: resultFilter === 'pending', onClick: () => toggleResult('pending'), title: 'Click to show the pending queue, click again to clear' },
          ]}
        />
        </>
      )}

      {queueStatus && (
        <Grid container spacing={2}>
          {/* Last 24h Analyzed Table */}
          {resultFilter !== 'pending' && <Grid item xs={12}>
            <Card>
              <CardContent sx={{ py: 1.5 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Typography sx={{ fontSize: '1rem', fontWeight: 600 }}>
                      Analysed in the last 24h
                    </Typography>
                  </Box>
                </Box>

                <TableContainer component={Paper} variant="outlined">
                  <Table size="small" sx={{
                    tableLayout: 'fixed',
                    '& .MuiTableRow-root': { height: '40px' },
                    '& .MuiTableCell-root': {
                      px: 1,
                      py: 0.5,
                      fontSize: '0.875rem',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }
                  }}>
                    <TableHead>
                      <TableRow>
                        <TableCell sx={{ py: 1, width: queueView === 'scripts' ? undefined : 150 }}>
                          <strong>{queueView === 'scripts' ? 'Script' : 'Incident Type'}</strong>
                        </TableCell>
                        {queueView === 'incidents' && (
                          <TableCell sx={{ py: 1, width: 110 }}>
                            <strong>Host</strong>
                          </TableCell>
                        )}
                        <TableCell sx={{ py: 1, width: 90 }}>
                          <strong>Status</strong>
                        </TableCell>
                        <TableCell sx={{ py: 1, width: 190 }}>
                          <strong>Discard</strong>
                        </TableCell>
                        <TableCell sx={{ py: 1, width: 110 }}>
                          <strong>Analyzed By</strong>
                        </TableCell>
                        <TableCell sx={{ py: 1, width: 95 }}>
                          <strong>Comment</strong>
                        </TableCell>
                        <TableCell sx={{ py: 1, width: 190 }}>
                          <strong>Analyzed At</strong>
                        </TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {analysisItems.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={queueView === 'incidents' ? 7 : 6} sx={{ textAlign: 'center', py: 4 }}>
                            <Typography variant="body2" color="text.secondary">
                              No analyzed results for this queue in the last 24h.
                            </Typography>
                          </TableCell>
                        </TableRow>
                      ) : (
                        analysisItems.map((item) => (
                          <TableRow
                            key={item.id}
                            sx={{
                              '&:hover': { backgroundColor: `${P.hoverBg} !important` },
                              opacity: item.discard ? 0.5 : 1,
                            }}
                          >
                            <TableCell sx={{ py: 0.5 }}>
                              {queueView === 'scripts'
                                ? item.script_name || 'n/a'
                                : item.incident_type || 'n/a'}
                            </TableCell>
                            {queueView === 'incidents' && (
                              <TableCell sx={{ py: 0.5 }}>{item.host_name || '-'}</TableCell>
                            )}
                            <TableCell sx={{ py: 0.5 }}>
                              {queueView === 'scripts' ? (
                                <Tooltip title={item.success ? 'Pass' : 'Fail'}>
                                  {item.success
                                    ? <PassIcon color="success" fontSize="small" />
                                    : <FailIcon color="error" fontSize="small" />}
                                </Tooltip>
                              ) : (
                                <Tooltip title={item.status || 'unknown'}>
                                  <Typography variant="body2" sx={{
                                    color: item.status === 'resolved' ? P.success : P.warning,
                                    fontWeight: 'bold',
                                  }}>
                                    {item.status || '-'}
                                  </Typography>
                                </Tooltip>
                              )}
                            </TableCell>
                            <TableCell sx={{ py: 0.5 }}>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                                <Typography
                                  variant="body2"
                                  sx={{ fontWeight: 'bold', color: item.discard ? P.warning : P.success }}
                                >
                                  {item.discard ? 'Yes' : 'No'}
                                </Typography>
                                {item.discard && discardReason(item.discard_comment) && (
                                  <Tooltip title={item.discard_comment || ''}>
                                    <Chip
                                      size="small"
                                      label={discardReason(item.discard_comment)}
                                      variant={reasonFilter === discardReason(item.discard_comment) ? 'filled' : 'outlined'}
                                      onClick={() => setReasonFilter((cur) => (cur === discardReason(item.discard_comment) ? null : discardReason(item.discard_comment)))}
                                      sx={{ height: 20, fontSize: '0.7rem' }}
                                    />
                                  </Tooltip>
                                )}
                              </Box>
                            </TableCell>
                            <TableCell sx={{ py: 0.5 }}>
                              {getCheckTypeIcon(item)}
                            </TableCell>
                            <TableCell sx={{ py: 0.5 }}>
                              {item.discard_comment ? (
                                <Tooltip title="View full comment">
                                  <IconButton
                                    size="small"
                                    onClick={() => setCommentModal({ open: true, item })}
                                    sx={{ p: 0.25 }}
                                  >
                                    <CommentIcon fontSize="small" />
                                  </IconButton>
                                </Tooltip>
                              ) : (
                                <Typography variant="body2" color="text.disabled">-</Typography>
                              )}
                            </TableCell>
                            <TableCell sx={{ py: 0.5 }}>
                              {formatToLocalTime(item.updated_at || null)}
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </TableContainer>
              </CardContent>
            </Card>
          </Grid>}

          {/* Queue Card */}
          {selectedQueue && (
            <Grid item xs={12}>
              <Card>
                <CardContent sx={{ py: 1 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      {queueView === 'incidents' ? <IncidentIcon sx={{ color: P.accentText }} /> : <ScriptIcon sx={{ color: P.accentText }} />}
                      <Typography variant="h6" sx={{ my: 0 }}>
                        {queueView === 'incidents' ? 'Incidents Queue' : 'Scripts Queue'}
                      </Typography>
                      <Box component="span" sx={{ fontSize: '0.72rem', fontWeight: 600, px: 1, py: 0.25, borderRadius: 999, color: selectedQueue.length > 0 ? P.accentText : P.textSecondary, bgcolor: selectedQueue.length > 0 ? `${P.accent}26` : P.hoverBg }}>
                        {selectedQueue.length} pending
                      </Box>
                    </Box>
                    <Box sx={{ display: 'flex', alignItems: 'center' }}>
                      <IconButton
                        size="small"
                        onClick={() => handleClearQueue(queueView, queueView === 'incidents' ? 'Incidents' : 'Scripts')}
                        disabled={selectedQueue.length === 0 || queueView === 'incidents'}
                        title={queueView === 'incidents'
                          ? 'Incidents have no queue: pending = recent alerts the triage worker has not handled'
                          : `Clear ${queueView} queue`}
                      >
                        <ClearIcon />
                      </IconButton>
                      <IconButton size="small" onClick={() => toggleSection(queueView)}>
                        {expandedSections.has(queueView) ? <ExpandMoreIcon /> : <ExpandLessIcon />}
                      </IconButton>
                    </Box>
                  </Box>

                  <Collapse in={expandedSections.has(queueView)}>
                    <Box sx={{ mt: 1, p: 2 }}>
                      {selectedQueue.items && selectedQueue.items.length > 0 ? (
                        <Box>
                          <Typography variant="body2" sx={{ mb: 1, fontWeight: 'bold' }}>
                            Last {Math.min(50, selectedQueue.items.length)} pending items:
                          </Typography>
                          <Box sx={{ maxHeight: 280, overflowY: 'auto' }}>
                            {selectedQueue.items.slice(0, 50).map((item, index) => (
                              <Box key={index} sx={{ mb: 1, p: 1, borderRadius: 0.5, fontSize: '0.75rem' }}>
                                <Typography variant="caption" sx={{ fontWeight: 'bold' }}>
                                  ID: {item.id}
                                </Typography>
                                <Typography variant="caption" sx={{ ml: 2, color: 'text.secondary' }}>
                                  {new Date(item.created_at).toLocaleString()}
                                </Typography>
                              </Box>
                            ))}
                          </Box>
                        </Box>
                      ) : (
                        <Typography variant="body2" color="text.secondary">
                          {selectedQueue.length === 0 ? 'No items in queue' : 'Loading items...'}
                        </Typography>
                      )}
                    </Box>
                  </Collapse>
                </CardContent>
              </Card>
            </Grid>
          )}
        </Grid>
      )}

      {/* Clear Queue Dialog */}
      <StyledDialog
        open={clearDialog.open}
        onClose={cancelClearQueue}
        aria-labelledby="clear-queue-dialog-title"
        aria-describedby="clear-queue-dialog-description"
      >
        <DialogTitle id="clear-queue-dialog-title">Clear {clearDialog.queueName}?</DialogTitle>
        <DialogContent>
          <DialogContentText id="clear-queue-dialog-description">
            Are you sure you want to clear the {clearDialog.queueName.toLowerCase()}?
            This will permanently remove all pending tasks from the queue and cannot be undone.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={cancelClearQueue} color="primary">Cancel</Button>
          <Button onClick={confirmClearQueue} color="error" variant="contained">Clear Queue</Button>
        </DialogActions>
      </StyledDialog>

      {/* Comment Modal */}
      <StyledDialog
        open={commentModal.open}
        onClose={() => setCommentModal({ open: false, item: null })}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <CommentIcon />
            AI Analysis Comment
          </Box>
        </DialogTitle>
        <DialogContent>
          {commentModal.item && (
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1, color: 'text.secondary' }}>
                {queueView === 'scripts'
                  ? `Script: ${commentModal.item.script_name || 'n/a'}`
                  : `Incident: ${commentModal.item.incident_type || 'n/a'}`}
              </Typography>
              <Typography variant="subtitle2" sx={{ mb: 2, color: 'text.secondary' }}>
                Analysis Type: {analysisTypeLabel(commentModal.item.check_type)}
              </Typography>
              {getJev(commentModal.item) && <JevWhy jev={getJev(commentModal.item)!} />}
              <Typography variant="body1" sx={{ whiteSpace: 'pre-wrap' }}>
                {commentModal.item.discard_comment}
              </Typography>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCommentModal({ open: false, item: null })} color="primary">
            Close
          </Button>
        </DialogActions>
      </StyledDialog>
    </Box>
  );
};

export default AIQueueMonitor;
