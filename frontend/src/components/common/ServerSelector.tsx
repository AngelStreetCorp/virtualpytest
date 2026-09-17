import React, { useState } from 'react';
import { FormControl, InputLabel, Select, MenuItem, Chip, Box, CircularProgress, Tooltip } from '@mui/material';
import { Lock as LockIcon } from '@mui/icons-material';
import { useServerManager } from '../../hooks/useServerManager';
import { ServerAuthDialog } from '../auth/ServerAuthDialog';
import { getServerAuthInfo } from '../../lib/serverIdentity';

interface ServerSelectorProps {
  size?: 'small' | 'medium';
  minWidth?: number;
  label?: string;
  variant?: 'outlined' | 'standard' | 'filled';
}

export const ServerSelector: React.FC<ServerSelectorProps> = ({
  size = 'small',
  minWidth = 200,
  label = 'Server',
  variant = 'outlined'
}) => {
  const {
    selectedServer,
    setSelectedServer,
    availableServers,
    failedServers,
    serverHostsData,
    isServerChanging,
    serverAuthStates,
    refreshServerAuth,
  } = useServerManager();

  // Server the user picked but cannot reach yet for lack of a session (TASK-18).
  // The switch is NOT committed until the sign-in succeeds, so cancelling leaves the
  // previous server selected rather than stranding the UI on an unusable one.
  const [pendingAuthServer, setPendingAuthServer] = useState<string | null>(null);

  const nameFor = (serverUrl: string): string => {
    const serverData = serverHostsData.find((s) => s.server_info.server_url === serverUrl);
    if (serverData?.server_info.server_name) return serverData.server_info.server_name;
    // serverHostsData comes from the authenticated getAllHosts fetch, which skips
    // needs-auth servers by design — so without this a server you have not signed
    // into yet shows as a bare URL, in the picker AND in the sign-in dialog title.
    // /server/auth/check advertises server_name unauthenticated, precisely so the
    // name is known before the first login.
    const discovered = getServerAuthInfo(serverUrl)?.serverName;
    if (discovered) return discovered;
    return serverUrl.replace(/^https?:\/\//, '');
  };

  const handleChange = (serverUrl: string) => {
    if (serverAuthStates[serverUrl] === 'needs-auth') {
      setPendingAuthServer(serverUrl);
      return;
    }
    setSelectedServer(serverUrl);
  };

  const handleAuthenticated = async () => {
    const serverUrl = pendingAuthServer;
    setPendingAuthServer(null);
    if (!serverUrl) return;

    // Re-probe first so the server is no longer marked needs-auth, otherwise the
    // refresh that follows the switch would skip it.
    await refreshServerAuth();
    setSelectedServer(serverUrl);
  };

  return (
    <>
      <FormControl size={size} sx={{ minWidth }} variant={variant}>
        <InputLabel>{isServerChanging ? 'Switching...' : label}</InputLabel>
        <Select
          value={selectedServer}
          label={isServerChanging ? 'Switching...' : label}
          onChange={(e) => handleChange(e.target.value)}
          disabled={isServerChanging}
          startAdornment={isServerChanging ? (
            <CircularProgress size={16} sx={{ mr: 1, ml: -0.5 }} />
          ) : undefined}
          sx={{
            opacity: isServerChanging ? 0.7 : 1,
            '& .MuiSelect-select': {
              display: 'flex',
              alignItems: 'center',
            }
          }}
        >
          {availableServers.map((serverUrl) => {
            const isFailed = failedServers.has(serverUrl);
            const needsAuth = serverAuthStates[serverUrl] === 'needs-auth';
            const displayName = nameFor(serverUrl);

            return (
              <MenuItem
                key={serverUrl}
                value={serverUrl}
                disabled={isFailed}
                sx={{
                  color: isFailed ? '#d32f2f' : 'inherit',
                  '&.Mui-disabled': {
                    opacity: 1,
                    color: '#d32f2f'
                  }
                }}
              >
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                  {displayName}
                  {isFailed && (
                    <Chip
                      label="Offline"
                      size="small"
                      color="error"
                      sx={{ height: 20, fontSize: '0.7rem' }}
                    />
                  )}
                  {!isFailed && needsAuth && (
                    <Tooltip title="Different login — sign in to use this server">
                      <LockIcon sx={{ fontSize: 16, opacity: 0.7 }} />
                    </Tooltip>
                  )}
                </Box>
              </MenuItem>
            );
          })}
        </Select>
      </FormControl>

      <ServerAuthDialog
        open={pendingAuthServer !== null}
        serverUrl={pendingAuthServer || ''}
        serverName={pendingAuthServer ? nameFor(pendingAuthServer) : undefined}
        onCancel={() => setPendingAuthServer(null)}
        onAuthenticated={handleAuthenticated}
      />
    </>
  );
};
