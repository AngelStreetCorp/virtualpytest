import React from 'react';
import { Box, Fab, Tooltip } from '@mui/material';
import { AutoAwesome } from '@mui/icons-material';
import { useLocation } from 'react-router-dom';
import { AICommandBar } from './AICommandBar';
import { LogTerminalPanel } from './panels/LogTerminalPanel';
import { useAIContext } from '../../contexts/AIContext';
import { useResponsiveMode } from '../../hooks/useResponsiveMode';
import { matchesFeatureRoute } from '../../config/features';

export const AIOmniOverlay: React.FC = () => {
  const { isLogsOpen, openCommand, status, suppressFloatingButton } = useAIContext();
  const { isMobile, isTablet } = useResponsiveMode();
  const location = useLocation();
  const isOnAgentChat = location.pathname === '/ai-agent';
  const isOnNavigationEditor = location.pathname.startsWith('/navigation-editor');
  // Dedicated fullscreen watch player — a bare page with no app chrome; no AI here.
  const isOnFullscreenPlayer = location.pathname === '/fullscreen-player';
  // The TestCase builder has its own AI mode (Visual/AI toggle), so the global
  // Ask AI button is redundant there.
  // Optional-feature builders (QuickTest, Virtual Scripts) opt in via
  // `hideFloatingAiButton` on their route (src/config/features.ts) instead of
  // being listed here.
  const isOnTestCaseBuilder =
    location.pathname.startsWith('/builder/test-builder') ||
    location.pathname.startsWith('/test-plan/testcase-builder') ||
    matchesFeatureRoute(location.pathname, 'hideFloatingAiButton');
  const hideFloatingAiButton =
    isMobile ||
    isTablet ||
    status !== 'ready' ||
    isOnAgentChat ||
    isOnNavigationEditor ||
    isOnTestCaseBuilder ||
    isOnFullscreenPlayer ||
    suppressFloatingButton;

  return (
    <Box sx={{ position: 'fixed', inset: 0, zIndex: 9999, pointerEvents: 'none' }}>

      {/* 1. Floating Command Bar (Always mounted, visible via internal state) */}
      {!isOnAgentChat && !isOnFullscreenPlayer && (
        <Box sx={{ pointerEvents: 'auto' }}>
          <AICommandBar />
        </Box>
      )}

      {/* Ask AI Button (Bottom Left) */}
      {!hideFloatingAiButton && (
        <Box
          sx={{
            position: 'fixed',
            bottom: 24,
            left: 24,
            pointerEvents: 'auto',
            zIndex: 1000
          }}
        >
          <Tooltip title="Ask AI (Cmd+K)" placement="right">
              <Fab
                  size="medium"
                  aria-label="Ask AI"
                  onClick={openCommand}
                  sx={{
                      bgcolor: 'rgba(212, 175, 55, 0.95)',
                      backdropFilter: 'blur(8px)',
                      boxShadow: '0 4px 24px rgba(212, 175, 55, 0.35)',
                      transition: 'all 0.2s ease',
                      '&:hover': {
                        bgcolor: '#B8860B',
                        boxShadow: '0 6px 28px rgba(212, 175, 55, 0.5)',
                        transform: 'scale(1.05)'
                      }
                  }}
              >
                  <AutoAwesome sx={{ color: '#1a1a1a', fontSize: 24 }} />
              </Fab>
          </Tooltip>
        </Box>
      )}

      {/* Bottom Panel (Logs) - Agent Pilot replaced by GlobalAgentBadges */}
      {isLogsOpen && (
        <Box sx={{ pointerEvents: 'auto' }}>
          <LogTerminalPanel />
        </Box>
      )}
      
    </Box>
  );
};
