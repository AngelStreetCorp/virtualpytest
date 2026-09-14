/**
 * Chat Messages Component - Main Chat Area
 *
 * Handles message rendering, processing state, empty state, and all chat content.
 */

import React, { useEffect } from 'react';
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
import Visibility from '@mui/icons-material/Visibility';
import VisibilityOff from '@mui/icons-material/VisibilityOff';
import {
  Terminal as ConsoleIcon,
  CheckCircle as SuccessIcon,
  Error as ErrorIcon,
  ExpandMore as ExpandIcon,
  Psychology as ThinkingIcon,
  ThumbUp,
  ThumbDown,
  ContentCopy as CopyIcon,
  AccessTime as TimeIcon,
  DataUsage as TokenIcon,
  Lock as CacheIcon,
  Person as PersonIcon,
} from '@mui/icons-material';
import { useTheme } from '@mui/material/styles';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { AGENT_CHAT_PALETTE } from '../../constants/agentChatTheme';
import { dedupeEvents, getInitials, mergeToolEvents } from '../../utils/agentChatUtils';
import { AgentEvent, Message } from '../../hooks/aiagent/useAgentChat';
import { useToolExecutionTiming } from '../../hooks/aiagent/useToolExecutionTiming';
import { ChatInput } from './ChatInput';

// Colorize PASSED (green) and FAILED (red) in agent responses
// Handles both strings and React node arrays from ReactMarkdown
const colorizeStatus = (node: React.ReactNode): React.ReactNode => {
  // Handle strings - split and colorize PASSED/FAILED
  if (typeof node === 'string') {
    const parts = node.split(/(PASSED|FAILED)/g);
    return parts.map((part, i) => {
      if (part === 'PASSED') return <span key={i} style={{ color: '#22c55e', fontWeight: 600 }}>PASSED</span>;
      if (part === 'FAILED') return <span key={i} style={{ color: '#ef4444', fontWeight: 600 }}>FAILED</span>;
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
  submitMessageFeedback: (messageId: string, rating: number, agentId: string, prompt?: string) => void;
  input: string;
  sendMessage: () => void;
  setInput: (input: string) => void;
  handleApproval: (approved: boolean) => void;
  toolExpanded: Record<string, boolean>;
  setToolExpanded: (updater: (prev: Record<string, boolean>) => Record<string, boolean>) => void;
  messagesEndRef: React.RefObject<HTMLDivElement>;
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
  activeKeyEnv: string;
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

const renderToolActivity = (
  event: AgentEvent,
  idx: number,
  toolExpanded: Record<string, boolean>,
  setToolExpanded: (updater: (prev: Record<string, boolean>) => Record<string, boolean>) => void,
  shouldShowExecutingAnimation: (key: string, isExecuting: boolean) => boolean,
  theme: any
) => {
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
        expandIcon={<ExpandIcon sx={{ fontSize: 14, color: hasError ? 'error.main' : showExecutingAnimation ? AGENT_CHAT_PALETTE.accent : 'text.disabled' }} />}
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
            fontSize: 12,
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
              <CopyIcon sx={{ fontSize: 11 }} />
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
            <ErrorIcon sx={{ fontSize: 12, color: 'error.main' }} /> :
            <SuccessIcon sx={{ fontSize: 12, color: 'success.main' }} />
          }
        </Box>
      </AccordionSummary>
      <AccordionDetails sx={{ p: 0, pl: 3 }}>
        {hasError && (
          <Alert
            severity="error"
            sx={{
              mb: 1.5,
              fontSize: '0.75rem',
              '& .MuiAlert-message': { fontSize: '0.75rem' }
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
            bgcolor: theme.palette.mode === 'dark' ? 'rgba(0,0,0,0.2)' : 'grey.50',
            borderColor: hasError
              ? 'error.main'
              : showExecutingAnimation
                ? `${AGENT_CHAT_PALETTE.accent}40`
                : (theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.1)' : 'grey.300'),
            borderRadius: 2
          }}
        >
          <Typography variant="caption" display="block" color="text.secondary" gutterBottom>Input</Typography>
          <Box component="pre" sx={{ m: 0, fontSize: '0.7rem', overflow: 'auto', color: 'text.primary', maxHeight: 150 }}>
            {event.tool_params ? JSON.stringify(event.tool_params, null, 2) : '{}'}
          </Box>

          {/* Only show Result section when there's no error (error already shown in alert above) */}
          {!hasError && !isExecuting && (
            <>
              <Typography variant="caption" display="block" color="text.secondary" gutterBottom sx={{ mt: 1.5 }}>
                Result
              </Typography>
              <Box component="pre" sx={{ m: 0, fontSize: '0.7rem', overflow: 'auto', color: 'text.primary', maxHeight: 300 }}>
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
    fontSize: '0.85em',
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
      fontSize: '0.8em',
    },
  },
  '& h1': { fontSize: '0.96rem', fontWeight: 700, m: 0, mt: 0.75, mb: 0.5 },
  '& h2': { fontSize: '0.92rem', fontWeight: 700, m: 0, mt: 0.75, mb: 0.5 },
  '& h3, & h4, & h5, & h6': { fontSize: '0.88rem', fontWeight: 600, m: 0, mt: 0.75, mb: 0.4 },
  '& ul, & ol': { m: 0, pl: 2, '& li': { mb: 0.2 } },
  '& table': {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: '0.78rem',
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
  fontSize: '0.82rem',
  lineHeight: 1.55,
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
  messageFeedback,
  submitMessageFeedback,
  input,
  sendMessage,
  setInput,
  handleApproval,
  toolExpanded,
  setToolExpanded,
  messagesEndRef,
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
  activeKeyEnv,
}) => {
  const theme = useTheme();
  const [showKey, setShowKey] = React.useState(false);

  // Tool execution timing hook (5-second delay for animations)
  const { shouldShowExecutingAnimation } = useToolExecutionTiming();

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

  // Determine if we should show empty state
  const isSystemConversation = activeConversationId?.startsWith('bg_');
  const hasNoMessages = messages.length === 0;
  const onChatsTabWithNoRegularConvo = sidebarTab === 'chats' && (!activeConversationId || isSystemConversation);
  // Show system placeholder only when on system tab AND (no conversation selected OR selected conversation is not a system one)
  const onSystemTabWithNoSelection = sidebarTab === 'system' && (!activeConversationId || !isSystemConversation);

  // Debug: Log render conditions
  console.log('[ChatMessages] Render check:', {
    activeConversationId,
    sidebarTab,
    messagesLength: messages.length,
    isSystemConversation,
    hasNoMessages,
    onChatsTabWithNoRegularConvo,
    onSystemTabWithNoSelection,
    status
  });

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
        <Box sx={{ width: '100%' }}>

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
                <Box sx={{ display: 'flex', justifyContent: 'center', mb: 1.5 }}>
                  <Box sx={{ p: 1.5, borderRadius: '50%', bgcolor: 'warning.main', display: 'flex' }}>
                    <VpnKeyIcon sx={{ fontSize: 28, color: 'background.paper' }} />
                  </Box>
                </Box>
                <Typography variant="h6" gutterBottom>AI Provider Configuration Required</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2.5 }}>
                  The active provider is <strong>{activeProvider}</strong>{activeModel ? ` using ${activeModel}` : ''}. Enter its API key here, or set it permanently in{' '}
                  <Typography component="span" variant="body2" color="primary.main" sx={{ cursor: 'pointer', textDecoration: 'underline' }}
                    onClick={() => window.location.href = '/configuration/settings?tab=ai'}
                  >
                    Settings → AI
                  </Typography>
                  {' '}or add <code>{activeKeyEnv}</code> to your server <code>.env</code>.
                </Typography>
                <TextField
                  fullWidth
                  size="small"
                  label={`${activeProvider} API Key`}
                  placeholder={activeProvider === 'anthropic' ? 'sk-ant-...' : activeProvider === 'openrouter' ? 'sk-or-v1-...' : 'Paste provider API key'}
                  value={apiKeyInput}
                  onChange={e => setApiKeyInput(e.target.value)}
                  type={showKey ? 'text' : 'password'}
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
                  {isValidating ? 'Validating…' : 'Save & Connect'}
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
                      sx={{ width: 28, height: 28, fontSize: 12, bgcolor: theme.palette.mode === 'dark' ? '#5c6bc0' : '#3f51b5', fontWeight: 600 }}
                    >
                      <PersonIcon sx={{ fontSize: 16 }} />
                    </Avatar>
                  ) : (
                    <Avatar sx={{ width: 28, height: 28, fontSize: 12, bgcolor: agentColor, fontWeight: 600 }}>
                      {getInitials(msg.agent || 'QA')}
                    </Avatar>
                  )}
                </Box>

                <Paper
                  elevation={0}
                  sx={{
                    p: 1.5,
                    flex: 1,
                    bgcolor: theme.palette.mode === 'dark'
                      ? (isUser ? AGENT_CHAT_PALETTE.userBubble : AGENT_CHAT_PALETTE.agentBubble)
                      : (isUser ? 'grey.100' : 'grey.50'),
                    border: isUser
                      ? `1px solid ${theme.palette.mode === 'dark' ? `${AGENT_CHAT_PALETTE.accent}50` : `${AGENT_CHAT_PALETTE.accent}40`}`
                      : `1px solid ${theme.palette.mode === 'dark' ? AGENT_CHAT_PALETTE.agentBorder : 'grey.200'}`,
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
                          <Typography variant="subtitle2" fontWeight={600} color="text.primary" sx={{ fontSize: '0.8rem' }}>
                      {getAgentNickname(msg.agent, allAgentsMap, availableAgents)}
                    </Typography>
                          {skillName && (
                            <Chip
                              label={skillName}
                              size="small"
                              variant="outlined"
                              sx={{
                                height: 18,
                                fontSize: '0.65rem',
                                borderColor: '#FFD700',
                                color: '#FFD700',
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
                                  fontSize: '0.65rem',
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
                              expandIcon={<ExpandIcon sx={{ fontSize: 14, color: AGENT_CHAT_PALETTE.accent }} />}
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
                                  fontSize: '0.65rem',
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
                                    <CopyIcon sx={{ fontSize: 11 }} />
                                  </IconButton>
                                </Tooltip>
                              </Box>
                            </AccordionSummary>
                            <AccordionDetails sx={{ p: 0, pl: 3, pt: 0, mt: 0 }}>
                              <Paper
                                variant="outlined"
                                sx={{
                                  p: 1.5,
                                  bgcolor: theme.palette.mode === 'dark' ? 'rgba(0,0,0,0.2)' : 'grey.50',
                                  borderRadius: 2,
                                  borderColor: AGENT_CHAT_PALETTE.accent + '40'
                                }}
                              >
                                <Box component="pre" sx={{
                                  m: 0,
                                  fontSize: '0.75rem',
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
                    <Box sx={{ mb: 1, p: 1, bgcolor: theme.palette.mode === 'dark' ? 'rgba(0,0,0,0.2)' : 'grey.100', borderRadius: 1.5 }}>
                      {mergeToolEvents(msg.events).map((event, idx) => renderToolActivity(event, idx, toolExpanded, setToolExpanded, shouldShowExecutingAnimation, theme))}
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
                              <ThinkingIcon sx={{ fontSize: 14, color: 'text.secondary' }} />
                              <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic', fontSize: '0.85rem' }}>
                                View Reasoning
                              </Typography>
                            </AccordionSummary>
                            <AccordionDetails sx={{ p: 0, pt: 1 }}>
                              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.5, color: 'text.secondary', fontSize: '0.85rem' }}>
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
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          rehypePlugins={[rehypeRaw]}
                          components={{
                            a: ({ href, children }) => (
                              <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
                            ),
                            p: ({ children }) => <p>{colorizeStatus(children)}</p>,
                          }}
                        >
                            {dedupeEvents(msg.events.filter(e => e.type === 'message' || e.type === 'result')).map(e => e.content).join('\n\n').replace(/\n{3,}/g, '\n\n').trim()}
                          </ReactMarkdown>
                        </Box>
                      )}
                    </Box>
                  ) : (
                    <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, justifyContent: 'space-between' }}>
                      <Box sx={{ flex: 1, minWidth: 0, ...assistantMarkdownSx(theme) }}>
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          rehypePlugins={[rehypeRaw]}
                          components={{
                            a: ({ href, children }) => (
                              <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
                            ),
                            p: ({ children }) => <p>{colorizeStatus(children)}</p>,
                          }}
                        >
                          {(msg.content || '').replace(/\n{3,}/g, '\n\n').trim()}
                        </ReactMarkdown>
                      </Box>
                      <Tooltip title="Copy message">
                        <IconButton
                          size="small"
                          onClick={() => navigator.clipboard.writeText(msg.content || '')}
                          sx={{ p: 0.25, opacity: 0.3, '&:hover': { opacity: 1, color: AGENT_CHAT_PALETTE.accent }, flexShrink: 0, mt: -0.5 }}
                        >
                          <CopyIcon sx={{ fontSize: 12 }} />
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
                      const toolCalls = uniqueEvents.filter(e => e.type === 'tool_call');
                      const toolResults = uniqueEvents.filter(e => e.type === 'tool_result');

                      toolCalls.forEach(tool => {
                        const result = toolResults.find(r => r.tool_name === tool.tool_name);
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
                    const isPositive = currentFeedback === 5;
                    const isNegative = currentFeedback === 1;

                    // Get first user message for context
                    const userMsgIndex = messages.findIndex(m => m.id === msg.id) - 1;
                    const userPrompt = userMsgIndex >= 0 ? messages[userMsgIndex]?.content : undefined;

                    return (
                      <Box sx={{ mt: 1, pt: 0.75, borderTop: '1px solid', borderColor: theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.05)', display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'nowrap' }}>
                        {/* Feedback buttons */}
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexShrink: 0 }}>
                          <Tooltip title={isPositive ? "Remove helpful rating" : "Mark as helpful"}>
                            <IconButton
                              size="small"
                              onClick={() => submitMessageFeedback(msg.id, 5, msg.agent || selectedAgentId, userPrompt)}
                              sx={{
                                p: 0.25,
                                color: isPositive ? '#22c55e' : 'text.disabled',
                                bgcolor: isPositive ? 'rgba(34, 197, 94, 0.15)' : 'transparent',
                                borderRadius: 1,
                                transition: 'all 0.2s',
                                '&:hover': {
                                  color: '#22c55e',
                                  bgcolor: 'rgba(34, 197, 94, 0.1)',
                                },
                              }}
                            >
                              <ThumbUp sx={{ fontSize: 13 }} />
                            </IconButton>
                          </Tooltip>
                          <Tooltip title={isNegative ? "Remove not helpful rating" : "Mark as not helpful"}>
                            <IconButton
                              size="small"
                              onClick={() => submitMessageFeedback(msg.id, 1, msg.agent || selectedAgentId, userPrompt)}
                              sx={{
                                p: 0.25,
                                color: isNegative ? '#ef4444' : 'text.disabled',
                                bgcolor: isNegative ? 'rgba(239, 68, 68, 0.15)' : 'transparent',
                                borderRadius: 1,
                                transition: 'all 0.2s',
                                '&:hover': {
                                  color: '#ef4444',
                                  bgcolor: 'rgba(239, 68, 68, 0.1)',
                                },
                              }}
                            >
                              <ThumbDown sx={{ fontSize: 13 }} />
                            </IconButton>
                          </Tooltip>
                        </Box>

                        {hasMetrics && (
                          <>
                            <Box sx={{ width: '1px', height: 12, bgcolor: theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)', flexShrink: 0 }} />

                            <Tooltip title="Processing time">
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, opacity: 0.5, flexShrink: 0 }}>
                                <TimeIcon sx={{ fontSize: 10 }} />
                                <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: '0.65rem', whiteSpace: 'nowrap' }}>
                                  {(metrics.duration / 1000).toFixed(1)}s
                                </Typography>
                              </Box>
                            </Tooltip>
                            <Tooltip title={`Input: ${metrics.input.toLocaleString()} new tokens (billed) / Output: ${metrics.output.toLocaleString()} tokens (generated)${metrics.cacheRead > 0 ? ` / ${metrics.cacheRead.toLocaleString()} tokens served from cache (~90% cheaper, not counted in ↓)` : ''}${metrics.cacheCreation > 0 ? ` / ${metrics.cacheCreation.toLocaleString()} tokens written to cache this turn` : ''}`}>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, opacity: 0.5, flexShrink: 0 }}>
                                <TokenIcon sx={{ fontSize: 10 }} />
                                <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: '0.65rem', whiteSpace: 'nowrap' }}>
                                  ↓{metrics.input.toLocaleString()} ↑{metrics.output.toLocaleString()}
                                </Typography>
                              </Box>
                            </Tooltip>
                            {metrics.cacheRead > 0 && (
                              <Tooltip title={`${metrics.cacheRead.toLocaleString()} tokens served from prompt cache (system prompt + tools) instead of being re-sent/rebilled as input`}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, opacity: 0.5, flexShrink: 0 }}>
                                  <CacheIcon sx={{ fontSize: 10 }} />
                                  <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: '0.65rem', whiteSpace: 'nowrap' }}>
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
                                <CopyIcon sx={{ fontSize: 12 }} />
                              </IconButton>
                            </Tooltip>
                          </>
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
                    fontSize: 11,
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
                  bgcolor: theme.palette.mode === 'dark' ? AGENT_CHAT_PALETTE.agentBubble : 'grey.50',
                  border: '1px solid',
                  borderColor: theme.palette.mode === 'dark' ? AGENT_CHAT_PALETTE.agentBorder : 'grey.200',
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
                      <Typography variant="subtitle2" fontWeight={600} color="text.primary" sx={{ fontSize: '0.8rem' }}>
                        {getAgentNickname(activeAgent, allAgentsMap, availableAgents)}
                      </Typography>
                      {skillName && (
                        <Chip
                          label={skillName}
                          size="small"
                          variant="outlined"
                          sx={{
                            height: 18,
                            fontSize: '0.65rem',
                            borderColor: '#FFD700',
                            color: '#FFD700',
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
                            expandIcon={<ExpandIcon sx={{ fontSize: 14, color: AGENT_CHAT_PALETTE.accent }} />}
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
                                fontSize: '0.65rem',
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
                                  <CopyIcon sx={{ fontSize: 11 }} />
                                </IconButton>
                              </Tooltip>
                            </Box>
                          </AccordionSummary>
                          <AccordionDetails sx={{ p: 0, pl: 3, pt: 0, mt: 0 }}>
                            <Paper
                              variant="outlined"
                              sx={{
                                p: 1.5,
                                bgcolor: theme.palette.mode === 'dark' ? 'rgba(0,0,0,0.2)' : 'grey.50',
                                borderRadius: 2,
                                borderColor: AGENT_CHAT_PALETTE.accent + '40'
                              }}
                            >
                              <Box component="pre" sx={{
                                m: 0,
                                fontSize: '0.75rem',
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

                {currentEvents.some(e => e.type === 'tool_call') && (
                  <Box sx={{ pl: 2, borderLeft: `2px solid ${session?.active_agent ? getAgentColor(session.active_agent, allAgentsMap, availableAgents, AGENT_CHAT_PALETTE.accent) : AGENT_CHAT_PALETTE.accent}40` }}>
                    {/* Tool calls only - thinking messages hidden */}
                    {mergeToolEvents(currentEvents).map((event, idx) => renderToolActivity(event, idx, toolExpanded, setToolExpanded, shouldShowExecutingAnimation, theme))}
                  </Box>
                )}

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
                        sx={{ minHeight: 'auto', p: 0, '& .MuiAccordionSummary-content': { m: 0, alignItems: 'center', gap: 1 } }}
                      >
                        <ThinkingIcon sx={{ fontSize: 14, color: 'text.secondary' }} />
                        <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic', fontSize: '0.85rem' }}>
                          Reasoning
                        </Typography>
                      </AccordionSummary>
                      <AccordionDetails sx={{ p: 0, pt: 1 }}>
                        <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.5, color: 'text.secondary', fontSize: '0.85rem' }}>
                          {liveThinking}
                        </Typography>
                      </AccordionDetails>
                    </Accordion>
                  );
                })()}

                {currentEvents.some(e => e.type === 'approval_required') && (
                  <Box sx={{ p: 1.5, mt: 1.5, border: '1px solid', borderColor: AGENT_CHAT_PALETTE.accent, borderRadius: 1.5, bgcolor: `${AGENT_CHAT_PALETTE.accent}10` }}>
                    <Typography variant="subtitle2" sx={{ color: AGENT_CHAT_PALETTE.accent, fontWeight: 600 }} gutterBottom>
                      🔐 Permission Request
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
                          fontSize: '0.8rem',
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
                          fontSize: '0.8rem',
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

          {error && (
            <Alert severity="error" sx={{ mt: 1 }} onClose={() => {}}>
              {error}
            </Alert>
          )}

          <div ref={messagesEndRef} />
        </Box>
      </Box>

      {/* Input Area */}
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
    </>
  );
};
