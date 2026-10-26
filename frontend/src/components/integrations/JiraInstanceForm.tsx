import { CheckCircle as CheckCircleIcon, Error as ErrorIcon } from '@mui/icons-material';
import { Alert, Box, Button, TextField } from '@mui/material';
import React, { useEffect, useState } from 'react';
import { APP_CONFIG } from '../../config/constants';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import IntegrationSwitchRow from './IntegrationSwitchRow';

export interface JiraInstance {
  id: string;
  name: string;
  domain: string;
  email: string;
  projectKey: string;
  /** Teams whose test-result defects may be pushed to this instance (server-enforced). */
  teamIds?: string[];
}

const EMPTY = { name: '', domain: '', email: '', apiToken: '', projectKey: '', allowTeamDefects: false };

interface Props {
  /** The instance being edited; null for a new one. */
  instance: JiraInstance | null;
  onSaved: () => void;
  onCancel?: () => void;
  /** Extra buttons next to Test connection / Save (the dialog's Cancel). */
  tokenHelper?: React.ReactNode;
}

/** Jira connection form: fields, write-only token, defects switch, Test connection and Save. */
const JiraInstanceForm: React.FC<Props> = ({ instance, onSaved, onCancel, tokenHelper }) => {
  const [formData, setFormData] = useState(EMPTY);
  const [testing, setTesting] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  useEffect(() => {
    setTestResult(null);
    setSaveError('');
    setFormData(instance ? {
      name: instance.name,
      domain: instance.domain,
      email: instance.email,
      apiToken: '',
      projectKey: instance.projectKey,
      allowTeamDefects: (instance.teamIds || []).includes(APP_CONFIG.DEFAULT_TEAM_ID),
    } : EMPTY);
  }, [instance]);

  const testConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const response = await fetch(buildServerUrl('/server/integrations/jira/test/test'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify((({ allowTeamDefects: _ignored, ...fields }) => fields)(formData)),
      });
      const data = await response.json();
      setTestResult(data.success
        ? { success: true, message: `Connected successfully as ${data.user}` }
        : { success: false, message: data.error || 'Connection failed' });
    } catch {
      setTestResult({ success: false, message: 'Connection test failed' });
    } finally {
      setTesting(false);
    }
  };

  const save = async () => {
    setSaveError('');
    try {
      // Only this team's membership is toggled; other teams bound to the instance are kept.
      const { allowTeamDefects, ...fields } = formData;
      const otherTeams = (instance?.teamIds || []).filter((t) => t !== APP_CONFIG.DEFAULT_TEAM_ID);
      const teamIds = allowTeamDefects ? [...otherTeams, APP_CONFIG.DEFAULT_TEAM_ID] : otherTeams;
      const payload = instance ? { ...fields, teamIds, id: instance.id } : { ...fields, teamIds };
      const response = await fetch(buildServerUrl('/server/integrations/jira/instances'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (data.success) onSaved();
      else setSaveError(data.error || 'Failed to save instance');
    } catch {
      setSaveError('Failed to save instance');
    }
  };

  const complete = formData.name && formData.domain && formData.email && formData.apiToken && formData.projectKey;
  const set = (key: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement>) => setFormData({ ...formData, [key]: e.target.value });

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <TextField label="Instance Name" fullWidth value={formData.name} onChange={set('name')} placeholder="My JIRA" />
      <TextField label="JIRA Domain" fullWidth value={formData.domain} onChange={set('domain')} placeholder="yourcompany.atlassian.net" helperText="Your JIRA domain (without https://)" />
      <TextField label="Email" fullWidth type="email" value={formData.email} onChange={set('email')} placeholder="your.email@company.com" />
      <TextField
        label="API Token" fullWidth type="password" autoComplete="new-password" value={formData.apiToken} onChange={set('apiToken')}
        helperText={tokenHelper ?? (instance ? 'Write-only. Type a token to replace the saved one.' : 'Write-only. Never shown again.')}
      />
      <TextField label="Project Key" fullWidth value={formData.projectKey} onChange={set('projectKey')} placeholder="PROJ" helperText="The project key (e.g., PROJ from PROJ-123)" />
      <IntegrationSwitchRow
        checked={formData.allowTeamDefects}
        onChange={(checked) => setFormData({ ...formData, allowTeamDefects: checked })}
        title="Allow defects to be pushed"
        description="This team's test-result defects may be pushed to this Jira project."
      />
      {testResult && (
        <Alert severity={testResult.success ? 'success' : 'error'} icon={testResult.success ? <CheckCircleIcon /> : <ErrorIcon />}>
          {testResult.message}
        </Alert>
      )}
      {saveError && <Alert severity="error">{saveError}</Alert>}
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
        <Button variant="outlined" onClick={testConnection} disabled={testing || !formData.domain || !formData.email || !formData.apiToken || !formData.projectKey}>
          {testing ? 'Testing...' : 'Test Connection'}
        </Button>
        <Button variant="contained" onClick={save} disabled={!complete}>Save</Button>
        {onCancel && <Button onClick={onCancel}>Cancel</Button>}
      </Box>
    </Box>
  );
};

export default JiraInstanceForm;
