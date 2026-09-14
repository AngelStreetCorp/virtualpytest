import {
  KeyboardArrowDown as ExpandMoreIcon,
  KeyboardArrowRight as ExpandLessIcon,
  Error as IncidentIcon,
  Assessment as ScriptIcon,
  Clear as ClearIcon,
  DeleteSweep as ClearAllIcon,
  CheckCircle as PassIcon,
  Error as FailIcon,
  SmartToy as AiIcon,
  Person as ManualIcon,
  Comment as CommentIcon,
} from '@mui/icons-material';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Chip,
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
import React, { useState, useEffect } from 'react';

import { StyledDialog } from '../components/common/StyledDialog';
import { useAIQueue, AIQueueStatus, LastAnalyzedResult } from '../hooks/pages/useAIQueue';
import { formatToLocalTime } from '../utils/dateUtils';
import { getCached, setCached } from '../utils/pageCache';

type QueueView = 'incidents' | 'scripts';

const AIQueueMonitor: React.FC = () => {
  const { getQueueStatus, clearQueues } = useAIQueue();
  const [queueStatus, setQueueStatus] = useState<AIQueueStatus | null>(() => getCached<AIQueueStatus>('ai-queue'));
  const [loading, setLoading] = useState(!getCached<AIQueueStatus>('ai-queue'));
  const [error, setError] = useState<string | null>(null);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set());
  const [queueView, setQueueView] = useState<QueueView>('incidents');
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
  const analysisItems = selectedAnalysis?.items || [];

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
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1, gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="h4">AI Queue Monitor</Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={queueView}
            onChange={(_, value: QueueView | null) => {
              if (value) setQueueView(value);
            }}
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
          >
            Clear All
          </Button>
        </Box>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {queueStatus && (
        <Grid container spacing={2}>
          {/* Last 24h Analyzed Table */}
          <Grid item xs={12}>
            <Card>
              <CardContent sx={{ py: 1.5 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                      Last 24h Analyzed
                    </Typography>
                    <Chip label={`${selectedAnalysis?.analyzed ?? 0} analyzed`} color="primary" size="small" />
                    <Chip label={`${selectedAnalysis?.discarded ?? 0} discarded`} color="warning" size="small" />
                    <Chip label={`${selectedAnalysis?.kept ?? 0} kept`} color="success" size="small" />
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
                        <TableCell sx={{ py: 1 }}>
                          <strong>{queueView === 'scripts' ? 'Script' : 'Incident Type'}</strong>
                        </TableCell>
                        {queueView === 'incidents' && (
                          <TableCell sx={{ py: 1, width: 100 }}>
                            <strong>Host</strong>
                          </TableCell>
                        )}
                        <TableCell sx={{ py: 1, width: 60 }}>
                          <strong>Status</strong>
                        </TableCell>
                        <TableCell sx={{ py: 1, width: 70 }}>
                          <strong>Discard</strong>
                        </TableCell>
                        <TableCell sx={{ py: 1, width: 80 }}>
                          <strong>Analyzed By</strong>
                        </TableCell>
                        <TableCell sx={{ py: 1, width: 60 }}>
                          <strong>Comment</strong>
                        </TableCell>
                        <TableCell sx={{ py: 1, width: 140 }}>
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
                              '&:hover': { backgroundColor: 'rgba(0, 0, 0, 0.04) !important' },
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
                                    color: item.status === 'resolved' ? 'success.main' : 'warning.main',
                                    fontWeight: 'bold',
                                  }}>
                                    {item.status || '-'}
                                  </Typography>
                                </Tooltip>
                              )}
                            </TableCell>
                            <TableCell sx={{ py: 0.5 }}>
                              <Typography
                                variant="body2"
                                sx={{
                                  fontWeight: 'bold',
                                  color: item.discard ? 'error.main' : 'success.main',
                                }}
                              >
                                {item.discard ? 'YES' : 'NO'}
                              </Typography>
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
          </Grid>

          {/* Queue Card */}
          {selectedQueue && (
            <Grid item xs={12}>
              <Card>
                <CardContent sx={{ py: 1 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      {queueView === 'incidents' ? <IncidentIcon color="error" /> : <ScriptIcon color="primary" />}
                      <Typography variant="h6" sx={{ my: 0 }}>
                        {queueView === 'incidents' ? 'Incidents Queue' : 'Scripts Queue'}
                      </Typography>
                      <Chip
                        label={`${selectedQueue.length} pending`}
                        color={selectedQueue.length > 0 ? 'warning' : 'default'}
                        size="small"
                      />
                    </Box>
                    <Box sx={{ display: 'flex', alignItems: 'center' }}>
                      <IconButton
                        size="small"
                        onClick={() => handleClearQueue(queueView, queueView === 'incidents' ? 'Incidents' : 'Scripts')}
                        disabled={selectedQueue.length === 0}
                        title={`Clear ${queueView} queue`}
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
                Analysis Type: {
                  (commentModal.item.check_type === 'ai' || commentModal.item.check_type === 'ai_agent')
                    ? 'AI Agent Analysis'
                    : commentModal.item.check_type === 'ai_and_human'
                      ? 'AI & Human Review'
                      : commentModal.item.check_type === 'ai_strategy_skip'
                        ? 'Strategy Skip'
                        : 'Manual Review'
                }
              </Typography>
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
