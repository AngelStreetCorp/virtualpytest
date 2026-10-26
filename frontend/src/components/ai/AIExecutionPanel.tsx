/**
 * AI Execution Panel
 *
 * Single-purpose prompt panel: the user types what they want, hits Send, and the
 * system either runs it immediately (direct match, no AI) or shows the AI's answer
 * and waits for the user to click Run. One contextual button drives the whole
 * lifecycle: Send → Run → Running → Success/Failed.
 */

import { AppIcon } from '../../constants/icons';
import React, { useEffect } from 'react';
import { Box, Typography, TextField, Button, CircularProgress } from '@mui/material';

import { Host, Device } from '../../types/common/Host_Types';
import { UserinterfaceSelector } from '../common';
import { useAIExecutionPanel } from '../../hooks/useAIExecutionPanel';
import { RecOverlayPanel } from '../rec/RecOverlayPanel';
import { useI18n } from '../../i18n/useI18n';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';

interface AIExecutionPanelProps {
  host: Host;
  device: Device;
  isControlActive: boolean;
  isVisible: boolean;
  onClose: () => void;
  // Export disambiguation state to parent for modal rendering
  onDisambiguationDataChange?: (
    data: any,
    resolve: (selections: Record<string, string>, saveToDb: boolean) => void,
    cancel: () => void
  ) => void;
  // Lets the parent show the running-step overlay while a prompt run is in flight.
  onExecutingChange?: (isExecuting: boolean) => void;
}

export const AIExecutionPanel: React.FC<AIExecutionPanelProps> = ({
  host,
  device,
  isControlActive,
  isVisible,
  onClose,
  onDisambiguationDataChange,
  onExecutingChange,
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

  const P = useAgentChatPalette();
  const { t } = useI18n();

  useEffect(() => {
    onExecutingChange?.(isExecuting);
  }, [isExecuting, onExecutingChange]);

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
    <RecOverlayPanel
      title={t('AI Prompt')}
      onClose={onClose}
      headerExtra={
        <UserinterfaceSelector
          deviceModel={device.device_model}
          value={selectedUserinterface}
          onChange={setSelectedUserinterface}
          label=""
          size="small"
          fullWidth={false}
          sx={{ minWidth: 150, maxWidth: 220 }}
        />
      }
    >
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
          <Box sx={{ mb: 1.5, p: 1.5, backgroundColor: P.hoverBg, borderRadius: 1 }}>
            {isExecuting ? (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <CircularProgress size={16} />
                <Typography variant="body2" sx={{ color: P.textSecondary }}>
                  Executing “{actionLabel}”…
                </Typography>
              </Box>
            ) : executionStatus === 'success' ? (
              <Typography variant="body2" sx={{ color: P.success }}>
                <AppIcon name="success" /> Done: “{actionLabel}”
              </Typography>
            ) : executionStatus === 'fail' ? (
              <Typography variant="body2" sx={{ color: P.error }}>
                <AppIcon name="error" /> Failed: “{actionLabel}”
              </Typography>
            ) : (
              <Typography variant="body2" sx={{ color: P.textSecondary, fontSize: TYPOGRAPHY.body.size, whiteSpace: 'pre-line' }}>
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
    </RecOverlayPanel>
  );
};
