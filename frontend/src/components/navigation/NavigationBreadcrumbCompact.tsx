import React from 'react';
import { Box, Typography, Chip } from '@mui/material';
import { ArrowBack, Home, ChevronRight } from '@mui/icons-material';
import { useNavigationStack } from '../../contexts/navigation/NavigationStackContext';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';

interface NavigationBreadcrumbCompactProps {
  onNavigateBack: () => void;
  onNavigateToLevel: (levelIndex: number) => void;
  onNavigateToRoot: () => void;
}

export const NavigationBreadcrumbCompact: React.FC<NavigationBreadcrumbCompactProps> = ({
  onNavigateBack,
  onNavigateToLevel,
  onNavigateToRoot,
}) => {
  const P = useAgentChatPalette();
  const { stack, isNested, currentLevel } = useNavigationStack();

  if (!isNested || !currentLevel) return null;

  // Get the root tree name from the navigation context (first level)
  const rootTreeName = stack.length > 0 && stack[0] ? 'root' : 'root';

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 0.5,
        backgroundColor: P.surface,
        border: `1px solid ${P.borderColor}`,
        borderRadius: '8px',
        padding: '8px 16px',
        margin: '8px 16px 0 16px',
        boxShadow: '0 1px 3px rgba(0, 0, 0, 0.12)',
        fontSize: TYPOGRAPHY.navbarItem.size,
        maxWidth: 'fit-content',
      }}
    >
      {/* Back Button */}
      <ArrowBack
        sx={{
          fontSize: TYPOGRAPHY.navbarItem.size,
          color: P.textMuted,
          cursor: 'pointer',
          '&:hover': { color: P.accentText },
        }}
        onClick={onNavigateBack}
      />
      {/* Home Icon - Clickable */}
      <Home
        sx={{
          fontSize: TYPOGRAPHY.navbarItem.size,
          color: P.textMuted,
          mx: 0.5,
          cursor: 'pointer',
          '&:hover': { color: P.accentText },
        }}
        onClick={onNavigateToRoot}
        titleAccess="Go to root navigation"
      />
      {/* Root Label - Clickable */}
      <Typography
        variant="caption"
        sx={{
          color: P.textMuted,
          fontSize: TYPOGRAPHY.body.size,
          fontWeight: 500,
          cursor: 'pointer',
          '&:hover': { color: P.accentText },
        }}
        onClick={onNavigateToRoot}
        title="Go to root navigation"
      >
        {rootTreeName}
      </Typography>
      {/* Show full chain if stack has multiple levels */}
      {stack.length > 1 &&
        stack.slice(0, -1).map((level, index) => (
          <React.Fragment key={index}>
            {/* Separator */}
            <ChevronRight sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textMuted }} />
            {/* Intermediate Level - Clickable */}
            <Typography
              variant="caption"
              sx={{
                color: P.textMuted,
                fontSize: TYPOGRAPHY.body.size,
                fontWeight: 500,
                cursor: 'pointer',
                '&:hover': { color: P.accentText },
              }}
              onClick={() => onNavigateToLevel(index)}
              title={`Go to ${level.parentNodeLabel}`}
            >
              {level.parentNodeLabel}
            </Typography>
          </React.Fragment>
        ))}
      {/* Final Separator */}
      <ChevronRight sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textMuted }} />
      {/* Current Level */}
      <Chip
        label={currentLevel.parentNodeLabel}
        size="small"
        sx={{
          height: '22px',
          fontSize: TYPOGRAPHY.body.size,
          fontWeight: 600,
          backgroundColor: P.hoverBg,
          color: P.accentText,
          '& .MuiChip-label': {
            padding: '0 8px',
          },
        }}
      />
    </Box>
  );
};