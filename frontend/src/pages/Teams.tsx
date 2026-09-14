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
  Checkbox,
  FormControlLabel,
  FormGroup,
  Divider,
} from '@mui/material';
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
import { ALL_PERMISSIONS, Permission } from '../types/auth';
import { api } from '../utils/apiClient';
import { buildServerUrl } from '../utils/buildUrlUtils';

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

interface TeamRowDetailProps {
  team: Team;
  allUsers: ReturnType<typeof useUsers>['users'];
  onMembersChanged: () => void;
}

const TeamRowDetail: React.FC<TeamRowDetailProps> = ({ team, allUsers, onMembersChanged }) => {
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
                onDelete={() => handleRemoveMember(member.user_id)}
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
                    startAdornment: <PersonAddIcon fontSize="small" sx={{ mr: 0.5, color: 'primary.main' }} />,
                  }}
                  sx={{
                    '& .MuiOutlinedInput-root': {
                      height: 32,
                      borderRadius: 4,
                      borderStyle: 'dashed',
                      fontSize: '0.85rem',
                      '& fieldset': { borderStyle: 'dashed' },
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
          </Box>

          {addError && <Alert severity="error" sx={{ mt: 1 }} onClose={() => setAddError(null)}>{addError}</Alert>}
        </>
      )}
    </Box>
  );
};

const Teams: React.FC = () => {
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
  const [teamPerms, setTeamPerms] = useState<Set<Permission>>(new Set());
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  const toggleExpand = (teamId: string) => {
    setExpanded((prev) => ({ ...prev, [teamId]: !prev[teamId] }));
  };

  const handleOpenDialog = (team?: Team) => {
    if (team) {
      setEditingTeam(team);
      setFormData({ name: team.name, description: team.description });
      setTeamPerms(new Set());
    } else {
      setEditingTeam(null);
      setFormData({ name: '', description: '' });
      setTeamPerms(new Set());
    }
    setActiveTab(0);
    setOpenDialog(true);
  };

  const handleCloseDialog = () => {
    setOpenDialog(false);
    setEditingTeam(null);
    setFormData({ name: '', description: '' });
    setTeamPerms(new Set());
  };

  const handleSaveTeam = async () => {
    try {
      if (editingTeam) {
        await updateTeam({
          id: editingTeam.id,
          payload: {
            name: formData.name,
            description: formData.description,
            permissions: Array.from(teamPerms),
          },
        });
      } else {
        await createTeam({
          name: formData.name,
          description: formData.description,
          permissions: Array.from(teamPerms),
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
      const next = new Set(prev);
      if (next.has(perm)) next.delete(perm);
      else next.add(perm);
      return next;
    });
  };

  const permGroups = groupPermissions(ALL_PERMISSIONS);

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <TeamsIcon fontSize="large" color="primary" />
          <Typography variant="h4" component="h1">
            Teams Management
          </Typography>
        </Box>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => handleOpenDialog()}
          disabled={isCreating}
        >
          Create Team
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
                          <IconButton
                            size="small"
                            color="primary"
                            onClick={() => handleOpenDialog(team)}
                            disabled={isUpdating || isDeleting}
                          >
                            <EditIcon fontSize="small" />
                          </IconButton>
                          <IconButton
                            size="small"
                            color="error"
                            onClick={() => handleDeleteTeam(team.id)}
                            disabled={isUpdating || isDeleting}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
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
            <Tab label="Permissions" />
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
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Permissions granted here apply to all members of this team.
            </Typography>
            {Object.entries(permGroups).map(([prefix, perms]) => (
              <Box key={prefix} sx={{ mb: 2 }}>
                <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 0.5 }}>
                  {PERMISSION_GROUPS[prefix] ?? prefix}
                </Typography>
                <Divider sx={{ mb: 1 }} />
                <FormGroup row>
                  {perms.map((perm) => {
                    const action = perm.substring(perm.indexOf(':') + 1);
                    return (
                      <FormControlLabel
                        key={perm}
                        control={
                          <Checkbox
                            size="small"
                            checked={teamPerms.has(perm)}
                            onChange={() => toggleTeamPerm(perm)}
                            color="success"
                          />
                        }
                        label={<Typography variant="body2">{action}</Typography>}
                        sx={{ minWidth: 200 }}
                      />
                    );
                  })}
                </FormGroup>
              </Box>
            ))}
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
