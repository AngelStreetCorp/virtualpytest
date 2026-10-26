/**
 * Settings -> Maintenance (TASK-97): declare, edit and end a maintenance window that is not part of a
 * Platform update. Scope "platform" = banner on every page; scope "devices" = banner on Devices/Dashboard and a
 * marker next to each selected device's name. Admin only (the tab is hidden for others, the routes enforce it).
 */
import { Star as StarIcon } from '@mui/icons-material';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Autocomplete, Box, Button, Chip, FormControlLabel, Radio, RadioGroup, TextField, Typography,
} from '@mui/material';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { neutralButtonSx } from '../common/PageChrome';
import { DeviceFavoriteStar } from '../common/DeviceFavoriteStar';
import { goldButtonSx } from '../common/PageChrome';
import { deviceMaintenanceKey, useMaintenanceWindow, type MaintenanceScope } from '../../hooks/platformUpdate/useMaintenanceWindow';
import { useDeviceFavorites } from '../../hooks/useDeviceFavorites';
import { useHostData } from '../../hooks/useHostManager';
import { useI18n } from '../../i18n/useI18n';
import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { TYPOGRAPHY } from '../../constants/typography';

const BASE = '/server/platform-update/windows';

interface StoredWindow {
  id: string;
  scope: MaintenanceScope;
  device_ids: string[];
  window_start: string;
  window_end: string;
  reason: string;
  created_by: string;
  state: 'upcoming' | 'active' | 'ended';
}

interface DeviceOption {
  key: string;
  label: string;
  host_name: string;
  device_id: string;
}

const toLocalInput = (date: Date): string => {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

export const MaintenanceSettings: React.FC = () => {
  const P = useAgentChatPalette();
  const { t, formatDate } = useI18n();
  const { getAllHosts } = useHostData();
  const { reload: reloadShared } = useMaintenanceWindow();

  const [windows, setWindows] = useState<StoredWindow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [start, setStart] = useState(() => toLocalInput(new Date()));
  const [end, setEnd] = useState(() => toLocalInput(new Date(Date.now() + 60 * 60 * 1000)));
  const [reason, setReason] = useState('');
  const [scope, setScope] = useState<MaintenanceScope>('devices');
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const options: DeviceOption[] = useMemo(
    () =>
      getAllHosts().flatMap((host) =>
        (host.devices || []).map((d) => ({
          key: deviceMaintenanceKey(host.host_name, d.device_id),
          label: `${d.device_name || d.device_id} (${host.host_name})`,
          host_name: host.host_name,
          device_id: d.device_id,
        })),
      ),
    [getAllHosts],
  );
  // Favorites (TASK-99): pinned first, with a chip that adds / removes all of them from the window.
  const favorites = useDeviceFavorites();
  const favoriteKeys = useMemo(
    () => options.filter((o) => favorites.isFavorite(o.host_name, o.device_id)).map((o) => o.key),
    [options, favorites],
  );
  const orderedKeys = useMemo(
    () => [...favoriteKeys, ...options.map((o) => o.key).filter((k) => !favoriteKeys.includes(k))],
    [options, favoriteKeys],
  );
  const allFavoritesSelected = favoriteKeys.length > 0 && favoriteKeys.every((k) => selected.includes(k));
  const toggleFavorites = () =>
    setSelected((prev) =>
      allFavoritesSelected
        ? prev.filter((k) => !favoriteKeys.includes(k))
        : Array.from(new Set([...prev, ...favoriteKeys])),
    );
  const labelOf = useCallback((key: string) => options.find((o) => o.key === key)?.label ?? key, [options]);

  const load = useCallback(async () => {
    try {
      const response = await apiClient(buildServerUrl(BASE));
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || response.statusText);
      setWindows(data.windows);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const reset = () => {
    setEditingId(null);
    setStart(toLocalInput(new Date()));
    setEnd(toLocalInput(new Date(Date.now() + 60 * 60 * 1000)));
    setReason('');
    setScope('devices');
    setSelected([]);
  };

  const call = async (url: string, method: string, body?: unknown) => {
    setBusy(true);
    setError(null);
    try {
      const response = await apiClient(buildServerUrl(url), {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || response.statusText);
      await Promise.all([load(), reloadShared()]);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const valid =
    !!start && !!end && new Date(end) > new Date(start) && (scope === 'platform' || selected.length > 0);

  const save = async () => {
    const body = {
      window_start: new Date(start).toISOString(),
      window_end: new Date(end).toISOString(),
      reason,
      scope,
      device_ids: scope === 'devices' ? selected : [],
    };
    const ok = editingId ? await call(`${BASE}/${editingId}`, 'PUT', body) : await call(BASE, 'POST', body);
    if (ok) reset();
  };

  const edit = (w: StoredWindow) => {
    setEditingId(w.id);
    setStart(toLocalInput(new Date(w.window_start)));
    setEnd(toLocalInput(new Date(w.window_end)));
    setReason(w.reason);
    setScope(w.scope);
    setSelected(w.device_ids);
  };

  const when = (iso: string) => formatDate(new Date(iso), { dateStyle: 'short', timeStyle: 'short' });
  const stateColor = (s: StoredWindow['state']) => (s === 'active' ? P.warning : s === 'upcoming' ? P.textSecondary : P.textMuted);

  return (
    <Box sx={{ maxWidth: 860 }}>
      <Typography sx={{ color: P.textSecondary, fontSize: TYPOGRAPHY.body.size, mb: 2 }}>
        {t('A maintenance window warns users. Platform: a banner on every page. Devices: a banner on Devices and Dashboard, and a warning icon next to each selected device name.')}
      </Typography>

      {error ? (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      ) : null}

      <Box sx={{ border: `1px solid ${P.borderColor}`, bgcolor: P.surface, borderRadius: 1.5, p: 2, mb: 3 }}>
        <Typography sx={{ fontWeight: 600, mb: 1 }}>
          {editingId ? t('Edit maintenance window') : t('New maintenance window')}
        </Typography>
        <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', mb: 1.5 }}>
          <TextField size="small" type="datetime-local" label={t('Window start')} value={start} onChange={(e) => setStart(e.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField size="small" type="datetime-local" label={t('Window end')} value={end} onChange={(e) => setEnd(e.target.value)} InputLabelProps={{ shrink: true }} />
        </Box>
        <TextField size="small" fullWidth label={t('Reason')} value={reason} onChange={(e) => setReason(e.target.value)} inputProps={{ maxLength: 500 }} sx={{ mb: 1.5 }} />
        <RadioGroup row value={scope} onChange={(e) => setScope(e.target.value as MaintenanceScope)}>
          <FormControlLabel value="devices" control={<Radio size="small" />} label={t('Selected devices')} />
          <FormControlLabel value="platform" control={<Radio size="small" />} label={t('Full platform')} />
        </RadioGroup>
        {scope === 'devices' ? (
          <>
            {favoriteKeys.length > 0 ? (
              <Chip
                size="small"
                icon={<StarIcon sx={{ fontSize: TYPOGRAPHY.body.size, color: `${P.gold} !important` }} />}
                label={`${t('Favorites')} ${favoriteKeys.length}`}
                onClick={toggleFavorites}
                variant={allFavoritesSelected ? 'filled' : 'outlined'}
                sx={{ mt: 1, borderColor: P.gold, color: P.textPrimary, ...(allFavoritesSelected ? { bgcolor: P.hoverBg } : {}) }}
              />
            ) : null}
            <Autocomplete
              multiple
              size="small"
              options={orderedKeys}
              groupBy={favoriteKeys.length > 0 ? (key) => (favoriteKeys.includes(key) ? t('Favorites') : t('All devices')) : undefined}
              getOptionLabel={labelOf}
              renderOption={(optionProps, key) => {
                const { key: reactKey, ...rest } = optionProps as React.HTMLAttributes<HTMLLIElement> & { key: string };
                const option = options.find((o) => o.key === key);
                return (
                  <li key={reactKey} {...rest}>
                    {labelOf(key)}
                    {option ? (
                      <span style={{ marginLeft: 'auto', display: 'flex' }}>
                        <DeviceFavoriteStar hostName={option.host_name} deviceId={option.device_id} />
                      </span>
                    ) : null}
                  </li>
                );
              }}
              value={selected}
              onChange={(_, value) => setSelected(value)}
              renderInput={(params) => <TextField {...params} label={t('Devices')} />}
              sx={{ mt: 1, mb: 1 }}
            />
          </>
        ) : null}
        <Box sx={{ display: 'flex', gap: 1, mt: 1.5 }}>
          <Button variant="contained" disabled={!valid || busy} onClick={() => void save()} sx={goldButtonSx(P)}>
            {editingId ? t('Save changes') : t('Start maintenance window')}
          </Button>
          {editingId ? (
            <Button onClick={reset} disabled={busy}>{t('Cancel')}</Button>
          ) : null}
        </Box>
      </Box>

      <Typography sx={{ fontWeight: 600, mb: 1 }}>{t('Maintenance windows')}</Typography>
      {windows.length === 0 ? (
        <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.body.size }}>{t('No maintenance windows.')}</Typography>
      ) : (
        windows.map((w) => (
          <Box
            key={w.id}
            sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap', border: `1px solid ${P.borderColor}`, borderRadius: 1.5, px: 1.5, py: 1, mb: 1 }}
          >
            <Box sx={{ flex: 1, minWidth: 220 }}>
              <Typography sx={{ fontSize: TYPOGRAPHY.navbarItem.size }}>
                {when(w.window_start)} - {when(w.window_end)}
                {w.reason ? ` · ${w.reason}` : ''}
              </Typography>
              <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
                {w.scope === 'platform' ? t('Full platform') : w.device_ids.map(labelOf).join(', ')} · {w.created_by}
              </Typography>
            </Box>
            <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 600, color: stateColor(w.state) }}>
              {w.state === 'active' ? t('Active') : w.state === 'upcoming' ? t('Scheduled') : t('Ended')}
            </Typography>
            {w.state !== 'ended' ? (
              <>
                <Button size="small" disabled={busy} onClick={() => edit(w)}>{t('Edit')}</Button>
                <Button size="small" disabled={busy} onClick={() => void call(`${BASE}/${w.id}/end`, 'POST')} sx={neutralButtonSx(P)}>
                  {t('End now')}
                </Button>
              </>
            ) : null}
          </Box>
        ))
      )}
    </Box>
  );
};

export default MaintenanceSettings;
