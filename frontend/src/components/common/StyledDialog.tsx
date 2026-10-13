import { Dialog, styled } from '@mui/material';

/**
 * Consistent styled Dialog: top-aligned. Border, radius, title and action spacing come
 * from the theme's MuiDialog overrides (docs/agent/platform/UI_STYLE.md "Dialogs").
 */
export const StyledDialog = styled(Dialog)(({ theme }) => ({
  // Top-aligned, not centred: dialogs whose content changes height (tabs, loading states)
  // would otherwise jump up and down as the centred paper re-centres.
  '& .MuiDialog-container': {
    alignItems: 'flex-start',
  },
  '& .MuiDialog-paper:not(.MuiDialog-paperFullScreen)': {
    marginTop: '10vh',
    maxHeight: `calc(90vh - ${theme.spacing(4)})`,
  },
}));

export default StyledDialog;

