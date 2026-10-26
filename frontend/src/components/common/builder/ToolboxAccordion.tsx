/**
 * Toolbox Accordion Component
 * 
 * Shared accordion with consistent styling for builder toolboxes.
 * Features:
 * - Left border accent color
 * - Single-expand behavior (controlled externally)
 * - Clean, professional styling
 */

import React from 'react';
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { useAgentChatPalette, AGENT_CHAT_PALETTE } from '../../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../../constants/typography';

interface ToolboxAccordionProps {
  /** Unique identifier for this accordion */
  id: string;
  /** Display title */
  title: string;
  /** Item count badge */
  count: number;
  /** Accent color for left border */
  accentColor: string;
  /** Is this accordion expanded */
  expanded: boolean;
  /** Callback when expansion changes */
  onExpandChange: (id: string, expanded: boolean) => void;
  /** Content to render inside */
  children: React.ReactNode;
  /** Force expansion (e.g., during search) */
  forceExpanded?: boolean;
}

export const ToolboxAccordion: React.FC<ToolboxAccordionProps> = ({
  id,
  title,
  count,
  accentColor,
  expanded,
  onExpandChange,
  children,
  forceExpanded = false,
}) => {
  const P = useAgentChatPalette();
  void P; // kept for symmetry with sibling components — categorical colours are on TOOLBOX_TAB_COLORS
  const isExpanded = forceExpanded || expanded;

  return (
    <Accordion
      expanded={isExpanded}
      onChange={(_event, newExpanded) => {
        onExpandChange(id, newExpanded);
      }}
      disableGutters
      TransitionProps={{ unmountOnExit: true }}
      sx={{
        boxShadow: 'none',
        '&:before': { display: 'none' },
        margin: '0 !important',
        borderRadius: 0,
        borderLeft: `3px solid ${accentColor}`,
        backgroundColor: isExpanded ? 'action.hover' : 'transparent',
        transition: 'all 0.15s ease',
        '& .MuiAccordionDetails-root': {
          padding: '4px 8px 8px 12px !important',
        },
        '&.Mui-expanded': {
          margin: '0 !important',
        }
      }}
    >
      <AccordionSummary
        expandIcon={<ExpandMoreIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size, color: 'text.secondary' }} />}
        sx={{
          minHeight: '36px !important',
          px: 1.5,
          '& .MuiAccordionSummary-content': {
            my: '8px !important',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          },
          '&:hover': {
            backgroundColor: 'action.hover',
          },
          '&.Mui-expanded': {
            minHeight: '36px !important',
          }
        }}
      >
        <Typography 
          fontSize="0.8125rem" 
          fontWeight={500}
          sx={{ color: 'text.primary' }}
        >
          {title}
        </Typography>
        <Typography 
          fontSize="0.6875rem" 
          sx={{ color: 'text.disabled', mr: 1 }}
        >
          {count}
        </Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ p: 0 }}>
        {children}
      </AccordionDetails>
    </Accordion>
  );
};

/** Default tab colors used across builder toolboxes.
 * Static (dark) — these are categorical colour marks for toolbox category
 * headers, read on both themes. Hooks aren't possible at module scope. */
export const TOOLBOX_TAB_COLORS: Record<string, string> = {
  // Common colors
  standard: AGENT_CHAT_PALETTE.textMuted,

  // TestCase Builder specific
  navigation: AGENT_CHAT_PALETTE.series[2],
  actions: AGENT_CHAT_PALETTE.warning,
  verifications: AGENT_CHAT_PALETTE.series[1],
  api: AGENT_CHAT_PALETTE.series[3],

  // Campaign Builder specific
  testcases: AGENT_CHAT_PALETTE.series[2],
  scripts: AGENT_CHAT_PALETTE.warning,
};

