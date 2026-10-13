import React, { useState } from 'react';
import {
  Box,
  Typography,
  LinearProgress,
  TextField,
  Button,
  Collapse,
  IconButton,
  Tooltip,
} from '@mui/material';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import HighlightOffIcon from '@mui/icons-material/HighlightOff';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import TerminalIcon from '@mui/icons-material/Terminal';
import SendIcon from '@mui/icons-material/Send';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { TestPromptExecution, TestPromptLiveEvent } from '../types/TestPrompt_Types';
import { AIEditPreview } from '../../../../frontend/src/components/testcase/ai/AIEditPreview';
import type { AIGraphEditProposal } from '../../../../frontend/src/hooks/testcase/useAIGraphEdit';
import { useAgentChatPalette } from '../../../../frontend/src/constants/agentChatTheme';

interface TestPromptResultsProps {
  executions: TestPromptExecution[];
  onSubmitFeedback: (executionId: string, feedback: string) => Promise<void>;
  /** Save the graph a graph run generated as a testcase linked to the prompt. */
  onSaveAsTestcase: (executionId: string) => Promise<void>;
  liveEventsByExecutionId?: Record<string, TestPromptLiveEvent[]>;
  /** A passing exploration's proposed testcase (its steps + checks for the criteria). */
  explorePreview?: { executionId: string; proposal: AIGraphEditProposal } | null;
  buildingFromExploreId?: string | null;
  onProposeFromExplore?: (executionId: string) => Promise<void>;
  onApplyExplorePreview?: () => Promise<void>;
  onCancelExplorePreview?: () => void;
}

type Palette = ReturnType<typeof useAgentChatPalette>;

/** Status colour from the AI-pages palette: error = the run broke (infra), failed = the test failed. */
const statusColor = (status: string, P: Palette) => {
  switch (status) {
    case 'passed': return P.success;
    case 'failed': return P.error;
    case 'error': return P.warning;
    case 'running': return P.accentText;
    default: return P.textMuted;
  }
};

const statusIcon = (status: string, color: string) => {
  const sx = { fontSize: 18, color };
  switch (status) {
    case 'passed': return <CheckCircleOutlineIcon sx={sx} />;
    case 'failed': return <HighlightOffIcon sx={sx} />;
    case 'error': return <WarningAmberIcon sx={sx} />;
    case 'running': return <PlayCircleOutlineIcon sx={sx} />;
    default: return <HourglassEmptyIcon sx={sx} />;
  }
};

const statusLabel = (status: string) => status.charAt(0).toUpperCase() + status.slice(1);

const formatDuration = (ms?: number) => {
  if (!ms) return '';
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
};

/** "21:44:52" today, "3 Oct 21:44:52" on another day. */
const formatClockTime = (ms?: number) => {
  if (!ms) return '';
  const d = new Date(ms);
  const time = d.toLocaleTimeString([], { hour12: false });
  return d.toDateString() === new Date().toDateString()
    ? time
    : `${d.toLocaleDateString([], { day: 'numeric', month: 'short' })} ${time}`;
};

/** First line of a run's error, for the one-line preview under a collapsed row. */
const firstLine = (text?: string) => (text || '').split('\n').find(l => l.trim())?.trim() || '';

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

const DECISION_LABELS: Record<string, string> = {
  app_failure: 'the app fails the test',
  stale_test: 'the saved test is out of date',
  infra_retry: 'a device or network glitch',
};
const ACTION_LABELS: Record<string, string> = {
  report_failure: 'reported as failed',
  retry: 'retried once',
  explore: 'explored',
};

/** "Jev: the app fails the test (66%; out of date 27%, glitch 7%) → explored (shadow: …)" */
const decisionText = (d: NonNullable<TestPromptExecution['decision']>) => {
  if (!d.success) return `No decision (${d.error || 'decision model unavailable'}) → ${ACTION_LABELS[d.action || 'explore']}`;
  const probs = Object.entries(d.probabilities || {})
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${k} ${Math.round(v * 100)}%`)
    .join(', ');
  const pick = DECISION_LABELS[d.choice || ''] || d.choice;
  const shadow = d.gated ? '' : ' (shadow: Auto always explores for now, the pick is logged to measure it)';
  return `Jev: ${pick} — ${probs}; confidence ${Math.round((d.confidence || 0) * 100)}% → ${ACTION_LABELS[d.action || 'explore']}${shadow}`;
};

/** What the run ran and how it ended: inputs, device, graph, the agent's verdict. */
const RunDetails: React.FC<{ exec: TestPromptExecution }> = ({ exec }) => {
  const rows: Array<[string, React.ReactNode]> = [];
  if (exec.ranUserinterface) rows.push(['Userinterface', exec.ranUserinterface]);
  if (exec.ranTarget) rows.push(['Target', exec.ranTarget]);
  if (exec.ranPrompt) rows.push(['Prompt', exec.ranPrompt]);
  if (exec.ranCriteria) rows.push(['Criteria', exec.ranCriteria]);
  if (exec.hostName) rows.push(['Device', `${exec.hostName} · ${exec.deviceId || ''}`]);
  if (exec.mode === 'graph') {
    if (exec.replayedTestcase) rows.push(['Graph', `Replayed testcase ${exec.replayedTestcase.name || exec.replayedTestcase.id}`]);
    else if (exec.generated) rows.push(['Graph', 'Generated from the prompt for this run']);
  }
  if (exec.autoFrom) rows.push(['Auto', 'Explored because the saved test failed']);
  if (exec.retryOf) rows.push(['Auto', 'Retry of the failed run']);
  if (exec.decision) rows.push(['Decision', decisionText(exec.decision)]);
  if (exec.outcome?.follow_up_mode) {
    rows.push(['Then', `${exec.outcome.follow_up_mode === 'graph' ? 'Retried' : 'Explored'}: ${exec.outcome.follow_up_status || 'running'}`]);
  }
  if (rows.length === 0 && !exec.verdict) {
    return (
      <Typography variant="caption" sx={{ color: 'text.disabled', display: 'block' }}>
        No run details were recorded for this run.
      </Typography>
    );
  }
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', columnGap: 1.5, rowGap: 0.25, mb: 0.5 }}>
      {rows.map(([label, value]) => (
        <React.Fragment key={label}>
          <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 600 }}>{label}</Typography>
          <Typography variant="caption" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{value}</Typography>
        </React.Fragment>
      ))}
      {exec.verdict && (
        <>
          <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 600 }}>Verdict</Typography>
          <Box sx={{ fontFamily: 'monospace', fontSize: '0.7rem', whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 240, overflowY: 'auto', p: 1, bgcolor: 'action.hover', borderRadius: 1 }}>
            {exec.verdict}
          </Box>
        </>
      )}
    </Box>
  );
};

export const TestPromptResults: React.FC<TestPromptResultsProps> = ({
  executions,
  onSubmitFeedback,
  onSaveAsTestcase,
  liveEventsByExecutionId,
  explorePreview,
  buildingFromExploreId,
  onProposeFromExplore,
  onApplyExplorePreview,
  onCancelExplorePreview,
}) => {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const P = useAgentChatPalette();

  if (executions.length === 0) return null;

  // Summary over finished runs (newest first in `executions`); history strip reads oldest → newest.
  const finished = executions.filter(e => e.status === 'passed' || e.status === 'failed' || e.status === 'error');
  const passedCount = finished.filter(e => e.status === 'passed').length;
  const history = finished.slice(0, 20).reverse();

  const linkSx = { p: 0.5, color: P.textSecondary, '&:hover': { color: P.accentText, bgcolor: P.hoverBg } };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, px: 0.5 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600, color: P.textPrimary }}>Results</Typography>
        {finished.length > 0 && (
          <>
            <Typography variant="caption" sx={{ color: P.textSecondary }}>
              {passedCount} of {finished.length} passed · {Math.round((passedCount / finished.length) * 100)}%
            </Typography>
            <Box sx={{ display: 'flex', gap: '3px' }}>
              {history.map(e => (
                <Tooltip key={e.executionId} title={`${statusLabel(e.status)} · ${formatClockTime(e.startedAt)}`}>
                  <Box sx={{ width: 8, height: 8, borderRadius: '2px', bgcolor: statusColor(e.status, P) }} />
                </Tooltip>
              ))}
            </Box>
          </>
        )}
      </Box>

      <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 2, overflow: 'hidden', bgcolor: P.surface }}>
      {executions.map((exec, index) => {
        const duration = exec.completedAt && exec.startedAt
          ? formatDuration(exec.completedAt - exec.startedAt)
          : exec.executionTimeMs
            ? formatDuration(exec.executionTimeMs)
            : null;
        const isExpanded = expandedId === exec.executionId;
        // An error is complete too: expanding it shows what ran and why it stopped.
        const isComplete = exec.status === 'passed' || exec.status === 'failed' || exec.status === 'error';
        const totalSteps = exec.steps.length;
        const completedSteps = exec.steps.filter(s => s.status === 'passed' || s.status === 'failed').length;
        const progress = totalSteps > 0 ? (completedSteps / totalSteps) * 100 : 0;
        const color = statusColor(exec.status, P);
        const errorPreview = !isExpanded && (exec.status === 'failed' || exec.status === 'error') ? firstLine(exec.error) : '';
        const meta = [
          exec.mode ? `${exec.auto ? 'Auto · ' : ''}${exec.mode === 'graph' ? 'Graph' : 'Explore'}` : '',
          exec.version ? (exec.edited ? `v${exec.version} · edited` : `v${exec.version}`) : '',
        ].filter(Boolean).join(' · ');

        return (
          <Box
            key={exec.executionId}
            sx={{ borderTop: index === 0 ? 'none' : `1px solid ${P.borderColor}` }}
          >
            {/* Row: status · when · mode/version · duration · actions */}
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1.25,
                px: 1.5,
                py: 0.9,
                cursor: isComplete ? 'pointer' : 'default',
                bgcolor: isExpanded ? P.hoverBg : 'transparent',
                '&:hover': { bgcolor: P.hoverBg },
              }}
              onClick={() => isComplete && setExpandedId(isExpanded ? null : exec.executionId)}
            >
              {statusIcon(exec.status, color)}
              <Typography sx={{ fontSize: '0.8rem', fontWeight: 600, color, minWidth: 56 }}>
                {statusLabel(exec.status)}
              </Typography>
              <Typography sx={{ fontSize: '0.8rem', color: P.textPrimary, whiteSpace: 'nowrap' }}>
                {formatClockTime(exec.startedAt)}
              </Typography>
              {meta && (
                <Typography
                  noWrap
                  title={exec.edited ? 'The form differed from the saved version when this ran — expand to see what ran' : undefined}
                  sx={{ fontSize: '0.75rem', color: P.textMuted, minWidth: 0 }}
                >
                  {meta}
                </Typography>
              )}

              <Box sx={{ flex: 1 }} />

              {exec.mode === 'explore' && exec.status === 'passed' && exec.hasTrace && onProposeFromExplore && (
                exec.savedTestcaseId ? (
                  <Typography sx={{ fontSize: '0.72rem', color: P.success, whiteSpace: 'nowrap' }}>Saved as testcase</Typography>
                ) : (
                  <Button
                    size="small"
                    variant="outlined"
                    disabled={buildingFromExploreId === exec.executionId || explorePreview?.executionId === exec.executionId}
                    onClick={e => { e.stopPropagation(); onProposeFromExplore(exec.executionId); }}
                    title="Turn the steps this exploration took, plus checks for the acceptance criteria, into a testcase linked to the prompt"
                    sx={{ fontSize: 11, py: 0, px: 1, minHeight: 24, textTransform: 'none', borderColor: P.accent, color: P.accentText, '&:hover': { borderColor: P.accent, bgcolor: `${P.accent}1a` } }}
                  >
                    {buildingFromExploreId === exec.executionId ? 'Building…' : 'Save as testcase'}
                  </Button>
                )
              )}
              {exec.mode === 'graph' && exec.generatedGraph && exec.status === 'passed' && (
                exec.savedTestcaseId ? (
                  <Typography sx={{ fontSize: '0.72rem', color: P.success, whiteSpace: 'nowrap' }}>Saved as testcase</Typography>
                ) : (
                  <Button
                    size="small"
                    variant="outlined"
                    onClick={e => { e.stopPropagation(); onSaveAsTestcase(exec.executionId); }}
                    title="Save this graph as a testcase linked to the prompt; Run graph then replays it without an AI call"
                    sx={{ fontSize: 11, py: 0, px: 1, minHeight: 24, textTransform: 'none', borderColor: P.accent, color: P.accentText, '&:hover': { borderColor: P.accent, bgcolor: `${P.accent}1a` } }}
                  >
                    Save as testcase
                  </Button>
                )
              )}

              {duration && (
                <Typography sx={{ fontSize: '0.75rem', color: P.textSecondary, minWidth: 40, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                  {duration}
                </Typography>
              )}

              <Box sx={{ display: 'flex', alignItems: 'center', minWidth: 52, justifyContent: 'flex-end' }}>
                {exec.reportUrl && (
                  <Tooltip title="Report">
                    <IconButton size="small" component="a" href={exec.reportUrl} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()} aria-label="Report" sx={linkSx}>
                      <DescriptionOutlinedIcon sx={{ fontSize: 17 }} />
                    </IconButton>
                  </Tooltip>
                )}
                {exec.logsUrl && (
                  <Tooltip title="Logs">
                    <IconButton size="small" component="a" href={exec.logsUrl} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()} aria-label="Logs" sx={linkSx}>
                      <TerminalIcon sx={{ fontSize: 17 }} />
                    </IconButton>
                  </Tooltip>
                )}
              </Box>

              <ExpandMoreIcon sx={{ fontSize: 18, color: isComplete ? P.textMuted : 'transparent', transform: isExpanded ? 'rotate(180deg)' : 'none', transition: '0.2s' }} />
            </Box>

            {/* Why it failed, without opening the report */}
            {errorPreview && (
              <Typography
                noWrap
                onClick={() => setExpandedId(exec.executionId)}
                title={exec.error}
                sx={{ px: 1.5, pl: 5.75, py: 0.6, fontSize: '0.75rem', color, bgcolor: `${color}14`, cursor: 'pointer' }}
              >
                {errorPreview}
              </Typography>
            )}

            {explorePreview?.executionId === exec.executionId && onApplyExplorePreview && onCancelExplorePreview && (
              <Box sx={{ px: 1.5, pb: 1.5 }} onClick={e => e.stopPropagation()}>
                <AIEditPreview proposal={explorePreview.proposal} onApply={onApplyExplorePreview} onCancel={onCancelExplorePreview} />
              </Box>
            )}

            {/* Progress bar for running */}
            {exec.status === 'running' && (
              <LinearProgress variant="determinate" value={progress} sx={{ height: 2, bgcolor: P.hoverBg, '& .MuiLinearProgress-bar': { bgcolor: P.accent } }} />
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
              <Box sx={{ px: 1.5, pt: 1, pb: 1.5, pl: 5.75, bgcolor: P.hoverBg }}>
                <RunDetails exec={exec} />
                {exec.error && (
                  <Typography variant="caption" component="div" sx={{ color: 'error.main', fontStyle: 'italic', whiteSpace: 'pre-wrap', mt: 0.5 }}>
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
          </Box>
        );
      })}
      </Box>
    </Box>
  );
};
