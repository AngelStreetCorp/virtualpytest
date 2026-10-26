import { useEffect, useState } from 'react';
import { useServerManager } from './useServerManager';
import { ServerAuthDialog } from '../components/auth/ServerAuthDialog';
import { getServerAuthInfo } from '../lib/serverIdentity';
import { buildServerPickerLabels } from '../utils/serverLabels';

/**
 * Server switching shared by ServerSelector (mobile) and ScopePicker (desktop header):
 * display labels, the needs-auth sign-in prompt (TASK-18) and the commit-after-sign-in switch.
 * Render `authDialog` once next to whatever lists the servers.
 */
export const useServerPicker = () => {
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

  // Prompt for the server that is ALREADY selected, not only for one being switched to:
  // a deployment with a single needs-auth server (every fresh mobile install) has no
  // change event to hang the prompt on, and the hosts fetch skips it entirely.
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

  // Two servers can share a SERVER_NAME (a copied .env, or a rename that reached only
  // one box); only colliding names get their host appended. Recomputed every render so
  // a name that arrives late still disambiguates at once.
  const pickerLabels = buildServerPickerLabels(availableServers, nameFor);
  const labelFor = (serverUrl: string): string => pickerLabels[serverUrl] ?? nameFor(serverUrl);

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

  const authDialog = (
    <ServerAuthDialog
      open={pendingAuthServer !== null}
      serverUrl={pendingAuthServer || ''}
      serverName={pendingAuthServer ? labelFor(pendingAuthServer) : undefined}
      onCancel={() => {
        setDismissedAuthFor(pendingAuthServer);
        setPendingAuthServer(null);
      }}
      onAuthenticated={handleAuthenticated}
    />
  );

  return {
    selectedServer,
    availableServers,
    failedServers,
    isServerChanging,
    serverAuthStates,
    labelFor,
    handleChange,
    authDialog,
  };
};
