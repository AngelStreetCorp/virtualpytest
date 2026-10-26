// AI Cache Management
export { useAICacheReset } from './useAICacheReset';

// AI Agent Chat
export { useAgentChat } from './useAgentChat';
export type { AgentEvent, Message, Session, Status, Conversation, BackgroundTask, BackgroundAgentInfo } from './useAgentChat';

// Atlas memory (TASK-172): the per-user, on-demand switch
export { useAtlasMemory } from './useAtlasMemory';
export type { AtlasMemoryStatus } from './useAtlasMemory';
