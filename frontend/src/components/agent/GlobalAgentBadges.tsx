/**
 * Global Agent Badges
 * 
 * Floating badge system that displays all active agent tasks.
 * - Manual triggers stack on TOP
 * - Auto triggers stack BELOW
 * - Badges show agent nickname + task status
 * - Click to expand task details
 */

import React, { useState } from 'react';
import { Box, Paper, Typography, IconButton, Collapse, Chip, LinearProgress, Fade, Tooltip } from '@mui/material';
import { Close, ExpandLess, ExpandMore, ThumbUp, ThumbDown, CheckCircle, Error as ErrorIcon, Schedule, OpenInNew } from '@mui/icons-material';
import { useAgentActivity, AgentTask } from '../../contexts/AgentActivityContext';
import { useNavigate } from 'react-router-dom';

// Styles
const BADGE_WIDTH = 380;
const COLORS = {
  bg: '#1a1a1a',
  bgHover: '#242424',
  border: 'rgba(212, 175, 55, 0.4)', // Gold tint border by default
  borderActive: '#d4af37',
  text: '#f0f0f0',
  textMuted: '#888',
  accent: '#d4af37',
  success: '#22c55e',
  error: '#ef4444',
};

const AGENT_DISPLAY_NAMES: Record<string, string> = {
  assistant: 'Atlas',
};

interface AgentBadgeProps {
  agentId: string;
  tasks: AgentTask[];
  isExpanded: boolean;
  onToggle: () => void;
  onDismiss: (taskId: string) => void;
  onFeedback: (taskId: string, rating: number, comment?: string) => void;
}

const AgentBadge: React.FC<AgentBadgeProps> = ({ 
  agentId, 
  tasks, 
  isExpanded, 
  onToggle, 
  onDismiss,
  onFeedback 
}) => {
  const navigate = useNavigate();
  const [localFeedback, setLocalFeedback] = useState<{ rating: number; animating: boolean } | null>(null);
  
  const displayName = AGENT_DISPLAY_NAMES[agentId] || agentId;
  const runningTasks = tasks.filter(t => t.status === 'running');
  const completedTasks = tasks.filter(t => t.status === 'completed');
  const failedTasks = tasks.filter(t => t.status === 'failed');
  
  // Only show the latest task — history is in Agent Chat page
  const currentTask = tasks[tasks.length - 1] || tasks[0];
  const isComplete = currentTask?.status === 'completed';
  const isFailed = currentTask?.status === 'failed';
  const isManual = currentTask?.triggerType === 'manual';
  
  // Check if feedback has been given (either from task or local state)
  const feedbackGiven = currentTask?.feedback || localFeedback;
  const isPositiveFeedback = feedbackGiven && (currentTask?.feedback?.rating ?? localFeedback?.rating ?? 0) > 3;
  const isNegativeFeedback = feedbackGiven && (currentTask?.feedback?.rating ?? localFeedback?.rating ?? 0) <= 3;

  const getStatusIcon = () => {
    if (failedTasks.length > 0) return <ErrorIcon sx={{ fontSize: 14, color: COLORS.error }} />;
    if (completedTasks.length > 0 && runningTasks.length === 0) return <CheckCircle sx={{ fontSize: 14, color: COLORS.success }} />;
    return <Schedule sx={{ fontSize: 14, color: COLORS.accent, animation: 'pulse 1.5s infinite' }} />;
  };

  // Progress dots removed — the pulsing status icon in the header is sufficient.

  const handleFeedbackClick = (taskId: string, rating: number) => {
    // Set local feedback state with animation
    setLocalFeedback({ rating, animating: true });
    
    // Trigger animation end after 300ms
    setTimeout(() => {
      setLocalFeedback(prev => prev ? { ...prev, animating: false } : null);
    }, 300);
    
    // Call the actual feedback handler
    onFeedback(taskId, rating);
  };

  // Determine border color based on feedback
  const getBorderColor = () => {
    if (isPositiveFeedback) return COLORS.success;
    if (isNegativeFeedback) return COLORS.error;
    if (isExpanded) return COLORS.borderActive;
    return COLORS.border;
  };

  const getBoxShadow = () => {
    if (isPositiveFeedback) return '0 4px 24px rgba(34, 197, 94, 0.3)';
    if (isNegativeFeedback) return '0 4px 24px rgba(239, 68, 68, 0.3)';
    if (isExpanded) return '0 4px 24px rgba(212, 175, 55, 0.25)';
    return '0 4px 20px rgba(0, 0, 0, 0.4)';
  };

  const handleOpenInAgentChat = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isExpanded) {
      onToggle();
    }
    navigate('/ai-agent');
  };

  return (
    <Paper
      elevation={8}
      sx={{
        width: BADGE_WIDTH,
        bgcolor: COLORS.bg,
        border: `1px solid ${getBorderColor()}`,
        borderRadius: 2,
        overflow: 'hidden',
        transition: 'all 0.3s ease',
        boxShadow: getBoxShadow(),
        transform: localFeedback?.animating ? 'scale(1.02)' : 'scale(1)',
        '&:hover': { 
          borderColor: feedbackGiven ? getBorderColor() : COLORS.borderActive,
          boxShadow: feedbackGiven ? getBoxShadow() : '0 4px 24px rgba(212, 175, 55, 0.2)',
        },
      }}
    >
      {/* Header - Always visible */}
      <Box
        sx={{
          py: 0.75,
          px: 1,
          display: 'flex',
          alignItems: 'center',
          gap: 0.75,
          '&:hover': { bgcolor: COLORS.bgHover },
        }}
      >
        <Box 
          onClick={onToggle}
          sx={{ flex: 1, minWidth: 0, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 0.75 }}
        >
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
              <Typography sx={{ fontWeight: 600, color: COLORS.text, fontSize: '0.85rem' }}>
                {displayName}
              </Typography>
              {false && tasks.length > 1 && (
                <Chip label={tasks.length} size="small" sx={{ height: 16, fontSize: '0.65rem', bgcolor: '#333', color: COLORS.textMuted }} />
              )}
              {getStatusIcon()}
            </Box>
            <Typography sx={{ color: COLORS.textMuted, fontSize: '0.7rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {currentTask?.prompt || 'Processing...'}
            </Typography>
          </Box>
          {/* Progress dots removed from collapsed view — the pulsing status icon is
              sufficient as a loading indicator and the dots added visual noise. */}
        <IconButton size="small" sx={{ color: COLORS.textMuted, p: 0.25 }} component="span">
            {isExpanded ? <ExpandMore sx={{ fontSize: 18 }} /> : <ExpandLess sx={{ fontSize: 18 }} />}
          </IconButton>
        </Box>
        <Tooltip title="Open in Agent Chat">
          <IconButton
            size="small"
            onClick={handleOpenInAgentChat}
            sx={{
              color: COLORS.accent,
              p: 0.25,
              opacity: 0.75,
              '&:hover': { opacity: 1, color: COLORS.text }
            }}
          >
            <OpenInNew sx={{ fontSize: 14 }} />
          </IconButton>
        </Tooltip>
        {/* Discreet close button - always visible */}
        <IconButton 
          size="small" 
          onClick={(e) => {
            e.stopPropagation();
            if (currentTask) onDismiss(currentTask.id);
          }}
          sx={{ 
            color: COLORS.textMuted, 
            p: 0.25, 
            opacity: 0.5,
            '&:hover': { opacity: 1, color: COLORS.text } 
          }}
        >
          <Close sx={{ fontSize: 14 }} />
        </IconButton>
      </Box>

      {/* Progress bar for running tasks */}
      {runningTasks.length > 0 && !isExpanded && (
        <LinearProgress 
          variant="indeterminate" 
          sx={{ 
            height: 2, 
            bgcolor: '#333', 
            '& .MuiLinearProgress-bar': { bgcolor: COLORS.accent } 
          }} 
        />
      )}

      {/* Expanded Content */}
      <Collapse in={isExpanded}>
        <Box sx={{ borderTop: `1px solid ${COLORS.border}` }}>
          {/* No tabs — only show latest task. History is in Agent Chat page. */}

          {/* Response only — no tools, no summary, just the answer */}
          {currentTask && (
            <Box sx={{ px: 1, py: 0.75 }}>
              {/* Running indicator */}
              {!isComplete && !isFailed && (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                  <LinearProgress sx={{ flex: 1, height: 2, borderRadius: 1, bgcolor: '#333', '& .MuiLinearProgress-bar': { bgcolor: COLORS.accent } }} />
                </Box>
              )}

              {/* Response text */}
              {isComplete && currentTask.response && (
                <Box
                  onClick={onToggle}
                  sx={{
                    maxHeight: 300,
                    overflowY: 'auto',
                    cursor: 'pointer',
                    scrollbarWidth: 'thin',
                    scrollbarColor: `${COLORS.border} transparent`,
                    '&::-webkit-scrollbar': { width: 4 },
                    '&::-webkit-scrollbar-thumb': { background: COLORS.border, borderRadius: 2 },
                  }}
                >
                  <Typography sx={{
                    fontSize: '0.75rem',
                    color: COLORS.text,
                    lineHeight: 1.5,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}>
                    {currentTask.response}
                  </Typography>
                </Box>
              )}

              {/* Error message */}
              {isFailed && currentTask.error && (
                <Box sx={{ px: 0.75, py: 0.5, mb: 0.75, bgcolor: 'rgba(239, 68, 68, 0.1)', borderRadius: 1, border: '1px solid rgba(239, 68, 68, 0.3)' }}>
                  <Typography sx={{ fontSize: '0.7rem', color: COLORS.error }}>
                    {currentTask.error}
                  </Typography>
                </Box>
              )}

              {/* Feedback + Actions Row */}
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, pt: 0.5 }}>
                {isComplete && isManual && (
                  <>
                    <Typography sx={{ fontSize: '0.7rem', color: feedbackGiven ? (isPositiveFeedback ? COLORS.success : COLORS.error) : COLORS.textMuted }}>
                      {feedbackGiven ? (isPositiveFeedback ? '👍 Helpful' : '👎 Not helpful') : 'Helpful?'}
                    </Typography>
                    <IconButton 
                      size="small" 
                      onClick={() => handleFeedbackClick(currentTask.id, 5)} 
                      disabled={!!feedbackGiven}
                      sx={{ 
                        p: 0.25, 
                        color: isPositiveFeedback ? COLORS.success : COLORS.textMuted,
                        bgcolor: isPositiveFeedback ? 'rgba(34, 197, 94, 0.15)' : 'transparent',
                        '&:hover': { color: feedbackGiven ? undefined : COLORS.success, bgcolor: feedbackGiven ? undefined : 'rgba(34, 197, 94, 0.1)' },
                        '&.Mui-disabled': { color: isPositiveFeedback ? COLORS.success : COLORS.textMuted, opacity: 1 },
                      }}
                    >
                      <ThumbUp sx={{ fontSize: 14 }} />
                    </IconButton>
                    <IconButton 
                      size="small" 
                      onClick={() => handleFeedbackClick(currentTask.id, 1)} 
                      disabled={!!feedbackGiven}
                      sx={{ 
                        p: 0.25, 
                        color: isNegativeFeedback ? COLORS.error : COLORS.textMuted,
                        bgcolor: isNegativeFeedback ? 'rgba(239, 68, 68, 0.15)' : 'transparent',
                        '&:hover': { color: feedbackGiven ? undefined : COLORS.error, bgcolor: feedbackGiven ? undefined : 'rgba(239, 68, 68, 0.1)' },
                        '&.Mui-disabled': { color: isNegativeFeedback ? COLORS.error : COLORS.textMuted, opacity: 1 },
                      }}
                    >
                      <ThumbDown sx={{ fontSize: 14 }} />
                    </IconButton>
                  </>
                )}
                <Box sx={{ flex: 1 }} />
              </Box>
            </Box>
          )}
        </Box>
      </Collapse>
    </Paper>
  );
};

// Main Component
export const GlobalAgentBadges: React.FC = () => {
  const { 
    activities, 
    toggleExpanded, 
    dismissTask, 
    submitFeedback,
    getManualTasks,
    getAutoTasks,
  } = useAgentActivity();

  const manualTasks = getManualTasks();
  const autoTasks = getAutoTasks();
  
  // Group by agent
  const manualAgents = new Set(manualTasks.map(t => t.agentId));
  const autoAgents = new Set(autoTasks.filter(t => !manualAgents.has(t.agentId)).map(t => t.agentId));

  if (Object.keys(activities).length === 0) {
    console.log('🎯 GlobalAgentBadges: No activities to display');
    return null;
  }
  
  console.log('🎯 GlobalAgentBadges: Rendering badges for', Object.keys(activities).length, 'agents');

  return (
    <Box
      sx={{
        position: 'fixed',
        bottom: 24,
        right: 24,
        zIndex: 1300, // Below modals (1400+) but above most content
        display: 'flex',
        flexDirection: 'column',
        gap: 1,
        pointerEvents: 'none',
        '& > *': { pointerEvents: 'auto' },
        // Ensure tooltips appear above
        '& .MuiTooltip-popper': { zIndex: 1500 },
      }}
    >
      {/* Manual tasks on TOP (reverse order so newest is at top) */}
      {Array.from(manualAgents).reverse().map(agentId => {
        const activity = activities[agentId];
        if (!activity) return null;
        const agentManualTasks = activity.tasks.filter(t => t.triggerType === 'manual');
        if (agentManualTasks.length === 0) return null;
        
        return (
          <Fade in key={`manual-${agentId}`}>
            <Box>
              <AgentBadge
                agentId={agentId}
                tasks={agentManualTasks}
                isExpanded={activity.isExpanded}
                onToggle={() => toggleExpanded(agentId)}
                onDismiss={(taskId) => dismissTask(agentId, taskId)}
                onFeedback={(taskId, rating, comment) => submitFeedback(agentId, taskId, rating, comment)}
              />
            </Box>
          </Fade>
        );
      })}

      {/* Auto tasks BELOW */}
      {Array.from(autoAgents).reverse().map(agentId => {
        const activity = activities[agentId];
        if (!activity) return null;
        const agentAutoTasks = activity.tasks.filter(t => t.triggerType !== 'manual');
        if (agentAutoTasks.length === 0) return null;
        
        return (
          <Fade in key={`auto-${agentId}`}>
            <Box>
              <AgentBadge
                agentId={agentId}
                tasks={agentAutoTasks}
                isExpanded={activity.isExpanded}
                onToggle={() => toggleExpanded(agentId)}
                onDismiss={(taskId) => dismissTask(agentId, taskId)}
                onFeedback={(taskId, rating, comment) => submitFeedback(agentId, taskId, rating, comment)}
              />
            </Box>
          </Fade>
        );
      })}

      {/* Pulse animation */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </Box>
  );
};

export default GlobalAgentBadges;
