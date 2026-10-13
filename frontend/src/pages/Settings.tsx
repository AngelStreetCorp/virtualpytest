import {
  Save as SaveIcon,
  Refresh as RefreshIcon,
  Storage as ServerIcon,
  Computer as HostIcon,
  Language as FrontendIcon,
  Add as AddIcon,
  Delete as DeleteIcon,
  ExpandMore as ExpandIcon,
  Palette as BrandingIcon,
  Upload as UploadIcon,
  RestartAlt as ResetIcon,
  Tune as FeaturesIcon,
  Visibility as VisibilityIcon,
  Android as AndroidIcon,
  VisibilityOff as VisibilityOffIcon,
  Videocam as VideoIcon,
  Bluetooth as BluetoothIcon,
  SettingsRemote as IrIcon,
} from '@mui/icons-material';
import { AIIcon } from '../components/common/icons/CustomIcons';
import { getEnv } from '../config/constants';
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
  Chip,
  FormControlLabel,
} from '@mui/material';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { PAGE_TITLE_SX, pageSurfaceSx } from '../components/common/PageChrome';
import { useResponsiveMode } from '../hooks/useResponsiveMode';
import React, { useState, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';

import { useSettings, FrontendConfig } from '../hooks/pages';
import { useBranding } from '../contexts/BrandingContext';
import { ALL_NAV_ITEMS } from '../config/navItems';
import { TOAST_POSITION, TOAST_AUTO_HIDE_DURATION } from '../constants/toastConfig';
import { featureSettingsNotices } from '../config/features';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { api } from '../utils/apiClient';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { AiRoutingSettings } from '../components/settings/AiRoutingSettings';
import { useConfirmDialog } from '../hooks/useConfirmDialog';

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
  updateFrontendConfig: (field: string, value: string) => void,
) {
  const hidden = parseNavSet(frontend.VITE_NAV_HIDDEN);
  if (visible) hidden.delete(path);
  else hidden.add(path);
  updateFrontendConfig('VITE_NAV_HIDDEN', [...hidden].join(','));
}

const settingsPanelSx = {
  minHeight: 360,
};

// ─── Restart-required tracking ────────────────────────────────────────────────
// There's no way to verify a service actually restarted, so this is honest
// best-effort bookkeeping: a save flags the section, and it stays flagged
// (across reloads, via localStorage) until the admin explicitly acknowledges
// having restarted it.
const RESTART_PENDING_STORAGE_KEY = 'vpt-settings-restart-pending';
type RestartPendingState = { server?: boolean; frontend?: boolean };

const readRestartPending = (): RestartPendingState => {
  try {
    return JSON.parse(localStorage.getItem(RESTART_PENDING_STORAGE_KEY) || '{}');
  } catch {
    return {};
  }
};

const writeRestartPending = (state: RestartPendingState) => {
  try {
    localStorage.setItem(RESTART_PENDING_STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* private window / storage disabled — badge just won't survive a reload */
  }
};

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

// ─── Dynamic "every other key" rendering ──────────────────────────────────────
// The backend now returns every key each .env file contains, not a fixed
// whitelist. Keys with their own dedicated field elsewhere on the page (the
// Server tab's Name/URL/Port, Frontend's known fields, Features'
// nav/feature toggles) are excluded here so they don't render twice.

const KNOWN_SERVER_KEYS = new Set<string>([
  'SERVER_NAME',
  'SERVER_URL',
  'SERVER_PORT',
]);

const KNOWN_FRONTEND_KEYS = new Set<string>([
  'VITE_SERVER_URL',
  'VITE_SLAVE_SERVER_URL',
  'VITE_GRAFANA_URL',
  'VITE_CLOUDFLARE_R2_PUBLIC_URL',
  'VITE_DEV_MODE',
  'VITE_FEATURE_DEPLOYMENTS',
  'VITE_FEATURE_RUN_VERSION_SELECTOR',
  'VITE_NAV_HIDDEN',
  'VITE_NAV_DISABLED',
  'VITE_NAV_COMING_SOON',
]);

// A masked TextField with an eye toggle for any credential-shaped .env key.
const MaskedTextField: React.FC<{
  label: string;
  value: string;
  onChange: (value: string) => void;
  sensitive: boolean;
}> = ({ label, value, onChange, sensitive }) => {
  const [shown, setShown] = useState(false);
  return (
    <TextField
      label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      fullWidth
      size="small"
      type={sensitive && !shown ? 'password' : 'text'}
      InputProps={
        sensitive
          ? {
              endAdornment: (
                <InputAdornment position="end">
                  <IconButton
                    aria-label={shown ? 'Hide value' : 'Show value'}
                    onClick={() => setShown((s) => !s)}
                    edge="end"
                    size="small"
                    tabIndex={-1}
                  >
                    {shown ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}
                  </IconButton>
                </InputAdornment>
              ),
            }
          : undefined
      }
    />
  );
};

// Every key in `entries` that isn't already rendered by a dedicated field
// elsewhere on the tab, as a plain masked-if-sensitive grid.
const ExtraEnvFields: React.FC<{
  entries: Record<string, string>;
  sensitiveKeys: string[];
  exclude: Set<string>;
  onChange: (key: string, value: string) => void;
}> = ({ entries, sensitiveKeys, exclude, onChange }) => {
  const sensitiveSet = new Set(sensitiveKeys);
  const keys = Object.keys(entries)
    .filter((k) => !exclude.has(k))
    .sort();
  if (keys.length === 0) return null;
  return (
    <>
      <Divider sx={{ mt: 3, mb: 2 }} />
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Other settings
      </Typography>
      <Grid container spacing={2}>
        {keys.map((key) => (
          <Grid item xs={12} md={6} key={key}>
            <MaskedTextField
              label={key}
              value={entries[key] ?? ''}
              onChange={(value) => onChange(key, value)}
              sensitive={sensitiveSet.has(key)}
            />
          </Grid>
        ))}
      </Grid>
    </>
  );
};

// ─── Branding Tab ─────────────────────────────────────────────────────────────

const BrandingTab: React.FC = () => {
  const { branding, setBranding, resetBranding, isLoaded, hasBackup } = useBranding();
  const [name, setName] = useState(branding.name);
  const [tagline, setTagline] = useState(branding.tagline);
  const [logoUrl, setLogoUrl] = useState(branding.logoUrl);
  const [faviconUrl, setFaviconUrl] = useState(branding.faviconUrl);
  const [showGithubLink, setShowGithubLink] = useState(branding.showGithubLink);
  const [showMobileAppLink, setShowMobileAppLink] = useState(branding.showMobileAppLink);
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
      setShowGithubLink(branding.showGithubLink);
      setShowMobileAppLink(branding.showMobileAppLink);
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
    await setBranding({ name, tagline, logoUrl, faviconUrl, showGithubLink, showMobileAppLink });
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

          {/* Footer links */}
          <Grid item xs={12}>
            <Typography variant="subtitle2" gutterBottom sx={{ mt: 1 }}>
              Footer links
            </Typography>
            <Box display="flex" flexDirection="column">
              <FormControlLabel
                control={<Switch size="small" checked={showMobileAppLink} onChange={(e) => setShowMobileAppLink(e.target.checked)} />}
                label="Show “Get the mobile app”"
              />
              <FormControlLabel
                control={<Switch size="small" checked={showGithubLink} onChange={(e) => setShowGithubLink(e.target.checked)} />}
                label="Show “View on GitHub”"
              />
            </Box>
          </Grid>

          {/* Live preview */}
          <Grid item xs={12}>
            <Typography variant="subtitle2" gutterBottom sx={{ mt: 1 }}>
              Header Preview
            </Typography>
            <Paper
              variant="outlined"
              sx={{ p: 1.5, display: 'flex', alignItems: 'center', gap: 1, backgroundColor: 'divider', borderRadius: 1 }}
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
  const P = useAgentChatPalette();
  const { isMobile } = useResponsiveMode();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTab = searchParams.get('tab') === 'ai' ? 5 : 0;
  const [activeTab, setActiveTab] = useState(initialTab);
  const [restartPending, setRestartPending] = useState<RestartPendingState>(() => readRestartPending());
  const [registeredHosts, setRegisteredHosts] = useState<Array<{ host_name: string }>>([]);
  const [selectedHostName, setSelectedHostName] = useState('');
  const [hostConfigSaved, setHostConfigSaved] = useState(false);
  const [hostConfigReady, setHostConfigReady] = useState(false);
  const [restartingHostService, setRestartingHostService] = useState<string | null>(null);

  const acknowledgeRestart = (scope: 'server' | 'frontend') => {
    setRestartPending((prev) => {
      const next = { ...prev, [scope]: false };
      writeRestartPending(next);
      return next;
    });
  };

  const [restarting, setRestarting] = useState<{ server?: boolean; frontend?: boolean }>({});
  const [restartError, setRestartError] = useState<string | null>(null);
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  const doRestartServer = async () => {
    setRestartError(null);
    setRestarting((prev) => ({ ...prev, server: true }));
    try {
      await api.post(buildServerUrl('/server/system/restartServerService'), {});
      acknowledgeRestart('server');
    } catch (err) {
      setRestartError(err instanceof Error ? err.message : 'Failed to restart the server');
    } finally {
      setRestarting((prev) => ({ ...prev, server: false }));
    }
  };

  const doRestartFrontend = async () => {
    setRestartError(null);
    setRestarting((prev) => ({ ...prev, frontend: true }));
    try {
      await api.post(buildServerUrl('/server/settings/restart-frontend'), {});
      acknowledgeRestart('frontend');
    } catch (err) {
      setRestartError(err instanceof Error ? err.message : 'Failed to restart the frontend');
    } finally {
      setRestarting((prev) => ({ ...prev, frontend: false }));
    }
  };

  const confirmRestartServer = () => {
    confirm({
      title: 'Restart Server',
      message: 'Restart the backend server (vpt-server)?\n\nIt will be briefly unreachable — a few seconds — while it restarts.',
      confirmText: 'Restart',
      confirmColor: 'warning',
      onConfirm: () => {
        void doRestartServer();
      },
    });
  };

  const confirmRestartFrontend = () => {
    confirm({
      title: 'Restart Frontend',
      message: 'Restart the frontend service (vpt-frontend-prod)?\n\nThe site will be briefly unreachable — a few seconds — while it restarts. This does not rebuild it: an edited .env value still needs a rebuild to take effect.',
      confirmText: 'Restart',
      confirmColor: 'warning',
      onConfirm: () => {
        void doRestartFrontend();
      },
    });
  };

  const confirmRestartSelectedHostService = (service: 'host' | 'stream') => {
    const serviceName = service === 'host' ? 'vpt-host' : 'vpt-stream';
    confirm({
      title: `Restart ${serviceName}`,
      message: `Restart ${serviceName} on ${selectedHostName}? The service will be briefly unavailable.`,
      confirmText: 'Restart',
      confirmColor: 'warning',
      onConfirm: async () => {
        setRestartError(null);
        setRestartingHostService(service);
        try {
          await api.post(buildServerUrl('/server/settings/restart-host-service'), {
            host_name: selectedHostName,
            service: serviceName,
          });
        } catch (err) {
          setRestartError(err instanceof Error ? err.message : `Failed to restart ${serviceName}`);
        } finally {
          setRestartingHostService(null);
        }
      },
    });
  };

  const {
    config,
    loading,
    saving,
    error,
    success,
    loadConfig,
    saveConfig,
    loadHostConfig,
    saveHostConfig,
    updateServerConfig,
    updateFrontendConfig,
    updateHostConfig,
    updateDeviceConfig,
    addDevice,
    deleteDevice,
    setError,
    setSuccess,
    grabbers,
    grabbersLoading,
    grabbersError,
    loadGrabbers,
    usedGrabberVideoPaths,
    applyGrabberToDevice,
    getAudioSource,
  } = useSettings();

  useEffect(() => {
    const initializeSettings = async () => {
      await loadConfig();
      try {
        const result = await api.get(buildServerUrl('/server/system/getAllHosts?include_actions=false'));
        const hosts = (result.hosts ?? []).map((host: any) => ({ host_name: host.host_name }));
        setRegisteredHosts(hosts);
        if (hosts.length) setSelectedHostName((current) => current || hosts[0].host_name);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load registered hosts');
      }
    };
    void initializeSettings();
  }, [loadConfig, setError]);

  useEffect(() => {
    if (!selectedHostName) return;
    setHostConfigSaved(false);
    setHostConfigReady(false);
    void loadHostConfig(selectedHostName).then(setHostConfigReady);
    // Detected grabbers come from the host's own /sys + v4l2-ctl walk, so
    // they refresh whenever the operator picks a different registered host.
    void loadGrabbers(selectedHostName);
  }, [selectedHostName, loadHostConfig, loadGrabbers]);

  const handleSave = async () => {
    if (activeTab === 2) {
      if (!hostConfigReady) return;
      setHostConfigSaved(await saveHostConfig(selectedHostName));
      return;
    }
    const updatedFiles = await saveConfig();
    if (updatedFiles.length === 0) return;
    setRestartPending((prev) => {
      const next = { ...prev };
      for (const file of updatedFiles) {
        if (file === 'server' || file === 'frontend') next[file] = true;
      }
      writeRestartPending(next);
      return next;
    });
  };

  useEffect(() => {
    if (searchParams.get('tab') === 'ai' && activeTab !== 5) {
      setActiveTab(5);
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
    <Box sx={pageSurfaceSx(P)}>
      <Box sx={{ mb: 0, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Box>
          <Typography component="h1" sx={PAGE_TITLE_SX}>
            Settings
          </Typography>
        </Box>
        <Box display="flex" gap={1}>
          <Button variant="outlined" startIcon={<RefreshIcon />} onClick={() => {
            void loadConfig().then(async () => {
            if (selectedHostName) {
              setHostConfigReady(false);
              setHostConfigReady(await loadHostConfig(selectedHostName));
            }
            });
          }}>
            Refresh
          </Button>
          <Button
            variant="contained"
            startIcon={saving ? <CircularProgress size={20} /> : <SaveIcon />}
            onClick={handleSave}
            disabled={saving || activeTab === 5 || (activeTab === 2 && !hostConfigReady)}
          >
            Save
          </Button>
        </Box>
      </Box>

      {getEnv('VITE_MOBILE_APP_URL') && (
        <Button
          variant="outlined"
          size="small"
          startIcon={<AndroidIcon />}
          component="a"
          href={getEnv('VITE_MOBILE_APP_URL')}
          sx={{ mb: 1, alignSelf: 'flex-start' }}
        >
          {isMobile ? 'Download APK' : 'Download Android app (APK)'}
        </Button>
      )}

      {featureSettingsNotices().map((Notice, i) => (
        <Notice key={i} />
      ))}

      {error && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {restartError && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setRestartError(null)}>
          {restartError}
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
          setSearchParams(newValue === 5 ? { tab: 'ai' } : {});
        }}
        variant="scrollable"
        scrollButtons="auto"
        sx={{
          mb: 1,
          minHeight: 48,
          // MUI forces minHeight 72 on icon+label tabs and pads them 16px: on a phone that is a
          // tall band and pushes the first tab visibly right of the card edge below it.
          '& .MuiTab-root': { minHeight: 48, py: 0.5, px: { xs: 1, sm: 2 } },
        }}
      >
        <Tab
          icon={<ServerIcon />}
          iconPosition="start"
          label={
            <Box display="flex" alignItems="center" gap={0.75}>
              Server
              {restartPending.server && (
                <Chip label="Restart needed" size="small" color="warning" sx={{ height: 18, fontSize: 10 }} />
              )}
            </Box>
          }
        />
        <Tab
          icon={<FrontendIcon />}
          iconPosition="start"
          label={
            <Box display="flex" alignItems="center" gap={0.75}>
              Frontend
              {restartPending.frontend && (
                <Chip label="Restart needed" size="small" color="warning" sx={{ height: 18, fontSize: 10 }} />
              )}
            </Box>
          }
        />
        <Tab icon={<HostIcon />} label="Host" iconPosition="start" />
        <Tab icon={<BrandingIcon />} label="Branding" iconPosition="start" />
        <Tab icon={<FeaturesIcon />} label="Features" iconPosition="start" />
        <Tab icon={<AIIcon />} label="AI" iconPosition="start" />
      </Tabs>

      {/* Tab 1: Server */}
      <SettingsTabPanel active={activeTab === 0}>
        {restartPending.server && (
          <Alert
            severity="warning"
            sx={{ mb: 2 }}
            action={
              <Box display="flex" gap={1}>
                <Button
                  color="inherit"
                  size="small"
                  onClick={confirmRestartServer}
                  disabled={!!restarting.server}
                  startIcon={restarting.server ? <CircularProgress size={14} color="inherit" /> : undefined}
                >
                  {restarting.server ? 'Restarting…' : 'Restart now'}
                </Button>
                <Button color="inherit" size="small" onClick={() => acknowledgeRestart('server')}>
                  Dismiss
                </Button>
              </Box>
            }
          >
            Saved, but not applied yet — restart the backend server (<code>vpt-server.service</code>) to
            pick up the change.
          </Alert>
        )}
        <Card>
          <CardContent>
            {!isMobile && (
              <>
                <Box display="flex" alignItems="center" mb={1}>
                  <ServerIcon sx={{ mr: 1 }} color="primary" />
                  <Typography variant="h6">Server</Typography>
                </Box>
                <Divider sx={{ mb: 2 }} />
              </>
            )}

            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <TextField
                  label="Server Name"
                  value={config.server.SERVER_NAME}
                  onChange={(e) => updateServerConfig('SERVER_NAME', e.target.value)}
                  placeholder="Awesomation"
                  fullWidth
                  size="small"
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
                />
              </Grid>
            </Grid>

            <ExtraEnvFields
              entries={config.server}
              sensitiveKeys={config.serverSensitiveKeys}
              exclude={KNOWN_SERVER_KEYS}
              onChange={updateServerConfig}
            />
          </CardContent>
        </Card>
      </SettingsTabPanel>

      {/* Tab 2: Frontend */}
      <SettingsTabPanel active={activeTab === 1}>
        {restartPending.frontend && (
          <Alert
            severity="warning"
            sx={{ mb: 2 }}
            action={
              <Box display="flex" gap={1}>
                <Button
                  color="inherit"
                  size="small"
                  onClick={confirmRestartFrontend}
                  disabled={!!restarting.frontend}
                  startIcon={restarting.frontend ? <CircularProgress size={14} color="inherit" /> : undefined}
                >
                  {restarting.frontend ? 'Restarting…' : 'Restart now'}
                </Button>
                <Button color="inherit" size="small" onClick={() => acknowledgeRestart('frontend')}>
                  Dismiss
                </Button>
              </Box>
            }
          >
            Saved, but not applied yet — restart the frontend service to pick up the change. Note: the
            live frontend runs a production build, so <code>VITE_*</code> values are baked in at build
            time — a plain restart alone won't apply an edited value until it's rebuilt (not available
            here yet).
          </Alert>
        )}
        {config.frontendWarning && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            {config.frontendWarning}
          </Alert>
        )}
        <Card>
          <CardContent>
            {!isMobile && (
              <>
                <Box display="flex" alignItems="center" mb={1}>
                  <FrontendIcon sx={{ mr: 1 }} color="primary" />
                  <Typography variant="h6">Frontend</Typography>
                </Box>
                <Divider sx={{ mb: 2 }} />
              </>
            )}

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
              {config.frontend.VITE_CLOUDFLARE_R2_PUBLIC_URL && (
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
              )}
            </Grid>

            <ExtraEnvFields
              entries={config.frontend}
              sensitiveKeys={config.frontendSensitiveKeys}
              exclude={KNOWN_FRONTEND_KEYS}
              onChange={updateFrontendConfig}
            />
          </CardContent>
        </Card>
      </SettingsTabPanel>

      {/* Tab 4: Branding */}
      <SettingsTabPanel active={activeTab === 3}>
        <BrandingTab />
      </SettingsTabPanel>

      {/* Tab 5: Features */}
      <SettingsTabPanel active={activeTab === 4}>
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

      {/* Tab 3: Host */}
      <SettingsTabPanel active={activeTab === 2}>
        <Box>
          <Card sx={{ mb: 1 }}>
            <CardContent>
              <Box display="flex" alignItems="center" justifyContent="space-between" gap={2} flexWrap="wrap">
                <TextField
                  select
                  label="Registered Host"
                  value={selectedHostName}
                  onChange={(event) => {
                    setHostConfigReady(false);
                    setSelectedHostName(event.target.value);
                  }}
                  size="small"
                  sx={{ minWidth: 280 }}
                  disabled={!registeredHosts.length}
                >
                  {registeredHosts.map((host) => <MenuItem key={host.host_name} value={host.host_name}>{host.host_name}</MenuItem>)}
                </TextField>
                <Box display="flex" gap={1} flexWrap="wrap">
                  <Button variant="outlined" disabled={!selectedHostName || !!restartingHostService} onClick={() => confirmRestartSelectedHostService('host')}>
                    {restartingHostService === 'host' ? <CircularProgress size={18} /> : 'Restart vpt-host'}
                  </Button>
                  <Button variant="outlined" disabled={!selectedHostName || !!restartingHostService} onClick={() => confirmRestartSelectedHostService('stream')}>
                    {restartingHostService === 'stream' ? <CircularProgress size={18} /> : 'Restart vpt-stream'}
                  </Button>
                </Box>
              </Box>
              {!registeredHosts.length && <Alert severity="info" sx={{ mt: 1 }}>No registered hosts are currently available.</Alert>}
              {hostConfigSaved && <Alert severity="success" sx={{ mt: 1 }}>Configuration saved on {selectedHostName}. Restart the affected service to apply changes.</Alert>}
            </CardContent>
          </Card>
          <Card sx={{ mb: 1}}>
            <CardContent>
              {!isMobile && (
                <>
                  <Box display="flex" alignItems="center" mb={1}>
                    <HostIcon sx={{ mr: 1 }} color="primary" />
                    <Typography variant="h6">Host Configuration</Typography>
                  </Box>
                  <Divider sx={{ mb: 2 }} />
                </>
              )}

              <Grid container spacing={2}>
                <Grid item xs={12} md={6}>
                  <TextField
                    label="Host Name"
                    value={config.host.HOST_NAME}
                    onChange={(e) => updateHostConfig('HOST_NAME', e.target.value)}
                    placeholder="host1"
                    fullWidth
                    size="small"
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

              {/* Detected Grabbers — host's live UVC + UAC inventory. Each row's
                  "Use" button fills the next free device's DEVICE_VIDEO +
                  DEVICE_VIDEO_AUDIO together, so the operator never types the
                  ALSA card by hand. Audio pairing is the same logic the
                  operator-facing scripts/detect_grabber.sh prints. */}
              <Box sx={{ mt: 2, mb: 1, p: 1.5, border: `1px solid ${P.borderColor}`, borderRadius: 1, background: P.surface }}>
                <Box display="flex" alignItems="center" gap={1} mb={1}>
                  <VideoIcon fontSize="small" sx={{ color: P.accentText }} />
                  <Typography variant="subtitle2" sx={{ color: P.accentText }}>
                    Detected Grabbers
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                    {grabbersLoading
                      ? 'detecting…'
                      : grabbersError
                        ? `detection failed: ${grabbersError}`
                        : `${grabbers.grabbers.length} capture card(s), ${grabbers.bluetooth.length} BT, ${grabbers.infrared.length} IR on ${selectedHostName ?? 'host'}`}
                  </Typography>
                  <Button
                    size="small"
                    startIcon={<RefreshIcon fontSize="small" />}
                    onClick={() => selectedHostName && void loadGrabbers(selectedHostName)}
                    disabled={grabbersLoading || !selectedHostName}
                    sx={{ ml: 'auto' }}
                  >
                    Rescan
                  </Button>
                </Box>
                {!grabbersLoading && !grabbersError && grabbers.grabbers.length === 0 && (
                  <Typography variant="body2" color="text.secondary">
                    No capture cards reported by this host. The vpt-host user may need to be
                    added to the <code>video</code> and <code>audio</code> groups (see{' '}
                    <code>setup/local/linux/backend_host/setup_permissions.sh</code>); without
                    those, <code>v4l2-ctl</code> cannot enumerate the device and the panel
                    stays empty.
                  </Typography>
                )}
                {grabbers.grabbers.length > 0 && (() => {
                  const used = usedGrabberVideoPaths();
                  return (
                    <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse' }}>
                      <Box component="thead">
                        <Box component="tr" sx={{ '& th': { textAlign: 'left', py: 0.5, pr: 2, fontSize: 12, color: 'text.secondary' } }}>
                          <Box component="th">Video</Box>
                          <Box component="th">Audio</Box>
                          <Box component="th">USB</Box>
                          <Box component="th">Port</Box>
                          <Box component="th" />
                        </Box>
                      </Box>
                      <Box component="tbody">
                        {grabbers.grabbers.map((g) => {
                          const inUse = used.has(g.video);
                          const usedBy = Object.entries(config.devices).find(
                            ([, d]) => d.DEVICE_VIDEO === g.video,
                          )?.[0];
                          return (
                            <Box
                              component="tr"
                              key={g.video}
                              sx={{ '& td': { py: 0.5, pr: 2, fontSize: 13, borderTop: `1px solid ${P.borderColor}` } }}
                            >
                              <Box component="td"><code>{g.video}</code></Box>
                              <Box component="td">
                                {g.has_audio ? <code>{g.audio}</code> : <Typography component="span" variant="caption" color="text.secondary">no ALSA on this port</Typography>}
                              </Box>
                              <Box component="td"><code>{g.usb_id}</code></Box>
                              <Box component="td"><code>{g.usb_path}</code></Box>
                              <Box component="td">
                                {inUse ? (
                                  <Typography component="span" variant="caption" color="text.secondary">
                                    in use by {usedBy}
                                  </Typography>
                                ) : (
                                  <Button
                                    size="small"
                                    variant="outlined"
                                    onClick={() => {
                                      const applied = applyGrabberToDevice(g);
                                      if (!applied) {
                                        setError('Add a device first, then click "Use" to attach a grabber.');
                                      }
                                    }}
                                  >
                                    Use
                                  </Button>
                                )}
                              </Box>
                            </Box>
                          );
                        })}
                      </Box>
                    </Box>
                  );
                })()}
                {grabbers.bluetooth.length > 0 && (
                  <Box mt={1.5}>
                    <Box display="flex" alignItems="center" gap={0.5} mb={0.5}>
                      <BluetoothIcon fontSize="small" sx={{ color: P.accentText }} />
                      <Typography variant="caption" sx={{ color: P.accentText }}>Bluetooth</Typography>
                    </Box>
                    <Typography variant="caption" component="div" color="text.secondary">
                      {grabbers.bluetooth.map((b) => `${b.name} (${b.mac || 'no MAC'}) @ ${b.usb_path || 'non-USB'}`).join(' · ')}
                    </Typography>
                  </Box>
                )}
                {grabbers.infrared.length > 0 && (
                  <Box mt={1.5}>
                    <Box display="flex" alignItems="center" gap={0.5} mb={0.5}>
                      <IrIcon fontSize="small" sx={{ color: P.accentText }} />
                      <Typography variant="caption" sx={{ color: P.accentText }}>Infrared</Typography>
                    </Box>
                    <Typography variant="caption" component="div" color="text.secondary">
                      {grabbers.infrared.map((i) => `${i.name} @ ${i.usb_path || 'non-USB'}`).join(' · ')}
                    </Typography>
                  </Box>
                )}
              </Box>

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
                        <Typography variant="subtitle2" sx={{ color: P.accentText }} gutterBottom>
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
                        <Typography variant="subtitle2" sx={{ color: P.accentText }} gutterBottom>
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
                          helperText={(() => {
                            // The audio field is auto-derived from the host's
                            // detected grabber for the selected video path.
                            // Show a small caption so the operator knows
                            // whether their typed value will stick or be
                            // overridden next time grabbers reload.
                            const source = getAudioSource(deviceKey);
                            if (source === 'detected') {
                              const detected = grabbers.grabbers.find((g) => g.video === device.DEVICE_VIDEO);
                              return detected
                                ? `auto-detected from USB ${detected.usb_path} — overrides any manual value on save`
                                : 'auto-detected';
                            }
                            if (source === 'env') {
                              return device.DEVICE_VIDEO_AUDIO
                                ? 'from .env (no detection for this video; manual value kept)'
                                : 'no audio detected for this video';
                            }
                            return 'no audio detected for this video — type one only if you need a cross-port pairing';
                          })()}
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
                        <Typography variant="subtitle2" sx={{ color: P.accentText }} gutterBottom>
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

      {/* Tab 6: AI */}
      <SettingsTabPanel active={activeTab === 5}>
        <AiRoutingSettings />
      </SettingsTabPanel>

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

export default Settings;
