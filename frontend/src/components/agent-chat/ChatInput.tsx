/**
 * Chat Input Component - Bottom Input Area
 *
 * Handles message input, send/stop buttons, and action buttons.
 */

import React from 'react';
import {
  Box,
  Paper,
  TextField,
  IconButton,
  Tooltip,
} from '@mui/material';
import {
  ArrowUpward as SendIcon,
  Stop as StopIcon,
  ContentCopy as CopyIcon,
  FileDownload as ExportIcon,
  DeleteOutline as ClearIcon,
} from '@mui/icons-material';
import { AGENT_CHAT_PALETTE } from '../../constants/agentChatTheme';
import { Message } from '../../hooks/aiagent/useAgentChat';

interface ChatInputProps {
  input: string;
  setInput: (input: string) => void;
  sendMessage: () => void;
  isProcessing: boolean;
  stopGeneration: () => void;
  messages: Message[];
  conversations: any[];
  clearHistory: () => void;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  input,
  setInput,
  sendMessage,
  isProcessing,
  stopGeneration,
  messages,
  conversations,
  clearHistory,
}) => {
  return (
    <Box sx={{ px: 2, py: 1.5, flexShrink: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Paper
          elevation={0}
          sx={{
            p: 0.75,
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            bgcolor: 'background.paper',
            border: '1px solid',
            borderColor: 'divider',
            borderRadius: 2.5,
            transition: 'all 0.2s',
            '&:focus-within': { borderColor: AGENT_CHAT_PALETTE.accent },
          }}
        >
          <TextField
            fullWidth
            multiline
            maxRows={4}
            placeholder="Message..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
              }
            }}
            sx={{ ml: 1.5, flex: 1, py: 0.25 }}
            variant="standard"
            autoComplete="off"
            InputProps={{ disableUnderline: true, sx: { fontSize: '0.9rem' } }}
          />
          <IconButton
            onClick={isProcessing ? stopGeneration : sendMessage}
            disabled={!input.trim() && !isProcessing}
            sx={{
              m: 0.25,
              bgcolor: (input.trim() || isProcessing) ? AGENT_CHAT_PALETTE.accent : 'transparent',
              color: (input.trim() || isProcessing) ? '#fff' : 'text.disabled',
              width: 32, height: 32,
              '&:hover': { bgcolor: (input.trim() || isProcessing) ? AGENT_CHAT_PALETTE.accentHover : 'transparent' },
            }}
          >
            {isProcessing ? <StopIcon sx={{ fontSize: 18 }} /> : <SendIcon sx={{ fontSize: 18 }} />}
          </IconButton>
        </Paper>

        <Box sx={{ display: 'flex', gap: 0.25 }}>
          <Tooltip title="Copy messages">
            <span>
              <IconButton
                size="small"
                disabled={messages.length === 0}
                onClick={() => {
                  const text = messages.map(msg => {
                    const role = msg.role === 'user' ? 'You' : (msg.agent || 'Assistant');

                    if (msg.role === 'user') {
                      return `${role}: ${msg.content || ''}`;
                    }

                    // For assistant messages, include tools and response
                    const parts: string[] = [`${role}:`];

                    // Add tool calls with results
                    if (msg.events) {
                      const toolCalls = msg.events.filter(e => e.type === 'tool_call');
                      const toolResults = msg.events.filter(e => e.type === 'tool_result');

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

                      // Add message content
                      const content = msg.events
                        .filter(e => e.type === 'message' || e.type === 'result')
                        .map(e => e.content)
                        .join('\n')
                        .trim();
                      if (content) parts.push(`\n${content}`);
                    }

                    return parts.join('\n');
                  }).join('\n\n');
                  navigator.clipboard.writeText(text);
                }}
                sx={{ opacity: messages.length > 0 ? 0.5 : 0.2, '&:hover': { opacity: 1 } }}
              >
                <CopyIcon sx={{ fontSize: 16 }} />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Export">
            <span>
              <IconButton size="small" disabled={messages.length === 0} sx={{ opacity: messages.length > 0 ? 0.5 : 0.2, '&:hover': { opacity: 1 } }}>
                <ExportIcon sx={{ fontSize: 16 }} />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Clear all">
            <span>
              <IconButton size="small" onClick={clearHistory} disabled={conversations.length === 0} sx={{ opacity: conversations.length > 0 ? 0.5 : 0.2, '&:hover': { opacity: 1, color: 'error.main' } }}>
                <ClearIcon sx={{ fontSize: 16 }} />
              </IconButton>
            </span>
          </Tooltip>
        </Box>
      </Box>
    </Box>
  );
};
