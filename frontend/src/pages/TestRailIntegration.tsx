import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  FormControl,
  FormControlLabel,
  Switch,
  Divider,
  InputLabel,
  Link as MuiLink,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { OpenInNew as OpenInNewIcon } from '@mui/icons-material';
import React, { useEffect, useState } from 'react';
import { buildServerUrl } from '../utils/buildUrlUtils';

interface TestRailProject { id: number; name: string }
interface ConnectionCheck { success: boolean; error?: string; category?: string; projects?: TestRailProject[]; base_url?: string }

const TestRailIntegration: React.FC = () => {
  const [baseUrl, setBaseUrl] = useState('https://virtualpytest.testrail.io');
  const [username, setUsername] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [projectId, setProjectId] = useState('');
  const [projects, setProjects] = useState<TestRailProject[]>([]);
  const [hasCredentials, setHasCredentials] = useState(false);
  const [autoPublish, setAutoPublish] = useState(false);
  const [busy, setBusy] = useState(false);
  const [check, setCheck] = useState<ConnectionCheck | null>(null);
  const [notice, setNotice] = useState<{ kind: 'success' | 'error' | 'info'; text: string } | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const response = await fetch(buildServerUrl('/server/integrations/testrail/config'));
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || 'Could not load TestRail settings.');
        if (data.config?.base_url) setBaseUrl(data.config.base_url);
        if (data.config?.username) setUsername(data.config.username);
        if (data.config?.project_id) setProjectId(String(data.config.project_id));
        setHasCredentials(Boolean(data.config?.has_credentials));
        setAutoPublish(Boolean(data.config?.auto_publish));
      } catch (error) {
        setNotice({ kind: 'error', text: error instanceof Error ? error.message : 'Could not load TestRail settings.' });
      }
    })();
  }, []);

  const testConnection = async () => {
    setBusy(true);
    setNotice({ kind: 'info', text: 'Testing the TestRail connection…' });
    setCheck(null);
    try {
      const response = await fetch(buildServerUrl('/server/integrations/testrail/test'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ base_url: baseUrl, username, api_key: apiKey }),
      });
      const data = await response.json() as ConnectionCheck;
      setCheck(data);
      if (!response.ok || !data.success) throw new Error(data.error || 'TestRail connection failed.');
      setProjects(data.projects || []);
      const selected = data.projects?.find((project) => String(project.id) === projectId);
      setNotice({
        kind: 'success',
        text: selected
          ? `Connected to ${data.base_url}. ${selected.name} is selected; save to apply the configuration.`
          : `Connected to ${data.base_url}. Found ${data.projects?.length ?? 0} accessible project(s). Choose a project to continue.`,
      });
    } catch (error) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : 'TestRail connection failed.' });
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    setNotice({ kind: 'info', text: 'Saving the TestRail connection…' });
    try {
      const response = await fetch(buildServerUrl('/server/integrations/testrail/config'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ base_url: baseUrl, username, api_key: apiKey, project_id: projectId || null }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || 'Could not save TestRail settings.');
      setHasCredentials(true);
      setApiKey('');
      setNotice({ kind: 'success', text: 'TestRail connection saved.' });
    } catch (error) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : 'Could not save TestRail settings.' });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setNotice({ kind: 'info', text: 'Removing the TestRail connection…' });
    try {
      const response = await fetch(buildServerUrl('/server/integrations/testrail/config'), { method: 'DELETE' });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || 'Could not remove TestRail settings.');
      setHasCredentials(false); setAutoPublish(false); setApiKey(''); setProjectId(''); setProjects([]); setCheck(null);
      setUsername(''); setBaseUrl('https://virtualpytest.testrail.io');
      setNotice({ kind: 'info', text: 'Connection removed. Enter new TestRail credentials to set it up again.' });
    } catch (error) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : 'Could not remove TestRail settings.' });
    } finally { setBusy(false); }
  };

  const updateAutoPublish = async (enabled: boolean) => {
    setBusy(true);
    setNotice({ kind: 'info', text: enabled ? 'Enabling automatic TestRail publishing…' : 'Pausing automatic TestRail publishing…' });
    try {
      const response = await fetch(buildServerUrl('/server/integrations/testrail/automation'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || 'Could not update TestRail publishing settings.');
      setAutoPublish(Boolean(data.auto_publish));
      setNotice({ kind: 'success', text: enabled ? 'Automatic publishing is on for completed campaign runs.' : 'Automatic publishing is paused.' });
    } catch (error) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : 'Could not update TestRail publishing settings.' });
    } finally {
      setBusy(false);
    }
  };

  const connectionReady = Boolean(check?.success && check.base_url === baseUrl.replace(/\/$/, ''));

  const invalidateConnection = () => {
    setCheck(null);
    setProjects([]);
    setProjectId('');
    setNotice({ kind: 'info', text: 'Connection details changed. Test the connection again before saving.' });
  };

  const testRailProjectUrl = hasCredentials && projectId
    ? `${baseUrl}/index.php?/projects/overview/${encodeURIComponent(projectId)}`
    : '';

  return (
    <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 900, mx: 'auto' }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
        <Typography variant="h4">TestRail</Typography>
        {testRailProjectUrl && (
          <Button component={MuiLink} href={testRailProjectUrl} target="_blank" rel="noopener noreferrer" endIcon={<OpenInNewIcon />}>
            Open TestRail
          </Button>
        )}
      </Stack>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Connect your TestRail project to publish VirtualPyTest results. Credentials are stored on the backend and never returned to this page.
      </Typography>
      <Card><CardContent>
        <Stack spacing={2.5}>
          <TextField label="TestRail instance URL" value={baseUrl} disabled={hasCredentials} onChange={(e) => { setBaseUrl(e.target.value); invalidateConnection(); }} placeholder="https://company.testrail.io" fullWidth />
          <TextField label="Username or email" value={username} disabled={hasCredentials} onChange={(e) => { setUsername(e.target.value); invalidateConnection(); }} autoComplete="username" fullWidth />
          {!hasCredentials && <TextField label="API key" value={apiKey} onChange={(e) => { setApiKey(e.target.value); invalidateConnection(); }} type="password" autoComplete="new-password" fullWidth />}
          {projects.length > 0 && <FormControl fullWidth>
            <InputLabel id="testrail-project-label">TestRail project</InputLabel>
            <Select labelId="testrail-project-label" label="TestRail project" value={projectId} onChange={(e) => {
              const value = String(e.target.value);
              setProjectId(value);
              const selected = projects.find((project) => String(project.id) === value);
              setNotice({
                kind: 'success',
                text: selected ? `${selected.name} selected. Save to apply the configuration.` : 'Choose a TestRail project to continue.',
              });
            }}>
              <MenuItem value=""><em>Choose a project</em></MenuItem>
              {projects.map((project) => <MenuItem key={project.id} value={String(project.id)}>{project.name} (#{project.id})</MenuItem>)}
            </Select>
          </FormControl>}
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
            <Button variant="outlined" onClick={() => void testConnection()} disabled={busy || !baseUrl || !username || (!apiKey && !hasCredentials)}>
              {busy ? <CircularProgress size={20} /> : 'Test Connection'}
            </Button>
            <Button variant="contained" onClick={() => void save()} disabled={busy || !connectionReady || !projectId}>
              Save Connection
            </Button>
            {hasCredentials && <Button color="error" onClick={() => void remove()} disabled={busy}>Remove</Button>}
          </Stack>
          {hasCredentials && <>
            <Divider />
            <Box>
              <Typography variant="subtitle1">Automatic result publishing</Typography>
              <Typography variant="body2" color="text.secondary">
                When enabled, each completed VirtualPyTest campaign creates a TestRail run and sends mapped results in batches. Unmapped or incomplete cases are skipped and reported in Test Reports.
              </Typography>
              <FormControlLabel
                sx={{ mt: 1 }}
                control={<Switch checked={autoPublish} disabled={busy} onChange={(_event, checked) => void updateAutoPublish(checked)} />}
                label={autoPublish ? 'Auto-publish is on' : 'Auto-publish is off'}
              />
            </Box>
          </>}
          <Box sx={{ minHeight: 56, mt: 1 }}>
            {notice && <Alert severity={notice.kind}>{notice.text}</Alert>}
          </Box>
        </Stack>
      </CardContent></Card>
    </Box>
  );
};

export default TestRailIntegration;
