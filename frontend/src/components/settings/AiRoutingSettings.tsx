/**
 * Settings → AI (TASK-30): which model serves each AI usage.
 *
 * Routing  — usage tree with the effective profile, layer, fallback chain and 24h stats;
 *            team overrides (settings.models:edit) and server-default routes (super admin).
 * Profiles — a model on an endpoint + parameters (super admin edits).
 * Endpoints — where requests go, with write-only API keys (super admin edits).
 * Prices    — USD per 1M tokens per endpoint + model, for the cost on Monitoring → AI usage (super admin edits).
 */

import {
  Refresh as RefreshIcon,
} from '@mui/icons-material';

import { AIIcon } from '../common/icons/CustomIcons';
import { Alert, Box, Button, Card, CardContent, CircularProgress, FormControl, InputLabel, MenuItem, Select, Snackbar, Tab, Tabs, Typography } from '@mui/material';
import React, { useCallback, useEffect, useState } from 'react';

import { TOAST_AUTO_HIDE_DURATION, TOAST_POSITION } from '../../constants/toastConfig';
import { usePermissionContext } from '../../contexts/auth/PermissionContext';

import { aiApi, errorMessage } from './ai/api';
import { EndpointsTab } from './ai/EndpointsTab';
import { PricesTab } from './ai/PricesTab';
import { ProfilesTab } from './ai/ProfilesTab';
import { RoutingTab } from './ai/RoutingTab';
import type { AiConfig, AiScope, AiUsageStats } from './ai/types';

export interface AiTabContext {
  config: AiConfig;
  stats: Record<string, AiUsageStats>;
  reload: () => Promise<void>;
  notify: (message: string) => void;
  fail: (message: string) => void;
  /** Team dropdown: '' = All (every team's overrides are listed, a new override needs a team picked). */
  scope: AiScope;
  /** Switch to another AI sub-tab: 0 Routing, 1 Profiles, 2 Endpoints, 3 Prices. */
  goToSub: (index: number) => void;
}

export const AiRoutingSettings: React.FC = () => {
  const { hasPermission } = usePermissionContext();
  const [subTab, setSubTab] = useState(() => {
    const sub = ['routing', 'profiles', 'endpoints', 'prices'].indexOf(new URLSearchParams(window.location.search).get('sub') ?? '');
    return sub < 0 ? 0 : sub; // ?sub=endpoints opens the Endpoints tab (a link from the AI usage page)
  });
  const [config, setConfig] = useState<AiConfig | null>(null);
  const [stats, setStats] = useState<Record<string, AiUsageStats>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [scope, setScope] = useState<AiScope>({ team: '', project: '' });
  const [options, setOptions] = useState<NonNullable<AiConfig['scope']>['options']>({ team: [], project: [] });

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const data = await aiApi.getConfig(scope);
      setConfig(data);
      if (data.scope?.options) setOptions(data.scope.options);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, 'Failed to load AI routing'));
    } finally {
      setLoading(false);
    }
    try {
      const s = await aiApi.getStats(24, scope);
      setStats(s.usages || {});
    } catch {
      setStats({}); // stats are informative only
    }
  }, [scope]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const ctx: AiTabContext | null = config
    ? { config, stats, reload, notify: setToast, fail: setError, scope, goToSub: setSubTab }
    : null;

  return (
    <Card>
      <CardContent>
        <Box display="flex" alignItems="center" mb={0.5}>
          <AIIcon sx={{ mr: 1 }} color="primary" />
          <Typography variant="h6" sx={{ flex: 1 }}>
            AI
          </Typography>
          <Button
            size="small"
            startIcon={loading ? <CircularProgress size={14} /> : <RefreshIcon />}
            onClick={() => void reload()}
            disabled={loading}
          >
            Reload
          </Button>
        </Box>
        <Typography variant="caption" color="text.secondary">
          Every AI call names its usage.
        </Typography>

        <Box display="flex" gap={1} flexWrap="wrap" mt={1}>
          {([['team', 'Team', options.team], ['project', 'Project', options.project]] as const).map(([field, label, list]) => (
            <FormControl key={field} size="small" sx={{ width: 190, flexShrink: 0 }}>
              <InputLabel id={`ai-scope-${field}`} shrink>{label}</InputLabel>
              <Select
                labelId={`ai-scope-${field}`}
                label={label}
                notched
                displayEmpty
                value={scope[field]}
                onChange={(e) => setScope((prev) => ({ ...prev, [field]: e.target.value }))}
                renderValue={(v) => (v ? list.find((o) => o.key === v)?.label ?? v : 'All')}
                MenuProps={{ transitionDuration: 0 }}
              >
                <MenuItem value="">All</MenuItem>
                {list.map((o) => (
                  <MenuItem key={o.key} value={o.key}>{o.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
          ))}
        </Box>

        {error && (
          <Alert severity="error" sx={{ mt: 1.5 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        <Tabs value={subTab} onChange={(_, v: number) => setSubTab(v)} sx={{ mt: 1, mb: 1.5 }}>
          <Tab label="Routing" />
          <Tab label="Profiles" />
          <Tab label="Endpoints" />
          <Tab label="Prices & budget" />
        </Tabs>

        {!ctx && loading && (
          <Box display="flex" justifyContent="center" py={4}>
            <CircularProgress />
          </Box>
        )}

        {ctx && subTab === 0 && <RoutingTab ctx={ctx} canEditTeam={hasPermission('settings.models:edit')} />}
        {ctx && subTab === 1 && <ProfilesTab ctx={ctx} />}
        {ctx && subTab === 2 && <EndpointsTab ctx={ctx} />}
        {ctx && subTab === 3 && <PricesTab ctx={ctx} />}
      </CardContent>

      <Snackbar
        open={!!toast}
        autoHideDuration={TOAST_AUTO_HIDE_DURATION.success}
        onClose={() => setToast(null)}
        anchorOrigin={TOAST_POSITION.anchorOrigin}
        sx={TOAST_POSITION.sx}
      >
        <Alert severity="success" onClose={() => setToast(null)}>
          {toast}
        </Alert>
      </Snackbar>
    </Card>
  );
};

export default AiRoutingSettings;
