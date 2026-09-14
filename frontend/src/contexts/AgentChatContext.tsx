/**
 * AgentChatContext — single source of truth for all agent conversations.
 *
 * Wraps useAgentChat hook as a global context provider so both the
 * Agent Chat page and the Cmd+K shortcut share the same conversation
 * engine, socket connection, and localStorage persistence.
 */

import React, { createContext, useContext } from 'react';
import { useAgentChat } from '../hooks/aiagent/useAgentChat';

// The context type is whatever useAgentChat returns
type AgentChatContextType = ReturnType<typeof useAgentChat>;

const AgentChatContext = createContext<AgentChatContextType | null>(null);

export const AgentChatProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const agentChat = useAgentChat();
  return (
    <AgentChatContext.Provider value={agentChat}>
      {children}
    </AgentChatContext.Provider>
  );
};

export const useAgentChatContext = (): AgentChatContextType => {
  const ctx = useContext(AgentChatContext);
  if (!ctx) {
    throw new Error('useAgentChatContext must be used within AgentChatProvider');
  }
  return ctx;
};
