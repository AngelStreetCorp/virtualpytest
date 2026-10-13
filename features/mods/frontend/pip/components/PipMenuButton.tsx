import { Check, Close, PictureInPictureAlt, SettingsRemote, TouchApp } from '@mui/icons-material';
import { Divider, IconButton, ListItemIcon, ListItemText, ListSubheader, Menu, MenuItem, Tooltip } from '@mui/material';
import React, { useState } from 'react';

import { useAgentChatPalette } from '../../../../../frontend/src/constants/agentChatTheme';
import { useResponsiveMode } from '../../../../../frontend/src/hooks/useResponsiveMode';
import { useI18n } from '../../../../../frontend/src/i18n/useI18n';
import { usePip } from '../hooks/usePip';
import { usePipControl } from '../hooks/usePipControl';

/** Top-bar button: pick the PiP device, take / release control, show / hide the remote, close. */
export const PipMenuButton: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { isMobile } = useResponsiveMode();
  const { state, hosts, host, device, paused, select, toggleRemote } = usePip();
  const { take, release } = usePipControl();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);

  if (isMobile) return null;
  const close = () => setAnchor(null);
  const active = !!state.selection;

  return (
    <>
      <Tooltip title={t('Picture-in-picture')}>
        <IconButton size="small" onClick={(e) => setAnchor(e.currentTarget)} sx={{ color: active ? P.accentText : P.textSecondary }}>
          <PictureInPictureAlt fontSize="small" />
        </IconButton>
      </Tooltip>
      <Menu anchorEl={anchor} open={!!anchor} onClose={close} slotProps={{ paper: { sx: { minWidth: 260, maxHeight: 480 } } }}>
        {active && host && device && [
          <MenuItem
            key="control"
            disabled={paused || state.controlBusy}
            onClick={() => {
              void (state.ownsControl ? release(host, device.device_id) : take(host, device.device_id));
              close();
            }}
          >
            <ListItemIcon>
              <TouchApp fontSize="small" />
            </ListItemIcon>
            <ListItemText primary={state.ownsControl ? t('Release control') : t('Take control')} />
          </MenuItem>,
          <MenuItem key="remote" disabled={!state.ownsControl} onClick={toggleRemote}>
            <ListItemIcon>
              <SettingsRemote fontSize="small" />
            </ListItemIcon>
            <ListItemText primary={state.remoteVisible ? t('Hide remote') : t('Show remote')} />
          </MenuItem>,
          <MenuItem
            key="close"
            onClick={() => {
              select(null);
              close();
            }}
          >
            <ListItemIcon>
              <Close fontSize="small" />
            </ListItemIcon>
            <ListItemText primary={t('Close picture-in-picture')} />
          </MenuItem>,
          <Divider key="divider" />,
        ]}
        {hosts.length === 0 && (
          <MenuItem disabled>
            <ListItemText primary={t('No device available')} />
          </MenuItem>
        )}
        {hosts.map((h) => [
          <ListSubheader key={`h-${h.host_name}`} sx={{ lineHeight: '32px', fontSize: '0.75rem' }}>
            {h.host_name}
          </ListSubheader>,
          ...h.devices.map((d) => {
            const selected = state.selection?.hostName === h.host_name && state.selection?.deviceId === d.device_id;
            return (
              <MenuItem
                key={`${h.host_name}:${d.device_id}`}
                selected={selected}
                onClick={() => {
                  select({ hostName: h.host_name, deviceId: d.device_id });
                  close();
                }}
              >
                <ListItemIcon>{selected && <Check fontSize="small" sx={{ color: P.accentText }} />}</ListItemIcon>
                <ListItemText primary={d.device_name || d.device_id} secondary={d.device_model} />
              </MenuItem>
            );
          }),
        ])}
      </Menu>
    </>
  );
};
