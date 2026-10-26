import { Box, Typography } from '@mui/material';
import { SxProps, Theme } from '@mui/material/styles';
import React from 'react';
import { TYPOGRAPHY } from '../../constants/typography';

/**
 * Bottom-right "what is running on this device" badge: the script/deployment name.
 *
 * It used to take an `ownerName` too and print "owner · script". That prop is gone: the
 * operator's name belongs to DeviceLockBadge at bottom-left, and while both existed the
 * name was rendered twice on the same tile. Two corners, one fact each — WHO is on the
 * device on the left, WHAT is running on the right.
 */
interface RunningScriptNameBadgeProps {
  scriptName: string | null;
  maxChars?: number;
  sx?: SxProps<Theme>;
  textSx?: SxProps<Theme>;
}

const truncate = (value: string, maxChars?: number) =>
  maxChars && value.length > maxChars ? `${value.slice(0, maxChars)}...` : value;

export const RunningScriptNameBadge: React.FC<RunningScriptNameBadgeProps> = ({
  scriptName,
  maxChars,
  sx,
  textSx,
}) => {
  if (!scriptName) {
    return null;
  }

  const label = truncate(scriptName, maxChars);

  return (
    <Box
      sx={{
        position: 'absolute',
        right: 8,
        bottom: 8,
        zIndex: 3,
        px: 0.75,
        py: 0.4,
        borderRadius: 1,
        backgroundColor: 'rgba(0, 0, 0, 0.7)',
        maxWidth: '85%',
        ...sx,
      }}
    >
      <Typography
        variant="caption"
        sx={{
          color: '#fff',
          fontSize: TYPOGRAPHY.caption.size,
          lineHeight: 1.2,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          ...textSx,
        }}
      >
        {label}
      </Typography>
    </Box>
  );
};
