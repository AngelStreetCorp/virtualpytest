import React, { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Box, IconButton, Typography } from '@mui/material';
import BuildCircleOutlinedIcon from '@mui/icons-material/BuildCircleOutlined';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import CloseIcon from '@mui/icons-material/Close';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useHostData } from '../../hooks/useHostManager';
import { deviceMaintenanceKey, useMaintenanceWindow } from '../../hooks/platformUpdate/useMaintenanceWindow';
import { useI18n } from '../../i18n/useI18n';
import { TYPOGRAPHY } from '../../constants/typography';

const DISMISSED_KEY = 'virtualpytest:maintenance-notice-dismissed';

const readDismissed = (): string | null => {
  try {
    return window.localStorage.getItem(DISMISSED_KEY);
  } catch {
    return null;
  }
};

/**
 * Global maintenance banner (TASK-95 G9), mounted once in the app shell. Shows the planned window, who
 * started the update and its current step while a platform update is open; afterwards a dismissible
 * "done" notice for a couple of hours. Device-scoped windows (TASK-97) show a banner on the Devices and
 * Dashboard pages only, listing the covered devices; everywhere else their devices carry a badge.
 */
const DEVICE_BANNER_PATHS = ['/', '/device-control'];

const MaintenanceBanner: React.FC = () => {
  const P = useAgentChatPalette();
  const { t, formatDate } = useI18n();
  const { windows, notice } = useMaintenanceWindow();
  const { pathname } = useLocation();
  const { getAllHosts } = useHostData();
  const win = windows.find((w) => w.scope === 'platform');
  const deviceWins = windows.filter((w) => w.scope === 'devices');
  const deviceNames = useMemo(() => {
    const keys = new Set(deviceWins.flatMap((w) => w.device_ids));
    const names: string[] = [];
    for (const host of getAllHosts()) {
      for (const device of host.devices || []) {
        const key = deviceMaintenanceKey(host.host_name, device.device_id);
        if (keys.delete(key)) names.push(`${device.device_name || device.device_id} (${host.host_name})`);
      }
    }
    return [...names, ...keys]; // a key whose host is not registered right now is shown as is
  }, [windows, getAllHosts]);
  const [dismissed, setDismissed] = useState<string | null>(readDismissed());

  useEffect(() => {
    setDismissed(readDismissed());
  }, [notice?.run_id]);

  const when = (iso: string) => formatDate(new Date(iso), { dateStyle: 'short', timeStyle: 'short' });

  let color = P.warning;
  let Icon = BuildCircleOutlinedIcon;
  let text = '';
  let dismissKey: string | null = null;

  if (win && win.scope === 'platform') {
    text = win.current_step
      ? t('Maintenance: the platform is being updated, {start} to {end}. Started by {user} - now: {step}.', {
          start: when(win.window_start),
          end: when(win.window_end),
          user: win.started_by,
          step: t(win.current_step.title),
        })
      : t('Maintenance: the platform is under maintenance, {start} to {end}. {reason}', {
          start: when(win.window_start),
          end: when(win.window_end),
          reason: win.reason || '',
        }).trim();
  } else if (DEVICE_BANNER_PATHS.includes(pathname) && deviceWins.length > 0) {
    const end = new Date(Math.max(...deviceWins.map((w) => Date.parse(w.window_end))));
    const reason = deviceWins.map((w) => w.reason).filter(Boolean)[0] || '';
    text = t('Maintenance: these devices are unavailable until {end}: {devices}. {reason}', {
      end: when(end.toISOString()),
      devices: deviceNames.join(', '),
      reason,
    }).trim();
  } else if (!win && notice && notice.scope === 'platform' && dismissed !== notice.run_id) {
    dismissKey = notice.run_id;
    if (notice.status === 'ok') {
      color = P.success;
      Icon = CheckCircleOutlineIcon;
      text = t('The platform update is finished. Everything is available again.');
    } else {
      color = P.error;
      Icon = ErrorOutlineIcon;
      text =
        notice.status === 'rolled_back'
          ? t('The platform update was rolled back. The previous version is running.')
          : t('The platform update did not complete. Some features may be unavailable.');
    }
    if (notice.message) text = `${text} ${notice.message}`;
  } else {
    return null;
  }

  const dismiss = () => {
    if (!dismissKey) return;
    try {
      window.localStorage.setItem(DISMISSED_KEY, dismissKey);
    } catch {
      // not persisted; it simply shows again after a reload
    }
    setDismissed(dismissKey);
  };

  return (
    <Box
      role="status"
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        px: 2,
        py: 0.75,
        bgcolor: `${color}1f`,
        borderBottom: `1px solid ${color}66`,
        flexShrink: 0,
      }}
    >
      <Icon sx={{ fontSize: TYPOGRAPHY.cardTitle.size, color }} />
      <Typography sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textPrimary, flex: 1 }}>{text}</Typography>
      {dismissKey ? (
        <IconButton size="small" onClick={dismiss} aria-label={t('Dismiss')} sx={{ color: P.textSecondary }}>
          <CloseIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
        </IconButton>
      ) : null}
    </Box>
  );
};

export default MaintenanceBanner;
