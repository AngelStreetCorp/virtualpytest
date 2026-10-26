import React from 'react';
import { Box, Tooltip } from '@mui/material';
import EngineeringIcon from '@mui/icons-material/Engineering';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useHostData } from '../../hooks/useHostManager';
import { useDeviceMaintenance } from '../../hooks/platformUpdate/useDeviceMaintenance';
import { useI18n } from '../../i18n/useI18n';

interface Props {
  hostName?: string | null;
  deviceId?: string | null;
  /** "host_name:device_id" as used by the Run and Campaign target selections. */
  deviceKey?: string | null;
  /** Name-based sites (pickers that only hold "device_name - host_name"): the device id is looked up. */
  deviceName?: string | null;
  /** A "device_name - host_name" picker label, split on the last " - " (host-only labels carry no device). */
  target?: string | null;
  size?: number;
}

/**
 * Warning marker for a device covered by a maintenance window (TASK-97 G5). Put it right next to the device
 * name wherever the name renders; it renders nothing for a device that is not covered.
 */
export const DeviceMaintenanceBadge: React.FC<Props> = ({ hostName, deviceId, deviceName, target, deviceKey, size = 16 }) => {
  const P = useAgentChatPalette();
  const { t, formatDate } = useI18n();
  const { getAllHosts } = useHostData();
  let host = hostName;
  let name = deviceName;
  let id = deviceId;
  if (deviceKey) {
    const at = deviceKey.indexOf(':');
    host = at >= 0 ? deviceKey.slice(0, at) : deviceKey;
    id = at >= 0 ? deviceKey.slice(at + 1) : null;
  }
  if (target) {
    const idx = target.lastIndexOf(' - ');
    host = idx >= 0 ? target.slice(idx + 3) : target;
    name = idx >= 0 ? target.slice(0, idx) : null;
  }
  if (!id && name && host) {
    id = getAllHosts()
      .find((h) => h.host_name === host)
      ?.devices?.find((d) => d.device_name === name)?.device_id;
  }
  const win = useDeviceMaintenance(host, id);
  if (!win) return null;
  const until = formatDate(new Date(win.window_end), { timeStyle: 'short' });
  const reason = win.reason || win.note || '';
  const label = reason
    ? t('Under maintenance until {time} — {reason}', { time: until, reason })
    : t('Under maintenance until {time}', { time: until });
  return (
    <Tooltip title={label}>
      <Box
        component="span"
        role="img"
        aria-label={label}
        sx={{ display: 'inline-flex', alignItems: 'center', verticalAlign: 'middle', ml: 0.5, color: P.warning }}
      >
        <EngineeringIcon sx={{ fontSize: size }} />
      </Box>
    </Tooltip>
  );
};

export default DeviceMaintenanceBadge;
