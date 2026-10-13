/**
 * Top of Settings, inside the APK only: says which version is installed and, when a newer
 * one is published for download, offers it. The APK carries its own copy of the web bundle, so a
 * fix only reaches a phone through a new install — without this the phone has no way of knowing
 * one exists. Renders nothing on the web, or when the APK cannot tell (no download URL baked in,
 * sidecar unreachable).
 */
import { SystemUpdate as UpdateIcon } from '@mui/icons-material';
import { Alert, Button, Typography } from '@mui/material';
import { useEffect, useState } from 'react';

import { isPhoneAgentAvailable, phoneAgent, type AppUpdateInfo } from './native/phoneAgent';

export default function AppUpdateNotice() {
  const [info, setInfo] = useState<AppUpdateInfo | null>(null);

  useEffect(() => {
    if (!isPhoneAgentAvailable()) return;
    let cancelled = false;
    phoneAgent
      .checkUpdate()
      .then((i) => {
        if (!cancelled) setInfo(i);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (!info) return null;

  if (!info.updateAvailable) {
    return (
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
        App v{info.installedVersion}
        {info.latestCode !== undefined ? ' · up to date' : ''}
      </Typography>
    );
  }

  return (
    <Alert
      severity="info"
      icon={<UpdateIcon />}
      sx={{ mb: 2, alignItems: 'center' }}
      action={
        <Button color="inherit" variant="outlined" size="small" onClick={() => void phoneAgent.openUpdate()}>
          Update
        </Button>
      }
    >
      <Typography variant="body2" fontWeight={600}>
        Update available — v{info.latestVersion}
      </Typography>
      <Typography variant="caption">You have v{info.installedVersion}</Typography>
    </Alert>
  );
}
