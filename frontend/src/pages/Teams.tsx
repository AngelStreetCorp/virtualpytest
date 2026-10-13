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
  Avatar,
  Autocomplete,
  Tabs,
  Tab,
  FormControlLabel,
  Switch,
} from '@mui/material';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { PAGE_TITLE_SX, pageSurfaceSx } from '../components/common/PageChrome';
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  Groups as TeamsIcon,
  ChevronRight as ChevronRightIcon,
  ExpandMore as ExpandMoreIcon,
  PersonAdd as PersonAddIcon,
  Close as CloseIcon,
} from '@mui/icons-material';
import { useTeams, useTeamMembers, Team, TeamMember } from '../hooks/pages/useTeams';
import { useUsers } from '../hooks/pages/useUsers';
import { useConfirmDialog } from '../hooks/useConfirmDialog';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { StyledDialog } from '../components/common/StyledDialog';
import { PermissionChecklist } from '../components/auth/PermissionChecklist';
import { DeviceScopePicker } from '../components/auth/DeviceScopePicker';
import { usePermissions } from '../hooks/auth/usePermissions';
import { ALL_PERMISSIONS, Permission } from '../types/auth';
import { api } from '../utils/apiClient';
import { buildServerUrl } from '../utils/buildUrlUtils';

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

interface TeamRowDetailProps {
  team: Team;
  allUsers: ReturnType<typeof useUsers>['users'];
  onMembersChanged: () => void;
}

const TeamRowDetail: React.FC<TeamRowDetailProps> = ({ team, allUsers, onMembersChanged }) => {
  const P = useAgentChatPalette();
  const { canAccess } = usePermissions();
  const canManageMembers = canAccess('org.teams:manage_members');
  const { data: members = [], isLoading: membersLoading, refetch } = useTeamMembers(team.id);
  const [addError, setAddError] = useState<string | null>(null);
  const [isAdding, setIsAdding] = useState(false);
  const [isRemoving, setIsRemoving] = useState<string | null>(null);

  const memberUserIds = new Set(members.map((m: TeamMember) => m.user_id));
  const availableUsers = allUsers.filter((u) => !memberUserIds.has(u.id));

  const handleAddMember = async (user: typeof allUsers[0]) => {
    setIsAdding(true);
    setAddError(null);
    try {
      await api.post(buildServerUrl(`/server/teams/${team.id}/members`), {
        user_id: user.id,
        role: 'member',
      });
      await refetch();
      onMembersChanged();
    } catch (err) {
      setAddError(err instanceof Error ? err.message : 'Failed to add member');
    } finally {
      setIsAdding(false);
    }
  };

  const handleRemoveMember = async (userId: string) => {
    setIsRemoving(userId);
    try {
      await api.delete(buildServerUrl(`/server/teams/${team.id}/members/${userId}`));
      await refetch();
      onMembersChanged();
    } catch (err) {
      console.error('Failed to remove member:', err);
    } finally {
      setIsRemoving(null);
    }
  };

  return (
    <Box sx={{ px: 3, py: 2 }}>
      {membersLoading ? (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 1 }}>
          <CircularProgress size={16} />
          <Typography variant="body2" color="text.secondary">Loading members...</Typography>
        </Box>
      ) : (
        <>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 1 }}>
            {members.map((member: TeamMember) => (
              <Chip
                key={member.id}
                avatar={
                  <Avatar src={member.avatar_url} sx={{ width: 24, height: 24 }}>
                    {member.full_name?.charAt(0).toUpperCase()}
                  </Avatar>
                }
                label={
                  <Box component="span" sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <span>{member.full_name || member.email}</span>
                    {member.team_role !== 'member' && (
                      <Typography
                        component="span"
                        variant="caption"
                        sx={{ opacity: 0.6, textTransform: 'capitalize' }}
                      >
                        ({member.team_role})
                      </Typography>
                    )}
                  </Box>
                }
                onDelete={canManageMembers ? () => handleRemoveMember(member.user_id) : undefined}
                deleteIcon={
                  isRemoving === member.user_id
                    ? <CircularProgress size={14} />
                    : <CloseIcon fontSize="small" />
                }
                disabled={isRemoving === member.user_id}
                variant="outlined"
                size="medium"
                sx={{ height: 32 }}
              />
            ))}

            {canManageMembers && (
            <Autocomplete
              size="small"
              options={availableUsers}
              getOptionLabel={(option) => option.full_name || option.email}
              onChange={(_, user) => { if (user) handleAddMember(user); }}
              value={null}
              loading={isAdding}
              disabled={isAdding}
              renderOption={(props, option) => (
                <Box component="li" {...props} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Avatar src={option.avatar_url} sx={{ width: 24, height: 24, fontSize: '0.75rem' }}>
                    {(option.full_name || option.email)?.charAt(0).toUpperCase()}
                  </Avatar>
                  <Box>
                    <Typography variant="body2">{option.full_name || 'No name'}</Typography>
                    <Typography variant="caption" color="text.secondary">{option.email}</Typography>
                  </Box>
                </Box>
              )}
              renderInput={(params) => (
                <TextField
                  {...params}
                  placeholder={members.length === 0 ? 'Add member' : 'Add'}
                  variant="outlined"
                  InputProps={{
                    ...params.InputProps,
                    startAdornment: <PersonAddIcon fontSize="small" sx={{ mr: 0.5, color: P.accentText }} />,
                  }}
                  sx={{
                    '& .MuiOutlinedInput-root': {
                      height: 32,
                      borderRadius: '16px',
                      fontSize: '0.85rem',
                      '& fieldset': { borderWidth: 1, borderColor: 'divider' },
                      '&:hover fieldset': { borderColor: 'text.secondary' },
                      '&.Mui-focused fieldset': { borderWidth: 1, borderColor: P.accent },
                    },
                  }}
                />
              )}
              sx={{ minWidth: 150 }}
              blurOnSelect
              clearOnBlur
              openOnFocus
              noOptionsText="No users available"
            />
            )}
          </Box>

          {addError && <Alert severity="error" sx={{ mt: 1 }} onClose={() => setAddError(null)}>{addError}</Alert>}
        </>
      )}
    </Box>
  );
};

const Teams: React.FC = () => {
  const P = useAgentChatPalette();
  const { canAccess } = usePermissions();
  const {
    teams,
    isLoading,
    error,
    createTeam,
    updateTeam,
    deleteTeam,
    isCreating,
    isUpdating,
    isDeleting,
    createError,
    updateError,
    deleteError,
    refetch,
  } = useTeams();

  const { users } = useUsers();

  const [openDialog, setOpenDialog] = useState(false);
  const [editingTeam, setEditingTeam] = useState<Team | null>(null);
  const [activeTab, setActiveTab] = useState(0);
  const [formData, setFormData] = useState({ name: '', description: '' });
  // The team's ceilings (TASK-31). null = no limit.
  const [teamPerms, setTeamPerms] = useState<Set<Permission> | null>(null);
  const [teamDevices, setTeamDevices] = useState<string[] | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  const toggleExpand = (teamId: string) => {
    setExpanded((prev) => ({ ...prev, [teamId]: !prev[teamId] }));
  };

  const handleOpenDialog = (team?: Team) => {
    if (team) {
      setEditingTeam(team);
      setFormData({ name: team.name, description: team.description });
      setTeamPerms(team.permissions === null ? null : new Set(team.permissions as Permission[]));
      setTeamDevices(team.allowed_devices ?? null);
    } else {
      setEditingTeam(null);
      setFormData({ name: '', description: '' });
      setTeamPerms(null);
      setTeamDevices(null);
    }
    setActiveTab(0);
    setOpenDialog(true);
  };

  const handleCloseDialog = () => {
    setOpenDialog(false);
    setEditingTeam(null);
    setFormData({ name: '', description: '' });
    setTeamPerms(null);
    setTeamDevices(null);
  };

  const handleSaveTeam = async () => {
    try {
      if (editingTeam) {
        await updateTeam({
          id: editingTeam.id,
          payload: {
            name: formData.name,
            description: formData.description,
            permissions: teamPerms === null ? null : Array.from(teamPerms),
            allowed_devices: teamDevices,
          },
        });
      } else {
        await createTeam({
          name: formData.name,
          description: formData.description,
          permissions: teamPerms === null ? null : Array.from(teamPerms),
          allowed_devices: teamDevices,
        });
      }
      handleCloseDialog();
    } catch (err) {
      console.error('Error saving team:', err);
    }
  };

  const handleDeleteTeam = async (teamId: string) => {
    confirm({
      title: 'Confirm Delete',
      message: 'Are you sure you want to delete this team?',
      confirmColor: 'error',
      onConfirm: async () => {
        try {
          await deleteTeam(teamId);
        } catch (err) {
          console.error('Error deleting team:', err);
        }
      },
    });
  };

  const toggleTeamPerm = (perm: Permission) => {
    setTeamPerms((prev) => {
      const next = new Set(prev ?? []);
      if (next.has(perm)) next.delete(perm);
      else next.add(perm);
      return next;
    });
  };


  return (
    <Box sx={pageSurfaceSx(P)}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <TeamsIcon sx={{ color: P.accentText, fontSize: 28 }} />
          <Typography component="h1" sx={PAGE_TITLE_SX}>
            Teams Management
          </Typography>
        </Box>
        {canAccess('org.teams:create') && (
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => handleOpenDialog()}
            disabled={isCreating}
          >
            Create Team
          </Button>
        )}
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
          <CardContent>
            <TableContainer component={Paper} elevation={0}>
              <Table
                sx={{
                  tableLayout: 'fixed', minWidth: 760, '& .MuiTableCell-root': { overflowWrap: 'anywhere' },
                  '& .MuiTableRow-root:hover': {
                    backgroundColor: 'transparent !important',
                  },
                }}
              >
              <colgroup><col style={{ width: 220 }} /><col /><col style={{ width: 100 }} /><col style={{ width: 170 }} /><col style={{ width: 130 }} /></colgroup>
                <TableHead>
                  <TableRow>
                    <TableCell><strong>Team Name</strong></TableCell>
                    <TableCell><strong>Description</strong></TableCell>
                    <TableCell align="center"><strong>Members</strong></TableCell>
                    <TableCell><strong>Created</strong></TableCell>
                    <TableCell align="right"><strong>Actions</strong></TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {teams.map((team) => (
                    <React.Fragment key={team.id}>
                      <TableRow>
                        <TableCell>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <IconButton size="small" onClick={() => toggleExpand(team.id)}>
                              {expanded[team.id] ? <ExpandMoreIcon fontSize="small" /> : <ChevronRightIcon fontSize="small" />}
                            </IconButton>
                            <Typography variant="body1" fontWeight="medium">
                              {team.name}
                            </Typography>
                          </Box>
                        </TableCell>
                        <TableCell>{team.description}</TableCell>
                        <TableCell align="center">
                          <Chip label={team.member_count} size="small" color="primary" />
                        </TableCell>
                        <TableCell>{new Date(team.created_at).toLocaleDateString()}</TableCell>
                        <TableCell align="right">
                          {canAccess('org.teams:edit') && (
                            <IconButton
                              size="small"
                              color="primary"
                              onClick={() => handleOpenDialog(team)}
                              disabled={isUpdating || isDeleting}
                            >
                              <EditIcon fontSize="small" />
                            </IconButton>
                          )}
                          {canAccess('org.teams:delete') && (
                            <IconButton
                              size="small"
                              color="error"
                              onClick={() => handleDeleteTeam(team.id)}
                              disabled={isUpdating || isDeleting}
                            >
                              <DeleteIcon fontSize="small" />
                            </IconButton>
                          )}
                        </TableCell>
                      </TableRow>
                      <TableRow key={`${team.id}-detail`}>
                        <TableCell colSpan={5} sx={{ py: 0, borderBottom: expanded[team.id] ? undefined : 'none' }}>
                          <Collapse in={expanded[team.id] ?? false}>
                            <TeamRowDetail
                              team={team}
                              allUsers={users}
                              onMembersChanged={refetch}
                            />
                          </Collapse>
                        </TableCell>
                      </TableRow>
                    </React.Fragment>
                  ))}
                  {teams.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={5} align="center">
                        <Typography variant="body2" color="textSecondary" sx={{ py: 4 }}>
                          No teams found. Create your first team to get started.
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
        <DialogTitle>{editingTeam ? 'Edit Team' : 'Create New Team'}</DialogTitle>
        <DialogContent>
          <Tabs value={activeTab} onChange={(_, v: number) => setActiveTab(v)} sx={{ borderBottom: 1, borderColor: 'divider' }}>
            <Tab label="Details" />
            <Tab label="Permission limit" />
            <Tab label="Device limit" />
          </Tabs>

          <TabPanel value={activeTab} index={0}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <TextField
                label="Team Name"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                fullWidth
                required
              />
              <TextField
                label="Description"
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                fullWidth
                multiline
                rows={3}
              />
            </Box>
          </TabPanel>

          <TabPanel value={activeTab} index={1}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              The most this team's members can ever hold. A team grants nothing: members get their
              permissions from their role and individual grants, and this limit caps both. For someone
              in several teams, the limits add up; the default team only counts when it is their only
              team. Changes apply at each member's next sign-in.
            </Typography>
            <FormControlLabel
              control={
                <Switch
                  checked={teamPerms === null}
                  onChange={(e) => setTeamPerms(e.target.checked ? null : new Set(ALL_PERMISSIONS))}
                />
              }
              label={teamPerms === null ? 'No limit' : `${teamPerms.size} permissions allowed`}
              sx={{ mb: 1 }}
            />
            {teamPerms !== null && (
              <PermissionChecklist isChecked={(perm) => teamPerms.has(perm)} onToggle={toggleTeamPerm} />
            )}
          </TabPanel>

          <TabPanel value={activeTab} index={2}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              The devices this team's members can work with. Roles and users can narrow it further.
            </Typography>
            <DeviceScopePicker value={teamDevices} onChange={setTeamDevices} />
          </TabPanel>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDialog}>Cancel</Button>
          <Button
            onClick={handleSaveTeam}
            variant="contained"
            disabled={!formData.name.trim() || isCreating || isUpdating}
          >
            {(isCreating || isUpdating) ? 'Saving...' : editingTeam ? 'Update' : 'Create'}
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

export default Teams;
