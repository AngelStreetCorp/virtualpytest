/**
 * ProjectInScope — the in-scope section of the project detail page.
 *
 * Consumes `GET /server/projects/<id>/in-scope` (BUG-0579) and renders the
 * three groups the v3 mockup pinned (docs/tasks/TASK-101-project-page-mockup-v3.html):
 *
 *   * Devices (left column) — every device whose `device_flags.flags`
 *     intersects the project's tag_names. Per-item runs + pass rate +
 *     last-seen. A `×` button severs the link (admin/owner only).
 *   * Executables (right column) — flat peer list of scripts +
 *     testcases + virtual scripts. Each row carries a type chip
 *     (script / testcase / virtual). Per-item runs + pass rate.
 *   * Campaigns (full-width row below) — separate section, runs +
 *     pass rate from `campaign_executions`. The user agreed (TASK-101
 *     v3 fix) that campaigns sit at a different concept level — they
 *     orchestrate, not execute — so they get their own band, not a
 *     third column at peer height.
 *
 * BUG-0608 — the v2 add/remove surface. The + add buttons open
 * `AddDeviceDialog` (PUTs the project's tag into the device's
 * `device_flags.flags`) and `AddExecutableDialog` (POSTs
 * `/server/projects/<id>/link` for script / testcase / virtual /
 * campaign). The × on a device row now actually severs the link
 * (reads the device's current flags, drops the project's tags,
 * PUTs back) instead of being a no-op stub. The component owns
 * the dialog open-state; the parent re-fetches the in-scope query
 * via `onChanged` after each mutation.
 *
 * The + add and × buttons only render for callers with
 * `canEdit = true` (admin OR project owner, mirrored from the
 * overview's `permissions.can_edit` block).
 *
 * No external dependencies beyond the shared `useI18n`, `apiClient`,
 * `useAgentChatPalette`, and `TYPOGRAPHY` constants the rest of the
 * project uses.
 */
import React, { useMemo, useState } from 'react';
import { Box, Chip, Stack, Tooltip, Typography } from '@mui/material';

import AddIcon from '@mui/icons-material/Add';
import CloseIcon from '@mui/icons-material/Close';

import { useI18n } from '../../i18n/useI18n';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { api, apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { useDeviceFlags } from '../../hooks/useDeviceFlags';
import type { AddKind } from './AddToProjectDialog';


// ---------------------------------------------------------------------------
// Public types — mirror the response shape of GET /server/projects/<id>/in-scope
// ---------------------------------------------------------------------------
export type ExecutableType = 'script' | 'testcase' | 'virtual_script' | 'campaign';

export interface InScopeDevice {
  host_name: string;
  device_id: string;
  device_name: string;
  flags: string[];
  in_scope_via: string;
  runs_30d: number;
  pct_pass: number | null;
  last_seen_at: string | null;
  state: 'online' | 'idle';
}

export interface InScopeExecutable {
  type: ExecutableType;
  id: string;
  name: string;
  runs_30d: number;
  pct_pass: number | null;
}

export interface InScopeCampaign {
  id: string;
  name: string;
  schedule: string | null;
  runs_30d: number;
  pct_pass: number | null;
}

export interface InScopeSummary {
  /** tokens_in + tokens_out summed across the day's `ai_calls` rows. */
  tokens: number;
  /** call count over the same window. */
  calls: number;
  /** cost in USD (rounded to 4 decimals). */
  cost_usd: number;
  /** Biggest token users by usage key / by person (label = display name), top 5. */
  top_features?: Array<{ key: string; tokens: number }>;
  top_senders?: Array<{ key: string; label: string; tokens: number }>;
}

export interface InScopeResponse {
  project_id: string;
  days: number;
  tag_ids: number[];
  tag_names: string[];
  totals: {
    devices: number;
    hosts: number;
    executables: { total: number; scripts: number; testcases: number; virtual: number };
    campaigns: number;
  };
  // BUG-0609 — per-project AI usage summary. The number comes from
  // `ai_calls` filtered by `project_id` and is the project total only;
  // a per-script / per-testcase breakdown is still deferred to a slice
  // that lands a `script_id` column on `ai_calls`. The field is
  // optional so older clients that don't know about it can fall back
  // to no chip.
  summary?: InScopeSummary;
  devices: InScopeDevice[];
  executables: InScopeExecutable[];
  campaigns: InScopeCampaign[];
}


// ---------------------------------------------------------------------------
// Local helpers
// ---------------------------------------------------------------------------
const TYPE_LABEL: Record<ExecutableType, string> = {
  script: 'script',
  testcase: 'testcase',
  virtual_script: 'virtual',
  campaign: 'campaign',
};

const formatRuns = (n: number): string => n.toLocaleString();
const formatPct = (n: number | null): string => (n === null ? '—' : `${n}%`);

const pctColor = (P: ReturnType<typeof useAgentChatPalette>, n: number | null): string => {
  if (n === null) return P.textMuted;
  if (n >= 90) return P.success;
  if (n >= 75) return P.warning;
  return P.error;
};


// ---------------------------------------------------------------------------
// Devices column
// ---------------------------------------------------------------------------
interface DevicesColumnProps {
  devices: InScopeDevice[];
  canEdit: boolean;
  onRemove: (host: string, deviceId: string) => Promise<void>;
  onAdd: () => void;
}

const DevicesColumn: React.FC<DevicesColumnProps> = ({ devices, canEdit, onRemove, onAdd }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();

  // Group by host so the column reads "by host". (TASK-101 v3 had `model`
  // grouping; the schema doesn't carry device_model on `device_flags`,
  // so host_name is the closest stable grouping. The per-host header
  // still answers "is this host in scope?")
  const byHost = useMemo(() => {
    const m = new Map<string, InScopeDevice[]>();
    for (const d of devices) {
      if (!m.has(d.host_name)) m.set(d.host_name, []);
      m.get(d.host_name)!.push(d);
    }
    return Array.from(m.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [devices]);

  if (devices.length === 0) {
    return (
      <Box sx={{ p: 2 }}>
        <ColumnHeader
          label={t('Devices')}
          count={0}
          addLabel={t('add device')}
          onAdd={canEdit ? onAdd : undefined}
        />
        <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.body.size, mt: 1.5 }}>
          {t('No devices in scope yet. Add a device flag that matches this project\'s tag.')}
        </Typography>
      </Box>
    );
  }

  return (
    <Box>
      <ColumnHeader
        label={t('Devices')}
        count={devices.length}
        addLabel={t('add device')}
        onAdd={canEdit ? onAdd : undefined}
      />
      {byHost.map(([host, items]) => (
        <Box key={host} sx={{ mt: 1.5 }}>
          <Typography
            sx={{
              fontSize: TYPOGRAPHY.caption.size,
              color: P.textMuted,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              fontWeight: 600,
              mb: 0.25,
            }}
          >
            {host} · <Box component="span" sx={{ color: P.textPrimary }}>{items.length}</Box>
          </Typography>
          {items.map((d) => (
            <InScopeRow
              key={`${d.host_name}:${d.device_id}`}
              name={`${d.host_name} / ${d.device_id}`}
              state={d.state}
              runs={d.runs_30d}
              pct={d.pct_pass}
              canEdit={canEdit}
              onRemove={() => onRemove(d.host_name, d.device_id)}
            />
          ))}
        </Box>
      ))}
    </Box>
  );
};


// ---------------------------------------------------------------------------
// Executables column — flat peer list
// ---------------------------------------------------------------------------
interface ExecutablesColumnProps {
  rows: InScopeExecutable[];
  canEdit: boolean;
  onRemove: (type: ExecutableType, id: string) => Promise<void>;
  onAdd: () => void;
}

const ExecutablesColumn: React.FC<ExecutablesColumnProps> = ({ rows, canEdit, onRemove, onAdd }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  if (rows.length === 0) {
    return (
      <Box sx={{ p: 2 }}>
        <ColumnHeader
          label={t('Executables')}
          count={0}
          addLabel={t('add script / testcase / virtual')}
          onAdd={canEdit ? onAdd : undefined}
        />
        <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.body.size, mt: 1.5 }}>
          {t('No executables in scope yet.')}
        </Typography>
      </Box>
    );
  }
  return (
    <Box>
      <ColumnHeader
        label={t('Executables')}
        count={rows.length}
        addLabel={t('add script / testcase / virtual')}
        onAdd={canEdit ? onAdd : undefined}
      />
      <Box sx={{ mt: 1.5 }}>
        {rows.map((r) => (
          <ExecutableRow
            key={`${r.type}:${r.id}`}
            type={r.type}
            name={r.name}
            runs={r.runs_30d}
            pct={r.pct_pass}
            canEdit={canEdit}
            onRemove={() => onRemove(r.type, r.id)}
          />
        ))}
      </Box>
    </Box>
  );
};


// ---------------------------------------------------------------------------
// Campaigns band
// ---------------------------------------------------------------------------
interface CampaignsBandProps {
  rows: InScopeCampaign[];
  canEdit: boolean;
  onRemove: (id: string) => Promise<void>;
  onAdd: () => void;
}

const CampaignsBand: React.FC<CampaignsBandProps> = ({ rows, canEdit, onRemove, onAdd }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  if (rows.length === 0) {
    return null; // no row = no band; less noise for projects with no campaigns
  }
  return (
    <Box sx={{ mt: 2.5 }}>
      <Stack
        direction="row"
        alignItems="center"
        spacing={1}
        sx={{ mb: 1 }}
      >
        <Typography
          sx={{
            fontSize: TYPOGRAPHY.body.size,
            color: P.textMuted,
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            fontWeight: 600,
          }}
        >
          {t('Campaigns')}
        </Typography>
        <Chip
          size="small"
          label={rows.length}
          sx={{
            height: 18,
            fontSize: TYPOGRAPHY.microMeta.size,
            backgroundColor: P.hoverBg,
            color: P.textSecondary,
          }}
        />
        <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
          {t('— group runs across many executables, different concept')}
        </Typography>
        {canEdit && (
          <Box
            onClick={onAdd}
            data-testid="project-in-scope-add-campaign"
            sx={{
              ml: 'auto',
              cursor: 'pointer',
              color: P.accent,
              fontSize: TYPOGRAPHY.caption.size,
              '&:hover': { textDecoration: 'underline' },
            }}
          >
            {t('add campaign')}
          </Box>
        )}
      </Stack>
      <Box
        sx={{
          backgroundColor: P.surface,
          border: `1px solid ${P.borderColor}`,
          borderRadius: 3,
          p: 1.5,
        }}
      >
        {rows.map((c) => (
          <CampaignRow
            key={c.id}
            row={c}
            canEdit={canEdit}
            onRemove={() => onRemove(c.id)}
          />
        ))}
      </Box>
    </Box>
  );
};


// ---------------------------------------------------------------------------
// Atoms — ColumnHeader, InScopeRow, ExecutableRow, CampaignRow
// ---------------------------------------------------------------------------
const ColumnHeader: React.FC<{
  label: string;
  count: number;
  addLabel: string;
  onAdd?: () => void;
}> = ({ label, count, addLabel, onAdd }) => {
  const P = useAgentChatPalette();
  return (
    <Stack direction="row" alignItems="center" spacing={1}>
      <Typography
        sx={{
          fontSize: TYPOGRAPHY.body.size,
          color: P.textMuted,
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          fontWeight: 600,
        }}
      >
        {label}
      </Typography>
      <Chip
        size="small"
        label={count}
        sx={{
          height: 18,
          fontSize: TYPOGRAPHY.microMeta.size,
          backgroundColor: P.hoverBg,
          color: P.textSecondary,
        }}
      />
      {onAdd && (
        <Box
          onClick={onAdd}
          sx={{
            ml: 'auto',
            cursor: 'pointer',
            color: P.accent,
            fontSize: TYPOGRAPHY.caption.size,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 0.25,
            '&:hover': { textDecoration: 'underline' },
          }}
        >
          <AddIcon sx={{ fontSize: TYPOGRAPHY.caption.size }} />
          {addLabel}
        </Box>
      )}
    </Stack>
  );
};

const InScopeRow: React.FC<{
  name: string;
  state: 'online' | 'idle';
  runs: number;
  pct: number | null;
  canEdit: boolean;
  onRemove: () => void;
}> = ({ name, state, runs, pct, canEdit, onRemove }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  return (
    <Stack
      direction="row"
      alignItems="center"
      spacing={1}
      sx={{
        py: 0.5,
        borderBottom: `1px dashed ${P.borderColor}`,
        '&:last-of-type': { borderBottom: 0 },
      }}
    >
      <Box
        sx={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          backgroundColor: state === 'online' ? P.success : P.textMuted,
          flexShrink: 0,
        }}
      />
      <Box sx={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        <Typography
          component="span"
          sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textPrimary }}
        >
          {name}
        </Typography>
      </Box>
      <Typography
        sx={{
          fontSize: TYPOGRAPHY.caption.size,
          color: P.textMuted,
          whiteSpace: 'nowrap',
        }}
      >
        {formatRuns(runs)} {t('runs')} ·{' '}
        <Box component="span" sx={{ color: pctColor(P, pct), fontWeight: 600 }}>{formatPct(pct)}</Box>
      </Typography>
      {canEdit && (
        <Tooltip title={t('Remove from project')} arrow>
          <Box
            component="button"
            onClick={onRemove}
            aria-label={t('Remove from project')}
            sx={{
              border: 0,
              background: 'transparent',
              color: P.textMuted,
              cursor: 'pointer',
              padding: 0,
              display: 'flex',
              alignItems: 'center',
              '&:hover': { color: P.error },
            }}
          >
            <CloseIcon sx={{ fontSize: TYPOGRAPHY.body.size }} />
          </Box>
        </Tooltip>
      )}
    </Stack>
  );
};

const TYPE_PALETTE: Record<ExecutableType, { bg: string; fg: string }> = {
  script: { bg: 'rgba(212,165,116,0.16)', fg: '#d4a574' },
  testcase: { bg: 'rgba(96,165,250,0.16)', fg: '#60a5fa' },
  virtual_script: { bg: 'rgba(34,197,94,0.16)', fg: '#22c55e' },
  campaign: { bg: 'rgba(167,139,250,0.16)', fg: '#a78bfa' },
};

const ExecutableRow: React.FC<{
  type: ExecutableType;
  name: string;
  runs: number;
  pct: number | null;
  canEdit: boolean;
  onRemove: () => void;
}> = ({ type, name, runs, pct, canEdit, onRemove }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const palette = TYPE_PALETTE[type];
  return (
    <Stack
      direction="row"
      alignItems="center"
      spacing={1}
      sx={{
        py: 0.5,
        borderBottom: `1px dashed ${P.borderColor}`,
        '&:last-of-type': { borderBottom: 0 },
      }}
    >
      <Box
        sx={{
          fontSize: TYPOGRAPHY.microMeta.size,
          fontWeight: 600,
          padding: '1px 6px',
          borderRadius: 1,
          minWidth: 60,
          textAlign: 'center',
          backgroundColor: palette.bg,
          color: palette.fg,
          letterSpacing: '0.03em',
        }}
      >
        {TYPE_LABEL[type]}
      </Box>
      <Box sx={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        <Typography
          component="span"
          sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textPrimary }}
        >
          {name}
        </Typography>
      </Box>
      <Typography
        sx={{
          fontSize: TYPOGRAPHY.caption.size,
          color: P.textMuted,
          whiteSpace: 'nowrap',
        }}
      >
        {formatRuns(runs)} {t('runs')} ·{' '}
        <Box component="span" sx={{ color: pctColor(P, pct), fontWeight: 600 }}>{formatPct(pct)}</Box>
      </Typography>
      {canEdit && (
        <Tooltip title={t('Remove from project')} arrow>
          <Box
            component="button"
            onClick={onRemove}
            aria-label={t('Remove from project')}
            sx={{
              border: 0,
              background: 'transparent',
              color: P.textMuted,
              cursor: 'pointer',
              padding: 0,
              display: 'flex',
              alignItems: 'center',
              '&:hover': { color: P.error },
            }}
          >
            <CloseIcon sx={{ fontSize: TYPOGRAPHY.body.size }} />
          </Box>
        </Tooltip>
      )}
    </Stack>
  );
};

const CampaignRow: React.FC<{
  row: InScopeCampaign;
  canEdit: boolean;
  onRemove: () => void;
}> = ({ row, canEdit, onRemove }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const passPct = row.pct_pass;
  return (
    <Stack
      direction="row"
      alignItems="center"
      spacing={1.5}
      sx={{
        py: 0.75,
        borderBottom: `1px dashed ${P.borderColor}`,
        '&:last-of-type': { borderBottom: 0 },
      }}
    >
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 600, color: P.textPrimary }}>
          {row.name}
        </Typography>
        {row.schedule && (
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
            {row.schedule}
          </Typography>
        )}
      </Box>
      <Box sx={{ width: 90 }}>
        <Box
          sx={{
            height: 6,
            backgroundColor: P.hoverBg,
            borderRadius: 1,
            overflow: 'hidden',
          }}
        >
          <Box
            sx={{
              height: '100%',
              width: `${passPct ?? 0}%`,
              backgroundColor: pctColor(P, passPct),
            }}
          />
        </Box>
        <Typography
          sx={{
            fontSize: TYPOGRAPHY.microMeta.size,
            color: P.textMuted,
            textAlign: 'right',
            mt: 0.25,
          }}
        >
          <Box component="span" sx={{ color: pctColor(P, passPct), fontWeight: 600 }}>
            {formatPct(passPct)}
          </Box>{' '}
          {t('pass')} · {formatRuns(row.runs_30d)}
        </Typography>
      </Box>
      {canEdit && (
        <Tooltip title={t('Remove from project')} arrow>
          <Box
            component="button"
            onClick={onRemove}
            aria-label={t('Remove from project')}
            sx={{
              border: 0,
              background: 'transparent',
              color: P.textMuted,
              cursor: 'pointer',
              padding: 0,
              display: 'flex',
              alignItems: 'center',
              '&:hover': { color: P.error },
            }}
          >
            <CloseIcon sx={{ fontSize: TYPOGRAPHY.body.size }} />
          </Box>
        </Tooltip>
      )}
    </Stack>
  );
};


// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------
export interface ProjectInScopeProps {
  projectId: string;
  canEdit: boolean;
  data: InScopeResponse | undefined;
  loading: boolean;
  onChanged: () => void;
  /** Opens the project page's Add dialog on this kind. */
  onAdd: (kind: AddKind) => void;
}

export const ProjectInScope: React.FC<ProjectInScopeProps> = ({
  projectId,
  canEdit,
  data,
  loading,
  onChanged,
  onAdd,
}) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();

  // local optimistic state — when the user removes a row, we hide it
  // immediately; the parent re-fetches and reconciles.
  const [removedKeys, setRemovedKeys] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState(false);

  // BUG-0608 — the device-flag table is the source of truth for the
  // picker (it lists every device that has any flag). The existing
  // `useDeviceFlags` hook is the right fetch path — we just
  // re-use it here instead of duplicating the GET.
  const { deviceFlags: allDeviceFlagRows } = useDeviceFlags();

  // The in-scope `tag_names` is lower-cased for the intersection check
  // (the device flags are also lower-cased by the workspace rule).
  const projectTagNamesLower = useMemo(
    () => (data?.tag_names ?? []).map((n) => n.toLowerCase()),
    [data?.tag_names],
  );

  // For the × on a device row: read the device's current flags,
  // remove any tag that matches the project's tag_names, PUT back.
  // The flag-intersection rule for in-scope is `flags ∩ project_tag_names ≠ ∅`,
  // so removing all matching tags is what severs the link.
  const removeDevice = async (host: string, deviceId: string) => {
    if (pending) return;
    const row = allDeviceFlagRows.find(
      (d) => d.host_name === host && d.device_id === deviceId,
    );
    if (!row) {
      // The device has no flag row — the in-scope endpoint shouldn't
      // have surfaced it. Roll back: nothing to do.
      return;
    }
    const newFlags = (row.flags ?? []).filter(
      (f) => !projectTagNamesLower.includes(f.toLowerCase()),
    );
    setPending(true);
    setRemovedKeys((prev) => new Set(prev).add(`device:${host}:${deviceId}`));
    try {
      const res = await apiClient(
        buildServerUrl(`/server/device-flags/${host}/${deviceId}`),
        {
          method: 'PUT',
          body: JSON.stringify({ flags: newFlags }),
        },
      );
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      onChanged();
    } catch {
      // Roll back the optimistic hide on error.
      setRemovedKeys((prev) => {
        const next = new Set(prev);
        next.delete(`device:${host}:${deviceId}`);
        return next;
      });
    } finally {
      setPending(false);
    }
  };

  const removeLink = async (type: ExecutableType, id: string) => {
    setPending(true);
    setRemovedKeys((prev) => new Set(prev).add(`${type}:${id}`));
    try {
      // The BUG-0579 route takes a JSON body on DELETE; the typed
      // `api.delete` helper doesn't expose a body, so we call the raw
      // `apiClient` and check the status.
      const res = await apiClient(buildServerUrl(`/server/projects/${projectId}/link`), {
        method: 'DELETE',
        body: JSON.stringify({ type, id }),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      onChanged();
    } catch {
      // Roll back the optimistic hide on error.
      setRemovedKeys((prev) => {
        const next = new Set(prev);
        next.delete(`${type}:${id}`);
        return next;
      });
    } finally {
      setPending(false);
    }
  };

  if (loading && !data) {
    return (
      <Box sx={{ p: 2 }}>
        <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.body.size }}>
          {t('Loading in-scope artefacts…')}
        </Typography>
      </Box>
    );
  }

  if (!data) {
    return null;
  }

  const visibleDevices = data.devices.filter(
    (d) => !removedKeys.has(`device:${d.host_name}:${d.device_id}`),
  );
  const visibleExecutables = data.executables.filter(
    (r) => !removedKeys.has(`${r.type}:${r.id}`),
  );
  const visibleCampaigns = data.campaigns.filter(
    (c) => !removedKeys.has(`campaign:${c.id}`),
  );

  return (
    <Box>
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={1.5}
        sx={{
          alignItems: 'stretch',
        }}
      >
        <Box
          sx={{
            flex: 1,
            backgroundColor: P.surface,
            border: `1px solid ${P.borderColor}`,
            borderRadius: 3,
            p: 1.5,
          }}
        >
          <DevicesColumn
            devices={visibleDevices}
            canEdit={canEdit && !pending}
            onRemove={removeDevice}
            onAdd={() => onAdd('device')}
          />
        </Box>
        <Box
          sx={{
            flex: 1.15,
            backgroundColor: P.surface,
            border: `1px solid ${P.borderColor}`,
            borderRadius: 3,
            p: 1.5,
          }}
        >
          <ExecutablesColumn
            rows={visibleExecutables}
            canEdit={canEdit && !pending}
            onRemove={removeLink}
            onAdd={() => onAdd('script')}
          />
        </Box>
      </Stack>

      {visibleCampaigns.length > 0 && (
        <CampaignsBand
          rows={visibleCampaigns}
          canEdit={canEdit && !pending}
          onRemove={(id) => removeLink('campaign', id)}
          onAdd={() => onAdd('campaign')}
        />
      )}

    </Box>
  );
};


// ---------------------------------------------------------------------------
// Public helper for the parent — wraps the GET /in-scope call so the
// ProjectDetail page doesn't import useQuery twice for the same URL.
// ---------------------------------------------------------------------------
export const fetchProjectInScope = (projectId: string, days: number = 30) =>
  api.get<InScopeResponse>(
    buildServerUrl(`/server/projects/${projectId}/in-scope?days=${days}`),
  );
