import React from 'react';
import { Box, Fab, Tooltip, keyframes } from '@mui/material';
import { AutoAwesome } from '@mui/icons-material';
import { useLocation } from 'react-router-dom';
import { AICommandBar } from './AICommandBar';
import { LogTerminalPanel } from './panels/LogTerminalPanel';
import { useAIContext } from '../../contexts/AIContext';
import { useResponsiveMode } from '../../hooks/useResponsiveMode';
import { matchesFeatureRoute } from '../../config/features';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { usePermissions } from '../../hooks/auth/usePermissions';
import { TYPOGRAPHY } from '../../constants/typography';

export const AIOmniOverlay: React.FC = () => {
  const P = useAgentChatPalette();
  const { isLogsOpen, openCommand, status, suppressFloatingButton } = useAIContext();
  const { isMobile, isTablet } = useResponsiveMode();
  const location = useLocation();
  const isOnAgentChat = location.pathname === '/ai-agent';
  // Ask AI and Cmd+K start an Atlas conversation; a role without ai_agent:use (viewer) cannot.
  const canChat = usePermissions().canAccess('ai_agent:use');
  const isOnNavigationEditor = location.pathname.startsWith('/navigation-editor');
  // Dedicated fullscreen watch player — a bare page with no app chrome; no AI here.
  // A public shared run snapshot is bare as well: the visitor may not be signed in.
  const isOnFullscreenPlayer =
    location.pathname === '/fullscreen-player' || location.pathname.startsWith('/share/run/');
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
    !canChat ||
    isMobile ||
    isTablet ||
    status !== 'ready' ||
    isOnAgentChat ||
    isOnNavigationEditor ||
    isOnTestCaseBuilder ||
    isOnFullscreenPlayer ||
    suppressFloatingButton;

  // Slow glow pulse on the floating Ask AI Fab: the accent-coloured halo swells
  // and fades (~20 % → ~60 % alpha, 8 → 16 px blur) with a 2.5 % scale breath;
  // kept tight and slow on purpose (a 38 px / 3.2 s glow read as too loud),
  // one peak per 5 s. Under `prefers-reduced-motion` only the scale is dropped
  // — the glow keeps running, since a fading halo is not motion (macOS "Reduce
  // motion" is on for the owner, which is why earlier pulses never showed).
  const askAiGlow = keyframes`
    0%, 100% { box-shadow: 0 0 8px 0 ${P.accent}33; }
    50%      { box-shadow: 0 0 16px 2px ${P.accent}99; }
  `;
  const askAiBreath = keyframes`
    0%, 100% { transform: scale(1); }
    50%      { transform: scale(1.025); }
  `;

  return (
    <Box sx={{ position: 'fixed', inset: 0, zIndex: 9999, pointerEvents: 'none' }}>

      {/* 1. Floating Command Bar (Always mounted, visible via internal state) */}
      {canChat && !isOnAgentChat && !isOnFullscreenPlayer && (
        <Box sx={{ pointerEvents: 'auto' }}>
          <AICommandBar />
        </Box>
      )}

      {/* Ask AI Button (Bottom Left) — lifted so the floating Fab doesn't sit on
          top of the in-flow Footer copyright line (BUG: footer "© 202…"
          appeared under the button at the bottom of long pages). */}
      {!hideFloatingAiButton && (
        <Box
          sx={{
            position: 'fixed',
            bottom: 64,
            left: 36,
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
                      bgcolor: P.accent,
                      backdropFilter: 'blur(8px)',
                      boxShadow: `0 4px 24px ${P.accent}59`,
                      animation: `${askAiGlow} 5s ease-in-out infinite, ${askAiBreath} 5s ease-in-out infinite`,
                      transition: 'background-color 0.2s ease',
                      '@media (prefers-reduced-motion: reduce)': {
                        animation: `${askAiGlow} 5s ease-in-out infinite`,
                      },
                      '&:hover': {
                        bgcolor: P.accentHover,
                        boxShadow: `0 6px 28px ${P.accent}80`,
                        transform: 'scale(1.05)',
                        // Pause the pulse on hover so the hover state reads cleanly
                        // against the resting pulse without two transitions stacking.
                        animationPlayState: 'paused',
                      }
                  }}
              >
                  <AutoAwesome sx={{ color: '#1a1a1a', fontSize: TYPOGRAPHY.pageTitle.size }} />
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
