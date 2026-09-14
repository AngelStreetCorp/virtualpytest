/**
 * AI Agent Chat Page - 3-Column Layout
 * 
 * Layout:
 * - Left: Conversation history sidebar (collapsible)
 * - Center: Main chat area
 * - Right: Device execution panel (collapsible, prepared for future)
 */

import React, { useRef, useEffect, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import {
  Box,
  Paper,
  Typography,
  TextField,
  IconButton,
  Chip,
  useTheme,
  Fade,
  Tooltip,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Switch,
  FormControlLabel,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material';
import {
  AutoAwesome as SparkleIcon,
  ViewSidebar as SidebarIcon,
  Chat as ChatPanelIcon,
  PhoneAndroid as DevicePanelIcon,
  TouchApp as RemoteIcon,
  ArrowUpward as SendIcon,
} from '@mui/icons-material';
import { useSearchParams, useLocation } from 'react-router-dom';
import { useAgentChatContext } from '../contexts/AgentChatContext';
import type { BackgroundAgentInfo } from '../hooks/aiagent';
import { useToolExecutionTiming } from '../hooks/aiagent/useToolExecutionTiming';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { AGENT_CHAT_PALETTE as PALETTE, AGENT_COLORS } from '../constants/agentChatTheme';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { UserinterfaceSelector } from '../components/common/UserinterfaceSelector';
import { useHostData, useHostControl } from '../hooks/useHostManager';
import { VNCStateProvider } from '../contexts/VNCStateContext';
import { useUserInterface } from '../hooks/pages/useUserInterface';
import { ConversationList } from '../components/agent-chat/ConversationList';
import { ChatMessages } from '../components/agent-chat/ChatMessages';
import { DevicePanel } from '../components/agent-chat/DevicePanel';
import { ContentViewer, type ContentType, type ContentData, type ContentTab } from '../components/agent-chat/ContentViewer';
import { PromptPresets, type PromptPresetCategory } from '../components/agent-chat/PromptPresets';
import { RemotePanel } from '../components/controller/remote/RemotePanel';
import { DesktopPanel } from '../components/controller/desktop/DesktopPanel';
import { WebPanel } from '../components/controller/web/WebPanel';
import { useStream } from '../hooks/controller';
import { DEFAULT_DEVICE_RESOLUTION } from '../config/deviceResolutions';
import { useInteractivityManager } from '../hooks/aiagent/useInteractivityManager';


// Colorize PASSED (green) and FAILED (red) in agent responses
// Handles both strings and React node arrays from ReactMarkdown
const _colorizeStatus = (node: React.ReactNode): React.ReactNode => {
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
      <React.Fragment key={i}>{_colorizeStatus(child)}</React.Fragment>
    ));
  }
  
  // Handle React elements (like <a>, <strong>, etc.) - return as-is
  return node;
};

// Shorten model identifiers like "claude-sonnet-4-20250514" → "sonnet-4",
// "openai/gpt-4.1-mini" → "gpt-4.1-mini", "microsoft/phi-3-mini-128k-instruct" → "phi-3-mini".
const formatModelLabel = (model: string): string => {
  if (!model) return '';
  let name = model.includes('/') ? model.split('/').pop()! : model;
  name = name.replace(/-\d{8}$/, ''); // strip trailing date like -20250514
  name = name.replace(/^claude-/, ''); // drop redundant vendor prefix
  return name;
};

// --- Components ---

// Prompt History Dropdown Component
const PromptHistoryDropdown: React.FC<{
  promptHistory: string[];
  onSelectPrompt: (prompt: string) => void;
  isDarkMode: boolean;
  dropdownStyles: any;
}> = ({ promptHistory, onSelectPrompt, isDarkMode, dropdownStyles }) => {
  if (promptHistory.length === 0) return null;

  return (
    <Box sx={{ mt: 1, pt: 0, borderTop: '0px solid', borderColor: isDarkMode ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)' }}>
      {/* Label + Dropdown - single line */}
      <Box sx={{
        display: 'flex',
        gap: 0.5,
        justifyContent: 'flex-start',
        alignItems: 'center',
        flexWrap: 'wrap',
      }}>
        <Box
          component="span"
          sx={{
            fontSize: '0.7rem',
            fontWeight: 600,
            color: PALETTE.accent,
            textTransform: 'uppercase',
          }}
        >
          RECENT
        </Box>
        <FormControl
          size="small"
          sx={{
            minWidth: 560,
            ml:2,
            ...dropdownStyles.formControl,
            '& .MuiInputLabel-root': {
              fontSize: '0.8rem',
              fontWeight: 500,
            },
          }}
        >
          <Select
            value={promptHistory[0] || ""}
            displayEmpty
            sx={{
              ...dropdownStyles.select,
              fontSize: '0.85rem',
              '& .MuiSelect-select': {
                ...dropdownStyles.select['& .MuiSelect-select'],
                py: 0.5,
              },
            }}
            MenuProps={{
              ...dropdownStyles.menuProps,
              PaperProps: {
                ...dropdownStyles.menuProps.PaperProps,
                sx: {
                  ...dropdownStyles.menuProps.PaperProps.sx,
                  maxWidth: 500,
                  minWidth: 400,
                },
              },
            }}
          >
            {promptHistory.map((prompt, index) => (
              <MenuItem
                key={index}
                value={prompt}
                onClick={() => onSelectPrompt(prompt)}
                sx={{
                  ...dropdownStyles.menuItem,
                  whiteSpace: 'normal',
                  wordWrap: 'break-word',
                  py: 1,
                  fontSize: '0.85rem',
                  lineHeight: 1,
                }}
              >
                {prompt.length > 60 ? `${prompt.substring(0, 60)}...` : prompt}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Box>
    </Box>
  );
};

const AgentChat: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const theme = useTheme();
  const isDarkMode = theme.palette.mode === 'dark';

  // Shared dropdown styles for consistency across all selectors
  const getDropdownStyles = () => ({
    formControl: {
      '& .MuiInputLabel-root': {
        color: isDarkMode ? PALETTE.textSecondary : 'rgba(0, 0, 0, 0.6)',
      },
      '& .MuiInputLabel-root.Mui-focused': {
        color: PALETTE.accent,
      },
    },
    select: {
      height: 32,
      fontSize: '0.85rem',
      color: isDarkMode ? PALETTE.textPrimary : '#000',
      bgcolor: isDarkMode ? PALETTE.inputBg : '#fff',
      borderRadius: 1.5,
      '& .MuiOutlinedInput-notchedOutline': {
        borderColor: isDarkMode ? PALETTE.borderColor : 'grey.300',
      },
      '&:hover .MuiOutlinedInput-notchedOutline': {
        borderColor: PALETTE.accent,
      },
      '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
        borderColor: PALETTE.accent,
      },
      '& .MuiSelect-select': {
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        py: 0.5,
        color: isDarkMode ? PALETTE.textPrimary : '#000',
      },
    },
    menuProps: {
      PaperProps: {
        sx: {
          bgcolor: isDarkMode ? PALETTE.surface : '#fff',
          border: '1px solid',
          borderColor: isDarkMode ? PALETTE.borderColor : 'grey.200',
          boxShadow: PALETTE.cardShadow,
        }
      }
    },
    menuItemPlaceholder: {
      fontSize: '0.85rem',
      py: 0.75,
      color: isDarkMode ? PALETTE.textSecondary : 'rgba(0, 0, 0, 0.6)',
    },
    menuItem: {
      fontSize: '0.85rem',
      py: 0.75,
      color: isDarkMode ? PALETTE.textPrimary : '#000',
      '&:hover': { bgcolor: isDarkMode ? PALETTE.hoverBg : 'grey.100' },
      '&.Mui-selected': { bgcolor: isDarkMode ? PALETTE.hoverBg : 'grey.100' },
    },
  });

  const dropdownStyles = React.useMemo(getDropdownStyles, [isDarkMode]);

  // Layout state - each section can be shown/hidden
  const [showHistory, setShowHistory] = useState(true);
  const [showContentViewer, setShowContentViewer] = useState(false);
  const [contentViewerFullscreen, setContentViewerFullscreen] = useState(false);
  const [showDevice, setShowDevice] = useState(false);
  const [showRemote, setShowRemote] = useState(false);
  // For host_vnc devices: toggle between Web (Playwright) and Desktop (PyAutoGUI) panels
  const [hostRemoteView, setHostRemoteView] = useState<'web' | 'desktop'>('web');

  // Ref for remote panel container to get dimensions
  const remoteContainerRef = useRef<HTMLDivElement>(null);

  // Content panel state - controlled by AI agent or user selections
  const [contentType, setContentType] = useState<ContentType | null>(null);
  const [contentData, setContentData] = useState<ContentData | null>(null);
  const [contentTitle, setContentTitle] = useState<string | undefined>(undefined);
  const [contentLoading, setContentLoading] = useState(false);

  // Device selection state for manual control
  // selectedDevice stores just the device_id (for APIs)
  // selectedDeviceFullValue stores "host_name:device_id" (for dropdown tracking)
  const [selectedDevice, setSelectedDevice] = useState<string>('');
  const [selectedDeviceFullValue, setSelectedDeviceFullValue] = useState<string>('');
  const [selectedDevices, setSelectedDevices] = useState<string[]>([]);
  const [selectedUserInterface, setSelectedUserInterface] = useState<string>('');
  
  // TestCase selection state
  const [selectedTestCase, setSelectedTestCase] = useState<string>('');
  const [testCaseList, setTestCaseList] = useState<Array<{ testcase_id: string; testcase_name: string }>>([]);
  const [isLoadingTestCases, setIsLoadingTestCases] = useState(false);

  // Campaign selection state
  const [selectedCampaign, setSelectedCampaign] = useState<string>('');
  const [campaignList, setCampaignList] = useState<Array<{ campaign_id: string; campaign_name: string }>>([]);
  const [isLoadingCampaigns, setIsLoadingCampaigns] = useState(false);
  
  // Content viewer active tab
  const [activeContentTab, setActiveContentTab] = useState<ContentTab>('device-preview');
  // showDevicePanel is now controlled by showDevice - when device panel is shown, HDMI is shown
  
  // Content viewer height resizer
  const [contentViewerHeight, setContentViewerHeight] = useState(60); // percentage
  const [isResizing, setIsResizing] = useState(false);

  // Horizontal panel resizers (history sidebar, device panel, remote panel)
  const [historyWidth, setHistoryWidth] = useState(240);
  const [devicePanelWidth, setDevicePanelWidth] = useState(320);
  const [remotePanelWidth, setRemotePanelWidth] = useState(320);
  // Which horizontal divider is currently being dragged
  const [resizingPanel, setResizingPanel] = useState<null | 'history' | 'device' | 'remote'>(null);

  // Available userinterfaces for context
  const [availableUserInterfaces, setAvailableUserInterfaces] = useState<any[]>([]);
  const [userInterfacesLoaded, setUserInterfacesLoaded] = useState(false);

  // Track if we've done initial auto-selection (only on mount)
  const [hasDoneInitialDeviceSelection, setHasDoneInitialDeviceSelection] = useState(false);

  // Track if user has manually selected a user interface (to disable future auto-selection)
  const [hasUserSelectedInterface, setHasUserSelectedInterface] = useState(false);

  // Get HostManager for device selection
  const { getAllHosts, getAllDevices } = useHostData();
  const { handleDeviceSelect } = useHostControl();

  // Get UserInterface hook for available interfaces
  const { getAllUserInterfaces } = useUserInterface();


  // Get selected host object for stream hook
  const getSelectedHost = () => {
    if (!selectedDevice) return null;
    const hosts = getAllHosts();
    for (const host of hosts) {
      const device = host.devices?.find(d => d.device_id === selectedDevice);
      if (device) return host;
    }
    return null;
  };

  const selectedHost = getSelectedHost();

  // Stream URL for embedded video in right panel
  const { streamUrl, isLoadingUrl } = useStream({
    host: selectedHost,
    device_id: selectedDevice || ''
  });
  
  // Sidebar tab state: 'system' for background agents, 'chats' for conversations
  const [sidebarTab, setSidebarTab] = useState<'system' | 'chats'>('chats');
  
  // Handle sidebar tab change - clear bg_ conversation when switching to chats
  const handleSidebarTabChange = (newTab: 'system' | 'chats') => {
    setSidebarTab(newTab);
    // When switching to chats tab, if current conversation is a system one, clear it
    if (newTab === 'chats' && activeConversationId?.startsWith('bg_')) {
      switchConversation(''); // Clear to show empty state
    }
  };
  
  // Track if we've processed URL params
  const [urlParamsProcessed, setUrlParamsProcessed] = useState(false);

  // Prompt history state - keep last 10 prompts
  const [promptHistory, setPromptHistory] = useState<string[]>([]);
  
  // Background agents expanded state (keyed by agent ID)
  const [backgroundExpanded, setBackgroundExpanded] = useState<Record<string, boolean>>({});
  
  // Tool accordion expanded state (keyed by tool event key)
  const [toolExpanded, setToolExpanded] = useState<Record<string, boolean>>({});
  
  // Background agents info (agents with background_queues)
  const [backgroundAgents, setBackgroundAgentsState] = useState<BackgroundAgentInfo[]>([]);
  
// Selected agent - will be set from API (looks for agent with default: true)
// Start empty to avoid MUI out-of-range while agents load
const [selectedAgentId, setSelectedAgentId] = useState<string>('');
  
  // Available agents for dropdown (selectable only) + all agents for nickname lookup
  const [availableAgents, setAvailableAgents] = useState<any[]>([]);
  const [allAgentsMap, setAllAgentsMap] = useState<Record<string, { nickname: string; icon?: string; color?: string }>>({});
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [agentsError, setAgentsError] = useState<string | null>(null);
  
  // Page-level loading state - skip loading screen on subsequent visits
  const [pageReady, setPageReady] = useState(() => {
    // If we've visited before in this session, skip the loading animation
    return sessionStorage.getItem('agentchat_visited') === 'true';
  });
  
  // Auto-select first available device only on initial mount (after userinterfaces are ready)
  useEffect(() => {
    if (!selectedDeviceFullValue && userInterfacesLoaded && !hasDoneInitialDeviceSelection) {
      const hosts = getAllHosts();
      const allDevices = hosts.flatMap(host => host.devices || []);

      if (allDevices.length > 0) {
        console.log('[AgentChat] Auto-selecting first available device on mount:', allDevices[0].device_name);
        // Find the host for this device and pass combined format "host_name:device_id"
        const device = allDevices[0];
        const deviceHost = hosts.find(h => h.devices?.some(d => d.device_id === device.device_id));
        if (deviceHost) {
          handleDeviceSelection(`${deviceHost.host_name}:${device.device_id}`);
          setHasDoneInitialDeviceSelection(true); // Prevent future auto-selections
        }
      }
    }
  }, [selectedDeviceFullValue, userInterfacesLoaded, hasDoneInitialDeviceSelection, getAllHosts]); // Include dependencies

  // Load agents from API (ONLY source of truth)
  useEffect(() => {
    const loadAgents = async () => {
      try {
        setAgentsLoading(true);
        setAgentsError(null);
        const response = await fetch(buildServerUrl('/server/agents/'));
        
        if (!response.ok) {
          throw new Error('Failed to load agents from backend');
        }
        
        const data = await response.json();
        
        if (!data.agents?.length) {
          throw new Error('No agents configured in backend');
        }
        
        // Build lookup map for ALL agents (including sub-agents)
        const agentMap: Record<string, { nickname: string; icon?: string; color?: string }> = {};
        data.agents.forEach((a: any) => {
          const id = a.metadata?.id || a.id;
          const nickname = a.metadata?.nickname || a.nickname || a.name || id;
          const icon = a.metadata?.icon || a.icon;
          const color = AGENT_COLORS[id] || PALETTE.accent;
          
          // Index by all possible keys
          agentMap[id] = { nickname, icon, color };
          agentMap[a.name] = { nickname, icon, color };
          agentMap[a.metadata?.id] = { nickname, icon, color };
          agentMap[a.metadata?.name] = { nickname, icon, color };
          if (nickname) agentMap[nickname] = { nickname, icon, color };
        });
        
        // Filter to selectable agents only (for dropdown)
        const selectableAgents = data.agents
          .filter((a: any) => a.metadata?.selectable !== false)
          .map((a: any) => {
            const id = a.metadata?.id || a.id;
            return {
              id,
              name: a.metadata?.name || a.name,
              nickname: a.metadata?.nickname || a.nickname || a.name,
              icon: a.metadata?.icon || a.icon || '🤖',
              description: a.metadata?.description || a.description || '',
              color: AGENT_COLORS[id] || PALETTE.accent,
              tips: a.metadata?.suggestions || [], // Load from YAML suggestions
              prompt_presets: a.metadata?.prompt_presets || [], // Load from YAML prompt presets
              isDefault: a.metadata?.default === true, // Track default for sorting
              model: a.model || '',
            };
          });
        
        if (selectableAgents.length === 0) {
          throw new Error('No selectable agents found');
        }
        
        // Sort agents: default agent first, then others
        selectableAgents.sort((a: any, b: any) => {
          if (a.isDefault) return -1;
          if (b.isDefault) return 1;
          return 0;
        });
        
        setAvailableAgents(selectableAgents);
        setAllAgentsMap(agentMap);

        // Set default agent from YAML (looks for default: true)
        const defaultAgent = selectableAgents.find((a: any) => a.isDefault);
        const defaultId = defaultAgent?.id || selectableAgents[0]?.id || 'assistant';
        setSelectedAgentId(defaultId);
        
        // Identify background agents (those with background_queues config AND enabled)
        const bgAgents: BackgroundAgentInfo[] = data.agents
          .filter((a: any) => a.config?.background_queues?.length > 0 && a.config?.enabled !== false)
          .map((a: any) => ({
            id: a.metadata?.id || a.id,
            nickname: a.metadata?.nickname || a.nickname || a.name,
            queues: a.config.background_queues,
            dryRun: a.config.dry_run || false,
            color: AGENT_COLORS[a.metadata?.id || a.id] || PALETTE.accent,
          }));
        
        if (bgAgents.length > 0) {
          console.log(`[AgentChat] Found ${bgAgents.length} background agents:`, bgAgents.map(a => `${a.id}/${a.nickname}`));
          console.log(`[AgentChat] Background agents full details:`, JSON.stringify(bgAgents, null, 2));
          setBackgroundAgentsState(bgAgents);
          setBackgroundAgents(bgAgents); // Pass to hook
        } else {
          console.warn('[AgentChat] No background agents found - check agent YAML config for background_queues');
        }
        
        setAgentsLoading(false);
        // Keep loading screen visible for smooth transition (first visit only)
        if (!pageReady) {
          setTimeout(() => {
            setPageReady(true);
            sessionStorage.setItem('agentchat_visited', 'true');
          }, 700);
        }
      } catch (err) {
        console.error('Failed to load agents:', err);
        setAgentsError(err instanceof Error ? err.message : 'Failed to load agents');
        setAgentsLoading(false);
        setPageReady(true); // Show page even on error
      }
    };
    loadAgents();
  }, []);
  
  
  
  // Feedback state - tracks ratings per message ID (shared concept with badge)
  const [messageFeedback, setMessageFeedback] = useState<Record<string, number>>({});
  
  // Confirm dialog state
  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
  }>({
    open: false,
    title: '',
    message: '',
    onConfirm: () => {},
  });
  
  // Add prompt to history (keep last 10, avoid duplicates)
  const addPromptToHistory = (prompt: string) => {
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt) return;

    setPromptHistory(prev => {
      // Remove the prompt if it already exists (to avoid duplicates)
      const filtered = prev.filter(p => p.trim() !== trimmedPrompt);
      // Add to beginning and keep only first 10
      return [trimmedPrompt, ...filtered].slice(0, 10);
    });
  };

  // Submit feedback for a message
  const submitMessageFeedback = async (messageId: string, rating: number, agentId: string, prompt?: string) => {
    // If clicking same rating, remove it (toggle off)
    if (messageFeedback[messageId] === rating) {
      setMessageFeedback(prev => {
        const newState = { ...prev };
        delete newState[messageId];
        return newState;
      });
      return;
    }
    
    // Update local state immediately
    setMessageFeedback(prev => ({ ...prev, [messageId]: rating }));
    
    // Send to backend
    try {
      const response = await fetch(buildServerUrl('/server/benchmarks/feedback'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_id: agentId || selectedAgentId,
          rating: rating,
          task_description: prompt,
        }),
      });
      
      if (response.ok) {
        console.log('✅ Chat feedback submitted');
      }
    } catch (error) {
      console.error('Failed to submit feedback:', error);
    }
  };
  
  // Tool execution timing hook (5-second delay for animations)
  const { shouldShowExecutingAnimation } = useToolExecutionTiming();

  const {
    status,
    session,
    messages,
    input,
    isProcessing,
    currentEvents,
    error,
    conversations,
    activeConversationId,
    pendingConversationId,
    backgroundTasks,
    setBackgroundAgents,
    setInput,
    sendMessage,
    handleApproval,
    stopGeneration,
    clearHistory,
    createNewConversation,
    switchConversation,
    deleteConversation,
    clearBackgroundHistory,
    setAgentId,
    setNavigationContext,
    setOnUIAction,
    reloadSkills,
    apiKeyInput,
    setApiKeyInput,
    saveApiKey,
    isValidating,
    activeProvider,
    activeModel,
    activeKeyEnv,
  } = useAgentChatContext();

  // Interactivity manager for automatic UI updates based on text analysis
  const interactivityManager = useInteractivityManager(
    {
      setSelectedDevice,
      setSelectedUserInterface,
      setSelectedTestCase,
      setSelectedCampaign,
      setShowContentViewer,
      setActiveContentTab,
    },
    {
      device: selectedDevice,
      userinterface: selectedUserInterface,
      testcase: selectedTestCase,
      campaign: selectedCampaign,
    },
    testCaseList,
    campaignList,
    availableUserInterfaces // Pass already loaded user interfaces
  );

  // Get visual feedback for auto-selected items
  const autoSelectionFeedback = interactivityManager.getAutoSelectionFeedback();

  // Track which message IDs we've already analyzed to prevent infinite loops
  const analyzedMessageIds = useRef<Set<string>>(new Set());

  // Interactivity toggle state
  const [isInteractivityEnabled, setIsInteractivityEnabled] = useState(false);

  // Handle UI actions from AI agent (consolidated from separate socket)
  const handleUIAction = useCallback((action: string, payload: any) => {
    console.log('[AgentChat] Handling UI action:', action, payload);

    if (action === 'show_content') {
      const { content_type, content_data, title } = payload || {};

      if (content_type) {
        console.log('[AgentChat] Showing content panel:', content_type, title);
        setContentType(content_type as ContentType);
        setContentData(content_data || null);
        setContentTitle(title);
        setShowContentViewer(true); // Show content viewer when content is shown
        setContentLoading(false);
      }
    } else if (action === 'hide_content') {
      console.log('[AgentChat] Hiding content panel');
      setContentType(null);
      setContentData(null);
      setContentTitle(undefined);
      setShowContentViewer(false); // Hide content viewer when content is hidden
    } else if (action === 'sync_context') {
      // Sync UI dropdowns with agent's execution context
      const { device_id, userinterface_name, testcase_id, campaign_id } = payload || {};
      console.log('[AgentChat] Syncing UI context:', { device_id, userinterface_name, testcase_id, campaign_id });

      if (device_id) {
        setSelectedDevice(device_id);
      }
      if (userinterface_name) {
        setSelectedUserInterface(userinterface_name);
        // Auto-show content viewer with navigation tab
        setShowContentViewer(true);
        setActiveContentTab('navigation');
        setContentType('navigation-tree');
        setContentData({ userinterface_name });
        setContentTitle(`Navigation: ${userinterface_name}`);
      }
      if (testcase_id) {
        setSelectedTestCase(testcase_id);
        // Auto-show content viewer with testcase tab
        setShowContentViewer(true);
        setActiveContentTab('testcase');
        setContentType('testcase-flow');
        setContentData({ testcase_id });
        // Title will update when testCaseList is available
      }
      if (campaign_id) {
        setSelectedCampaign(campaign_id);
        // Auto-show content viewer with campaign tab
        setShowContentViewer(true);
        setActiveContentTab('campaign');
        setContentType('campaign-flow');
        setContentData({ campaign_id });
        // Title will update when campaignList is available
      }
      // Note: heatmap doesn't need specific syncing as it's always available
    }
  }, []);

  // Set up UI action handler for agent-driven UI updates
  useEffect(() => {
    setOnUIAction(handleUIAction);
  }, [setOnUIAction, handleUIAction]);

  // Enhanced send message with pre-prompt interactivity analysis
  const sendMessageWithInteractivity = useCallback(async () => {
    if (!input.trim()) return;

    // Add to prompt history before sending
    addPromptToHistory(input.trim());

    // Pre-prompt analysis: Update UI based on what user is about to ask (only if enabled)
    if (isInteractivityEnabled) {
      try {
        await interactivityManager.analyzePrompt(input);
      } catch (error) {
        console.warn('[AgentChat] Interactivity analysis failed:', error);
        // Continue with sending message even if analysis fails
      }
    }

    // Send the message
    sendMessage();
  }, [input, interactivityManager, sendMessage, isInteractivityEnabled, addPromptToHistory]);

// Sync selected agent with hook once we have a real value
useEffect(() => {
  if (selectedAgentId) {
    setAgentId(selectedAgentId);
  }
}, [selectedAgentId, setAgentId]);

// Post-response interactivity analysis - monitor for new AI messages
useEffect(() => {
  if (messages.length > 0 && isInteractivityEnabled) {
    const lastMessage = messages[messages.length - 1];

    // Only analyze AI responses (agent messages), not user messages
    // And only if we haven't analyzed this message before
    if (lastMessage.role === 'agent' && lastMessage.content) {
      const messageId = lastMessage.id || `${lastMessage.timestamp}-${lastMessage.content?.substring(0, 50)}`;

      if (!analyzedMessageIds.current.has(messageId)) {
        console.log('[AgentChat] Analyzing AI response for interactivity');
        analyzedMessageIds.current.add(messageId);

        // Analyze the AI response for entities and update UI accordingly
        interactivityManager.analyzeResponse(lastMessage.content)
          .catch(error => {
            console.warn('[AgentChat] Failed to analyze AI response:', error);
            // Remove from analyzed set if analysis failed, so we can retry
            analyzedMessageIds.current.delete(messageId);
          });
      }
    }
  }
}, [messages, interactivityManager, isInteractivityEnabled]);
  
  // Sync navigation context with hook (for 2-step workflow)
  useEffect(() => {
    // Get current device context from hostManager
    const hosts = getAllHosts();
    const allDevices = hosts.flatMap(host =>
      (host.devices || []).map(d => ({
        host_name: host.host_name,
        device_id: d.device_id,
        device_name: d.device_name || d.device_id,
      }))
    );

    // Get host name from selected host
    const currentHost = getSelectedHost();
    const hostName = currentHost?.host_name || '';

    setNavigationContext(
      false,
      location.pathname,
      hostName,
      selectedDevice || '',
      selectedUserInterface || '',
      selectedTestCase || '',
      selectedCampaign || '',
      allDevices,
      availableUserInterfaces
    );
  }, [location.pathname, setNavigationContext, availableUserInterfaces, selectedDevice, selectedUserInterface, selectedTestCase, selectedCampaign, userInterfacesLoaded]);
  
  // Manual device selection handler
  const handleDeviceSelection = (deviceValue: string) => {
    // Parse host_name:device_id from the combined value
    let hostName = '';
    let deviceId = '';

    if (deviceValue && deviceValue.includes(':')) {
      [hostName, deviceId] = deviceValue.split(':', 2);
    } else {
      deviceId = deviceValue;
    }

    setSelectedDevice(deviceId);
    setSelectedDeviceFullValue(deviceValue); // Store full value for dropdown tracking

    if (!deviceId) {
      // Clearing device selection - hide panels and clear interface
      setSelectedDevices([]);
      setSelectedUserInterface('');
      setShowDevice(false);
      setShowRemote(false);
      handleDeviceSelect(null, null);
      // Clear navigation context
      setNavigationContext(false, location.pathname, '', '', '', '', '', [], availableUserInterfaces);
      return;
    }

    // Update selectedDevices array with the selected device
    setSelectedDevices([deviceValue]); // deviceValue is in "host_name:device_id" format

    // Selecting a device - don't hide panels, just update context
    // Clear interface selection when device changes (but keep panels visible)
    setSelectedUserInterface('');

    // Find the host by name to update the device panels and navigation context
    const hosts = getAllHosts();
    const allDevices = hosts.flatMap(host => host.devices || []);
    const selectedHost = hosts.find(h => h.host_name === hostName);

    if (selectedHost) {
      handleDeviceSelect(selectedHost, deviceId);
      // Update navigation context with host_name, device_id, and available devices
      setNavigationContext(false, location.pathname, hostName, deviceId, '', '', '', allDevices, availableUserInterfaces);
    } else {
      console.error(`Host ${hostName} not found for device ${deviceId}`);
    }
  };

  // Get device model for the selected device (for userinterface filtering)
  const getSelectedDeviceModel = () => {
    if (!selectedDevice) return undefined;

    const hosts = getAllHosts();
    for (const host of hosts) {
      const device = host.devices?.find(d => d.device_id === selectedDevice);
      if (device) {
        return device.device_model;
      }
    }
    return undefined;
  };

  // Manual userinterface selection handler
  const handleUserInterfaceSelection = (userInterface: string) => {
    setSelectedUserInterface(userInterface);
    setHasUserSelectedInterface(true); // Mark that user has manually selected an interface

    // Get current host and device for navigation context
    const selectedHost = getSelectedHost();
    const hostName = selectedHost?.host_name || '';
    const deviceId = selectedDevice || '';

    // Get available devices for context
    const hosts = getAllHosts();
    const allDevices = hosts.flatMap(host => host.devices || []);

    // Update navigation context with all available information
    setNavigationContext(false, location.pathname, hostName, deviceId, userInterface || '', '', '', allDevices, availableUserInterfaces);

    // Auto-show ContentViewer with Navigation tab when interface selected
    if (userInterface && showContentViewer) {
      setActiveContentTab('navigation');
      setContentType('navigation-tree');
      setContentData({ userinterface_name: userInterface });
      setContentTitle(`Navigation: ${userInterface}`);
    }
  };
  
  // Fetch test case list
  const fetchTestCaseList = async () => {
    try {
      setIsLoadingTestCases(true);
      const response = await fetch(buildServerUrl('/server/testcase/list'));
      if (response.ok) {
        const data = await response.json();
        setTestCaseList(data.testcases || []);
      }
    } catch (error) {
      console.error('[AgentChat] Failed to fetch test cases:', error);
    } finally {
      setIsLoadingTestCases(false);
    }
  };

  // Fetch campaign list
  const fetchCampaignList = async () => {
    try {
      setIsLoadingCampaigns(true);
      const response = await fetch(buildServerUrl('/server/campaigns/getAllCampaigns'));
      if (response.ok) {
        const data = await response.json();
        if (data.success && data.campaigns) {
          setCampaignList(data.campaigns);
        } else {
          setCampaignList([]);
        }
      }
    } catch (error) {
      console.error('[AgentChat] Failed to fetch campaigns:', error);
    } finally {
      setIsLoadingCampaigns(false);
    }
  };

  // Fetch test cases, campaigns, and userinterfaces on mount
  useEffect(() => {
    fetchTestCaseList();
    fetchCampaignList();

    // Load available userinterfaces for context
    const loadUserInterfaces = async () => {
      try {
        const interfaces = await getAllUserInterfaces();
        setAvailableUserInterfaces(interfaces || []);
        setUserInterfacesLoaded(true);
        console.log('[AgentChat] Loaded available userinterfaces:', interfaces?.length || 0);
      } catch (error) {
        console.error('[AgentChat] Failed to load userinterfaces:', error);
        setUserInterfacesLoaded(true); // Still mark as loaded even on error to avoid blocking
      }
    };
    loadUserInterfaces();
  }, [getAllUserInterfaces]);
  
  // Handle vertical resize of content viewer
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing) return;
      
      const container = document.querySelector('[data-content-container]') as HTMLElement;
      if (!container) return;
      
      const containerRect = container.getBoundingClientRect();
      const newHeight = ((e.clientY - containerRect.top) / containerRect.height) * 100;
      
      // Clamp between 20% and 80%
      const clampedHeight = Math.min(Math.max(newHeight, 20), 80);
      setContentViewerHeight(clampedHeight);
    };
    
    const handleMouseUp = () => {
      setIsResizing(false);
    };
    
    if (isResizing) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'ns-resize';
      document.body.style.userSelect = 'none';
    }
    
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [isResizing]);

  // Horizontal panel resize (history / device / remote)
  useEffect(() => {
    if (!resizingPanel) return;

    const MIN = 180;
    const MAX = 720;

    const handleMouseMove = (e: MouseEvent) => {
      if (resizingPanel === 'history') {
        // Drag from the left edge area: width = mouseX
        setHistoryWidth(Math.min(Math.max(e.clientX, MIN), MAX));
      } else if (resizingPanel === 'device') {
        // Device panel is anchored to the right of chat. Width is window.innerWidth - mouseX - remotePanelWidth (if remote shown)
        const fromRight = window.innerWidth - e.clientX - (showRemote ? remotePanelWidth : 0);
        setDevicePanelWidth(Math.min(Math.max(fromRight, MIN), MAX));
      } else if (resizingPanel === 'remote') {
        // Remote panel is the rightmost. Width = window.innerWidth - mouseX
        const fromRight = window.innerWidth - e.clientX;
        setRemotePanelWidth(Math.min(Math.max(fromRight, MIN), MAX));
      }
    };

    const handleMouseUp = () => setResizingPanel(null);

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    document.body.style.cursor = 'ew-resize';
    document.body.style.userSelect = 'none';

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [resizingPanel, showRemote, remotePanelWidth]);

  // Handle test case selection
  const handleTestCaseSelection = (testcaseId: string) => {
    setSelectedTestCase(testcaseId);

    // Get current context for navigation update
    const selectedHost = getSelectedHost();
    const hostName = selectedHost?.host_name || '';
    const deviceId = selectedDevice || '';
    const hosts = getAllHosts();
    const allDevices = hosts.flatMap(host => host.devices || []);

    // Update navigation context with testcase_id
    setNavigationContext(false, location.pathname, hostName, deviceId, selectedUserInterface, testcaseId, selectedCampaign, allDevices, availableUserInterfaces);

    // Auto-show ContentViewer with TestCase tab when test case selected and content viewer is active
    if (testcaseId && showContentViewer) {
      const testcase = testCaseList.find(tc => tc.testcase_id === testcaseId);
      setActiveContentTab('testcase');
      setContentType('testcase-flow');
      setContentData({ testcase_id: testcaseId });
      setContentTitle(testcase ? `Test Case: ${testcase.testcase_name}` : 'Test Case');
    }
  };

  // Handle campaign selection
  const handleCampaignSelection = (campaignId: string) => {
    setSelectedCampaign(campaignId);

    // Get current context for navigation update
    const selectedHost = getSelectedHost();
    const hostName = selectedHost?.host_name || '';
    const deviceId = selectedDevice || '';
    const hosts = getAllHosts();
    const allDevices = hosts.flatMap(host => host.devices || []);

    // Update navigation context with campaign_id
    setNavigationContext(false, location.pathname, hostName, deviceId, selectedUserInterface, selectedTestCase, campaignId, allDevices, availableUserInterfaces);

    // Auto-show ContentViewer with Campaign tab when campaign selected and content viewer is active
    if (campaignId && showContentViewer) {
      const campaign = campaignList.find(c => c.campaign_id === campaignId);
      setActiveContentTab('campaign');
      setContentType('campaign-flow');
      setContentData({ campaign_id: campaignId });
      setContentTitle(campaign ? `Campaign: ${campaign.campaign_name}` : 'Campaign');
    }
  };

  // Handle device panel toggle with smart 3-panel logic
  const handleDevicePanelToggle = () => {
    if (showDevice) {
      // Hide device panel
      setShowDevice(false);
    } else if (selectedDevice) {
      // Show device panel - check if we need to auto-collapse
      if (showRemote && showHistory) {
        // Would create 4 panels - auto-hide history to maintain 3-panel max
        setShowHistory(false);
      }
      setShowDevice(true);
    }
  };

  // Handle remote panel toggle with smart 3-panel logic
  const handleRemotePanelToggle = () => {
    if (showRemote) {
      // Hide remote panel
      setShowRemote(false);
    } else if (selectedDevice) {
      // Show remote panel - check if we need to auto-collapse
      if (showDevice && showHistory) {
        // Would create 4 panels - auto-hide history to maintain 3-panel max
        setShowHistory(false);
      }
      setShowRemote(true);
    }
  };

  
  // Reset scroll state and tool expanded state when conversation changes
  useEffect(() => {
    isUserScrolledUp.current = false;
    lastMessageCount.current = 0;
    lastToolEventCount.current = 0;
    setToolExpanded({}); // Clear tool expanded state for new conversation
    analyzedMessageIds.current.clear(); // Clear analyzed messages for new conversation
  }, [activeConversationId]);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const isUserScrolledUp = useRef(false);
  const lastMessageCount = useRef(0);
  const lastToolEventCount = useRef(0);
  

  // Track if user has scrolled up manually
  const handleScroll = () => {
    const container = scrollContainerRef.current;
    if (!container) return;
    
    const { scrollTop, scrollHeight, clientHeight } = container;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 100;
    isUserScrolledUp.current = !isAtBottom;
  };

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
  }, [messages.length, currentEvents]);
  
  // Handle URL params from command bar (prompt & agent)
  useEffect(() => {
    if (urlParamsProcessed) return;
    
    const prompt = searchParams.get('prompt');
    const agentParam = searchParams.get('agent');
    
    if (prompt && status === 'ready') {
      // Set agent if provided
      if (agentParam) {
        setSelectedAgentId(agentParam);
        setAgentId(agentParam);
      }
      
      // Clear URL params
      setSearchParams({}, { replace: true });
      setUrlParamsProcessed(true);

      // Set input and trigger send after a brief delay
      setInput(prompt);
      setTimeout(() => {
        // Add to history and send
        addPromptToHistory(prompt);
        sendMessage();
      }, 150);
    }
  }, [searchParams, status, urlParamsProcessed, setSearchParams, setAgentId, setInput, sendMessage]);

  // Handle incoming Slack messages (bidirectional chat)
  useEffect(() => {
    const handleSlackMessage = (event: CustomEvent) => {
      const { content } = event.detail;
      if (content && status === 'ready') {
        console.log('💬 Processing Slack message:', content);
        // Set input and auto-send
        setInput(content);
        setTimeout(() => {
          // Add to history and send
          addPromptToHistory(content);
          sendMessage();
        }, 150);
      }
    };

    window.addEventListener('slack-message-received', handleSlackMessage as EventListener);
    return () => {
      window.removeEventListener('slack-message-received', handleSlackMessage as EventListener);
    };
  }, [status, setInput, sendMessage, addPromptToHistory]);
  

  // --- Renderers ---



  // --- Left Sidebar ---
  const renderLeftSidebar = () => (
    <>
      <ConversationList
        showHistory={showHistory}
        sidebarTab={sidebarTab}
        handleSidebarTabChange={handleSidebarTabChange}
        conversations={conversations}
        activeConversationId={activeConversationId}
        backgroundAgents={backgroundAgents}
        backgroundTasks={backgroundTasks}
        backgroundExpanded={backgroundExpanded}
        setBackgroundExpanded={setBackgroundExpanded}
        createNewConversation={createNewConversation}
        switchConversation={switchConversation}
        deleteConversation={deleteConversation}
        clearBackgroundHistory={clearBackgroundHistory}
        reloadSkills={reloadSkills}
        width={historyWidth}
      />
      {showHistory && (
        <Box
          onMouseDown={() => setResizingPanel('history')}
          sx={{
            width: 4,
            cursor: 'ew-resize',
            bgcolor: isDarkMode ? PALETTE.borderColor : 'grey.300',
            flexShrink: 0,
            transition: 'background-color 0.2s',
            '&:hover': { bgcolor: PALETTE.accent },
            '&:active': { bgcolor: PALETTE.accent },
          }}
        />
      )}
    </>
  );

  // --- Right Panel (Device + Remote Control - side by side) ---
  const renderRightPanel = () => {
    // Debug logging
    console.log('[@AgentChat] renderRightPanel - showDevice:', showDevice, 'showRemote:', showRemote);
    const selectedDeviceModel = getSelectedDeviceModel();
    const isDesktopDevice = selectedDeviceModel === 'host_vnc';

    // Calculate total width based on which panels are shown
    const deviceWidth = showDevice ? devicePanelWidth : 0;
    const remoteWidth = showRemote && selectedDevice && selectedHost ? remotePanelWidth : 0;
    // Add 4px per visible resizer divider
    const resizerWidth = (showDevice ? 4 : 0) + (showRemote && selectedDevice && selectedHost ? 4 : 0);
    const totalWidth = deviceWidth + remoteWidth + resizerWidth;

    if (totalWidth === 0) return null;

    return (
      <Box
        sx={{
          width: totalWidth,
          minWidth: totalWidth,
          height: '100%',
          display: 'flex',
          overflow: 'hidden',
          transition: 'width 0.2s, min-width 0.2s',
        }}
      >
        {/* Resizer between chat and device panel */}
        {showDevice && (
          <Box
            onMouseDown={() => setResizingPanel('device')}
            sx={{
              width: 4,
              cursor: 'ew-resize',
              bgcolor: isDarkMode ? PALETTE.borderColor : 'grey.300',
              flexShrink: 0,
              '&:hover': { bgcolor: PALETTE.accent },
              '&:active': { bgcolor: PALETTE.accent },
            }}
          />
        )}

        {/* Device Panel */}
        {showDevice && (
          <Box
            sx={{
              width: devicePanelWidth,
              minWidth: devicePanelWidth,
              height: '100%',
              borderLeft: 'none',
              flexShrink: 0,
            }}
          >
            <DevicePanel
              showDevice={showDevice}
              selectedDevice={selectedDevice}
              streamUrl={streamUrl}
              isLoadingUrl={isLoadingUrl}
              getSelectedDeviceModel={getSelectedDeviceModel}
            />
          </Box>
        )}

        {/* Resizer between device panel (or chat) and remote panel */}
        {showRemote && selectedDevice && selectedHost && (
          <Box
            onMouseDown={() => setResizingPanel('remote')}
            sx={{
              width: 4,
              cursor: 'ew-resize',
              bgcolor: isDarkMode ? PALETTE.borderColor : 'grey.300',
              flexShrink: 0,
              '&:hover': { bgcolor: PALETTE.accent },
              '&:active': { bgcolor: PALETTE.accent },
            }}
          />
        )}

        {/* Remote Panel */}
        {showRemote && selectedDevice && selectedHost && (
          <Box
            ref={remoteContainerRef}
            sx={{
              width: remotePanelWidth,
              minWidth: remotePanelWidth,
              height: '100%',
              bgcolor: theme.palette.mode === 'dark' ? '#1a1a1a' : 'grey.50',
              borderLeft: '1px solid',
              borderColor: theme.palette.mode === 'dark' ? '#333' : 'grey.200',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              flexShrink: 0,
            }}
          >
            {/* Minimal header - title + (host-only) Web/Desktop toggle */}
            <Box sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 1,
              p: 0.5,
              bgcolor: theme.palette.mode === 'dark' ? '#1a1a1a' : 'grey.100',
              borderBottom: '1px solid',
              borderColor: theme.palette.mode === 'dark' ? '#333' : 'grey.300',
              minHeight: '24px',
              flexShrink: 0,
            }}>
              <Typography variant="caption" sx={{ fontWeight: 500, color: 'text.secondary' }}>
                Remote Control
              </Typography>
              {isDesktopDevice && (
                <ToggleButtonGroup
                  value={hostRemoteView}
                  exclusive
                  size="small"
                  onChange={(_, value) => {
                    if (value) setHostRemoteView(value);
                  }}
                  sx={{
                    '& .MuiToggleButton-root': {
                      py: 0,
                      px: 1,
                      fontSize: '0.65rem',
                      lineHeight: 1.4,
                      textTransform: 'none',
                      borderColor: theme.palette.mode === 'dark' ? '#333' : 'grey.400',
                      color: 'text.secondary',
                    },
                    '& .Mui-selected': {
                      bgcolor: `${PALETTE.accent}20 !important`,
                      color: `${PALETTE.accent} !important`,
                    },
                  }}
                >
                  <ToggleButton value="web">Web</ToggleButton>
                  <ToggleButton value="desktop">Desktop</ToggleButton>
                </ToggleButtonGroup>
              )}
            </Box>

            {/* Full height remote content - calculate actual container dimensions */}
            <Box sx={{
              flex: 1,
              overflow: 'hidden',
              position: 'relative',
              height: 'calc(100% - 24px)', // Account for header height
            }}>
              {isDesktopDevice ? (
                <Box
                  sx={{
                    height: '100%',
                    p: 1,
                    bgcolor: theme.palette.mode === 'dark' ? '#111' : 'grey.100',
                    overflow: 'hidden',
                  }}
                >
                  <Box
                    sx={{
                      height: '100%',
                      overflow: 'hidden',
                      borderRadius: 1,
                      border: '1px solid',
                      borderColor: theme.palette.mode === 'dark' ? '#333' : 'grey.300',
                      bgcolor: theme.palette.mode === 'dark' ? '#1a1a1a' : '#fff',
                    }}
                  >
                    {hostRemoteView === 'web' ? (
                      <WebPanel
                        host={selectedHost}
                        deviceId={selectedDevice}
                        deviceModel={selectedDeviceModel || 'host_vnc'}
                        isConnected={true}
                        onReleaseControl={() => {}}
                        initialCollapsed={false}
                        streamContainerDimensions={{
                          width: remoteWidth - 16,
                          height: 600,
                          x: 0,
                          y: 0,
                        }}
                      />
                    ) : (
                      <DesktopPanel
                        host={selectedHost}
                        deviceId={selectedDevice}
                        deviceModel={selectedDeviceModel || 'host_vnc'}
                        isConnected={true}
                        onReleaseControl={() => {}}
                        initialCollapsed={false}
                        streamContainerDimensions={{
                          width: remoteWidth - 16,
                          height: 600,
                          x: 0,
                          y: 0,
                        }}
                      />
                    )}
                  </Box>
                </Box>
              ) : (
                <RemotePanel
                  host={selectedHost}
                  deviceId={selectedDevice}
                  deviceModel={selectedDeviceModel || 'unknown'}
                  isConnected={true}
                  onReleaseControl={() => {}}
                  initialCollapsed={false}
                  deviceResolution={DEFAULT_DEVICE_RESOLUTION}
                  streamContainerDimensions={{
                    width: remoteWidth,
                    height: 578,
                    x: 802,
                    y: 145,
                  }}
                  useAbsolutePositioning={false}
                  disableResize={true}
                  showOverlay={showDevice}
                />
              )}
            </Box>
          </Box>
        )}
      </Box>
    );
  };


  // --- Welcome Screen (Empty State) ---
  const renderEmptyState = () => (
    <Box sx={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'flex-start',
      pt: '20vh',
      px: 4,
      pb: 4,
    }}>
      <Fade in timeout={800}>
        <Box sx={{ textAlign: 'center', maxWidth: 640, width: '100%' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', mb: 2.3, gap: 2 }}>
            <Box sx={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 64,
              height: 64,
              borderRadius: '50%',
              bgcolor: `${PALETTE.accent}15`
            }}>
              <SparkleIcon sx={{ fontSize: 32, color: PALETTE.accent }} />
            </Box>

            <Typography
              variant="h5"
              sx={{ fontWeight: 500, color: 'text.primary', letterSpacing: '-0.01em' }}
            >
              AI Agent
            </Typography>
          </Box>

          {/* Input Card */}
          <Paper
            elevation={0}
            sx={{
              p: 1,
              display: 'flex',
              alignItems: 'center',
              bgcolor: isDarkMode ? PALETTE.inputBg : '#fff',
              border: '1px solid',
              borderColor: isDarkMode ? PALETTE.borderColor : 'grey.300',
              borderRadius: 3,
              boxShadow: isDarkMode ? PALETTE.cardShadow : '0 2px 8px rgba(0,0,0,0.08)',
              transition: 'all 0.2s',
              '&:hover': { borderColor: PALETTE.accent },
              '&:focus-within': { borderColor: PALETTE.accent },
            }}
          >
            <TextField
              autoFocus
              fullWidth
              placeholder="How can I help you?"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  sendMessageWithInteractivity();
                }
              }}
              sx={{ ml: 1.5, flex: 1 }}
              variant="standard"
              autoComplete="off"
              InputProps={{ disableUnderline: true, sx: { fontSize: '0.95rem' } }}
            />
            <IconButton
              onClick={sendMessageWithInteractivity}
              disabled={!input.trim()}
              sx={{
                m: 0.5, width: 36, height: 36,
                bgcolor: input.trim() ? PALETTE.accent : 'transparent',
                color: input.trim() ? '#fff' : 'text.disabled',
                '&:hover': { bgcolor: input.trim() ? PALETTE.accentHover : 'transparent' },
              }}
            >
              <SendIcon fontSize="small" />
            </IconButton>
          </Paper>

          {/* Suggestion Chips - Loaded from YAML metadata.suggestions */}
          {!agentsLoading && availableAgents.length > 0 && availableAgents.find(a => a.id === selectedAgentId)?.tips?.length > 0 && (
            <Box sx={{ mt: 3, display: 'flex', gap: 1, justifyContent: 'center', flexWrap: 'wrap' }}>
              {availableAgents.find(a => a.id === selectedAgentId)?.tips.map((suggestion: string) => (
                <Chip
                  key={suggestion}
                  label={suggestion}
                  onClick={() => setInput(suggestion)}
                  size="small"
                  sx={{
                    bgcolor: isDarkMode ? PALETTE.surface : 'grey.100',
                    border: '1px solid',
                    borderColor: isDarkMode ? PALETTE.borderColor : 'grey.200',
                    borderRadius: 2,
                    fontSize: '0.8rem',
                    '&:hover': { borderColor: PALETTE.accent, cursor: 'pointer' },
                  }}
                />
              ))}
            </Box>
          )}

          {/* Prompt Presets - Categorized prompts with variable substitution */}
          {!agentsLoading && availableAgents.length > 0 && availableAgents.find(a => a.id === selectedAgentId)?.prompt_presets?.length > 0 && (
            <PromptPresets
              presets={availableAgents.find(a => a.id === selectedAgentId)?.prompt_presets as PromptPresetCategory[]}
              onSelectPreset={setInput}
              context={{
                device_id: selectedDevice,
                device_name: (() => {
                  if (!selectedDevice) return undefined;
                  const hosts = getAllHosts();
                  for (const host of hosts) {
                    const device = host.devices?.find(d => d.device_id === selectedDevice);
                    if (device) return device.device_name;
                  }
                  return undefined;
                })(),
                host_name: (() => {
                  if (!selectedDevice) return undefined;
                  const hosts = getAllHosts();
                  for (const host of hosts) {
                    const device = host.devices?.find(d => d.device_id === selectedDevice);
                    if (device) return host.host_name;
                  }
                  return undefined;
                })(),
                userinterface_name: selectedUserInterface,
                testcase_id: selectedTestCase,
                testcase_name: (() => {
                  if (!selectedTestCase) return undefined;
                  return testCaseList.find(tc => tc.testcase_id === selectedTestCase)?.testcase_name;
                })(),
                campaign_id: selectedCampaign,
                campaign_name: (() => {
                  if (!selectedCampaign) return undefined;
                  return campaignList.find(c => c.campaign_id === selectedCampaign)?.campaign_name;
                })(),
              }}
              isDarkMode={isDarkMode}
            />
          )}

          {/* Prompt History - Recent prompts with same style as presets */}
          {promptHistory.length > 0 && (
            <PromptHistoryDropdown
              promptHistory={promptHistory}
              onSelectPrompt={setInput}
              isDarkMode={isDarkMode}
              dropdownStyles={dropdownStyles}
            />
          )}
        </Box>
      </Fade>
    </Box>
  );

  // --- Main Chat Content ---
  const renderChatContent = () => (
    <ChatMessages
      sidebarTab={sidebarTab}
      activeConversationId={activeConversationId}
      status={status}
      messages={messages}
      currentEvents={currentEvents}
      isProcessing={isProcessing}
      pendingConversationId={pendingConversationId}
      session={session}
      agentsLoading={agentsLoading}
      agentsError={agentsError}
      error={error}
      availableAgents={availableAgents}
      allAgentsMap={allAgentsMap}
      selectedAgentId={selectedAgentId}
      messageFeedback={messageFeedback}
      submitMessageFeedback={submitMessageFeedback}
      input={input}
      sendMessage={sendMessage}
      setInput={setInput}
      handleApproval={handleApproval}
      toolExpanded={toolExpanded}
      setToolExpanded={setToolExpanded}
      messagesEndRef={messagesEndRef}
      scrollContainerRef={scrollContainerRef}
      isUserScrolledUp={isUserScrolledUp}
      lastMessageCount={lastMessageCount}
      lastToolEventCount={lastToolEventCount}
      handleScroll={handleScroll}
      conversations={conversations}
      clearHistory={clearHistory}
      stopGeneration={stopGeneration}
      shouldShowExecutingAnimation={shouldShowExecutingAnimation}
      apiKeyInput={apiKeyInput}
      setApiKeyInput={setApiKeyInput}
      saveApiKey={saveApiKey}
      isValidating={isValidating}
      activeProvider={activeProvider}
      activeModel={activeModel}
      activeKeyEnv={activeKeyEnv}
    />
  );

  // --- Section Toggle Button ---
  const SectionToggle = ({ 
    active, 
    onClick, 
    icon: Icon, 
    tooltip 
  }: { 
    active: boolean; 
    onClick: () => void; 
    icon: React.ElementType; 
    tooltip: string;
  }) => (
    <Tooltip title={tooltip}>
      <IconButton
        size="small"
        onClick={onClick}
        sx={{
          width: 32,
          height: 32,
          borderRadius: 1.5,
          bgcolor: active 
            ? (isDarkMode ? PALETTE.surface : 'grey.200') 
            : 'transparent',
          color: active ? PALETTE.accent : 'text.disabled',
          border: '1px solid',
          borderColor: active 
            ? (isDarkMode ? PALETTE.borderColor : 'grey.300')
            : 'transparent',
          transition: 'all 0.15s',
          '&:hover': {
            bgcolor: isDarkMode ? PALETTE.hoverBg : 'grey.100',
            color: active ? PALETTE.accent : 'text.secondary',
          },
        }}
      >
        <Icon sx={{ fontSize: 18 }} />
      </IconButton>
    </Tooltip>
  );

  // --- Main Render ---
  
  // Show full-screen loading overlay until page is ready (using Portal to render at body level)
  if (!pageReady) {
    return createPortal(
      <Box sx={{ 
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100vw',
        height: '100vh',
        zIndex: 99999,
        display: 'flex', 
        alignItems: 'center',
        justifyContent: 'center',
        bgcolor: isDarkMode ? '#0a0a0a' : '#ffffff',
        // No animation on background - appears instantly to cover everything
      }}>
        <Box sx={{ 
          display: 'flex', 
          flexDirection: 'column', 
          alignItems: 'center', 
          gap: 2,
          animation: 'slideUp 0.1s ease-out forwards',
          opacity: 0,
        }}>
          <SparkleIcon sx={{ fontSize: 36, color: PALETTE.accent, animation: 'pulse 1.5s ease-in-out infinite' }} />
          <Typography variant="body2" sx={{ color: isDarkMode ? '#888' : '#666', fontWeight: 500 }}>
            AI Agent
          </Typography>
        </Box>
        <style>{`
          @keyframes slideUp {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
          }
          @keyframes pulse {
            0%, 100% { opacity: 0.6; transform: scale(1); }
            50% { opacity: 1; transform: scale(1.08); }
          }
        `}</style>
      </Box>,
      document.body
    );
  }
  
  return (
    <Box sx={{ 
      height: 'calc(98vh - 64px)', 
      display: 'flex', 
      flexDirection: 'column',
      bgcolor: 'background.default',
      overflow: 'hidden',
      animation: 'contentFadeIn 0.4s ease-out forwards',
      '@keyframes contentFadeIn': {
        from: { opacity: 0 },
        to: { opacity: 1 },
      },
    }}>
      {/* Top Bar with Section Toggles */}
      <Box sx={{ 
        py: 0.5, 
        px: 2, 
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid',
        borderColor: isDarkMode ? PALETTE.borderColor : 'grey.200',
        flexShrink: 0,
        bgcolor: isDarkMode ? PALETTE.sidebarBg : 'grey.50',
      }}>
        {/* Left: Logo + Agent Selector */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <SparkleIcon sx={{ fontSize: 18, color: PALETTE.accent }} />

          {/* Agent Selector */}
          <FormControl size="small" sx={{ width: 160, ...dropdownStyles.formControl }} disabled={agentsLoading || agentsError !== null}>
            <Select
              value={availableAgents.length ? selectedAgentId : ''}
              onChange={(e) => setSelectedAgentId(e.target.value)}
              renderValue={(value) => {
                const agent = availableAgents.find((a) => a.id === value);
                return (
                  <Typography
                    variant="body2"
                    sx={{
                      fontWeight: 600,
                      fontSize: '0.85rem',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {agent?.nickname || ''}
                  </Typography>
                );
              }}
              sx={{
                height: 32,
                fontSize: '0.85rem',
                bgcolor: isDarkMode ? PALETTE.inputBg : '#fff',
                borderRadius: 1.5,
                '& .MuiOutlinedInput-notchedOutline': {
                  borderColor: isDarkMode ? PALETTE.borderColor : 'grey.300',
                },
                '&:hover .MuiOutlinedInput-notchedOutline': {
                  borderColor: PALETTE.accent,
                },
                '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
                  borderColor: PALETTE.accent,
                },
                '& .MuiSelect-select': {
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1,
                  py: 0.5,
                },
              }}
              MenuProps={{
                PaperProps: {
                  sx: {
                    bgcolor: isDarkMode ? PALETTE.surface : '#fff',
                    border: '1px solid',
                    borderColor: isDarkMode ? PALETTE.borderColor : 'grey.200',
                    boxShadow: PALETTE.cardShadow,
                    maxWidth: 280,
                  }
                }
              }}
            >
              {availableAgents.map((agent) => (
                <MenuItem
                  key={agent.id}
                  value={agent.id}
                  sx={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                    py: 0.75,
                    maxWidth: 280,
                    '&:hover': { bgcolor: isDarkMode ? PALETTE.hoverBg : 'grey.100' },
                    '&.Mui-selected': { bgcolor: isDarkMode ? PALETTE.hoverBg : 'grey.100' },
                  }}
                >
                  <Typography variant="body2" sx={{ fontWeight: 600, lineHeight: 1.2 }}>
                    {agent.nickname}
                  </Typography>
                  <Typography
                    variant="caption"
                    sx={{
                      color: 'text.secondary',
                      fontSize: '0.7rem',
                      lineHeight: 1.2,
                      maxWidth: 260,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {(() => {
                      const idx = agent.description.indexOf('. ');
                      return idx === -1 ? agent.description : agent.description.substring(0, idx + 1);
                    })()}
                  </Typography>
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          {/* Model pill for the currently-selected agent */}
          {(() => {
            const selectedAgent = availableAgents.find(a => a.id === selectedAgentId);
            const label = formatModelLabel(selectedAgent?.model || '');
            if (!label) return null;
            return (
              <Tooltip title={`Model: ${selectedAgent?.model}`} placement="bottom" arrow>
                <Box
                  sx={{
                    px: 1,
                    py: 0.25,
                    borderRadius: 1,
                    border: '1px solid',
                    borderColor: isDarkMode ? PALETTE.borderColor : 'grey.300',
                    bgcolor: isDarkMode ? PALETTE.surface : 'grey.100',
                    color: 'text.secondary',
                    fontSize: '0.7rem',
                    fontWeight: 500,
                    fontFamily: 'monospace',
                    lineHeight: 1.6,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {label}
                </Box>
              </Tooltip>
            );
          })()}
        </Box>

        {/* Right: Device Controls + Auto-redirect toggle + Section Toggles */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          {/* Device Controls */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {/* Target Selection Dropdown */}
            <FormControl
              size="small"
              sx={{
                width: 200,
                ...dropdownStyles.formControl,
                ...(autoSelectionFeedback.device && {
                  '& .MuiOutlinedInput-root': {
                    borderColor: PALETTE.accent,
                    boxShadow: `0 0 0 1px ${PALETTE.accent}40`,
                  }
                })
              }}
            >
              <InputLabel id="agent-chat-device-select-label">
                Target {autoSelectionFeedback.device && '🤖'}
              </InputLabel>
              <Select
                labelId="agent-chat-device-select-label"
                value={selectedDeviceFullValue}
                onChange={(e) => handleDeviceSelection(e.target.value)}
                label="Target"
                sx={dropdownStyles.select}
                MenuProps={dropdownStyles.menuProps}
                renderValue={(value) => {
                  if (!value) return <em>Select Target...</em>;
                  const [hostName, deviceId] = (value as string).split(':');
                  const device = getAllDevices().find(
                    (d) => d.hostName === hostName && d.device_id === deviceId
                  );
                  if (!device) return value as string;
                  const targetLabel = (device.device_name || device.device_id).replace(/_Host$/, '');
                  return targetLabel;
                }}
              >
                <MenuItem value="" sx={dropdownStyles.menuItemPlaceholder}>
                  <em>Select Target...</em>
                </MenuItem>
                {getAllDevices()
                  .map((device) => {
                    const hostName = device.hostName || '';
                    const targetLabel = (device.device_name || device.device_id).replace(/_Host$/, '');
                    return { device, hostName, targetLabel };
                  })
                  .sort((a, b) =>
                    a.hostName.localeCompare(b.hostName, undefined, { numeric: true })
                  )
                  .map(({ device, hostName, targetLabel }) => (
                    <MenuItem
                      key={`${hostName}:${device.device_id}`}
                      value={`${hostName}:${device.device_id}`}
                      sx={dropdownStyles.menuItem}
                    >
                      <Box
                        sx={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 1,
                          width: '100%',
                          minWidth: 0,
                        }}
                      >
                        <Typography
                          variant="body2"
                          sx={{
                            fontSize: '0.8rem',
                            flex: '0 1 34%',
                            minWidth: 0,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {targetLabel}
                        </Typography>
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          sx={{
                            fontSize: '0.7rem',
                            flex: '1 1 auto',
                            minWidth: 0,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {hostName}
                        </Typography>
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          sx={{
                            fontSize: '0.7rem',
                            flex: '0 0 auto',
                            textAlign: 'right',
                          }}
                        >
                          {device.device_model}
                        </Typography>
                      </Box>
                    </MenuItem>
                  ))}
              </Select>
            </FormControl>

            {/* UserInterface Selection Dropdown */}
            <Box sx={{ width: 150 }}>
              {userInterfacesLoaded ? (
                <UserinterfaceSelector
                  deviceModel={getSelectedDeviceModel()}
                  value={selectedUserInterface}
                  onChange={handleUserInterfaceSelection}
                  label="Interface"
                  size="small"
                  fullWidth
                  dropdownStyles={dropdownStyles}
                  disableAutoSelect={hasUserSelectedInterface}
                />
              ) : (
                <FormControl
                  size="small"
                  fullWidth
                  sx={{
                    ...dropdownStyles.formControl,
                    ...(autoSelectionFeedback.userinterface && {
                      '& .MuiOutlinedInput-root': {
                        borderColor: PALETTE.accent,
                        boxShadow: `0 0 0 1px ${PALETTE.accent}40`,
                      }
                    })
                  }}
                >
                  <InputLabel id="agent-chat-userinterface-select-label">
                    Interface {autoSelectionFeedback.userinterface && '🤖'}
                  </InputLabel>
                  <Select
                    labelId="agent-chat-userinterface-select-label"
                    value=""
                    disabled
                    label="Interface"
                    sx={dropdownStyles.select}
                    MenuProps={dropdownStyles.menuProps}
                  >
                    <MenuItem value="" sx={dropdownStyles.menuItemPlaceholder}>
                      <em>Loading...</em>
                    </MenuItem>
                  </Select>
                </FormControl>
              )}
            </Box>

            {/* TestCase Selection Dropdown */}
            <FormControl
              size="small"
              sx={{
                width: 150,
                ...dropdownStyles.formControl,
                ...(autoSelectionFeedback.testcase && {
                  '& .MuiOutlinedInput-root': {
                    borderColor: PALETTE.accent,
                    boxShadow: `0 0 0 1px ${PALETTE.accent}40`,
                  }
                })
              }}
            >
              <InputLabel id="agent-chat-testcase-select-label">
                Test Case {autoSelectionFeedback.testcase && '🤖'}
              </InputLabel>
              <Select
                labelId="agent-chat-testcase-select-label"
                value={selectedTestCase || ''}
                onChange={(e) => handleTestCaseSelection(e.target.value)}
                label="Test Case"
                disabled={isLoadingTestCases}
                sx={dropdownStyles.select}
                MenuProps={dropdownStyles.menuProps}
              >
                <MenuItem value="" sx={dropdownStyles.menuItemPlaceholder}>
                  <em>{isLoadingTestCases ? 'Loading...' : 'Select Test Case...'}</em>
                </MenuItem>
                {testCaseList.map((tc) => (
                  <MenuItem
                    key={tc.testcase_id}
                    value={tc.testcase_id}
                    sx={dropdownStyles.menuItem}
                  >
                    {tc.testcase_name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            {/* Campaign Selection Dropdown */}
            <FormControl
              size="small"
              sx={{
                width: 150,
                ...dropdownStyles.formControl,
                ...(autoSelectionFeedback.campaign && {
                  '& .MuiOutlinedInput-root': {
                    borderColor: PALETTE.accent,
                    boxShadow: `0 0 0 1px ${PALETTE.accent}40`,
                  }
                })
              }}
            >
              <InputLabel id="agent-chat-campaign-select-label">
                Campaign {autoSelectionFeedback.campaign && '🤖'}
              </InputLabel>
              <Select
                labelId="agent-chat-campaign-select-label"
                value={selectedCampaign || ''}
                onChange={(e) => handleCampaignSelection(e.target.value)}
                label="Campaign"
                disabled={isLoadingCampaigns}
                sx={dropdownStyles.select}
                MenuProps={dropdownStyles.menuProps}
              >
                <MenuItem value="" sx={dropdownStyles.menuItemPlaceholder}>
                  <em>{isLoadingCampaigns ? 'Loading...' : 'Select Campaign...'}</em>
                </MenuItem>
                {campaignList.map((campaign) => (
                  <MenuItem
                    key={campaign.campaign_id}
                    value={campaign.campaign_id}
                    sx={dropdownStyles.menuItem}
                  >
                    {campaign.campaign_name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

          </Box>

          
          {/* Section Toggles */}
          <Box sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 0.5,
            p: 0.5,
            borderRadius: 2,
            bgcolor: isDarkMode ? 'rgba(0,0,0,0.2)' : 'rgba(0,0,0,0.05)',
          }}>
            {/* Interactivity Toggle */}
            <Box sx={{
              pr: 1,
              mr: 1,
              borderRight: '1px solid',
              borderColor: isDarkMode ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)',
            }}>
              <Tooltip title="Enable smart UI interactivity">
                <FormControlLabel
                  control={
                    <Switch
                      checked={isInteractivityEnabled}
                      onChange={(e) => setIsInteractivityEnabled(e.target.checked)}
                      size="small"
                      sx={{
                        '& .MuiSwitch-switchBase.Mui-checked': {
                          color: PALETTE.accent,
                          '&:hover': {
                            backgroundColor: 'rgba(99, 102, 241, 0.1)',
                          },
                        },
                        '& .MuiSwitch-switchBase.Mui-checked + .MuiSwitch-track': {
                          backgroundColor: PALETTE.accent,
                        },
                      }}
                    />
                  }
                  label={
                    <Typography variant="caption" sx={{ fontSize: '0.75rem', color: 'text.secondary' }}>

                    </Typography>
                  }
                  sx={{
                    mx: 0,
                    '& .MuiFormControlLabel-label': {
                      fontSize: '0.75rem',
                    }
                  }}
                />
              </Tooltip>
            </Box>

            <SectionToggle
              active={showHistory}
              onClick={() => {
                if (!showHistory && showDevice && showRemote) {
                  // Would create 4 panels - auto-hide remote to maintain 3-panel max
                  setShowRemote(false);
                }
                setShowHistory(!showHistory);
              }}
              icon={SidebarIcon}
              tooltip={showHistory ? "Hide history" : "Show history"}
            />
            <SectionToggle
              active={showContentViewer}
              onClick={() => {
                if (showContentViewer) {
                  // Hide content viewer - go to full chat (keep selections)
                  setShowContentViewer(false);
                  setContentViewerFullscreen(false);
                  setContentType(null);
                  setContentData(null);
                  setContentTitle(undefined);
                  // Don't clear selectedUserInterface/selectedTestCase - user might toggle back
                } else {
                  // Show content viewer - minimize chat
                  setShowContentViewer(true);
                  // If we have selections, show them automatically
                  if (selectedUserInterface) {
                    setActiveContentTab('navigation');
                    setContentType('navigation-tree');
                    setContentData({ userinterface_name: selectedUserInterface });
                    setContentTitle(`Navigation: ${selectedUserInterface}`);
                  } else if (selectedTestCase) {
                    setActiveContentTab('testcase');
                    setContentType('testcase-flow');
                    setContentData({ testcase_id: selectedTestCase });
                    const tc = testCaseList.find(t => t.testcase_id === selectedTestCase);
                    setContentTitle(tc ? `Test Case: ${tc.testcase_name}` : 'Test Case');
                  }
                }
              }}
              icon={ChatPanelIcon}
              tooltip={showContentViewer ? "Hide content viewer" : "Show content viewer"}
            />
            <SectionToggle
              active={showDevice}
              onClick={handleDevicePanelToggle}
              icon={DevicePanelIcon}
              tooltip={showDevice ? "Hide device panel" : "Show device panel"}
            />
            <SectionToggle
              active={showRemote}
              onClick={handleRemotePanelToggle}
              icon={RemoteIcon}
              tooltip={showRemote ? "Hide remote control" : "Show remote control"}
            />
          </Box>
        </Box>
      </Box>

      {/* Main Content Area */}
      <Box sx={{
        flex: 1,
        display: 'flex',
        overflow: 'hidden',
      }}>
        {/* Left Sidebar - hidden in fullscreen */}
        {!contentViewerFullscreen && renderLeftSidebar()}

        {/* Center - Content Viewer + Chat (vertical split) */}
        <Box 
          data-content-container
          sx={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            minWidth: 0,
            overflow: 'hidden',
            position: 'relative',
          }}
        >
          {/* Content Viewer (top area - shown when user toggles it on) */}
          {showContentViewer && (
            <Box sx={{
              height: contentViewerFullscreen ? '100%' : `${contentViewerHeight}%`,
              minHeight: 200,
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}>
              <ContentViewer
                contentType={contentType}
                contentData={contentData}
                title={contentTitle}
                isLoading={contentLoading}
                activeTab={activeContentTab}
                onTabChange={(tab) => {
                  setActiveContentTab(tab);
                  // Update content type based on tab
                  if (tab === 'navigation' && selectedUserInterface) {
                    setContentType('navigation-tree');
                    setContentData({ userinterface_name: selectedUserInterface });
                    setContentTitle(`Navigation: ${selectedUserInterface}`);
                  } else if (tab === 'testcase' && selectedTestCase) {
                    const tc = testCaseList.find(t => t.testcase_id === selectedTestCase);
                    setContentType('testcase-flow');
                    setContentData({ testcase_id: selectedTestCase });
                    setContentTitle(tc ? `Test Case: ${tc.testcase_name}` : 'Test Case');
                  }
                }}
                selectedUserInterface={selectedUserInterface}
                selectedTestCase={selectedTestCase}
                selectedCampaign={selectedCampaign}
                selectedDevices={selectedDevices}
                isFullscreen={contentViewerFullscreen}
                onFullscreenChange={(fullscreen) => {
                  setContentViewerFullscreen(fullscreen);
                }}
                onClose={() => {
                  setShowContentViewer(false);
                  setContentViewerFullscreen(false);
                  setContentType(null);
                  setContentData(null);
                  setContentTitle(undefined);
                }}
              />
            </Box>
          )}

          {/* Vertical Resizer - draggable divider */}
          {showContentViewer && !contentViewerFullscreen && (
            <Box
              onMouseDown={() => setIsResizing(true)}
              sx={{
                height: 4,
                bgcolor: isDarkMode ? PALETTE.borderColor : 'grey.300',
                cursor: 'ns-resize',
                flexShrink: 0,
                transition: 'background-color 0.2s',
                '&:hover': {
                  bgcolor: PALETTE.accent,
                },
                '&:active': {
                  bgcolor: PALETTE.accent,
                },
              }}
            />
          )}

          {/* Chat Area - hidden in fullscreen */}
          {(!contentViewerFullscreen || !showContentViewer) && (
            <Box sx={{
              height: showContentViewer ? `${100 - contentViewerHeight}%` : '100%',
              minHeight: showContentViewer ? 200 : 'auto',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}>
              {(() => {
                // Determine if we should show empty state (same logic as original)
                const isSystemConversation = activeConversationId?.startsWith('bg_');
                const hasNoMessages = messages.length === 0;
                const onChatsTabWithNoRegularConvo = sidebarTab === 'chats' && (!activeConversationId || isSystemConversation);
                // Show system placeholder only when on system tab AND (no conversation selected OR selected conversation is not a system one)
                const onSystemTabWithNoSelection = sidebarTab === 'system' && (!activeConversationId || !isSystemConversation);

                // Debug: Log render conditions
                console.log('[AgentChat] Render check:', {
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
                  return (
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
                          color: 'text.secondary',
                          fontWeight: 400,
                          opacity: 0.6,
                        }}
                      >
                        No incident selected
                      </Typography>
                    </Box>
                  );
                }

                // Show empty state when ready AND (no messages OR on chats tab without a regular conversation OR active conversation with no messages)
                const showEmpty = status === 'ready' && (hasNoMessages || onChatsTabWithNoRegularConvo || (activeConversationId && messages.length === 0));

                if (showEmpty) {
                  return (
                    <Box sx={{
                      flex: 1,
                      display: 'flex',
                      flexDirection: 'column',
                      '& > *': {
                        flex: 1,
                        overflow: 'auto',
                      },
                    }}>
                      {renderEmptyState()}
                    </Box>
                  );
                } else {
                  // When in discussion (has messages), messages align to bottom with input reserved at bottom
                  return (
                    <Box sx={{
                      flex: 1,
                      display: 'flex',
                      flexDirection: 'column',
                      minHeight: 0,
                    }}>
                      {renderChatContent()}
                    </Box>
                  );
                }
              })()}
            </Box>
          )}
        </Box>

        {/* Right Panel - hidden in fullscreen */}
        {!contentViewerFullscreen && renderRightPanel()}
      </Box>

      {/* Confirm Dialog */}
      <ConfirmDialog
        open={confirmDialog.open}
        title={confirmDialog.title}
        message={confirmDialog.message}
        confirmText="OK"
        cancelText="Cancel"
        confirmColor="error"
        onConfirm={confirmDialog.onConfirm}
        onCancel={() => setConfirmDialog(prev => ({ ...prev, open: false }))}
      />
    </Box>
  );
};

const AgentChatWithProviders: React.FC = () => (
  <VNCStateProvider>
    <AgentChat />
  </VNCStateProvider>
);

export default AgentChatWithProviders;
