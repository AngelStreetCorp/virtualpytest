/**
 * Conversation List Component - Left Sidebar
 *
 * Handles conversations, background agents, and system tabs.
 */

import React from 'react';
import {
  Box,
  Typography,
  Button,
  IconButton,
  Tabs,
  Tab,
  Chip,
  Tooltip,
  Fade,
} from '@mui/material';
import {
  Add as AddIcon,
  Chat as ChatIcon,
  Devices as DevicesIcon,
  ClearOutlined as ClearIcon,
  ExpandMore as ExpandIcon,
  Refresh as ReloadIcon,
} from '@mui/icons-material';
import { useTheme } from '@mui/material/styles';
import { APP_CONFIG } from '../../config/constants';
import { AGENT_CHAT_LAYOUT } from '../../constants/agentChatTheme';
import { BackgroundTask, BackgroundAgentInfo } from '../../hooks/aiagent/useAgentChat';

const { sidebarWidth: SIDEBAR_WIDTH, maxRecentBackgroundTasks: MAX_RECENT_TASKS } = AGENT_CHAT_LAYOUT;

interface ConversationListProps {
  showHistory: boolean;
  sidebarTab: 'system' | 'chats';
  handleSidebarTabChange: (newTab: 'system' | 'chats') => void;
  conversations: Array<{
    id: string;
    title: string;
    createdAt: string;
  }>;
  activeConversationId: string | null;
  backgroundAgents: BackgroundAgentInfo[];
  backgroundTasks: Record<string, { inProgress: BackgroundTask[]; recent: BackgroundTask[] }>;
  backgroundExpanded: Record<string, boolean>;
  setBackgroundExpanded: (updater: (prev: Record<string, boolean>) => Record<string, boolean>) => void;
  createNewConversation: () => void;
  switchConversation: (conversationId: string) => void;
  deleteConversation: (conversationId: string) => void;
  clearBackgroundHistory: (agentId: string) => void;
  reloadSkills: () => Promise<any>;
  /** Optional override for sidebar width (px) when expanded. */
  width?: number;
}

// Generic Background Agent Section
// Renders a section for any agent with background_queues config
const renderBackgroundAgentSection = (
  agent: BackgroundAgentInfo,
  backgroundTasks: Record<string, { inProgress: BackgroundTask[]; recent: BackgroundTask[] }>,
  backgroundExpanded: Record<string, boolean>,
  setBackgroundExpanded: (updater: (prev: Record<string, boolean>) => Record<string, boolean>) => void,
  switchConversation: (conversationId: string) => void,
  activeConversationId: string | null,
  sidebarTab: 'system' | 'chats',
  clearBackgroundHistory: (agentId: string) => void,
  theme: any
) => {
  const agentTasks = backgroundTasks[agent.id] || { inProgress: [], recent: [] };

  // Combine in-progress and recent tasks
  const allTasks = [
    ...agentTasks.inProgress.map(t => ({ ...t, isInProgress: true })),
    ...agentTasks.recent.slice(0, MAX_RECENT_TASKS).map(t => ({ ...t, isInProgress: false }))
  ];

  const totalActive = allTasks.length;
  const isExpanded = backgroundExpanded[agent.id] || false;

  // Get status icon - simplified to tick or cross
  const getTaskIcon = (task: BackgroundTask & { isInProgress?: boolean }) => {
    if (task.isInProgress) return null; // Will show pulsing dot

    // Check for failure indicators
    const isFailed = task.classification && [
      'VALID_FAIL', 'BUG', 'SCRIPT_ISSUE', 'SYSTEM_ISSUE'
    ].includes(task.classification);

    return isFailed ? '✗' : '✓';
  };

  return (
    <Box key={agent.id} sx={{ px: 1, mb: 1 }}>
      {/* Agent Section Header */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 0.5,
          px: 1.5,
          py: 0.75,
          borderRadius: 1.5,
        }}
      >
        <ExpandIcon
          onClick={() => setBackgroundExpanded(prev => ({ ...prev, [agent.id]: !isExpanded }))}
          sx={{
            fontSize: 16,
            color: theme.palette.text.secondary,
            transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s',
            cursor: 'pointer',
            '&:hover': { color: 'text.primary' },
          }}
        />

        <Typography
          onClick={() => setBackgroundExpanded(prev => ({ ...prev, [agent.id]: !isExpanded }))}
          variant="body2"
          sx={{
            flex: 1,
            fontSize: '0.85rem',
            fontWeight: 500,
            cursor: 'pointer',
            '&:hover': { color: 'text.primary' },
          }}
        >
          # {agent.nickname}
        </Typography>

        {totalActive > 0 ? (
          <Chip
            label={totalActive}
            size="small"
            sx={{
              height: 18,
              minWidth: 18,
              fontSize: '0.7rem',
              bgcolor: agent.color || theme.palette.accent,
              color: '#fff',
              '& .MuiChip-label': { px: 0.75 },
            }}
          />
        ) : (
          <Typography variant="caption" sx={{ color: 'text.disabled', fontSize: '0.75rem' }}>
            (0)
          </Typography>
        )}

        {/* Clear history button */}
        {totalActive > 0 && (
          <Tooltip title={`Clear ${agent.nickname} history`}>
            <IconButton
              size="small"
              onClick={(e) => {
                e.stopPropagation();
                clearBackgroundHistory(agent.id);
              }}
              sx={{
                p: 0.25,
                opacity: 0.4,
                '&:hover': { opacity: 1, color: 'error.main' },
              }}
            >
              <ClearIcon sx={{ fontSize: 14 }} />
            </IconButton>
          </Tooltip>
        )}
      </Box>

      {/* Expandable Task List */}
      {totalActive > 0 && (
        <Fade in={isExpanded}>
          <Box sx={{ pl: 2, pr: 1, mt: 0.5 }}>
            {allTasks.map(task => {
              const icon = getTaskIcon(task);

              return (
                <Box
                  key={task.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    console.log('[AgentChat] Task clicked:', task.id, task.title, task.conversationId);
                    switchConversation(task.conversationId);
                  }}
                  sx={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 1,
                    px: 1.5,
                    py: 1,
                    borderRadius: 1.5,
                    cursor: 'pointer',
                    bgcolor: task.conversationId === activeConversationId && sidebarTab === 'system'
                      ? (theme.palette.mode === 'dark' ? '#1a1a1a' : 'grey.200')
                      : 'transparent',
                    '&:hover': {
                      bgcolor: theme.palette.mode === 'dark' ? '#1a1a1a' : 'grey.100',
                    },
                    transition: 'background-color 0.15s',
                  }}
                >
                  {task.isInProgress ? (
                    <Box sx={{
                      width: 14,
                      height: 14,
                      mt: 0.3,
                      borderRadius: '50%',
                      bgcolor: agent.color || theme.palette.accent,
                      flexShrink: 0,
                      animation: 'pulse 2s ease-in-out infinite',
                      '@keyframes pulse': {
                        '0%, 100%': { opacity: 1, transform: 'scale(1)' },
                        '50%': { opacity: 0.5, transform: 'scale(0.8)' },
                      },
                    }} />
                  ) : (
                    <Box sx={{
                      fontSize: 14,
                      minWidth: 14,
                      height: 14,
                      mt: 0.3,
                      textAlign: 'center',
                      flexShrink: 0,
                      fontWeight: 700,
                      lineHeight: 1,
                      color: icon === '✗' ? '#ef4444' : '#22c55e'
                    }}>
                      {icon}
                    </Box>
                  )}

                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    {/* Script name */}
                    <Typography
                      variant="body2"
                      sx={{
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        color: task.conversationId === activeConversationId ? 'text.primary' : 'text.secondary',
                        fontSize: '0.85rem',
                      }}
                    >
                      {task.subtitle ? `${task.title}-${task.subtitle}` : task.title}
                    </Typography>
                    {/* Date/time - same format as Chats tab */}
                    <Typography
                      variant="caption"
                      sx={{
                        display: 'block',
                        color: theme.palette.text.secondary,
                        fontSize: '0.65rem',
                        opacity: 0.7,
                        mt: -0.25,
                      }}
                    >
                      {(() => {
                        const d = new Date(task.startedAt);
                        const time = `${d.getHours().toString().padStart(2, '0')}h${d.getMinutes().toString().padStart(2, '0')}m${d.getSeconds().toString().padStart(2, '0')}s`;
                        const date = `${d.getDate().toString().padStart(2, '0')}/${(d.getMonth() + 1).toString().padStart(2, '0')}/${d.getFullYear().toString().slice(-2)}`;
                        return `${time} - ${date}`;
                      })()}
                    </Typography>
                  </Box>
                </Box>
              );
            })}
          </Box>
        </Fade>
      )}
    </Box>
  );
};

export const ConversationList: React.FC<ConversationListProps> = ({
  showHistory,
  sidebarTab,
  handleSidebarTabChange,
  conversations,
  activeConversationId,
  backgroundAgents,
  backgroundTasks,
  backgroundExpanded,
  setBackgroundExpanded,
  createNewConversation,
  switchConversation,
  deleteConversation,
  clearBackgroundHistory,
  reloadSkills,
  width,
}) => {
  const theme = useTheme();
  const effectiveWidth = width ?? SIDEBAR_WIDTH;

  // Count total tasks for System tab badge
  const totalSystemTasks = backgroundAgents.reduce((sum, agent) => {
    const agentTasks = backgroundTasks[agent.id] || { inProgress: [], recent: [] };
    return sum + agentTasks.inProgress.length + agentTasks.recent.length;
  }, 0);

  // Group conversations (exclude background agent conversations - they show in their sections)
  const regularConversations = conversations.filter(c => !c.id.startsWith('bg_'));
  const groupedConversations = regularConversations.reduce((groups, conv) => {
    const d = new Date(conv.createdAt);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    let label = '';
    if (d.toDateString() === today.toDateString()) {
      label = 'Today';
    } else if (d.toDateString() === yesterday.toDateString()) {
      label = 'Yesterday';
    } else {
      const weekAgo = new Date(today);
      weekAgo.setDate(weekAgo.getDate() - 7);
      if (d >= weekAgo) {
        label = 'This Week';
      } else {
        label = 'Older';
      }
    }

    if (!groups[label]) {
      groups[label] = [];
    }
    groups[label].push(conv);
    return groups;
  }, {} as Record<string, typeof conversations>);

  return (
    <Box
      sx={{
        width: showHistory ? effectiveWidth : 0,
        minWidth: showHistory ? effectiveWidth : 0,
        height: '100%',
        bgcolor: theme.palette.mode === 'dark' ? '#1a1a1a' : 'grey.50',
        borderRight: showHistory ? '1px solid' : 'none',
        borderColor: theme.palette.mode === 'dark' ? '#333' : 'grey.200',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        transition: 'width 0.2s, min-width 0.2s',
      }}
    >
      {showHistory && (
        <>
          {/* New Chat Button */}
          <Box sx={{ p: 1.5, pb: 1 }}>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button
                fullWidth
                startIcon={<AddIcon />}
                onClick={() => {
                  createNewConversation();
                  handleSidebarTabChange('chats'); // Switch to chats tab when creating new
                }}
                sx={{
                  flex: 1,
                  justifyContent: 'flex-start',
                  color: 'text.primary',
                  bgcolor: theme.palette.mode === 'dark' ? '#2a2a2a' : 'grey.100',
                  border: '1px solid',
                  borderColor: theme.palette.mode === 'dark' ? '#333' : 'grey.300',
                  borderRadius: 2,
                  textTransform: 'none',
                  fontWeight: 500,
                  py: 1,
                  '&:hover': {
                    bgcolor: theme.palette.mode === 'dark' ? '#333' : 'grey.200',
                    borderColor: theme.palette.primary.main,
                  },
                }}
              >
                New Chat
              </Button>

              {/* Development: Skills Reload Button */}
              {APP_CONFIG.IS_DEVELOPMENT && (
                <Tooltip title="Reload Skills (Dev Only)">
                  <IconButton
                    onClick={async () => {
                      try {
                        await reloadSkills();
                        console.log('✅ Skills reloaded successfully');
                      } catch (error) {
                        console.error('❌ Failed to reload skills:', error);
                      }
                    }}
                    sx={{
                      color: theme.palette.primary.main,
                      bgcolor: theme.palette.mode === 'dark' ? '#2a2a2a' : 'grey.100',
                      border: '1px solid',
                      borderColor: theme.palette.mode === 'dark' ? '#333' : 'grey.300',
                      borderRadius: 2,
                      width: 48,
                      height: 48,
                      '&:hover': {
                        bgcolor: theme.palette.mode === 'dark' ? '#333' : 'grey.200',
                        borderColor: theme.palette.primary.main,
                      },
                    }}
                  >
                    <ReloadIcon />
                  </IconButton>
                </Tooltip>
              )}
            </Box>
          </Box>

          {/* Tabs for System vs Chats */}
          {backgroundAgents.length > 0 && (
            <Tabs
              value={sidebarTab}
              onChange={(_, newValue) => handleSidebarTabChange(newValue)}
              sx={{
                minHeight: 36,
                px: 1,
                mb: 0.5,
                '& .MuiTabs-indicator': {
                  backgroundColor: theme.palette.primary.main,
                  height: 2,
                },
              }}
            >
              <Tab
                value="chats"
                label={
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                    <ChatIcon sx={{ fontSize: 14 }} />
                    <span>Chats</span>
                    {regularConversations.length > 0 && (
                      <Chip
                        label={regularConversations.length}
                        size="small"
                        sx={{
                          height: 16,
                          minWidth: 16,
                          fontSize: '0.65rem',
                          bgcolor: sidebarTab === 'chats' ? theme.palette.primary.main : (theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.1)' : 'grey.300'),
                          color: sidebarTab === 'chats' ? '#fff' : 'text.secondary',
                          '& .MuiChip-label': { px: 0.5 },
                        }}
                      />
                    )}
                  </Box>
                }
                sx={{
                  minHeight: 36,
                  py: 0.5,
                  px: 1.5,
                  textTransform: 'none',
                  fontSize: '0.8rem',
                  fontWeight: sidebarTab === 'chats' ? 600 : 400,
                  color: sidebarTab === 'chats' ? 'text.primary' : 'text.secondary',
                  minWidth: 0,
                  flex: 1,
                }}
              />
              <Tab
                value="system"
                label={
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                    <DevicesIcon sx={{ fontSize: 14 }} />
                    <span>System</span>
                    {totalSystemTasks > 0 && (
                      <Chip
                        label={totalSystemTasks}
                        size="small"
                        sx={{
                          height: 16,
                          minWidth: 16,
                          fontSize: '0.65rem',
                          bgcolor: sidebarTab === 'system' ? theme.palette.primary.main : (theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.1)' : 'grey.300'),
                          color: sidebarTab === 'system' ? '#fff' : 'text.secondary',
                          '& .MuiChip-label': { px: 0.5 },
                        }}
                      />
                    )}
                  </Box>
                }
                sx={{
                  minHeight: 36,
                  py: 0.5,
                  px: 1.5,
                  textTransform: 'none',
                  fontSize: '0.8rem',
                  fontWeight: sidebarTab === 'system' ? 600 : 400,
                  color: sidebarTab === 'system' ? 'text.primary' : 'text.secondary',
                  minWidth: 0,
                  flex: 1,
                }}
              />
            </Tabs>
          )}

          {/* Tab Content */}
          <Box
            sx={{
              flex: 1,
              overflowY: 'auto',
              overflowX: 'hidden',
              px: 1,
              pb: 2,
              scrollbarWidth: 'thin',
              scrollbarColor: theme.palette.mode === 'dark' ? '#333 transparent' : '#c1c1c1 transparent',
              '&::-webkit-scrollbar': { width: 4 },
              '&::-webkit-scrollbar-track': { background: 'transparent' },
              '&::-webkit-scrollbar-thumb': {
                background: theme.palette.mode === 'dark' ? '#333' : '#c1c1c1',
                borderRadius: 2,
              },
            }}
          >
            {/* System Tab Content */}
            {sidebarTab === 'system' && backgroundAgents.length > 0 && (
              <Box sx={{ pt: 1 }}>
                {backgroundAgents.map(agent => renderBackgroundAgentSection(
                  agent,
                  backgroundTasks,
                  backgroundExpanded,
                  setBackgroundExpanded,
                  switchConversation,
                  activeConversationId,
                  sidebarTab,
                  clearBackgroundHistory,
                  theme
                ))}
              </Box>
            )}

            {/* Chats Tab Content */}
            {(sidebarTab === 'chats' || backgroundAgents.length === 0) && (
              <>
                {Object.entries(groupedConversations).map(([label, convs]) => (
                  <Box key={label} sx={{ mb: 1 }}>
                    <Typography
                      variant="caption"
                      sx={{
                        display: 'block',
                        px: 1,
                        pt: 0.5,
                        pb: 0,
                        color: theme.palette.text.secondary,
                        fontWeight: 600,
                        fontSize: '0.7rem',
                        textTransform: 'uppercase',
                        letterSpacing: '0.5px',
                      }}
                    >
                      {label}
                    </Typography>
                    {convs.map((conv) => (
                      <Box
                        key={conv.id}
                        onClick={() => {
                          handleSidebarTabChange('chats'); // Ensure we stay on chats tab
                          switchConversation(conv.id);
                        }}
                        sx={{
                          display: 'flex',
                          alignItems: 'flex-start',
                          gap: 1,
                          px: 1.5,
                          py: 1,
                          borderRadius: 1.5,
                          cursor: 'pointer',
                          bgcolor: conv.id === activeConversationId && sidebarTab === 'chats'
                            ? (theme.palette.mode === 'dark' ? '#1a1a1a' : 'grey.200')
                            : 'transparent',
                          '&:hover': {
                            bgcolor: theme.palette.mode === 'dark' ? '#1a1a1a' : 'grey.100',
                          },
                          transition: 'background-color 0.15s',
                        }}
                      >
                        <ChatIcon sx={{ fontSize: 14, color: theme.palette.text.secondary, flexShrink: 0, mt: 0.3 }} />
                        <Box sx={{ flex: 1, minWidth: 0 }}>
                          <Typography
                            variant="body2"
                            sx={{
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                              color: conv.id === activeConversationId ? 'text.primary' : 'text.secondary',
                              fontSize: '0.85rem',
                            }}
                          >
                            {conv.title}
                          </Typography>
                          <Typography
                            variant="caption"
                            sx={{
                              display: 'block',
                              color: theme.palette.text.secondary,
                              fontSize: '0.65rem',
                              opacity: 0.7,
                              mt: -0.25,
                            }}
                          >
                            {(() => {
                              const d = new Date(conv.createdAt);
                              const time = `${d.getHours().toString().padStart(2, '0')}h${d.getMinutes().toString().padStart(2, '0')}m${d.getSeconds().toString().padStart(2, '0')}s`;
                              const date = `${d.getDate().toString().padStart(2, '0')}/${(d.getMonth() + 1).toString().padStart(2, '0')}/${d.getFullYear().toString().slice(-2)}`;
                              return `${time} - ${date}`;
                            })()}
                          </Typography>
                        </Box>
                        <Tooltip title="Delete">
                          <IconButton
                            size="small"
                            onClick={(e) => {
                              e.stopPropagation();
                              deleteConversation(conv.id);
                            }}
                            sx={{
                              p: 0.25,
                              opacity: 0.5,
                              '&:hover': { opacity: 1, color: 'error.main' },
                            }}
                          >
                            <ClearIcon sx={{ fontSize: 14 }} />
                          </IconButton>
                        </Tooltip>
                      </Box>
                    ))}
                  </Box>
                ))}

                {regularConversations.length === 0 && (
                  <Typography
                    variant="caption"
                    sx={{
                      display: 'block',
                      textAlign: 'center',
                      color: theme.palette.text.secondary,
                      py: 4,
                    }}
                  >
                    No conversations yet
                  </Typography>
                )}
              </>
            )}
          </Box>
        </>
      )}
    </Box>
  );
};
