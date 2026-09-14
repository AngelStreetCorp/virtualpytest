import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network disabled in tests')));
});

// NOTE: every mocked hook below returns *stable* function/array references
// (defined once at module scope inside the factory) rather than fresh
// literals on every call. AgentChat.tsx puts several of these functions in
// useEffect dependency arrays; a mock that hands back a new reference each
// render makes those effects re-fire every render and (since some of them
// unconditionally call setState with a new array) creates an infinite
// render loop that hangs the test runner instead of failing fast.

const mockAgentChatContextValue = {
  status: 'ready',
  session: null,
  messages: [] as any[],
  input: '',
  isProcessing: false,
  currentEvents: [] as any[],
  error: null,
  conversations: [] as any[],
  activeConversationId: null,
  pendingConversationId: null,
  backgroundTasks: [] as any[],
  setBackgroundAgents: () => {},
  setInput: () => {},
  sendMessage: () => {},
  handleApproval: () => {},
  stopGeneration: () => {},
  clearHistory: () => {},
  createNewConversation: () => {},
  switchConversation: () => {},
  deleteConversation: () => {},
  clearBackgroundHistory: () => {},
  setAgentId: () => {},
  setNavigationContext: () => {},
  setOnUIAction: () => {},
  reloadSkills: () => {},
  apiKeyInput: '',
  setApiKeyInput: () => {},
  saveApiKey: () => {},
  isValidating: false,
  activeProvider: '',
  activeModel: '',
  activeKeyEnv: '',
};

vi.mock('../../frontend/src/contexts/AgentChatContext', () => ({
  useAgentChatContext: () => mockAgentChatContextValue,
}));

vi.mock('../../frontend/src/hooks/aiagent/useToolExecutionTiming', () => {
  const shouldShowExecutingAnimation = () => false;
  return {
    useToolExecutionTiming: () => ({ shouldShowExecutingAnimation }),
  };
});

vi.mock('../../frontend/src/hooks/useHostManager', () => {
  const getAllHosts = () => [] as any[];
  const getAllDevices = () => [] as any[];
  const handleDeviceSelect = () => {};
  return {
    useHostData: () => ({ getAllHosts, getAllDevices }),
    useHostControl: () => ({ handleDeviceSelect }),
  };
});

vi.mock('../../frontend/src/contexts/VNCStateContext', () => ({
  VNCStateProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useVNCState: () => ({}),
}));

vi.mock('../../frontend/src/hooks/pages/useUserInterface', () => {
  const getAllUserInterfaces = async () => [] as any[];
  return {
    useUserInterface: () => ({ getAllUserInterfaces }),
  };
});

vi.mock('../../frontend/src/components/agent-chat/ConversationList', () => ({
  ConversationList: () => <div data-testid="conversation-list" />,
}));

vi.mock('../../frontend/src/components/agent-chat/ChatMessages', () => ({
  ChatMessages: () => <div data-testid="chat-messages" />,
}));

vi.mock('../../frontend/src/components/agent-chat/DevicePanel', () => ({
  DevicePanel: () => <div data-testid="device-panel" />,
}));

vi.mock('../../frontend/src/components/agent-chat/ContentViewer', () => ({
  ContentViewer: () => <div data-testid="content-viewer" />,
}));

vi.mock('../../frontend/src/components/agent-chat/PromptPresets', () => ({
  PromptPresets: () => <div data-testid="prompt-presets" />,
}));

vi.mock('../../frontend/src/components/controller/remote/RemotePanel', () => ({
  RemotePanel: () => <div data-testid="remote-panel" />,
}));

vi.mock('../../frontend/src/components/controller/desktop/DesktopPanel', () => ({
  DesktopPanel: () => <div data-testid="desktop-panel" />,
}));

vi.mock('../../frontend/src/components/controller/web/WebPanel', () => ({
  WebPanel: () => <div data-testid="web-panel" />,
}));

vi.mock('../../frontend/src/hooks/controller', () => {
  const streamValue = { streamUrl: null, isLoadingUrl: false };
  return {
    useStream: () => streamValue,
  };
});

vi.mock('../../frontend/src/hooks/aiagent/useInteractivityManager', () => {
  const feedback = {};
  const analyzePrompt = async () => {};
  const analyzeResponse = async () => {};
  const value = {
    getAutoSelectionFeedback: () => feedback,
    analyzePrompt,
    analyzeResponse,
  };
  return {
    useInteractivityManager: () => value,
  };
});

vi.mock('../../frontend/src/components/common/ConfirmDialog', () => ({
  ConfirmDialog: () => null,
}));

vi.mock('../../frontend/src/components/common/UserinterfaceSelector', () => ({
  UserinterfaceSelector: () => <div data-testid="userinterface-selector" />,
}));

import AgentChat from '../../frontend/src/pages/AgentChat';

describe('AgentChat page', () => {
  it('renders the AI Agent empty state', async () => {
    sessionStorage.setItem('agentchat_visited', 'true');

    render(
      <BrowserRouter>
        <AgentChat />
      </BrowserRouter>,
    );

    expect(await screen.findByRole('heading', { name: 'AI Agent', level: 5 })).toBeInTheDocument();
  });
});
