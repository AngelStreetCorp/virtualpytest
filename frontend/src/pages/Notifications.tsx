import React, { useMemo, useState } from 'react';
import {
  Box,
  Button,
  Checkbox,
  IconButton,
  MenuItem,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material';
import { useNavigate } from 'react-router-dom';

import { PageTitle, pageSurfaceSx, neutralButtonSx, segmentedSx } from '../components/common/PageChrome';
import { formatAgo } from '../components/dashboard/dashboardFormat';
import { APP_CONFIG } from '../config/constants';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { AppIcon } from '../constants/icons';
import { TYPOGRAPHY } from '../constants/typography';
import {
  inheritedRow,
  NOTIFICATION_CATEGORIES,
  notificationStore,
  useNotifications,
  type MinSeverity,
  type NotificationCategory,
  type NotificationItem,
  type NotificationPrefRow,
  type PrefScopeType,
} from '../contexts/notificationStore';
import { useCurrentProject } from '../hooks/common/useCurrentProject';
import { useNotificationPrefs } from '../hooks/useNotificationPrefs';
import { useWorkspaces } from '../hooks/pages/useWorkspaces';
import { useToast } from '../hooks/useToast';
import { useI18n } from '../i18n/useI18n';

type Tab = 'history' | 'settings';
const SEVERITIES: MinSeverity[] = ['info', 'warning', 'error'];
const MUTE_MS: Record<string, number> = { '1h': 3600e3, '1d': 86400e3, '7d': 7 * 86400e3 };

/** Category labels. The English text is the i18n key. */
const useCategoryLabel = () => {
  const { t } = useI18n();
  const labels: Record<NotificationCategory, string> = {
    device: t('Devices'),
    host: t('Hosts'),
    script: t('Scripts'),
    capture: t('Capture'),
    ai_spend: t('Wasted AI tokens'),
    storage: t('Storage'),
    deploy: t('Deployments'),
    security: t('Security'),
    support: t('Support'),
    action: t('Action errors'),
  };
  return (c: NotificationCategory | undefined) => labels[c ?? 'action'];
};

const useSeverityLabel = () => {
  const { t } = useI18n();
  return (s: string) => (s === 'error' ? t('Error') : s === 'warning' ? t('Warning') : t('Info'));
};

const HistoryTab: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const navigate = useNavigate();
  const items = useNotifications();
  const categoryLabel = useCategoryLabel();
  const severityLabel = useSeverityLabel();
  const { showError } = useToast();
  const { rows, userId, save } = useNotificationPrefs();
  const [category, setCategory] = useState<'all' | NotificationCategory>('all');
  const [severity, setSeverity] = useState<'all' | 'error' | 'warning'>('all');
  const isMuted = (n: NotificationItem) =>
    rows.some((r) => r.scope_type === 'device' && r.scope_id === n.scope?.device_id && r.category === (n.category ?? 'action') && (r.user_id ?? '') === (userId ?? ''));
  /** Writes the user's own device row: this category stays quiet (no bell, no toast) for this one device. */
  const muteDevice = async (n: NotificationItem) => {
    try {
      await save({
        scope_type: 'device',
        scope_id: n.scope?.device_id ?? '',
        category: n.category ?? 'action',
        bell: false,
        toast: false,
        email: false,
        min_severity: 'info',
        muted_until: null,
        locked: false,
      });
    } catch (err) {
      showError(err instanceof Error ? err.message : t('Could not save the notification settings'), { id: 'notification-prefs-save', category: 'action' });
    }
  };
  const shown = items.filter(
    (n) => (category === 'all' || (n.category ?? 'action') === category) && (severity === 'all' || n.severity === severity),
  );

  const open = (n: NotificationItem) => {
    notificationStore.markRead(n.id);
    if (n.to) navigate(n.to);
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', alignItems: 'center', mb: 1.5 }}>
        <Select size="small" value={category} onChange={(e) => setCategory(e.target.value as 'all' | NotificationCategory)} sx={{ minWidth: 180 }}>
          <MenuItem value="all">{t('All categories')}</MenuItem>
          {NOTIFICATION_CATEGORIES.map((c) => (
            <MenuItem key={c} value={c}>{categoryLabel(c)}</MenuItem>
          ))}
        </Select>
        <ToggleButtonGroup exclusive size="small" value={severity} onChange={(_, v) => v && setSeverity(v)} sx={segmentedSx(P, 'sm')}>
          <ToggleButton value="all">{t('All')}</ToggleButton>
          <ToggleButton value="error">{t('Error')}</ToggleButton>
          <ToggleButton value="warning">{t('Warning')}</ToggleButton>
        </ToggleButtonGroup>
        <Box sx={{ flex: 1 }} />
        <Button size="small" variant="outlined" disabled={!items.some((n) => !n.read)} onClick={notificationStore.markAllRead} sx={neutralButtonSx(P)}>
          {t('Mark all read')}
        </Button>
        <Button size="small" variant="outlined" disabled={items.length === 0} onClick={notificationStore.clear} sx={neutralButtonSx(P)}>
          {t('Clear')}
        </Button>
      </Box>
      {shown.length === 0 ? (
        <Typography sx={{ p: 4, textAlign: 'center', color: P.textMuted }}>{t('No notifications')}</Typography>
      ) : (
        <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 2 }}>
          {shown.map((n) => (
            <Box key={n.id} sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5, px: 1.5, py: 1, borderBottom: `1px solid ${P.borderColor}`, '&:last-child': { borderBottom: 'none' }, '&:hover': { bgcolor: P.hoverBg } }}>
              <Box sx={{ pt: 0.25 }}>
                <AppIcon name={n.severity} />
              </Box>
              <Box
                role={n.to ? 'link' : undefined}
                tabIndex={0}
                onClick={() => open(n)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    open(n);
                  }
                }}
                sx={{ flex: 1, minWidth: 0, cursor: n.to ? 'pointer' : 'default', '&:focus-visible': { outline: `2px solid ${P.accentText}` } }}
              >
                <Typography sx={{ fontWeight: n.read ? 400 : 600, wordBreak: 'break-word' }}>{n.message}</Typography>
                <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size }}>
                  {categoryLabel(n.category)} · {severityLabel(n.severity)} · {t('{ago} ago', { ago: formatAgo(new Date(n.ts).toISOString(), Date.now(), t) })}
                </Typography>
              </Box>
              {n.scope?.device_id && !isMuted(n) && (
                <Button size="small" variant="outlined" onClick={() => muteDevice(n)} sx={{ ...neutralButtonSx(P), flexShrink: 0 }}>
                  {t('Mute this device')}
                </Button>
              )}
              <Tooltip title={t('Dismiss')}>
                <IconButton size="small" aria-label={t('Dismiss')} onClick={() => notificationStore.dismiss(n.id)} sx={{ color: P.textMuted }}>
                  <AppIcon name="close" />
                </IconButton>
              </Tooltip>
            </Box>
          ))}
        </Box>
      )}
    </Box>
  );
};

/** Devices this user muted from the history (device rows of their own), each with an unmute button. */
const MutedDevices: React.FC<{
  rows: NotificationPrefRow[];
  userId: string | undefined;
  remove: (key: { scope_type: PrefScopeType; scope_id: string; category: NotificationCategory }) => Promise<void>;
}> = ({ rows, userId, remove }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { showError } = useToast();
  const categoryLabel = useCategoryLabel();
  const muted = rows.filter((r) => r.scope_type === 'device' && !!userId && r.user_id === userId);
  if (muted.length === 0) return null;
  return (
    <Box sx={{ mt: 3 }}>
      <Typography sx={{ fontWeight: 600, mb: 0.5 }}>{t('Muted devices')}</Typography>
      <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size, mb: 1 }}>
        {t('These devices stay quiet for you. Everyone else still hears about them.')}
      </Typography>
      <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 2 }}>
        {muted.map((r) => (
          <Box key={`${r.scope_id}:${r.category}`} sx={{ display: 'flex', alignItems: 'center', gap: 1.5, px: 1.5, py: 1, borderBottom: `1px solid ${P.borderColor}`, '&:last-child': { borderBottom: 'none' } }}>
            <Typography sx={{ flex: 1, minWidth: 0, wordBreak: 'break-word' }}>
              {r.scope_id} · <span style={{ color: P.textMuted }}>{categoryLabel(r.category)}</span>
            </Typography>
            <Button
              size="small"
              variant="outlined"
              sx={neutralButtonSx(P)}
              onClick={() =>
                remove({ scope_type: 'device', scope_id: r.scope_id, category: r.category }).catch((err) =>
                  showError(err instanceof Error ? err.message : t('Could not save the notification settings'), { id: 'notification-prefs-save', category: 'action' }),
                )
              }
            >
              {t('Unmute')}
            </Button>
          </Box>
        ))}
      </Box>
    </Box>
  );
};

const SettingsTab: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { showError } = useToast();
  const categoryLabel = useCategoryLabel();
  const severityLabel = useSeverityLabel();
  const { rows, userId, isAdmin, loaded, save, remove } = useNotificationPrefs();
  const { workspaces } = useWorkspaces();
  const { projects } = useCurrentProject();
  const [scopeType, setScopeType] = useState<PrefScopeType>('user');
  const [workspaceId, setWorkspaceId] = useState('');
  const [projectId, setProjectId] = useState('');

  const scopeId =
    scopeType === 'user' ? userId ?? '' : scopeType === 'team' ? APP_CONFIG.DEFAULT_TEAM_ID : scopeType === 'workspace' ? workspaceId : projectId;
  const shared = scopeType !== 'user';
  const readOnly = (shared && !isAdmin) || !scopeId;

  const lockedByAdmin = useMemo(
    () => new Set(rows.filter((r) => r.locked && r.scope_type !== 'user').map((r) => r.category)),
    [rows],
  );

  const own = (category: NotificationCategory) =>
    rows.find((r) => r.scope_type === scopeType && r.scope_id === scopeId && r.category === category);

  const effective = (category: NotificationCategory) => {
    const row = own(category);
    return row ?? { ...inheritedRow(rows, category, scopeType, scopeId), muted_until: null as string | null };
  };

  const write = async (category: NotificationCategory, patch: Partial<NotificationPrefRow>) => {
    const eff = effective(category);
    const row: NotificationPrefRow = {
      scope_type: scopeType,
      scope_id: scopeId,
      category,
      bell: eff.bell,
      toast: eff.toast,
      email: false,
      min_severity: eff.min_severity,
      muted_until: (eff as NotificationPrefRow).muted_until ?? null,
      locked: !!eff.locked && shared,
      ...patch,
    };
    try {
      await save(row);
    } catch (err) {
      showError(err instanceof Error ? err.message : t('Could not save the notification settings'), { id: 'notification-prefs-save', category: 'action' });
    }
  };

  const reset = async (category: NotificationCategory) => {
    try {
      await remove({ scope_type: scopeType, scope_id: scopeId, category });
    } catch (err) {
      showError(err instanceof Error ? err.message : t('Could not save the notification settings'), { id: 'notification-prefs-save', category: 'action' });
    }
  };

  const muteValue = (until?: string | null) => (until && Date.parse(until) > Date.now() ? 'on' : 'off');

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap', mb: 1.5 }}>
        <Typography sx={{ color: P.textMuted }}>{t('Applies to')}</Typography>
        <ToggleButtonGroup exclusive size="small" value={scopeType} onChange={(_, v) => v && setScopeType(v)} sx={segmentedSx(P, 'sm')}>
          <ToggleButton value="user">{t('User')}</ToggleButton>
          <ToggleButton value="project">{t('Project')}</ToggleButton>
          <ToggleButton value="workspace">{t('Workspace')}</ToggleButton>
          <ToggleButton value="team">{t('Team')}</ToggleButton>
        </ToggleButtonGroup>
        {scopeType === 'workspace' && (
          <Select size="small" displayEmpty value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)} sx={{ minWidth: 200 }}>
            <MenuItem value="">{t('Choose a workspace')}</MenuItem>
            {workspaces.map((w) => (
              <MenuItem key={w.id} value={w.id}>{w.name}</MenuItem>
            ))}
          </Select>
        )}
        {scopeType === 'project' && (
          <Select size="small" displayEmpty value={projectId} onChange={(e) => setProjectId(e.target.value)} sx={{ minWidth: 200 }}>
            <MenuItem value="">{t('Choose a project')}</MenuItem>
            {projects.map((p) => (
              <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>
            ))}
          </Select>
        )}
      </Box>
      <Typography sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size, mb: 1 }}>
        {scopeType === 'user'
          ? t('Your own choice. It wins over the project, workspace and team defaults unless an admin locked the row.')
          : isAdmin
            ? t('A default for everyone in this scope. Lock a row to stop members from muting it.')
            : t('Only a team admin can change this level.')}
      </Typography>
      <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 2, overflowX: 'auto', opacity: loaded ? 1 : 0.6 }}>
        <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 760 }}>
          <colgroup>
            <col />
            <col style={{ width: 64 }} />
            <col style={{ width: 64 }} />
            <col style={{ width: 64 }} />
            <col style={{ width: 140 }} />
            <col style={{ width: 170 }} />
            {shared && <col style={{ width: 80 }} />}
            <col style={{ width: 56 }} />
          </colgroup>
          <TableHead>
            <TableRow>
              <TableCell>{t('Category')}</TableCell>
              <TableCell>{t('Bell')}</TableCell>
              <TableCell>{t('Toast')}</TableCell>
              <TableCell>{t('Email')}</TableCell>
              <TableCell>{t('Toast from')}</TableCell>
              <TableCell>{t('Mute')}</TableCell>
              {shared && <TableCell>{t('Locked')}</TableCell>}
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {NOTIFICATION_CATEGORIES.map((category) => {
              const eff = effective(category) as NotificationPrefRow;
              const locked = !shared && lockedByAdmin.has(category);
              const off = readOnly || locked;
              const isAction = category === 'action';
              return (
                <TableRow key={category}>
                  <TableCell>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, color: locked ? P.textMuted : 'inherit' }}>
                      {locked && (
                        <Tooltip title={t('Locked by a team admin')}>
                          <span><AppIcon name="lock" /></span>
                        </Tooltip>
                      )}
                      {categoryLabel(category)}
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Checkbox size="small" checked={eff.bell} disabled={off} onChange={(e) => write(category, { bell: e.target.checked })} inputProps={{ 'aria-label': `${categoryLabel(category)} ${t('Bell')}` }} />
                  </TableCell>
                  <TableCell>
                    <Tooltip title={isAction ? t('An error from something you just did always shows') : ''}>
                      <span>
                        <Checkbox size="small" checked={isAction ? true : eff.toast} disabled={off || isAction} onChange={(e) => write(category, { toast: e.target.checked })} inputProps={{ 'aria-label': `${categoryLabel(category)} ${t('Toast')}` }} />
                      </span>
                    </Tooltip>
                  </TableCell>
                  <TableCell>
                    <Tooltip title={t('Email arrives in a later release')}>
                      <span><Checkbox size="small" checked={false} disabled inputProps={{ 'aria-label': `${categoryLabel(category)} ${t('Email')}` }} /></span>
                    </Tooltip>
                  </TableCell>
                  <TableCell>
                    <Select size="small" value={eff.min_severity} disabled={off} onChange={(e) => write(category, { min_severity: e.target.value as MinSeverity })} sx={{ minWidth: 110 }}>
                      {SEVERITIES.map((s) => (
                        <MenuItem key={s} value={s}>{severityLabel(s)}</MenuItem>
                      ))}
                    </Select>
                  </TableCell>
                  <TableCell>
                    <Select
                      size="small"
                      value={muteValue(eff.muted_until)}
                      disabled={off || isAction}
                      onChange={(e) => {
                        const v = e.target.value as string;
                        write(category, { muted_until: v in MUTE_MS ? new Date(Date.now() + MUTE_MS[v]).toISOString() : null });
                      }}
                      renderValue={(v) => (v === 'on' ? t('Until {date}', { date: new Date(eff.muted_until as string).toLocaleDateString() }) : t('Not muted'))}
                      sx={{ minWidth: 150 }}
                    >
                      <MenuItem value="off">{t('Not muted')}</MenuItem>
                      <MenuItem value="1h">{t('1 hour')}</MenuItem>
                      <MenuItem value="1d">{t('1 day')}</MenuItem>
                      <MenuItem value="7d">{t('7 days')}</MenuItem>
                    </Select>
                  </TableCell>
                  {shared && (
                    <TableCell>
                      <Checkbox size="small" checked={!!eff.locked} disabled={off} onChange={(e) => write(category, { locked: e.target.checked })} inputProps={{ 'aria-label': `${categoryLabel(category)} ${t('Locked')}` }} />
                    </TableCell>
                  )}
                  <TableCell align="right">
                    {own(category) && !off && (
                      <Tooltip title={t('Use the inherited setting')}>
                        <IconButton size="small" aria-label={t('Use the inherited setting')} onClick={() => reset(category)} sx={{ color: P.textMuted }}>
                          <AppIcon name="refresh" />
                        </IconButton>
                      </Tooltip>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Box>
      <MutedDevices rows={rows} userId={userId} remove={remove} />
    </Box>
  );
};

const Notifications: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>('history');
  return (
    <Box sx={pageSurfaceSx(P)}>
      <PageTitle
        title={t('Notifications')}
        subtitle={t('What happened, and which of it you want to hear about.')}
        right={
          <ToggleButtonGroup exclusive size="small" value={tab} onChange={(_, v) => v && setTab(v)} sx={segmentedSx(P)}>
            <ToggleButton value="history">{t('History')}</ToggleButton>
            <ToggleButton value="settings">{t('Settings')}</ToggleButton>
          </ToggleButtonGroup>
        }
      />
      {tab === 'history' ? <HistoryTab /> : <SettingsTab />}
    </Box>
  );
};

export default Notifications;
