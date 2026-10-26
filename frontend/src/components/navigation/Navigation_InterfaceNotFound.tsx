import { Alert, Box, Button, Typography } from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import React from 'react';
import { useNavigate } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { primaryButtonSx } from '../common/PageChrome';

/**
 * The navigation editor could not resolve the interface it was asked for: the
 * name does not exist, or it exists in dev only and the link asked for the prod
 * snapshot. Without this screen the editor used to render as if the tree were
 * simply empty — a working-looking canvas reading "0/0 nodes" with "Add Node"
 * and "Publish" still live, so a developer would add nodes to the wrong place
 * (BUG-0774).
 */
export const NavigationInterfaceNotFound: React.FC<{
  /** The reason, in the words of the failed lookup. */
  message: string;
}> = ({ message }) => {
  const P = useAgentChatPalette();
  const navigate = useNavigate();

  return (
    <Box
      sx={{
        position: 'fixed',
        top: 64,
        left: 0,
        right: 0,
        bottom: 32,
        overflow: 'auto',
        p: 3,
      }}
    >
      <Box
        sx={{
          maxWidth: 560,
          mx: 'auto',
          mt: 6,
          display: 'flex',
          flexDirection: 'column',
          gap: 2,
          alignItems: 'flex-start',
        }}
      >
        <Typography sx={{ fontSize: TYPOGRAPHY.pageTitle.size, fontWeight: TYPOGRAPHY.pageTitle.weight, color: P.textPrimary }}>
          This tree cannot be opened
        </Typography>
        <Alert severity="error">{message}</Alert>
        <Button
          variant="contained"
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/configuration/interface')}
          sx={primaryButtonSx(P)}
        >
          Back to Interfaces
        </Button>
      </Box>
    </Box>
  );
};

export default NavigationInterfaceNotFound;
