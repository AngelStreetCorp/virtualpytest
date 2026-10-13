import { Box } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { RemoteCommandSinkProvider } from '../../../contexts/RemoteCommandSinkContext';
import { useElementBox } from '../../../hooks/rec/useElementBox';
import type { GroupMember, RemoteCommandSink } from '../../../types/pages/groupControl.types';
import { RemotePanel } from '../../controller/remote/RemotePanel';

interface GroupRemoteSideProps {
  primary: GroupMember;
  remoteType: string;
  /** No longer used since the "Sends to N devices" header line was removed
   *  (BUG-0440); kept on the type so the caller doesn't need to change. */
  targets?: GroupMember[];
  sink: RemoteCommandSink;
  /** No longer used since the press_key debug log was removed (BUG-0440). */
  log?: unknown[];
  /** TASK-80: keys present on every controlled member — anything outside is greyed
   *  on the visible skin and the click is dropped server-side. */
  sharedKeys?: string[];
  onRelease: () => void;
}

/** The group profile's remote, laid out from the first member, with every send routed to the group. */
export const GroupRemoteSide: React.FC<GroupRemoteSideProps> = ({
  primary,
  remoteType,
  sink,
  sharedKeys,
  onRelease,
}) => {
  const P = useAgentChatPalette();
  // RemotePanel lays itself out inline only when given its container's size; without it, it floats.
  const { ref: remoteBoxRef, box: remoteBox } = useElementBox<HTMLDivElement>();

  return (
    <Box
      sx={{
        width: { xs: '100%', md: 320 },
        flexShrink: 0,
        borderLeft: { md: `1px solid ${P.borderColor}` },
        borderTop: { xs: `1px solid ${P.borderColor}`, md: 0 },
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
        bgcolor: P.surface,
      }}
    >
      <Box ref={remoteBoxRef} sx={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        <RemoteCommandSinkProvider sink={sink} disabledKeys={sharedKeys}>
          {remoteBox && (
            <RemotePanel
              host={primary.host}
              deviceId={primary.device.device_id}
              deviceModel={primary.device.device_model}
              remoteType={remoteType}
              isConnected
              onReleaseControl={onRelease}
              initialCollapsed={false}
              disableResize
              streamContainerDimensions={remoteBox}
              // remoteBox is the remote's own box, not a stream: a phone's tap overlay
              // placed there would cover the panel and swallow its clicks.
              showOverlay={false}
              disabledKeys={sharedKeys}
            />
          )}
        </RemoteCommandSinkProvider>
      </Box>
    </Box>
  );
};
