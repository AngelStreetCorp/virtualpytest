// Legacy exports - redirect to new unified hook
export { useAI as useAIAgent } from '../useAI';

// AI Cache Management
export { useAICacheReset } from './useAICacheReset';

// AI Agent Chat
export { useAgentChat } from './useAgentChat';
export type { AgentEvent, Message, Session, Status, Conversation, BackgroundTask, BackgroundAgentInfo } from './useAgentChat';
