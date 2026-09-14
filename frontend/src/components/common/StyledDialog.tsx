import { Dialog, styled } from '@mui/material';

/**
 * Consistent styled Dialog component with border and white button borders
 */
export const StyledDialog = styled(Dialog)(({ theme }) => ({
  '& .MuiDialog-paper': {
    border: `1px solid ${theme.palette.primary.main}`,
    borderRadius: theme.spacing(1),
  },
  '& .MuiDialogActions-root': {
    '& .MuiButton-outlined, & .MuiButton-contained': {
      border: '1px solid white',
      '&:hover': {
        border: '1px solid white',
      },
    },
  },
}));

export default StyledDialog;

