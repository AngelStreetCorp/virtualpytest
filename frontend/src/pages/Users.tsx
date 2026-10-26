import React, { useMemo, useState } from 'react';
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
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Chip,
  Avatar,
  Alert,
  Tabs,
  Tab,
} from '@mui/material';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { PAGE_TITLE_SX, dangerIconSx, pageSurfaceSx } from '../components/common/PageChrome';
import {
  Edit as EditIcon,
  Delete as DeleteIcon,
  People as UsersIcon,
} from '@mui/icons-material';
import { useUsers, User } from '../hooks/pages/useUsers';
import { useConfirmDialog } from '../hooks/useConfirmDialog';
import { usePermissions } from '../hooks/auth/usePermissions';
import { useAuthContext } from '../contexts/auth/AuthContext';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { StyledDialog } from '../components/common/StyledDialog';
import { TableRowsSkeleton } from '../components/common/ReportSkeleton';
import { Permission, computeEffectivePermissions, permissionSource } from '../types/auth';
import { useRoles } from '../hooks/pages/useRoles';
import { PermissionChecklist, PermissionLegend } from '../components/auth/PermissionChecklist';
import { DeviceScopePicker } from '../components/auth/DeviceScopePicker';
import { TYPOGRAPHY } from '../constants/typography';

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
  const P = useAgentChatPalette();
  const {
    users,
    isLoading,
    error,
    updateUser,
    deleteUser,
    isUpdating,
    isDeleting,
    updateError,
    deleteError,
  } = useUsers();

  const { hasPermission, role: callerRole } = usePermissions();
  const { roles, catalog, roleLabel, roleRank } = useRoles();
  const roleDevices = (r: string) => catalog.find((c) => c.role === r)?.allowed_devices ?? null;
  const { profile } = useAuthContext();
  const canEditUsers = hasPermission('org.users:edit');
  const canDeleteUsers = hasPermission('org.users:delete');
  // A non-admin only edits users, and gives roles, ranked strictly below their own
  // (enforced server-side by forbid_role_assignment).
  const callerIsAdmin = callerRole === 'admin';
  const belowCaller = (target: string) => callerIsAdmin || roleRank(target) > roleRank(callerRole);

  const [openDialog, setOpenDialog] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [activeTab, setActiveTab] = useState(0);

  const [role, setRole] = useState<User['role']>('tester');

  const [grantedPerms, setGrantedPerms] = useState<Set<Permission>>(new Set());
  const [deniedPerms, setDeniedPerms] = useState<Set<Permission>>(new Set());
  const [userDevices, setUserDevices] = useState<string[] | null>(null);


  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  const handleOpenDialog = (user: User) => {
    setEditingUser(user);
    setActiveTab(0);
    setRole(user.role);
    setGrantedPerms(new Set((user.permissions ?? []) as Permission[]));
    setDeniedPerms(new Set((user.denied_permissions ?? []) as Permission[]));
    setUserDevices(user.allowed_devices ?? null);
    setOpenDialog(true);
  };

  const handleCloseDialog = () => {
    setOpenDialog(false);
    setEditingUser(null);
  };

  // What the user gets without any individual override: the role's defaults. A team never
  // grants (TASK-31); its ceiling only caps. Follows the role picked in the Profile tab.
  const basePerms = useMemo(() => new Set<string>(roles?.[role] ?? []), [role, roles]);
  const teamCeiling = editingUser?.team_ceiling ?? null;
  const isAdmin = role === 'admin';
  const sourceOf = (perm: Permission) =>
    permissionSource(perm, role, roles?.[role], teamCeiling, Array.from(grantedPerms), Array.from(deniedPerms));
  const hasPerm = (perm: Permission) => ['role', 'grant'].includes(sourceOf(perm));
  const outsideCeiling = (perm: Permission) => !isAdmin && teamCeiling !== null && !teamCeiling.includes(perm);
  // The user's device limit must sit inside team ∩ role (the server refuses anything else).
  const deviceLimit = useMemo(() => {
    const levels = [editingUser?.team_device_ceiling ?? null, roleDevices(role)].filter(
      (l): l is string[] => l !== null,
    );
    return levels.length === 0 ? null : levels.reduce((a, b) => a.filter((k) => b.includes(k)));
  }, [editingUser, role, catalog]);

  const handleSaveUser = async () => {
    if (!editingUser) return;
    try {
      await updateUser({
        id: editingUser.id,
        payload: {
          role,
          // Store only real overrides: grants outside the base, denials inside it.
          permissions: isAdmin ? Array.from(grantedPerms) : Array.from(grantedPerms).filter((p) => !basePerms.has(p)),
          denied_permissions: isAdmin ? Array.from(deniedPerms) : Array.from(deniedPerms).filter((p) => basePerms.has(p)),
          ...(isAdmin ? {} : { allowed_devices: userDevices }),
        },
      });
      handleCloseDialog();
    } catch (err) {
      console.error('Error saving user:', err);
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

  // One checkbox per permission, ticked when the user effectively holds it. Unticking a
  // role/team permission records a denial; ticking one outside the base records a grant.
  const togglePerm = (perm: Permission) => {
    const holds = hasPerm(perm);
    const inBase = basePerms.has(perm);
    setGrantedPerms((prev) => {
      const next = new Set(prev);
      if (holds || inBase) next.delete(perm);
      else next.add(perm);
      return next;
    });
    setDeniedPerms((prev) => {
      const next = new Set(prev);
      if (holds && inBase) next.add(perm);
      else next.delete(perm);
      return next;
    });
  };

  const getRoleColor = (role: string): 'secondary' | 'primary' | 'default' => {
    if (role === 'admin') return 'secondary';
    return role === 'viewer' ? 'default' : 'primary';
  };


  return (
    <Box sx={pageSurfaceSx(P)}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <UsersIcon sx={{ color: P.accentText, fontSize: TYPOGRAPHY.kpiValue.size }} />
          <Typography component="h1" sx={PAGE_TITLE_SX}>
            Users Management
          </Typography>
        </Box>
      </Box>

      {(error || updateError || deleteError) && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error || updateError || deleteError}
        </Alert>
      )}

      <Card>
        <CardContent>
          <TableContainer component={Paper} elevation={0}>
            <Table
              sx={{
                tableLayout: 'fixed', minWidth: 900, '& .MuiTableCell-root': { overflowWrap: 'anywhere' },
                '& .MuiTableRow-root:hover': {
                  backgroundColor: 'transparent !important',
                },
              }}
            >
            <colgroup><col /><col style={{ width: 230 }} /><col style={{ width: 100 }} /><col style={{ width: 150 }} /><col style={{ width: 120 }} /><col style={{ width: 100 }} /><col style={{ width: 90 }} /></colgroup>
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
                {isLoading ? (
                  <TableRowsSkeleton widths={[null, 230, 100, 150, 120, 100, 90]} rows={8} />
                ) : users.map((user) => (
                    <TableRow key={user.id}>
                      <TableCell>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <Avatar
                            src={user.avatar_url}
                            sx={{ width: 32, height: 32, bgcolor: P.accent }}
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
                          label={roleLabel(user.role)}
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
                        {(() => {
                          const effective = computeEffectivePermissions(
                            user.role,
                            roles?.[user.role],
                            user.team_ceiling ?? null,
                            user.permissions,
                            user.denied_permissions,
                          );
                          return (
                            <Chip
                              label={user.role === 'admin' ? 'All' : effective.length}
                              size="small"
                              sx={{ bgcolor: P.hoverBg, color: P.textSecondary, fontWeight: 600 }}
                              title={effective.join(', ')}
                            />
                          );
                        })()}
                      </TableCell>
                      <TableCell>{new Date(user.created_at).toLocaleDateString()}</TableCell>
                      <TableCell align="right">
                        <IconButton
                          size="small"
                          color="primary"
                          onClick={() => handleOpenDialog(user)}
                          disabled={isUpdating || isDeleting || !canEditUsers || !belowCaller(user.role)}
                        >
                          <EditIcon fontSize="small" />
                        </IconButton>
                        {canDeleteUsers && (
                          <IconButton
                            size="small"
                            onClick={() => handleDeleteUser(user.id)}
                            disabled={isUpdating || isDeleting || user.id === profile?.id || !belowCaller(user.role)}
                            title={user.id === profile?.id ? 'You cannot delete yourself' : 'Delete user'}
                            sx={dangerIconSx(P)}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        )}
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

      <StyledDialog open={openDialog} onClose={handleCloseDialog} maxWidth="md" fullWidth>
        <DialogTitle>
          Edit User
          {editingUser && (
            <Typography component="span" variant="body2" color="text.secondary" sx={{ display: 'block' }}>
              {editingUser.full_name ? `${editingUser.full_name} · ${editingUser.email}` : editingUser.email}
            </Typography>
          )}
        </DialogTitle>
        <DialogContent>
          <Tabs value={activeTab} onChange={(_, v: number) => setActiveTab(v)} sx={{ borderBottom: 1, borderColor: 'divider' }}>
            <Tab label="Profile" />
            <Tab label="Permissions" />
            <Tab label="Devices" disabled={isAdmin} />
          </Tabs>

          <TabPanel value={activeTab} index={0}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <FormControl fullWidth>
                <InputLabel>Role</InputLabel>
                <Select
                  value={role}
                  label="Role"
                  onChange={(e) => setRole(e.target.value as User['role'])}
                >
                  {catalog.map((r) => (
                    <MenuItem key={r.role} value={r.role} disabled={!belowCaller(r.role)}>
                      {r.display_name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Box>
          </TabPanel>

          <TabPanel value={activeTab} index={1}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              {isAdmin
                ? 'Admins hold every permission; they cannot be restricted.'
                : 'Ticked = the user has it. Untick a role permission to deny it; tick any other to grant it. A user never holds more than their teams allow.'}
            </Typography>
            {!isAdmin && (
              <PermissionLegend
                items={[
                  { color: 'text.primary', label: 'From the role' },
                  { color: 'success.main', label: 'Extra grant (beyond the role)' },
                  { color: 'error.main', label: 'Denied' },
                  { color: 'warning.main', label: 'Blocked by the team limit' },
                  { color: 'text.disabled', label: 'Not held' },
                ]}
              />
            )}
            {!isAdmin && teamCeiling !== null && (
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                The user's teams allow {teamCeiling.length} permissions; everything else is locked.
                Changing a team limit applies at the user's next sign-in.
              </Typography>
            )}
            <PermissionChecklist
              isChecked={hasPerm}
              onToggle={togglePerm}
              isDisabled={(perm) => isAdmin || outsideCeiling(perm)}
              labelColor={(perm) => {
                if (isAdmin) return undefined;
                return {
                  role: 'text.primary',
                  grant: 'success.main',
                  denied: 'error.main',
                  capped: 'warning.main',
                  none: 'text.disabled',
                }[sourceOf(perm)];
              }}
              renderTag={(perm) => {
                if (isAdmin) return null;
                const tag = { grant: 'extra', denied: 'denied', capped: 'team limit' }[
                  sourceOf(perm) as 'grant' | 'denied' | 'capped'
                ];
                return tag && (
                  <Typography component="span" variant="caption" sx={{ ml: 1 }}>
                    {tag}
                  </Typography>
                );
              }}
            />
          </TabPanel>

          <TabPanel value={activeTab} index={2}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Devices this user works with, inside what their teams and role allow.
            </Typography>
            <DeviceScopePicker
              value={userDevices}
              onChange={setUserDevices}
              limit={deviceLimit}
              limitLabel="team and role"
            />
          </TabPanel>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDialog}>Cancel</Button>
          <Button
            onClick={handleSaveUser}
            variant="contained"
            disabled={isUpdating}
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
