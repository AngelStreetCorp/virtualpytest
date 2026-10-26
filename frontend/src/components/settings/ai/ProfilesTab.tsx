/**
 * Settings → AI → Profiles: a model on an endpoint + parameters + optional fallback.
 * Super admin edits; the Test buttons record tools/vision/web capabilities on success.
 */

import {
  Add as AddIcon,
  Delete as DeleteIcon,
  Edit as EditIcon,
} from '@mui/icons-material';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  ButtonGroup,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
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
import React, { useState } from 'react';

import { useConfirmDialog } from '../../../hooks/useConfirmDialog';
import { ConfirmDialog } from '../../common/ConfirmDialog';
import SettingRow from '../../common/SettingRow';
import type { AiTabContext } from '../AiRoutingSettings';

import { aiApi, errorMessage, numOrNull, type ProfilePayload } from './api';
import type { AiProfile, ProfileTestResult, Thinking } from './types';
import { TYPOGRAPHY } from '../../../constants/typography';

interface ProfileForm {
  name: string;
  endpoint_id: string;
  model: string;
  temperature: string;
  max_tokens_cap: string;
  thinking: Thinking;
  image_max_edge: string;
  fallback_profile_id: string;
  extra: string;
  enabled: boolean;
}

const emptyForm = (endpointId: string): ProfileForm => ({
  name: '',
  endpoint_id: endpointId,
  model: '',
  temperature: '',
  max_tokens_cap: '',
  thinking: 'auto',
  image_max_edge: '',
  fallback_profile_id: '',
  extra: '{}',
  enabled: true,
});

const numText = (value: number | null): string => (value == null ? '' : String(value));

const formFrom = (p: AiProfile): ProfileForm => ({
  name: p.name,
  endpoint_id: p.endpoint_id,
  model: p.model,
  temperature: numText(p.temperature),
  max_tokens_cap: numText(p.max_tokens_cap),
  thinking: p.thinking,
  image_max_edge: numText(p.image_max_edge),
  fallback_profile_id: p.fallback_profile_id || '',
  extra: JSON.stringify(p.extra || {}, null, 2),
  enabled: p.enabled,
});

const parseExtra = (text: string): Record<string, unknown> | string => {
  if (!text.trim()) return {};
  try {
    const value: unknown = JSON.parse(text);
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return 'Extra must be a JSON object';
    return value as Record<string, unknown>;
  } catch (e) {
    return `Extra is not valid JSON: ${e instanceof Error ? e.message : String(e)}`;
  }
};

const TEST_KINDS: ProfileTestResult['kind'][] = ['text', 'vision', 'tools', 'web'];

export const ProfilesTab: React.FC<{ ctx: AiTabContext }> = ({ ctx }) => {
  const { config, reload, notify, fail } = ctx;
  const admin = config.is_platform_admin;
  const endpointById = new Map(config.endpoints.map((e) => [e.id, e]));
  const profileById = new Map(config.profiles.map((p) => [p.id, p]));
  const presetByName = new Map(config.presets.map((p) => [p.name, p]));
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  const [editing, setEditing] = useState<AiProfile | 'new' | null>(null);
  const [form, setForm] = useState<ProfileForm>(emptyForm(''));
  const [saving, setSaving] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, ProfileTestResult>>({});

  const set = <K extends keyof ProfileForm>(key: K, value: ProfileForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const formEndpoint = endpointById.get(form.endpoint_id);
  const listsModels = !!(formEndpoint && presetByName.get(formEndpoint.preset)?.lists_models);
  const modelOptions = models[form.endpoint_id] || [];

  const openNew = () => {
    setForm(emptyForm(config.endpoints[0]?.id || ''));
    setDialogError(null);
    setModelsError(null);
    setEditing('new');
  };
  const openEdit = (profile: AiProfile) => {
    setForm(formFrom(profile));
    setDialogError(null);
    setModelsError(null);
    setEditing(profile);
  };

  const loadModels = async () => {
    if (!form.endpoint_id) return;
    setLoadingModels(true);
    setModelsError(null);
    try {
      const result = await aiApi.testEndpoint(form.endpoint_id, {});
      if (result.models) setModels((prev) => ({ ...prev, [form.endpoint_id]: result.models || [] }));
      if (!result.success) setModelsError(result.error || 'Could not list models');
    } catch (err) {
      setModelsError(errorMessage(err, 'Could not list models'));
    } finally {
      setLoadingModels(false);
    }
  };

  const save = async () => {
    if (!form.name.trim() || !form.endpoint_id || !form.model.trim()) {
      setDialogError('Name, endpoint and model are required');
      return;
    }
    const extra = parseExtra(form.extra);
    if (typeof extra === 'string') {
      setDialogError(extra);
      return;
    }
    const temperature = numOrNull(form.temperature);
    if (temperature != null && (temperature < 0 || temperature > 2)) {
      setDialogError('Temperature must be between 0 and 2');
      return;
    }
    const imageMaxEdge = numOrNull(form.image_max_edge);
    if (imageMaxEdge != null && imageMaxEdge < 64) {
      setDialogError('Image max edge must be at least 64');
      return;
    }
    const payload: ProfilePayload = {
      name: form.name.trim(),
      endpoint_id: form.endpoint_id,
      model: form.model.trim(),
      temperature,
      max_tokens_cap: numOrNull(form.max_tokens_cap),
      thinking: form.thinking,
      image_max_edge: imageMaxEdge,
      fallback_profile_id: form.fallback_profile_id || null,
      extra,
      enabled: form.enabled,
    };
    setSaving(true);
    setDialogError(null);
    try {
      if (editing === 'new') await aiApi.createProfile(payload);
      else if (editing) await aiApi.updateProfile(editing.id, payload);
      setEditing(null);
      notify(`Profile ${payload.name} saved`);
      await reload();
    } catch (err) {
      setDialogError(errorMessage(err, 'Failed to save profile'));
    } finally {
      setSaving(false);
    }
  };

  const remove = (profile: AiProfile) =>
    confirm({
      title: 'Delete profile',
      message: `Delete profile "${profile.name}"? Routes still using it block the delete.`,
      confirmText: 'Delete',
      confirmColor: 'error',
      onConfirm: async () => {
        try {
          await aiApi.deleteProfile(profile.id);
          notify(`Profile ${profile.name} deleted`);
          await reload();
        } catch (err) {
          fail(errorMessage(err, 'Failed to delete profile'));
        }
      },
    });

  const test = async (profile: AiProfile, kind: ProfileTestResult['kind']) => {
    setTesting(`${profile.id}:${kind}`);
    try {
      const result = await aiApi.testProfile(profile.id, kind);
      setTestResults((prev) => ({ ...prev, [profile.id]: result }));
      if (result.success && kind !== 'text') await reload(); // capability recorded
    } catch (err) {
      setTestResults((prev) => ({
        ...prev,
        [profile.id]: { success: false, kind, error: errorMessage(err, 'Test failed') },
      }));
    } finally {
      setTesting(null);
    }
  };

  const editingId = editing && editing !== 'new' ? editing.id : null;

  return (
    <Box>
      <Box display="flex" alignItems="center" mb={1}>
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
          A profile is a model on an endpoint with its parameters. The Verified column lists what a passed Test (text / vision / tools / web buttons) has proven the model can do.
          {!admin && ' Only the platform super admin can change profiles.'}
        </Typography>
        {admin && (
          <Button
            size="small"
            variant="outlined"
            startIcon={<AddIcon />}
            onClick={openNew}
            disabled={config.endpoints.length === 0}
          >
            Add profile
          </Button>
        )}
      </Box>

      <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 860, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col style={{ width: 160 }} /><col style={{ width: 160 }} /><col /><col style={{ width: 130 }} /><col style={{ width: 100 }} /><col style={{ width: 130 }} />{admin && <col style={{ width: 110 }} />}</colgroup>
        <TableHead>
          <TableRow>
            <TableCell>Name</TableCell>
            <TableCell>Endpoint</TableCell>
            <TableCell>Model</TableCell>
            <TableCell>Params</TableCell>
            <TableCell>Verified</TableCell>
            <TableCell>Fallback</TableCell>
            {admin && <TableCell align="right">Actions</TableCell>}
          </TableRow>
        </TableHead>
        <TableBody>
          {config.profiles.length === 0 && (
            <TableRow>
              <TableCell colSpan={admin ? 7 : 6}>
                <Typography variant="body2" color="text.secondary">
                  No profiles yet.
                </Typography>
              </TableCell>
            </TableRow>
          )}
          {config.profiles.map((profile) => {
            const params = [
              profile.temperature != null ? `temp ${profile.temperature}` : null,
              profile.max_tokens_cap != null ? `max ${profile.max_tokens_cap} tok` : null,
              profile.thinking !== 'auto' ? `thinking ${profile.thinking}` : null,
              profile.image_max_edge != null ? `img ≤${profile.image_max_edge}px` : null,
              Object.keys(profile.extra || {}).length ? 'extra' : null,
            ].filter(Boolean);
            const result = testResults[profile.id];
            return (
              <React.Fragment key={profile.id}>
                <TableRow sx={{ opacity: profile.enabled ? 1 : 0.55 }}>
                  <TableCell>
                    <strong>{profile.name}</strong>
                    {!profile.enabled && <Chip size="small" label="disabled" sx={{ ml: 1 }} />}
                  </TableCell>
                  <TableCell>{endpointById.get(profile.endpoint_id)?.name || '—'}</TableCell>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size }}>{profile.model}</TableCell>
                  <TableCell>
                    <Typography variant="caption">{params.join(' · ') || 'defaults'}</Typography>
                  </TableCell>
                  <TableCell>
                    {profile.capabilities.length === 0 ? (
                      <Typography variant="caption" color="text.secondary">
                        undeclared
                      </Typography>
                    ) : (
                      profile.capabilities.map((c) => <Chip key={c} size="small" label={c} sx={{ mr: 0.5 }} />)
                    )}
                  </TableCell>
                  <TableCell>
                    {profile.fallback_profile_id ? profileById.get(profile.fallback_profile_id)?.name || '?' : '—'}
                  </TableCell>
                  {admin && (
                    <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                      <Typography component="span" variant="caption" color="text.secondary" sx={{ mr: 0.5 }}>
                        Test:
                      </Typography>
                      <ButtonGroup size="small" variant="outlined" sx={{ mr: 1 }}>
                        {TEST_KINDS.map((kind) => (
                          <Button
                            key={kind}
                            onClick={() => void test(profile, kind)}
                            disabled={testing !== null}
                          >
                            {testing === `${profile.id}:${kind}` ? <CircularProgress size={14} /> : kind}
                          </Button>
                        ))}
                      </ButtonGroup>
                      <Tooltip title="Edit">
                        <IconButton size="small" onClick={() => openEdit(profile)}>
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Delete">
                        <IconButton size="small" onClick={() => remove(profile)}>
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  )}
                </TableRow>
                {result && (
                  <TableRow>
                    <TableCell colSpan={7} sx={{ pt: 0 }}>
                      <Alert severity={result.success ? 'success' : 'error'} sx={{ mt: 1 }}>
                        <strong>{result.kind}</strong> test {result.success ? 'passed' : 'failed'}
                        {result.success && result.kind !== 'text' ? ` — "${result.kind}" capability recorded` : ''}
                        {result.reply && <Box sx={{ mt: 0.5 }}>Reply: {result.reply}</Box>}
                        {result.error && <Box sx={{ mt: 0.5 }}>{result.error}</Box>}
                      </Alert>
                    </TableCell>
                  </TableRow>
                )}
              </React.Fragment>
            );
          })}
        </TableBody>
      </Table>

      <Dialog open={editing !== null} onClose={() => !saving && setEditing(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{editing === 'new' ? 'Add profile' : 'Edit profile'}</DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 0 }}>
            <Grid item xs={12} sm={6}>
              <TextField
                label="Name"
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                fullWidth
                size="small"
                required
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                label="Endpoint"
                value={form.endpoint_id}
                onChange={(e) => set('endpoint_id', e.target.value)}
                select
                fullWidth
                size="small"
                required
              >
                {config.endpoints.map((e) => (
                  <MenuItem key={e.id} value={e.id}>
                    {e.name} ({presetByName.get(e.preset)?.label || e.preset})
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
            <Grid item xs={12}>
              <Box display="flex" gap={1} alignItems="flex-start">
                <Autocomplete
                  freeSolo
                  options={modelOptions}
                  value={form.model}
                  inputValue={form.model}
                  onInputChange={(_, value) => set('model', value)}
                  onChange={(_, value) => set('model', value || '')}
                  sx={{ flex: 1 }}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      label="Model"
                      size="small"
                      required
                      helperText={
                        modelOptions.length
                          ? `${modelOptions.length} models from the endpoint`
                          : listsModels
                            ? 'Free text, or load the endpoint model list'
                            : 'Model id as the provider expects it'
                      }
                    />
                  )}
                />
                {listsModels && (
                  <Button
                    size="small"
                    onClick={() => void loadModels()}
                    disabled={loadingModels}
                    startIcon={loadingModels ? <CircularProgress size={14} /> : undefined}
                    sx={{ mt: 0.5, whiteSpace: 'nowrap' }}
                  >
                    Load models
                  </Button>
                )}
              </Box>
              {modelsError && (
                <Alert severity="warning" sx={{ mt: 1 }}>
                  {modelsError}
                </Alert>
              )}
            </Grid>
            <Grid item xs={6} sm={4}>
              <TextField
                label="Temperature"
                type="number"
                value={form.temperature}
                onChange={(e) => set('temperature', e.target.value)}
                placeholder="caller default"
                inputProps={{ min: 0, max: 2, step: 0.1 }}
                fullWidth
                size="small"
              />
            </Grid>
            <Grid item xs={6} sm={4}>
              <TextField
                label="Max tokens cap"
                type="number"
                value={form.max_tokens_cap}
                onChange={(e) => set('max_tokens_cap', e.target.value)}
                placeholder="none"
                inputProps={{ min: 1 }}
                fullWidth
                size="small"
              />
            </Grid>
            <Grid item xs={6} sm={4}>
              <TextField
                label="Thinking"
                value={form.thinking}
                onChange={(e) => set('thinking', e.target.value as Thinking)}
                select
                fullWidth
                size="small"
              >
                <MenuItem value="auto">auto</MenuItem>
                <MenuItem value="on">on</MenuItem>
                <MenuItem value="off">off</MenuItem>
              </TextField>
            </Grid>
            <Grid item xs={6} sm={4}>
              <TextField
                label="Image max edge (px)"
                type="number"
                value={form.image_max_edge}
                onChange={(e) => set('image_max_edge', e.target.value)}
                placeholder="no resize"
                inputProps={{ min: 64 }}
                fullWidth
                size="small"
              />
            </Grid>
            <Grid item xs={12} sm={8}>
              <TextField
                label="Fallback profile"
                value={form.fallback_profile_id}
                onChange={(e) => set('fallback_profile_id', e.target.value)}
                select
                fullWidth
                size="small"
                SelectProps={{ displayEmpty: true }}
                InputLabelProps={{ shrink: true }}
              >
                <MenuItem value="">
                  <em>None</em>
                </MenuItem>
                {config.profiles
                  .filter((p) => p.id !== editingId)
                  .map((p) => (
                    <MenuItem key={p.id} value={p.id}>
                      {p.name} — {p.model}
                    </MenuItem>
                  ))}
              </TextField>
            </Grid>
            <Grid item xs={12}>
              <TextField
                label="Extra (JSON object, sent in the request body)"
                value={form.extra}
                onChange={(e) => set('extra', e.target.value)}
                error={typeof parseExtra(form.extra) === 'string'}
                helperText={typeof parseExtra(form.extra) === 'string' ? (parseExtra(form.extra) as string) : ' '}
                multiline
                minRows={3}
                fullWidth
                size="small"
                InputProps={{ sx: { fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size } }}
              />
            </Grid>
            <Grid item xs={12}>
<SettingRow title="Enabled" checked={form.enabled} onChange={(on) => set('enabled', on)} />
            </Grid>
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
