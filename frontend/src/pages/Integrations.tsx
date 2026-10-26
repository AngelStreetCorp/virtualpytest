import { Box, Button, Chip, Collapse, IconButton, Link as MuiLink, MenuItem, Select, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material';
import { TYPOGRAPHY } from '../constants/typography';
import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import JiraInstanceForm, { JiraInstance } from '../components/integrations/JiraInstanceForm';
import TestRailConnectionForm, { TestRailFormState } from '../components/integrations/TestRailConnectionForm';
import { PageTitle, StatTiles, pageSurfaceSx, segmentedSx } from '../components/common/PageChrome';
import { getEnv } from '../config/constants';
import { featureNavItems } from '../config/features';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { AppIcon } from '../constants/icons';
import { useI18n } from '../i18n/useI18n';
import { toPublicGitLabUrl } from '../utils/gitlabUrl';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { cachedCheck, clearChecks, isTestDomain, loadFold, saveFold, type CheckState } from '../components/integrations/connectionChecks';

type Status = 'connected' | 'not_configured' | 'error' | 'loading' | 'checking' | 'test';
type Tab = 'tracking' | 'notifications' | 'observability';

const StatusChip: React.FC<{ status: Status; detail?: string; error?: string }> = ({ status, detail, error }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  if (status === 'loading') return null;
  const map = {
    connected: { label: t('Connected'), color: P.success, icon: 'success' as const },
    not_configured: { label: t('Not configured'), color: P.textMuted, icon: 'pending' as const },
    error: { label: t('Connection failed'), color: P.error, icon: 'error' as const },
    checking: { label: t('Checking…'), color: P.textMuted, icon: 'pending' as const },
    test: { label: t('Test instance'), color: P.textMuted, icon: 'info' as const },
  }[status];
  const chip = (
    <Chip
      size="small"
      icon={<AppIcon name={map.icon} color={map.color} />}
      label={detail ? `${map.label} · ${detail}` : map.label}
      sx={{ color: map.color, bgcolor: P.hoverBg, border: `1px solid ${P.borderColor}`, fontWeight: 600 }}
    />
  );
  return error ? <Tooltip title={error}>{chip}</Tooltip> : chip;
};

interface CardProps {
  logo?: string;
  name: string;
  status: Status;
  statusDetail?: string;
  statusError?: string;
  enables: string[];
  tokenUrl?: string;
  docsUrl: string;
  /** In-app page for the tool (ticket table, dashboard…). */
  openTo?: { label: string; path: string };
  openExternal?: { label: string; href: string };
  children?: React.ReactNode;
}

const ToolCard: React.FC<CardProps> = ({ logo, name, status, statusDetail, statusError, enables, tokenUrl, docsUrl, openTo, openExternal, children }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  // Folded by default only when the connection really works; the user's own choice (per card) wins.
  const [chosen, setChosen] = useState<boolean | null>(() => loadFold(name));
  const open = chosen ?? status !== 'connected';
  const toggle = () => { setChosen(!open); saveFold(name, !open); };
  return (
    <Box sx={{ bgcolor: P.surface, border: `1px solid ${P.borderColor}`, borderRadius: 2, p: 2.5 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap', mb: open ? 1.5 : 0 }}>
        {logo
          ? <img src={`/vendor/integrations/${logo}-mark.svg`} alt="" width={24} height={24} style={{ display: 'block', objectFit: 'contain' }} />
          : <AppIcon name="branch" size="md" />}
        <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.sectionTitle.size }}>{name}</Typography>
        <StatusChip status={status} detail={statusDetail} error={statusError} />
        <Box sx={{ flex: 1 }} />
        {openTo && <Button component={Link} to={openTo.path} size="small">{openTo.label} →</Button>}
        {openExternal && <Button component="a" href={openExternal.href} target="_blank" rel="noopener noreferrer" size="small">{openExternal.label} ↗</Button>}
        <IconButton size="small" onClick={toggle} aria-expanded={open} aria-label={open ? t('Fold {name}', { name }) : t('Unfold {name}', { name })}>
          <AppIcon name={open ? 'expand' : 'chevron'} size="md" />
        </IconButton>
      </Box>
      <Collapse in={open} unmountOnExit={false}>
      <Typography sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.caption.size, mb: 0.5 }}>{t('What this enables')}</Typography>
      <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0, mb: 1.5 }}>
        {enables.map((line) => (
          <Box component="li" key={line} sx={{ display: 'flex', gap: 1, alignItems: 'flex-start', py: 0.25 }}>
            <Box sx={{ color: P.success, display: 'flex', mt: '2px' }}><AppIcon name="success" /></Box>
            <Typography sx={{ fontSize: TYPOGRAPHY.body.size }}>{t(line)}</Typography>
          </Box>
        ))}
      </Box>
      <Box sx={{ display: 'flex', gap: 2, mb: children ? 2 : 0 }}>
        {tokenUrl && <MuiLink href={tokenUrl} target="_blank" rel="noopener noreferrer" underline="hover" sx={{ fontSize: TYPOGRAPHY.caption.size }}>{t('Create a token')} ↗</MuiLink>}
        <MuiLink href={docsUrl} target="_blank" rel="noopener noreferrer" underline="hover" sx={{ fontSize: TYPOGRAPHY.caption.size }}>{t('Documentation')} ↗</MuiLink>
      </Box>
      {children}
      </Collapse>
    </Box>
  );
};

const JiraCard: React.FC<{ onCount: (n: number | null) => void }> = ({ onCount }) => {
  const { t } = useI18n();
  const [instances, setInstances] = useState<JiraInstance[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState<string>('');
  const [checks, setChecks] = useState<Record<string, CheckState>>({});

  const load = useCallback(async () => {
    try {
      const response = await fetch(buildServerUrl('/server/integrations/jira/instances'));
      const data = await response.json();
      if (!data.success) throw new Error(data.error || 'failed');
      setInstances(data.instances as JiraInstance[]);
      setFailed(false);
      setSelected((cur) => cur || data.instances[0]?.id || '');
    } catch {
      setFailed(true);
      setInstances([]);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  // One real test per real instance, once per session, in the background (the saved token is used server-side).
  useEffect(() => {
    let live = true;
    (instances || []).filter((i) => !isTestDomain(i.domain)).forEach((i) => {
      setChecks((c) => (c[i.id] ? c : { ...c, [i.id]: { state: 'checking' } }));
      void cachedCheck(`jira:${i.id}`, async () => {
        const response = await fetch(buildServerUrl(`/server/integrations/jira/${encodeURIComponent(i.id)}/test`), {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
        });
        const data = await response.json();
        return data.success ? { state: 'ok' } : { state: 'failed', error: data.error || 'Connection failed' };
      }).then((r) => { if (live) setChecks((c) => ({ ...c, [i.id]: r })); });
    });
    return () => { live = false; };
  }, [instances]);

  const list = instances || [];
  const real = list.filter((i) => !isTestDomain(i.domain));
  const okCount = real.filter((i) => checks[i.id]?.state === 'ok').length;
  const checking = real.some((i) => !checks[i.id] || checks[i.id].state === 'checking');
  const firstError = real.map((i) => checks[i.id]).find((c): c is { state: 'failed'; error: string } => c?.state === 'failed')?.error;
  useEffect(() => { onCount(instances === null || failed ? null : checking ? null : okCount); }, [instances, failed, checking, okCount, onCount]);

  const current = list.find((i) => i.id === selected) || null;
  const status: Status = instances === null ? 'loading'
    : failed ? 'error'
    : !list.length ? 'not_configured'
    : okCount ? 'connected'
    : checking ? 'checking'
    : real.length ? 'error'
    : 'test';
  const statusDetail = status === 'connected' && real.length > 1 ? `${okCount}/${real.length}` : undefined;
  return (
    <ToolCard
      logo="jira" name="Jira" status={status}
      statusDetail={statusDetail}
      statusError={status === 'error' ? firstError : undefined}
      enables={[
        'Push a failed step as a defect, with the screenshot and the report link',
        'See the ticket status next to the run that raised it',
        'One switch per team decides whether defects may be pushed',
      ]}
      tokenUrl="https://id.atlassian.com/manage/api-tokens"
      docsUrl="https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/"
      openTo={{ label: t('Open tickets'), path: '/integrations/jira' }}
    >
      {list.length > 0 && (
        <Select size="small" value={selected} onChange={(e) => setSelected(String(e.target.value))} sx={{ mb: 2, minWidth: 260 }}>
          {list.map((i) => <MenuItem key={i.id} value={i.id}>{i.name} ({i.domain}){isTestDomain(i.domain) ? ` · ${t('Test instance')}` : ''}</MenuItem>)}
          <MenuItem value="">{t('Add an instance')}</MenuItem>
        </Select>
      )}
      <JiraInstanceForm instance={current} onSaved={() => { clearChecks(); setChecks({}); void load(); }} />
    </ToolCard>
  );
};

const TestRailCard: React.FC<{ onConfigured: (v: boolean) => void }> = ({ onConfigured }) => {
  const { t } = useI18n();
  const [state, setState] = useState<TestRailFormState | null>(null);
  const handle = useCallback((s: TestRailFormState) => { setState(s); onConfigured(s.connection?.state === 'ok'); }, [onConfigured]);
  const conn = state?.connection;
  const status: Status = !state?.loaded ? 'loading'
    : !state.configured ? 'not_configured'
    : !conn || conn.state === 'checking' ? 'checking'
    : conn.state === 'ok' ? 'connected'
    : 'error';
  return (
    <ToolCard
      logo="testrail" name="TestRail" status={status}
      statusError={conn?.state === 'failed' ? conn.error : undefined}
      enables={[
        'Publish each completed campaign as a TestRail run',
        'Send mapped results in batches, with unmapped cases reported in Test Reports',
        'Pause or resume automatic publishing with one switch',
      ]}
      docsUrl="https://support.testrail.com/hc/en-us/articles/7076810203028-Introduction-to-the-TestRail-API"
      openTo={{ label: t('Full page'), path: '/integrations/testrail' }}
      openExternal={state?.projectUrl ? { label: t('Open TestRail'), href: state.projectUrl } : undefined}
    >
      <TestRailConnectionForm onState={handle} />
    </ToolCard>
  );
};

const Integrations: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>('tracking');
  const [jiraCount, setJiraCount] = useState<number | null>(null);
  const [testrailOn, setTestrailOn] = useState(false);
  const [slackUrl, setSlackUrl] = useState('');
  const [gitlabUrl, setGitlabUrl] = useState<string | null>(null);

  const hasGitlab = featureNavItems('plugins').some((i) => i.label === 'GitLab');
  const langfuseUrl = getEnv('VITE_LANGFUSE_URL') as string | undefined;
  const grafanaUrl = getEnv('VITE_GRAFANA_URL') as string | undefined;

  useEffect(() => {
    void (async () => {
      try {
        const data = await (await fetch(buildServerUrl('/server/integrations/slack/config'))).json();
        if (data.success && data.config?.url) setSlackUrl(data.config.url);
      } catch { /* shown as not configured */ }
    })();
  }, []);

  useEffect(() => {
    if (!hasGitlab) return;
    void (async () => {
      try {
        const data = await (await fetch(buildServerUrl('/server/gitlab/instances'))).json();
        setGitlabUrl(data?.success && data.instances?.[0]?.base_url ? toPublicGitLabUrl(data.instances[0].base_url) : '');
      } catch { setGitlabUrl(''); }
    })();
  }, [hasGitlab]);

  const tracking = (jiraCount ? 1 : 0) + (testrailOn ? 1 : 0) + (gitlabUrl ? 1 : 0);
  const trackingTotal = hasGitlab ? 3 : 2;
  const slackOn = slackUrl && slackUrl !== 'https://slack.com';
  const observing = (grafanaUrl ? 1 : 0) + (langfuseUrl ? 1 : 0);

  return (
    <Box sx={pageSurfaceSx(P)}>
      <PageTitle title={t('Integrations')} subtitle={t('Connect the tools your team already uses. Tokens are stored on the server and never sent back to the browser.')} />
      <StatTiles
        columns={3}
        tiles={[
          { label: t('Work tracking'), value: `${tracking}/${trackingTotal}`, extra: hasGitlab ? 'Jira, TestRail, GitLab' : 'Jira, TestRail', onClick: () => setTab('tracking'), active: tab === 'tracking' },
          { label: t('Notifications'), value: `${slackOn ? 1 : 0}/1`, extra: 'Slack', onClick: () => setTab('notifications'), active: tab === 'notifications' },
          { label: t('Observability'), value: `${observing}/2`, extra: 'Grafana, Langfuse', onClick: () => setTab('observability'), active: tab === 'observability' },
        ]}
      />
      <ToggleButtonGroup exclusive size="small" value={tab} onChange={(_, v: Tab | null) => v && setTab(v)} sx={{ ...segmentedSx(P, 'sm'), mb: 2 }}>
        <ToggleButton value="tracking">{t('Work tracking')}</ToggleButton>
        <ToggleButton value="notifications">{t('Notifications')}</ToggleButton>
        <ToggleButton value="observability">{t('Observability')}</ToggleButton>
      </ToggleButtonGroup>

      <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', lg: 'repeat(2, minmax(0, 1fr))' }, alignItems: 'start' }}>
        {tab === 'tracking' && (
          <>
            <JiraCard onCount={setJiraCount} />
            <TestRailCard onConfigured={setTestrailOn} />
            {hasGitlab && (
              <ToolCard
                name="GitLab" status={gitlabUrl === null ? 'loading' : gitlabUrl ? 'connected' : 'not_configured'}
                enables={['Browse the connected GitLab instance from the platform', 'Link runs and reports to your repositories']}
                tokenUrl="https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html"
                docsUrl="https://docs.gitlab.com/"
                openExternal={gitlabUrl ? { label: t('Open GitLab'), href: gitlabUrl } : undefined}
              />
            )}
          </>
        )}
        {tab === 'notifications' && (
          <ToolCard
            logo="slack" name="Slack" status={slackOn ? 'connected' : 'not_configured'}
            enables={['Post run and campaign results to a channel', 'Alert the team when a monitored device fails']}
            docsUrl="https://api.slack.com/messaging/webhooks"
            openExternal={{ label: t('Open Slack'), href: slackUrl || 'https://slack.com' }}
          />
        )}
        {tab === 'observability' && (
          <>
            <ToolCard
              logo="grafana" name="Grafana" status={grafanaUrl ? 'connected' : 'not_configured'}
              enables={['Embedded dashboards for devices, runs and KPIs', 'Alerts on quality and availability']}
              docsUrl="https://grafana.com/docs/grafana/latest/"
              openTo={{ label: t('Open dashboards'), path: '/grafana-dashboard' }}
            />
            <ToolCard
              logo="langfuse" name="Langfuse" status={langfuseUrl ? 'connected' : 'not_configured'}
              enables={['Trace every AI call with cost and latency', 'Compare prompts and models over time']}
              docsUrl="https://langfuse.com/docs"
              openTo={{ label: t('Open traces'), path: '/langfuse-dashboard' }}
            />
          </>
        )}
      </Box>
    </Box>
  );
};

export default Integrations;
