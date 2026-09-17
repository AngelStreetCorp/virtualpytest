import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  Save as SaveIcon,
  Cancel as CancelIcon,
  Launch as LaunchIcon,
  ContentCopy as DuplicateIcon,
  Tune as TuneIcon,
  AccountTreeOutlined as DomIcon,
  Download as ExportIcon,
  Upload as ImportIcon,
  MoreVert as MoreIcon,
  Publish as PublishIcon,
} from '@mui/icons-material';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  TextField,
  IconButton,
  DialogTitle,
  DialogContent,
  DialogActions,
  Alert,
  Chip,
  CircularProgress,
  Backdrop,
  Autocomplete,
  Tooltip,
  Menu,
  MenuItem,
  ListItemIcon,
  ListItemText,
  Divider,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material';
import React, { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';

import { useUserInterface } from '../hooks/pages/useUserInterface';
import { useDeviceModels } from '../hooks/pages/useDeviceModels';
import { useResponsiveMode } from '../hooks/useResponsiveMode';
import {
  primeAllVariants,
  useUserInterfaceVariants,
} from '../hooks/userinterface/useUserInterfaceVariants';
import { useConfirmDialog } from '../hooks/useConfirmDialog';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { StyledDialog } from '../components/common/StyledDialog';
import UserInterface_VariantsSection from '../components/userinterface/UserInterface_VariantsSection';
import {
  UserInterface as UserInterfaceType,
  UserInterfaceCreatePayload,
} from '../types/pages/UserInterface_Types';
import { buildServerUrl } from '../utils/buildUrlUtils';

// Collapse min/max into a single "min - max" cell to save a column.
const formatVersionRange = (ui: UserInterfaceType): string => {
  const min = (ui.min_version || '').trim();
  const max = (ui.max_version || '').trim();
  if (!min && !max) return 'N/A';
  return `${min || 'N/A'} - ${max || 'N/A'}`;
};

const isProd = (ui: UserInterfaceType) => ui.mode === 'prod';

// dev = outlined chip, prod = gold filled chip (matches the run-picker badges).
const ModeChip: React.FC<{ ui: UserInterfaceType }> = ({ ui }) => (
  <Chip
    label={isProd(ui) ? 'prod' : 'dev'}
    size="small"
    variant={isProd(ui) ? 'filled' : 'outlined'}
    sx={{
      height: 18,
      ml: 0.5,
      '& .MuiChip-label': { px: 0.5, fontSize: '0.65rem', fontWeight: 600 },
      ...(isProd(ui)
        ? { bgcolor: '#b8860b', color: '#fff' }
        : { color: 'text.secondary' }),
    }}
  />
);

// One <VariantsCell> per row, hydrated from the cache primeAllVariants fills
// on mount — so the rows issue no requests of their own. The module cache only
// dedupes repeats for the SAME id, so without the prime this was an N+1: one
// GET per interface, all serializing on the single-worker backend.
const VariantsCell: React.FC<{ userInterfaceId: string }> = ({ userInterfaceId }) => {
  const { variants, loading } = useUserInterfaceVariants(userInterfaceId);

  if (loading && variants.length === 0) {
    return <CircularProgress size={14} />;
  }
  if (variants.length === 0) {
    return (
      <Typography variant="caption" color="text.disabled">
        —
      </Typography>
    );
  }
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
      {variants.map((v) => (
        <Chip
          key={v.name}
          label={v.name}
          size="small"
          variant="outlined"
          sx={{ height: 20, '& .MuiChip-label': { px: 0.5, fontSize: '0.75rem' } }}
        />
      ))}
    </Box>
  );
};

const UserInterface: React.FC = () => {
  // Get navigation hook
  const navigate = useNavigate();
  const { isMobile } = useResponsiveMode();

  // Get the hook functions
  const {
    getAllUserInterfaces,
    updateUserInterfaceWithValidation,
    deleteUserInterface,
    createUserInterfaceWithValidation,
    duplicateUserInterface,
    publishUserInterface,
    exportUserInterface,
    importUserInterface,
  } = useUserInterface();

  const [userInterfaces, setUserInterfaces] = useState<UserInterfaceType[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState({
    name: '',
    models: [] as string[],
    min_version: '',
    max_version: '',
  });
  const [openDialog, setOpenDialog] = useState(false);
  const [newInterface, setNewInterface] = useState({
    name: '',
    models: [] as string[],
    min_version: '',
    max_version: '',
  });
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Dev/prod filter (top-right toggle, like the execution-type filter on ModelReports).
  const [modeFilter, setModeFilter] = useState<'all' | 'dev' | 'prod'>('all');
  // Duplication copies every reference image server-side, so it can run for a
  // while. Hold the name of the UI being duplicated to show a blocking overlay
  // (separate from `submitting` so the message reads specifically as "copying").
  const [duplicatingName, setDuplicatingName] = useState<string | null>(null);
  // Publishing also copies references server-side — same blocking overlay.
  const [publishingName, setPublishingName] = useState<string | null>(null);

  // Import (.vptree bundle) dialog state.
  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importName, setImportName] = useState('');
  const [importing, setImporting] = useState(false);

  // Confirmation dialog
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  // Single row-actions ⋮ menu shared by all rows; anchored to the clicked button.
  const [actionMenu, setActionMenu] = useState<{
    anchorEl: HTMLElement;
    ui: UserInterfaceType;
  } | null>(null);
  const closeActionMenu = () => setActionMenu(null);

  // Variants manager modal — Phase 2 of named-variant feature.
  // List page → modal pattern keeps the page additive (no detail route added).
  const [variantsModalUi, setVariantsModalUi] = useState<UserInterfaceType | null>(null);
  const handleOpenVariants = (userInterface: UserInterfaceType) =>
    setVariantsModalUi(userInterface);
  const handleCloseVariants = () => setVariantsModalUi(null);

  // Display order: each prod row right after its dev source, then the mode filter.
  const visibleInterfaces = useMemo(() => {
    const prodByDevId = new Map(
      userInterfaces.filter((ui) => isProd(ui) && ui.dev_userinterface_id)
        .map((ui) => [ui.dev_userinterface_id as string, ui]),
    );
    const ordered: UserInterfaceType[] = [];
    for (const ui of userInterfaces) {
      if (isProd(ui)) continue;
      ordered.push(ui);
      const prod = prodByDevId.get(ui.id);
      if (prod) ordered.push(prod);
    }
    if (modeFilter === 'all') return ordered;
    return ordered.filter((ui) => (modeFilter === 'prod' ? isProd(ui) : !isProd(ui)));
  }, [userInterfaces, modeFilter]);

  // Real models from database (same hook as Models page — shares cache)
  const { models: deviceModels } = useDeviceModels();
  const availableModels = useMemo(
    () => deviceModels.map((model) => model.name).sort(),
    [deviceModels],
  );

  // Load data on component mount only
  useEffect(() => {
    const loadUserInterfaces = async () => {
      try {
        setLoading(true);
        setError(null);
        const interfaces = await getAllUserInterfaces();
        // Prime every row's variants with ONE request before the rows mount —
        // each <VariantsCell> would otherwise fire its own GET (one per
        // interface). Deliberately not awaited: the table renders immediately
        // and the cells resolve from cache as the batch lands.
        primeAllVariants(interfaces.map((ui) => ui.id));
        setUserInterfaces(interfaces);
      } catch (err) {
        console.error('[@component:UserInterface] Error loading user interfaces:', err);
        setError(err instanceof Error ? err.message : 'Failed to load user interfaces');
      } finally {
        setLoading(false);
      }
    };

    loadUserInterfaces();
  }, [getAllUserInterfaces]);

  const handleEdit = (userInterface: UserInterfaceType) => {
    setEditingId(userInterface.id);
    setEditForm({
      name: userInterface.name,
      models: userInterface.models,
      min_version: userInterface.min_version || '',
      max_version: userInterface.max_version || '',
    });
  };

  const handleSaveEdit = async () => {
    try {
      setSubmitting(true);
      setError(null);

      const payload: UserInterfaceCreatePayload = {
        name: editForm.name,
        models: editForm.models,
        min_version: editForm.min_version,
        max_version: editForm.max_version,
      };

      const updatedInterface = await updateUserInterfaceWithValidation(
        editingId!,
        payload,
        userInterfaces,
      );

      // Update local state
      setUserInterfaces(userInterfaces.map((ui) => (ui.id === editingId ? updatedInterface : ui)));
      setEditingId(null);
      console.log(
        '[@component:UserInterface] Successfully updated user interface:',
        updatedInterface.name,
      );
    } catch (err) {
      console.error('[@component:UserInterface] Error updating user interface:', err);
      setError(err instanceof Error ? err.message : 'Failed to update user interface');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancelEdit = () => {
    setEditingId(null);
    setEditForm({ name: '', models: [], min_version: '', max_version: '' });
    setError(null);
  };

  const handleDelete = async (id: string) => {
    confirm({
      title: 'Confirm Delete',
      message: 'Are you sure you want to delete this user interface?',
      confirmColor: 'error',
      onConfirm: async () => {
        // Optimistic: drop the row immediately. The backend deletes the DB row
        // fast and reclaims storage in the background, so the user shouldn't wait.
        const prev = userInterfaces;
        setError(null);
        setUserInterfaces((list) => list.filter((ui) => ui.id !== id));
        try {
          await deleteUserInterface(id);
          console.log('[@component:UserInterface] Successfully deleted user interface');
        } catch (err) {
          console.error('[@component:UserInterface] Error deleting user interface:', err);
          // Restore the row on failure so the UI reflects reality.
          setUserInterfaces(prev);
          setError(err instanceof Error ? err.message : 'Failed to delete user interface');
        }
      },
    });
  };

  const handleDuplicate = async (userInterface: UserInterfaceType) => {
    try {
      setError(null);
      setSubmitting(true);
      setDuplicatingName(userInterface.name);

      const duplicatedInterface = await duplicateUserInterface(userInterface, userInterfaces);

      // Update local state
      setUserInterfaces([...userInterfaces, duplicatedInterface]);
      console.log(
        '[@component:UserInterface] Successfully duplicated user interface:',
        duplicatedInterface.name,
      );
    } catch (err) {
      console.error('[@component:UserInterface] Error duplicating user interface:', err);
      setError(err instanceof Error ? err.message : 'Failed to duplicate user interface');
    } finally {
      setSubmitting(false);
      setDuplicatingName(null);
    }
  };

  const handlePublish = (userInterface: UserInterfaceType) => {
    const existingProd = userInterfaces.find(
      (ui) => isProd(ui) && ui.dev_userinterface_id === userInterface.id,
    );
    confirm({
      title: `Publish "${userInterface.name}" to production?`,
      message: existingProd
        ? `Overwrites prod v${existingProd.published_version ?? '?'} with the current dev content. Prod metrics & history are preserved.`
        : 'Creates the production version as a full copy of the current dev content.',
      onConfirm: async () => {
        try {
          setError(null);
          setPublishingName(userInterface.name);
          await publishUserInterface(userInterface);
          // Reload so the prod row (and its bumped version) shows up.
          const interfaces = await getAllUserInterfaces();
          primeAllVariants(interfaces.map((ui) => ui.id));
          setUserInterfaces(interfaces);
          console.log('[@component:UserInterface] Successfully published:', userInterface.name);
        } catch (err) {
          console.error('[@component:UserInterface] Error publishing user interface:', err);
          setError(err instanceof Error ? err.message : 'Failed to publish user interface');
        } finally {
          setPublishingName(null);
        }
      },
    });
  };

  const handleExport = async (userInterface: UserInterfaceType) => {
    try {
      setError(null);
      await exportUserInterface(userInterface);
    } catch (err) {
      console.error('[@component:UserInterface] Error exporting user interface:', err);
      setError(err instanceof Error ? err.message : 'Failed to export user interface');
    }
  };

  const handleOpenImport = () => {
    setImportFile(null);
    setImportName('');
    setError(null);
    setImportOpen(true);
  };

  // Default the new name to the bundle filename (minus .vptree) so the common case
  // is one click. Uniqueness is enforced server-side and surfaced as an error.
  const handleImportFileSelected = (file: File | null) => {
    setImportFile(file);
    if (file && !importName) {
      setImportName(file.name.replace(/\.vptree$/i, ''));
    }
  };

  const handleImport = async () => {
    if (!importFile || !importName.trim()) return;
    try {
      setImporting(true);
      setError(null);
      const imported = await importUserInterface(importFile, importName.trim());
      setUserInterfaces([...userInterfaces, imported]);
      setImportOpen(false);
      console.log('[@component:UserInterface] Successfully imported user interface:', imported.name);
    } catch (err) {
      console.error('[@component:UserInterface] Error importing user interface:', err);
      setError(err instanceof Error ? err.message : 'Failed to import user interface');
    } finally {
      setImporting(false);
    }
  };

  const handleAddNew = async () => {
    try {
      setSubmitting(true);
      setError(null);

      const payload: UserInterfaceCreatePayload = {
        name: newInterface.name,
        models: newInterface.models,
        min_version: newInterface.min_version,
        max_version: newInterface.max_version,
      };

      const createdInterface = await createUserInterfaceWithValidation(
        payload,
        userInterfaces,
        { createNavigationConfig: true },
      );

      // Update local state
      setUserInterfaces([...userInterfaces, createdInterface]);
      setNewInterface({ name: '', models: [], min_version: '', max_version: '' });
      setOpenDialog(false);
      console.log(
        '[@component:UserInterface] Successfully created user interface:',
        createdInterface.name,
      );
    } catch (err) {
      console.error('[@component:UserInterface] Error creating user interface:', err);
      setError(err instanceof Error ? err.message : 'Failed to create user interface');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCloseDialog = () => {
    setOpenDialog(false);
    setNewInterface({ name: '', models: [], min_version: '', max_version: '' });
    setError(null);
  };

  // Handle edit navigation functionality
  const handleEditNavigation = (userInterface: UserInterfaceType) => {
    try {
      console.log('[@component:UserInterface] Opening navigation editor for userinterface:', {
        interfaceId: userInterface.id,
        interfaceName: userInterface.name,
        models: userInterface.models,
      });

      // Navigate to navigation editor using React Router navigation with state
      // This matches our simplified config system: {userinterface_name}.json
      // Prod opens read-only; ?mode=prod keeps deep links unambiguous (the name
      // is shared between the dev and prod rows).
      const prod = isProd(userInterface);
      const url = `/navigation-editor/${encodeURIComponent(userInterface.name)}${prod ? '?mode=prod' : ''}`;
      navigate(url, {
        state: {
          userInterface: {
            id: userInterface.id,
            name: userInterface.name,
            models: userInterface.models,
            mode: userInterface.mode || 'dev',
          },
        },
      });
    } catch (err) {
      console.error('[@component:UserInterface] Error opening navigation editor:', err);
      setError('Failed to open navigation editor. Please try again.');
    }
  };

  // Loading state component
  const LoadingState = () => (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        py: 8,
        textAlign: 'center',
      }}
    >
      <CircularProgress size={40} sx={{ mb: 2 }} />
      <Typography variant="h6" color="text.secondary">
        Loading User Interfaces...
      </Typography>
    </Box>
  );

  // Empty state component
  const EmptyState = () => (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        py: 8,
        textAlign: 'center',
      }}
    >
      <Typography variant="h6" color="text.secondary" gutterBottom>
        No User Interface Created
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3, maxWidth: 400 }}>
        Create your first user interface to define navigation structures and device compatibility
        for your test automation.
      </Typography>
    </Box>
  );

  return (
    <Box>
      <Box
        sx={{
          mb: 2,
          display: 'flex',
          flexDirection: isMobile ? 'column' : 'row',
          justifyContent: 'space-between',
          alignItems: isMobile ? 'stretch' : 'center',
          gap: isMobile ? 1 : 0,
        }}
      >
        <Box>
          <Typography variant={isMobile ? 'h5' : 'h4'} gutterBottom>
            Interface
          </Typography>
          <Typography variant="body1" color="textSecondary">
            Manage navigation and device compatibility for your test automation.
          </Typography>
        </Box>
        <Box
          sx={{
            display: 'flex',
            gap: 1,
            alignItems: 'center',
            flexWrap: 'wrap',
            justifyContent: isMobile ? 'flex-start' : 'flex-end',
          }}
        >
          <ToggleButtonGroup
            value={modeFilter}
            exclusive
            onChange={(_, value) => value && setModeFilter(value)}
            size="small"
            aria-label="dev/prod filter"
          >
            <ToggleButton value="all" sx={{ px: isMobile ? 0.75 : 1, py: 0.25 }}>
              All
            </ToggleButton>
            <ToggleButton value="dev" sx={{ px: isMobile ? 0.75 : 1, py: 0.25 }}>
              Dev
            </ToggleButton>
            <ToggleButton value="prod" sx={{ px: isMobile ? 0.75 : 1, py: 0.25 }}>
              Prod
            </ToggleButton>
          </ToggleButtonGroup>
          <Button
            variant="outlined"
            startIcon={!isMobile ? <ImportIcon /> : undefined}
            onClick={handleOpenImport}
            size="small"
            disabled={loading}
            aria-label="Import"
            sx={isMobile ? { minWidth: 0, px: 1 } : undefined}
          >
            {isMobile ? <ImportIcon fontSize="small" /> : 'Import'}
          </Button>
          <Button
            variant="contained"
            startIcon={!isMobile ? <AddIcon /> : undefined}
            onClick={() => setOpenDialog(true)}
            size="small"
            disabled={loading}
            aria-label="Add UI"
            sx={isMobile ? { minWidth: 0, px: 1 } : undefined}
          >
            {isMobile ? <AddIcon fontSize="small" /> : 'Add UI'}
          </Button>
        </Box>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Card sx={{ boxShadow: 1 }}>
        <CardContent sx={{ p: 1, '&:last-child': { pb: 1 } }}>
          {loading ? (
            <LoadingState />
          ) : userInterfaces.length === 0 ? (
            <EmptyState />
          ) : (
            <TableContainer
              component={Paper}
              variant="outlined"
              sx={{ boxShadow: 'none', overflowX: 'hidden' }}
            >
              <Table
                size="small"
                sx={{
                  tableLayout: 'fixed',
                  width: '100%',
                  '& .MuiTableCell-root': {
                    py: 0.5,
                    px: 1,
                    wordBreak: 'break-word',
                  },
                  '& .MuiTableBody-root .MuiTableRow-root:hover': {
                    backgroundColor: 'transparent !important',
                  },
                  '& .MuiTableHead-root .MuiTableRow-root:hover': {
                    backgroundColor: 'transparent !important',
                  },
                }}
              >
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ width: isMobile ? '45%' : '24%' }}>
                      <strong>Name</strong>
                    </TableCell>
                    <TableCell sx={{ width: isMobile ? '30%' : '22%' }}>
                      <strong>Models</strong>
                    </TableCell>
                    {!isMobile && (
                      <TableCell sx={{ width: '10%' }}>
                        <strong>Version</strong>
                      </TableCell>
                    )}
                    <TableCell sx={{ width: isMobile ? '15%' : '16%' }}>
                      <strong>Variants</strong>
                    </TableCell>
                    {!isMobile && (
                      <>
                        <TableCell align="center" sx={{ width: '9%', whiteSpace: 'nowrap' }}>
                          <strong>Navigation</strong>
                        </TableCell>
                        <TableCell align="center" sx={{ width: '9%', whiteSpace: 'nowrap' }}>
                          <strong>References</strong>
                        </TableCell>
                      </>
                    )}
                    <TableCell align="center" sx={{ width: isMobile ? '10%' : '10%', whiteSpace: 'nowrap' }}>
                      <strong>Actions</strong>
                    </TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {visibleInterfaces.map((userInterface) => (
                    <TableRow
                      key={userInterface.id}
                      onClick={
                        isMobile && editingId !== userInterface.id
                          ? () => handleEditNavigation(userInterface)
                          : undefined
                      }
                      sx={{ cursor: isMobile && editingId !== userInterface.id ? 'pointer' : 'default' }}
                    >
                      <TableCell>
                        {editingId === userInterface.id ? (
                          <TextField
                            size="small"
                            value={editForm.name}
                            onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                            fullWidth
                            variant="outlined"
                            sx={{
                              '& .MuiInputBase-root': { height: '32px' },
                              '& .MuiInputBase-input': { fontSize: '0.75rem', p: '4px 6px' },
                            }}
                          />
                        ) : (
                          <Box sx={{ display: 'flex', alignItems: 'center' }}>
                            <Typography variant="body2" sx={{ fontSize: '0.8rem' }}>
                              {userInterface.name}
                            </Typography>
                            <ModeChip ui={userInterface} />
                          </Box>
                        )}
                      </TableCell>
                      <TableCell>
                        {editingId === userInterface.id ? (
                          <Autocomplete
                            multiple
                            size="small"
                            options={availableModels}
                            freeSolo
                            value={editForm.models}
                            onChange={(_, newValue) => {
                              setEditForm({ ...editForm, models: newValue });
                            }}
                            renderTags={(value, getTagProps) =>
                              value.map((option, index) => {
                                const { key, ...chipProps } = getTagProps({ index });
                                return (
                                  <Chip
                                    key={key}
                                    variant="outlined"
                                    label={option}
                                    size="small"
                                    {...chipProps}
                                    sx={{
                                      height: 20,
                                      '& .MuiChip-label': { px: 0.5, fontSize: '0.75rem' },
                                      '& .MuiChip-deleteIcon': { width: 14, height: 14 },
                                    }}
                                  />
                                );
                              })
                            }
                            renderInput={(params) => (
                              <TextField
                                {...params}
                                variant="outlined"
                                placeholder="Add models..."
                                sx={{ '& .MuiInputBase-root': { minHeight: '32px' } }}
                              />
                            )}
                          />
                        ) : (
                          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                            {userInterface.models.map((model) => (
                              <Chip key={model} label={model} size="small" variant="outlined" />
                            ))}
                          </Box>
                        )}
                      </TableCell>
                      {!isMobile && (
                      <TableCell>
                        {editingId === userInterface.id ? (
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                            <TextField
                              size="small"
                              value={editForm.min_version}
                              onChange={(e) =>
                                setEditForm({ ...editForm, min_version: e.target.value })
                              }
                              variant="outlined"
                              placeholder="Min"
                              sx={{
                                flex: 1,
                                minWidth: 0,
                                '& .MuiInputBase-root': { height: '32px' },
                                '& .MuiInputBase-input': { fontSize: '0.75rem', p: '4px 6px' },
                              }}
                            />
                            <Box component="span" sx={{ color: 'text.secondary' }}>
                              -
                            </Box>
                            <TextField
                              size="small"
                              value={editForm.max_version}
                              onChange={(e) =>
                                setEditForm({ ...editForm, max_version: e.target.value })
                              }
                              variant="outlined"
                              placeholder="Max"
                              sx={{
                                flex: 1,
                                minWidth: 0,
                                '& .MuiInputBase-root': { height: '32px' },
                                '& .MuiInputBase-input': { fontSize: '0.75rem', p: '4px 6px' },
                              }}
                            />
                          </Box>
                        ) : isProd(userInterface) ? (
                          <Tooltip
                            title={
                              userInterface.published_at
                                ? `Published ${new Date(userInterface.published_at).toLocaleString()}`
                                : ''
                            }
                          >
                            <Typography variant="body2" sx={{ fontSize: '0.8rem' }}>
                              v{userInterface.published_version ?? '?'}
                            </Typography>
                          </Tooltip>
                        ) : (
                          formatVersionRange(userInterface)
                        )}
                      </TableCell>
                      )}
                      <TableCell>
                        <VariantsCell userInterfaceId={userInterface.id} />
                      </TableCell>
                      {!isMobile && (
                      <TableCell align="center">
                        <Tooltip
                          title={isProd(userInterface) ? 'View navigation (read-only)' : 'Edit navigation'}
                        >
                          <IconButton
                            size="small"
                            color="primary"
                            onClick={() => handleEditNavigation(userInterface)}
                            sx={{ p: 0.5 }}
                          >
                            <LaunchIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </TableCell>
                      )}
                      {!isMobile && (
                      <TableCell align="center">
                        {/* References route is name-keyed and resolves to the dev
                            row — disabled on prod (refs sync on publish). */}
                        <Tooltip
                          title={
                            isProd(userInterface)
                              ? 'References are managed on the dev version (synced on publish)'
                              : 'Open references'
                          }
                        >
                          <span>
                            <IconButton
                              size="small"
                              color="primary"
                              disabled={isProd(userInterface)}
                              onClick={() =>
                                navigate(
                                  `/configuration/interface/${encodeURIComponent(userInterface.name)}/references`,
                                )
                              }
                              sx={{ p: 0.5 }}
                            >
                              <LaunchIcon fontSize="small" />
                            </IconButton>
                          </span>
                        </Tooltip>
                      </TableCell>
                      )}
                      <TableCell align="center">
                        {editingId === userInterface.id ? (
                          <Box sx={{ display: 'flex', gap: 0.5, justifyContent: 'center' }}>
                            <IconButton
                              size="small"
                              color="primary"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleSaveEdit();
                              }}
                              disabled={submitting}
                              sx={{ p: 0.5 }}
                            >
                              {submitting ? (
                                <CircularProgress size={16} />
                              ) : (
                                <SaveIcon fontSize="small" />
                              )}
                            </IconButton>
                            <IconButton
                              size="small"
                              color="secondary"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleCancelEdit();
                              }}
                              disabled={submitting}
                              sx={{ p: 0.5 }}
                            >
                              <CancelIcon fontSize="small" />
                            </IconButton>
                          </Box>
                        ) : (
                          <IconButton
                            size="small"
                            onClick={(e) => {
                              e.stopPropagation();
                              setActionMenu({ anchorEl: e.currentTarget, ui: userInterface });
                            }}
                            sx={{ p: 0.5 }}
                            title="Actions"
                          >
                            <MoreIcon fontSize="small" />
                          </IconButton>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </CardContent>
      </Card>

      {/* Row actions menu — one shared instance, anchored to the clicked ⋮ button */}
      <Menu
        anchorEl={actionMenu?.anchorEl}
        open={Boolean(actionMenu)}
        onClose={closeActionMenu}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        {/* Prod rows are read-only snapshots: no Edit / Manage variants / Publish
            / Export — just Duplicate (makes a plain dev copy) and Delete
            (= unpublish). */}
        {actionMenu && !isProd(actionMenu.ui) && (
          <MenuItem
            onClick={() => {
              if (actionMenu) handleEdit(actionMenu.ui);
              closeActionMenu();
            }}
          >
            <ListItemIcon>
              <EditIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Edit</ListItemText>
          </MenuItem>
        )}
        {actionMenu && !isProd(actionMenu.ui) && (
          <MenuItem
            onClick={() => {
              if (actionMenu) handleOpenVariants(actionMenu.ui);
              closeActionMenu();
            }}
          >
            <ListItemIcon>
              <TuneIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Manage variants</ListItemText>
          </MenuItem>
        )}
        <MenuItem
          disabled={submitting}
          onClick={() => {
            if (actionMenu) handleDuplicate(actionMenu.ui);
            closeActionMenu();
          }}
        >
          <ListItemIcon>
            <DuplicateIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Duplicate</ListItemText>
        </MenuItem>
        {actionMenu && !isProd(actionMenu.ui) && (
          <MenuItem
            disabled={Boolean(publishingName)}
            onClick={() => {
              if (actionMenu) handlePublish(actionMenu.ui);
              closeActionMenu();
            }}
          >
            <ListItemIcon>
              <PublishIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Publish to prod</ListItemText>
          </MenuItem>
        )}
        {actionMenu && !isProd(actionMenu.ui) && (
          <MenuItem
            onClick={() => {
              if (actionMenu) handleExport(actionMenu.ui);
              closeActionMenu();
            }}
          >
            <ListItemIcon>
              <ExportIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Export (.vptree)</ListItemText>
          </MenuItem>
        )}
        {actionMenu && !isProd(actionMenu.ui) && (
          <MenuItem
            onClick={() => {
              if (actionMenu) {
                window.open(
                  buildServerUrl(
                    `/server/userinterface/domReport?userinterface=${encodeURIComponent(
                      actionMenu.ui.name,
                    )}`,
                  ),
                  '_blank',
                );
              }
              closeActionMenu();
            }}
          >
            <ListItemIcon>
              <DomIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>DOM report</ListItemText>
          </MenuItem>
        )}
        <Divider />
        <MenuItem
          onClick={() => {
            if (actionMenu) handleDelete(actionMenu.ui.id);
            closeActionMenu();
          }}
          sx={{ color: 'error.main' }}
        >
          <ListItemIcon sx={{ color: 'error.main' }}>
            <DeleteIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>
            {actionMenu && isProd(actionMenu.ui) ? 'Delete (unpublish)' : 'Delete'}
          </ListItemText>
        </MenuItem>
      </Menu>

      {/* Add New User Interface Dialog */}
      <StyledDialog open={openDialog} onClose={handleCloseDialog} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ pb: 1 }}>Add New User Interface</DialogTitle>
        <DialogContent sx={{ pt: 1 }}>
          <Box sx={{ pt: 0.5 }}>
            <TextField
              autoFocus
              margin="dense"
              label="Name"
              fullWidth
              variant="outlined"
              value={newInterface.name}
              onChange={(e) => setNewInterface({ ...newInterface, name: e.target.value })}
              sx={{ mb: 1.5 }}
              size="small"
              placeholder="e.g., Main Navigation Tree"
            />

            <Autocomplete
              multiple
              size="small"
              options={availableModels}
              freeSolo
              value={newInterface.models}
              onChange={(_, newValue) => {
                setNewInterface({ ...newInterface, models: newValue });
              }}
              renderTags={(value, getTagProps) =>
                value.map((option, index) => {
                  const { key, ...chipProps } = getTagProps({ index });
                  return (
                    <Chip
                      key={key}
                      variant="outlined"
                      label={option}
                      size="small"
                      {...chipProps}
                      sx={{
                        height: 20,
                        '& .MuiChip-label': { px: 0.5, fontSize: '0.75rem' },
                        '& .MuiChip-deleteIcon': { width: 14, height: 14 },
                      }}
                    />
                  );
                })
              }
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Models"
                  variant="outlined"
                  placeholder="Add device models..."
                  margin="dense"
                  sx={{ mb: 1.5 }}
                />
              )}
            />

            <TextField
              margin="dense"
              label="Min Version"
              fullWidth
              variant="outlined"
              value={newInterface.min_version}
              onChange={(e) => setNewInterface({ ...newInterface, min_version: e.target.value })}
              sx={{ mb: 1.5 }}
              size="small"
              placeholder="e.g., 1.0"
            />

            <TextField
              margin="dense"
              label="Max Version"
              fullWidth
              variant="outlined"
              value={newInterface.max_version}
              onChange={(e) => setNewInterface({ ...newInterface, max_version: e.target.value })}
              sx={{ mb: 1.5 }}
              size="small"
              placeholder="e.g., 2.0"
            />
          </Box>
        </DialogContent>
        <DialogActions sx={{ pt: 1, pb: 2, px: 3, gap: 1 }}>
          <Button onClick={handleCloseDialog} size="small" variant="outlined" disabled={submitting}>
            Cancel
          </Button>
          <Button
            onClick={handleAddNew}
            variant="contained"
            size="small"
            disabled={!newInterface.name.trim() || newInterface.models.length === 0 || submitting}
          >
            {submitting ? <CircularProgress size={16} sx={{ mr: 1 }} /> : null}
            Add
          </Button>
        </DialogActions>
      </StyledDialog>

      {/* Import (.vptree bundle) Dialog */}
      <StyledDialog open={importOpen} onClose={() => !importing && setImportOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ pb: 1 }}>Import user interface</DialogTitle>
        <DialogContent sx={{ pt: 1 }}>
          <Box sx={{ pt: 0.5 }}>
            <Button
              component="label"
              variant="outlined"
              startIcon={<ImportIcon />}
              size="small"
              sx={{ mb: 1.5 }}
              disabled={importing}
            >
              {importFile ? importFile.name : 'Choose .vptree file'}
              <input
                type="file"
                accept=".vptree,application/zip"
                hidden
                onChange={(e) => handleImportFileSelected(e.target.files?.[0] || null)}
              />
            </Button>

            <TextField
              margin="dense"
              label="New name"
              fullWidth
              variant="outlined"
              value={importName}
              onChange={(e) => setImportName(e.target.value)}
              size="small"
              placeholder="Name for the imported interface"
              helperText="Must be unique. Trees, nodes, variants and reference images are restored from the bundle."
            />
          </Box>
        </DialogContent>
        <DialogActions sx={{ pt: 1, pb: 2, px: 3, gap: 1 }}>
          <Button onClick={() => setImportOpen(false)} size="small" variant="outlined" disabled={importing}>
            Cancel
          </Button>
          <Button
            onClick={handleImport}
            variant="contained"
            size="small"
            disabled={!importFile || !importName.trim() || importing}
          >
            {importing ? <CircularProgress size={16} sx={{ mr: 1 }} /> : null}
            Import
          </Button>
        </DialogActions>
      </StyledDialog>

      {/* Variants manager modal (Phase 2 — see docs/agent/ENHANCE_VARIANT.md §3.1).
          The component owns its Dialog (border, title, close icon, actions). */}
      {variantsModalUi ? (
        <UserInterface_VariantsSection
          open
          onClose={handleCloseVariants}
          userInterfaceId={variantsModalUi.id}
          userInterfaceName={variantsModalUi.name}
        />
      ) : null}

      {/* Duplication overlay — blocks interaction while references are copied
          server-side (a long operation) so the user sees progress and can't
          fire a second duplicate. */}
      <Backdrop
        open={Boolean(duplicatingName || publishingName)}
        sx={{
          zIndex: (theme) => theme.zIndex.modal + 1,
          color: '#fff',
          flexDirection: 'column',
          gap: 2,
        }}
      >
        <CircularProgress color="inherit" />
        <Box sx={{ textAlign: 'center' }}>
          <Typography variant="h6">
            {publishingName
              ? `Publishing "${publishingName}" to prod…`
              : `Duplicating "${duplicatingName}"…`}
          </Typography>
          <Typography variant="body2" sx={{ opacity: 0.85 }}>
            Copying references — this can take a little while.
          </Typography>
        </Box>
      </Backdrop>

      {/* Confirmation Dialog */}
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

export default UserInterface;
