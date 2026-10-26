/**
 * AddToProjectDialog — the one Add dialog of the project page.
 *
 * Kind switch (script / testcase / virtual / campaign / device / user), search, tick list,
 * "Add N". Executables and campaigns go through `POST /server/projects/<id>/link`; a device is
 * tagged with the project's tag (`PUT /server/device-flags/<host>/<device>`); a user joins as a
 * viewer (`POST /server/projects/<id>/members`). Items already in the project are hidden.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';

import { useI18n } from '../../i18n/useI18n';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { api, apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { useDeviceFlags } from '../../hooks/useDeviceFlags';
import { neutralButtonSx, primaryButtonSx, segmentedSx } from '../common/PageChrome';
import type { ExecutableType, InScopeResponse } from './ProjectInScope';

export type AddKind = ExecutableType | 'device' | 'user';

interface Candidate {
  id: string;
  name: string;
  meta?: string;
}

const KINDS: AddKind[] = ['script', 'testcase', 'virtual_script', 'campaign', 'device', 'user'];

async function fetchExecutables(kind: ExecutableType, teamId: string | undefined): Promise<Candidate[]> {
  const params = teamId ? `?team_id=${encodeURIComponent(teamId)}` : '';
  if (kind === 'script') {
    const rows = await api.get<Array<{ script_name?: string; name?: string }>>(buildServerUrl(`/server/script/list${params}`));
    return (rows || []).map((r) => ({ id: r.script_name ?? r.name ?? '', name: r.script_name ?? r.name ?? '' })).filter((r) => r.id);
  }
  if (kind === 'testcase') {
    const rows = await api.get<Array<{ testcase_id: string; testcase_name?: string }>>(buildServerUrl(`/server/testcase/list${params}`));
    return (rows || []).map((r) => ({ id: r.testcase_id, name: r.testcase_name || r.testcase_id }));
  }
  if (kind === 'virtual_script') {
    const rows = await api.get<Array<{ id: string; name?: string; folder?: string }>>(buildServerUrl(`/server/virtual-script/list${params}`));
    return (rows || []).map((r) => ({ id: r.id, name: r.name || r.id, meta: r.folder }));
  }
  const res = await api.get<{ campaigns?: Array<{ campaign_id: string; campaign_name?: string }> } | Array<{ campaign_id: string; campaign_name?: string }>>(
    buildServerUrl(`/server/campaigns/getAllCampaigns${params}`),
  );
  const list = Array.isArray(res) ? res : (res?.campaigns ?? []);
  return list.map((r) => ({ id: r.campaign_id, name: r.campaign_name || r.campaign_id }));
}

async function fetchTeamMembers(teamId: string | undefined): Promise<Candidate[]> {
  if (!teamId) return [];
  const rows = await api.get<Array<{ id: string; full_name?: string; email?: string }>>(buildServerUrl(`/server/teams/${teamId}/members`));
  return (rows || []).map((r) => ({ id: r.id, name: r.full_name || r.email || r.id, meta: r.email }));
}

export interface AddToProjectDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  teamId?: string;
  initialKind?: AddKind;
  /** The in-scope answer: what is already in the project. */
  inScope: InScopeResponse | undefined;
  /** `team_members.id` of the current project members. */
  memberIds: string[];
  /** Users can only be added by an owner or admin; the kind is hidden otherwise. */
  canEdit: boolean;
  onAdded: () => void;
}

export const AddToProjectDialog: React.FC<AddToProjectDialogProps> = ({
  open, onClose, projectId, teamId, initialKind = 'script', inScope, memberIds, canEdit, onAdded,
}) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const { deviceFlags } = useDeviceFlags();

  const [kind, setKind] = useState<AddKind>(initialKind);
  const [search, setSearch] = useState('');
  const [items, setItems] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const kindLabel: Record<AddKind, string> = {
    script: t('Script'),
    testcase: t('Testcase'),
    virtual_script: t('Virtual'),
    campaign: t('Campaign'),
    device: t('Device'),
    user: t('User'),
  };

  useEffect(() => {
    if (open) setKind(initialKind);
  }, [open, initialKind]);

  useEffect(() => {
    if (!open) return;
    setPicked(new Set());
    setSearch('');
    setError(null);
    if (kind === 'device') return;
    let cancelled = false;
    setLoading(true);
    setItems([]);
    const load = kind === 'user' ? fetchTeamMembers(teamId) : fetchExecutables(kind, teamId);
    load
      .then((rows) => { if (!cancelled) setItems(rows); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error && e.message ? e.message : t('Failed to load list')); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open, kind, teamId, t]);

  const projectTags = inScope?.tag_names ?? [];

  const candidates = useMemo<Candidate[]>(() => {
    const q = search.trim().toLowerCase();
    let base: Candidate[];
    if (kind === 'device') {
      const inScopeIds = new Set((inScope?.devices ?? []).map((d) => `${d.host_name}:${d.device_id}`));
      base = deviceFlags
        .filter((d) => Array.isArray(d.flags) && d.flags.length > 0)
        .filter((d) => !inScopeIds.has(`${d.host_name}:${d.device_id}`))
        .map((d) => ({ id: `${d.host_name}:${d.device_id}`, name: d.device_name || d.device_id, meta: d.host_name }));
    } else if (kind === 'user') {
      const have = new Set(memberIds);
      base = items.filter((i) => !have.has(i.id));
    } else {
      const have = new Set<string>();
      for (const r of inScope?.executables ?? []) if (r.type === kind) have.add(r.id);
      if (kind === 'campaign') for (const c of inScope?.campaigns ?? []) have.add(c.id);
      base = items.filter((i) => !have.has(i.id));
    }
    return base
      .filter((i) => !q || i.id.toLowerCase().includes(q) || i.name.toLowerCase().includes(q) || (i.meta ?? '').toLowerCase().includes(q))
      .slice(0, 200);
  }, [kind, items, deviceFlags, inScope, memberIds, search]);

  const toggle = (id: string) => setPicked((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const submit = async () => {
    if (pending || picked.size === 0) return;
    setPending(true);
    setError(null);
    const ids = Array.from(picked);
    const results = await Promise.all(ids.map(async (id) => {
      try {
        let res: Response;
        if (kind === 'device') {
          const row = deviceFlags.find((d) => `${d.host_name}:${d.device_id}` === id);
          if (!row) return false;
          const have = new Set((row.flags ?? []).map((f) => f.toLowerCase()));
          const flags = [...(row.flags ?? []), ...projectTags.filter((tag) => !have.has(tag.toLowerCase()))];
          res = await apiClient(buildServerUrl(`/server/device-flags/${row.host_name}/${row.device_id}`), {
            method: 'PUT',
            body: JSON.stringify({ flags }),
          });
        } else if (kind === 'user') {
          res = await apiClient(buildServerUrl(`/server/projects/${projectId}/members`), {
            method: 'POST',
            body: JSON.stringify({ team_member_id: id, role: 'viewer' }),
          });
        } else {
          res = await apiClient(buildServerUrl(`/server/projects/${projectId}/link`), {
            method: 'POST',
            body: JSON.stringify({ type: kind, id }),
          });
        }
        return res.ok;
      } catch {
        return false;
      }
    }));
    setPending(false);
    const failed = results.filter((ok) => !ok).length;
    if (failed < ids.length) onAdded();
    if (failed === 0) {
      onClose();
    } else {
      setPicked(new Set(ids.filter((_, i) => !results[i])));
      setError(t('{count} could not be added', { count: failed }));
    }
  };

  const kinds = KINDS.filter((k) => k !== 'user' || canEdit);

  return (
    <Dialog open={open} onClose={() => { if (!pending) onClose(); }} maxWidth="sm" fullWidth aria-labelledby="add-to-project-title">
      <DialogTitle id="add-to-project-title">{t('Add to project')}</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, mt: 0.5 }}>
          <Box sx={{ overflowX: 'auto' }}>
            <ToggleButtonGroup
              exclusive
              size="small"
              value={kind}
              onChange={(_e, v: AddKind | null) => { if (v) setKind(v); }}
              sx={segmentedSx(P, 'sm')}
            >
              {kinds.map((k) => (
                <ToggleButton key={k} value={k} data-testid={`add-kind-${k}`}>{kindLabel[k]}</ToggleButton>
              ))}
            </ToggleButtonGroup>
          </Box>
          {kind === 'device' && (
            <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
              {t('Adds the project tag to the device')}
            </Typography>
          )}
          <TextField
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            size="small"
            fullWidth
            autoFocus
            placeholder={t('Search')}
            inputProps={{ 'aria-label': t('Search') }}
          />
          <Box sx={{ maxHeight: 320, overflowY: 'auto', border: `1px solid ${P.borderColor}`, borderRadius: 2 }}>
            {loading ? (
              <Typography sx={{ p: 2, color: P.textMuted, fontSize: TYPOGRAPHY.body.size }}>{t('Loading…')}</Typography>
            ) : candidates.length === 0 ? (
              <Typography sx={{ p: 2, color: P.textMuted, fontSize: TYPOGRAPHY.body.size }}>{t('Nothing to add')}</Typography>
            ) : (
              candidates.map((c) => (
                <Box key={c.id} sx={{ px: 1.5, borderBottom: `1px solid ${P.borderColor}`, '&:last-child': { borderBottom: 0 } }}>
                  <FormControlLabel
                    sx={{ width: '100%', m: 0, '& .MuiFormControlLabel-label': { flex: 1, minWidth: 0 } }}
                    control={<Checkbox size="small" checked={picked.has(c.id)} onChange={() => toggle(c.id)} />}
                    label={
                      <Box sx={{ display: 'flex', gap: 1, alignItems: 'baseline', minWidth: 0 }}>
                        <Typography noWrap sx={{ fontSize: TYPOGRAPHY.body.size }}>{c.name}</Typography>
                        {c.meta && <Typography noWrap sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>{c.meta}</Typography>}
                      </Box>
                    }
                  />
                </Box>
              ))
            )}
          </Box>
          {error && <Box role="alert" sx={{ color: P.error, fontSize: TYPOGRAPHY.body.size }}>{error}</Box>}
        </Box>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2, pt: 1, gap: 1 }}>
        <Button onClick={onClose} disabled={pending} size="small" variant="outlined" sx={neutralButtonSx(P)}>{t('Cancel')}</Button>
        <Button
          onClick={() => { void submit(); }}
          variant="contained"
          size="small"
          startIcon={<AddIcon />}
          disabled={pending || picked.size === 0}
          sx={primaryButtonSx(P)}
          data-testid="add-to-project-submit"
        >
          {picked.size > 0 ? t('Add {count}', { count: picked.size }) : t('Add')}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
