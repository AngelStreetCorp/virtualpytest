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
import { TYPOGRAPHY } from '../../constants/typography';
import { useAgentChatContext } from '../../contexts/AgentChatContext';
import { useVoice } from '../../contexts/VoiceContext';
import { useI18n } from '../../i18n/useI18n';
import { VoiceCommandLine, VoiceConversationButton, VoiceError, VoiceMessageButton, VoiceRecordBar, VoiceSettingsButton, VoiceStrip } from '../ai/voice/VoiceControls';

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
  const voice = useVoice();
  const { t } = useI18n();
  const agentChat = useAgentChatContext();
  const recording = voice.phase === 'recording' && voice.surface === 'atlas';
  const talking = voice.conversation && voice.surface === 'atlas';
  return (
    <Box sx={{ pl: 5, pr: 0, py: 1.5, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 1 }}>
      {talking && <VoiceStrip />}
      <VoiceError />
      {!talking && <VoiceCommandLine />}
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
          {recording ? (
            <VoiceRecordBar
              height={44}
              onEdit={(text) => setInput(text)}
              onSend={(text) => { void agentChat.sendMessage(text); }}
            />
          ) : (
          <>
          <TextField
            fullWidth
            multiline
            maxRows={4}
            placeholder={talking ? t('Talk, or type. Both work.') : 'Message...'}
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
            InputProps={{ disableUnderline: true, sx: { fontSize: TYPOGRAPHY.navbarItem.size } }}
          />
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mr: 0.25 }}>
            <VoiceSettingsButton />
              <VoiceMessageButton surface="atlas" size={32} />
            {!isProcessing && <VoiceConversationButton surface="atlas" compact />}
          </Box>
          {(input.trim() || isProcessing) && (
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
            {isProcessing ? <StopIcon sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} /> : <SendIcon sx={{ fontSize: TYPOGRAPHY.cardTitle.size }} />}
          </IconButton>
          )}
          </>
          )}
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
                      // A call's result is the tool_result between it and the next call (tools run one at a
                      // time; a failed call has none). Matching by name showed the first result on every call.
                      const events = msg.events;
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
                <CopyIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Export">
            <span>
              <IconButton size="small" disabled={messages.length === 0} sx={{ opacity: messages.length > 0 ? 0.5 : 0.2, '&:hover': { opacity: 1 } }}>
                <ExportIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Clear all">
            <span>
              <IconButton size="small" onClick={clearHistory} disabled={conversations.length === 0} sx={{ opacity: conversations.length > 0 ? 0.5 : 0.2, '&:hover': { opacity: 1, color: 'error.main' } }}>
                <ClearIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
              </IconButton>
            </span>
          </Tooltip>
        </Box>
      </Box>
    </Box>
  );
};
