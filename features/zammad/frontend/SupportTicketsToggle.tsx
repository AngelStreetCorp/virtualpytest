/**
 * Zammad feature - the "Support tickets (Zammad)" row of Settings -> Features -> Feature Toggles.
 * Contributed through FeatureDefinition.settingsToggles, so core never names the feature and a build
 * with DISABLED_FEATURES=zammad has no such row. Reads the server's Enabled flag from /health and writes
 * it with PUT /enabled (admin only; the route enforces it), then refreshes the store so the Settings
 * menu entry appears or disappears without a reload.
 */
import { useCallback, useEffect, useState } from 'react';

import SettingRow from '../../../frontend/src/components/common/SettingRow';
import { usePermissions } from '../../../frontend/src/hooks/auth/usePermissions';
import { refreshReportEnabled } from './reportIncident';
import { ZammadConfig, zammadApi } from './zammadApi';

export default function SupportTicketsToggle() {
  const { hasRole } = usePermissions();
  const [config, setConfig] = useState<ZammadConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    zammadApi.health().then((h) => setConfig(h.config)).catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    load();
    window.addEventListener('vpt:server-changed', load);
    return () => window.removeEventListener('vpt:server-changed', load);
  }, [load]);

  const toggle = async (next: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const res = await zammadApi.setEnabled(next);
      setConfig(res.config);
      refreshReportEnabled();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const configured = Boolean(config?.configured);
  const caption = error
    ? error
    : config && !configured
      ? 'Connect a Zammad instance in Plugins first.'
      : 'Lets users open a support ticket from the Settings menu.';

  return (
    <SettingRow
      divider
      title="Support tickets (Zammad)"
      description={caption}
      checked={Boolean(config?.enabled)}
      disabled={!config || !configured || busy || !hasRole('admin')}
      onChange={toggle}
    />
  );
}
