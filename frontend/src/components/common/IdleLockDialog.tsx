import { DialogTitle, DialogContent, DialogActions, Button, Typography, LinearProgress, Box } from '@mui/material';
import React from 'react';

import { StyledDialog } from './StyledDialog';

interface IdleLockDialogProps {
  open: boolean;
  countdown: number;
  onDismiss: () => void;
}

const TOTAL_SECONDS = 10;

/**
 * "Are you still there?" dialog shown when manual control locks
 * have been held for too long without user activity.
 */
export const IdleLockDialog: React.FC<IdleLockDialogProps> = ({
  open,
  countdown,
  onDismiss,
}) => {
  const progress = (countdown / TOTAL_SECONDS) * 100;

  return (
    <StyledDialog
      open={open}
      onClose={onDismiss}
      maxWidth="xs"
      fullWidth
    >
      <DialogTitle sx={{ pb: 1 }}>Are you still there?</DialogTitle>
      <DialogContent>
        <Typography sx={{ mb: 2 }}>
          Your device control session has been idle for 3 minutes.
          Control will be released in <strong>{countdown}</strong> second{countdown !== 1 ? 's' : ''}.
        </Typography>
        <Box sx={{ width: '100%' }}>
          <LinearProgress
            variant="determinate"
            value={progress}
            color={countdown <= 3 ? 'error' : 'warning'}
            sx={{ height: 6, borderRadius: 3 }}
          />
        </Box>
      </DialogContent>
      <DialogActions sx={{ pt: 1, pb: 2, px: 3 }}>
        <Button
          onClick={onDismiss}
          variant="contained"
          color="primary"
          size="small"
          autoFocus
        >
          I&apos;m still here
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};
