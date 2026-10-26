/**
 * Settings → AI → Endpoints: where AI requests go. Super admin edits; API keys are
 * write-only (the UI only ever sees has_secret).
 */

import {
  Add as AddIcon,
  Delete as DeleteIcon,
  Edit as EditIcon,
  NetworkCheck as TestIcon,
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
  Link,
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

import { PRESET_INFO } from './presetInfo';
import { aiApi, errorMessage, numOrNull, strOrNull, type EndpointPayload } from './api';
import type { AiEndpoint, EndpointTestResult, Reach } from './types';

const NAME_RE = /^[a-z0-9][a-z0-9_-]{0,62}$/;

interface EndpointForm {
  name: string;
  preset: string;
  base_url: string;
  reach: Reach;
  timeout_s: string;
  max_concurrency: string;
  region: string;
  enabled: boolean;
  api_key: string;
  clear_api_key: boolean;
}

const emptyForm = (preset: string): EndpointForm => ({
  name: '',
  preset,
  base_url: '',
  reach: 'server',
  timeout_s: '120',
  max_concurrency: '',
  region: '',
  enabled: true,
  api_key: '',
  clear_api_key: false,
});

const formFrom = (e: AiEndpoint): EndpointForm => ({
  name: e.name,
  preset: e.preset,
  base_url: e.base_url || '',
  reach: e.reach,
  timeout_s: String(e.timeout_s),
  max_concurrency: e.max_concurrency == null ? '' : String(e.max_concurrency),
  region: e.region || '',
  enabled: e.enabled,
  api_key: '',
  clear_api_key: false,
});

export const TestResultAlert: React.FC<{ result: EndpointTestResult }> = ({ result }) => (
  <Alert severity={result.success ? 'success' : 'error'} sx={{ mt: 1 }}>
    {result.success ? 'Connection OK.' : result.error || 'Test failed.'}
    {result.note && <Box sx={{ mt: 0.5 }}>{result.note}</Box>}
    {result.reply && <Box sx={{ mt: 0.5 }}>Reply: {result.reply}</Box>}
    {result.models && (
      <Box sx={{ mt: 0.5 }}>
        {result.models.length} model(s): {result.models.slice(0, 30).join(', ')}
        {result.models.length > 30 ? '…' : ''}
      </Box>
    )}
  </Alert>
);

export const EndpointsTab: React.FC<{ ctx: AiTabContext }> = ({ ctx }) => {
  const { config, reload, notify, fail } = ctx;
  const admin = config.is_platform_admin;
  const presetByName = new Map(config.presets.map((p) => [p.name, p]));
  // Read-only fallback order: each profile chain, e.g. "fast → backup". Edited in Routing / Profiles.
  const profileById = new Map(config.profiles.map((p) => [p.id, p]));
  const fallbackTargets = new Set(config.profiles.map((p) => p.fallback_profile_id).filter(Boolean));
  const fallbackOrder = config.profiles
    .filter((p) => p.fallback_profile_id && !fallbackTargets.has(p.id))
    .map((p) => {
      const names = [p.name];
      const seen = new Set([p.id]);
      let next = p.fallback_profile_id ? profileById.get(p.fallback_profile_id) : undefined;
      while (next && !seen.has(next.id)) {
        names.push(next.name);
        seen.add(next.id);
        next = next.fallback_profile_id ? profileById.get(next.fallback_profile_id) : undefined;
      }
      return names.join(' → ');
    })
    .join(' · ');
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  const [editing, setEditing] = useState<AiEndpoint | 'new' | null>(null);
  const [form, setForm] = useState<EndpointForm>(emptyForm(config.presets[0]?.name || 'anthropic'));
  const [saving, setSaving] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, EndpointTestResult>>({});

  const preset = presetByName.get(form.preset);
  const set = <K extends keyof EndpointForm>(key: K, value: EndpointForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const openNew = () => {
    setForm(emptyForm(config.presets[0]?.name || 'anthropic'));
    setDialogError(null);
    setEditing('new');
  };
  const openEdit = (endpoint: AiEndpoint) => {
    setForm(formFrom(endpoint));
    setDialogError(null);
    setEditing(endpoint);
  };

  const validate = (): string | null => {
    if (!NAME_RE.test(form.name)) return 'Name: lowercase letters, digits, - and _ (must start with a letter or digit)';
    if (preset?.base_url_required && !form.base_url.trim()) return 'Base URL is required for this preset';
    const timeout = Number(form.timeout_s);
    if (!Number.isInteger(timeout) || timeout < 5 || timeout > 1800) return 'Timeout must be 5–1800 seconds';
    if (form.max_concurrency.trim() && !(Number(form.max_concurrency) > 0)) return 'Max concurrency must be > 0';
    return null;
  };

  const save = async () => {
    const invalid = validate();
    if (invalid) {
      setDialogError(invalid);
      return;
    }
    const payload: EndpointPayload = {
      name: form.name,
      preset: form.preset,
      base_url: strOrNull(form.base_url),
      reach: form.reach,
      timeout_s: Number(form.timeout_s),
      max_concurrency: numOrNull(form.max_concurrency),
      region: strOrNull(form.region),
      enabled: form.enabled,
    };
    if (form.reach === 'server' && form.api_key.trim()) payload.api_key = form.api_key.trim();
    if (form.clear_api_key) payload.clear_api_key = true;
    setSaving(true);
    setDialogError(null);
    try {
      if (editing === 'new') await aiApi.createEndpoint(payload);
      else if (editing) await aiApi.updateEndpoint(editing.id, payload);
      setEditing(null);
      notify(`Endpoint ${form.name} saved`);
      await reload();
    } catch (err) {
      setDialogError(errorMessage(err, 'Failed to save endpoint'));
    } finally {
      setSaving(false);
    }
  };

  const remove = (endpoint: AiEndpoint) =>
    confirm({
      title: 'Delete endpoint',
      message: `Delete endpoint "${endpoint.name}" and its stored API key? Profiles still using it block the delete.`,
      confirmText: 'Delete',
      confirmColor: 'error',
      onConfirm: async () => {
        try {
          await aiApi.deleteEndpoint(endpoint.id);
          notify(`Endpoint ${endpoint.name} deleted`);
          await reload();
        } catch (err) {
          fail(errorMessage(err, 'Failed to delete endpoint'));
        }
      },
    });

  const test = async (endpoint: AiEndpoint, apiKey?: string) => {
    setTesting(endpoint.id);
    try {
      const result = await aiApi.testEndpoint(endpoint.id, apiKey ? { api_key: apiKey } : {});
      setTestResults((prev) => ({ ...prev, [endpoint.id]: result }));
    } catch (err) {
      setTestResults((prev) => ({
        ...prev,
        [endpoint.id]: { success: false, error: errorMessage(err, 'Test failed') },
      }));
    } finally {
      setTesting(null);
    }
  };

  const editingEndpoint = editing && editing !== 'new' ? editing : null;

  return (
    <Box>
      <Alert severity="info" sx={{ mb: 1.5 }}>
        Keys are stored on the server and never sent back to the browser.
      </Alert>
      <Box display="flex" alignItems="center" mb={1}>
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
          Endpoints are where requests go (a provider API or a local OpenAI-compatible server).
          {!admin && ' Only the platform super admin can change them.'}
        </Typography>
        {admin && (
          <Button size="small" variant="outlined" startIcon={<AddIcon />} onClick={openNew}>
            Add endpoint
          </Button>
        )}
      </Box>

      <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 1100, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col style={{ width: 130 }} /><col style={{ width: 230 }} /><col style={{ width: 220 }} /><col style={{ width: 80 }} /><col style={{ width: 110 }} /><col style={{ width: 80 }} /><col style={{ width: 90 }} />{admin && <col style={{ width: 110 }} />}</colgroup>
        <TableHead>
          <TableRow>
            <TableCell>Name</TableCell>
            <TableCell>Preset</TableCell>
            <TableCell>Base URL</TableCell>
            <TableCell>Reach</TableCell>
            <TableCell>Key</TableCell>
            <TableCell>Timeout</TableCell>
            <TableCell>Status</TableCell>
            {admin && <TableCell align="right">Actions</TableCell>}
          </TableRow>
        </TableHead>
        <TableBody>
          {config.endpoints.length === 0 && (
            <TableRow>
              <TableCell colSpan={admin ? 8 : 7}>
                <Typography variant="body2" color="text.secondary">
                  No endpoints yet.
                </Typography>
              </TableCell>
            </TableRow>
          )}
          {config.endpoints.map((endpoint) => (
            <React.Fragment key={endpoint.id}>
              <TableRow>
                <TableCell>
                  <strong>{endpoint.name}</strong>
                </TableCell>
                <TableCell>
                  {presetByName.get(endpoint.preset)?.label || endpoint.preset}
                  {PRESET_INFO[endpoint.preset] && (
                    <Typography variant="caption" color="text.secondary" display="block">
                      {PRESET_INFO[endpoint.preset].description}
                    </Typography>
                  )}
                </TableCell>
                <TableCell sx={{ maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {endpoint.base_url || presetByName.get(endpoint.preset)?.base_url || '—'}
                </TableCell>
                <TableCell>{endpoint.reach}</TableCell>
                <TableCell>
                  {endpoint.has_secret ? (
                    <Chip size="small" color="success" label="key saved" />
                  ) : endpoint.needs_key ? (
                    <>
                      <Chip size="small" color="warning" label="no key" />
                      {PRESET_INFO[endpoint.preset]?.keyUrl && (
                        <Link
                          href={PRESET_INFO[endpoint.preset].keyUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          variant="caption"
                          display="block"
                        >
                          Get a key ↗
                        </Link>
                      )}
                    </>
                  ) : (
                    <Chip size="small" variant="outlined" label="keyless" />
                  )}
                </TableCell>
                <TableCell>{endpoint.timeout_s}s</TableCell>
                <TableCell>
                  {!endpoint.enabled ? (
                    <Chip size="small" label="disabled" />
                  ) : endpoint.down_for_s > 0 ? (
                    <Tooltip title={`Unreachable on the last call — its fallback serves instead; retried in ${endpoint.down_for_s}s`}>
                      <Chip size="small" color="error" label={`down · retry ${endpoint.down_for_s}s`} />
                    </Tooltip>
                  ) : (
                    'enabled'
                  )}
                </TableCell>
                {admin && (
                  <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                    <Tooltip title="Test connection">
                      <span>
                        <IconButton size="small" onClick={() => void test(endpoint)} disabled={testing === endpoint.id}>
                          {testing === endpoint.id ? <CircularProgress size={16} /> : <TestIcon fontSize="small" />}
                        </IconButton>
                      </span>
                    </Tooltip>
                    <Tooltip title="Edit">
                      <IconButton size="small" onClick={() => openEdit(endpoint)}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Delete">
                      <IconButton size="small" onClick={() => remove(endpoint)}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                )}
              </TableRow>
              {testResults[endpoint.id] && (
                <TableRow>
                  <TableCell colSpan={8} sx={{ pt: 0 }}>
                    <TestResultAlert result={testResults[endpoint.id]} />
                  </TableCell>
                </TableRow>
              )}
            </React.Fragment>
          ))}
        </TableBody>
      </Table>

      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1.5 }}>
        Fallback order: {fallbackOrder || 'no profile has a fallback'}.{' '}
        <Link component="button" type="button" variant="caption" onClick={() => ctx.goToSub(0)} sx={{ verticalAlign: 'baseline' }}>
          Edit in Routing
        </Link>
      </Typography>

      <Dialog open={editing !== null} onClose={() => !saving && setEditing(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{editing === 'new' ? 'Add endpoint' : `Edit endpoint ${editingEndpoint?.name ?? ''}`}</DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 0 }}>
            <Grid item xs={12} sm={6}>
              <TextField
                label="Name"
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                helperText="lowercase, digits, - and _"
                fullWidth
                size="small"
                required
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                label="Preset"
                value={form.preset}
                onChange={(e) => set('preset', e.target.value)}
                select
                fullWidth
                size="small"
              >
                {config.presets.map((p) => (
                  <MenuItem key={p.name} value={p.name}>
                    {p.label}
                  </MenuItem>
                ))}
              </TextField>
              {PRESET_INFO[form.preset] && (
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                  {PRESET_INFO[form.preset].description}
                  {PRESET_INFO[form.preset].keyUrl && (
                    <>
                      {' '}
                      <Link href={PRESET_INFO[form.preset].keyUrl} target="_blank" rel="noopener noreferrer">
                        Get a key ↗
                      </Link>
                    </>
                  )}
                </Typography>
              )}
            </Grid>
            <Grid item xs={12}>
              <TextField
                label="Base URL"
                value={form.base_url}
                onChange={(e) => set('base_url', e.target.value)}
                placeholder={preset?.base_url || 'http://192.168.1.20:1234/v1'}
                helperText={
                  preset?.base_url_required
                    ? 'Required — e.g. LM Studio http://192.168.1.20:1234/v1, Ollama http://host:11434/v1'
                    : `Leave empty for the preset default${preset?.base_url ? ` (${preset.base_url})` : ''}`
                }
                required={preset?.base_url_required}
                fullWidth
                size="small"
              />
            </Grid>
            <Grid item xs={12} sm={4}>
              <TextField
                label="Reach"
                value={form.reach}
                onChange={(e) => set('reach', e.target.value as Reach)}
                select
                fullWidth
                size="small"
                helperText="host = keyless LAN server only hosts can reach"
              >
                <MenuItem value="server">server</MenuItem>
                <MenuItem value="host">host</MenuItem>
              </TextField>
            </Grid>
            <Grid item xs={6} sm={4}>
              <TextField
                label="Timeout (s)"
                type="number"
                value={form.timeout_s}
                onChange={(e) => set('timeout_s', e.target.value)}
                inputProps={{ min: 5, max: 1800 }}
                fullWidth
                size="small"
              />
            </Grid>
            <Grid item xs={6} sm={4}>
              <TextField
                label="Max concurrency"
                type="number"
                value={form.max_concurrency}
                onChange={(e) => set('max_concurrency', e.target.value)}
                placeholder="unlimited"
                inputProps={{ min: 1 }}
                fullWidth
                size="small"
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                label="Region"
                value={form.region}
                onChange={(e) => set('region', e.target.value)}
                placeholder="EU, US, local…"
                helperText="Where this provider hosts the data. Shown on Monitoring → AI usage."
                inputProps={{ maxLength: 40 }}
                fullWidth
                size="small"
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                label="API key"
                type="password"
                autoComplete="new-password"
                value={form.api_key}
                onChange={(e) => set('api_key', e.target.value)}
                disabled={form.reach === 'host' || form.clear_api_key}
                placeholder={
                  editingEndpoint?.has_secret ? 'key saved — type to replace' : preset?.needs_key ? 'no key' : 'optional'
                }
                helperText={
                  form.reach === 'host'
                    ? 'Host-reach endpoints are keyless (hosts never hold API keys).'
                    : 'Write-only: a stored key is never shown.'
                }
                fullWidth
                size="small"
              />
              <Box display="flex" alignItems="center" gap={1} mt={0.5}>
                {editingEndpoint && (
                  <Chip
                    size="small"
                    color={editingEndpoint.has_secret ? 'success' : 'default'}
                    label={editingEndpoint.has_secret ? 'key saved' : 'no key'}
                  />
                )}
                {editingEndpoint?.has_secret && (
                  <FormControlLabel
                    control={
                      <Checkbox
                        size="small"
                        checked={form.clear_api_key}
                        onChange={(e) => set('clear_api_key', e.target.checked)}
                      />
                    }
                    label="Remove stored key"
                  />
                )}
                {editingEndpoint && (
                  <Button
                    size="small"
                    startIcon={testing === editingEndpoint.id ? <CircularProgress size={14} /> : <TestIcon />}
                    disabled={testing === editingEndpoint.id}
                    onClick={() => void test(editingEndpoint, form.api_key.trim() || undefined)}
                  >
                    Test connection
                  </Button>
                )}
              </Box>
              {editingEndpoint && testResults[editingEndpoint.id] && (
                <TestResultAlert result={testResults[editingEndpoint.id]} />
              )}
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
