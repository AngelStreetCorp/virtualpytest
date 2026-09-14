import React from 'react';
import { Button } from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';

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
}) => {
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
        minWidth: size === 'small' ? 'auto' : undefined,
        backgroundColor: variant === 'contained' ? '#3b82f6' : undefined,
        color: variant === 'contained' ? '#ffffff' : undefined,
        '&:hover': {
          backgroundColor: variant === 'contained' ? '#2563eb' : undefined,
        },
        '&:disabled': {
          backgroundColor: '#6b7280',
          color: '#ffffff',
        },
      }}
    >
      {isExecuting ? 'Running...' : 'Run'}
    </Button>
  );
};