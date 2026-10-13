/**
 * MessageFeedbackBar — thumb up/down + optional inline comment for one chat message.
 *
 * Shared between the desktop chat (`ChatMessages.tsx`) and the mobile chat
 * (`MobileAgentChat.tsx`) so the feedback logic and the POST to
 * `/server/agents/feedback` live in one place. The component is presentational: the
 * parent owns the per-message rating and supplies a submitter; the inline comment
 * field state lives inside the component (one row of fields per id, keyed by
 * messageId so multiple messages can have an open field at once without conflict).
 *
 * Visual tokens come from `useAgentChatPalette()` so it follows light/dark without
 * inline hex colours (UI style guide §2).
 */

import React, { useState } from 'react';
import {
  Box,
  IconButton,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import {
  Close as CloseIcon,
  Send as SendIcon,
  ThumbDown,
  ThumbUp,
} from '@mui/icons-material';
import { useTheme } from '@mui/material/styles';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';

export type FeedbackSubmitter = (
  messageId: string,
  rating: number,
  agentId: string,
  prompt?: string,
  comment?: string
) => void;

export interface MessageFeedbackBarProps {
  /** Stable id of the chat message being rated; passed back to the submitter. */
  messageId: string;
  /** Agent id stamped on the POST so the backend can scope the row by agent. */
  agentId: string;
  /** Optional original user prompt, forwarded as `task_description` for context. */
  prompt?: string;
  /** Current rating for this message (1 = thumb down, 5 = thumb up). `undefined` = none yet. */
  currentRating?: number;
  /** Shared handler — the same instance is used by every message on the page. */
  submitFeedback: FeedbackSubmitter;
  /**
   * Layout hint: `inline` puts the comment field on the same row as the thumbs (default
   * desktop behaviour); `stacked` wraps the comment field under the thumbs on its own
   * line (default mobile behaviour, so the field gets full width on narrow viewports).
   */
  variant?: 'inline' | 'stacked';
}

export const MessageFeedbackBar: React.FC<MessageFeedbackBarProps> = ({
  messageId,
  agentId,
  prompt,
  currentRating,
  submitFeedback,
  variant = 'stacked',
}) => {
  const P = useAgentChatPalette();
  const theme = useTheme();
  const { t } = useI18n();
  const [comment, setComment] = useState('');
  const [commentStatus, setCommentStatus] = useState<'editing' | 'sent'>('editing');

  const isPositive = currentRating === 5;
  const isNegative = currentRating === 1;
  const isEditing = commentStatus === 'editing';
  const isSent = commentStatus === 'sent';
  const showCommentRow = isEditing || isSent;

  const openCommentField = (rating: number) => {
    // Always send the thumb immediately (one-shot write), then open the field.
    submitFeedback(messageId, rating, agentId, prompt);
    setComment('');
    setCommentStatus('editing');
  };

  const closeCommentField = () => {
    setComment('');
    setCommentStatus('editing');
  };

  const sendComment = () => {
    const text = comment.trim();
    if (!text) return;
    const rating = currentRating || (isNegative ? 1 : 5);
    submitFeedback(messageId, rating, agentId, prompt, text);
    setComment(text);
    setCommentStatus('sent');
  };

  const thumbsBox = (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexShrink: 0 }}>
      <Tooltip title={isPositive ? t('Remove helpful rating') : t('Mark as helpful')}>
        <IconButton
          size="small"
          aria-label={t('Mark as helpful')}
          onClick={() => {
            if (isPositive) {
              submitFeedback(messageId, 5, agentId, prompt);
            } else {
              openCommentField(5);
            }
          }}
          sx={{
            p: 0.25,
            color: isPositive ? P.success : 'text.disabled',
            bgcolor: isPositive ? 'rgba(34, 197, 94, 0.15)' : 'transparent',
            borderRadius: 1,
            transition: 'all 0.2s',
            '&:hover': {
              color: P.success,
              bgcolor: 'rgba(34, 197, 94, 0.1)',
            },
          }}
        >
          <ThumbUp sx={{ fontSize: 13 }} />
        </IconButton>
      </Tooltip>
      <Tooltip title={isNegative ? t('Remove not helpful rating') : t('Mark as not helpful')}>
        <IconButton
          size="small"
          aria-label={t('Mark as not helpful')}
          onClick={() => {
            if (isNegative) {
              submitFeedback(messageId, 1, agentId, prompt);
            } else {
              openCommentField(1);
            }
          }}
          sx={{
            p: 0.25,
            color: isNegative ? P.error : 'text.disabled',
            bgcolor: isNegative ? 'rgba(239, 68, 68, 0.15)' : 'transparent',
            borderRadius: 1,
            transition: 'all 0.2s',
            '&:hover': {
              color: P.error,
              bgcolor: 'rgba(239, 68, 68, 0.1)',
            },
          }}
        >
          <ThumbDown sx={{ fontSize: 13 }} />
        </IconButton>
      </Tooltip>
    </Box>
  );

  const commentRow = showCommentRow && (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 0.5,
        flex: variant === 'inline' ? 1 : undefined,
        minWidth: 0,
        width: variant === 'stacked' ? '100%' : undefined,
      }}
    >
      {isSent ? (
        <Typography
          variant="caption"
          sx={{ fontSize: '0.7rem', color: P.textMuted, fontStyle: 'italic' }}
        >
          {t('Thanks — your feedback was logged.')}
        </Typography>
      ) : (
        <>
          <TextField
            size="small"
            value={comment}
            onChange={(e) => {
              setComment(e.target.value);
              if (commentStatus !== 'editing') setCommentStatus('editing');
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendComment();
              } else if (e.key === 'Escape') {
                closeCommentField();
              }
            }}
            placeholder={isPositive ? t('What was good?') : t('What went wrong?')}
            autoFocus
            sx={{
              flex: 1,
              minWidth: 0,
              '& .MuiInputBase-input': {
                fontSize: '0.75rem',
                py: 0.5,
                px: 1,
                color: P.textPrimary,
              },
              '& .MuiOutlinedInput-root': {
                bgcolor: P.surface,
                '& fieldset': { borderColor: P.borderColor },
                '&:hover fieldset': { borderColor: P.borderColor },
                '&.Mui-focused fieldset': { borderColor: P.accent },
              },
            }}
          />
          <Tooltip title={t('Send')}>
            <span>
              <IconButton
                size="small"
                onClick={sendComment}
                disabled={!comment.trim()}
                sx={{ p: 0.25, color: P.accentText, '&:hover': { color: P.accent } }}
                aria-label={t('Send')}
              >
                <SendIcon sx={{ fontSize: 13 }} />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title={t('Dismiss')}>
            <IconButton
              size="small"
              onClick={closeCommentField}
              sx={{ p: 0.25, color: P.textMuted, '&:hover': { color: P.textPrimary } }}
              aria-label={t('Dismiss')}
            >
              <CloseIcon sx={{ fontSize: 13 }} />
            </IconButton>
          </Tooltip>
        </>
      )}
    </Box>
  );

  if (variant === 'inline') {
    return (
      <Box
        sx={{
          mt: 1,
          pt: 0.75,
          borderTop: '1px solid',
          borderColor: theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.05)',
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          flexWrap: 'wrap',
        }}
      >
        {thumbsBox}
        {commentRow}
      </Box>
    );
  }

  // stacked (mobile) — thumbs on their own row, comment field below when open so the
  // field gets full width on narrow viewports and the thumbs don't push the input off-screen.
  return (
    <Box
      sx={{
        mt: 1,
        pt: 0.75,
        borderTop: '1px solid',
        borderColor: theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.05)',
        display: 'flex',
        flexDirection: 'column',
        gap: 0.75,
      }}
    >
      {thumbsBox}
      {commentRow}
    </Box>
  );
};

export default MessageFeedbackBar;