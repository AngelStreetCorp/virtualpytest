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
  Chip,
  Alert,
  TextField,
  Stack,
  Divider,
} from '@mui/material';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { PAGE_TITLE_SX, pageSurfaceSx } from '../components/common/PageChrome';
import {
  Edit as EditIcon,
  AdminPanelSettings as RolesIcon,
} from '@mui/icons-material';
import { useRoles } from '../hooks/pages/useRoles';
import { useUsers } from '../hooks/pages/useUsers';
import { usePermissions } from '../hooks/auth/usePermissions';
import { StyledDialog } from '../components/common/StyledDialog';
import { TableRowsSkeleton } from '../components/common/ReportSkeleton';
import { PermissionChecklist } from '../components/auth/PermissionChecklist';
import { DeviceScopePicker } from '../components/auth/DeviceScopePicker';
import { ALL_PERMISSIONS, Permission, Role, RoleInfo } from '../types/auth';
import { TYPOGRAPHY } from '../constants/typography';

const ROLE_DESCRIPTION: Record<Role, string> = {
  admin: 'Holds every permission. Cannot be restricted.',
  manager: 'Manages the people of their own teams. Cannot touch admin settings.',
  developer: 'Builds navigation trees, tests and campaigns, and runs them.',
  tester: 'Builds and runs tests and campaigns.',
  viewer: 'Read-only. Can only be given view permissions.',
};

const isViewPermission = (perm: Permission) => perm.endsWith(':view');

/**
 * The permissions the app can honour.
 *
 * A stored role can hold permissions the app has no route for: the projects
 * migration (20261006a_projects.sql) seeded team:projects:view / :edit / :delete
 * into the role rows, and no project route but POST checks them, so they gate
 * nothing. They are in neither the frontend registry nor the backend one, which
 * made this page count 3 permissions more than the Users page counted for the
 * same role, and made every save of those roles fail (BUG-0787).
 */
const KNOWN_PERMISSIONS = new Set<string>(ALL_PERMISSIONS);

const knownPermissions = (permissions: readonly string[] | undefined): Permission[] =>
  (permissions ?? []).filter((p): p is Permission => KNOWN_PERMISSIONS.has(p));

const unknownPermissions = (permissions: readonly string[] | undefined): string[] =>
  (permissions ?? []).filter((p) => !KNOWN_PERMISSIONS.has(p));

const Roles: React.FC = () => {
  const P = useAgentChatPalette();
  const { roles, catalog, adminOnly, isLoading, error, updateRole, isUpdating, updateError } = useRoles();
  const { users } = useUsers();
  const { hasPermission } = usePermissions();
  const canEditRoles = hasPermission('org.roles:edit');

  const [editing, setEditing] = useState<RoleInfo | null>(null);
  const [displayName, setDisplayName] = useState('');
  const [selected, setSelected] = useState<Set<Permission>>(new Set());
  const [roleDevices, setRoleDevices] = useState<string[] | null>(null);

  const handleOpenDialog = (info: RoleInfo) => {
    setEditing(info);
    setDisplayName(info.display_name);
    // Only the permissions the app knows: the stored list can hold permissions that
    // gate nothing, and sending them back would make the save fail (BUG-0787).
    setSelected(new Set(knownPermissions(roles?.[info.role])));
    setRoleDevices(info.allowed_devices ?? null);
  };

  const handleCloseDialog = () => setEditing(null);

  const togglePerm = (perm: Permission) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(perm)) next.delete(perm);
      else next.add(perm);
      return next;
    });
  };

  const handleSave = async () => {
    if (!editing) return;
    try {
      await updateRole({
        role: editing.role,
        display_name: displayName.trim(),
        ...(editing.editable ? { permissions: Array.from(selected), allowed_devices: roleDevices } : {}),
      });
      handleCloseDialog();
    } catch (err) {
      console.error('Error saving role:', err);
    }
  };

  const isViewer = editing?.role === 'viewer';
  const grantable = ALL_PERMISSIONS.filter((p) => !adminOnly.has(p) && (!isViewer || isViewPermission(p)));

  return (
    <Box sx={pageSurfaceSx(P)}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
        <RolesIcon sx={{ color: P.accentText, fontSize: TYPOGRAPHY.kpiValue.size }} />
        <Typography component="h1" sx={PAGE_TITLE_SX}>
          Roles Management
        </Typography>
      </Box>

      {(error || updateError) && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error || updateError}
        </Alert>
      )}

      <Card>
        <CardContent>
          <TableContainer component={Paper} elevation={0}>
            <Table sx={{ tableLayout: 'fixed', minWidth: 760, '& .MuiTableCell-root': { overflowWrap: 'anywhere' } }}>
<colgroup><col style={{ width: 150 }} /><col /><col style={{ width: 140 }} /><col style={{ width: 90 }} /><col style={{ width: 120 }} /></colgroup>
              <TableHead>
                <TableRow>
                  <TableCell><strong>Role</strong></TableCell>
                  <TableCell><strong>Description</strong></TableCell>
                  <TableCell><strong>Permissions</strong></TableCell>
                  <TableCell><strong>Users</strong></TableCell>
                  <TableCell align="right"><strong>Actions</strong></TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {isLoading ? (
                  <TableRowsSkeleton widths={[150, null, 140, 90, 120]} rows={6} />
                ) : catalog.map((info) => {
                    const perms = roles?.[info.role] ?? [];
                    return (
                      <TableRow key={info.role}>
                        <TableCell>
                          <Typography variant="body2" fontWeight="bold">{info.display_name}</Typography>
                          <Typography variant="caption" color="text.secondary">{info.role}</Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" color="text.secondary">
                            {ROLE_DESCRIPTION[info.role]}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          {/* The count is the number of permissions the app honours, so it
                              matches what the Users page counts for the same role (BUG-0787). */}
                          <Chip
                            label={info.editable ? knownPermissions(perms).length : 'All'}
                            size="small"
                            sx={{ bgcolor: P.hoverBg, color: P.textSecondary, fontWeight: 600 }}
                            title={knownPermissions(perms).join(', ')}
                          />
                        </TableCell>
                        <TableCell>{users.filter((u) => u.role === info.role).length}</TableCell>
                        <TableCell align="right">
                          <IconButton
                            size="small"
                            color="primary"
                            onClick={() => handleOpenDialog(info)}
                            disabled={!canEditRoles || isUpdating}
                            title="Edit role"
                          >
                            <EditIcon fontSize="small" />
                          </IconButton>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          </CardContent>
        </Card>

      <StyledDialog open={editing !== null} onClose={handleCloseDialog} maxWidth="md" fullWidth>
        <DialogTitle>
          Edit Role
          {editing && (
            <Typography component="span" variant="body2" color="text.secondary" sx={{ display: 'block' }}>
              {editing.role}
              {editing.editable && ` · ${selected.size} of ${grantable.length} permissions`}
            </Typography>
          )}
        </DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="Preferred name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              helperText="Shown for this role everywhere in the app. An external platform that creates users sends this name (e.g. SuperAdmin) and it is mapped to this role. Unique across roles."
              size="small"
              fullWidth
              required
            />

            <Divider />

            {editing?.editable && unknownPermissions(roles?.[editing.role]).length > 0 && (
              <Alert severity="info" icon={false}>
                {unknownPermissions(roles?.[editing.role]).length} stored permission(s) are not used by
                the app and are not shown here: {unknownPermissions(roles?.[editing.role]).join(', ')}.
                They gate nothing, and saving this role removes them.
              </Alert>
            )}

            {editing?.editable ? (
              <Box>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  {isViewer
                    ? 'Viewers are read-only: only view permissions can be given. Untick a view to hide that page from every viewer.'
                    : 'Default permissions of every user with this role.'}{' '}
                  Admin-only permissions (roles, team limits, server settings, deploys, hosts, security)
                  cannot be given to any role.
                </Typography>
                <PermissionChecklist
                  isChecked={(perm) => selected.has(perm)}
                  onToggle={togglePerm}
                  isDisabled={(perm) => adminOnly.has(perm) || (isViewer && !isViewPermission(perm))}
                />
              </Box>
            ) : (
              <Typography variant="body2" color="text.secondary">
                Admin holds every permission and sees every device; only its preferred name can be changed.
              </Typography>
            )}

            {editing?.editable && (
              <>
                <Divider />
                <Box>
                  <Typography variant="subtitle2">Device limit</Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    Devices users with this role can work with, inside what their teams allow.
                  </Typography>
                  <DeviceScopePicker value={roleDevices} onChange={setRoleDevices} />
                </Box>
              </>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDialog}>Cancel</Button>
          <Button onClick={handleSave} variant="contained" disabled={isUpdating || !displayName.trim()}>
            {isUpdating ? 'Saving...' : 'Update'}
          </Button>
        </DialogActions>
      </StyledDialog>
    </Box>
  );
};

export default Roles;
