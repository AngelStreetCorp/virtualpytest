/**
 * TASK-113 — migration-3: the ALL-mode landing for /settings.
 *
 * In ALL mode the Settings page cannot operate on a single server —
 * branding, restart, AI routing, etc. are per-server actions. The
 * landing page lists every eligible server and lets the user pick
 * one to edit; clicking "Edit" sets the picker to that single
 * server, which reveals the existing single-server Settings UI.
 *
 * This is the minimum-viable per-server Settings table the
 * rewrite's §5.4 calls for: a list of rows, each carrying the
 * home server, with one click per row that scopes the rest of
 * the page to that server. A future PR can add inline edit
 * drawers; the per-row dispatch helpers from PR-D are already
 * in place to make that path short.
 */
import React from 'react';
import {
  Box,
  Card,
  CardActionArea,
  CardContent,
  Chip,
  Stack,
  Typography,
} from '@mui/material';
import { useServerManager } from '../../hooks/useServerManager';
import { useServerPicker } from '../../hooks/useServerPicker';
import { isAllServersSentinel } from '../../lib/allServer/scope';
import { buildServerConnectionList } from '../../lib/allServer/serverConnectionList';

interface AllServersSettingsLandingProps {
  /**
   * Optional sub-title shown above the server list. Defaults to
   * "Pick a server to edit its settings." A future PR can let the
   * host pass a different message per tab.
   */
  hint?: string;
}

const urlForDisplay = (url: string): string => {
  try {
    return new URL(url).host;
  } catch {
    return url.replace(/^https?:\/\//, '');
  }
};

export const AllServersSettingsLanding: React.FC<AllServersSettingsLandingProps> = ({
  hint,
}) => {
  const { serverHostsData, serverAuthStates, selectedServer } = useServerManager();
  const { handleChange } = useServerPicker();
  const isAll = isAllServersSentinel(selectedServer);
  const eligible = buildServerConnectionList(serverHostsData, serverAuthStates);
  const hostCountByServer = new Map<string, number>();
  for (const entry of serverHostsData) {
    const url = entry.server_info?.server_url;
    if (!url) continue;
    hostCountByServer.set(url, (entry.hosts ?? []).length);
  }

  if (!isAll) return null;

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 1 }}>
        {hint ?? 'Pick a server to edit its settings'}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Settings are per-server. Choose a server below to open its settings page;
        you can come back to ALL mode at any time with the picker.
      </Typography>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} flexWrap="wrap" useFlexGap>
        {eligible.map((server) => (
          <Card
            key={server.serverId}
            sx={{ minWidth: 280, maxWidth: 360, flex: '1 1 280px' }}
            data-testid={`settings-server-card-${server.serverId}`}
          >
            <CardActionArea
              onClick={() => handleChange(server.serverId)}
              aria-label={`Edit settings on ${server.name}`}
            >
              <CardContent>
                <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
                  <Typography variant="h6" noWrap title={server.name}>
                    {server.name}
                  </Typography>
                  <Chip label={server.authState} size="small" />
                </Stack>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  {urlForDisplay(server.url)}
                </Typography>
                <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                  <Chip
                    label={`${hostCountByServer.get(server.serverId) ?? 0} host${(hostCountByServer.get(server.serverId) ?? 0) === 1 ? '' : 's'}`}
                    size="small"
                    variant="outlined"
                  />
                </Stack>
              </CardContent>
            </CardActionArea>
          </Card>
        ))}
      </Stack>
    </Box>
  );
};
