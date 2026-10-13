import { Drawer } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { PANE_WIDTH } from '../constants';

import { ModSlot } from './ModSlot';
import { useMods } from './ModsProvider';

/** The right-hand pane a mod opens with `$.ui.openPane(id)`; non-modal, the page stays usable. */
export const ModPaneDrawer: React.FC = () => {
  const P = useAgentChatPalette();
  const { openPaneId } = useMods();

  return (
    <Drawer
      anchor="right"
      variant="persistent"
      open={openPaneId !== null}
      PaperProps={{
        sx: {
          width: { xs: '100%', sm: PANE_WIDTH },
          bgcolor: P.surface,
          borderLeft: `1px solid ${P.borderColor}`,
          boxShadow: 'none',
        },
      }}
    >
      {openPaneId && <ModSlot name="app.pane" props={{ paneId: openPaneId }} />}
    </Drawer>
  );
};
