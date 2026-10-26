/**
 * TASK-113 — PR-C: the per-row home-server chip.
 *
 * Every row rendered under ALL mode carries a small chip naming the
 * home server, so a user can tell at a glance which peer a device /
 * project / script / etc. belongs to. The chip is read-only and
 * inert in v1; clicking it does NOT switch the picker (that would
 * lose the ALL view, and the spec says the user shouldn't have to
 * think about which server).
 *
 * The label is the registry's display name (`server_info.server_name`)
 * or, as a fallback, the URL host. The component is intentionally
 * dumb — no theming, no tooltip, no interactions. Pages that want
 * a richer presentation can compose their own.
 */
import React from 'react';
import { Chip } from '@mui/material';
import { useServerManager } from '../../hooks/useServerManager';
import { TYPOGRAPHY } from '../../constants/typography';

interface ServerChipProps {
  /** The home server's URL (the resource's `server_url` field). */
  serverUrl: string;
  /** Optional override for the label. */
  label?: string;
  /** Chip size. Default 'small'. */
  size?: 'small' | 'medium';
}

const labelFor = (url: string, serverName: string | undefined): string => {
  if (serverName) return serverName;
  try {
    return new URL(url).host;
  } catch {
    return url.replace(/^https?:\/\//, '');
  }
};

export const ServerChip: React.FC<ServerChipProps> = ({
  serverUrl,
  label,
  size = 'small',
}) => {
  const { serverHostsData } = useServerManager();
  const serverName = serverHostsData.find(
    (s) => s.server_info?.server_url === serverUrl,
  )?.server_info?.server_name;
  return (
    <Chip
      label={label ?? labelFor(serverUrl, serverName)}
      size={size}
      variant="outlined"
      sx={{ height: 20, fontSize: TYPOGRAPHY.caption.size }}
    />
  );
};
