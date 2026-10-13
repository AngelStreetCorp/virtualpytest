/**
 * Settings → AI → Prices & budget: USD per 1M tokens per endpoint + model, valid from a date,
 * and the team's monthly budget (warn or block). Prices: Used only when a provider
 * reports no cost. The call log stores the cost when the call is made, so a new price never rewrites history.
 * Super admin edits; "no price" on Monitoring → AI usage means no row matches.
 */

import { Add as AddIcon, Delete as DeleteIcon } from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
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
import React, { useCallback, useEffect, useState } from 'react';

import { useConfirmDialog } from '../../../hooks/useConfirmDialog';
import { ConfirmDialog } from '../../common/ConfirmDialog';
import type { AiTabContext } from '../AiRoutingSettings';

import { TEAM_ID, aiApi, errorMessage, numOrNull, strOrNull, type PricePayload } from './api';
import type { AiPrice, BudgetResponse, UnpricedEndpoint } from './types';

interface PriceForm {
  endpoint: string;
  model: string;
  price_in: string;
  price_out: string;
  price_cache_read: string;
  price_cache_write: string;
  price_web_search: string;
  valid_from: string;
  note: string;
}

const emptyForm = (endpoint: string): PriceForm => ({
  endpoint,
  model: '',
  price_in: '',
  price_out: '',
  price_cache_read: '',
  price_cache_write: '',
  price_web_search: '',
  valid_from: new Date().toISOString().slice(0, 10),
  note: '',
});

const SOURCE_LABEL: Record<NonNullable<AiPrice['source']>, string> = {
  manual: 'manual',
  openrouter: 'OpenRouter list',
  langfuse: 'Langfuse',
  plan: 'plan',
};

const fmt = (n: number | null) => (n == null ? '—' : String(n));

export const PricesTab: React.FC<{ ctx: AiTabContext }> = ({ ctx }) => {
  const { config, notify, fail } = ctx;
  const admin = config.is_platform_admin;
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();
  const [prices, setPrices] = useState<AiPrice[]>([]);
  const [unpriced, setUnpriced] = useState<UnpricedEndpoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<PriceForm>(emptyForm(config.endpoints[0]?.name || ''));
  const [saving, setSaving] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [budget, setBudget] = useState<BudgetResponse | null>(null);
  const [budgetOpen, setBudgetOpen] = useState(false);
  const [budgetForm, setBudgetForm] = useState({ limit: '', mode: 'warn' as 'warn' | 'block', warn_at: '80' });

  const loadBudget = useCallback(async () => {
    try {
      setBudget(await aiApi.getBudget());
    } catch {
      setBudget(null); // informative only
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await aiApi.listPrices();
      setPrices(res.prices);
      setUnpriced(res.unpriced ?? []);
    } catch (err) {
      fail(errorMessage(err, 'Failed to load prices'));
    } finally {
      setLoading(false);
    }
  }, [fail]);

  useEffect(() => {
    void load();
    void loadBudget();
  }, [load, loadBudget]);

  const openBudget = () => {
    const b = budget?.budget;
    setBudgetForm({ limit: b ? String(b.limit) : '', mode: b?.mode ?? 'warn', warn_at: String(Math.round((b?.warn_at ?? 0.8) * 100)) });
    setDialogError(null);
    setBudgetOpen(true);
  };

  const saveBudget = async () => {
    const limit = numOrNull(budgetForm.limit);
    const warnAt = numOrNull(budgetForm.warn_at);
    if (limit == null || limit <= 0) return setDialogError('Monthly limit must be above 0 (USD)');
    if (warnAt == null || warnAt <= 0 || warnAt > 100) return setDialogError('Warn at must be 1–100 %');
    setSaving(true);
    setDialogError(null);
    try {
      await aiApi.setBudget({ team_id: TEAM_ID, month_limit_usd: limit, mode: budgetForm.mode, warn_at: warnAt / 100 });
      setBudgetOpen(false);
      notify('Budget saved');
      await loadBudget();
    } catch (err) {
      setDialogError(errorMessage(err, 'Failed to save budget'));
    } finally {
      setSaving(false);
    }
  };

  const removeBudget = () =>
    confirm({
      title: 'Remove budget',
      message: 'Remove the monthly AI budget of this team? Calls are no longer blocked or warned about.',
      confirmText: 'Remove',
      confirmColor: 'error',
      onConfirm: async () => {
        try {
          await aiApi.deleteBudget();
          await loadBudget();
        } catch (err) {
          fail(errorMessage(err, 'Failed to remove budget'));
        }
      },
    });

  const set = <K extends keyof PriceForm>(key: K, value: PriceForm[K]) => setForm((f) => ({ ...f, [key]: value }));

  const save = async () => {
    const priceIn = numOrNull(form.price_in);
    const priceOut = numOrNull(form.price_out);
    if (!form.endpoint) return setDialogError('Pick an endpoint');
    if (!form.model.trim()) return setDialogError('Model is required (* = every model of the endpoint)');
    if (priceIn == null || priceOut == null || priceIn < 0 || priceOut < 0) {
      return setDialogError('Input and output prices are required, 0 or more (USD per 1M tokens)');
    }
    const payload: PricePayload = {
      endpoint: form.endpoint,
      model: form.model.trim(),
      price_in: priceIn,
      price_out: priceOut,
      price_cache_read: numOrNull(form.price_cache_read),
      price_cache_write: numOrNull(form.price_cache_write),
      price_web_search: numOrNull(form.price_web_search),
      valid_from: form.valid_from ? new Date(form.valid_from).toISOString() : undefined,
      note: strOrNull(form.note),
    };
    setSaving(true);
    setDialogError(null);
    try {
      await aiApi.createPrice(payload);
      setOpen(false);
      notify(`Price for ${form.endpoint} · ${form.model} saved`);
      await load();
    } catch (err) {
      setDialogError(errorMessage(err, 'Failed to save price'));
    } finally {
      setSaving(false);
    }
  };

  const remove = (price: AiPrice) =>
    confirm({
      title: 'Delete price',
      message: `Delete the price of ${price.endpoint} · ${price.model} valid from ${price.valid_from.slice(0, 10)}? Calls already logged keep their cost.`,
      confirmText: 'Delete',
      confirmColor: 'error',
      onConfirm: async () => {
        try {
          await aiApi.deletePrice(price.id);
          await load();
        } catch (err) {
          fail(errorMessage(err, 'Failed to delete price'));
        }
      },
    });

  const b = budget?.budget ?? null;

  return (
    <Box>
      <Box display="flex" alignItems="center" mb={2} gap={1}>
        <Typography variant="body2" sx={{ flex: 1 }}>
          <strong>Monthly budget of this team:</strong>{' '}
          {b
            ? `$${b.limit} (${b.mode === 'block' ? 'blocks AI calls once used up' : 'warning only'}), spent $${b.spent} this month, forecast $${b.forecast}`
            : `none set${budget ? ` · spent $${budget.spent} this month, forecast $${budget.forecast}` : ''}`}
          {!admin && ' · only the platform super admin can change it'}
        </Typography>
        {admin && (
          <Button size="small" variant="outlined" onClick={openBudget}>
            {b ? 'Edit budget' : 'Set budget'}
          </Button>
        )}
        {admin && b && (
          <Button size="small" color="error" onClick={removeBudget}>
            Remove
          </Button>
        )}
      </Box>

      <Box display="flex" alignItems="center" mb={1}>
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
          USD per 1M tokens, used only when the provider reports no cost (OpenRouter and Jev do). OpenRouter and Langfuse
          prices are synced daily (a price you type always wins); flat plans and local PCs need no price. A price applies from
          its date on; calls already logged keep the cost they were stored with. Use model * for a whole endpoint
          (a local GPU: price 0).{!admin && ' Only the platform super admin can change prices.'}
        </Typography>
        {admin && (
          <Button
            size="small"
            variant="outlined"
            startIcon={<AddIcon />}
            onClick={() => {
              setForm(emptyForm(config.endpoints[0]?.name || ''));
              setDialogError(null);
              setOpen(true);
            }}
          >
            Add price
          </Button>
        )}
      </Box>

      <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 900, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
        <colgroup>
          <col style={{ width: 140 }} />
          <col />
          <col style={{ width: 80 }} />
          <col style={{ width: 80 }} />
          <col style={{ width: 90 }} />
          <col style={{ width: 90 }} />
          <col style={{ width: 80 }} />
          <col style={{ width: 110 }} />
          <col style={{ width: 120 }} />
          {admin && <col style={{ width: 60 }} />}
        </colgroup>
        <TableHead>
          <TableRow>
            <TableCell>Endpoint</TableCell>
            <TableCell>Model</TableCell>
            <TableCell align="right">In</TableCell>
            <TableCell align="right">Out</TableCell>
            <TableCell align="right">Cache read</TableCell>
            <TableCell align="right">Cache write</TableCell>
            <TableCell align="right">Search</TableCell>
            <TableCell>Valid from</TableCell>
            <TableCell>Source</TableCell>
            {admin && <TableCell />}
          </TableRow>
        </TableHead>
        <TableBody>
          {loading && prices.length === 0 && (
            <TableRow>
              <TableCell colSpan={admin ? 10 : 9}>
                <CircularProgress size={18} />
              </TableCell>
            </TableRow>
          )}
          {!loading && prices.length === 0 && (
            <TableRow>
              <TableCell colSpan={admin ? 10 : 9}>
                <Typography variant="body2" color="text.secondary">
                  No prices yet: calls without a provider-reported cost show "no price".
                </Typography>
              </TableCell>
            </TableRow>
          )}
          {prices.map((price) => (
            <TableRow key={price.id}>
              <TableCell>
                <strong>{price.endpoint}</strong>
              </TableCell>
              <TableCell>{price.model}</TableCell>
              <TableCell align="right">{price.price_in}</TableCell>
              <TableCell align="right">{price.price_out}</TableCell>
              <TableCell align="right">{fmt(price.price_cache_read)}</TableCell>
              <TableCell align="right">{fmt(price.price_cache_write)}</TableCell>
              <TableCell align="right">{fmt(price.price_web_search)}</TableCell>
              <TableCell>{price.valid_from.slice(0, 10)}</TableCell>
              <TableCell title={price.note ?? undefined}>{SOURCE_LABEL[price.source ?? 'manual']}</TableCell>
              {admin && (
                <TableCell align="right">
                  <Tooltip title="Delete">
                    <IconButton size="small" onClick={() => remove(price)}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </TableCell>
              )}
            </TableRow>
          ))}
          {unpriced.map((u) => (
            <TableRow key={`unpriced-${u.endpoint}`}>
              <TableCell>
                <strong>{u.endpoint}</strong>
              </TableCell>
              <TableCell>*</TableCell>
              <TableCell colSpan={5}>
                <Typography variant="body2" color="text.secondary">
                  {u.kind === 'plan' ? 'Included in plan: flat subscription, no cost per call' : 'Local PC: free'}
                </Typography>
              </TableCell>
              <TableCell>—</TableCell>
              <TableCell>{u.kind === 'plan' ? 'plan' : 'local'}</TableCell>
              {admin && <TableCell />}
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Dialog open={open} onClose={() => !saving && setOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Add price</DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 0 }}>
            <Grid item xs={12} sm={6}>
              <TextField label="Endpoint" value={form.endpoint} onChange={(e) => set('endpoint', e.target.value)} select fullWidth size="small">
                {config.endpoints.map((e) => (
                  <MenuItem key={e.id} value={e.name}>
                    {e.name}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                label="Model"
                value={form.model}
                onChange={(e) => set('model', e.target.value)}
                helperText="Exact model id, or * for the whole endpoint"
                fullWidth
                size="small"
              />
            </Grid>
            {(
              [
                ['price_in', 'Input $/1M'],
                ['price_out', 'Output $/1M'],
                ['price_cache_read', 'Cache read $/1M'],
                ['price_cache_write', 'Cache write $/1M'],
                ['price_web_search', '$ per search'],
              ] as [keyof PriceForm, string][]
            ).map(([key, label]) => (
              <Grid item xs={6} sm={4} key={key}>
                <TextField label={label} type="number" value={form[key]} onChange={(e) => set(key, e.target.value)} inputProps={{ min: 0, step: 'any' }} fullWidth size="small" />
              </Grid>
            ))}
            <Grid item xs={12}>
              <Typography variant="caption" color="text.secondary">
                USD per 1M tokens. Cache prices default to the input price; leave empty when the provider has none.
              </Typography>
            </Grid>
            <Grid item xs={6} sm={4}>
              <TextField label="Valid from" type="date" value={form.valid_from} onChange={(e) => set('valid_from', e.target.value)} InputLabelProps={{ shrink: true }} fullWidth size="small" />
            </Grid>
            <Grid item xs={12}>
              <TextField label="Note" value={form.note} onChange={(e) => set('note', e.target.value)} fullWidth size="small" />
            </Grid>
          </Grid>
          {dialogError && (
            <Alert severity="error" sx={{ mt: 1 }}>
              {dialogError}
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)} disabled={saving}>
            Cancel
          </Button>
          <Button variant="contained" onClick={() => void save()} disabled={saving}>
            {saving ? <CircularProgress size={18} /> : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={budgetOpen} onClose={() => !saving && setBudgetOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Monthly AI budget</DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 0 }}>
            <Grid item xs={12}>
              <TextField
                label="Limit per month (USD)"
                type="number"
                value={budgetForm.limit}
                onChange={(e) => setBudgetForm((f) => ({ ...f, limit: e.target.value }))}
                helperText="Counts priced calls only: calls with no price add nothing."
                inputProps={{ min: 0, step: 'any' }}
                fullWidth
                size="small"
              />
            </Grid>
            <Grid item xs={7}>
              <TextField
                label="When it is used up"
                value={budgetForm.mode}
                onChange={(e) => setBudgetForm((f) => ({ ...f, mode: e.target.value as 'warn' | 'block' }))}
                select
                fullWidth
                size="small"
              >
                <MenuItem value="warn">Only warn</MenuItem>
                <MenuItem value="block">Block AI calls</MenuItem>
              </TextField>
            </Grid>
            <Grid item xs={5}>
              <TextField
                label="Warn at (%)"
                type="number"
                value={budgetForm.warn_at}
                onChange={(e) => setBudgetForm((f) => ({ ...f, warn_at: e.target.value }))}
                inputProps={{ min: 1, max: 100 }}
                fullWidth
                size="small"
              />
            </Grid>
          </Grid>
          {dialogError && (
            <Alert severity="error" sx={{ mt: 1 }}>
              {dialogError}
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBudgetOpen(false)} disabled={saving}>
            Cancel
          </Button>
          <Button variant="contained" onClick={() => void saveBudget()} disabled={saving}>
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
