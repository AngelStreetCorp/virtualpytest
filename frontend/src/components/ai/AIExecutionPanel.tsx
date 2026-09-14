/**
 * AI Execution Panel
 *
 * Single-purpose prompt panel: the user types what they want, hits Send, and the
 * system either runs it immediately (direct match, no AI) or shows the AI's answer
 * and waits for the user to click Run. One contextual button drives the whole
 * lifecycle: Send → Run → Running → Success/Failed.
 */

import React from 'react';
import { Box, Typography, TextField, Button, CircularProgress } from '@mui/material';

import { Host, Device } from '../../types/common/Host_Types';
import { UserinterfaceSelector } from '../common';
import { useAIExecutionPanel } from '../../hooks/useAIExecutionPanel';

interface AIExecutionPanelProps {
  host: Host;
  device: Device;
  isControlActive: boolean;
  isVisible: boolean;
  // Export disambiguation state to parent for modal rendering
  onDisambiguationDataChange?: (
    data: any,
    resolve: (selections: Record<string, string>, saveToDb: boolean) => void,
    cancel: () => void
  ) => void;
}

export const AIExecutionPanel: React.FC<AIExecutionPanelProps> = ({
  host,
  device,
  isControlActive,
  isVisible,
  onDisambiguationDataChange,
}) => {
  const {
    prompt,
    setPrompt,
    selectedUserinterface,
    setSelectedUserinterface,
    graph,
    analysis,
    usedAI,
    actionLabel,
    isGenerating,
    isExecuting,
    executionStatus,
    handleSend,
    handleExecute,
  } = useAIExecutionPanel({ host, device, onDisambiguationDataChange });

  if (!isVisible) return null;

  const isAIAnswerWaiting = Boolean(graph && usedAI) && !isExecuting && executionStatus === 'idle';
  const showResult = isExecuting || executionStatus !== 'idle' || isAIAnswerWaiting;

  // Contextual primary button — one button for the entire flow.
  let button: {
    label: string;
    color: 'primary' | 'success' | 'error';
    onClick?: () => void;
    disabled: boolean;
    spinner: boolean;
  };
  if (isGenerating) {
    button = { label: 'Send', color: 'primary', disabled: true, spinner: true };
  } else if (isExecuting) {
    button = { label: 'Running…', color: 'primary', disabled: true, spinner: true };
  } else if (executionStatus === 'success') {
    button = { label: 'Success', color: 'success', disabled: true, spinner: false };
  } else if (executionStatus === 'fail') {
    button = { label: 'Failed — Retry', color: 'error', onClick: handleExecute, disabled: !isControlActive, spinner: false };
  } else if (isAIAnswerWaiting) {
    button = { label: 'Run', color: 'primary', onClick: handleExecute, disabled: !isControlActive, spinner: false };
  } else {
    button = {
      label: 'Send',
      color: 'primary',
      onClick: handleSend,
      disabled: !isControlActive || !prompt.trim() || !selectedUserinterface,
      spinner: false,
    };
  }

  return (
    <Box
      sx={{
        position: 'absolute',
        top: '50%',
        right: 10,
        transform: 'translateY(-50%)',
        // Sit above the stream caption/transcript/restart overlays (which use hardcoded
        // ~1250–1000040 z-indexes). The disambiguation modal is portaled to <body>, so it
        // still renders above this panel regardless of this value.
        zIndex: 1000050,
        pointerEvents: 'auto',
        width: '420px',
        backgroundColor: 'rgba(0,0,0,0.9)',
        borderRadius: 2,
        border: '1px solid rgba(255,255,255,0.2)',
        backdropFilter: 'blur(10px)',
      }}
    >
      <Box sx={{ p: 2 }}>
        {/* Title + interface selector on one line */}
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 1,
            mb: 1.5,
          }}
        >
          <Typography variant="subtitle1" sx={{ color: '#ffffff', fontWeight: 600, whiteSpace: 'nowrap' }}>
            AI Prompt
          </Typography>
          <UserinterfaceSelector
            deviceModel={device.device_model}
            value={selectedUserinterface}
            onChange={setSelectedUserinterface}
            label=""
            size="small"
            fullWidth={false}
            sx={{ minWidth: 150, maxWidth: 220 }}
          />
        </Box>

        <TextField
          size="small"
          fullWidth
          multiline
          rows={3}
          placeholder={
            isControlActive
              ? "What should I do? (e.g. 'Go to live TV and check audio')"
              : 'Take control of the device first'
          }
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          disabled={!isControlActive || isGenerating || isExecuting}
          sx={{ mb: 1.5 }}
        />

        {/* Result / progress area */}
        {showResult && (
          <Box sx={{ mb: 1.5, p: 1.5, backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: 1 }}>
            {isExecuting ? (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <CircularProgress size={16} />
                <Typography variant="body2" sx={{ color: '#ddd' }}>
                  Executing “{actionLabel}”…
                </Typography>
              </Box>
            ) : executionStatus === 'success' ? (
              <Typography variant="body2" sx={{ color: '#4caf50' }}>
                ✓ Done: “{actionLabel}”
              </Typography>
            ) : executionStatus === 'fail' ? (
              <Typography variant="body2" sx={{ color: '#f44336' }}>
                ✕ Failed: “{actionLabel}”
              </Typography>
            ) : (
              <Typography variant="body2" sx={{ color: '#ddd', fontSize: '0.85rem', whiteSpace: 'pre-line' }}>
                {analysis}
              </Typography>
            )}
          </Box>
        )}

        <Button
          variant="contained"
          fullWidth
          color={button.color}
          onClick={button.onClick}
          disabled={button.disabled}
          startIcon={button.spinner ? <CircularProgress size={16} color="inherit" /> : undefined}
        >
          {button.label}
        </Button>
      </Box>
    </Box>
  );
};
