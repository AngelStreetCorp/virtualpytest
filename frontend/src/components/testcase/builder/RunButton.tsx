import React from 'react';
import { Button, SxProps, Theme } from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';

interface RunButtonProps {
  onExecute: () => void;
  isExecuting: boolean;
  isExecutable: boolean;
  selectedDeviceId: string | null;
  isControlActive: boolean;
  userinterfaceName: string;
  disabled?: boolean;
  size?: 'small' | 'medium' | 'large';
  variant?: 'contained' | 'outlined' | 'text';
  showIcon?: boolean;
  /** Extra styles merged over the defaults (a page can recolour Run to its palette). */
  sx?: SxProps<Theme>;
}

export const RunButton: React.FC<RunButtonProps> = ({
  onExecute,
  isExecuting,
  isExecutable,
  selectedDeviceId,
  isControlActive,
  userinterfaceName,
  disabled = false,
  size = 'small',
  variant = 'contained',
  showIcon = true,
  sx,
}) => {
  const P = useAgentChatPalette();
  const isDisabled = disabled ||
    isExecuting ||
    !selectedDeviceId ||
    !isControlActive ||
    !userinterfaceName ||
    !isExecutable;

  const getTooltipText = () => {
    if (!userinterfaceName) return 'Select a userinterface first';
    if (!selectedDeviceId) return 'Select a device first';
    if (!isControlActive) return 'Take control of device first';
    if (!isExecutable) return 'Connect START block to at least one action';
    if (isExecuting) return 'Test is running';
    return 'Run test case on device';
  };

  return (
    <Button
      size={size}
      variant={variant}
      startIcon={showIcon ? <PlayArrowIcon /> : undefined}
      onClick={onExecute}
      disabled={isDisabled}
      title={getTooltipText()}
      sx={{
        // Run is the app's gold primary action (same palette as the AI pages), in both themes.
        minWidth: size === 'small' ? 'auto' : undefined,
        textTransform: 'none',
        fontWeight: 600,
        boxShadow: 'none',
        backgroundColor: variant === 'contained' ? P.accent : undefined,
        color: variant === 'contained' ? '#1a1a1a' : P.accentText,
        borderColor: variant === 'outlined' ? P.accent : undefined,
        '&:hover': {
          backgroundColor: variant === 'contained' ? P.accentHover : `${P.accent}1a`,
          boxShadow: 'none',
        },
        '&:disabled': {
          backgroundColor: variant === 'contained' ? P.hoverBg : undefined,
          color: P.textMuted,
        },
        ...(sx as object),
      }}
    >
      {isExecuting ? 'Running...' : 'Run'}
    </Button>
  );
};