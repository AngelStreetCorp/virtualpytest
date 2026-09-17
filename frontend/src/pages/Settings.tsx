import {
  Save as SaveIcon,
  Refresh as RefreshIcon,
  Storage as ServerIcon,
  Computer as HostIcon,
  Language as FrontendIcon,
  SmartToy as AIIcon,
  Add as AddIcon,
  Delete as DeleteIcon,
  ExpandMore as ExpandIcon,
  Palette as BrandingIcon,
  Upload as UploadIcon,
  RestartAlt as ResetIcon,
  Tune as FeaturesIcon,
  Visibility as VisibilityIcon,
  VisibilityOff as VisibilityOffIcon,
  AccountCircle as ProfileIcon,
  Logout as LogoutIcon,
} from '@mui/icons-material';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Button,
  TextField,
  Alert,
  Grid,
  Divider,
  CircularProgress,
  Tabs,
  Tab,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  IconButton,
  InputAdornment,
  MenuItem,
  Paper,
  Tooltip,
  Switch,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  Snackbar,
} from '@mui/material';
import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { useSettings, FrontendConfig } from '../hooks/pages';
import type { ServerConfig } from '../hooks/pages/useSettings';
import { useAuth } from '../hooks/auth/useAuth';
import { isAuthEnabled } from '../lib/supabase';
import { useBranding } from '../contexts/BrandingContext';
import { useResponsiveMode } from '../hooks/useResponsiveMode';
import { ALL_NAV_ITEMS } from '../config/navItems';
import { TOAST_POSITION, TOAST_AUTO_HIDE_DURATION } from '../constants/toastConfig';
import { buildServerUrl } from '../utils/buildUrlUtils';

// ─── Feature Visibility Tab ───────────────────────────────────────────────────
// Sources navbar items from the shared `navItems` config so toggle keys
// always match what the navbar uses at render time.

function parseNavSet(val: string | undefined): Set<string> {
  if (!val) return new Set();
  return new Set(val.split(',').map((s) => s.trim()).filter(Boolean));
}

function isNavPathVisible(path: string, frontend: FrontendConfig): boolean {
  return !parseNavSet(frontend.VITE_NAV_HIDDEN).has(path);
}

function toggleNavPathVisibility(
  path: string,
  visible: boolean,
  frontend: FrontendConfig,
  updateFrontendConfig: (field: keyof FrontendConfig, value: string) => void,
) {
  const hidden = parseNavSet(frontend.VITE_NAV_HIDDEN);
  if (visible) hidden.delete(path);
  else hidden.add(path);
  updateFrontendConfig('VITE_NAV_HIDDEN', [...hidden].join(','));
}

const settingsPanelSx = {
  minHeight: 360,
};

interface AiProviderOption {
  value: string;
  label: string;
  apiKeyField: keyof ServerConfig;
  placeholder: string;
  // Field whose non-empty value makes the provider selectable. Defaults to apiKeyField;
  // the local provider is enabled by its base URL, the key being optional.
  enabledField?: keyof ServerConfig;
}

const LOCAL_PROVIDER = 'local';

const AI_PROVIDER_OPTIONS: readonly AiProviderOption[] = [
  { value: 'openrouter', label: 'OpenRouter', apiKeyField: 'OPENROUTER_API_KEY', placeholder: 'sk-or-v1-...' },
  { value: 'anthropic', label: 'Anthropic', apiKeyField: 'ANTHROPIC_API_KEY', placeholder: 'sk-ant-...' },
  { value: 'openai', label: 'OpenAI', apiKeyField: 'OPENAI_API_KEY', placeholder: 'sk-...' },
  { value: 'minimax', label: 'MiniMax', apiKeyField: 'MINIMAX_API_KEY', placeholder: 'your-minimax-key' },
  { value: 'google', label: 'Google', apiKeyField: 'GOOGLE_API_KEY', placeholder: 'your-google-api-key' },
  {
    value: LOCAL_PROVIDER,
    label: 'Local (OpenAI-compatible)',
    apiKeyField: 'LOCAL_AI_API_KEY',
    placeholder: 'optional — only if the server requires one',
    enabledField: 'LOCAL_AI_BASE_URL',
  },
];

const SettingsTabPanel: React.FC<React.PropsWithChildren<{ active: boolean }>> = ({ active, children }) => (
  <Box
    role="tabpanel"
    hidden={!active}
    sx={{
      mt: 0,
      display: active ? 'block' : 'none',
      ...settingsPanelSx,
    }}
  >
    {children}
  </Box>
);

// Per-task model configuration. Each task resolves to its own provider+model,
// falling back to the primary provider (AI_PROVIDER) when left blank.
const AI_TASKS = [
  {
    key: 'agent',
    short: 'Agent',
    label: 'Agent — chat & tools (Atlas)',
    providerField: 'AI_AGENT_PROVIDER' as keyof ServerConfig,
    modelField: 'AI_AGENT_MODEL' as keyof ServerConfig,
  },
  {
    key: 'vision',
    short: 'Vision',
    label: 'Vision — subtitle / banner / screen detection',
    providerField: 'AI_VISION_PROVIDER' as keyof ServerConfig,
    modelField: 'AI_VISION_MODEL' as keyof ServerConfig,
  },
  {
    key: 'text',
    short: 'Text',
    label: 'Text — translation / analysis',
    providerField: 'AI_TEXT_PROVIDER' as keyof ServerConfig,
    modelField: 'AI_TEXT_MODEL' as keyof ServerConfig,
  },
] as const;

type ProviderModelMatrix = Record<string, Record<string, string | null>>;

// Per-task fallback when no provider is configured (mirrors backend DEFAULT_PROVIDER_BY_TASK).
const DEFAULT_PROVIDER_BY_TASK: Record<string, string> = {
  agent: 'anthropic',
  vision: 'openrouter',
  text: 'openrouter',
};

const AISettingsTab: React.FC<{
  serverConfig: ServerConfig;
  updateServerConfig: (field: keyof ServerConfig, value: string) => void;
}> = ({ serverConfig, updateServerConfig }) => {
  const [matrix, setMatrix] = useState<ProviderModelMatrix>({});
  const [shownKeys, setShownKeys] = useState<Record<string, boolean>>({});
  const toggleKey = (field: string) => setShownKeys((prev) => ({ ...prev, [field]: !prev[field] }));

  // Load the per-provider × per-task default model matrix from the backend.
  useEffect(() => {
    fetch(buildServerUrl('/server/agent/models'))
      .then((r) => r.json())
      .then((d) => {
        if (d?.success && d.provider_models) setMatrix(d.provider_models as ProviderModelMatrix);
      })
      .catch(() => undefined);
  }, []);

  // Only providers with a filled API key (or, for local, a base URL) can be selected.
  const availableProviders = AI_PROVIDER_OPTIONS.filter(
    (option) => !!(serverConfig[option.enabledField ?? option.apiKeyField] as string)?.trim(),
  );

  const primary = (serverConfig.AI_PROVIDER || '').trim();

  // The local provider's model is whatever the operator typed (unsaved edits included);
  // the backend matrix only knows it after a save.
  const localModel = (serverConfig.LOCAL_AI_MODEL || '').trim() || null;

  const defaultModelFor = (provider: string, task: string): string | null =>
    provider === LOCAL_PROVIDER ? localModel : (matrix[provider]?.[task] ?? null);

  // Whether a provider can serve a task (matrix not yet loaded → assume yes).
  const taskCapable = (provider: string, task: string): boolean => {
    if (provider === LOCAL_PROVIDER) return localModel !== null;
    return matrix[provider] === undefined ? true : matrix[provider][task] != null;
  };

  // Resolve the provider a task will actually use (mirrors backend resolution):
  // explicit task provider -> primary (if it can serve the task) -> per-task default.
  const effectiveProvider = (task: string, taskProvider: string): string => {
    if (taskProvider) return taskProvider;
    if (primary && taskCapable(primary, task)) return primary;
    return DEFAULT_PROVIDER_BY_TASK[task] || 'anthropic';
  };

  const providerLabel = (value: string): string =>
    AI_PROVIDER_OPTIONS.find((o) => o.value === value)?.label || value;

  return (
    <Card>
      <CardContent sx={{ '& .MuiTextField-root': { mt: 0 } }}>
        <Box display="flex" alignItems="center" mb={0.5}>
          <AIIcon sx={{ mr: 1 }} color="primary" />
          <Typography variant="h6">AI Provider Configuration</Typography>
        </Box>
        <Typography variant="caption" color="text.secondary">
          Every field has a working default — nothing is required. Set a provider only to override.
        </Typography>
        <Divider sx={{ my: 1.5 }} />

        {/* Primary provider */}
        <Box display="flex" alignItems="center" gap={1.5} mb={1.5}>
          <Typography variant="body2" sx={{ minWidth: 110, color: 'text.secondary' }}>
            Primary
          </Typography>
          <TextField
            value={availableProviders.some((o) => o.value === primary) ? primary : ''}
            onChange={(e) => updateServerConfig('AI_PROVIDER', e.target.value)}
            size="small"
            select
            sx={{ width: 220 }}
            disabled={availableProviders.length === 0}
            SelectProps={{ displayEmpty: true }}
          >
            <MenuItem value="">
              <em>Per-task defaults</em>
            </MenuItem>
            {availableProviders.map((option) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </TextField>
          <Typography variant="caption" color="text.secondary">
            {availableProviders.length === 0
              ? 'Add an API key below to enable.'
              : 'Applied to any task that can use it.'}
          </Typography>
        </Box>

        {/* Per-task rows: label | provider | model (compact, one row each) */}
        {AI_TASKS.map((task) => {
          const taskProvider = (serverConfig[task.providerField] as string) || '';
          const resolvedProvider = effectiveProvider(task.key, taskProvider);
          const defaultModel = defaultModelFor(resolvedProvider, task.key);
          const noModel =
            resolvedProvider === LOCAL_PROVIDER
              ? defaultModel === null && !(serverConfig[task.modelField] as string)?.trim()
              : matrix[resolvedProvider] !== undefined && defaultModel === null;
          return (
            <Box key={task.key} display="flex" alignItems="center" gap={1.5} mb={1}>
              <Tooltip title={task.label}>
                <Typography variant="body2" noWrap sx={{ minWidth: 110, color: 'text.secondary' }}>
                  {task.short}
                </Typography>
              </Tooltip>
              <TextField
                value={availableProviders.some((o) => o.value === taskProvider) ? taskProvider : ''}
                onChange={(e) => updateServerConfig(task.providerField, e.target.value)}
                size="small"
                select
                sx={{ width: 220 }}
                disabled={availableProviders.length === 0}
                SelectProps={{ displayEmpty: true }}
              >
                <MenuItem value="">
                  <em>{`Default (${providerLabel(resolvedProvider)})`}</em>
                </MenuItem>
                {availableProviders.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                value={(serverConfig[task.modelField] as string) || defaultModel || ''}
                onChange={(e) => updateServerConfig(task.modelField, e.target.value)}
                placeholder={defaultModel || `${resolvedProvider} default`}
                size="small"
                error={noModel}
                helperText={noModel ? `⚠️ ${resolvedProvider} has no ${task.key} model` : undefined}
                sx={{ flex: 1, minWidth: 200 }}
              />
            </Box>
          );
        })}

        {/* API keys (one per provider, shared across tasks) */}
        <Divider sx={{ my: 1.5 }} />
        <Typography variant="body2" sx={{ mb: 1, color: 'text.secondary' }}>
          Provider API keys
        </Typography>
        <Grid container spacing={1.5}>
          {AI_PROVIDER_OPTIONS.filter((option) => option.value !== LOCAL_PROVIDER).map((option) => {
            const shown = !!shownKeys[option.apiKeyField];
            return (
              <Grid item xs={12} sm={6} md={4} key={option.value}>
                <TextField
                  label={option.label}
                  value={serverConfig[option.apiKeyField] || ''}
                  onChange={(e) => updateServerConfig(option.apiKeyField, e.target.value)}
                  placeholder={option.placeholder}
                  fullWidth
                  size="small"
                  type={shown ? 'text' : 'password'}
                  InputProps={{
                    endAdornment: (
                      <InputAdornment position="end">
                        <IconButton
                          aria-label={shown ? 'Hide key' : 'Show key'}
                          onClick={() => toggleKey(option.apiKeyField)}
                          edge="end"
                          size="small"
                          tabIndex={-1}
                        >
                          {shown ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}
                        </IconButton>
                      </InputAdornment>
                    ),
                  }}
                />
              </Grid>
            );
          })}
        </Grid>

        {/* Local OpenAI-compatible server (Ollama, vLLM, llama.cpp, LM Studio...) */}
        <Divider sx={{ my: 1.5 }} />
        <Typography variant="body2" sx={{ color: 'text.secondary' }}>
          Local model server
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
          Any OpenAI-compatible endpoint on your network. Set the URL and a model name to enable the
          &quot;Local&quot; provider above. No key needed unless the server enforces one.
        </Typography>
        <Grid container spacing={1.5}>
          <Grid item xs={12} sm={6} md={5}>
            <TextField
              label="Base URL"
              value={serverConfig.LOCAL_AI_BASE_URL || ''}
              onChange={(e) => updateServerConfig('LOCAL_AI_BASE_URL', e.target.value)}
              placeholder="http://10.10.10.10:8000/v1"
              fullWidth
              size="small"
            />
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <TextField
              label="Model"
              value={serverConfig.LOCAL_AI_MODEL || ''}
              onChange={(e) => updateServerConfig('LOCAL_AI_MODEL', e.target.value)}
              placeholder="qwen3:8b"
              fullWidth
              size="small"
            />
          </Grid>
          <Grid item xs={12} sm={6} md={4}>
            <TextField
              label="API key (optional)"
              value={serverConfig.LOCAL_AI_API_KEY || ''}
              onChange={(e) => updateServerConfig('LOCAL_AI_API_KEY', e.target.value)}
              placeholder="only if the server requires one"
              fullWidth
              size="small"
              type={shownKeys.LOCAL_AI_API_KEY ? 'text' : 'password'}
              InputProps={{
                endAdornment: (
                  <InputAdornment position="end">
                    <IconButton
                      aria-label={shownKeys.LOCAL_AI_API_KEY ? 'Hide key' : 'Show key'}
                      onClick={() => toggleKey('LOCAL_AI_API_KEY')}
                      edge="end"
                      size="small"
                      tabIndex={-1}
                    >
                      {shownKeys.LOCAL_AI_API_KEY ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}
                    </IconButton>
                  </InputAdornment>
                ),
              }}
            />
          </Grid>
        </Grid>
      </CardContent>
    </Card>
  );
};

// ─── Branding Tab ─────────────────────────────────────────────────────────────

const BrandingTab: React.FC = () => {
  const { branding, setBranding, resetBranding, isLoaded, hasBackup } = useBranding();
  const [name, setName] = useState(branding.name);
  const [tagline, setTagline] = useState(branding.tagline);
  const [logoUrl, setLogoUrl] = useState(branding.logoUrl);
  const [faviconUrl, setFaviconUrl] = useState(branding.faviconUrl);
  const [saving, setSaving] = useState(false);
  const [reverting, setReverting] = useState(false);
  const [saved, setSaved] = useState(false);

  const logoInputRef = useRef<HTMLInputElement>(null);
  const faviconInputRef = useRef<HTMLInputElement>(null);

  // Sync form fields once API-loaded branding arrives
  useEffect(() => {
    if (isLoaded) {
      setName(branding.name);
      setTagline(branding.tagline);
      setLogoUrl(branding.logoUrl);
      setFaviconUrl(branding.faviconUrl);
    }
  }, [isLoaded]);

  const uploadAsset = async (file: File, asset: 'logo' | 'favicon'): Promise<string> => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('asset', asset);
    const res = await fetch(buildServerUrl('/server/branding/upload'), {
      method: 'POST',
      body: formData,
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || 'Upload failed');
    return data.url as string;
  };

  const handleLogoFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setLogoUrl(await uploadAsset(file, 'logo'));
    } catch (err) {
      console.error('Logo upload failed:', err);
    }
  };

  const handleFaviconFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setFaviconUrl(await uploadAsset(file, 'favicon'));
    } catch (err) {
      console.error('Favicon upload failed:', err);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    await setBranding({ name, tagline, logoUrl, faviconUrl });
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 4000);
  };

  const handleRevert = async () => {
    setReverting(true);
    await resetBranding();
    setReverting(false);
  };

  return (
    <Card>
      <CardContent>
        <Box display="flex" alignItems="center" mb={1}>
          <BrandingIcon sx={{ mr: 1 }} color="primary" />
          <Typography variant="h6">Branding</Typography>
          {hasBackup && (
            <Tooltip title="Revert to previous branding (restore backup)">
              <span>
                <Button
                  size="small"
                  variant="outlined"
                  color="warning"
                  startIcon={reverting ? <CircularProgress size={14} /> : <ResetIcon fontSize="small" />}
                  onClick={handleRevert}
                  disabled={reverting}
                  sx={{ ml: 'auto' }}
                >
                  Revert to backup
                </Button>
              </span>
            </Tooltip>
          )}
        </Box>
        <Divider sx={{ mb: 2 }} />

        {saved && (
          <Alert severity="success" sx={{ mb: 2 }}>
            Branding saved to server — applies immediately across all browsers.
          </Alert>
        )}

        <Grid container spacing={2}>
          {/* Name & Tagline */}
          <Grid item xs={12} md={6}>
            <TextField
              label="App Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              fullWidth
              size="small"
              helperText="Shown in the header and browser tab"
            />
          </Grid>
          <Grid item xs={12} md={6}>
            <TextField
              label="Tagline"
              value={tagline}
              onChange={(e) => setTagline(e.target.value)}
              fullWidth
              size="small"
              helperText="Short description shown in the footer"
            />
          </Grid>

          {/* Logo */}
          <Grid item xs={12}>
            <Typography variant="subtitle2" gutterBottom sx={{ mt: 1 }}>
              Logo
            </Typography>
            <Box display="flex" alignItems="center" gap={2} flexWrap="wrap">
              <TextField
                label="Logo URL"
                value={logoUrl}
                onChange={(e) => setLogoUrl(e.target.value)}
                size="small"
                placeholder="/logo.png"
                sx={{ flex: 1, minWidth: 260 }}
                helperText="Upload a file (saved to public/) or paste an external URL"
              />
              <Button
                variant="outlined"
                size="small"
                startIcon={<UploadIcon />}
                onClick={() => logoInputRef.current?.click()}
              >
                Upload
              </Button>
              <input
                ref={logoInputRef}
                type="file"
                accept="image/*"
                hidden
                onChange={handleLogoFile}
              />
              {logoUrl && (
                <Paper variant="outlined" sx={{ p: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', height: 48, minWidth: 120 }}>
                  <Box
                    component="img"
                    src={logoUrl}
                    alt="logo preview"
                    sx={{ maxHeight: 36, maxWidth: 160, objectFit: 'contain' }}
                    onError={(e: React.SyntheticEvent<HTMLImageElement>) => { e.currentTarget.style.display = 'none'; }}
                  />
                </Paper>
              )}
            </Box>
          </Grid>

          {/* Favicon */}
          <Grid item xs={12}>
            <Typography variant="subtitle2" gutterBottom sx={{ mt: 1 }}>
              Favicon
            </Typography>
            <Box display="flex" alignItems="center" gap={2} flexWrap="wrap">
              <TextField
                label="Favicon URL"
                value={faviconUrl}
                onChange={(e) => setFaviconUrl(e.target.value)}
                size="small"
                placeholder="/favicon.ico"
                sx={{ flex: 1, minWidth: 260 }}
                helperText="Upload a file (saved to public/) or paste an external URL. 32×32 or 64×64 recommended"
              />
              <Button
                variant="outlined"
                size="small"
                startIcon={<UploadIcon />}
                onClick={() => faviconInputRef.current?.click()}
              >
                Upload
              </Button>
              <input
                ref={faviconInputRef}
                type="file"
                accept="image/x-icon,image/png,image/svg+xml"
                hidden
                onChange={handleFaviconFile}
              />
              {faviconUrl && (
                <Paper variant="outlined" sx={{ p: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', height: 48, width: 48 }}>
                  <Box
                    component="img"
                    src={faviconUrl}
                    alt="favicon preview"
                    sx={{ width: 32, height: 32, objectFit: 'contain' }}
                    onError={(e: React.SyntheticEvent<HTMLImageElement>) => { e.currentTarget.style.display = 'none'; }}
                  />
                </Paper>
              )}
            </Box>
          </Grid>

          {/* Live preview */}
          <Grid item xs={12}>
            <Typography variant="subtitle2" gutterBottom sx={{ mt: 1 }}>
              Header Preview
            </Typography>
            <Paper
              variant="outlined"
              sx={{ p: 1.5, display: 'flex', alignItems: 'center', gap: 1, backgroundColor: 'primary.main', borderRadius: 1 }}
            >
              {logoUrl ? (
                <Box
                  component="img"
                  src={logoUrl}
                  alt="logo"
                  sx={{ height: 28, width: 'auto', maxWidth: 140, objectFit: 'contain' }}
                  onError={(e: React.SyntheticEvent<HTMLImageElement>) => { e.currentTarget.style.display = 'none'; }}
                />
              ) : null}
              <Typography variant="h6" sx={{ color: 'primary.contrastText', fontWeight: 600 }}>
                {name || 'App Name'}
              </Typography>
            </Paper>
          </Grid>
        </Grid>

        <Box display="flex" justifyContent="flex-end" mt={3}>
          <Button
            variant="contained"
            startIcon={saving ? <CircularProgress size={18} /> : <SaveIcon />}
            onClick={handleSave}
            disabled={saving}
          >
            Save Branding
          </Button>
        </Box>
      </CardContent>
    </Card>
  );
};

// ─── Main Settings Page ────────────────────────────────────────────────────────

const Settings: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTab = searchParams.get('tab') === 'ai' ? 1 : 0;
  const [activeTab, setActiveTab] = useState(initialTab);
  const navigate = useNavigate();
  const { isMobile } = useResponsiveMode();
  const { user, signOut } = useAuth();
  const [signingOut, setSigningOut] = useState(false);
  const handleSignOut = async () => {
    setSigningOut(true);
    try {
      await signOut();
      navigate('/login');
    } finally {
      setSigningOut(false);
    }
  };

  const {
    config,
    loading,
    saving,
    error,
    success,
    loadConfig,
    saveConfig,
    updateServerConfig,
    updateFrontendConfig,
    updateHostConfig,
    updateDeviceConfig,
    addDevice,
    deleteDevice,
    setError,
    setSuccess,
  } = useSettings();

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  useEffect(() => {
    if (searchParams.get('tab') === 'ai' && activeTab !== 1) {
      setActiveTab(1);
    }
  }, [activeTab, searchParams]);

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Box sx={{ mb: 0, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Box>
          <Typography variant="h4" gutterBottom>
            System Settings
          </Typography>
        </Box>
        <Box display="flex" gap={1}>
          <Button variant="outlined" startIcon={<RefreshIcon />} onClick={loadConfig}>
            Refresh
          </Button>
          <Button
            variant="contained"
            startIcon={saving ? <CircularProgress size={20} /> : <SaveIcon />}
            onClick={saveConfig}
            disabled={saving}
          >
            Save
          </Button>
        </Box>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Snackbar
        open={success}
        autoHideDuration={TOAST_AUTO_HIDE_DURATION.success}
        onClose={() => setSuccess(false)}
        anchorOrigin={TOAST_POSITION.anchorOrigin}
        sx={TOAST_POSITION.sx}
      >
        <Alert severity="success" onClose={() => setSuccess(false)}>
          Saved successfully
        </Alert>
      </Snackbar>

      <Tabs
        value={activeTab}
        onChange={(_, newValue) => {
          setActiveTab(newValue);
          setSearchParams(newValue === 1 ? { tab: 'ai' } : {});
        }}
        variant="scrollable"
        scrollButtons="auto"
        allowScrollButtonsMobile
        sx={{ mb: 1 }}
      >
        <Tab icon={<ServerIcon />} label="Backend Server" iconPosition="start" />
        <Tab icon={<AIIcon />} label="AI" iconPosition="start" />
        <Tab icon={<FrontendIcon />} label="Frontend" iconPosition="start" />
        <Tab icon={<HostIcon />} label="Host & Devices" iconPosition="start" />
        <Tab icon={<BrandingIcon />} label="Branding" iconPosition="start" />
        <Tab icon={<FeaturesIcon />} label="Features" iconPosition="start" />
        {isAuthEnabled && user && (
          <Tab icon={<ProfileIcon />} label="Profile" iconPosition="start" />
        )}
      </Tabs>

      {/* Tab 1: Backend Server */}
      <SettingsTabPanel active={activeTab === 0}>
        <Card>
          <CardContent>
            <Box display="flex" alignItems="center" mb={1}>
              <ServerIcon sx={{ mr: 1 }} color="primary" />
              <Typography variant="h6">Backend Server Configuration</Typography>
            </Box>
            <Divider sx={{ mb: 2 }} />

            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <TextField
                  label="Server Name"
                  value={config.server.SERVER_NAME}
                  onChange={(e) => updateServerConfig('SERVER_NAME', e.target.value)}
                  placeholder="Awesomation"
                  fullWidth
                  size="small"
                  helperText="Display name for this server"
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <TextField
                  label="Server URL"
                  value={config.server.SERVER_URL}
                  onChange={(e) => updateServerConfig('SERVER_URL', e.target.value)}
                  placeholder="http://localhost:5109"
                  fullWidth
                  size="small"
                  helperText="Base URL for the backend server"
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <TextField
                  label="Server Port"
                  value={config.server.SERVER_PORT}
                  onChange={(e) => updateServerConfig('SERVER_PORT', e.target.value)}
                  placeholder="5109"
                  fullWidth
                  size="small"
                  type="number"
                  helperText="Port for the backend server API"
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <TextField
                  label="Environment"
                  value={config.server.ENVIRONMENT}
                  onChange={(e) => updateServerConfig('ENVIRONMENT', e.target.value)}
                  fullWidth
                  size="small"
                  select
                  helperText="Current environment mode"
                >
                  <MenuItem value="development">Development</MenuItem>
                  <MenuItem value="staging">Staging</MenuItem>
                  <MenuItem value="production">Production</MenuItem>
                </TextField>
              </Grid>
             
             
            </Grid>
          </CardContent>
        </Card>
      </SettingsTabPanel>

      {/* Tab 2: AI */}
      <SettingsTabPanel active={activeTab === 1}>
        <AISettingsTab
          serverConfig={config.server}
          updateServerConfig={updateServerConfig}
        />
      </SettingsTabPanel>

      {/* Tab 3: Frontend */}
      <SettingsTabPanel active={activeTab === 2}>
        <Card>
          <CardContent>
            <Box display="flex" alignItems="center" mb={1}>
              <FrontendIcon sx={{ mr: 1 }} color="primary" />
              <Typography variant="h6">Frontend Configuration</Typography>
            </Box>
            <Divider sx={{ mb: 2 }} />

            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <TextField
                  label="Server URL"
                  value={config.frontend.VITE_SERVER_URL}
                  onChange={(e) => updateFrontendConfig('VITE_SERVER_URL', e.target.value)}
                  placeholder="http://localhost:5109"
                  fullWidth
                  size="small"
                  helperText="Backend server URL for API calls"
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <TextField
                  label="Slave Server URLs"
                  value={config.frontend.VITE_SLAVE_SERVER_URL}
                  onChange={(e) => updateFrontendConfig('VITE_SLAVE_SERVER_URL', e.target.value)}
                  placeholder="[]"
                  fullWidth
                  size="small"
                  helperText="JSON array of additional server URLs"
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <TextField
                  label="Grafana URL"
                  value={config.frontend.VITE_GRAFANA_URL}
                  onChange={(e) => updateFrontendConfig('VITE_GRAFANA_URL', e.target.value)}
                  placeholder="http://localhost:3000"
                  fullWidth
                  size="small"
                  helperText="Grafana dashboard URL"
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <TextField
                  label="R2 Public URL"
                  value={config.frontend.VITE_CLOUDFLARE_R2_PUBLIC_URL}
                  onChange={(e) =>
                    updateFrontendConfig('VITE_CLOUDFLARE_R2_PUBLIC_URL', e.target.value)
                  }
                  placeholder="https://pub-..."
                  fullWidth
                  size="small"
                  helperText="Cloudflare R2 public URL for assets"
                />
              </Grid>
            </Grid>

          </CardContent>
        </Card>
      </SettingsTabPanel>

      {/* Tab 5: Branding */}
      <SettingsTabPanel active={activeTab === 4}>
        <BrandingTab />
      </SettingsTabPanel>

      {/* Tab 6: Features */}
      <SettingsTabPanel active={activeTab === 5}>
        <Card>
          <CardContent sx={{ p: 0, '&:last-child': { pb: 0 } }}>
            {/* Feature Toggles */}
            <Box display="flex" alignItems="center" p={2} pb={1}>
              <FeaturesIcon sx={{ mr: 1 }} color="primary" />
              <Typography variant="h6">Feature Toggles</Typography>
            </Box>
            <Divider />
            <Table size="small" sx={{ tableLayout: 'fixed', width: '100%' }}>
              <TableBody>
                <TableRow sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
                  <TableCell sx={{ width: 'calc(100% - 90px)' }}>
                    <Typography variant="body2" fontWeight={500}>Periodic Deployments</Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', whiteSpace: 'nowrap' }}>
                      Enable periodic test execution. Requires frontend rebuild.
                    </Typography>
                  </TableCell>
                  <TableCell align="center" sx={{ width: 90 }}>
                    <Switch
                      size="small"
                      checked={config.frontend.VITE_FEATURE_DEPLOYMENTS !== 'false'}
                      onChange={(e) =>
                        updateFrontendConfig('VITE_FEATURE_DEPLOYMENTS', e.target.checked ? 'true' : 'false')
                      }
                    />
                  </TableCell>
                </TableRow>
                <TableRow sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
                  <TableCell sx={{ width: 'calc(100% - 90px)' }}>
                    <Typography variant="body2" fontWeight={500}>Run Version Selector</Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', whiteSpace: 'nowrap' }}>
                      Show version dropdowns on Run Tests and Run Campaign. Requires frontend rebuild.
                    </Typography>
                  </TableCell>
                  <TableCell align="center" sx={{ width: 90 }}>
                    <Switch
                      size="small"
                      checked={config.frontend.VITE_FEATURE_RUN_VERSION_SELECTOR === 'true'}
                      onChange={(e) =>
                        updateFrontendConfig('VITE_FEATURE_RUN_VERSION_SELECTOR', e.target.checked ? 'true' : 'false')
                      }
                    />
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
            <Divider sx={{ mt: 1 }} />

            {/* Navbar Visibility */}
            <Box display="flex" alignItems="center" p={2} pb={1}>
              <FeaturesIcon sx={{ mr: 1 }} color="primary" />
              <Typography variant="h6">Navbar Visibility</Typography>
              <Typography variant="body2" color="textSecondary" sx={{ ml: 2 }}>
                Toggle navbar items on/off. Hidden items are removed from the navbar and require a frontend rebuild.
              </Typography>
            </Box>
            <Divider />
            <Table size="small">
              <TableHead>
                <TableRow sx={{ '&:hover': { backgroundColor: 'transparent !important' } }}>
                  <TableCell sx={{ fontWeight: 600, width: '25%' }}>Item</TableCell>
                  <TableCell sx={{ fontWeight: 600, width: '20%' }}>Section</TableCell>
                  <TableCell sx={{ fontWeight: 600, fontFamily: 'monospace' }}>Path</TableCell>
                  <TableCell align="center" sx={{ fontWeight: 600, width: 90 }}>Visible</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {ALL_NAV_ITEMS.map(({ label, section, path }) => {
                  const visible = isNavPathVisible(path, config.frontend);
                  return (
                    <TableRow
                      key={`${section}-${path}`}
                      sx={{
                        opacity: visible ? 1 : 0.45,
                        '&:last-child td': { border: 0 },
                        '&:hover': { backgroundColor: 'transparent !important' },
                      }}
                    >
                      <TableCell>
                        <Typography variant="body2" fontWeight={visible ? 500 : 400}>
                          {label}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="caption" color="text.secondary">
                          {section}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography
                          variant="caption"
                          sx={{ fontFamily: 'monospace', color: 'text.secondary' }}
                        >
                          {path}
                        </Typography>
                      </TableCell>
                      <TableCell align="center">
                        <Switch
                          size="small"
                          checked={visible}
                          onChange={(e) =>
                            toggleNavPathVisibility(
                              path,
                              e.target.checked,
                              config.frontend,
                              updateFrontendConfig,
                            )
                          }
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </SettingsTabPanel>

      {/* Tab 4: Host & Devices */}
      <SettingsTabPanel active={activeTab === 3}>
        <Box>
          <Card sx={{ mb: 1}}>
            <CardContent>
              <Box display="flex" alignItems="center" mb={1}>
                <HostIcon sx={{ mr: 1 }} color="primary" />
                <Typography variant="h6">Host Configuration</Typography>
              </Box>
              <Divider sx={{ mb: 2 }} />

              <Grid container spacing={2}>
                <Grid item xs={12} md={6}>
                  <TextField
                    label="Host Name"
                    value={config.host.HOST_NAME}
                    onChange={(e) => updateHostConfig('HOST_NAME', e.target.value)}
                    placeholder="host1"
                    fullWidth
                    size="small"
                    helperText="Unique identifier for this host"
                  />
                </Grid>
                <Grid item xs={12} md={6}>
                  <TextField
                    label="Host Port"
                    value={config.host.HOST_PORT}
                    onChange={(e) => updateHostConfig('HOST_PORT', e.target.value)}
                    placeholder="6109"
                    fullWidth
                    size="small"
                    type="number"
                    helperText="Port for the host service"
                  />
                </Grid>
                <Grid item xs={12} md={6}>
                  <TextField
                    label="Host URL"
                    value={config.host.HOST_URL}
                    onChange={(e) => updateHostConfig('HOST_URL', e.target.value)}
                    placeholder="http://localhost:6109"
                    fullWidth
                    size="small"
                    helperText="Base URL for the host service"
                  />
                </Grid>
                <Grid item xs={12} md={6}>
                  <TextField
                    label="Host API URL"
                    value={config.host.HOST_API_URL}
                    onChange={(e) => updateHostConfig('HOST_API_URL', e.target.value)}
                    placeholder="http://localhost:6109"
                    fullWidth
                    size="small"
                    helperText="API endpoint URL for the host"
                  />
                </Grid>
              </Grid>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <Box display="flex" alignItems="center" justifyContent="space-between" mb={1}>
                <Typography variant="h6">Device Configuration</Typography>
                <Button variant="contained" size="small" startIcon={<AddIcon />} onClick={addDevice}>
                  Add Device
                </Button>
              </Box>
              <Divider sx={{ mb: 0 }} />

              {Object.keys(config.devices).length === 0 && (
                <Alert severity="info">
                  No devices configured. Click "Add Device" to add a new device configuration.
                </Alert>
              )}

              {Object.entries(config.devices).map(([deviceKey, device]) => (
                <Accordion key={deviceKey} defaultExpanded={Object.keys(config.devices).length === 1}>
                  <AccordionSummary
                    sx={{
                      '&.Mui-expanded .device-expand-chevron': { transform: 'rotate(180deg)' },
                    }}
                  >
                    <Box display="flex" alignItems="center" justifyContent="space-between" width="100%" mr={2}>
                      <Typography>
                        {deviceKey}: {device.DEVICE_NAME || 'Unnamed Device'}
                      </Typography>
                      <Box display="flex" alignItems="center" gap={0.5}>
                        <ExpandIcon
                          className="device-expand-chevron"
                          fontSize="small"
                          sx={{ transition: 'transform 0.2s', color: 'action.active' }}
                        />
                        <IconButton
                          size="small"
                          onClick={(e) => {
                            e.stopPropagation();
                            deleteDevice(deviceKey);
                          }}
                          color="error"
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Box>
                    </Box>
                  </AccordionSummary>
                  <AccordionDetails>
                    <Grid container spacing={1}>
                      <Grid item xs={12}>
                        <Typography variant="subtitle2" color="primary" gutterBottom>
                          Basic Information
                        </Typography>
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <TextField
                          label="Device Name"
                          value={device.DEVICE_NAME}
                          onChange={(e) => updateDeviceConfig(deviceKey, 'DEVICE_NAME', e.target.value)}
                          placeholder="S21x"
                          fullWidth
                          size="small"
                        />
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <TextField
                          label="Device Model"
                          value={device.DEVICE_MODEL}
                          onChange={(e) => updateDeviceConfig(deviceKey, 'DEVICE_MODEL', e.target.value)}
                          placeholder="android_mobile"
                          fullWidth
                          size="small"
                        />
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <TextField
                          label="IP Address"
                          value={device.DEVICE_IP}
                          onChange={(e) => updateDeviceConfig(deviceKey, 'DEVICE_IP', e.target.value)}
                          placeholder="192.168.1.124"
                          fullWidth
                          size="small"
                        />
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <TextField
                          label="Port"
                          value={device.DEVICE_PORT}
                          onChange={(e) => updateDeviceConfig(deviceKey, 'DEVICE_PORT', e.target.value)}
                          placeholder="5555"
                          fullWidth
                          size="small"
                        />
                      </Grid>

                      <Grid item xs={12}>
                        <Typography variant="subtitle2" color="primary" gutterBottom>
                          Video Configuration
                        </Typography>
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <TextField
                          label="Video Device"
                          value={device.DEVICE_VIDEO}
                          onChange={(e) => updateDeviceConfig(deviceKey, 'DEVICE_VIDEO', e.target.value)}
                          placeholder="/dev/video0"
                          fullWidth
                          size="small"
                        />
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <TextField
                          label="Audio Device"
                          value={device.DEVICE_VIDEO_AUDIO}
                          onChange={(e) =>
                            updateDeviceConfig(deviceKey, 'DEVICE_VIDEO_AUDIO', e.target.value)
                          }
                          placeholder="plughw:2,0"
                          fullWidth
                          size="small"
                        />
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <TextField
                          label="FPS"
                          value={device.DEVICE_VIDEO_FPS}
                          onChange={(e) => updateDeviceConfig(deviceKey, 'DEVICE_VIDEO_FPS', e.target.value)}
                          placeholder="10"
                          fullWidth
                          size="small"
                          type="number"
                        />
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <TextField
                          label="Stream Path"
                          value={device.DEVICE_VIDEO_STREAM_PATH}
                          onChange={(e) =>
                            updateDeviceConfig(deviceKey, 'DEVICE_VIDEO_STREAM_PATH', e.target.value)
                          }
                          placeholder="/host/stream/capture1"
                          fullWidth
                          size="small"
                        />
                      </Grid>
                      <Grid item xs={12}>
                        <TextField
                          label="Capture Path"
                          value={device.DEVICE_VIDEO_CAPTURE_PATH}
                          onChange={(e) =>
                            updateDeviceConfig(deviceKey, 'DEVICE_VIDEO_CAPTURE_PATH', e.target.value)
                          }
                          placeholder="/var/www/html/stream/capture1"
                          fullWidth
                          size="small"
                        />
                      </Grid>

                      <Grid item xs={12}>
                        <Typography variant="subtitle2" color="primary" gutterBottom>
                          Power Control
                        </Typography>
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <TextField
                          label="Power Device Name"
                          value={device.DEVICE_POWER_NAME}
                          onChange={(e) =>
                            updateDeviceConfig(deviceKey, 'DEVICE_POWER_NAME', e.target.value)
                          }
                          placeholder="TAPO_P100_EOS"
                          fullWidth
                          size="small"
                        />
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <TextField
                          label="Power Device IP"
                          value={device.DEVICE_POWER_IP}
                          onChange={(e) =>
                            updateDeviceConfig(deviceKey, 'DEVICE_POWER_IP', e.target.value)
                          }
                          placeholder="192.168.1.220"
                          fullWidth
                          size="small"
                        />
                      </Grid>
                     
                    </Grid>
                  </AccordionDetails>
                </Accordion>
              ))}
            </CardContent>
          </Card>
        </Box>
      </SettingsTabPanel>

      {isAuthEnabled && user && (
        <SettingsTabPanel active={activeTab === 6}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, alignItems: isMobile ? 'stretch' : 'flex-start' }}>
                <Typography variant="h6">Profile</Typography>
                <Typography variant="body2" color="text.secondary">
                  Signed in as <strong>{user.email}</strong>
                </Typography>
                <Button
                  variant="outlined"
                  color="error"
                  startIcon={<LogoutIcon />}
                  onClick={handleSignOut}
                  disabled={signingOut}
                  fullWidth={isMobile}
                >
                  {signingOut ? 'Signing out...' : 'Log out'}
                </Button>
              </Box>
            </CardContent>
          </Card>
        </SettingsTabPanel>
      )}
    </Box>
  );
};

export default Settings;
