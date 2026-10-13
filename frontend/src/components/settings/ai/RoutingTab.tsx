/**
 * Settings → AI → Routing: usage tree with the effective profile per usage.
 * Team overrides need settings.models:edit; server-default routes need the platform super admin.
 */

import {
  Add as AddIcon,
  Delete as DeleteIcon,
  Edit as EditIcon,
} from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Grid,
  IconButton,
  MenuItem,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import React, { useMemo, useState } from 'react';

import { useConfirmDialog } from '../../../hooks/useConfirmDialog';
import { ConfirmDialog } from '../../common/ConfirmDialog';
import type { AiTabContext } from '../AiRoutingSettings';

import { TEAM_ID, aiApi, errorMessage, numOrNull, strOrNull, type RoutePayload } from './api';
import { isResolutionError, type AiProfile, type AiRoute, type AiUsage } from './types';

const ROOT_KEYS = new Set(['agent', 'vision', 'text']);

const isProtectedRoot = (route: AiRoute): boolean =>
  route.team_id === null &&
  ROOT_KEYS.has(route.usage_key) &&
  !route.host_name &&
  !route.device_model &&
  !route.userinterface_name;

interface TreeRow {
  usage: AiUsage;
  depth: number;
}

/** Depth-first order by `parent` (not key prefix: public.ask → agent, analyzer.sherlock → text). */
const buildTree = (usages: AiUsage[]): TreeRow[] => {
  const keys = new Set(usages.map((u) => u.key));
  const children = new Map<string, AiUsage[]>();
  const roots: AiUsage[] = [];
  for (const u of usages) {
    if (u.parent && keys.has(u.parent)) {
      const list = children.get(u.parent) || [];
      list.push(u);
      children.set(u.parent, list);
    } else {
      roots.push(u);
    }
  }
  const rows: TreeRow[] = [];
  const walk = (u: AiUsage, depth: number) => {
    rows.push({ usage: u, depth });
    for (const child of children.get(u.key) || []) walk(child, depth + 1);
  };
  roots.forEach((r) => walk(r, 0));
  return rows;
};

interface RouteForm {
  profile_id: string;
  host_name: string;
  device_model: string;
  userinterface_name: string;
  split_profile_id: string;
  split_percent: string;
  priority: string;
  enabled: boolean;
}

interface Editing {
  usage: AiUsage;
  teamId: string | null;
  route: AiRoute | null;
}

const formFrom = (route: AiRoute | null): RouteForm => ({
  profile_id: route?.profile_id || '',
  host_name: route?.host_name || '',
  device_model: route?.device_model || '',
  userinterface_name: route?.userinterface_name || '',
  split_profile_id: route?.split_profile_id || '',
  split_percent: route?.split_percent == null ? '' : String(route.split_percent),
  priority: String(route?.priority ?? 100),
  enabled: route?.enabled ?? true,
});

const scopeLabel = (route: AiRoute): string =>
  [
    route.host_name && `host=${route.host_name}`,
    route.device_model && `model=${route.device_model}`,
    route.userinterface_name && `ui=${route.userinterface_name}`,
  ]
    .filter(Boolean)
    .join(', ');

export const RoutingTab: React.FC<{ ctx: AiTabContext; canEditTeam: boolean }> = ({ ctx, canEditTeam }) => {
  const { config, stats, reload, notify, fail } = ctx;
  const admin = config.is_platform_admin;
  const rows = useMemo(() => buildTree(config.usages), [config.usages]);
  const profileById = new Map(config.profiles.map((p) => [p.id, p]));
  const endpointById = new Map(config.endpoints.map((e) => [e.id, e]));
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  const [editing, setEditing] = useState<Editing | null>(null);
  const [form, setForm] = useState<RouteForm>(formFrom(null));
  const [saving, setSaving] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);

  const set = <K extends keyof RouteForm>(key: K, value: RouteForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const canEditLayer = (teamId: string | null) => (teamId ? canEditTeam : admin);

  /** Profiles a usage may route to: enabled, capabilities cover `needs` (or none declared), endpoint usable. */
  const compatibleProfiles = (usage: AiUsage, teamId: string | null): AiProfile[] =>
    config.profiles.filter((p) => {
      if (!p.enabled) return false;
      const endpoint = endpointById.get(p.endpoint_id);
      if (!endpoint) return false;
      if (teamId && endpoint.allowed_team_ids?.length && !endpoint.allowed_team_ids.includes(teamId)) return false;
      return p.capabilities.length === 0 || usage.needs.every((n) => p.capabilities.includes(n));
    });

  const openRoute = (usage: AiUsage, teamId: string | null, route: AiRoute | null) => {
    setForm(formFrom(route));
    setDialogError(null);
    setEditing({ usage, teamId, route });
  };

  const save = async () => {
    if (!editing) return;
    if (!form.profile_id) {
      setDialogError('Pick a profile');
      return;
    }
    const splitPercent = form.split_profile_id ? numOrNull(form.split_percent) : null;
    if (!!form.split_profile_id !== (splitPercent != null)) {
      setDialogError('A split needs both a profile and a percent');
      return;
    }
    if (splitPercent != null && (splitPercent < 1 || splitPercent > 99 || !Number.isInteger(splitPercent))) {
      setDialogError('Split percent must be a whole number between 1 and 99');
      return;
    }
    const priority = Number(form.priority);
    if (!Number.isInteger(priority)) {
      setDialogError('Priority must be a whole number');
      return;
    }
    const root = editing.route ? isProtectedRoot(editing.route) : false;
    const payload: RoutePayload = {
      usage_key: editing.usage.key,
      profile_id: form.profile_id,
      split_profile_id: form.split_profile_id || null,
      split_percent: splitPercent,
      priority,
    };
    if (!root) {
      payload.host_name = strOrNull(form.host_name);
      payload.device_model = strOrNull(form.device_model);
      payload.userinterface_name = strOrNull(form.userinterface_name);
      payload.enabled = form.enabled;
    }
    setSaving(true);
    setDialogError(null);
    try {
      if (editing.route) await aiApi.updateRoute(editing.route.id, editing.teamId, payload);
      else await aiApi.createRoute({ ...payload, team_id: editing.teamId });
      setEditing(null);
      notify(`Route for ${editing.usage.key} saved`);
      await reload();
    } catch (err) {
      setDialogError(errorMessage(err, 'Failed to save route'));
    } finally {
      setSaving(false);
    }
  };

  const remove = (route: AiRoute) =>
    confirm({
      title: 'Remove route',
      message: `Remove the ${route.team_id ? 'team override' : 'server-default route'} for "${route.usage_key}"${
        scopeLabel(route) ? ` (${scopeLabel(route)})` : ''
      }? The usage then inherits from its parent.`,
      confirmText: 'Remove',
      confirmColor: 'error',
      onConfirm: async () => {
        try {
          await aiApi.deleteRoute(route.id, route.team_id);
          notify(`Route for ${route.usage_key} removed`);
          await reload();
        } catch (err) {
          fail(errorMessage(err, 'Failed to remove route'));
        }
      },
    });

  const profileName = (id: string | null) => (id ? profileById.get(id)?.name || '?' : '');

  const renderEffective = (usage: AiUsage) => {
    const eff = config.effective[usage.key];
    if (!eff) return <Typography variant="caption" color="text.secondary">—</Typography>;
    if (isResolutionError(eff)) {
      return (
        <Typography variant="caption" color="error">
          {eff.error}
        </Typography>
      );
    }
    const [primary, ...fallbacks] = eff.chain;
    const chip =
      eff.via !== usage.key ? (
        <Chip size="small" variant="outlined" label={`inherited from ${eff.via}`} />
      ) : eff.layer === 'team' ? (
        <Chip size="small" color="primary" label="team override" />
      ) : (
        <Chip size="small" color="default" label="server default" />
      );
    return (
      <Box>
        {primary && (
          <Typography variant="body2">
            <strong>{primary.profile}</strong>{' '}
            <Typography component="span" variant="caption" sx={{ fontFamily: 'monospace' }}>
              {primary.model}
            </Typography>{' '}
            <Typography component="span" variant="caption" color="text.secondary">
              @ {primary.endpoint}
              {primary.reach === 'host' ? ' (host reach)' : ''}
            </Typography>
          </Typography>
        )}
        <Box display="flex" gap={0.5} flexWrap="wrap" mt={0.25}>
          {chip}
          {eff.split_arm && <Chip size="small" variant="outlined" label={`split arm: ${eff.split_arm}`} />}
        </Box>
        {fallbacks.length > 0 && (
          <Typography variant="caption" color="text.secondary" display="block">
            fallback: {fallbacks.map((h) => `${h.profile} (${h.model})`).join(' → ')}
          </Typography>
        )}
      </Box>
    );
  };

  const renderStats = (key: string) => {
    const s = stats[key];
    if (!s || !s.calls) {
      return (
        <Typography variant="caption" color="text.secondary">
          no calls
        </Typography>
      );
    }
    const profiles = Object.entries(s.profiles)
      .map(([name, calls]) => `${name}: ${calls}`)
      .join(', ');
    return (
      <Tooltip title={`${s.fallbacks} fallback(s) · ${s.tokens_in} tokens in / ${s.tokens_out} out · ${profiles}`}>
        <Box>
          <Typography variant="caption" display="block">
            {s.calls} calls
          </Typography>
          <Typography variant="caption" display="block" color={s.error_rate > 0.05 ? 'error' : 'text.secondary'}>
            {(s.error_rate * 100).toFixed(1)}% errors · {s.avg_ms} ms
          </Typography>
        </Box>
      </Tooltip>
    );
  };

  const renderRoutes = (usage: AiUsage) => {
    const routes = config.routes.filter((r) => r.usage_key === usage.key);
    if (routes.length === 0) return null;
    return (
      <Box display="flex" flexDirection="column" gap={0.25} mt={0.5}>
        {routes.map((route) => {
          const editable = canEditLayer(route.team_id);
          const scope = scopeLabel(route);
          return (
            <Box key={route.id} display="flex" alignItems="center" gap={0.5} sx={{ opacity: route.enabled ? 1 : 0.55 }}>
              <Chip
                size="small"
                variant="outlined"
                color={route.team_id ? 'primary' : 'default'}
                label={route.team_id ? 'team' : 'default'}
                sx={{ height: 18, fontSize: 10 }}
              />
              <Typography variant="caption">
                {profileName(route.profile_id)}
                {route.split_profile_id ? ` / ${route.split_percent}% → ${profileName(route.split_profile_id)}` : ''}
                {scope ? ` [${scope}]` : ''}
                {route.priority !== 100 ? ` · prio ${route.priority}` : ''}
                {!route.enabled ? ' · disabled' : ''}
              </Typography>
              {editable && (
                <>
                  <IconButton size="small" onClick={() => openRoute(usage, route.team_id, route)} sx={{ p: 0.25 }}>
                    <EditIcon sx={{ fontSize: 14 }} />
                  </IconButton>
                  {!isProtectedRoot(route) && (
                    <IconButton size="small" onClick={() => remove(route)} sx={{ p: 0.25 }}>
                      <DeleteIcon sx={{ fontSize: 14 }} />
                    </IconButton>
                  )}
                </>
              )}
            </Box>
          );
        })}
      </Box>
    );
  };

  const editingRoot = editing?.route ? isProtectedRoot(editing.route) : false;
  const dialogProfiles = editing ? compatibleProfiles(editing.usage, editing.teamId) : [];
  // Keep the route's current profiles selectable even if no longer "compatible" (e.g. disabled).
  for (const id of [editing?.route?.profile_id, editing?.route?.split_profile_id]) {
    const current = id ? profileById.get(id) : undefined;
    if (current && !dialogProfiles.includes(current)) dialogProfiles.push(current);
  }

  return (
    <Box>

      <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 560, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col style={{ width: 200 }} /><col /><col style={{ width: 100 }} />{(canEditTeam || admin) && <col style={{ width: 90 }} />}</colgroup>
        <TableHead>
          <TableRow>
            <TableCell>Usage</TableCell>
            <TableCell>Effective model</TableCell>
            <TableCell>Last 24h</TableCell>
            {(canEditTeam || admin) && <TableCell align="right">Add</TableCell>}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map(({ usage, depth }) => {
            const hasTeamRoute = config.routes.some(
              (r) => r.usage_key === usage.key && r.team_id && !scopeLabel(r),
            );
            return (
              <TableRow key={usage.key} sx={{ verticalAlign: 'top' }}>
                <TableCell sx={{ pl: 1 + depth * 3 }}>
                  <Tooltip title={usage.description}>
                    <Typography variant="body2" fontWeight={depth === 0 ? 600 : 400}>
                      {usage.label}
                    </Typography>
                  </Tooltip>
                  <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                    {usage.key}
                  </Typography>
                  {usage.needs.length > 0 && depth === 0 && (
                    <Typography variant="caption" color="text.secondary">
                      {' '}
                      · needs {usage.needs.join(', ')}
                    </Typography>
                  )}
                  {renderRoutes(usage)}
                </TableCell>
                <TableCell>{renderEffective(usage)}</TableCell>
                <TableCell>{renderStats(usage.key)}</TableCell>
                {(canEditTeam || admin) && (
                  <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                    {canEditTeam && (
                      <Tooltip title={hasTeamRoute ? 'Add a scoped team override' : 'Override for this team'}>
                        <Button size="small" startIcon={<AddIcon />} onClick={() => openRoute(usage, ctx.scope.team || TEAM_ID, null)}>
                          Team
                        </Button>
                      </Tooltip>
                    )}
                    {admin && (
                      <Tooltip title="Add a server-default route">
                        <Button size="small" startIcon={<AddIcon />} onClick={() => openRoute(usage, null, null)}>
                          Default
                        </Button>
                      </Tooltip>
                    )}
                  </TableCell>
                )}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      <Dialog open={editing !== null} onClose={() => !saving && setEditing(null)} maxWidth="sm" fullWidth>
        <DialogTitle>
          {editing?.route ? 'Edit' : 'Add'} {editing?.teamId ? 'team override' : 'server-default route'} —{' '}
          <Box component="span" sx={{ fontFamily: 'monospace' }}>
            {editing?.usage.key}
          </Box>
        </DialogTitle>
        <DialogContent>
          {editingRoot && (
            <Alert severity="info" sx={{ mb: 1 }}>
              Root server-default route: it can only be repointed (no scope, always enabled, never deleted).
            </Alert>
          )}
          <Grid container spacing={2} sx={{ mt: 0 }}>
            <Grid item xs={12}>
              <TextField
                label="Profile"
                value={form.profile_id}
                onChange={(e) => set('profile_id', e.target.value)}
                select
                fullWidth
                size="small"
                required
                helperText={
                  editing?.usage.needs.length
                    ? `Needs ${editing.usage.needs.join(', ')} — profiles with other declared capabilities are hidden`
                    : ' '
                }
              >
                {dialogProfiles.length === 0 && (
                  <MenuItem value="" disabled>
                    No compatible profile
                  </MenuItem>
                )}
                {dialogProfiles.map((p) => (
                  <MenuItem key={p.id} value={p.id}>
                    {p.name} — {p.model} @ {endpointById.get(p.endpoint_id)?.name}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
            {!editingRoot && (
              <>
                <Grid item xs={12}>
                  <Typography variant="caption" color="text.secondary">
                    Optional scope — leave empty to apply everywhere
                  </Typography>
                </Grid>
                <Grid item xs={12} sm={4}>
                  <TextField
                    label="Host name"
                    value={form.host_name}
                    onChange={(e) => set('host_name', e.target.value)}
                    fullWidth
                    size="small"
                  />
                </Grid>
                <Grid item xs={12} sm={4}>
                  <TextField
                    label="Device model"
                    value={form.device_model}
                    onChange={(e) => set('device_model', e.target.value)}
                    fullWidth
                    size="small"
                  />
                </Grid>
                <Grid item xs={12} sm={4}>
                  <TextField
                    label="User interface"
                    value={form.userinterface_name}
                    onChange={(e) => set('userinterface_name', e.target.value)}
                    fullWidth
                    size="small"
                  />
                </Grid>
              </>
            )}
            <Grid item xs={12} sm={8}>
              <TextField
                label="Split profile (A/B)"
                value={form.split_profile_id}
                onChange={(e) => set('split_profile_id', e.target.value)}
                select
                fullWidth
                size="small"
                SelectProps={{ displayEmpty: true }}
                InputLabelProps={{ shrink: true }}
              >
                <MenuItem value="">
                  <em>No split</em>
                </MenuItem>
                {dialogProfiles
                  .filter((p) => p.id !== form.profile_id)
                  .map((p) => (
                    <MenuItem key={p.id} value={p.id}>
                      {p.name} — {p.model}
                    </MenuItem>
                  ))}
              </TextField>
            </Grid>
            <Grid item xs={12} sm={4}>
              <TextField
                label="Split %"
                type="number"
                value={form.split_percent}
                onChange={(e) => set('split_percent', e.target.value)}
                disabled={!form.split_profile_id}
                helperText="share sent to the split profile"
                inputProps={{ min: 1, max: 99 }}
                fullWidth
                size="small"
              />
            </Grid>
            <Grid item xs={6} sm={4}>
              <TextField
                label="Priority"
                type="number"
                value={form.priority}
                onChange={(e) => set('priority', e.target.value)}
                fullWidth
                size="small"
              />
            </Grid>
            {!editingRoot && (
              <Grid item xs={6} sm={8}>
                <FormControlLabel
                  control={<Checkbox checked={form.enabled} onChange={(e) => set('enabled', e.target.checked)} />}
                  label="Enabled"
                />
              </Grid>
            )}
          </Grid>
          {dialogError && (
            <Alert severity="error" sx={{ mt: 1 }}>
              {dialogError}
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditing(null)} disabled={saving}>
            Cancel
          </Button>
          <Button variant="contained" onClick={() => void save()} disabled={saving}>
            {saving ? <CircularProgress size={18} /> : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={dialogState.open}
        title={dialogState.title}
        message={dialogState.message}
        confirmText={dialogState.confirmText}
        cancelText={dialogState.cancelText}
        confirmColor={dialogState.confirmColor}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </Box>
  );
};
