import React, { useState } from 'react';
import {
  Box,
  Typography,
  Paper,
  Chip,
  LinearProgress,
  TextField,
  Button,
  Collapse,
  IconButton,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import PlayCircleIcon from '@mui/icons-material/PlayCircle';
import SendIcon from '@mui/icons-material/Send';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { TestPromptExecution, TestPromptLiveEvent } from '../types/TestPrompt_Types';

interface TestPromptResultsProps {
  executions: TestPromptExecution[];
  onSubmitFeedback: (executionId: string, feedback: string) => Promise<void>;
  liveEventsByExecutionId?: Record<string, TestPromptLiveEvent[]>;
}

const statusIcon = (status: string) => {
  switch (status) {
    case 'passed': return <CheckCircleIcon fontSize="small" sx={{ color: 'success.main' }} />;
    case 'failed': return <ErrorIcon fontSize="small" sx={{ color: 'error.main' }} />;
    case 'running': return <PlayCircleIcon fontSize="small" sx={{ color: 'info.main' }} />;
    default: return <HourglassEmptyIcon fontSize="small" sx={{ color: 'text.disabled' }} />;
  }
};

const formatDuration = (ms?: number) => {
  if (!ms) return '';
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
};

const formatClockTime = (ms?: number) => {
  if (!ms) return '';
  return new Date(ms).toLocaleTimeString([], { hour12: false });
};

const FeedbackInput: React.FC<{ executionId: string; existingFeedback?: string; onSubmit: (id: string, feedback: string) => Promise<void> }> = ({
  executionId, existingFeedback, onSubmit
}) => {
  const [feedback, setFeedback] = useState(existingFeedback || '');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!feedback.trim()) return;
    setSubmitting(true);
    await onSubmit(executionId, feedback);
    setSubmitting(false);
  };

  if (existingFeedback) {
    return (
      <Typography variant="caption" sx={{ color: 'text.secondary', fontStyle: 'italic', mt: 0.5 }}>
        Feedback: {existingFeedback}
      </Typography>
    );
  }

  return (
    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mt: 1 }}>
      <TextField
        size="small"
        fullWidth
        placeholder="What should the AI do differently?"
        value={feedback}
        onChange={e => setFeedback(e.target.value)}
        sx={{ '& .MuiInputBase-root': { fontSize: '0.8rem' } }}
      />
      <Button
        size="small"
        variant="outlined"
        onClick={handleSubmit}
        disabled={!feedback.trim() || submitting}
        startIcon={<SendIcon sx={{ fontSize: 14 }} />}
        sx={{ whiteSpace: 'nowrap', fontSize: '0.75rem', py: 0.5 }}
      >
        Send
      </Button>
    </Box>
  );
};

export const TestPromptResults: React.FC<TestPromptResultsProps> = ({
  executions,
  onSubmitFeedback,
  liveEventsByExecutionId,
}) => {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (executions.length === 0) return null;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, p: 3, pt: 0 }}>
      <Typography variant="overline" sx={{ color: 'text.secondary', fontWeight: 600, letterSpacing: 1.2 }}>
        Results
      </Typography>

      {executions.map(exec => {
        const duration = exec.completedAt && exec.startedAt
          ? formatDuration(exec.completedAt - exec.startedAt)
          : exec.executionTimeMs
            ? formatDuration(exec.executionTimeMs)
            : null;
        const isExpanded = expandedId === exec.executionId;
        const isComplete = exec.status === 'passed' || exec.status === 'failed';
        const totalSteps = exec.steps.length;
        const completedSteps = exec.steps.filter(s => s.status === 'passed' || s.status === 'failed').length;
        const progress = totalSteps > 0 ? (completedSteps / totalSteps) * 100 : 0;

        return (
          <Paper
            key={exec.executionId}
            variant="outlined"
            sx={{
              borderColor: exec.status === 'failed' ? 'error.main' : exec.status === 'passed' ? 'success.main' : 'divider',
              overflow: 'hidden',
            }}
          >
            {/* Compact row: icon + status + version + duration + links + expand */}
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1,
                px: 1.5,
                py: 1,
                cursor: isComplete ? 'pointer' : 'default',
              }}
              onClick={() => isComplete && setExpandedId(isExpanded ? null : exec.executionId)}
            >
              {statusIcon(exec.status)}
              <Chip
                size="small"
                label={exec.status === 'running' ? 'Running' : exec.status.charAt(0).toUpperCase() + exec.status.slice(1)}
                color={exec.status === 'passed' ? 'success' : exec.status === 'failed' ? 'error' : exec.status === 'running' ? 'info' : 'default'}
                variant="outlined"
                sx={{ height: 20, fontSize: '0.7rem' }}
              />
              {exec.version && (
                <Chip
                  size="small"
                  label={`v${exec.version}`}
                  variant="outlined"
                  sx={{ height: 18, fontSize: '0.65rem' }}
                />
              )}
              {duration && (
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  {duration}
                </Typography>
              )}
              {exec.startedAt && exec.completedAt && (
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  Start: {formatClockTime(exec.startedAt)} | End: {formatClockTime(exec.completedAt)}
                </Typography>
              )}

              <Box sx={{ flex: 1 }} />

              {/* Report/Logs links inline */}
              {exec.reportUrl && (
                <Typography
                  variant="caption"
                  component="a"
                  href={exec.reportUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={e => e.stopPropagation()}
                  sx={{ color: 'primary.main', textDecoration: 'none', '&:hover': { textDecoration: 'underline' } }}
                >
                  Report
                </Typography>
              )}
              {exec.logsUrl && (
                <Typography
                  variant="caption"
                  component="a"
                  href={exec.logsUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={e => e.stopPropagation()}
                  sx={{ color: 'primary.main', textDecoration: 'none', '&:hover': { textDecoration: 'underline' } }}
                >
                  Logs
                </Typography>
              )}

              {isComplete && (
                <IconButton size="small" sx={{ p: 0.25 }}>
                  <ExpandMoreIcon sx={{ fontSize: 18, transform: isExpanded ? 'rotate(180deg)' : 'none', transition: '0.2s' }} />
                </IconButton>
              )}
            </Box>

            {/* Progress bar for running */}
            {exec.status === 'running' && (
              <LinearProgress variant="determinate" value={progress} sx={{ height: 2 }} />
            )}

            {/* Live log while running — streamed over Socket.io /agent namespace.
                 Shown inline during a run so the user sees progress as it happens.
                 After the run finishes the same buffered events stay available in
                 the Collapse below so the execution history isn't thrown away. */}
            {(() => {
              const events = (liveEventsByExecutionId && liveEventsByExecutionId[exec.executionId]) || [];
              if (events.length === 0 || (exec.status !== 'running' && exec.status !== 'error')) return null;
              return (
                <Box
                  sx={{
                    px: 1.5,
                    py: 0.75,
                    borderTop: '1px solid',
                    borderColor: 'divider',
                    maxHeight: 160,
                    overflowY: 'auto',
                    fontFamily: 'monospace',
                    fontSize: '0.7rem',
                    bgcolor: 'action.hover',
                  }}
                >
                  {events.slice(-30).map((ev) => (
                    <Box key={ev.id} sx={{ color: ev.type === 'error' ? 'error.main' : 'text.secondary', lineHeight: 1.4, whiteSpace: 'pre-wrap' }}>
                      [{ev.type}]{ev.toolName ? ` ${ev.toolName}` : ''} {ev.content}{ev.toolParams ? `\n  ${JSON.stringify(ev.toolParams, null, 0)}` : ''}
                    </Box>
                  ))}
                </Box>
              );
            })()}

            {/* Expanded: error + full event log + feedback */}
            <Collapse in={isExpanded}>
              <Box sx={{ px: 1.5, pb: 1.5 }}>
                {exec.error && (
                  <Typography variant="caption" sx={{ color: 'error.main', fontStyle: 'italic' }}>
                    {exec.error}
                  </Typography>
                )}
                {(() => {
                  const events = (liveEventsByExecutionId && liveEventsByExecutionId[exec.executionId]) || [];
                  if (events.length === 0) return null;
                  return (
                    <Box
                      sx={{
                        mt: 1,
                        p: 1,
                        border: '1px solid',
                        borderColor: 'divider',
                        borderRadius: 1,
                        maxHeight: 240,
                        overflowY: 'auto',
                        fontFamily: 'monospace',
                        fontSize: '0.7rem',
                        bgcolor: 'action.hover',
                      }}
                    >
                      <Typography variant="caption" sx={{ display: 'block', fontWeight: 600, mb: 0.5, color: 'text.secondary' }}>
                        Execution log ({events.length})
                      </Typography>
                      {events.map((ev) => (
                        <Box key={ev.id} sx={{ color: ev.type === 'error' ? 'error.main' : 'text.secondary', lineHeight: 1.4, whiteSpace: 'pre-wrap' }}>
                          [{ev.type}]{ev.toolName ? ` ${ev.toolName}` : ''} {ev.content}{ev.toolParams ? `\n  ${JSON.stringify(ev.toolParams, null, 0)}` : ''}
                        </Box>
                      ))}
                    </Box>
                  );
                })()}
                <FeedbackInput
                  executionId={exec.id || exec.executionId}
                  existingFeedback={exec.humanFeedback}
                  onSubmit={onSubmitFeedback}
                />
              </Box>
            </Collapse>
          </Paper>
        );
      })}
    </Box>
  );
};
