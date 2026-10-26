/**
 * Mobile AI Agent Chat
 *
 * Simplified single-column chat for the AI Agent page on mobile viewports.
 * The desktop page (`pages/AgentChat.tsx`) is a fixed two-pane layout
 * (conversation sidebar + wide chat pane) that doesn't fit a phone screen —
 * this component intentionally leaves out the conversation-history sidebar,
 * multiple conversations, target/model selectors, and file uploads, and just
 * drives one ongoing conversation through a message list + input bar, the
 * same lightweight pattern as `AIOmniOverlay`/`AICommandBar`.
 *
 * It reuses the same conversation engine those components use
 * (`useAgentChatContext`, backed by `useAgentChat`) so sending a message here
 * goes through the exact same socket/session plumbing as everywhere else in
 * the app — no separate backend integration.
 */

import React, { useEffect, useRef } from 'react';
import { Box, Paper, TextField, IconButton, Typography, CircularProgress, Alert } from '@mui/material';
import { ArrowBack as BackIcon, ArrowUpward as SendIcon, AutoAwesome as SparkleIcon } from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { useAgentChatContext } from '../../contexts/AgentChatContext';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { MessageFeedbackBar, FeedbackSubmitter } from '../agent-chat/MessageFeedbackBar';
import { TYPOGRAPHY } from '../../constants/typography';

export interface MobileAgentChatProps {
  /** Current rating per chat message id (1 = down, 5 = up). */
  messageFeedback?: Record<string, number>;
  /** Shared POST handler; same instance the desktop chat uses. */
  submitMessageFeedback?: FeedbackSubmitter;
}

export const MobileAgentChat: React.FC<MobileAgentChatProps> = ({
  messageFeedback = {},
  submitMessageFeedback,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const navigate = useNavigate();
  const { status, messages, input, setInput, sendMessage, isProcessing, error, session } = useAgentChatContext();
  const listEndRef = useRef<HTMLDivElement>(null);

  /**
   * BUG-0776: on a phone this chat is the whole page — the bottom navigation is hidden
   * on /ai-agent — so the user had no way to leave it (a dead end in the native app,
   * which has no browser chrome). The arrow goes back to where the chat was opened
   * from; when the app was launched straight onto the chat there is nothing to go back
   * to, and the dashboard is where the user lands instead.
   */
  const handleBack = () => {
    const idx = (window.history.state as { idx?: number } | null)?.idx;
    if (typeof idx === 'number' && idx > 0) {
      navigate(-1);
      return;
    }
    navigate('/');
  };

  // Keep the latest message in view as the conversation grows.
  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, isProcessing]);

  const canSend = Boolean(input.trim()) && !isProcessing && status !== 'needs_key';

  const handleSend = () => {
    if (!canSend) return;
    sendMessage();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {/* BUG-0776: the way out of the chat. */}
      <Box
        sx={{
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          gap: 0.5,
          px: 0.5,
          py: 0.5,
          borderBottom: '1px solid',
          borderColor: 'divider',
        }}
      >
        <IconButton onClick={handleBack} aria-label={t('Back')} size="small" sx={{ color: P.textPrimary }}>
          <BackIcon fontSize="small" />
        </IconButton>
        <Typography sx={{ fontSize: TYPOGRAPHY.cardTitle.size, fontWeight: TYPOGRAPHY.cardTitle.weight, color: P.textPrimary }}>
          {t('AI Agent')}
        </Typography>
      </Box>

      {/* Message list */}
      <Box
        sx={{
          flex: 1,
          minHeight: 0,
          overflowY: 'auto',
          overflowX: 'hidden',
          px: 1.5,
          py: 2,
          display: 'flex',
          flexDirection: 'column',
          gap: 1.5,
        }}
      >
        {status === 'checking' && messages.length === 0 && (
          <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
            <CircularProgress size={24} />
          </Box>
        )}

        {status === 'needs_key' && (
          <Alert severity="info" sx={{ mb: 1 }}>
            The AI provider isn't configured yet. Open this app on a desktop browser (AI Agent
            page or Settings → AI) to set it up.
          </Alert>
        )}

        {status === 'error' && messages.length === 0 && (
          <Alert severity="warning" sx={{ mb: 1 }}>
            Couldn't reach the AI backend. Pull to refresh or try again shortly.
          </Alert>
        )}

        {status === 'ready' && messages.length === 0 && (
          <Box sx={{ textAlign: 'center', color: 'text.secondary', mt: 4, px: 2 }}>
            <SparkleIcon sx={{ fontSize: TYPOGRAPHY.kpiValue.size, mb: 1, opacity: 0.6 }} />
            <Typography variant="body2">Ask the AI agent anything to get started.</Typography>
          </Box>
        )}

        {messages.map((message) => (
          <Box
            key={message.id}
            sx={{ display: 'flex', flexDirection: 'column', alignItems: message.role === 'user' ? 'flex-end' : 'flex-start' }}
          >
            <Paper
              elevation={0}
              sx={{
                maxWidth: '85%',
                px: 1.5,
                py: 1,
                borderRadius: 2,
                bgcolor: message.role === 'user' ? P.accent : P.hoverBg,
                color: message.role === 'user' ? 'primary.contrastText' : P.textPrimary,
              }}
            >
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {message.content}
              </Typography>
            </Paper>
            {/* Per-message feedback (thumbs + optional comment) — same shared component the
                desktop chat uses, so the POST to /server/agents/feedback is identical and the
                backend can dedupe by message id + session id (one row per chat message). */}
            {message.role !== 'user' && submitMessageFeedback && (() => {
              const idx = messages.findIndex(m => m.id === message.id);
              const userPrompt = idx > 0 ? messages[idx - 1]?.content : undefined;
              const rating = messageFeedback[message.id];
              return (
                <Box sx={{ maxWidth: '85%', mt: 0.25, px: 0.5, alignSelf: 'flex-start' }}>
                  <MessageFeedbackBar
                    messageId={message.id}
                    agentId={(message as any).agent || (session as any)?.active_agent || 'atlas'}
                    prompt={userPrompt}
                    currentRating={rating}
                    submitFeedback={(mid, rt, ag, prm, cmt) => submitMessageFeedback(mid, rt, ag, prm, cmt)}
                    variant="stacked"
                  />
                </Box>
              );
            })()}
          </Box>
        ))}

        {isProcessing && (
          <Box sx={{ display: 'flex', justifyContent: 'flex-start' }}>
            <Paper
              elevation={0}
              sx={{
                px: 1.5,
                py: 1,
                borderRadius: 2,
                bgcolor: 'action.hover',
                display: 'flex',
                alignItems: 'center',
                gap: 1,
              }}
            >
              <CircularProgress size={14} />
              <Typography variant="body2" color="text.secondary">
                Thinking…
              </Typography>
            </Paper>
          </Box>
        )}

        {error && (
          <Alert severity="error" sx={{ mt: 1 }}>
            {error}
          </Alert>
        )}

        <div ref={listEndRef} />
      </Box>

      {/* Input bar, pinned to the bottom of the page */}
      <Box
        sx={{
          flexShrink: 0,
          borderTop: '1px solid',
          borderColor: 'divider',
          bgcolor: 'background.paper',
          px: 1,
          py: 1,
          pb: 'calc(8px + env(safe-area-inset-bottom, 0px))',
          display: 'flex',
          alignItems: 'flex-end',
          gap: 1,
        }}
      >
        <TextField
          fullWidth
          multiline
          maxRows={4}
          size="small"
          placeholder="Ask AI Agent..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={status === 'needs_key'}
        />
        <IconButton color="primary" onClick={handleSend} disabled={!canSend} aria-label="send message">
          <SendIcon />
        </IconButton>
      </Box>
    </Box>
  );
};

export default MobileAgentChat;
