/**
 * Shared AI Step Display Component
 * 
 * Displays AI plan steps in consistent command format across:
 * - Live AI execution panel
 * - Test case generation preview
 * - Test case editor details
 * 
 * Features:
 * - Shows command format (not AI descriptions)
 * - Expandable navigation steps with PRE-FETCHED transitions (no API calls)
 * - Status indicators (pending/current/completed/failed)
 * 
 * IMPORTANT: Transitions are ALWAYS pre-fetched during plan generation.
 * No fallback, no legacy, no API fetching in UI.
 */

import React, { useState } from 'react';
import { Box, Typography, IconButton, CircularProgress, Tooltip } from '@mui/material';
import { ExpandMore as ExpandMoreIcon, ExpandLess as ExpandLessIcon } from '@mui/icons-material';
import { useAgentChatPalette } from '../../constants/agentChatTheme';

interface AIStepDisplayProps {
  step: {
    stepNumber: number;
    command: string;
    params?: any;
    description?: string;
    type?: string;
    status?: 'pending' | 'current' | 'completed' | 'failed';
    duration?: number;
    transitions?: any[]; // PRE-FETCHED transitions - always available, no UI fetching
  };
  showExpand?: boolean; // Default true
  compact?: boolean; // Compact mode for lists
}

export const AIStepDisplay: React.FC<AIStepDisplayProps> = ({
  step,
  showExpand = true,
  compact = false
}) => {
  const P = useAgentChatPalette();
  const [isExpanded, setIsExpanded] = useState(false);

  const isNavigation = step.command === 'execute_navigation';
  const transitions = step.transitions || []; // PRE-FETCHED - always available

  // Status styling
  const getStatusStyle = () => {
    const { status } = step;

    let statusIcon, bgColor, borderColor;
    if (status === 'completed') {
      statusIcon = <Box sx={{ width: 12, height: 12, borderRadius: '50%', backgroundColor: P.success }} />;
      bgColor = `${P.success}1a`;
      borderColor = `${P.success}4d`;
    } else if (status === 'failed') {
      statusIcon = <Box sx={{ width: 12, height: 12, borderRadius: '50%', backgroundColor: P.error }} />;
      bgColor = `${P.error}1a`;
      borderColor = `${P.error}4d`;
    } else if (status === 'current') {
      statusIcon = <CircularProgress size={12} sx={{ color: P.accentText }} />;
      bgColor = `${P.accent}1a`;
      borderColor = `${P.accent}4d`;
    } else {
      statusIcon = <Box sx={{ width: 12, height: 12, borderRadius: '50%', backgroundColor: P.textMuted, border: `1px solid ${P.borderColor}` }} />;
      bgColor = `${P.hoverBg}`;
      borderColor = 'transparent';
    }

    return { statusIcon, bgColor, borderColor };
  };

  const { statusIcon, bgColor, borderColor } = getStatusStyle();

  // Display text: command format for navigation, description for others
  const displayText = isNavigation 
    ? `${step.command}(${step.params?.target_node || 'unknown'})`
    : step.description || step.command;

  // Simple toggle - transitions are ALWAYS pre-fetched, no API calls needed
  const handleToggleExpand = () => {
    if (!isNavigation) return;
    setIsExpanded(!isExpanded);
  };

  return (
    <Box
      sx={{
        mb: compact ? 0.25 : 0.5,
        px: compact ? 0.5 : 0.75,
        py: compact ? 0.25 : 0.5,
        backgroundColor: bgColor,
        borderRadius: 0.5,
        border: `1px solid ${borderColor}`,
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
        {statusIcon}
         <Tooltip title={`${step.stepNumber}. ${displayText}${step.duration !== undefined ? (step.duration === 0 ? ' (already at target)' : ` (${step.duration.toFixed(1)}s)`) : ''}`} arrow placement="top">
          <Typography
            variant="caption"
            sx={{
              color: P.textPrimary,
              fontWeight: 'bold',
              fontFamily: isNavigation ? 'monospace' : 'inherit',
              flex: 1,
              fontSize: compact ? '0.65rem' : '0.75rem',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              cursor: 'default'
            }}
           >
             {step.stepNumber}. {displayText}
             {step.duration !== undefined && (step.duration === 0 ? ' (already at target)' : ` (${step.duration.toFixed(1)}s)`)}
           </Typography>
        </Tooltip>
        
        {isNavigation && showExpand && (
          <IconButton
            size="small"
            onClick={handleToggleExpand}
            sx={{ color: P.textSecondary, p: 0.25 }}
          >
            {isExpanded ? (
              <ExpandLessIcon fontSize="small" />
            ) : (
              <ExpandMoreIcon fontSize="small" />
            )}
          </IconButton>
        )}
      </Box>
      
      {/* Navigation transitions (when expanded) - Compact vertical spacing */}
      {isNavigation && isExpanded && transitions.length > 0 && (
        <Box sx={{ ml: 1.5, mt: 0.5, borderLeft: `2px solid ${P.borderColor}`, pl: 0.75 }}>
          {transitions.map((transition: any, tIdx: number) => (
            <Box key={tIdx} sx={{ mb: 0.5 }}>
              <Typography variant="caption" sx={{ color: P.accentText, fontWeight: 'bold', display: 'block', fontSize: '0.7rem' }}>
                {transition.from_node_label} → {transition.to_node_label}
              </Typography>
              {transition.actions?.map((action: any, aIdx: number) => {
                const firstParam = action.params ? Object.values(action.params)[0] : '';
                const paramStr = typeof firstParam === 'string' ? firstParam : JSON.stringify(firstParam);
                return (
                  <Typography key={aIdx} variant="caption" sx={{ color: P.textSecondary, display: 'block', ml: 0.75, fontFamily: 'monospace', fontSize: '0.65rem', lineHeight: 1.3 }}>
                    - {action.command}({paramStr})
                  </Typography>
                );
              })}
              {transition.verifications?.length > 0 && (
                <Box sx={{ ml: 0.75, mt: 0.25 }}>
                  <Typography variant="caption" sx={{ color: P.textMuted, fontSize: '0.6rem' }}>Verifications:</Typography>
                  {transition.verifications.map((verification: any, vIdx: number) => (
                    <Typography key={vIdx} variant="caption" sx={{ color: P.textMuted, display: 'block', ml: 0.75, fontFamily: 'monospace', fontSize: '0.6rem', lineHeight: 1.3 }}>
                      - {verification.command} ({verification.verification_type})
                    </Typography>
                  ))}
                </Box>
              )}
            </Box>
          ))}
        </Box>
      )}

      {/* Non-navigation steps: show command/params */}
      {!isNavigation && (
        <Typography variant="caption" sx={{ color: P.textSecondary, display: 'block', ml: 2, fontFamily: 'monospace', fontSize: compact ? '0.65rem' : '0.75rem' }}>
          {step.command}
          {step.params && Object.keys(step.params).length > 0 && ` | ${JSON.stringify(step.params)}`}
        </Typography>
      )}
    </Box>
  );
};
