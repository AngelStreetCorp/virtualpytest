/**
 * Script Running Overlay Component
 *
 * Displays real-time script execution progress from running.log data.
 * Polling is centralized in useRunningLog; this component receives logData as prop.
 *
 * Features:
 * - Shows previous/current/next steps
 * - Current step expandable to show actions/verifications
 * - Start time and estimated end time
 * - Show/hide toggle button
 */

import React, { useState, useEffect } from 'react';
import { Box, Typography, IconButton, CircularProgress } from '@mui/material';
import {
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
  Lock as LockIcon,
} from '@mui/icons-material';

import type { RunningLogData } from '../../hooks/rec/useRunningLog';
import { getTimeRemaining } from '../../utils/recUtils';
import { RunningScriptNameBadge } from './RunningScriptNameBadge';

interface ScriptRunningOverlayProps {
  logData: RunningLogData;
  scriptNameRightOffset?: number | string;
}

// Resolve the value shown next to a verification command, mirroring the Go To
// Node preview (Navigation_NodeGotoPanel): text verifications show their target
// text, image verifications show their reference path. Falls back to the
// verification_type when no params snapshot is available.
function getVerificationValue(verification: {
  verification_type: string;
  params?: Record<string, unknown>;
}): string | undefined {
  const params = verification.params || {};
  if (verification.verification_type === 'image') {
    return typeof params.image_path === 'string' ? params.image_path : undefined;
  }
  if (verification.verification_type === 'text') {
    return typeof params.text === 'string' ? params.text : undefined;
  }
  return undefined;
}

export const ScriptRunningOverlay: React.FC<ScriptRunningOverlayProps> = ({
  logData,
  scriptNameRightOffset = 8,
}) => {
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set());
  const [isCollapsed, setIsCollapsed] = useState(false);
  const scrollContainerRef = React.useRef<HTMLDivElement>(null);
  const stepRefs = React.useRef<Map<number, HTMLDivElement>>(new Map());
  // Step that was just expanded — drives the scroll-into-view effect below.
  const [recentlyExpanded, setRecentlyExpanded] = useState<number | null>(null);

  // Auto-scroll to most recent step when log data changes
  useEffect(() => {
    if (scrollContainerRef.current && logData) {
      scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
    }
  }, [logData?.current_step_number]);

  // When a step is expanded, scroll its details into view within the overlay's own
  // scroll container (the expanded actions/verifications otherwise stay clipped below
  // the fold). Scoped to the container so it never scrolls the modal/page.
  useEffect(() => {
    if (recentlyExpanded == null) return;
    const container = scrollContainerRef.current;
    const el = stepRefs.current.get(recentlyExpanded);
    if (!container || !el) return;

    const elTop = el.offsetTop;
    const elBottom = elTop + el.offsetHeight;
    const viewTop = container.scrollTop;
    const viewBottom = viewTop + container.clientHeight;

    if (elBottom > viewBottom) {
      // Show the bottom of the expanded step; if it is taller than the viewport,
      // align its top instead so the start of the details is visible.
      container.scrollTo({
        top: el.offsetHeight > container.clientHeight ? elTop : elBottom - container.clientHeight,
        behavior: 'smooth',
      });
    } else if (elTop < viewTop) {
      container.scrollTo({ top: elTop, behavior: 'smooth' });
    }
  }, [recentlyExpanded, expandedSteps]);

  const toggleStep = (stepNumber: number) => {
    const willExpand = !expandedSteps.has(stepNumber);
    setExpandedSteps((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(stepNumber)) {
        newSet.delete(stepNumber);
      } else {
        newSet.add(stepNumber);
      }
      return newSet;
    });
    if (willExpand) {
      setRecentlyExpanded(stepNumber);
    }
  };

  const allSteps: Array<{
    step_number: number;
    command: string;
    description?: string;
    actions?: unknown[];
    verifications?: unknown[];
    current_action_index?: number;
    current_verification_index?: number;
    isCurrent: boolean;
    isPrevious: boolean;
    isNext?: boolean;
  }> = [];

  if (logData.completed_steps && logData.completed_steps.length > 0) {
    logData.completed_steps.forEach((step) => {
      allSteps.push({ ...step, isCurrent: false, isPrevious: true });
    });
  } else if (logData.previous_step) {
    allSteps.push({ ...logData.previous_step, isCurrent: false, isPrevious: true });
  }

  if (logData.current_step) {
    allSteps.push({ ...logData.current_step, isCurrent: true, isPrevious: false });
  }

  if (logData.next_step) {
    allSteps.push({ ...logData.next_step, isCurrent: false, isPrevious: false, isNext: true });
  }

  const scriptInfoBanner = (
    <Box
      sx={{
        position: 'absolute',
        bottom: 8,
        right: scriptNameRightOffset,
        zIndex: 25,
        backgroundColor: 'rgba(0, 0, 0, 0.75)',
        borderRadius: 1,
        px: 1.5,
        py: 0.75,
        display: 'flex',
        alignItems: 'center',
        gap: 2,
        pointerEvents: 'none',
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
        <LockIcon sx={{ fontSize: '0.85rem', color: 'warning.main' }} />
        <RunningScriptNameBadge
          scriptName={logData.script_name}
          sx={{
            position: 'relative',
            right: 0,
            bottom: 0,
            maxWidth: 'none',
            px: 0,
            py: 0,
            backgroundColor: 'transparent',
          }}
          textSx={{ fontWeight: 'bold', fontSize: '0.75rem' }}
        />
      </Box>
      <Typography variant="caption" sx={{ color: '#aaa', fontSize: '0.7rem' }}>
        Started:{' '}
        {new Date(logData.start_time).toLocaleTimeString('en-US', {
          hour12: false,
          hour: '2-digit',
          minute: '2-digit',
        })}
      </Typography>
      {logData.estimated_end && (
        <Typography variant="caption" sx={{ color: '#aaa', fontSize: '0.7rem' }}>
          Est. End:{' '}
          {new Date(logData.estimated_end).toLocaleTimeString('en-US', {
            hour12: false,
            hour: '2-digit',
            minute: '2-digit',
          })}
          {getTimeRemaining(logData.estimated_end) && ` (${getTimeRemaining(logData.estimated_end)})`}
        </Typography>
      )}
    </Box>
  );

  if (isCollapsed) {
    return (
      <>
        {scriptInfoBanner}
        <Box
          sx={{
            position: 'absolute',
            bottom: 16,
            left: 16,
            zIndex: 30,
            backgroundColor: 'rgba(0, 0, 0, 0.85)',
            borderRadius: 1,
            p: 1,
            minWidth: 200,
            cursor: 'pointer',
          }}
          onClick={() => setIsCollapsed(false)}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <LockIcon sx={{ fontSize: '1rem', color: 'warning.main' }} />
            <Typography variant="caption" sx={{ color: '#fff', fontWeight: 'bold', flex: 1 }}>
              Step {logData.current_step_number}/{logData.total_steps}
            </Typography>
            {getTimeRemaining(logData.estimated_end) && (
              <Typography variant="caption" sx={{ color: '#aaa', fontSize: '0.7rem' }}>
                {getTimeRemaining(logData.estimated_end)}
              </Typography>
            )}
            <ExpandMoreIcon sx={{ fontSize: '1rem', color: '#aaa' }} />
          </Box>
        </Box>
      </>
    );
  }

  return (
    <>
      {scriptInfoBanner}
      <Box
        sx={{
          position: 'absolute',
          bottom: 16,
          left: 16,
          zIndex: 30,
          backgroundColor: 'rgba(0, 0, 0, 0.85)',
          borderRadius: 1,
          p: 1.5,
          minWidth: 320,
          maxWidth: 400,
          pointerEvents: 'auto',
        }}
      >
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            mb: 1,
            pb: 0.5,
            borderBottom: '1px solid rgba(255,255,255,0.1)',
          }}
        >
          <IconButton
            size="small"
            onClick={() => setIsCollapsed(true)}
            sx={{ color: '#aaa', p: 0.25 }}
            title="Minimize"
          >
            <ExpandLessIcon fontSize="small" />
          </IconButton>
        </Box>

        <Box
          ref={scrollContainerRef}
          sx={{
            position: 'relative',
            maxHeight: '160px',
            overflowY: 'auto',
            pr: 0.5,
            '&::-webkit-scrollbar': { width: '4px' },
            '&::-webkit-scrollbar-thumb': {
              backgroundColor: 'rgba(255,255,255,0.3)',
              borderRadius: '4px',
            },
          }}
        >
          {allSteps.map((step) => {
            const isExpanded = expandedSteps.has(step.step_number);
            const hasDetails =
              (step.actions && step.actions.length > 0) ||
              (step.verifications && step.verifications.length > 0);

            return (
              <Box
                key={step.step_number}
                ref={(el: HTMLDivElement | null) => {
                  if (el) stepRefs.current.set(step.step_number, el);
                  else stepRefs.current.delete(step.step_number);
                }}
                sx={{
                  mb: 1,
                  p: 0.75,
                  backgroundColor: step.isCurrent
                    ? 'rgba(33,150,243,0.2)'
                    : step.isPrevious
                      ? 'rgba(76,175,80,0.15)'
                      : 'rgba(158,158,158,0.1)',
                  borderRadius: 0.5,
                  border: step.isCurrent
                    ? '1px solid rgba(33,150,243,0.5)'
                    : step.isPrevious
                      ? '1px solid rgba(76,175,80,0.3)'
                      : '1px solid rgba(158,158,158,0.2)',
                  opacity: step.isPrevious ? 0.7 : step.isNext ? 0.6 : 1,
                }}
              >
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  {step.isCurrent ? (
                    <CircularProgress size={12} sx={{ color: '#2196f3' }} />
                  ) : step.isPrevious ? (
                    <Box
                      sx={{
                        width: 12,
                        height: 12,
                        borderRadius: '50%',
                        backgroundColor: '#4caf50',
                      }}
                    />
                  ) : (
                    <Box
                      sx={{
                        width: 12,
                        height: 12,
                        borderRadius: '50%',
                        backgroundColor: '#666',
                        border: '1px solid #888',
                      }}
                    />
                  )}
                  <Typography
                    variant="caption"
                    sx={{
                      color: step.isCurrent ? '#fff' : step.isPrevious ? '#fff' : '#aaa',
                      fontSize: '0.75rem',
                      fontWeight: 'bold',
                      flex: 1,
                    }}
                  >
                    {step.step_number}. {step.description || step.command}
                  </Typography>
                  {hasDetails && (
                    <IconButton
                      size="small"
                      onClick={() => toggleStep(step.step_number)}
                      sx={{ color: '#aaa', p: 0.25 }}
                    >
                      {isExpanded ? (
                        <ExpandLessIcon fontSize="small" />
                      ) : (
                        <ExpandMoreIcon fontSize="small" />
                      )}
                    </IconButton>
                  )}
                </Box>

                {isExpanded && hasDetails && (
                  <Box sx={{ ml: 1.5, mt: 0.75, borderLeft: '2px solid #444', pl: 0.75 }}>
                    {step.actions && step.actions.length > 0 && (
                      <Box sx={{ mb: 0.5 }}>
                        <Typography
                          variant="caption"
                          sx={{ color: '#2196f3', fontWeight: 'bold', fontSize: '0.7rem' }}
                        >
                          Actions ({step.current_action_index || 0}/{step.actions.length})
                        </Typography>
                        {(step.actions as Array<{ command: string; params?: Record<string, unknown> }>).map(
                          (action, idx) => {
                            const isCurrent = idx === (step.current_action_index || 0) - 1;
                            const isCompleted = idx < (step.current_action_index || 0) - 1;
                            return (
                              <Box
                                key={idx}
                                sx={{
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: 0.5,
                                  ml: 0.75,
                                  mt: 0.25,
                                }}
                              >
                                {isCurrent ? (
                                  <CircularProgress size={8} sx={{ color: '#2196f3' }} />
                                ) : isCompleted ? (
                                  <Box
                                    sx={{
                                      width: 8,
                                      height: 8,
                                      borderRadius: '50%',
                                      backgroundColor: '#4caf50',
                                    }}
                                  />
                                ) : (
                                  <Box
                                    sx={{
                                      width: 8,
                                      height: 8,
                                      borderRadius: '50%',
                                      backgroundColor: '#666',
                                    }}
                                  />
                                )}
                                <Typography
                                  variant="caption"
                                  sx={{
                                    color: isCurrent ? '#fff' : isCompleted ? '#4caf50' : '#aaa',
                                    fontFamily: 'monospace',
                                    fontSize: '0.65rem',
                                  }}
                                >
                                  {action.command}
                                  {action.params &&
                                    `(${Object.values(action.params)[0]})`}
                                </Typography>
                              </Box>
                            );
                          }
                        )}
                      </Box>
                    )}

                    {step.verifications && step.verifications.length > 0 && (
                      <Box>
                        <Typography
                          variant="caption"
                          sx={{ color: '#888', fontSize: '0.65rem' }}
                        >
                          Verifications (
                          {step.current_verification_index || 0}/{step.verifications.length})
                        </Typography>
                        {(step.verifications as Array<{
                          command: string;
                          verification_type: string;
                          params?: Record<string, unknown>;
                        }>).map(
                          (verification, idx) => {
                            const isCurrent =
                              idx === (step.current_verification_index || 0) - 1;
                            const isCompleted =
                              idx < (step.current_verification_index || 0) - 1;
                            const value = getVerificationValue(verification);
                            // Per-leg polling window (ms). 0 = single-frame check —
                            // the 'any can pass' gotcha, flagged red like the preview.
                            const timeoutMs = Number(
                              (verification.params as any)?.timeout ?? 0,
                            );
                            return (
                              <Box
                                key={idx}
                                sx={{
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: 0.5,
                                  ml: 0.75,
                                  mt: 0.25,
                                }}
                              >
                                {isCurrent ? (
                                  <CircularProgress size={8} sx={{ color: '#2196f3' }} />
                                ) : isCompleted ? (
                                  <Box
                                    sx={{
                                      width: 8,
                                      height: 8,
                                      borderRadius: '50%',
                                      backgroundColor: '#4caf50',
                                    }}
                                  />
                                ) : (
                                  <Box
                                    sx={{
                                      width: 8,
                                      height: 8,
                                      borderRadius: '50%',
                                      backgroundColor: '#666',
                                    }}
                                  />
                                )}
                                <Typography
                                  variant="caption"
                                  sx={{
                                    color: isCurrent ? '#fff' : isCompleted ? '#4caf50' : '#888',
                                    fontFamily: 'monospace',
                                    fontSize: '0.6rem',
                                  }}
                                >
                                  {verification.command}
                                  {value ? (
                                    <span style={{ color: '#64b5f6', marginLeft: '4px' }}>
                                      {value}
                                    </span>
                                  ) : (
                                    <span style={{ marginLeft: '4px' }}>
                                      ({verification.verification_type})
                                    </span>
                                  )}
                                  <span
                                    style={{
                                      color: timeoutMs > 0 ? '#888' : '#ef5350',
                                      marginLeft: '6px',
                                    }}
                                  >
                                    {timeoutMs}ms
                                  </span>
                                </Typography>
                              </Box>
                            );
                          }
                        )}
                      </Box>
                    )}
                  </Box>
                )}
              </Box>
            );
          })}
        </Box>
      </Box>
    </>
  );
};
