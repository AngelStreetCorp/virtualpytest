import React, { useContext } from 'react';
import { Box } from '@mui/material';
import { ServerSelector } from './ServerSelector';
import { MobileHeaderSlotContext } from '../../contexts/MobileHeaderSlotContext';

/**
 * Mobile replacement for the desktop AppBar's server picker. The AppBar is not rendered on
 * mobile (AppHeader), and it was the only place ServerSelector lived, so phones had no way
 * to switch servers — nor to get the sign-in prompt ServerSelector opens for a needs-auth
 * server. Rendered from AppHeader on Dashboard and Device, the pages that list hosts and devices. Pages put their header
 * actions on the same line through MobileHeaderActions.
 */
export const MobileServerBar: React.FC = () => {
  const setSlot = useContext(MobileHeaderSlotContext)?.setSlot;
  return (
    <Box sx={{ px: 1, pt: 1.5, display: 'flex', alignItems: 'center', gap: 1 }}>
      <Box sx={{ flex: 1, minWidth: 0, '& .MuiFormControl-root': { width: '100%' } }}>
        <ServerSelector size="small" minWidth={0} />
      </Box>
      <Box ref={setSlot} sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexShrink: 0, '&:empty': { display: 'none' } }} />
    </Box>
  );
};
