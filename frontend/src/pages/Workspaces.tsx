import React, { useState } from 'react';
import {
  Box,
  Card,
  CardContent,
  Typography,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  IconButton,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Chip,
  CircularProgress,
  Alert,
  Collapse,
  Tabs,
  Tab,
  Checkbox,
  FormControlLabel,
  FormGroup,
  Divider,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Switch,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
} from '@mui/material';
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  WorkspacesOutlined as WorkspacesIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
  PersonAdd as PersonAddIcon,
  GroupAdd as GroupAddIcon,
  RemoveCircleOutline as RemoveIcon,
} from '@mui/icons-material';
import {
  useWorkspaces,
  useWorkspaceMembers,
  Workspace,
  WorkspaceMember,
  WorkspaceCreatePayload,
} from '../hooks/pages/useWorkspaces';
import { useTeams } from '../hooks/pages/useTeams';
import { useUsers } from '../hooks/pages/useUsers';
import { useServerManager } from '../hooks/useServerManager';
import { useConfirmDialog } from '../hooks/useConfirmDialog';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { StyledDialog } from '../components/common/StyledDialog';
import { TargetPanel } from '../components/common/TargetPanel';
import { ALL_NAV_ITEMS } from '../config/navItems';
import { ALL_PERMISSIONS, Permission } from '../types/auth';
import { buildServerUrl } from '../utils/buildUrlUtils';

// ---------------------------------------------------------------------------
// Permission grouping helpers
// ---------------------------------------------------------------------------
const PERMISSION_GROUPS: Record<string, string> = {
  dashboard: 'Dashboard',
  device_control: 'Device Control',
  testcases: 'Test Cases',
  campaigns: 'Campaigns',
  'builder.test': 'Test Builder',
  'builder.campaign': 'Campaign Builder',
  'execution.run': 'Execution',
  'execution.monitor': 'Execution Monitor',
  'execution.build': 'Execution Build',
  reports: 'Reports',
  monitoring: 'Monitoring',
  interface: 'Interface',
  ai_agent: 'AI Agent',
  plugins: 'Plugins',
  settings: 'Settings',
  org: 'Organisation',
};

function getPermissionGroup(perm: string): string {
  const prefix = perm.split(':')[0];
  for (const [key, label] of Object.entries(PERMISSION_GROUPS)) {
    if (prefix === key || prefix.startsWith(key + '.')) return label;
  }
  return 'Other';
}

function groupPermissions(perms: Permission[]): Record<string, Permission[]> {
  const groups: Record<string, Permission[]> = {};
  for (const perm of perms) {
    const group = getPermissionGroup(perm);
    if (!groups[group]) groups[group] = [];
    groups[group].push(perm);
  }
  return groups;
}

// ---------------------------------------------------------------------------
// ALL_PAGES list (for hidden_pages tab)
//
// Sourced from the shared navItems config so the saved paths match exactly
// what the navbar checks at render time. Otherwise hiding "/run/tests" from
// Workspaces wouldn't affect the navbar which links to "/test-execution/run-tests".
// ---------------------------------------------------------------------------
const ALL_PAGES: { path: string; label: string }[] = ALL_NAV_ITEMS.map((item) => ({
  path: item.path,
  label: item.label,
}));

// ---------------------------------------------------------------------------
// Tab panel helper
// ---------------------------------------------------------------------------
interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

const TabPanel: React.FC<TabPanelProps> = ({ children, value, index }) => (
  <Box role="tabpanel" hidden={value !== index} sx={{ pt: 2 }}>
    {value === index && children}
  </Box>
);

// ---------------------------------------------------------------------------
// Expanded row — members + add user/team
// ---------------------------------------------------------------------------
interface ExpandedRowProps {
  workspace: Workspace;
}

const ExpandedRow: React.FC<ExpandedRowProps> = ({ workspace }) => {
  const { data: members = [], isLoading } = useWorkspaceMembers(workspace.id);
  const { users } = useUsers();
  const { teams } = useTeams();
  const { addWorkspaceUser, addWorkspaceTeam, removeWorkspaceMember } = useWorkspaces();

  const [selectedUserId, setSelectedUserId] = useState('');
  const [selectedTeamId, setSelectedTeamId] = useState('');
  const [addingUser, setAddingUser] = useState(false);
  const [addingTeam, setAddingTeam] = useState(false);

  const handleAddUser = async () => {
    if (!selectedUserId) return;
    setAddingUser(true);
    try {
      await addWorkspaceUser({ workspaceId: workspace.id, userId: selectedUserId });
      setSelectedUserId('');
    } finally {
      setAddingUser(false);
    }
  };

  const handleAddTeam = async () => {
    if (!selectedTeamId) return;
    setAddingTeam(true);
    try {
      await addWorkspaceTeam({ workspaceId: workspace.id, teamId: selectedTeamId });
      setSelectedTeamId('');
    } finally {
      setAddingTeam(false);
    }
  };

  const handleRemove = async (member: WorkspaceMember) => {
    await removeWorkspaceMember({ workspaceId: workspace.id, memberId: member.id });
  };

  if (isLoading) {
    return (
      <Box sx={{ p: 2, display: 'flex', justifyContent: 'center' }}>
        <CircularProgress size={20} />
      </Box>
    );
  }

  return (
    <Box sx={{ p: 2, bgcolor: 'action.hover' }}>
      {/* Members list */}
      <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 1 }}>
        Members ({members.length})
      </Typography>
      {members.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          No members yet.
        </Typography>
      ) : (
        <List dense disablePadding sx={{ mb: 2 }}>
          {members.map((m) => (
            <ListItem key={m.id} disablePadding sx={{ py: 0.25 }}>
              <ListItemText
                primary={
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Chip
                      label={m.type}
                      size="small"
                      color={m.type === 'user' ? 'primary' : 'secondary'}
                      sx={{ height: 18, fontSize: '0.65rem' }}
                    />
                    <Typography variant="body2">
                      {m.type === 'user' ? (m.full_name || m.email || m.user_id) : (m.team_name || m.team_id)}
                    </Typography>
                    {m.role && (
                      <Typography variant="caption" color="text.secondary">
                        ({m.role})
                      </Typography>
                    )}
                  </Box>
                }
              />
              <ListItemSecondaryAction>
                <IconButton size="small" color="error" onClick={() => handleRemove(m)}>
                  <RemoveIcon fontSize="small" />
                </IconButton>
              </ListItemSecondaryAction>
            </ListItem>
          ))}
        </List>
      )}

      <Divider sx={{ mb: 2 }} />

      {/* Add user / Add team — two columns */}
      <Box sx={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
        <Box sx={{ flex: 1, minWidth: 280 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
            <PersonAddIcon fontSize="small" color="action" />
            <Typography variant="subtitle2">Add User</Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <FormControl size="small" sx={{ flex: 1, minWidth: 180 }}>
              <InputLabel>Select user</InputLabel>
              <Select
                value={selectedUserId}
                label="Select user"
                onChange={(e) => setSelectedUserId(e.target.value)}
              >
                {users.map((u) => (
                  <MenuItem key={u.id} value={u.id}>
                    {u.full_name || u.email}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button
              variant="outlined"
              size="small"
              onClick={handleAddUser}
              disabled={!selectedUserId || addingUser}
              startIcon={<AddIcon />}
            >
              Add
            </Button>
          </Box>
        </Box>

        <Box sx={{ flex: 1, minWidth: 280 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
            <GroupAddIcon fontSize="small" color="action" />
            <Typography variant="subtitle2">Add Team</Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <FormControl size="small" sx={{ flex: 1, minWidth: 180 }}>
              <InputLabel>Select team</InputLabel>
              <Select
                value={selectedTeamId}
                label="Select team"
                onChange={(e) => setSelectedTeamId(e.target.value)}
              >
                {teams.map((t) => (
                  <MenuItem key={t.id} value={t.id}>
                    {t.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button
              variant="outlined"
              size="small"
              onClick={handleAddTeam}
              disabled={!selectedTeamId || addingTeam}
              startIcon={<AddIcon />}
            >
              Add
            </Button>
          </Box>
        </Box>
      </Box>
    </Box>
  );
};

// ---------------------------------------------------------------------------
// Create / Edit dialog
// ---------------------------------------------------------------------------
interface WorkspaceDialogProps {
  open: boolean;
  workspace: Workspace | null;
  onClose: () => void;
  onSave: (payload: WorkspaceCreatePayload) => Promise<void>;
  isSaving: boolean;
}

const buildDefaultForm = (): WorkspaceCreatePayload => ({
  name: '',
  description: '',
  permissions: [...ALL_PERMISSIONS],
  denied_permissions: [],
  device_filter: [],
  script_filter: [],
  project_tags: [],
  hidden_pages: [],
  is_public: false,
});

// Group script names by folder prefix (everything before the first '/').
// Scripts at the root get bucketed under 'root'.
function groupScriptsByFolder(scripts: string[]): Record<string, string[]> {
  const groups: Record<string, string[]> = {};
  for (const name of scripts) {
    const idx = name.indexOf('/');
    const folder = idx === -1 ? 'root' : name.slice(0, idx);
    if (!groups[folder]) groups[folder] = [];
    groups[folder].push(name);
  }
  for (const key of Object.keys(groups)) {
    groups[key].sort((a, b) => a.localeCompare(b));
  }
  return groups;
}

const WorkspaceDialog: React.FC<WorkspaceDialogProps> = ({ open, workspace, onClose, onSave, isSaving }) => {
  const [tab, setTab] = useState(0);
  const [form, setForm] = useState<WorkspaceCreatePayload>(buildDefaultForm());
  // Workspaces are global scope — we must show targets from every registered
  // server, not just the currently selected one, because the device_filter
  // applies across the whole platform.
  const { serverHostsData } = useServerManager();

  const allHosts = React.useMemo(() => {
    const byHostName = new Map<string, { host_name: string; devices: any[] }>();
    serverHostsData.forEach((server) => {
      server.hosts.forEach((host) => {
        // If the same host name appears on multiple servers (shouldn't in
        // practice, but guard anyway), merge their devices rather than drop.
        const existing = byHostName.get(host.host_name);
        if (existing) {
          const seen = new Set(existing.devices.map((d: any) => d.device_id));
          (host.devices || []).forEach((d: any) => {
            if (!seen.has(d.device_id)) existing.devices.push(d);
          });
        } else {
          byHostName.set(host.host_name, {
            host_name: host.host_name,
            devices: [...(host.devices || [])],
          });
        }
      });
    });
    return Array.from(byHostName.values()).sort((a, b) =>
      a.host_name.localeCompare(b.host_name, undefined, { numeric: true }),
    );
  }, [serverHostsData]);

  const getDevicesFromHost = React.useCallback(
    (hostName: string) => allHosts.find((h) => h.host_name === hostName)?.devices ?? [],
    [allHosts],
  );

  // All `hostName:deviceId` keys across every server — used to default a new
  // workspace to "every device allowed" (same key format as `TargetPanel`).
  const allDeviceTargetKeys = React.useMemo(() => {
    const keys: string[] = [];
    allHosts.forEach((h) =>
      (h.devices || []).forEach((d: any) => keys.push(`${h.host_name}:${d.device_id}`)),
    );
    return keys;
  }, [allHosts]);

  // Available scripts loaded from /server/script/list (same source as RunTests).
  // Fetched on mount rather than on open so late-arriving script data doesn't
  // retrigger the form-reset effect and snap the user back to the General tab.
  const [availableScripts, setAvailableScripts] = useState<string[]>([]);
  const [loadingScripts, setLoadingScripts] = useState(false);

  React.useEffect(() => {
    let cancelled = false;
    setLoadingScripts(true);
    fetch(buildServerUrl('/server/script/list'))
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return;
        if (data.success) {
          setAvailableScripts((data.scripts || []) as string[]);
        }
      })
      .catch((e) => console.error('[@Workspaces] Failed to load scripts:', e))
      .finally(() => {
        if (!cancelled) setLoadingScripts(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Refs to read the latest async-loaded values from the reset effect without
  // listing them as deps — otherwise a late host or script update re-runs the
  // effect, calls setTab(0), and clobbers whatever the user is editing.
  const allDeviceTargetKeysRef = React.useRef(allDeviceTargetKeys);
  allDeviceTargetKeysRef.current = allDeviceTargetKeys;
  const availableScriptsRef = React.useRef(availableScripts);
  availableScriptsRef.current = availableScripts;

  // Reset form only when the dialog opens or the edited workspace changes.
  React.useEffect(() => {
    if (open) {
      setTab(0);
      if (workspace) {
        setForm({
          name: workspace.name,
          description: workspace.description,
          permissions: [...workspace.permissions],
          denied_permissions: [...workspace.denied_permissions],
          device_filter: [...workspace.device_filter],
          script_filter: [...(workspace.script_filter ?? [])],
          project_tags: [...workspace.project_tags],
          hidden_pages: [...workspace.hidden_pages],
          is_public: workspace.is_public ?? false,
        });
      } else {
        setForm({
          ...buildDefaultForm(),
          device_filter: [...allDeviceTargetKeysRef.current],
          script_filter: [...availableScriptsRef.current],
        });
      }
    }
  }, [open, workspace]);

  const handleSave = async () => {
    await onSave({
      name: form.name,
      description: form.description,
      permissions: form.permissions,
      denied_permissions: form.denied_permissions,
      device_filter: form.device_filter,
      script_filter: form.script_filter,
      project_tags: form.project_tags,
      hidden_pages: form.hidden_pages,
      is_public: form.is_public,
    });
  };

  const toggleScript = (name: string) => {
    setForm((prev) => {
      const current = prev.script_filter ?? [];
      return {
        ...prev,
        script_filter: current.includes(name)
          ? current.filter((s) => s !== name)
          : [...current, name],
      };
    });
  };

  const selectAllScripts = () => setForm({ ...form, script_filter: [...availableScripts] });
  const clearAllScripts = () => setForm({ ...form, script_filter: [] });

  const toggleGrantedPerm = (perm: Permission) => {
    const current = form.permissions ?? [];
    setForm({
      ...form,
      permissions: current.includes(perm)
        ? current.filter((p) => p !== perm)
        : [...current, perm],
    });
  };

  const toggleDeniedPerm = (perm: Permission) => {
    const current = form.denied_permissions ?? [];
    setForm({
      ...form,
      denied_permissions: current.includes(perm)
        ? current.filter((p) => p !== perm)
        : [...current, perm],
    });
  };

  const toggleHiddenPage = (path: string) => {
    const current = form.hidden_pages ?? [];
    setForm({
      ...form,
      hidden_pages: current.includes(path)
        ? current.filter((p) => p !== path)
        : [...current, path],
    });
  };

  const toggleDeviceTarget = (key: string) => {
    setForm((prev) => {
      const current = prev.device_filter ?? [];
      return {
        ...prev,
        device_filter: current.includes(key)
          ? current.filter((d) => d !== key)
          : [...current, key],
      };
    });
  };

  // Map<key, ui> expected by TargetPanel — the UI value is unused here since
  // the workspace's device filter doesn't carry a per-device userinterface.
  const selectedDeviceMap = React.useMemo(() => {
    return new Map((form.device_filter ?? []).map((key) => [key, '']));
  }, [form.device_filter]);

  const selectAllPermissions = (key: 'permissions' | 'denied_permissions') =>
    setForm({ ...form, [key]: [...ALL_PERMISSIONS] });
  const clearAllPermissions = (key: 'permissions' | 'denied_permissions') =>
    setForm({ ...form, [key]: [] });
  const selectAllPages = () => setForm({ ...form, hidden_pages: [] });
  const clearAllPages = () => setForm({ ...form, hidden_pages: ALL_PAGES.map((p) => p.path) });

  const grantedGroups = groupPermissions(ALL_PERMISSIONS);

  return (
    <StyledDialog
      open={open}
      onClose={onClose}
      maxWidth={false}
      PaperProps={{
        sx: {
          width: 800,
          height: 650,
        },
      }}
    >
      <DialogTitle>{workspace ? 'Edit Workspace' : 'Create New Workspace'}</DialogTitle>
      <DialogContent>
        <Tabs value={tab} onChange={(_, v: number) => setTab(v)} sx={{ borderBottom: 1, borderColor: 'divider' }}>
          <Tab label="General" />
          <Tab label="Permissions" />
          <Tab label="Devices" />
          <Tab label="Scripts" />
          <Tab label="Pages" />
        </Tabs>

        {/* Tab 0: General */}
        <TabPanel value={tab} index={0}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <TextField
              label="Name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              fullWidth
              required
            />
            <TextField
              label="Description"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              fullWidth
              multiline
              rows={3}
            />
            <FormControlLabel
              control={
                <Switch
                  checked={!!form.is_public}
                  onChange={(e) => setForm({ ...form, is_public: e.target.checked })}
                />
              }
              label={
                <Box>
                  <Typography variant="body2">Public workspace</Typography>
                  <Typography variant="caption" color="text.secondary">
                    When enabled, this workspace is visible to everyone
                  </Typography>
                </Box>
              }
            />
          </Box>
        </TabPanel>

        {/* Tab 1: Permissions */}
        <TabPanel value={tab} index={1}>
          <Alert severity="info" sx={{ mb: 2 }}>
            Workspace permissions are a filter — they cannot grant users more than their role allows.
          </Alert>

          {/* Granted permissions */}
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
            <Typography variant="subtitle1" fontWeight="bold">
              Granted in workspace
            </Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button size="small" onClick={() => selectAllPermissions('permissions')}>Select all</Button>
              <Button size="small" onClick={() => clearAllPermissions('permissions')}>Unselect all</Button>
            </Box>
          </Box>
          {Object.entries(grantedGroups).map(([group, perms]) => (
            <Box key={group} sx={{ mb: 1.5 }}>
              <Typography variant="caption" color="text.secondary" fontWeight="bold">
                {group.toUpperCase()}
              </Typography>
              <FormGroup row>
                {perms.map((perm) => (
                  <FormControlLabel
                    key={perm}
                    control={
                      <Checkbox
                        size="small"
                        checked={(form.permissions ?? []).includes(perm)}
                        onChange={() => toggleGrantedPerm(perm)}
                      />
                    }
                    label={<Typography variant="caption">{perm}</Typography>}
                    sx={{ mr: 1 }}
                  />
                ))}
              </FormGroup>
            </Box>
          ))}

          <Divider sx={{ my: 2 }} />

          {/* Denied permissions */}
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
            <Typography variant="subtitle1" fontWeight="bold">
              Denied in workspace
            </Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button size="small" onClick={() => selectAllPermissions('denied_permissions')}>Select all</Button>
              <Button size="small" onClick={() => clearAllPermissions('denied_permissions')}>Unselect all</Button>
            </Box>
          </Box>
          {Object.entries(grantedGroups).map(([group, perms]) => (
            <Box key={group} sx={{ mb: 1.5 }}>
              <Typography variant="caption" color="text.secondary" fontWeight="bold">
                {group.toUpperCase()}
              </Typography>
              <FormGroup row>
                {perms.map((perm) => (
                  <FormControlLabel
                    key={perm}
                    control={
                      <Checkbox
                        size="small"
                        checked={(form.denied_permissions ?? []).includes(perm)}
                        onChange={() => toggleDeniedPerm(perm)}
                      />
                    }
                    label={<Typography variant="caption">{perm}</Typography>}
                    sx={{ mr: 1 }}
                  />
                ))}
              </FormGroup>
            </Box>
          ))}
        </TabPanel>

        {/* Tab 2: Devices */}
        <TabPanel value={tab} index={2}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Select devices visible in this workspace.
          </Typography>
          {allHosts.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
              No hosts available.
            </Typography>
          ) : (
            <TargetPanel
              selectedDevices={selectedDeviceMap}
              onToggle={toggleDeviceTarget}
              onUpdateUserinterface={() => undefined}
              allHosts={allHosts}
              getDevicesFromHost={getDevicesFromHost}
              selectionCountLabel={`${(form.device_filter ?? []).length} device${(form.device_filter ?? []).length !== 1 ? 's' : ''} selected`}
            />
          )}
        </TabPanel>

        {/* Tab 3: Scripts */}
        <TabPanel value={tab} index={3}>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
            <Typography variant="body2" color="text.secondary">
              Select scripts visible in this workspace.
            </Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button size="small" onClick={selectAllScripts}>Select all</Button>
              <Button size="small" onClick={clearAllScripts}>Unselect all</Button>
            </Box>
          </Box>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 2 }}>
            {(form.script_filter ?? []).length} of {availableScripts.length} scripts selected
          </Typography>
          {loadingScripts ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress size={24} />
            </Box>
          ) : availableScripts.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
              No scripts available.
            </Typography>
          ) : (
            Object.entries(groupScriptsByFolder(availableScripts)).map(([folder, scripts]) => (
              <Box key={folder} sx={{ mb: 1.5 }}>
                <Typography variant="caption" color="text.secondary" fontWeight="bold">
                  {folder.toUpperCase()}
                </Typography>
                <FormGroup>
                  {scripts.map((name) => (
                    <FormControlLabel
                      key={name}
                      control={
                        <Checkbox
                          size="small"
                          checked={(form.script_filter ?? []).includes(name)}
                          onChange={() => toggleScript(name)}
                        />
                      }
                      label={<Typography variant="caption">{name}</Typography>}
                    />
                  ))}
                </FormGroup>
              </Box>
            ))
          )}
        </TabPanel>

        {/* Tab 4: Pages */}
        <TabPanel value={tab} index={4}>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
            <Typography variant="body2" color="text.secondary">
              Pages toggled <strong>off</strong> will be hidden for members of this workspace.
            </Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button size="small" onClick={selectAllPages}>Select all</Button>
              <Button size="small" onClick={clearAllPages}>Unselect all</Button>
            </Box>
          </Box>
          <FormGroup>
            {ALL_PAGES.map((page) => {
              const isHidden = (form.hidden_pages ?? []).includes(page.path);
              return (
                <FormControlLabel
                  key={page.path}
                  control={
                    <Switch
                      size="small"
                      checked={!isHidden}
                      onChange={() => toggleHiddenPage(page.path)}
                    />
                  }
                  label={
                    <Typography variant="body2">
                      {page.label}
                      <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                        ({page.path})
                      </Typography>
                    </Typography>
                  }
                />
              );
            })}
          </FormGroup>
        </TabPanel>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          onClick={handleSave}
          variant="contained"
          disabled={!form.name.trim() || isSaving}
        >
          {isSaving ? 'Saving...' : workspace ? 'Update' : 'Create'}
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
const Workspaces: React.FC = () => {
  const {
    workspaces,
    isLoading,
    error,
    createWorkspace,
    updateWorkspace,
    deleteWorkspace,
    isCreating,
    isUpdating,
    isDeleting,
    createError,
    updateError,
    deleteError,
  } = useWorkspaces();

  const [openDialog, setOpenDialog] = useState(false);
  const [editingWorkspace, setEditingWorkspace] = useState<Workspace | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  const handleOpenDialog = (ws?: Workspace) => {
    setEditingWorkspace(ws ?? null);
    setOpenDialog(true);
  };

  const handleCloseDialog = () => {
    setOpenDialog(false);
    setEditingWorkspace(null);
  };

  const handleSave = async (payload: WorkspaceCreatePayload) => {
    try {
      if (editingWorkspace) {
        await updateWorkspace({ id: editingWorkspace.id, payload });
      } else {
        await createWorkspace(payload);
      }
      handleCloseDialog();
    } catch (err) {
      console.error('Error saving workspace:', err);
    }
  };

  const handleDelete = (wsId: string) => {
    confirm({
      title: 'Confirm Delete',
      message: 'Are you sure you want to delete this workspace?',
      confirmColor: 'error',
      onConfirm: async () => {
        try {
          await deleteWorkspace(wsId);
        } catch (err) {
          console.error('Error deleting workspace:', err);
        }
      },
    });
  };

  const handleToggleExpand = (wsId: string) => {
    setExpandedId((prev) => (prev === wsId ? null : wsId));
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <WorkspacesIcon fontSize="large" color="primary" />
          <Typography variant="h4" component="h1">
            Workspaces Management
          </Typography>
        </Box>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => handleOpenDialog()}
          disabled={isCreating}
        >
          Create Workspace
        </Button>
      </Box>

      {(error || createError || updateError || deleteError) && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error || createError || updateError || deleteError}
        </Alert>
      )}

      {isLoading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
          <CircularProgress />
        </Box>
      ) : (
        <Card>
          <CardContent sx={{ p: 0, '&:last-child': { pb: 0 } }}>
            <TableContainer component={Paper} elevation={0}>
              <Table
                sx={{
                  '& .MuiTableRow-root:hover': {
                    backgroundColor: 'transparent !important',
                  },
                }}
              >
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ width: 48 }} />
                    <TableCell><strong>Workspace Name</strong></TableCell>
                    <TableCell><strong>Description</strong></TableCell>
                    <TableCell align="center"><strong>Members</strong></TableCell>
                    <TableCell align="center"><strong>Permissions</strong></TableCell>
                    <TableCell><strong>Created</strong></TableCell>
                    <TableCell align="right"><strong>Actions</strong></TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {workspaces.map((ws) => (
                    <React.Fragment key={ws.id}>
                      <TableRow>
                        <TableCell sx={{ width: 48 }}>
                          {!ws.is_public && (
                            <IconButton size="small" onClick={() => handleToggleExpand(ws.id)}>
                              {expandedId === ws.id ? (
                                <ExpandLessIcon fontSize="small" />
                              ) : (
                                <ExpandMoreIcon fontSize="small" />
                              )}
                            </IconButton>
                          )}
                        </TableCell>
                        <TableCell>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <Typography variant="body1" fontWeight="medium">
                              {ws.name}
                            </Typography>
                            {ws.is_public && (
                              <Chip label="Public" size="small" color="success" sx={{ height: 18, fontSize: '0.65rem' }} />
                            )}
                          </Box>
                        </TableCell>
                        <TableCell>{ws.description}</TableCell>
                        <TableCell align="center">
                          <Chip label={ws.member_count} size="small" color="primary" />
                        </TableCell>
                        <TableCell align="center">
                          <Chip label={ws.permissions.length} size="small" color="default" />
                        </TableCell>
                        <TableCell>{new Date(ws.created_at).toLocaleDateString()}</TableCell>
                        <TableCell align="right">
                          <IconButton
                            size="small"
                            color="primary"
                            onClick={() => handleOpenDialog(ws)}
                            disabled={isUpdating || isDeleting}
                          >
                            <EditIcon fontSize="small" />
                          </IconButton>
                          <IconButton
                            size="small"
                            color="error"
                            onClick={() => handleDelete(ws.id)}
                            disabled={isUpdating || isDeleting}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </TableCell>
                      </TableRow>

                      {/* Expanded row — member management, hidden for public workspaces */}
                      {!ws.is_public && (
                        <TableRow>
                          <TableCell colSpan={7} sx={{ p: 0, border: 0 }}>
                            <Collapse in={expandedId === ws.id} timeout="auto" unmountOnExit>
                              <ExpandedRow workspace={ws} />
                            </Collapse>
                          </TableCell>
                        </TableRow>
                      )}
                    </React.Fragment>
                  ))}
                  {workspaces.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={7} align="center">
                        <Typography variant="body2" color="textSecondary" sx={{ py: 4 }}>
                          No workspaces found. Create your first workspace to get started.
                        </Typography>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </CardContent>
        </Card>
      )}

      <WorkspaceDialog
        open={openDialog}
        workspace={editingWorkspace}
        onClose={handleCloseDialog}
        onSave={handleSave}
        isSaving={isCreating || isUpdating}
      />

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

export default Workspaces;
