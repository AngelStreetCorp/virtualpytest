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
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Chip,
  Avatar,
  CircularProgress,
  Alert,
  Tabs,
  Tab,
  Checkbox,
  FormControlLabel,
  FormGroup,
  Divider,
} from '@mui/material';
import {
  Edit as EditIcon,
  Delete as DeleteIcon,
  People as UsersIcon,
} from '@mui/icons-material';
import { useUsers, User } from '../hooks/pages/useUsers';
import { useTeams } from '../hooks/pages/useTeams';
import { useConfirmDialog } from '../hooks/useConfirmDialog';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { StyledDialog } from '../components/common/StyledDialog';
import { ALL_PERMISSIONS, Permission } from '../types/auth';

const PERMISSION_GROUPS: Record<string, string> = {
  dashboard: 'Dashboard',
  device_control: 'Device Control',
  testcases: 'Test Cases',
  campaigns: 'Campaigns',
  'builder.test': 'Builder - Test',
  'builder.campaign': 'Builder - Campaign',
  'execution.run': 'Execution - Run',
  'execution.monitor': 'Execution - Monitor',
  'execution.build': 'Execution - Build',
  'reports.tests': 'Reports - Tests',
  'reports.campaigns': 'Reports - Campaigns',
  'reports.models': 'Reports - Models',
  'reports.dependency': 'Reports - Dependency',
  'monitoring.incidents': 'Monitoring - Incidents',
  'monitoring.heatmap': 'Monitoring - Heatmap',
  'monitoring.ai_queue': 'Monitoring - AI Queue',
  interface: 'Interface',
  ai_agent: 'AI Agent',
  'plugins.grafana': 'Plugins - Grafana',
  'plugins.langfuse': 'Plugins - Langfuse',
  'plugins.postman': 'Plugins - Postman',
  'plugins.jira': 'Plugins - Jira',
  'plugins.slack': 'Plugins - Slack',
  'settings.general': 'Settings - General',
  'settings.models': 'Settings - Models',
  'settings.code_deploy': 'Settings - Code Deploy',
  'settings.cicd': 'Settings - CI/CD',
  'settings.branding': 'Settings - Branding',
  'settings.status': 'Settings - Status',
  'org.users': 'Org - Users',
  'org.teams': 'Org - Teams',
  'org.invite': 'Org - Invite',
  'org.workspaces': 'Org - Workspaces',
};

function getPermissionPrefix(perm: Permission): string {
  const colonIdx = perm.indexOf(':');
  return colonIdx !== -1 ? perm.substring(0, colonIdx) : perm;
}

function groupPermissions(perms: Permission[]): Record<string, Permission[]> {
  const groups: Record<string, Permission[]> = {};
  for (const perm of perms) {
    const prefix = getPermissionPrefix(perm);
    if (!groups[prefix]) groups[prefix] = [];
    groups[prefix].push(perm);
  }
  return groups;
}

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

const TabPanel: React.FC<TabPanelProps> = ({ children, value, index }) => (
  <div hidden={value !== index}>
    {value === index && <Box sx={{ pt: 2 }}>{children}</Box>}
  </div>
);

const Users: React.FC = () => {
  const {
    users,
    isLoading,
    error,
    updateUser,
    deleteUser,
    assignUserToTeam,
    isUpdating,
    isDeleting,
    updateError,
    deleteError,
  } = useUsers();

  const { teams } = useTeams();

  const [openDialog, setOpenDialog] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [activeTab, setActiveTab] = useState(0);

  const [profileData, setProfileData] = useState({
    fullName: '',
    email: '',
    role: 'tester' as 'admin' | 'tester' | 'viewer',
  });

  const [grantedPerms, setGrantedPerms] = useState<Set<Permission>>(new Set());
  const [deniedPerms, setDeniedPerms] = useState<Set<Permission>>(new Set());

  const [selectedAddTeamId, setSelectedAddTeamId] = useState('');
  const [userTeamIds, setUserTeamIds] = useState<string[]>([]);

  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  const handleOpenDialog = (user: User) => {
    setEditingUser(user);
    setActiveTab(0);
    setProfileData({
      fullName: user.full_name,
      email: user.email,
      role: user.role,
    });
    setGrantedPerms(new Set((user.permissions ?? []) as Permission[]));
    setDeniedPerms(new Set((user.denied_permissions ?? []) as Permission[]));
    const currentTeamIds = user.teams
      ? teams.filter((t) => user.teams!.includes(t.name)).map((t) => t.id)
      : user.team_id
      ? [user.team_id]
      : [];
    setUserTeamIds(currentTeamIds);
    setSelectedAddTeamId('');
    setOpenDialog(true);
  };

  const handleCloseDialog = () => {
    setOpenDialog(false);
    setEditingUser(null);
  };

  const handleSaveUser = async () => {
    if (!editingUser) return;
    try {
      await updateUser({
        id: editingUser.id,
        payload: {
          full_name: profileData.fullName,
          role: profileData.role,
          permissions: Array.from(grantedPerms),
          denied_permissions: Array.from(deniedPerms),
        },
      });
      handleCloseDialog();
    } catch (err) {
      console.error('Error saving user:', err);
    }
  };

  const handleAddTeam = async () => {
    if (!editingUser || !selectedAddTeamId) return;
    try {
      await assignUserToTeam({
        userId: editingUser.id,
        payload: { team_id: selectedAddTeamId },
      });
      setUserTeamIds((prev) => [...prev, selectedAddTeamId]);
      setSelectedAddTeamId('');
    } catch (err) {
      console.error('Error adding team:', err);
    }
  };

  const handleDeleteUser = async (userId: string) => {
    confirm({
      title: 'Confirm Delete',
      message: 'Are you sure you want to delete this user? This action cannot be undone.',
      confirmColor: 'error',
      onConfirm: async () => {
        try {
          await deleteUser(userId);
        } catch (err) {
          console.error('Error deleting user:', err);
        }
      },
    });
  };

  const toggleGranted = (perm: Permission) => {
    setGrantedPerms((prev) => {
      const next = new Set(prev);
      if (next.has(perm)) next.delete(perm);
      else next.add(perm);
      return next;
    });
  };

  const toggleDenied = (perm: Permission) => {
    setDeniedPerms((prev) => {
      const next = new Set(prev);
      if (next.has(perm)) next.delete(perm);
      else next.add(perm);
      return next;
    });
  };

  const getRoleColor = (role: string): 'secondary' | 'primary' | 'default' => {
    switch (role) {
      case 'admin': return 'secondary';
      case 'tester': return 'primary';
      default: return 'default';
    }
  };

  const permGroups = groupPermissions(ALL_PERMISSIONS);

  const availableTeamsForAdd = teams.filter((t) => !userTeamIds.includes(t.id));

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <UsersIcon fontSize="large" color="primary" />
          <Typography variant="h4" component="h1">
            Users Management
          </Typography>
        </Box>
      </Box>

      {(error || updateError || deleteError) && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error || updateError || deleteError}
        </Alert>
      )}

      {isLoading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
          <CircularProgress />
        </Box>
      ) : (
        <Card>
          <CardContent>
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
                    <TableCell><strong>User</strong></TableCell>
                    <TableCell><strong>Email</strong></TableCell>
                    <TableCell><strong>Role</strong></TableCell>
                    <TableCell><strong>Teams</strong></TableCell>
                    <TableCell><strong>Permissions</strong></TableCell>
                    <TableCell><strong>Joined</strong></TableCell>
                    <TableCell align="right"><strong>Actions</strong></TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {users.map((user) => (
                    <TableRow key={user.id}>
                      <TableCell>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <Avatar
                            src={user.avatar_url}
                            sx={{ width: 32, height: 32, bgcolor: 'primary.main' }}
                          >
                            {user.full_name?.charAt(0).toUpperCase() || user.email?.charAt(0).toUpperCase()}
                          </Avatar>
                          <Typography variant="body1" fontWeight="medium">
                            {user.full_name || 'No name'}
                          </Typography>
                        </Box>
                      </TableCell>
                      <TableCell>{user.email}</TableCell>
                      <TableCell>
                        <Chip
                          label={user.role.toUpperCase()}
                          size="small"
                          color={getRoleColor(user.role)}
                        />
                      </TableCell>
                      <TableCell>
                        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                          {user.teams && user.teams.length > 0
                            ? user.teams.map((t) => (
                                <Chip key={t} label={t} size="small" variant="outlined" />
                              ))
                            : user.team
                            ? <Chip label={user.team} size="small" variant="outlined" />
                            : <Typography variant="body2" color="text.secondary">No teams</Typography>}
                        </Box>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={user.permissions?.length ?? 0}
                          size="small"
                          color="info"
                          title={user.permissions?.join(', ')}
                        />
                      </TableCell>
                      <TableCell>{new Date(user.created_at).toLocaleDateString()}</TableCell>
                      <TableCell align="right">
                        <IconButton
                          size="small"
                          color="primary"
                          onClick={() => handleOpenDialog(user)}
                          disabled={isUpdating || isDeleting}
                        >
                          <EditIcon fontSize="small" />
                        </IconButton>
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => handleDeleteUser(user.id)}
                          disabled
                          title="Users are provisioned externally"
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))}
                  {users.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={7} align="center">
                        <Typography variant="body2" color="textSecondary" sx={{ py: 4 }}>
                          No users found.
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

      <StyledDialog open={openDialog} onClose={handleCloseDialog} maxWidth="md" fullWidth>
        <DialogTitle>Edit User</DialogTitle>
        <DialogContent>
          <Tabs value={activeTab} onChange={(_, v: number) => setActiveTab(v)} sx={{ borderBottom: 1, borderColor: 'divider' }}>
            <Tab label="Profile" />
            <Tab label="Permissions" />
            <Tab label="Teams" />
          </Tabs>

          <TabPanel value={activeTab} index={0}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <TextField
                label="Full Name"
                value={profileData.fullName}
                fullWidth
                disabled
                helperText="Managed externally"
              />
              <TextField
                label="Email"
                type="email"
                value={profileData.email}
                fullWidth
                disabled
                helperText="Email cannot be changed"
              />
              <FormControl fullWidth>
                <InputLabel>Role</InputLabel>
                <Select
                  value={profileData.role}
                  label="Role"
                  onChange={(e) =>
                    setProfileData({
                      ...profileData,
                      role: e.target.value as 'admin' | 'tester' | 'viewer',
                    })
                  }
                >
                  <MenuItem value="admin">Admin</MenuItem>
                  <MenuItem value="tester">Tester</MenuItem>
                  <MenuItem value="viewer">Viewer</MenuItem>
                </Select>
              </FormControl>
            </Box>
          </TabPanel>

          <TabPanel value={activeTab} index={1}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Individual permissions override the role defaults. Denied permissions block access even if the role grants it.
            </Typography>
            {Object.entries(permGroups).map(([prefix, perms]) => (
              <Box key={prefix} sx={{ mb: 2 }}>
                <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 0.5 }}>
                  {PERMISSION_GROUPS[prefix] ?? prefix}
                </Typography>
                <Divider sx={{ mb: 1 }} />
                {perms.map((perm) => {
                  const action = perm.substring(perm.indexOf(':') + 1);
                  return (
                    <Box key={perm} sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                      <FormGroup row sx={{ flex: 1 }}>
                        <FormControlLabel
                          control={
                            <Checkbox
                              size="small"
                              checked={grantedPerms.has(perm)}
                              onChange={() => toggleGranted(perm)}
                              color="success"
                            />
                          }
                          label={<Typography variant="body2">{action} (grant)</Typography>}
                          sx={{ minWidth: 200 }}
                        />
                        <FormControlLabel
                          control={
                            <Checkbox
                              size="small"
                              checked={deniedPerms.has(perm)}
                              onChange={() => toggleDenied(perm)}
                              color="error"
                            />
                          }
                          label={<Typography variant="body2">{action} (deny)</Typography>}
                        />
                      </FormGroup>
                    </Box>
                  );
                })}
              </Box>
            ))}
          </TabPanel>

          <TabPanel value={activeTab} index={2}>
            <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 1 }}>
              Current Teams
            </Typography>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2 }}>
              {userTeamIds.length === 0 ? (
                <Typography variant="body2" color="text.secondary">No team memberships</Typography>
              ) : (
                userTeamIds.map((tid) => {
                  const team = teams.find((t) => t.id === tid);
                  return team ? (
                    <Chip
                      key={tid}
                      label={team.name}
                      size="small"
                    />
                  ) : null;
                })
              )}
            </Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Team membership is derived from the upstream group and managed externally.
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <FormControl size="small" sx={{ minWidth: 200 }} disabled>
                <InputLabel>Add to team</InputLabel>
                <Select
                  value={selectedAddTeamId}
                  label="Add to team"
                  onChange={(e) => setSelectedAddTeamId(e.target.value)}
                >
                  {availableTeamsForAdd.map((t) => (
                    <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Button
                variant="outlined"
                size="small"
                onClick={handleAddTeam}
                disabled
              >
                Add
              </Button>
            </Box>
          </TabPanel>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDialog}>Cancel</Button>
          <Button
            onClick={handleSaveUser}
            variant="contained"
            disabled={!profileData.fullName.trim() || isUpdating}
          >
            {isUpdating ? 'Saving...' : 'Update'}
          </Button>
        </DialogActions>
      </StyledDialog>

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

export default Users;
