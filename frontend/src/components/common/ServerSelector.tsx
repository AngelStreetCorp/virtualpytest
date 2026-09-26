import React, { useEffect, useState } from 'react';
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
  // Set when the user cancels the dialog, so the effect below does not immediately
  // reopen what they just dismissed. Cleared when they ask for it again by picking the
  // server, or when its auth state changes under them (a session appearing elsewhere).
  const [dismissedAuthFor, setDismissedAuthFor] = useState<string | null>(null);

  // Prompt for the server that is ALREADY selected, not only for one being switched to.
  // Opening the dialog used to live solely in `handleChange`, which MUI's Select fires
  // only when the value actually changes — so a deployment with a single server had no
  // way to reach it at all: the server is already selected, re-picking it emits nothing,
  // and a `needs-auth` server is filtered out of the hosts fetch
  // (ServerManagerProvider), leaving "No servers connected" and a padlock with no way to
  // act on either. That is every fresh install of the mobile app, where the configured
  // server is always `needs-auth` on first launch — the one case where the prompt matters
  // most was the one case it never fired.
  useEffect(() => {
    if (!selectedServer || pendingAuthServer) return;
    if (serverAuthStates[selectedServer] !== 'needs-auth') return;
    if (dismissedAuthFor === selectedServer) return;
    setPendingAuthServer(selectedServer);
  }, [selectedServer, serverAuthStates, pendingAuthServer, dismissedAuthFor]);

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

  // Long server URLs (e.g. "virtualpytest-backend-server.onrender.com") overflow
  // the closed Select and wrap to a second line. Cap the displayed value at 30
  // chars with an ellipsis; the dropdown MenuItems keep the full text. The full
  // URL stays available via the browser title bar and the picker itself.
  const MAX_DISPLAY_LENGTH = 30;
  const truncateForDisplay = (value: string): string => {
    if (value.length <= MAX_DISPLAY_LENGTH) return value;
    return `${value.slice(0, MAX_DISPLAY_LENGTH - 1)}…`;
  };

  const renderSelectedServer = (value: unknown): React.ReactNode => {
    const serverUrl = typeof value === 'string' ? value : '';
    return truncateForDisplay(nameFor(serverUrl));
  };

  const handleChange = (serverUrl: string) => {
    if (serverAuthStates[serverUrl] === 'needs-auth') {
      // Picking it IS asking for the dialog, so an earlier dismissal no longer applies.
      setDismissedAuthFor(null);
      setPendingAuthServer(serverUrl);
      return;
    }
    setSelectedServer(serverUrl);
  };

  const handleAuthenticated = async () => {
    const serverUrl = pendingAuthServer;
    setPendingAuthServer(null);
    setDismissedAuthFor(null);
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
          renderValue={renderSelectedServer}
          startAdornment={isServerChanging ? (
            <CircularProgress size={16} sx={{ mr: 1, ml: -0.5 }} />
          ) : undefined}
          sx={{
            opacity: isServerChanging ? 0.7 : 1,
            '& .MuiSelect-select': {
              display: 'flex',
              alignItems: 'center',
              overflow: 'hidden',
              whiteSpace: 'nowrap',
              textOverflow: 'ellipsis',
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
        onCancel={() => {
          setDismissedAuthFor(pendingAuthServer);
          setPendingAuthServer(null);
        }}
        onAuthenticated={handleAuthenticated}
      />
    </>
  );
};
