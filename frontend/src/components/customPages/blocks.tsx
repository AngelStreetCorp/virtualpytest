/**
 * The renderers of the custom-page block catalogue (TASK-139). One component per block type in
 * backend_server/src/services/custom_pages/catalogue.py; each reads only its own settings and the device a
 * device_picker block holds, and calls the same server APIs as the page that offers the feature by hand.
 */
import { Box, Button, CircularProgress, FormControlLabel, MenuItem, Select, Switch, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import React, { useEffect, useMemo, useRef, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useHostData } from '../../hooks/useHostManager';
import { useDeviceControlWithForceUnlock } from '../../hooks/useDeviceControlWithForceUnlock';
import { useUserInterface } from '../../hooks/pages/useUserInterface';
import { describeError, runReportQuery } from '../../hooks/reports/runManagementApi';
import { useI18n } from '../../i18n/useI18n';
import { MODEL_FAMILIES } from '../../config/deviceModelFamilies';
import type { PageBlock } from '../../types/customPages';
import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { ConfirmDialog } from '../common/ConfirmDialog';
import { neutralButtonSx, primaryButtonSx } from '../common/PageChrome';
import { RecGotoNodePanel } from '../rec/RecGotoNodePanel';
import { RecHostPreview } from '../rec/RecHostPreview';
import { StatusChip, formatDateTime } from '../reports/status';
import { toRunStatus } from '../../types/reports';
import { NoDevice } from './blockParts';
import { useBlockDevice, usePageRuntime, type DeviceRef } from './PageRuntime';

export interface BlockProps {
  block: PageBlock;
}

// ---------------------------------------------------------------------------------------------
// device_picker
// ---------------------------------------------------------------------------------------------

const MODEL_FILTERS: Record<string, (model: string) => boolean> = {
  any: () => true,
  stb: (m) => m.includes('stb'),
  mobile: (m) => m.includes('mobile') || m === 'phone_agent' || MODEL_FAMILIES.android_phone.includes(m),
  tv: (m) => MODEL_FAMILIES.android_tv.includes(m) || m.includes('tv'),
  web: (m) => m.includes('web') || m.includes('host_vnc'),
};

const storageKey = (pageId: string, blockId: string) => `virtualpytest:custom-page:${pageId}:${blockId}`;

export const DevicePickerBlock: React.FC<BlockProps> = ({ block }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { pageId, picks, setPick } = usePageRuntime();
  const { getAllDevices, getHostByName, isLoading } = useHostData();
  const filter = MODEL_FILTERS[String(block.settings.model_filter ?? 'any')] ?? MODEL_FILTERS.any;
  const options = useMemo(
    () => getAllDevices().filter((d) => filter(String(d.device_model || '').toLowerCase())),
    [getAllDevices, filter],
  );
  const keyOf = (d: { hostName?: string; device_id: string }) => `${d.hostName}:${d.device_id}`;
  const selected = picks[block.id];
  const selectedKey = selected ? `${selected.host.host_name}:${selected.device.device_id}` : '';

  // Restore the last choice of this viewer on this page, else take the only device.
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current || isLoading || selected || options.length === 0) return;
    restored.current = true;
    let saved: string | null = null;
    try {
      saved = window.localStorage.getItem(storageKey(pageId, block.id));
    } catch {
      saved = null;
    }
    const match = options.find((d) => keyOf(d) === saved) ?? (options.length === 1 ? options[0] : undefined);
    const host = match?.hostName ? getHostByName(match.hostName) : null;
    if (match && host) setPick(block.id, { host, device: match });
  }, [options, isLoading, selected, pageId, block.id, getHostByName, setPick]);

  const choose = (key: string) => {
    const device = options.find((d) => keyOf(d) === key);
    const host = device?.hostName ? getHostByName(device.hostName) : null;
    if (!device || !host) return;
    setPick(block.id, { host, device });
    try {
      window.localStorage.setItem(storageKey(pageId, block.id), key);
    } catch {
      /* storage blocked: the choice just does not persist */
    }
  };

  if (isLoading) return <CircularProgress size={18} sx={{ color: P.accent }} />;
  if (options.length === 0) {
    return (
      <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.body.size }}>
        {t('No device matches this filter, or none is allowed in your workspace.')}
      </Typography>
    );
  }
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
      <Select
        size="small"
        displayEmpty
        value={selectedKey}
        onChange={(e) => choose(String(e.target.value))}
        inputProps={{ 'aria-label': t('Device') }}
        renderValue={(v) => (v ? `${selected?.device.device_name || selected?.device.device_id} · ${selected?.host.host_name}` : t('Choose a device'))}
        sx={{ fontSize: TYPOGRAPHY.body.size }}
      >
        {options.map((d) => (
          <MenuItem key={keyOf(d)} value={keyOf(d)}>
            {d.device_name || d.device_id} · {d.hostName}
          </MenuItem>
        ))}
      </Select>
      {selected && (
        <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size }}>
          {selected.device.device_model}
        </Typography>
      )}
    </Box>
  );
};

// ---------------------------------------------------------------------------------------------
// node_goto
// ---------------------------------------------------------------------------------------------

const NodeGotoInner: React.FC<{ target: DeviceRef; pageId: string }> = ({ target, pageId }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { host, device } = target;
  const control = useDeviceControlWithForceUnlock({ host, device_id: device.device_id, sessionId: `custom-page-${pageId}`, autoCleanup: true });
  const dialog = control.confirmDialogState;
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <Button
          size="small"
          variant="contained"
          disabled={control.isControlLoading}
          onClick={() => control.handleDeviceControl()}
          sx={control.isControlActive ? neutralButtonSx(P) : primaryButtonSx(P)}
        >
          {control.isControlActive ? t('Release control') : t('Take control')}
        </Button>
        <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size }}>
          {control.isControlActive ? t('You control {device}', { device: device.device_name || device.device_id }) : t('Take control to go to a node.')}
        </Typography>
      </Box>
      {control.controlError && (
        <Typography sx={{ color: P.error, fontSize: TYPOGRAPHY.caption.size }}>{control.controlError}</Typography>
      )}
      {control.isControlActive && (
        <RecGotoNodePanel host={host} device={device} isControlActive onClose={() => undefined} inline />
      )}
      <ConfirmDialog
        open={dialog.open}
        title={dialog.title}
        message={dialog.message}
        confirmText={dialog.confirmText}
        cancelText={dialog.cancelText}
        confirmColor={dialog.confirmColor}
        onConfirm={control.confirmDialogHandleConfirm}
        onCancel={control.confirmDialogHandleCancel}
      />
    </Box>
  );
};

export const NodeGotoBlock: React.FC<BlockProps> = ({ block }) => {
  const { pageId } = usePageRuntime();
  const target = useBlockDevice(block.settings.device_from);
  if (!target) return <NoDevice />;
  // key: a new device is a new control session
  return <NodeGotoInner key={`${target.host.host_name}:${target.device.device_id}`} target={target} pageId={pageId} />;
};

// ---------------------------------------------------------------------------------------------
// localize_result
// ---------------------------------------------------------------------------------------------

interface LocalizeCandidateRow {
  node_id: string;
  label: string;
  confidence: number;
}
interface LocalizeResponse {
  success?: boolean;
  error?: string;
  verdict?: { kind?: string; label?: string; confidence?: number } | null;
  candidates?: LocalizeCandidateRow[];
  ranked?: LocalizeCandidateRow[];
  frame_url?: string | null;
  total?: number;
}

const LocalizeInner: React.FC<{ target: DeviceRef; block: PageBlock }> = ({ target, block }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { getAllUserInterfaces } = useUserInterface();
  const [interfaces, setInterfaces] = useState<string[]>([]);
  const configured = String(block.settings.userinterface ?? '');
  const [ui, setUi] = useState<string>(configured || target.device.preferred_userinterface || '');
  const [auto, setAuto] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<LocalizeResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAllUserInterfaces()
      .then((list) => {
        if (!cancelled) setInterfaces((list || []).map((u) => u.name).sort((a, b) => a.localeCompare(b)));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const run = React.useCallback(async () => {
    if (!ui) return;
    setLoading(true);
    try {
      const resp = await apiClient(buildServerUrl('/server/navigation/localize'), {
        method: 'POST',
        body: JSON.stringify({ host_name: target.host.host_name, device_id: target.device.device_id, userinterface_name: ui }),
      });
      setResult((await resp.json()) as LocalizeResponse);
    } catch (e) {
      setResult({ success: false, error: e instanceof Error ? e.message : 'Request failed' });
    } finally {
      setLoading(false);
    }
  }, [ui, target]);

  useEffect(() => {
    if (!auto) return undefined;
    const timer = window.setInterval(run, 5000);
    return () => window.clearInterval(timer);
  }, [auto, run]);

  const verdict = result?.verdict;
  const rows = [...(result?.candidates ?? []), ...(result?.ranked ?? []).filter((r) => !(result?.candidates ?? []).some((c) => c.node_id === r.node_id))].slice(0, 5);
  const headline = !result
    ? null
    : !result.success
      ? t('Localize failed')
      : rows.length > 0 && (result.candidates ?? []).length > 0
        ? (result.candidates ?? [])[0].label
        : verdict?.label || t('No match');
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
        <Select
          size="small"
          displayEmpty
          value={ui}
          onChange={(e) => setUi(String(e.target.value))}
          inputProps={{ 'aria-label': t('User interface') }}
          renderValue={(v) => v || t('User interface')}
          sx={{ minWidth: 140, fontSize: TYPOGRAPHY.body.size }}
        >
          {interfaces.map((name) => (
            <MenuItem key={name} value={name}>
              {name}
            </MenuItem>
          ))}
        </Select>
        <Button size="small" variant="contained" disabled={!ui || loading} onClick={run} sx={primaryButtonSx(P)}>
          {loading ? t('Localizing...') : t('Localize now')}
        </Button>
        <FormControlLabel
          control={<Switch size="small" checked={auto} onChange={(e) => setAuto(e.target.checked)} />}
          label={<Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>{t('Every 5 s')}</Typography>}
        />
      </Box>
      {result && (
        <Box>
          <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.navbarItem.size, color: result.success ? P.textPrimary : P.error }}>
            {headline}
          </Typography>
          {!result.success && result.error && (
            <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size }}>{result.error}</Typography>
          )}
          {result.success && verdict?.kind && (
            <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size }}>
              {t('Kind')}: {verdict.kind}
            </Typography>
          )}
          {rows.length > 0 && (
            <Box sx={{ mt: 1, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
              {rows.map((row) => (
                <Box key={row.node_id} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Typography sx={{ flex: '0 0 40%', minWidth: 0, fontSize: TYPOGRAPHY.body.size }} noWrap>
                    {row.label}
                  </Typography>
                  <Box sx={{ flex: 1, height: 6, borderRadius: 3, bgcolor: P.hoverBg, overflow: 'hidden' }}>
                    <Box sx={{ width: `${Math.round(Math.max(0, Math.min(1, row.confidence)) * 100)}%`, height: '100%', bgcolor: P.accent }} />
                  </Box>
                  <Typography sx={{ width: 40, textAlign: 'right', fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>
                    {Math.round(row.confidence * 100)}%
                  </Typography>
                </Box>
              ))}
            </Box>
          )}
        </Box>
      )}
    </Box>
  );
};

export const LocalizeResultBlock: React.FC<BlockProps> = ({ block }) => {
  const target = useBlockDevice(block.settings.device_from);
  if (!target) return <NoDevice />;
  return <LocalizeInner key={`${target.host.host_name}:${target.device.device_id}`} target={target} block={block} />;
};

// ---------------------------------------------------------------------------------------------
// stream
// ---------------------------------------------------------------------------------------------

export const StreamBlock: React.FC<BlockProps> = ({ block }) => {
  const target = useBlockDevice(block.settings.device_from);
  if (!target) return <NoDevice />;
  return (
    <Box sx={{ width: '100%', minHeight: 200 }}>
      <RecHostPreview key={`${target.host.host_name}:${target.device.device_id}`} host={target.host} device={target.device} hideHeader />
    </Box>
  );
};

// ---------------------------------------------------------------------------------------------
// recent_runs
// ---------------------------------------------------------------------------------------------

const tqlQuote = (value: string) => `"${value.replace(/["\\]/g, '\\$&')}"`;

export const RecentRunsBlock: React.FC<BlockProps> = ({ block }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const target = useBlockDevice(block.settings.device_from);
  const wantsDevice = typeof block.settings.device_from === 'string' && block.settings.device_from !== '';
  const limit = Number(block.settings.limit ?? 5);
  const tql = target ? `host:${tqlQuote(target.host.host_name)} device:${tqlQuote(target.device.device_id)}` : '';
  const query = useQuery({
    queryKey: ['custom-page', 'recent-runs', tql, limit],
    queryFn: () =>
      runReportQuery({
        filter: { schema_version: 1, tql },
        columns: ['script_name', 'status', 'started_at'],
        chart: { type: 'none' },
        limit,
        offset: 0,
      }),
    enabled: !wantsDevice || Boolean(target),
    retry: false,
  });
  if (wantsDevice && !target) return <NoDevice />;
  if (query.isLoading) return <CircularProgress size={18} sx={{ color: P.accent }} />;
  if (query.error) return <Typography sx={{ color: P.error, fontSize: TYPOGRAPHY.caption.size }}>{describeError(query.error)}</Typography>;
  const rows = query.data?.rows ?? [];
  if (rows.length === 0) return <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.body.size }}>{t('No runs yet.')}</Typography>;
  return (
    <Box sx={{ overflowX: 'auto' }}>
      <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse', fontSize: TYPOGRAPHY.body.size, '& td': { py: 0.5, pr: 1, borderTop: `1px solid ${P.borderColor}` } }}>
        <tbody>
          {rows.map((row) => (
            <tr key={row.script_result_id}>
              <td>{String(row.script_name ?? '')}</td>
              <td>
                <StatusChip status={toRunStatus(String(row.status ?? ''))} />
              </td>
              <td style={{ color: P.textMuted, whiteSpace: 'nowrap' }}>{formatDateTime(String(row.started_at ?? ''))}</td>
            </tr>
          ))}
        </tbody>
      </Box>
    </Box>
  );
};

// ---------------------------------------------------------------------------------------------
// report
// ---------------------------------------------------------------------------------------------

interface StoredReport {
  name: string;
  valid: boolean;
  filter: { schema_version: number; tql: string };
  columns: Parameters<typeof runReportQuery>[0]['columns'];
}

export const ReportBlock: React.FC<BlockProps> = ({ block }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const reportId = String(block.settings.report_id ?? '');
  const query = useQuery({
    queryKey: ['custom-page', 'report', reportId],
    queryFn: async () => {
      const resp = await apiClient(buildServerUrl(`/server/custom-reports/${reportId}`));
      if (!resp.ok) throw new Error(resp.status === 404 ? t('This saved report was not found, or it is not yours.') : `HTTP ${resp.status}`);
      const report = (await resp.json()) as StoredReport;
      if (!report.valid) throw new Error(t('This saved report is no longer valid. Open it in Test Reports to fix it.'));
      const data = await runReportQuery({ filter: report.filter, columns: report.columns, chart: { type: 'none' }, limit: 20, offset: 0 });
      return { report, data };
    },
    retry: false,
  });
  if (query.isLoading) return <CircularProgress size={18} sx={{ color: P.accent }} />;
  if (query.error) return <Typography sx={{ color: P.error, fontSize: TYPOGRAPHY.caption.size }}>{describeError(query.error)}</Typography>;
  const { report, data } = query.data!;
  return (
    <Box sx={{ overflowX: 'auto' }}>
      <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.body.size, mb: 0.5 }}>{report.name}</Typography>
      <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse', fontSize: TYPOGRAPHY.body.size, '& th, & td': { textAlign: 'left', py: 0.5, pr: 1, borderTop: `1px solid ${P.borderColor}` }, '& th': { color: P.textSecondary, fontWeight: 600 } }}>
        <thead>
          <tr>
            {data.columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr key={row.script_result_id}>
              {data.columns.map((c) => (
                <td key={c}>{c === 'status' ? <StatusChip status={toRunStatus(String(row[c] ?? ''))} /> : String(row[c] ?? '')}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </Box>
      <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size, mt: 0.5 }}>
        {t('{shown} of {total} rows', { shown: data.rows.length, total: data.total })}
      </Typography>
    </Box>
  );
};

// ---------------------------------------------------------------------------------------------
// text
// ---------------------------------------------------------------------------------------------

export const TextBlock: React.FC<BlockProps> = ({ block }) => {
  const P = useAgentChatPalette();
  const text = String(block.settings.text ?? '');
  const heading = block.settings.heading === true;
  return (
    <Typography
      sx={{
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        color: P.textPrimary,
        fontSize: heading ? TYPOGRAPHY.navbarItem.size : TYPOGRAPHY.body.size,
        fontWeight: heading ? 600 : 400,
      }}
    >
      {text}
    </Typography>
  );
};

// ---------------------------------------------------------------------------------------------

export const BLOCK_RENDERERS: Record<string, React.FC<BlockProps>> = {
  device_picker: DevicePickerBlock,
  node_goto: NodeGotoBlock,
  localize_result: LocalizeResultBlock,
  stream: StreamBlock,
  recent_runs: RecentRunsBlock,
  report: ReportBlock,
  text: TextBlock,
};

