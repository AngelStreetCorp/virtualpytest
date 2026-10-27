/**
 * Settings -> Frontend: the platform server list (TASK-179 P2).
 *
 * The servers in the picker are rows of `platform_servers`, read through `GET /server/servers`;
 * `VITE_SERVER_URL` stays the one bootstrap address. A platform admin edits the rows here and saves
 * them with `PUT /server/servers` (the whole list is replaced); everyone else sees the list read-only.
 * A 400 from the server carries the reason in `error` and is shown inline.
 */
import { Alert, Box, Button, Card, CardContent, IconButton, Switch, TextField, Typography } from '@mui/material';
import React, { useCallback, useEffect, useState } from 'react';

import { AppIcon } from '../../constants/icons';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useProfile } from '../../hooks/auth/useProfile';
import { useI18n } from '../../i18n/useI18n';
import {
  fetchPlatformServersPayload,
  setPlatformServers,
  type PlatformServer,
} from '../../lib/allServer/platformServers';
import { apiClient } from '../../utils/apiClient';
import { buildPrimaryServerUrl } from '../../utils/buildUrlUtils';
import { dangerIconSx, neutralButtonSx, primaryButtonSx } from '../common/PageChrome';

const ENDPOINT = '/server/servers';

export const ServerListSettings: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { isPlatformAdmin } = useProfile();

  const [rows, setRows] = useState<PlatformServer[]>([]);
  const [selfName, setSelfName] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchPlatformServersPayload(buildPrimaryServerUrl(ENDPOINT));
      setRows([...payload.servers].sort((a, b) => a.sort_order - b.sort_order));
      setSelfName(payload.self_name);
      setWarning(payload.warning);
      setDirty(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const edit = (index: number, patch: Partial<PlatformServer>) => {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
    setDirty(true);
  };

  const add = () => {
    const next = rows.reduce((max, r) => Math.max(max, r.sort_order), 0) + 10;
    setRows((prev) => [...prev, { name: '', url: '', enabled: true, sort_order: next }]);
    setDirty(true);
  };

  const remove = (index: number) => {
    setRows((prev) => prev.filter((_, i) => i !== index));
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const response = await apiClient(buildPrimaryServerUrl(ENDPOINT), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          servers: rows.map((r) => ({ ...r, name: r.name.trim(), url: r.url.trim() })),
        }),
      });
      const data = await response.json();
      if (!response.ok || data?.success === false) {
        throw new Error(data?.error || response.statusText);
      }
      // Publish the saved list so the picker follows without a reload, then re-read it for the warning.
      setPlatformServers(data.servers ?? []);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const readOnly = !isPlatformAdmin;

  return (
    <Card sx={{ mt: 2 }}>
      <CardContent>
        <Box display="flex" alignItems="center" gap={1} mb={0.5}>
          <AppIcon name="storage" size="md" color={P.accentText} />
          <Typography variant="h6" sx={{ flex: 1 }}>{t('Servers')}</Typography>
          <Button
            size="small"
            variant="outlined"
            sx={neutralButtonSx(P)}
            disabled={loading || saving}
            onClick={() => void load()}
            startIcon={<AppIcon name="refresh" />}
          >
            {t('Reload')}
          </Button>
        </Box>
        <Typography variant="caption" sx={{ color: P.textSecondary, display: 'block', mb: 1.5 }}>
          {readOnly
            ? t('The servers of the platform, shown in the server picker. Only a platform admin can edit this list.')
            : t('The servers of the platform, shown in the server picker. The server in Server URL above is always the first one. A server of this list that is turned off leaves the picker.')}
        </Typography>

        {selfName ? (
          <Typography variant="caption" sx={{ color: P.textMuted, display: 'block', mb: 1 }}>
            {t('This server is {name}.', { name: selfName })}
          </Typography>
        ) : null}
        {warning ? (
          <Alert severity="warning" sx={{ mb: 1.5 }}>{warning}</Alert>
        ) : null}
        {error ? (
          <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => setError(null)}>{error}</Alert>
        ) : null}

        {rows.length === 0 && !loading ? (
          <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.body.size, mb: 1.5 }}>
            {t('No servers in the list.')}
          </Typography>
        ) : null}

        {rows.map((row, index) => (
          <Box
            key={index}
            sx={{ display: 'flex', gap: 1.5, alignItems: 'center', flexWrap: 'wrap', mb: 1.5 }}
          >
            <TextField
              size="small"
              label={t('Name')}
              value={row.name}
              onChange={(e) => edit(index, { name: e.target.value })}
              disabled={readOnly || saving}
              sx={{ width: 190 }}
            />
            <TextField
              size="small"
              label={t('URL')}
              value={row.url}
              onChange={(e) => edit(index, { url: e.target.value })}
              placeholder="https://server.example.com" // i18n-ignore
              disabled={readOnly || saving}
              sx={{ flex: 1, minWidth: 240 }}
            />
            <TextField
              size="small"
              type="number"
              label={t('Order')}
              value={row.sort_order}
              onChange={(e) => edit(index, { sort_order: Number(e.target.value) || 0 })}
              disabled={readOnly || saving}
              sx={{ width: 90 }}
            />
            <Switch
              checked={row.enabled}
              onChange={(e) => edit(index, { enabled: e.target.checked })}
              disabled={readOnly || saving}
              inputProps={{ 'aria-label': t('Enabled') }}
            />
            {readOnly ? null : (
              <IconButton
                size="small"
                aria-label={t('Remove server')}
                sx={dangerIconSx(P)}
                disabled={saving}
                onClick={() => remove(index)}
              >
                <AppIcon name="delete" />
              </IconButton>
            )}
          </Box>
        ))}

        {readOnly ? null : (
          <Box display="flex" gap={1} mt={1}>
            <Button
              variant="outlined"
              sx={neutralButtonSx(P)}
              disabled={saving}
              onClick={add}
              startIcon={<AppIcon name="add" />}
            >
              {t('Add server')}
            </Button>
            <Button
              variant="contained"
              sx={primaryButtonSx(P)}
              disabled={!dirty || saving}
              onClick={() => void save()}
            >
              {t('Save servers')}
            </Button>
          </Box>
        )}
      </CardContent>
    </Card>
  );
};
