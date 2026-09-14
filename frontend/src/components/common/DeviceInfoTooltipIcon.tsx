/**
 * DeviceInfoTooltipIcon — a small info icon that reveals the latest (corrected)
 * device info and/or gateway (network environment) info on hover. Renders nothing
 * when neither exists, so it only appears for devices that have been scanned.
 *
 * Both maps ride along on the device payload from getAllHosts (`device.device_info`
 * and `device.gateway_info`), so this needs no fetch of its own. The tooltip shows
 * Device Info first, then GW Info below; clicking opens the editor on the relevant
 * tab.
 */
import { InfoOutlined as InfoIcon } from '@mui/icons-material';
import { Box, Tooltip, Typography } from '@mui/material';
import React from 'react';

interface Props {
  info?: Record<string, string> | null;
  gatewayInfo?: Record<string, string> | null;
  deviceName?: string;
  hostName?: string;
  fontSize?: number;
}

const Section: React.FC<{ heading: string; entries: [string, string][] }> = ({ heading, entries }) => (
  <Box sx={{ py: 0.5 }}>
    <Typography variant="caption" sx={{ fontWeight: 'bold', display: 'block', mb: 0.5 }}>
      {heading}
    </Typography>
    {entries.map(([key, value]) => (
      <Box
        key={key}
        sx={{ display: 'flex', gap: 1, fontFamily: 'monospace', fontSize: '0.7rem', lineHeight: 1.5, whiteSpace: 'nowrap' }}
      >
        <Box component="span" sx={{ opacity: 0.7 }}>
          {key}:
        </Box>
        <Box component="span">{String(value)}</Box>
      </Box>
    ))}
  </Box>
);

export const DeviceInfoTooltipIcon: React.FC<Props> = ({
  info,
  gatewayInfo,
  deviceName,
  hostName,
  fontSize = 16,
}) => {
  const deviceEntries = info ? Object.entries(info) : [];
  const gatewayEntries = gatewayInfo ? Object.entries(gatewayInfo) : [];
  if (deviceEntries.length === 0 && gatewayEntries.length === 0) return null;

  const openEditor = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!deviceName || !hostName) return;
    // Land on the tab that has data (gateway when only gateway info exists).
    const tab = deviceEntries.length === 0 ? 'gateway' : 'device';
    const url =
      `/device-info?device_name=${encodeURIComponent(deviceName)}` +
      `&host_name=${encodeURIComponent(hostName)}&tab=${tab}`;
    window.open(url, '_blank', 'noopener');
  };

  const title = (
    <Box>
      {deviceEntries.length > 0 && <Section heading="Device Info" entries={deviceEntries} />}
      {gatewayEntries.length > 0 && <Section heading="GW Info" entries={gatewayEntries} />}
    </Box>
  );

  return (
    <Tooltip
      title={title}
      arrow
      placement="top"
      slotProps={{
        // Style the tooltip surface like a small modal: opaque background,
        // border, and shadow. MUI's default `rgba(97,97,97,0.92)` bleeds into
        // the dark dashboard cards and made the content unreadable.
        tooltip: {
          sx: (theme) => ({
            maxWidth: 'none',
            backgroundColor: theme.palette.background.paper,
            color: theme.palette.text.primary,
            border: `1px solid ${theme.palette.divider}`,
            borderRadius: 1,
            boxShadow: theme.shadows[8],
            px: 1.5,
            py: 1,
            opacity: '1 !important',
          }),
        },
        arrow: {
          sx: (theme) => ({
            color: theme.palette.background.paper,
            '&::before': {
              border: `1px solid ${theme.palette.divider}`,
              backgroundColor: theme.palette.background.paper,
            },
          }),
        },
      }}
    >
      <InfoIcon
        sx={{
          fontSize,
          color: 'text.secondary',
          cursor: 'pointer',
          flexShrink: 0,
          '&:hover': { color: 'primary.main' },
        }}
        onClick={openEditor}
      />
    </Tooltip>
  );
};
