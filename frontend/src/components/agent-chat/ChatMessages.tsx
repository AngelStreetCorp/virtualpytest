/**
 * Chat Messages Component - Main Chat Area
 *
 * Handles message rendering, processing state, empty state, and all chat content.
 */

import React, { useEffect } from 'react';
import { AgentChatErrorAlert } from './AgentChatErrorAlert';
import {
  Box,
  Paper,
  Typography,
  Alert,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Chip,
  Tooltip,
  IconButton,
  Avatar,
  TextField,
  Button,
  CircularProgress,
  InputAdornment,
} from '@mui/material';
import VpnKeyIcon from '@mui/icons-material/VpnKey';
import SettingsIcon from '@mui/icons-material/Settings';
import Visibility from '@mui/icons-material/Visibility';
import VisibilityOff from '@mui/icons-material/VisibilityOff';
import {
  Terminal as ConsoleIcon,
  CheckCircle as SuccessIcon,
  Error as ErrorIcon,
  ExpandMore as ExpandIcon,
  Psychology as ThinkingIcon,
  ContentCopy as CopyIcon,
  AccessTime as TimeIcon,
  DataUsage as TokenIcon,
  Lock as CacheIcon,
  Person as PersonIcon,
  PlayArrow as VideoPlayIcon,
} from '@mui/icons-material';
import { useTheme } from '@mui/material/styles';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { AGENT_CHAT_PALETTE, useAgentChatPalette } from '../../constants/agentChatTheme';
import { dedupeEvents, getInitials, mergeToolEvents } from '../../utils/agentChatUtils';
import { AgentEvent, Message } from '../../hooks/aiagent/useAgentChat';
import { useToolExecutionTiming } from '../../hooks/aiagent/useToolExecutionTiming';
import { ChatInput } from './ChatInput';
import { MessageFeedbackBar } from './MessageFeedbackBar';
import { MasterchiefConfirmCard } from '../ai/panels/MasterchiefConfirmCard';
import { AppIcon } from '../../constants/icons';
import { neutralButtonSx } from '../common/PageChrome';
import { TYPOGRAPHY } from '../../constants/typography';

// Colorize PASSED (green) and FAILED (red) in agent responses
// Handles both strings and React node arrays from ReactMarkdown.
// Static palette import: status colour is a fixed semantic (success/error) shared
// across both themes, so we read AGENT_CHAT_PALETTE directly.
const colorizeStatus = (node: React.ReactNode): React.ReactNode => {
  // Handle strings - split and colorize PASSED/FAILED
  if (typeof node === 'string') {
    const parts = node.split(/(PASSED|FAILED)/g);
    return parts.map((part, i) => {
      if (part === 'PASSED') return <span key={i} style={{ color: AGENT_CHAT_PALETTE.success, fontWeight: 600 }}>PASSED</span>;
      if (part === 'FAILED') return <span key={i} style={{ color: AGENT_CHAT_PALETTE.error, fontWeight: 600 }}>FAILED</span>;
      return part;
    });
  }

  // Handle arrays (mixed content from ReactMarkdown like text + links)
  if (Array.isArray(node)) {
    return node.map((child, i) => (
      <React.Fragment key={i}>{colorizeStatus(child)}</React.Fragment>
    ));
  }

  // Handle React elements (like <a>, <strong>, etc.) - return as-is
  return node;
};

// --- Video card: lite-embed pattern for the agent's [[video:<id>]] tokens ---
//
// Same UX as frontend/src/components/docs/VideoShowcase.tsx: poster image + play
// button first, the YouTube <iframe> only loads when the user clicks. The
// `[[video:<id>]]` token is the only way the agent can embed a video — never a
// raw URL or <iframe>, those would skip the lite-embed and load ~1 MB of YouTube
// JS eagerly on every chat render.
//
// Why the `<div data-video-id="...">` encoding instead of a `<video-card>` custom
// element: react-markdown's `Components` type is strict about element names, so
// the preprocessor writes a `div` (already typed) carrying a `data-video-id`
// attribute that the custom `div` handler below recognizes. Unknown ids pass
// through as a normal empty div, so a malformed token never silently swallows
// content.

// Match the LLM's video token, accepting 1-2 brackets on each side. The
// video-library SKILL.md and the tool docstring both tell the model to emit
// `[[video:<id>]]` (double brackets), but in live tests 2026-10-15 the model
// occasionally drops a closing bracket and emits `[[video:YWJ1uz8KHCo]`
// (single closing bracket) — and the chat then shows the raw text instead
// of a card. Be defensive: match either one or two brackets on each side.
const VIDEO_TOKEN_RE = /\[+video:([\w-]{11})\]+/g;
const VIDEO_ID_RE = /^[\w-]{11}$/;

// Split the LLM content at every [[video:<id>]] token into a sequence of
// segments, each tagged either as a 'text' segment (run through ReactMarkdown
// as usual) or a 'video' segment (rendered as a <VideoCard> directly).
//
// Why split-then-render instead of the earlier "preprocessor writes a
// <div data-video-id=...></div>, custom div component handler turns it into
// <VideoCard>" approach: react-markdown re-renders the entire markdown tree
// on every parent update, and the custom `div` component handler returns a
// brand-new <VideoCard> element each time. The VideoCard's internal `playing`
// state lives inside the ReactMarkdown subtree, so it gets re-mounted on every
// re-render and the click state is lost (BUG seen live 2026-10-15 19:48:
// `[VideoCard] play clicked` fired but the iframe never appeared).
// Pulling the VideoCard out of the ReactMarkdown tree gives it a stable
// position in the React tree, so `setPlaying(true)` survives re-renders.
const splitVideoTokens = (content: string): Array<{ kind: 'text' | 'video'; value: string }> => {
  const parts: Array<{ kind: 'text' | 'video'; value: string }> = [];
  const re = new RegExp(VIDEO_TOKEN_RE.source, 'g');
  let lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(content)) !== null) {
    if (m.index > lastIndex) {
      parts.push({ kind: 'text', value: content.slice(lastIndex, m.index) });
    }
    parts.push({ kind: 'video', value: m[1] });
    lastIndex = m.index + m[0].length;
  }
  if (lastIndex < content.length) {
    parts.push({ kind: 'text', value: content.slice(lastIndex) });
  }
  return parts;
};

// Render an assistant message body: split at [[video:<id>]] tokens, send
// each text segment to ReactMarkdown, render each video segment as a
// <VideoCard> directly. Empty text segments (e.g. a token at the very start
// of the content) are skipped so we don't end up with an empty <ReactMarkdown/>.
const renderContentWithVideos = (content: string): React.ReactNode => {
  const parts = splitVideoTokens(content);
  return parts.map((part, i) => {
    if (part.kind === 'video') {
      return <VideoCard key={`v-${i}-${part.value}`} id={part.value} />;
    }
    // Skip empty text segments that would otherwise render as an empty
    // ReactMarkdown block (which can cause layout issues in the chat column).
    if (part.value.trim().length === 0) {
      return null;
    }
    return (
      <ReactMarkdown
        key={`t-${i}`}
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw]}
        components={{
          a: ({ href, children }: any) => (
            <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
          ),
          p: ({ children }: any) => <p>{colorizeStatus(children)}</p>,
        }}
      >
        {part.value}
      </ReactMarkdown>
    );
  });
};

interface VideoCardProps {
  id: string;
}
// YouTube `hqdefault.jpg` is the lightweight 480x360 poster; the <iframe>
// only ships when the user presses play.
//
// We use `youtube.com/embed/...` (not `youtube-nocookie.com/embed/...`)
// because youtube-nocookie has stricter autoplay gating in some browsers —
// live test 2026-10-15 showed the iframe loading but autoplay=1 not kicking
// off. youtube.com with `?autoplay=1&rel=0&playsinline=1` is the same URL
// the in-app VideoShowcase uses, and it works there.
const videoPoster = (id: string) => `https://img.youtube.com/vi/${id}/hqdefault.jpg`;
const videoEmbedUrl = (id: string) =>
  `https://www.youtube.com/embed/${id}?autoplay=1&rel=0&playsinline=1&modestbranding=1`;

const VideoCard: React.FC<VideoCardProps> = ({ id }) => {
  const P = useAgentChatPalette();
  const [playing, setPlaying] = React.useState(false);
  if (!VIDEO_ID_RE.test(id)) {
    return null;
  }
  return (
    <Box
      // Center the card horizontally in the chat column. `display: 'block'` +
      // `mx: 'auto'` only centers a fixed-width block, so we wrap the
      // aspect-ratio card in a centering container. The inner Box keeps the
      // 16:9 aspect ratio and the lite-embed pattern.
      sx={{
        display: 'block',
        mx: 'auto',
        my: 1.25,
        width: '100%',
        maxWidth: 560,
      }}
    >
      <Box
        sx={{
          position: 'relative',
          width: '100%',
          aspectRatio: '16 / 9',
          borderRadius: 1.5,
          overflow: 'hidden',
          border: `1px solid ${P.borderColor}`,
          bgcolor: P.hoverBg,
        }}
      >
      {playing ? (
        <iframe
          src={videoEmbedUrl(id)}
          title={`YouTube video ${id}`}
          // loading="eager" because the card is already in the chat viewport
          // when the user clicks play, and lazy iframes have a race condition
          // where the YouTube embed JS hasn't finished downloading on first
          // load (no cache yet). The user would click play and see nothing;
          // only after a hard refresh (cache warm) would the iframe play.
          // BUG seen live 2026-10-15 20:48.
          loading="eager"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', border: 0 }}
        />
      ) : (
        <Box
          component="button"
          type="button"
          onClick={() => setPlaying(true)}
          aria-label={`Play video ${id}`}
          sx={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            p: 0,
            border: 0,
            cursor: 'pointer',
            bgcolor: 'transparent',
            display: 'block',
            '&:focus-visible': { outline: `2px solid ${P.accent}`, outlineOffset: -2 },
            '&:hover .play-btn': { bgcolor: P.accentHover },
          }}
        >
          <Box
            component="img"
            src={videoPoster(id)}
            alt=""
            sx={{ display: 'block', width: '100%', height: '100%', objectFit: 'cover' }}
          />
          <Box
            className="play-btn"
            sx={{
              position: 'absolute',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              width: 56,
              height: 56,
              borderRadius: '50%',
              bgcolor: P.accent,
              color: 'primary.contrastText',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <VideoPlayIcon sx={{ fontSize: TYPOGRAPHY.displayKpi.size }} />
          </Box>
        </Box>
      )}
      </Box>
    </Box>
  );
};

interface ChatMessagesProps {
  sidebarTab: 'system' | 'chats';
  activeConversationId: string | null;
  status: string;
  messages: Message[];
  currentEvents: AgentEvent[];
  isProcessing: boolean;
  pendingConversationId: string | null;
  session: any;
  agentsLoading: boolean;
  agentsError: string | null;
  error: string | null | undefined;
  availableAgents: any[];
  allAgentsMap: Record<string, { nickname: string; icon?: string; color?: string }>;
  selectedAgentId: string;
  messageFeedback: Record<string, number>;
  submitMessageFeedback: (messageId: string, rating: number, agentId: string, prompt?: string, comment?: string) => void;
  input: string;
  sendMessage: () => void;
  setInput: (input: string) => void;
  handleApproval: (approved: boolean) => void;
  toolExpanded: Record<string, boolean>;
  setToolExpanded: (updater: (prev: Record<string, boolean>) => Record<string, boolean>) => void;
  messagesEndRef: React.RefObject<HTMLDivElement>;
  /** Rendered under the last Atlas answer (the Open companion offer). */
  afterAnswer?: React.ReactNode;
  /** TASK-175: switch to another agent and ask it the same question (the "Ask Masterchief" button). */
  onAskAgent?: (agentId: string, prompt?: string) => void;
  scrollContainerRef: React.RefObject<HTMLDivElement>;
  isUserScrolledUp: React.MutableRefObject<boolean>;
  lastMessageCount: React.MutableRefObject<number>;
  lastToolEventCount: React.MutableRefObject<number>;
  handleScroll: () => void;
  conversations: any[];
  clearHistory: () => void;
  stopGeneration: () => void;
  shouldShowExecutingAnimation: (key: string, isExecuting: boolean) => boolean;
  apiKeyInput: string;
  setApiKeyInput: (value: string) => void;
  saveApiKey: () => void;
  isValidating: boolean;
  activeProvider: string;
  activeModel: string;
  activeEndpoint: string;
  // Wall-clock turn timing (ms epoch). All three come from `useAgentChat`:
  // `turnStartedAt` is set when the user sends and stays set until the turn
  // finalizes; `firstThinkingStartedAt` flips on the first thinking chunk and
  // is the origin for the Reasoning timer; `lastThinkingAt` tracks the most
  // recent thinking chunk so the Reasoning timer can freeze the moment
  // reasoning stops streaming.
  turnStartedAt?: number | null;
  firstThinkingStartedAt?: number | null;
  lastThinkingAt?: number | null;
}

// Helper function to get agent nickname from agents map
const getAgentNickname = (
  agentName: string | undefined, 
  allAgentsMap: Record<string, { nickname: string; icon?: string; color?: string }>,
  availableAgents: any[]
): string => {
  if (!agentName) return 'Agent';
  // Check allAgentsMap first (includes sub-agents)
  const mapped = allAgentsMap[agentName];
  if (mapped?.nickname) return mapped.nickname;
  // Fallback to availableAgents
  const agent = availableAgents.find(a => a.name === agentName || a.id === agentName || a.nickname === agentName);
  return agent?.nickname || agentName;
};

// Helper function to get agent color
const getAgentColor = (
  agentName: string | undefined,
  allAgentsMap: Record<string, { nickname: string; icon?: string; color?: string }>,
  availableAgents: any[],
  accentColor: string
): string => {
  if (!agentName) return accentColor;
  const mapped = allAgentsMap[agentName];
  if (mapped?.color) return mapped.color;
  const agent = availableAgents.find(a => a.name === agentName || a.id === agentName);
  return agent?.color || accentColor;
};

const getUniqueDebugEvents = (events: AgentEvent[]): AgentEvent[] => {
  const seen = new Set<string>();
  const unique: AgentEvent[] = [];

  for (const event of events) {
    if (event.type !== 'system_prompt' && event.type !== 'conversation_context' && event.type !== 'tool_definitions') continue;
    const key = `${event.type}::${event.content || ''}`;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(event);
  }

  const order: Record<string, number> = {
    conversation_context: 0,
    system_prompt: 1,
    tool_definitions: 2,
  };

  unique.sort((a, b) => {
    return (order[a.type] ?? 99) - (order[b.type] ?? 99);
  });

  return unique;
};

const TOOLS_COLLAPSED_COUNT = 5;

// Tool calls, newest first, capped to the last few so the reasoning above stays
// in view; "Show N more" reveals the rest. Original indices keep each row's
// expanded state stable as new calls arrive.
const renderToolList = (
  events: AgentEvent[],
  scope: string,
  toolExpanded: Record<string, boolean>,
  setToolExpanded: (updater: (prev: Record<string, boolean>) => Record<string, boolean>) => void,
  shouldShowExecutingAnimation: (key: string, isExecuting: boolean) => boolean,
  theme: any
) => {
  const showAll = toolExpanded[`tools-all-${scope}`] ?? false;
  const indexed = events.map((event, idx) => ({ event, idx })).reverse();
  const visible = showAll ? indexed : indexed.slice(0, TOOLS_COLLAPSED_COUNT);
  const hidden = indexed.length - visible.length;
  const toggle = (open: boolean) => setToolExpanded(prev => ({ ...prev, [`tools-all-${scope}`]: open }));
  const linkSx = { cursor: 'pointer', color: 'text.secondary', fontSize: TYPOGRAPHY.caption.size, py: 0.5, px: 1, '&:hover': { color: 'text.primary' } };
  return (
    <>
      {visible.map(({ event, idx }) => renderToolActivity(event, idx, toolExpanded, setToolExpanded, shouldShowExecutingAnimation, theme))}
      {hidden > 0 && (
        <Typography variant="caption" onClick={() => toggle(true)} sx={{ ...linkSx, display: 'block' }} data-testid="tools-show-more">
          Show {hidden} earlier tool call{hidden === 1 ? '' : 's'}
        </Typography>
      )}
      {showAll && indexed.length > TOOLS_COLLAPSED_COUNT && (
        <Typography variant="caption" onClick={() => toggle(false)} sx={{ ...linkSx, display: 'block' }}>
          Show fewer
        </Typography>
      )}
    </>
  );
};

const renderToolActivity = (
  event: AgentEvent,
  idx: number,
  toolExpanded: Record<string, boolean>,
  setToolExpanded: (updater: (prev: Record<string, boolean>) => Record<string, boolean>) => void,
  shouldShowExecutingAnimation: (key: string, isExecuting: boolean) => boolean,
  theme: any
) => {
  // Masterchief proposal: render a confirm card instead of the generic JSON
  // dump. The propose tool returns { success, data: { audit_id, op, ... } };
  // the card shows blast radius + permission + Confirm/Requeue/Abandon and
  // POSTs /server/masterchief/execute with the user's JWT.
  if (
    event.tool_name === 'propose_masterchief_op' &&
    event.tool_result &&
    typeof event.tool_result === 'object' &&
    (event.tool_result as any).success &&
    (event.tool_result as any).data
  ) {
    return (
      <MasterchiefConfirmCard
        key={`propose-${event.tool_name}-${idx}-${(event.tool_result as any).data?.audit_id || ''}`}
        proposal={(event.tool_result as any).data}
      />
    );
  }

  // Extract error information from multiple possible sources
  const hasError = event.success === false;
  const isExecuting = event.tool_result === undefined && event.success === undefined;

  // Use hook to determine if we should show executing animation (5-second delay)
  const toolKey = `${event.tool_name}-${idx}`;
  const showExecutingAnimation = shouldShowExecutingAnimation(toolKey, isExecuting);

  let errorMessage = '';

  if (hasError) {
    // Try to extract error from various sources
    if (event.tool_result) {
      if (typeof event.tool_result === 'string') {
        errorMessage = event.tool_result;
      } else if (typeof event.tool_result === 'object') {
        errorMessage = (event.tool_result as any).error || JSON.stringify(event.tool_result, null, 2);
      }
    } else if ((event as any).error) {
      // Check if error is directly on the event object
      errorMessage = typeof (event as any).error === 'string'
        ? (event as any).error
        : JSON.stringify((event as any).error, null, 2);
    } else if (event.content) {
      // Check if error is in content field
      errorMessage = event.content;
    } else {
      errorMessage = 'Tool failed with no error details';
    }
  }

  const shouldAutoExpand = hasError || showExecutingAnimation;

  return (
    <Accordion
      key={`${event.tool_name}-${idx}-${event.success ?? 'pending'}-${event.tool_result ? 'done' : 'waiting'}`}
      disableGutters
      elevation={0}
      expanded={toolExpanded[toolKey] ?? shouldAutoExpand}
      onChange={(_, isExpanded) => setToolExpanded(prev => ({ ...prev, [toolKey]: isExpanded }))}
      sx={{
        bgcolor: showExecutingAnimation ? 'rgba(212, 165, 116, 0.05)' : 'transparent',
        border: showExecutingAnimation ? '1px solid' : 'none',
        borderColor: showExecutingAnimation ? `${AGENT_CHAT_PALETTE.accent}30` : 'transparent',
        '&:before': { display: 'none' },
        mb: 0.5,
        borderRadius: 1,
        transition: 'all 0.3s',
      }}
    >
      <AccordionSummary
        expandIcon={<ExpandIcon sx={{ fontSize: TYPOGRAPHY.body.size, color: hasError ? 'error.main' : showExecutingAnimation ? AGENT_CHAT_PALETTE.accent : 'text.disabled' }} />}
        sx={{
          minHeight: 24,
          p: 0,
          '& .MuiAccordionSummary-content': { my: 0 },
          flexDirection: 'row-reverse',
          gap: 1,
          bgcolor: hasError ? 'rgba(239, 68, 68, 0.08)' : 'transparent',
          borderRadius: 1,
          px: 0.5,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
          <ConsoleIcon sx={{
            fontSize: TYPOGRAPHY.caption.size,
            color: hasError ? 'error.main' : showExecutingAnimation ? AGENT_CHAT_PALETTE.accent : 'text.disabled',
          }} />
          <Typography variant="caption" sx={{
            fontFamily: 'monospace',
            color: hasError ? 'error.main' : showExecutingAnimation ? AGENT_CHAT_PALETTE.accent : 'text.secondary',
            flex: 1,
            fontWeight: hasError ? 600 : showExecutingAnimation ? 500 : 400
          }}>
            {event.tool_name}
          </Typography>
          <Tooltip title="Copy tool name, input, and result">
            <IconButton
              size="small"
              onClick={(e) => {
                e.stopPropagation();
                const inputText = event.tool_params
                  ? JSON.stringify(event.tool_params, null, 2)
                  : 'No input parameters';
                const resultText = hasError && errorMessage
                  ? errorMessage
                  : event.tool_result === undefined || event.tool_result === null
                    ? (hasError ? errorMessage || 'No error details provided' : 'Executing...')
                    : typeof event.tool_result === 'string'
                      ? event.tool_result
                      : JSON.stringify(event.tool_result, null, 2);
                const fullText = `Tool: ${event.tool_name}\n\nInput:\n${inputText}\n\nResult:\n${resultText}`;
                navigator.clipboard.writeText(fullText);
              }}
              sx={{
                p: 0.25,
                opacity: 0.4,
                '&:hover': { opacity: 1, color: AGENT_CHAT_PALETTE.accent },
              }}
            >
              <CopyIcon sx={{ fontSize: TYPOGRAPHY.microMeta.size }} />
            </IconButton>
          </Tooltip>
          {showExecutingAnimation ? (
            <Box sx={{
              width: 12,
              height: 12,
              borderRadius: '50%',
              border: '2px solid',
              borderColor: `${AGENT_CHAT_PALETTE.accent}40`,
              borderTopColor: AGENT_CHAT_PALETTE.accent,
              animation: 'spin 1s linear infinite',
              '@keyframes spin': {
                '0%': { transform: 'rotate(0deg)' },
                '100%': { transform: 'rotate(360deg)' },
              },
            }} />
          ) : isExecuting ? null : hasError ?
            <ErrorIcon sx={{ fontSize: TYPOGRAPHY.caption.size, color: 'error.main' }} /> :
            <SuccessIcon sx={{ fontSize: TYPOGRAPHY.caption.size, color: 'success.main' }} />
          }
        </Box>
      </AccordionSummary>
      <AccordionDetails sx={{ p: 0, pl: 3 }}>
        {hasError && (
          <Alert
            severity="error"
            sx={{
              mb: 1.5,
              fontSize: TYPOGRAPHY.caption.size,
              '& .MuiAlert-message': { fontSize: TYPOGRAPHY.caption.size }
            }}
          >
            <Typography variant="caption" sx={{ fontWeight: 600, display: 'block', mb: 0.5 }}>
              Tool Execution Failed
            </Typography>
            <Typography variant="caption" component="pre" sx={{ m: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'monospace' }}>
              {errorMessage}
            </Typography>
          </Alert>
        )}

        <Paper
          variant="outlined"
          sx={{
            p: 1.5,
            bgcolor: theme.palette.mode === 'dark' ? 'rgba(0,0,0,0.2)' : AGENT_CHAT_PALETTE.hoverBg,
            borderColor: hasError
              ? 'error.main'
              : showExecutingAnimation
                ? `${AGENT_CHAT_PALETTE.accent}40`
                : (theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.1)' : AGENT_CHAT_PALETTE.borderColor),
            borderRadius: 2
          }}
        >
          <Typography variant="caption" display="block" color="text.secondary" gutterBottom>Input</Typography>
          <Box component="pre" sx={{ m: 0, fontSize: TYPOGRAPHY.caption.size, overflow: 'auto', color: 'text.primary', maxHeight: 150 }}>
            {event.tool_params ? JSON.stringify(event.tool_params, null, 2) : '{}'}
          </Box>

          {/* Only show Result section when there's no error (error already shown in alert above) */}
          {!hasError && !isExecuting && (
            <>
              <Typography variant="caption" display="block" color="text.secondary" gutterBottom sx={{ mt: 1.5 }}>
                Result
              </Typography>
              <Box component="pre" sx={{ m: 0, fontSize: TYPOGRAPHY.caption.size, overflow: 'auto', color: 'text.primary', maxHeight: 300 }}>
                {event.tool_result === undefined || event.tool_result === null
                  ? <Typography variant="caption" color="text.disabled" sx={{ fontStyle: 'italic' }}>
                      No result data
                    </Typography>
                  : typeof event.tool_result === 'string'
                    ? event.tool_result
                    : JSON.stringify(event.tool_result, null, 2)
                }
              </Box>
            </>
          )}

          {showExecutingAnimation && (
            <Box sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              p: 1.5,
              mt: 1.5,
              bgcolor: theme.palette.mode === 'dark' ? 'rgba(0,0,0,0.3)' : 'rgba(0,0,0,0.02)',
              borderRadius: 1,
              border: '1px dashed',
              borderColor: AGENT_CHAT_PALETTE.accent,
            }}>
              <Box sx={{
                width: 16,
                height: 16,
                borderRadius: '50%',
                border: '2px solid',
                borderColor: `${AGENT_CHAT_PALETTE.accent}40`,
                borderTopColor: AGENT_CHAT_PALETTE.accent,
                animation: 'spin 1s linear infinite',
                '@keyframes spin': {
                  '0%': { transform: 'rotate(0deg)' },
                  '100%': { transform: 'rotate(360deg)' },
                },
              }} />
              <Typography variant="caption" sx={{ color: AGENT_CHAT_PALETTE.accent, fontWeight: 500 }}>
                Waiting for response...
              </Typography>
            </Box>
          )}
        </Paper>
      </AccordionDetails>
    </Accordion>
  );
};

const getDebugEventTitle = (type: string): string => {
  if (type === 'system_prompt') return 'System Prompt';
  if (type === 'conversation_context') return 'Runtime Context';
  if (type === 'tool_definitions') return 'Tools';
  return type;
};

const getDebugEventText = (event: AgentEvent): string => {
  const content = event.content || '';
  try {
    const parsed = JSON.parse(content);
    if (Array.isArray(parsed)) {
      return parsed
        .filter((b: any) => b.type === 'text' && b.text)
        .map((b: any) => b.text)
        .join('\n\n') || content || 'No content available';
    }
  } catch {
    // Raw text or JSON object
  }
  return typeof content === 'string' ? content : JSON.stringify(content, null, 2);
};

const estimateTokenCount = (text: string): number => Math.ceil(text.length / 4);

const assistantMarkdownSx = (theme: any) => ({
  '& p': { m: 0, mb: 0.75, '&:last-child': { mb: 0 } },
  '& a': { color: AGENT_CHAT_PALETTE.accent, textDecoration: 'none', '&:hover': { textDecoration: 'underline' } },
  '& strong': { fontWeight: 600 },
  '& code': {
    bgcolor: theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.05)',
    px: 0.5,
    py: 0.15,
    borderRadius: 0.5,
    fontFamily: 'monospace',
    // ui-ok: no-literal-font-size — em is contextual to the surrounding text; code blocks
    // always render slightly smaller than their parent, regardless of the user's Size choice.
    fontSize: '0.85em', // ui-ok: no-literal-font-size - em is relative to the parent, follows the Size picker
    border: '1px solid',
    borderColor: theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
  },
  '& pre': {
    bgcolor: theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.03)',
    p: 1.25,
    borderRadius: 1,
    overflow: 'auto',
    border: '1px solid',
    borderColor: theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)',
    '& code': {
      bgcolor: 'transparent',
      p: 0,
      border: 'none',
      // ui-ok: no-literal-font-size — em relative to the surrounding `<pre>` parent; the
      // outer code-block rule above is the typography contract.
      fontSize: '0.8em', // ui-ok: no-literal-font-size - em is relative to the parent, follows the Size picker
    },
  },
  '& h1': { fontSize: TYPOGRAPHY.cardTitle.size, fontWeight: 700, m: 0, mt: 1, mb: 0.5 },
  '& h2': { fontSize: TYPOGRAPHY.navbarItem.size, fontWeight: 700, m: 0, mt: 0.85, mb: 0.5 },
  '& h3, & h4, & h5, & h6': { fontSize: TYPOGRAPHY.navbarItem.size, fontWeight: 600, m: 0, mt: 0.75, mb: 0.4 },
  '& ul, & ol': { m: 0, pl: 2, '& li': { mb: 0.2 } },
  '& table': {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: TYPOGRAPHY.caption.size,
    lineHeight: 1.45,
    my: 0.75,
  },
  '& thead th': {
    textAlign: 'left',
    fontWeight: 600,
    borderBottom: '1px solid',
    borderColor: theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.16)' : 'rgba(0,0,0,0.16)',
    pb: 0.35,
    pr: 1,
  },
  '& tbody td': {
    verticalAlign: 'top',
    borderBottom: '1px solid',
    borderColor: theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
    py: 0.3,
    pr: 1,
  },
  '& hr': {
    border: 'none',
    borderTop: '1px solid',
    borderColor: 'inherit',
    opacity: 0.2,
    margin: '8px 0',
  },
  fontSize: TYPOGRAPHY.navbarItem.size,
  lineHeight: 1.65,
  color: 'text.primary',
});

const renderSystemPlaceholder = (theme: any) => (
  <Box sx={{
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
  }}>
    <Typography
      variant="body1"
      sx={{
        color: theme.palette.text.secondary,
        fontWeight: 400,
        opacity: 0.6,
      }}
    >
      No incident
    </Typography>
  </Box>
);

export const ChatMessages: React.FC<ChatMessagesProps> = ({
  sidebarTab,
  activeConversationId,
  status,
  messages,
  currentEvents,
  isProcessing,
  pendingConversationId,
  session,
  agentsLoading,
  agentsError,
  error,
  availableAgents,
  allAgentsMap,
  selectedAgentId,
  onAskAgent,
  messageFeedback,
  submitMessageFeedback,
  input,
  sendMessage,
  setInput,
  handleApproval,
  toolExpanded,
  setToolExpanded,
  messagesEndRef,
  afterAnswer,
  scrollContainerRef,
  isUserScrolledUp,
  lastMessageCount,
  lastToolEventCount,
  handleScroll,
  conversations,
  clearHistory,
  stopGeneration,
  apiKeyInput,
  setApiKeyInput,
  saveApiKey,
  isValidating,
  activeProvider,
  activeModel,
  activeEndpoint,
  turnStartedAt,
  firstThinkingStartedAt,
  lastThinkingAt,
}) => {
  const P = useAgentChatPalette();
  const theme = useTheme();
  const [showKey, setShowKey] = React.useState(false);
  // Per-message feedback comment state lives inside MessageFeedbackBar (one row per message id).

  // Tool execution timing hook (5-second delay for animations)
  const { shouldShowExecutingAnimation } = useToolExecutionTiming();

  // Live tick for the right-aligned "answer elapsed" + "reasoning elapsed"
  // counters. The counters need to re-render while the turn is running so
  // the user can watch the seconds tick by; we update `now` four times a
  // second (250ms), which is fast enough for sub-second resolution at the
  // tenths-digit granularity we display ("mm:ss.t") without burning CPU on a
  // 16ms timer. Stops as soon as the turn finalizes (turnStartedAt becomes
  // null) so the freed interval never leaks.
  const [now, setNow] = React.useState<number>(() => Date.now());
  React.useEffect(() => {
    if (turnStartedAt == null) return undefined;
    const interval = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(interval);
  }, [turnStartedAt]);

  // Format an elapsed-ms duration as "mm:ss" (or "00:00" for null/0).
  // Kept local to this component because every consumer of the timer needs
  // the exact same shape — splitting it out would only have one caller.
  const formatElapsed = React.useCallback((elapsedMs: number | null | undefined): string => {
    const ms = Math.max(0, Math.floor(elapsedMs ?? 0));
    const totalSeconds = Math.floor(ms / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
  }, []);

  // Reset scroll state and tool expanded state when conversation changes
  useEffect(() => {
    isUserScrolledUp.current = false;
    lastMessageCount.current = 0;
    lastToolEventCount.current = 0;
    setToolExpanded(() => ({})); // Clear tool expanded state for new conversation
  }, [activeConversationId, setToolExpanded, isUserScrolledUp, lastMessageCount, lastToolEventCount]);


  // Only scroll on actual new content (new messages or completed tool calls)
  useEffect(() => {
    // Count completed tool events (those with results)
    const completedToolCount = currentEvents.filter(e =>
      e.type === 'tool_call' && (e.tool_result !== undefined || e.success !== undefined)
    ).length;

    const hasNewMessage = messages.length > lastMessageCount.current;
    const hasNewToolResult = completedToolCount > lastToolEventCount.current;

    // Only scroll if user hasn't scrolled up AND there's actual new content
    if (!isUserScrolledUp.current && (hasNewMessage || hasNewToolResult)) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }

    // Update tracking refs
    lastMessageCount.current = messages.length;
    lastToolEventCount.current = completedToolCount;
  }, [messages.length, currentEvents, isUserScrolledUp, lastMessageCount, lastToolEventCount, messagesEndRef]);

  // Only show processing state if viewing the conversation that's being processed
  const showProcessing = isProcessing && activeConversationId === pendingConversationId;

  // Show system placeholder only when on system tab AND (no conversation selected OR selected conversation is not a system one)
  const isSystemConversation = activeConversationId?.startsWith('bg_');
  const onSystemTabWithNoSelection = sidebarTab === 'system' && (!activeConversationId || !isSystemConversation);

  // Show system placeholder when on system tab with no incident selected
  if (status === 'ready' && onSystemTabWithNoSelection) {
    return renderSystemPlaceholder(theme);
  }

  // Empty state logic moved to AgentChat.tsx - ChatMessages only handles existing messages

  return (
    <>
      {/* Chat Stream - Messages area with top alignment */}
      <Box
        ref={scrollContainerRef}
        onScroll={handleScroll}
        sx={{
          flex: 1,
          overflowY: 'auto',
          overflowX: 'hidden',
          px: 2,
          py: 1,
          display: 'flex',
          flexDirection: 'column',
          gap: 1,
          justifyContent: 'flex-start', // Align messages to top of scrollable area
          minHeight: 0, // Allow shrinking
          pb: 0, // Extra padding at bottom to separate from input
          scrollbarWidth: 'thin',
          scrollbarColor: theme.palette.mode === 'dark' ? `${theme.palette.divider} transparent` : '#c1c1c1 transparent',
          '&::-webkit-scrollbar': { width: 6 },
          '&::-webkit-scrollbar-track': { background: 'transparent' },
          '&::-webkit-scrollbar-thumb': {
            background: theme.palette.mode === 'dark' ? theme.palette.divider : '#c1c1c1',
            borderRadius: 3,
          },
        }}
      >
        {/* Constrain the chat column to a comfortable reading width and
            center it. Without this, lines stretch to the full panel width
            (often >1200px on desktop), making paragraphs very hard to scan
            compared to ChatGPT / Claude (which cap around 768px). On narrow
            screens we collapse to 100% so nothing is clipped. */}
        <Box sx={{ width: '100%', maxWidth: 820, mx: 'auto' }}>

          {agentsLoading && (
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <Typography variant="body2" color="text.secondary">
                Loading agents...
              </Typography>
            </Box>
          )}

          {agentsError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              <Typography variant="subtitle2" gutterBottom>Failed to load agents</Typography>
              <Typography variant="caption">{agentsError}</Typography>
              <Typography variant="caption" display="block" sx={{ mt: 1 }}>
                Make sure the backend is running and agents are configured in YAML templates.
              </Typography>
            </Alert>
          )}

          {status === 'needs_key' && (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', flex: 1, p: 3 }}>
              <Paper
                elevation={0}
                sx={{
                  maxWidth: 480,
                  width: '100%',
                  p: 3,
                  border: '1px solid',
                  borderColor: 'warning.main',
                  borderRadius: 2,
                  textAlign: 'center',
                }}
              >
                <Box sx={{ position: 'relative', mb: 1 }}>
                  <Tooltip title="Settings → AI → Endpoints">
                    <IconButton
                      size="small"
                      href="/configuration/settings?tab=ai"
                      sx={{ position: 'absolute', top: -12, right: -12, color: 'text.secondary' }}
                    >
                      <SettingsIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <VpnKeyIcon sx={{ fontSize: TYPOGRAPHY.kpiValue.size, color: 'warning.main' }} />
                </Box>
                <Typography variant="h6" gutterBottom>API key needed</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  <strong>{activeEndpoint || activeProvider || 'unknown'}</strong>
                  {activeModel ? ` · ${activeModel}` : ''} has no key.
                </Typography>
                <TextField
                  fullWidth
                  size="small"
                  label="API key"
                  placeholder={activeProvider === 'anthropic' ? 'sk-ant-...' : activeProvider === 'openrouter' ? 'sk-or-v1-...' : 'Paste provider API key'}
                  value={apiKeyInput}
                  onChange={e => setApiKeyInput(e.target.value)}
                  type={showKey ? 'text' : 'password'}
                  autoComplete="new-password"
                  onKeyDown={e => { if (e.key === 'Enter') saveApiKey(); }}
                  sx={{ mb: 1.5 }}
                  InputProps={{
                    endAdornment: (
                      <InputAdornment position="end">
                        <IconButton size="small" onClick={() => setShowKey(v => !v)}>
                          {showKey ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}
                        </IconButton>
                      </InputAdornment>
                    ),
                  }}
                />
                <Button
                  variant="contained"
                  fullWidth
                  onClick={saveApiKey}
                  disabled={isValidating || !apiKeyInput.trim()}
                  startIcon={isValidating ? <CircularProgress size={14} /> : undefined}
                >
                  {isValidating ? 'Checking…' : 'Save'}
                </Button>
              </Paper>
            </Box>
          )}


          {messages.map((msg) => {
            const isUser = msg.role === 'user';
            const agentColor = getAgentColor(msg.agent, allAgentsMap, availableAgents, AGENT_CHAT_PALETTE.accent);

            return (
              <Box
                key={msg.id}
                sx={{
                  display: 'flex',
                  gap: 1.5,
                  flexDirection: isUser ? 'row-reverse' : 'row',
                  alignSelf: isUser ? 'flex-end' : 'flex-start',
                  maxWidth: '100%',
                  mb: 1
                }}
              >
                <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', pt: 0.5 }}>
                  {isUser ? (
                    <Avatar
                      sx={{ width: 28, height: 28, fontSize: TYPOGRAPHY.caption.size, bgcolor: theme.palette.mode === 'dark' ? '#5c6bc0' : '#3f51b5', fontWeight: 600 }}
                    >
                      <PersonIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
                    </Avatar>
                  ) : (
                    <Avatar sx={{ width: 28, height: 28, fontSize: TYPOGRAPHY.caption.size, bgcolor: agentColor, fontWeight: 600 }}>
                      {getInitials(msg.agent || 'QA')}
                    </Avatar>
                  )}
                </Box>

                <Paper
                  elevation={0}
                  sx={{
                    p: 1.5,
                    // Assistant bubble fills the (capped) row so markdown
                    // content can use the full reading width; user bubble
                    // sizes to content with a cap so short questions do not
                    // look like a full-width banner (matches ChatGPT/Claude).
                    flex: isUser ? '0 1 auto' : 1,
                    maxWidth: isUser ? '70%' : '100%',
                    bgcolor: theme.palette.mode === 'dark'
                      ? (isUser ? AGENT_CHAT_PALETTE.userBubble : AGENT_CHAT_PALETTE.agentBubble)
                      : (isUser ? P.hoverBg : P.surface),
                    border: isUser
                      ? `1px solid ${theme.palette.mode === 'dark' ? `${AGENT_CHAT_PALETTE.accent}50` : `${AGENT_CHAT_PALETTE.accent}40`}`
                      : `1px solid ${theme.palette.mode === 'dark' ? AGENT_CHAT_PALETTE.agentBorder : P.borderColor}`,
                    borderRadius: 2.5,
                    borderTopRightRadius: isUser ? 4 : 10,
                    borderTopLeftRadius: !isUser ? 4 : 10,
                    minWidth: 0,
                  }}
                >
                  {!isUser && (() => {
                    // Extract all unique agents from events
                    const agentChain = msg.events
                      ? [...new Set(msg.events.map(e => e.agent).filter(Boolean))]
                      : [];
                    const mainAgent = msg.agent || agentChain[0];
                    const delegatedAgents = agentChain.filter(a => a !== mainAgent && a !== 'System');

                    // Extract skill name from skill_loaded event
                    const skillLoadedEvent = msg.events?.find(e => e.type === 'skill_loaded');
                    const skillName = skillLoadedEvent?.content || null;

                      return (
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5, flexWrap: 'wrap' }}>
                          <Typography variant="subtitle2" fontWeight={600} color="text.primary" sx={{ fontSize: TYPOGRAPHY.body.size }}>
                      {getAgentNickname(msg.agent, allAgentsMap, availableAgents)}
                    </Typography>
                          {skillName && (
                            <Chip
                              label={skillName}
                              size="small"
                              variant="outlined"
                              sx={{
                                height: 18,
                                fontSize: TYPOGRAPHY.microMeta.size,
                                borderColor: P.accent,
                                color: P.accentText,
                                fontWeight: 600,
                                '& .MuiChip-label': { px: 0.75 }
                              }}
                            />
                          )}
                        {delegatedAgents.length > 0 && (
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                            <Typography variant="caption" sx={{ color: 'text.disabled' }}>→</Typography>
                            {delegatedAgents.map((agent) => (
                              <Chip
                                key={agent}
                                label={agent}
                                size="small"
                                sx={{
                                  height: 18,
                                  fontSize: TYPOGRAPHY.microMeta.size,
                                  bgcolor: getAgentColor(agent, allAgentsMap, availableAgents, AGENT_CHAT_PALETTE.accent),
                                  color: '#fff',
                                  '& .MuiChip-label': { px: 0.75 }
                                }}
                              />
                            ))}
                          </Box>
                        )}
                      </Box>
                    );
                  })()}

                  {/* Debug Events - Runtime Context, System Prompt, and Tools from stored message events */}
                  {!isUser && msg.events && (() => {
                    const debugEvents = getUniqueDebugEvents(msg.events);
                    return debugEvents.length > 0 && (
                      <Box sx={{ pl: 2, borderLeft: `2px solid ${AGENT_CHAT_PALETTE.accent}30`, mb: 1 }}>
                        {debugEvents.map((event, idx) => (
                          <Accordion
                            key={`debug-msg-${msg.id}-${idx}`}
                            expanded={toolExpanded[`debug-msg-${msg.id}-${event.type}`] || false}
                            onChange={(_, expanded) => setToolExpanded(prev => ({ ...prev, [`debug-msg-${msg.id}-${event.type}`]: expanded }))}
                            disableGutters
                            elevation={0}
                            sx={{
                              minHeight: 20,
                              p: 0,
                              m: 0,
                              '& .MuiAccordionSummary-content': { my: 0 },
                              '&:before': { display: 'none' },
                              flexDirection: 'row-reverse',
                              gap: 1,
                              borderRadius: 1,
                              mb: 1,
                              bgcolor: 'transparent',
                            }}
                          >
                            <AccordionSummary
                              expandIcon={<ExpandIcon sx={{ fontSize: TYPOGRAPHY.body.size, color: AGENT_CHAT_PALETTE.accent }} />}
                              sx={{
                                minHeight: 20,
                                p: 0,
                                '& .MuiAccordionSummary-content': { my: 0 },
                                '& .MuiAccordionSummary-content.Mui-expanded': { my: 0 },
                                '&.Mui-expanded': { minHeight: 24, my: 0 },
                                flexDirection: 'row-reverse',
                                gap: 1,
                              }}
                            >
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                                <Typography variant="caption" sx={{
                                  fontFamily: 'monospace',
                                  color: AGENT_CHAT_PALETTE.accent,
                                  fontWeight: 600,
                                }}>
                                  {getDebugEventTitle(event.type)}
                                </Typography>
                                {/* Token count estimate */}
                                <Typography variant="caption" sx={{
                                  fontFamily: 'monospace',
                                  color: 'text.secondary',
                                  fontSize: TYPOGRAPHY.microMeta.size,
                                  opacity: 0.7,
                                  flex: 1,
                                }}>
                                  {(() => {
                                    const textContent = getDebugEventText(event);
                                    const tokens = estimateTokenCount(textContent);
                                    return `~${tokens.toLocaleString()} tokens`;
                                  })()}
                                </Typography>
                                <Tooltip title="Copy content">
                                  <IconButton
                                    size="small"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      // Copy parsed text content
                                      const textToCopy = getDebugEventText(event);
                                      navigator.clipboard.writeText(textToCopy || 'No content available');
                                    }}
                                    sx={{
                                      p: 0.25,
                                      opacity: 0.5,
                                      '&:hover': { opacity: 1, color: AGENT_CHAT_PALETTE.accent },
                                      flexShrink: 0,
                                    }}
                                  >
                                    <CopyIcon sx={{ fontSize: TYPOGRAPHY.microMeta.size }} />
                                  </IconButton>
                                </Tooltip>
                              </Box>
                            </AccordionSummary>
                            <AccordionDetails sx={{ p: 0, pl: 3, pt: 0, mt: 0 }}>
                              <Paper
                                variant="outlined"
                                sx={{
                                  p: 1.5,
                                  bgcolor: theme.palette.mode === 'dark' ? 'rgba(0,0,0,0.2)' : AGENT_CHAT_PALETTE.hoverBg,
                                  borderRadius: 2,
                                  borderColor: AGENT_CHAT_PALETTE.accent + '40'
                                }}
                              >
                                <Box component="pre" sx={{
                                  m: 0,
                                  fontSize: TYPOGRAPHY.caption.size,
                                  overflow: 'auto',
                                  color: 'text.primary',
                                  maxHeight: 400,
                                  whiteSpace: 'pre-wrap',
                                  wordBreak: 'break-word',
                                  fontFamily: 'monospace'
                                }}>
                                  {getDebugEventText(event) || 'No content available'}
                                </Box>
                              </Paper>
                            </AccordionDetails>
                          </Accordion>
                        ))}
                      </Box>
                    );
                  })()}

                  {!isUser && msg.events && msg.events.filter(e => e.type === 'tool_call').length > 0 && (
                    <Box sx={{ mb: 1, p: 1, bgcolor: theme.palette.mode === 'dark' ? 'rgba(0,0,0,0.2)' : AGENT_CHAT_PALETTE.hoverBg, borderRadius: 1.5 }}>
                      {renderToolList(mergeToolEvents(msg.events), `msg-${msg.id}`, toolExpanded, setToolExpanded, shouldShowExecutingAnimation, theme)}
                    </Box>
                  )}

                  {!isUser && msg.events ? (
                    <Box>
                      {/* Show thinking/reasoning accordion only if meaningful content exists */}
                      {(() => {
                        // Filter out internal routing/analysis messages that aren't real reasoning
                        const internalPatterns = [
                          /^Analyzing\.{0,3}\s*\[[\w-]+\]$/i,  // "Analyzing... [router]", "Analyzing... [run-script]"
                          /^Analyzing your request\.{0,3}$/i,  // "Analyzing your request..."
                          /^Processing\.{0,3}$/i,              // "Processing..."
                          /^Routing\.{0,3}$/i,                 // "Routing..."
                          /^Delegating\.{0,3}$/i,              // "Delegating..."
                        ];

                        const thinkingContent = msg.events
                          .filter(e => e.type === 'thinking')
                          .map(e => e.content)
                          .filter(content => {
                            // Filter out internal routing messages
                            const trimmed = content?.trim() || '';
                            return !internalPatterns.some(pattern => pattern.test(trimmed));
                          })
                          .join('\n\n')
                          .replace(/\n{3,}/g, '\n\n')
                          .trim();

                        // Only show if there's meaningful reasoning content
                        const hasRealThinking = thinkingContent.length > 50;

                        if (!hasRealThinking) return null;

                        return (
                          <Accordion elevation={0} disableGutters sx={{ bgcolor: 'transparent', '&:before': { display: 'none' }, mb: 1 }}>
                            <AccordionSummary
                              expandIcon={<ExpandIcon sx={{ color: 'text.secondary' }} />}
                              sx={{ minHeight: 'auto', p: 0, '& .MuiAccordionSummary-content': { m: 0, alignItems: 'center', gap: 1 } }}
                            >
                              <ThinkingIcon sx={{ fontSize: TYPOGRAPHY.body.size, color: 'text.secondary' }} />
                              <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic', fontSize: TYPOGRAPHY.body.size }}>
                                View Reasoning
                              </Typography>
                            </AccordionSummary>
                            <AccordionDetails sx={{ p: 0, pt: 1 }}>
                              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.6, color: 'text.secondary', fontSize: TYPOGRAPHY.navbarItem.size }}>
                                {thinkingContent}
                              </Typography>
                            </AccordionDetails>
                          </Accordion>
                        );
                      })()}

                      {/* Errors now shown inline with their tool calls via mergeToolEvents */}
                      {/* Show actual response - message/result events */}
                      {msg.events.filter(e => e.type === 'message' || e.type === 'result').length > 0 && (
                        <Box sx={assistantMarkdownSx(theme)}>
                          {renderContentWithVideos(dedupeEvents(msg.events.filter(e => e.type === 'message' || e.type === 'result')).map(e => e.content).join('\n\n').replace(/\n{3,}/g, '\n\n').trim())}
                        </Box>
                      )}
                    </Box>
                  ) : (
                    <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, justifyContent: 'space-between' }}>
                      <Box sx={{ flex: 1, minWidth: 0, ...assistantMarkdownSx(theme) }}>
                        {renderContentWithVideos((msg.content || '').replace(/\n{3,}/g, '\n\n').trim())}
                      </Box>
                      <Tooltip title="Copy message">
                        <IconButton
                          size="small"
                          onClick={() => navigator.clipboard.writeText(msg.content || '')}
                          sx={{ p: 0.25, opacity: 0.3, '&:hover': { opacity: 1, color: AGENT_CHAT_PALETTE.accent }, flexShrink: 0, mt: -0.5 }}
                        >
                          <CopyIcon sx={{ fontSize: TYPOGRAPHY.caption.size }} />
                        </IconButton>
                      </Tooltip>
                    </Box>
                  )}

                  {!isUser && (() => {
                    const uniqueEvents = dedupeEvents(msg.events || []);
                    const metrics = uniqueEvents.reduce((acc, e) => {
                      if (e.metrics) {
                        acc.duration += e.metrics.duration_ms;
                        acc.input += e.metrics.input_tokens;
                        acc.output += e.metrics.output_tokens;
                        acc.cacheRead += e.metrics.cache_read_tokens || 0;
                        acc.cacheCreation += e.metrics.cache_creation_tokens || 0;
                      }
                      return acc;
                    }, { duration: 0, input: 0, output: 0, cacheRead: 0, cacheCreation: 0 }) || { duration: 0, input: 0, output: 0, cacheRead: 0, cacheCreation: 0 };

                    const hasMetrics = metrics.duration > 0 || metrics.input > 0;

                    const copyMessage = () => {
                      const parts: string[] = [`${msg.agent || 'Assistant'}:`];
                      // Wall-clock timing header — surfaces the same gold the
                      // user wants logged: total answer latency and total
                      // reasoning latency, plus the number of thinking chunks.
                      // Both fields are optional; a turn that never thought
                      // (one-shot answers) shows only the answer elapsed.
                      if (msg.timing) {
                        const t = msg.timing;
                        const timingLines: string[] = [];
                        if (typeof t.answer_elapsed_ms === 'number') {
                          timingLines.push(`  answer_elapsed_ms=${t.answer_elapsed_ms}`);
                        }
                        if (typeof t.thinking_elapsed_ms === 'number') {
                          timingLines.push(`  thinking_elapsed_ms=${t.thinking_elapsed_ms}`);
                        }
                        if (t.thinking_chunks && t.thinking_chunks.length > 0) {
                          timingLines.push(`  thinking_chunks=${t.thinking_chunks.length}`);
                          timingLines.push(`  thinking_rhythm_ms=[${t.thinking_chunks.map(c => c.at_ms).join(',')}]`);
                        }
                        if (timingLines.length > 0) {
                          parts.push(`  timing:`);
                          parts.push(...timingLines);
                        }
                      }
                      const toolCalls = uniqueEvents.filter(e => e.type === 'tool_call');
                      // A call's result is the tool_result between it and the next call (tools run one at a
                      // time; a failed call has none). Matching by name showed the first result on every call.
                      const events = uniqueEvents;
                      const resultOf = (tool: typeof toolCalls[number]) => {
                        for (let j = events.indexOf(tool) + 1; j < events.length; j++) {
                          if (events[j].type === 'tool_call') return undefined;
                          if (events[j].type === 'tool_result') return events[j];
                        }
                        return undefined;
                      };

                      toolCalls.forEach(tool => {
                        const result = resultOf(tool);
                        parts.push(`\n  [Tool: ${tool.tool_name}]`);
                        if (tool.tool_params) {
                          parts.push(`  Input: ${JSON.stringify(tool.tool_params, null, 2).split('\n').join('\n  ')}`);
                        }
                        if (result?.tool_result) {
                          const resultStr = typeof result.tool_result === 'string'
                            ? result.tool_result
                            : JSON.stringify(result.tool_result, null, 2);
                          parts.push(`  Result: ${resultStr.split('\n').join('\n  ')}`);
                        }
                      });

                      const content = uniqueEvents
                        .filter(e => e.type === 'message' || e.type === 'result')
                        .map(e => e.content)
                        .join('\n')
                        .trim();
                      if (content) parts.push(`\n${content}`);

                      navigator.clipboard.writeText(parts.join('\n'));
                    };

                    const currentFeedback = messageFeedback[msg.id];

                    // Get first user message for context (used as task_description on the POST)
                    const userMsgIndex = messages.findIndex(m => m.id === msg.id) - 1;
                    const userPrompt = userMsgIndex >= 0 ? messages[userMsgIndex]?.content : undefined;

                    return (
                      <Box sx={{ mt: 1, pt: 0.75, borderTop: '1px solid', borderColor: theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.05)', display: 'flex', flexDirection: 'column', gap: 0.75 }}>
                        <MessageFeedbackBar
                          messageId={msg.id}
                          agentId={msg.agent || selectedAgentId}
                          prompt={userPrompt}
                          currentRating={currentFeedback}
                          submitFeedback={submitMessageFeedback}
                          variant="inline"
                        />

                        {(() => {
                          // TASK-175: Atlas named a better agent for this ask (ops → Masterchief, failure analysis → Sherlock).
                          const suggested = (msg.events || []).find(e => e.metrics?.suggest_agent)?.metrics;
                          if (!suggested?.suggest_agent || !onAskAgent
                              || !availableAgents.some(a => a.id === suggested.suggest_agent)) return null;
                          return (
                            <Box>
                              <Button
                                size="small"
                                sx={neutralButtonSx(P)}
                                startIcon={<AppIcon name="agent" />}
                                onClick={() => onAskAgent(suggested.suggest_agent as string, userPrompt)}
                              >
                                {`Ask ${suggested.suggest_name || suggested.suggest_agent}`}
                              </Button>
                            </Box>
                          );
                        })()}

                        {hasMetrics && (
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                            <Box sx={{ width: '1px', height: 12, bgcolor: theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)', flexShrink: 0 }} />

                            <Tooltip title="Processing time">
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, opacity: 0.5, flexShrink: 0 }}>
                                <TimeIcon sx={{ fontSize: TYPOGRAPHY.microMeta.size }} />
                                <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: TYPOGRAPHY.microMeta.size, whiteSpace: 'nowrap' }}>
                                  {(metrics.duration / 1000).toFixed(1)}s
                                </Typography>
                              </Box>
                            </Tooltip>
                            {/* Wall-clock timing row. Surfaced as the right
                                answer on whether this turn was a long-answer or
                                long-reasoning turn. Shown whenever the persisted
                                message carries at least one elapsed value
                                (answer or thinking). The thinking chip only
                                appears for turns that actually reasoned. */}
                            {msg.timing && typeof msg.timing.answer_elapsed_ms === 'number' && (
                              <Tooltip title="Wall-clock time from your message to the agent's terminal event (includes any silence gaps and tool execution).">
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, opacity: 0.5, flexShrink: 0 }} data-testid="msg-answer-elapsed">
                                  <TimeIcon sx={{ fontSize: TYPOGRAPHY.microMeta.size }} />
                                  <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: TYPOGRAPHY.microMeta.size, whiteSpace: 'nowrap' }}>
                                    {formatElapsed(msg.timing.answer_elapsed_ms)}
                                  </Typography>
                                </Box>
                              </Tooltip>
                            )}
                            {msg.timing && typeof msg.timing.thinking_elapsed_ms === 'number' && (
                              <Tooltip title={`Wall-clock time the model spent producing thinking chunks (${msg.timing.thinking_chunks?.length ?? 0} chunk${(msg.timing.thinking_chunks?.length ?? 0) === 1 ? '' : 's'}).`}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, opacity: 0.5, flexShrink: 0 }} data-testid="msg-thinking-elapsed">
                                  <ThinkingIcon sx={{ fontSize: TYPOGRAPHY.microMeta.size }} />
                                  <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: TYPOGRAPHY.microMeta.size, whiteSpace: 'nowrap' }}>
                                    {(msg.timing.thinking_elapsed_ms / 1000).toFixed(1)}s reasoning
                                  </Typography>
                                </Box>
                              </Tooltip>
                            )}
                            <Tooltip title={`Input: ${metrics.input.toLocaleString()} new tokens (billed) / Output: ${metrics.output.toLocaleString()} tokens (generated)${metrics.cacheRead > 0 ? ` / ${metrics.cacheRead.toLocaleString()} tokens served from cache (~90% cheaper, not counted in ↓)` : ''}${metrics.cacheCreation > 0 ? ` / ${metrics.cacheCreation.toLocaleString()} tokens written to cache this turn` : ''}`}>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, opacity: 0.5, flexShrink: 0 }}>
                                <TokenIcon sx={{ fontSize: TYPOGRAPHY.microMeta.size }} />
                                <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: TYPOGRAPHY.microMeta.size, whiteSpace: 'nowrap' }}>
                                  ↓{metrics.input.toLocaleString()} ↑{metrics.output.toLocaleString()}
                                </Typography>
                              </Box>
                            </Tooltip>
                            {metrics.cacheRead > 0 && (
                              <Tooltip title={`${metrics.cacheRead.toLocaleString()} tokens served from prompt cache (system prompt + tools) instead of being re-sent/rebilled as input`}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, opacity: 0.5, flexShrink: 0 }}>
                                  <CacheIcon sx={{ fontSize: TYPOGRAPHY.microMeta.size }} />
                                  <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: TYPOGRAPHY.microMeta.size, whiteSpace: 'nowrap' }}>
                                    {metrics.cacheRead.toLocaleString()} cached
                                  </Typography>
                                </Box>
                              </Tooltip>
                            )}
                            <Tooltip title="Copy message">
                              <IconButton
                                size="small"
                                onClick={copyMessage}
                                sx={{ p: 0, opacity: 0.5, '&:hover': { opacity: 1, color: AGENT_CHAT_PALETTE.accent }, flexShrink: 0 }}
                              >
                                <CopyIcon sx={{ fontSize: TYPOGRAPHY.caption.size }} />
                              </IconButton>
                            </Tooltip>
                          </Box>
                        )}
                      </Box>
                    );
                  })()}
                </Paper>
              </Box>
            );
          })}

          {/* Processing State - only show when viewing the conversation that's being processed */}
          {showProcessing && (
            <Box
              sx={{
                display: 'flex',
                gap: 1.5,
                flexDirection: 'row',
                alignSelf: 'flex-start',
                maxWidth: '100%',
                mb: 1
              }}
            >
              <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', pt: 0.5 }}>
                <Avatar
                  sx={{
                    width: 28,
                    height: 28,
                    fontSize: TYPOGRAPHY.microMeta.size,
                    fontWeight: 600,
                    bgcolor: getAgentColor(session?.active_agent || selectedAgentId, allAgentsMap, availableAgents, AGENT_CHAT_PALETTE.accent),
                    animation: 'pulse 1.5s infinite',
                  }}
                >
                  {getInitials(getAgentNickname(session?.active_agent || selectedAgentId, allAgentsMap, availableAgents))}
                </Avatar>
              </Box>

              <Paper
                elevation={0}
                sx={{
                  p: 1.5,
                  flex: 1,
                  bgcolor: theme.palette.mode === 'dark' ? AGENT_CHAT_PALETTE.agentBubble : P.surface,
                  border: '1px solid',
                  borderColor: theme.palette.mode === 'dark' ? AGENT_CHAT_PALETTE.agentBorder : P.borderColor,
                  borderRadius: 2.5,
                  borderTopRightRadius: 10,
                  borderTopLeftRadius: 4,
                  minWidth: 0,
                }}
              >
                {/* Agent name and status */}
                {(() => {
                  const activeAgent = session?.active_agent || selectedAgentId;
                  const hasToolEvents = currentEvents.some(e => e.type === 'tool_call');
                  // Extract skill name from skill_loaded event
                  const skillLoadedEvent = currentEvents.find(e => e.type === 'skill_loaded');
                  const skillName = skillLoadedEvent?.content || null;
                  
                  return (
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: hasToolEvents ? 1 : 0.5, flexWrap: 'wrap' }}>
                      <Typography variant="subtitle2" fontWeight={600} color="text.primary" sx={{ fontSize: TYPOGRAPHY.body.size }}>
                        {getAgentNickname(activeAgent, allAgentsMap, availableAgents)}
                      </Typography>
                      {skillName && (
                        <Chip
                          label={skillName}
                          size="small"
                          variant="outlined"
                          sx={{
                            height: 18,
                            fontSize: TYPOGRAPHY.microMeta.size,
                            borderColor: P.accent,
                            color: P.accentText,
                            fontWeight: 600,
                            '& .MuiChip-label': { px: 0.75 }
                          }}
                        />
                      )}
                      {/* Inline bouncing dots - always visible during processing */}
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, ml: 0.5 }}>
                        {[0, 1, 2].map((i) => (
                          <Box
                            key={i}
                            sx={{
                              width: 4, height: 4, borderRadius: '50%', bgcolor: AGENT_CHAT_PALETTE.accent,
                              animation: 'bounce 1.4s ease-in-out infinite',
                              animationDelay: `${i * 0.16}s`,
                              '@keyframes bounce': {
                                '0%, 80%, 100%': { transform: 'scale(0.6)', opacity: 0.4 },
                                '40%': { transform: 'scale(1)', opacity: 1 },
                              },
                            }}
                          />
                        ))}
                      </Box>
                      {/* Right-aligned live "answer elapsed" counter. ml:auto
                          pushes it to the far right of the same row as the
                          bouncing dots. The `0:00.0` value keeps the row from
                          jumping as soon as the timer begins; once the turn
                          finalizes (turnStartedAt flips to null) the chip is
                          hidden so it does not linger on a stale card. */}
                      {turnStartedAt != null && (
                        <Tooltip title="Wall-clock time since your message was sent. Freezes when the agent finishes.">
                          <Box
                            data-testid="atlas-answer-elapsed"
                            sx={{
                              ml: 'auto',
                              display: 'flex',
                              alignItems: 'center',
                              gap: 0.5,
                              px: 0.75,
                              py: 0.25,
                              borderRadius: 1,
                              bgcolor: theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
                              border: `1px solid ${P.borderColor}`,
                              fontFamily: 'monospace',
                              fontSize: TYPOGRAPHY.caption.size,
                              fontWeight: 600,
                              color: P.textSecondary,
                              flexShrink: 0,
                              minWidth: 56,
                              justifyContent: 'center',
                            }}
                          >
                            {formatElapsed(now - turnStartedAt)}
                          </Box>
                        </Tooltip>
                      )}
                    </Box>
                  );
                })()}

                {/* Debug Events - System Prompt and Context */}
                {(() => {
                  const debugEvents = getUniqueDebugEvents(currentEvents);
                  return debugEvents.length > 0 && (
                    <Box sx={{ pl: 2, borderLeft: `2px solid ${AGENT_CHAT_PALETTE.accent}30`, mb: 2 }}>
                      {debugEvents.map((event, idx) => (
                        <Accordion
                          key={`debug-${idx}`}
                          expanded={toolExpanded[`debug-${event.type}`] || false}
                          onChange={(_, expanded) => setToolExpanded(prev => ({ ...prev, [`debug-${event.type}`]: expanded }))}
                          disableGutters
                          elevation={0}
                          sx={{
                            minHeight: 24,
                            p: 0,
                            m: 0,
                            '& .MuiAccordionSummary-content': { my: 0 },
                            '&:before': { display: 'none' },
                            flexDirection: 'row-reverse',
                            gap: 1,
                            borderRadius: 1,
                            mb: 1,
                            bgcolor: 'transparent',
                          }}
                        >
                          <AccordionSummary
                            expandIcon={<ExpandIcon sx={{ fontSize: TYPOGRAPHY.body.size, color: AGENT_CHAT_PALETTE.accent }} />}
                            sx={{
                              minHeight: 24,
                              p: 0,
                              '& .MuiAccordionSummary-content': { my: 0 },
                              '& .MuiAccordionSummary-content.Mui-expanded': { my: 0 },
                              '&.Mui-expanded': { minHeight: 24, my: 0 },
                              flexDirection: 'row-reverse',
                              gap: 1,
                            }}
                          >
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                              <Typography variant="caption" sx={{
                                fontFamily: 'monospace',
                                color: AGENT_CHAT_PALETTE.accent,
                                fontWeight: 600,
                              }}>
                                {getDebugEventTitle(event.type)}
                              </Typography>
                              {/* Token count estimate */}
                              <Typography variant="caption" sx={{
                                fontFamily: 'monospace',
                                color: 'text.secondary',
                                fontSize: TYPOGRAPHY.microMeta.size,
                                opacity: 0.7,
                                flex: 1,
                              }}>
                                {(() => {
                                  const textContent = getDebugEventText(event);
                                  const tokens = estimateTokenCount(textContent);
                                  return `~${tokens.toLocaleString()} tokens`;
                                })()}
                              </Typography>
                              <Tooltip title="Copy content">
                                <IconButton
                                  size="small"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    // Copy parsed text content
                                    const textToCopy = getDebugEventText(event);
                                    navigator.clipboard.writeText(textToCopy || 'No content available');
                                  }}
                                  sx={{
                                    p: 0.25,
                                    opacity: 0.5,
                                    '&:hover': { opacity: 1, color: AGENT_CHAT_PALETTE.accent },
                                    flexShrink: 0,
                                  }}
                                >
                                  <CopyIcon sx={{ fontSize: TYPOGRAPHY.microMeta.size }} />
                                </IconButton>
                              </Tooltip>
                            </Box>
                          </AccordionSummary>
                          <AccordionDetails sx={{ p: 0, pl: 3, pt: 0, mt: 0 }}>
                            <Paper
                              variant="outlined"
                              sx={{
                                p: 1.5,
                                bgcolor: theme.palette.mode === 'dark' ? 'rgba(0,0,0,0.2)' : AGENT_CHAT_PALETTE.hoverBg,
                                borderRadius: 2,
                                borderColor: AGENT_CHAT_PALETTE.accent + '40'
                              }}
                            >
                              <Box component="pre" sx={{
                                m: 0,
                                fontSize: TYPOGRAPHY.caption.size,
                                overflow: 'auto',
                                color: 'text.primary',
                                maxHeight: 400,
                                whiteSpace: 'pre-wrap',
                                wordBreak: 'break-word',
                                fontFamily: 'monospace'
                              }}>
                                {getDebugEventText(event) || 'No content available'}
                              </Box>
                            </Paper>
                          </AccordionDetails>
                        </Accordion>
                      ))}
                  </Box>
                  );
                })()}


                {/* Live reasoning during the active turn. Starts auto-expanded
                    so the user sees the model's per-step narration as it
                    streams in; user can still collapse it manually. The same
                    reasoning is re-rendered on the completed message below,
                    collapsed by default. */}
                {(() => {
                  const internalPatterns = [
                    /^Analyzing\.{0,3}\s*\[[\w-]+\]$/i,
                    /^Analyzing your request\.{0,3}$/i,
                    /^Processing\.{0,3}$/i,
                    /^Routing\.{0,3}$/i,
                    /^Delegating\.{0,3}$/i,
                    /^Received\.{0,3}$/i,
                  ];
                  const liveThinking = currentEvents
                    .filter(e => e.type === 'thinking')
                    .map(e => e.content || '')
                    .filter(content => {
                      const trimmed = content.trim();
                      return trimmed && !internalPatterns.some(p => p.test(trimmed));
                    })
                    .join('\n\n')
                    .replace(/\n{3,}/g, '\n\n')
                    .trim();
                  if (liveThinking.length < 10) return null;
                  return (
                    <Accordion
                      elevation={0}
                      disableGutters
                      expanded={toolExpanded['live-reasoning'] ?? true}
                      onChange={(_, expanded) => setToolExpanded(prev => ({ ...prev, 'live-reasoning': expanded }))}
                      sx={{ bgcolor: 'transparent', '&:before': { display: 'none' }, mt: 1 }}
                    >
                      <AccordionSummary
                        expandIcon={<ExpandIcon sx={{ color: 'text.secondary' }} />}
                        sx={{ minHeight: 'auto', p: 0, '& .MuiAccordionSummary-content': { m: 0, alignItems: 'center', gap: 1, width: '100%' } }}
                      >
                        <ThinkingIcon sx={{ fontSize: TYPOGRAPHY.body.size, color: 'text.secondary' }} />
                        <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic', fontSize: TYPOGRAPHY.body.size }}>
                          Reasoning
                        </Typography>
                        {/* Right-aligned live "reasoning elapsed" counter.
                            Stamps the time the first thinking chunk arrived
                            and ticks `now - firstThinkingStartedAt` while
                            the stream is open. Freezes the moment the model
                            stops reasoning — once the difference between
                            `lastThinkingAt` and `now` exceeds ~600ms the
                            counter stops updating (the upstream `now` tick
                            keeps running for the answer timer; this chip
                            just shows the frozen value).
                            Sits on the same row as the icon + "Reasoning"
                            label, pushed right with ml:auto. */}
                        {firstThinkingStartedAt != null && (
                          <Tooltip title="Wall-clock time the model spent reasoning this turn. Freezes once the model stops producing thinking chunks.">
                            <Box
                              data-testid="atlas-reasoning-elapsed"
                              sx={{
                                ml: 'auto',
                                display: 'flex',
                                alignItems: 'center',
                                gap: 0.5,
                                px: 0.75,
                                py: 0.25,
                                borderRadius: 1,
                                bgcolor: theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
                                border: `1px solid ${P.borderColor}`,
                                fontFamily: 'monospace',
                                fontSize: TYPOGRAPHY.caption.size,
                                fontWeight: 600,
                                color: P.textSecondary,
                                flexShrink: 0,
                                minWidth: 56,
                                justifyContent: 'center',
                              }}
                            >
                              <Box
                                sx={{
                                  width: 6,
                                  height: 6,
                                  borderRadius: '50%',
                                  bgcolor: lastThinkingAt != null && now - lastThinkingAt < 600
                                    ? AGENT_CHAT_PALETTE.accent
                                    : 'text.disabled',
                                  animation: lastThinkingAt != null && now - lastThinkingAt < 600
                                    ? 'pulse 1.5s infinite'
                                    : 'none',
                                }}
                              />
                              {/* If reasoning stopped within the last tick, show
                                  the still-ticking counter. Otherwise freeze it
                                  on lastThinkingAt so the user sees the final
                                  reasoning duration without waiting for the
                                  answer to finish. */}
                              {lastThinkingAt != null && now - lastThinkingAt < 600
                                ? formatElapsed(now - firstThinkingStartedAt)
                                : formatElapsed((lastThinkingAt ?? now) - firstThinkingStartedAt)}
                            </Box>
                          </Tooltip>
                        )}
                      </AccordionSummary>
                      <AccordionDetails sx={{ p: 0, pt: 1 }}>
                        <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.5, color: 'text.secondary', fontSize: TYPOGRAPHY.body.size }}>
                          {liveThinking}
                        </Typography>
                      </AccordionDetails>
                    </Accordion>
                  );
                })()}

                {currentEvents.some(e => e.type === 'tool_call') && (
                  <Box sx={{ mt: 1, pl: 2, borderLeft: `2px solid ${session?.active_agent ? getAgentColor(session.active_agent, allAgentsMap, availableAgents, AGENT_CHAT_PALETTE.accent) : AGENT_CHAT_PALETTE.accent}40` }}>
                    {/* Newest first, last 5 shown; reasoning sits above */}
                    {renderToolList(mergeToolEvents(currentEvents), 'live', toolExpanded, setToolExpanded, shouldShowExecutingAnimation, theme)}
                  </Box>
                )}

                {currentEvents.some(e => e.type === 'approval_required') && (
                  <Box sx={{ p: 1.5, mt: 1.5, border: '1px solid', borderColor: AGENT_CHAT_PALETTE.accent, borderRadius: 1.5, bgcolor: `${AGENT_CHAT_PALETTE.accent}10` }}>
                    <Typography variant="subtitle2" sx={{ color: AGENT_CHAT_PALETTE.accent, fontWeight: 600 }} gutterBottom>
                      <AppIcon name="lock" /> Permission Request
                    </Typography>
                    <Typography variant="caption" sx={{ mb: 1.5, display: 'block', color: 'text.secondary' }}>
                      The agent wants to perform a critical action.
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      <button
                        onClick={() => handleApproval(true)}
                        style={{
                          padding: '4px 12px',
                          backgroundColor: AGENT_CHAT_PALETTE.accent,
                          color: '#fff',
                          border: 'none',
                          borderRadius: '4px',
                          cursor: 'pointer',
                          fontSize: TYPOGRAPHY.body.size,
                          fontWeight: 600,
                          textTransform: 'none',
                        }}
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => handleApproval(false)}
                        style={{
                          padding: '4px 12px',
                          backgroundColor: 'transparent',
                          color: 'inherit',
                          border: '1px solid',
                          borderColor: 'currentColor',
                          borderRadius: '4px',
                          cursor: 'pointer',
                          fontSize: TYPOGRAPHY.body.size,
                          textTransform: 'none',
                        }}
                      >
                        Deny
                      </button>
                    </Box>
                  </Box>
                )}
              </Paper>
            </Box>
          )}

          {afterAnswer}

          <AgentChatErrorAlert error={error} />

          <div ref={messagesEndRef} />
        </Box>
      </Box>

      {/* Input Area — capped to the same 820px reading column as the messages
          above so the message box and the 3 action buttons (copy / export /
          clear) stay coherent and vertically aligned with the text container. */}
      <Box sx={{ width: '100%', maxWidth: 820, mx: 'auto' }}>
        <ChatInput
          input={input}
          setInput={setInput}
          sendMessage={sendMessage}
          isProcessing={isProcessing}
          stopGeneration={stopGeneration}
          messages={messages}
          conversations={conversations}
          clearHistory={clearHistory}
        />
      </Box>
    </>
  );
};
