/**
 * Utility functions for Agent Chat
 */

import type { AgentEvent, Conversation } from '../hooks/aiagent';

const stableSerialize = (value: unknown): string => {
  if (value === null || value === undefined) return '';
  if (typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableSerialize).join(',')}]`;

  const entries = Object.entries(value as Record<string, unknown>)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, nestedValue]) => `"${key}":${stableSerialize(nestedValue)}`);

  return `{${entries.join(',')}}`;
};

// timestamp is part of the key: distinct events can carry byte-identical
// payloads (e.g. two tool_results both "✅ 1/1 passed (0ms)"), while genuine
// re-deliveries of one event keep the backend-stamped timestamp — so this
// still dedupes real duplicates without eating look-alike neighbors.
export const getEventDedupKey = (event: AgentEvent): string => stableSerialize({
  type: event.type,
  timestamp: event.timestamp || '',
  agent: event.agent,
  content: event.content?.trim() || '',
  tool_name: event.tool_name || '',
  tool_params: event.tool_params || null,
  tool_result: event.tool_result || null,
  success: event.success ?? null,
  error: event.error || '',
  task_id: event.task_id || '',
  task_type: event.task_type || '',
  queue_name: event.queue_name || '',
  dry_run: event.dry_run ?? null,
});

export const dedupeEvents = (events: AgentEvent[]): AgentEvent[] => {
  const seen = new Set<string>();
  return events.filter(event => {
    const key = getEventDedupKey(event);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
};

/**
 * Extract initials from a name (e.g., "John Doe" -> "JD")
 */
export const getInitials = (name: string) => 
  name.split(' ').map(n => n[0]).join('').substring(0, 2);

/**
 * Merge tool_call events with their corresponding tool_result/error events by sequence order
 * Events come in order: tool_call → tool_result/error → tool_call → tool_result/error → ...
 */
export const mergeToolEvents = (events: AgentEvent[]): AgentEvent[] => {
  const uniqueEvents = dedupeEvents(events);
  const merged: AgentEvent[] = [];
  let pendingToolCall: AgentEvent | null = null;
  
  for (const event of uniqueEvents) {
    if (event.type === 'tool_call') {
      // If there was a previous tool call without result, add it as-is
      if (pendingToolCall) {
        merged.push(pendingToolCall);
      }
      pendingToolCall = { ...event };
    } else if (event.type === 'tool_result' && pendingToolCall) {
      // Link result to the pending tool call
      merged.push({
        ...pendingToolCall,
        tool_result: event.tool_result,
        success: event.success,
      });
      pendingToolCall = null;
    } else if (event.type === 'error' && pendingToolCall) {
      // Link error to the pending tool call - mark as failure
      const errorContent = event.content || event.error || 'Tool error';
      merged.push({
        ...pendingToolCall,
        tool_result: errorContent,
        success: false,
        error: errorContent,
      });
      pendingToolCall = null;
    }
  }
  
  // Don't forget the last pending call if exists
  if (pendingToolCall) {
    merged.push(pendingToolCall);
  }
  
  return merged;
};

/**
 * Group conversations by time period (Today, Yesterday, This Week, etc.)
 */
export const groupConversationsByTime = (conversations: Conversation[]) => {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 24 * 60 * 60 * 1000);
  const thisWeek = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000);
  const thisMonth = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000);

  const groups: { label: string; items: Conversation[] }[] = [
    { label: 'Today', items: [] },
    { label: 'Yesterday', items: [] },
    { label: 'This Week', items: [] },
    { label: 'This Month', items: [] },
    { label: 'Older', items: [] },
  ];

  conversations.forEach(conv => {
    const date = new Date(conv.updatedAt);
    if (date >= today) {
      groups[0].items.push(conv);
    } else if (date >= yesterday) {
      groups[1].items.push(conv);
    } else if (date >= thisWeek) {
      groups[2].items.push(conv);
    } else if (date >= thisMonth) {
      groups[3].items.push(conv);
    } else {
      groups[4].items.push(conv);
    }
  });

  return groups.filter(g => g.items.length > 0);
};


