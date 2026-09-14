import { Box, Typography } from '@mui/material';
import { SxProps, Theme } from '@mui/material/styles';
import React from 'react';

interface RunningScriptNameBadgeProps {
  scriptName: string | null;
  /** Who holds the device / launched the run. Shown alongside the script name. */
  ownerName?: string | null;
  maxChars?: number;
  sx?: SxProps<Theme>;
  textSx?: SxProps<Theme>;
}

const truncate = (value: string, maxChars?: number) =>
  maxChars && value.length > maxChars ? `${value.slice(0, maxChars)}...` : value;

export const RunningScriptNameBadge: React.FC<RunningScriptNameBadgeProps> = ({
  scriptName,
  ownerName,
  maxChars,
  sx,
  textSx,
}) => {
  if (!scriptName && !ownerName) {
    return null;
  }

  // Both known → show both, each truncated on its own budget. Truncating the
  // joined string would eat the script name, which is the part that changes.
  const bothShown = Boolean(scriptName && ownerName);
  const partBudget = bothShown && maxChars ? Math.ceil(maxChars / 2) : maxChars;
  const label = [ownerName, scriptName]
    .filter(Boolean)
    .map((part) => truncate(part as string, partBudget))
    .join(' · ');

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
          fontSize: '0.7rem',
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
