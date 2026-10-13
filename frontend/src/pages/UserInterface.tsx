import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  Launch as LaunchIcon,
  ContentCopy as DuplicateIcon,
  Tune as TuneIcon,
  AccountTreeOutlined as DomIcon,
  Download as ExportIcon,
  Upload as ImportIcon,
  MoreVert as MoreIcon,
  Publish as PublishIcon,
  ReportProblemOutlined as UnknownIcon,
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
  Switch,
  FormControlLabel,
} from '@mui/material';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { goldButtonSx, pageSurfaceSx, segmentedSx } from '../components/common/PageChrome';
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
  unknownCountFor,
  useUnknownScreenCounts,
} from '../hooks/pages/useUserInterfaceUnknown';
import {
  UserInterface as UserInterfaceType,
  UserInterfaceCreatePayload,
} from '../types/pages/UserInterface_Types';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { api } from '../utils/apiClient';

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
        ? { bgcolor: '#b8860b', color: '#fff' } // gold = prod, same in both themes
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
  const P = useAgentChatPalette();
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
  // Edit-in-popup state. Replaces the old inline `editingId`/`editForm` pair:
  // the row actions ⋮ menu opens a single StyledDialog that owns every
  // editable field at once, so there are no per-row conditional renderings.
  // `editOpen` controls visibility; `editTarget` is the row being edited;
  // `editForm` mirrors the Add-dialog payload shape (same fields, same
  // "empty string means unset" conventions for company/is_media).
  const [editOpen, setEditOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<UserInterfaceType | null>(null);
  const [editForm, setEditForm] = useState({
    name: '',
    models: [] as string[],
    min_version: '',
    max_version: '',
    // Empty string is the editor's "not set" state; the editor turns it back
    // into NULL on save by omitting the key, so a cleared field does not
    // persist a literal "".
    company: '',
    // Optional media-surface flag. `null` = "editor has not decided"; the
    // switch shows OFF on null and ignores a null on save (the backend's
    // presence-check then leaves the column untouched). `true` / `false`
    // are explicit editorial choices persisted verbatim.
    is_media: null as boolean | null,
  });
  const [openDialog, setOpenDialog] = useState(false);
  const [newInterface, setNewInterface] = useState({
    name: '',
    models: [] as string[],
    min_version: '',
    max_version: '',
    company: '',
    // Same convention as `company`: defaults to null (do not set) on create.
    // The switch rides at false by default on the dialog so the editor sees
    // an explicit OFF state — a new UI is not a media surface unless the
    // editor says so.
    is_media: false,
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

  // Per-userinterface "DOM report has been generated at least once" flag, persisted in
  // localStorage so the colour survives reloads and matches across tabs for this browser.
  // Once a DOM report has been run, the Unknown-screens pill in the row's ⋮ menu drops its
  // warning amber and renders white — the operator has already looked at the unknown screens
  // in the DOM report, so the count is no longer a "needs your attention" signal regardless
  // of how many remain. Keyed by userinterface name; the value is the ISO timestamp of the
  // first generation (overwritten on each visit so the value is always the latest run).
  const DOM_REPORT_LS_PREFIX = 'vpt:dom_report:';
  const [domReportDone, setDomReportDone] = useState<Record<string, string>>(() => {
    if (typeof window === 'undefined') return {};
    const out: Record<string, string> = {};
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const k = window.localStorage.key(i);
      if (k && k.startsWith(DOM_REPORT_LS_PREFIX)) {
        const v = window.localStorage.getItem(k);
        if (v) out[k.slice(DOM_REPORT_LS_PREFIX.length)] = v;
      }
    }
    return out;
  });
  const markDomReportDone = (uiName: string) => {
    const stamp = new Date().toISOString();
    window.localStorage.setItem(`${DOM_REPORT_LS_PREFIX}${uiName}`, stamp);
    setDomReportDone((prev) => ({ ...prev, [uiName]: stamp }));
  };

  // Unknown-screen counts: one request for the whole page, keyed by interface name.
  // The page used to surface a "Unknown screens N" button in the action bar pointing
  // at the worst-named interface, and an "Unknown" column next to Actions. Both have
  // been folded into the row's ⋮ menu as "Unknown screens (N)" so the row stays
  // uncluttered — the count travels with the row it belongs to.
  const { counts: unknownCounts } = useUnknownScreenCounts();

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

  const openEditModal = (userInterface: UserInterfaceType) => {
    setEditTarget(userInterface);
    setEditForm({
      name: userInterface.name,
      models: userInterface.models,
      min_version: userInterface.min_version || '',
      max_version: userInterface.max_version || '',
      company: userInterface.company || '',
      is_media: (userInterface.is_media ?? null) as boolean | null,
    });
    setEditOpen(true);
  };

  const closeEditModal = () => {
    setEditOpen(false);
    // Keep `editTarget` until next openEditModal so the dialog can still
    // resolve the original row (e.g. for the Save spinner label) while the
    // close animation runs.
  };

  const handleSaveEdit = async () => {
    if (!editTarget) return;
    try {
      setSubmitting(true);
      setError(null);

      // Empty `company` means "leave it as-is on the server" — the dialog
      // shows an empty field, the backend keeps the existing value.
      // A NON-empty value is the user's edit and goes through verbatim.
      //
      // `is_media` is a literal boolean on the wire: a missing key (null
      // in the editor) is omitted entirely, the backend keeps the column
      // untouched; `true` / `false` go through verbatim and clear the
      // NULL default for a row that has never been set.
      const is_media_payload =
        editForm.is_media === null ? undefined : editForm.is_media;
      const payload: UserInterfaceCreatePayload = {
        name: editForm.name,
        models: editForm.models,
        min_version: editForm.min_version,
        max_version: editForm.max_version,
        company: editForm.company.trim() || undefined,
        is_media: is_media_payload,
      };

      const updatedInterface = await updateUserInterfaceWithValidation(
        editTarget.id,
        payload,
        userInterfaces,
      );

      // Update local state
      setUserInterfaces(
        userInterfaces.map((ui) => (ui.id === editTarget.id ? updatedInterface : ui)),
      );
      setEditOpen(false);
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

  // Open the DOM report in a new tab. Mirrors the script-reports / openR2Url
  // pattern (BUG-0459): the backend builds (or re-signs) the cached R2 artifact,
  // returns a presigned URL against the public proxy, and the new-tab navigation
  // carries the signature as its credential — no Authorization header, no
  // vpt_jwt cookie, no cross-origin issue when the selected server is a sibling
  // of the frontend.
  const openDomReport = async (uiName: string) => {
    try {
      const res = await api.get<{ success: boolean; url?: string; message?: string }>(
        buildServerUrl(
          `/server/userinterface/domReport/url?userinterface=${encodeURIComponent(uiName)}`,
        ),
      );
      if (res.success && res.url) {
        window.open(res.url, '_blank');
      } else {
        console.error('[@component:UserInterface] DOM report URL failed:', res.message);
        setError(res.message || 'Failed to open DOM report');
      }
    } catch (err) {
      console.error('[@component:UserInterface] Error opening DOM report:', err);
      setError(err instanceof Error ? err.message : 'Failed to open DOM report');
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
        // Same convention as edit: an empty input means "do not set company",
        // which the backend persists as NULL — same as a row that pre-dates
        // the column. A non-empty input is verbatim.
        company: newInterface.company.trim() || undefined,
        // New rows ride with is_media=false by default (the dialog switch is
        // OFF on open); a non-false value is the explicit editorial choice.
        is_media: newInterface.is_media,
      };

      const createdInterface = await createUserInterfaceWithValidation(
        payload,
        userInterfaces,
        { createNavigationConfig: true },
      );

      // Update local state
      setUserInterfaces([...userInterfaces, createdInterface]);
      setNewInterface({
        name: '',
        models: [],
        min_version: '',
        max_version: '',
        company: '',
        is_media: false,
      });
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
    setNewInterface({
      name: '',
      models: [],
      min_version: '',
      max_version: '',
      company: '',
      is_media: false,
    });
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
    <Box sx={pageSurfaceSx(P)}>
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
          {/* Count sits next to the title so the H1 always answers "how many
              do I have?" without a long explanatory subtitle underneath. */}
          <Typography component="h1" sx={{ fontSize: isMobile ? '1.25rem' : '1.5rem', fontWeight: 600, lineHeight: 1.3 }}>
            Interface ({userInterfaces.length})
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
            sx={segmentedSx(P, 'sm')}
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
            sx={{ textTransform: 'none', ...(isMobile ? { minWidth: 0, px: 1 } : {}) }}
          >
            {isMobile ? <ImportIcon fontSize="small" /> : 'Import'}
          </Button>
          {/* The Unknown-screens cross-device entry point used to live here as an
              outlined warning button. Moved into the row's ⋮ action menu so the
              indication travels with the row it belongs to (no top bar clutter).
              The counts request is still issued once per page via
              `useUnknownScreenCounts`; the total surfaces in each row's menu. */}
          <Button
            variant="contained"
            startIcon={!isMobile ? <AddIcon /> : undefined}
            onClick={() => setOpenDialog(true)}
            size="small"
            disabled={loading}
            aria-label="Add UI"
            sx={{ ...(goldButtonSx(P) as object), ...(isMobile ? { minWidth: 0, px: 1 } : {}) }}
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

      <Card>
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
                      <TableCell sx={{ width: '12%' }}>
                        <strong>Version</strong>
                      </TableCell>
                    )}
                    <TableCell sx={{ width: isMobile ? '15%' : '13%' }}>
                      <strong>Variants</strong>
                    </TableCell>
                    {!isMobile && (
                      <>
                        <TableCell align="center" sx={{ width: '8%', whiteSpace: 'nowrap' }}>
                          <strong>Navigation</strong>
                        </TableCell>
                        <TableCell align="center" sx={{ width: '8%', whiteSpace: 'nowrap' }}>
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
                        isMobile ? () => handleEditNavigation(userInterface) : undefined
                      }
                      sx={{ cursor: isMobile ? 'pointer' : 'default' }}
                    >
                      <TableCell>
                        <Box sx={{ display: 'flex', alignItems: 'center' }}>
                          <Typography variant="body2" sx={{ fontSize: '0.8rem' }}>
                            {userInterface.name}
                          </Typography>
                          <ModeChip ui={userInterface} />
                        </Box>
                      </TableCell>
                      <TableCell>
                        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                          {userInterface.models.map((model) => (
                            <Chip key={model} label={model} size="small" variant="outlined" />
                          ))}
                        </Box>
                      </TableCell>
                      {!isMobile && (
                      <TableCell>
                        {isProd(userInterface) ? (
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
                      {/* The Unknown-screens pill used to live in its own column here; the
                          count is now surfaced inside the row's ⋮ action menu
                          (see "Unknown screens (N)" below). Name / Models /
                          Company / Is media / Version are no longer inline-edited —
                          the row's ⋮ menu opens a single Edit popup that owns all
                          editable fields at once. */}
                      <TableCell align="center">
                        <IconButton
                          size="small"
                          onClick={(e) => {
                            e.stopPropagation();
                            setActionMenu({ anchorEl: e.currentTarget, ui: userInterface });
                          }}
                          sx={{ p: 0.5 }}
                          title="Actions"
                          aria-label={`Actions for ${userInterface.name}`}
                        >
                          <MoreIcon fontSize="small" />
                        </IconButton>
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
        {/* Unknown screens — surfaced here (not as its own column or top button) so
            the count travels with the row it belongs to. Renders only when the
            server reports at least one pending unknown for this interface. */}
        {actionMenu && unknownCountFor(unknownCounts, actionMenu.ui.name) > 0 && (
          <MenuItem
            onClick={() => {
              if (actionMenu) {
                navigate(
                  `/configuration/interface/${encodeURIComponent(actionMenu.ui.name)}/unknown`,
                );
              }
              closeActionMenu();
            }}
            sx={{ color: domReportDone[actionMenu.ui.name] ? P.textPrimary : P.warning }}
          >
            <ListItemIcon
              sx={{ color: domReportDone[actionMenu.ui.name] ? P.textPrimary : P.warning }}
            >
              <UnknownIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>
              Unknown screens ({unknownCountFor(unknownCounts, actionMenu.ui.name)})
            </ListItemText>
          </MenuItem>
        )}
        {actionMenu &&
          unknownCountFor(unknownCounts, actionMenu.ui.name) > 0 &&
          !isProd(actionMenu.ui) && <Divider />}
        {/* Prod rows are read-only snapshots: no Edit / Manage variants / Publish
            / Export — just Duplicate (makes a plain dev copy) and Delete
            (= unpublish). */}
        {actionMenu && !isProd(actionMenu.ui) && (
          <MenuItem
            onClick={() => {
              if (actionMenu) openEditModal(actionMenu.ui);
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
                markDomReportDone(actionMenu.ui.name);
                openDomReport(actionMenu.ui.name);
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

            <TextField
              margin="dense"
              label="Company"
              fullWidth
              variant="outlined"
              value={newInterface.company}
              onChange={(e) => setNewInterface({ ...newInterface, company: e.target.value })}
              sx={{ mb: 1.5 }}
              size="small"
              placeholder="e.g., brand_a, brand_b, brand_c"
            />

            <FormControlLabel
              control={
                <Switch
                  size="small"
                  checked={!!newInterface.is_media}
                  onChange={(_, checked) =>
                    setNewInterface({ ...newInterface, is_media: checked })
                  }
                  inputProps={{ 'aria-label': 'is_media switch (new)' }}
                />
              }
              label="Is media"
              sx={{ mb: 1, ml: 0.5 }}
            />
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ display: 'block', mb: 1.5, ml: 1.5 }}
            >
              Mark this UI as a media surface so the monitor's Tier-2 playback
              arm answers <em>playing / paused / stopped</em>. Off (default) means
              playback is <em>not_applicable</em> on this UI.
            </Typography>
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

      {/* Edit popup — opened by the row's ⋮ action menu. Mirrors the Add
          dialog field-by-field so an editor never sees a different shape
          of form when editing vs. creating. */}
      <StyledDialog open={editOpen} onClose={closeEditModal} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ pb: 1 }}>
          Edit interface
          {editTarget && (
            <Typography
              component="span"
              variant="body2"
              sx={{ ml: 1, color: P.textMuted, fontWeight: 400 }}
            >
              {editTarget.name}
            </Typography>
          )}
        </DialogTitle>
        <DialogContent sx={{ pt: 1 }}>
          <Box sx={{ pt: 0.5 }}>
            <TextField
              autoFocus
              margin="dense"
              label="Name"
              fullWidth
              variant="outlined"
              value={editForm.name}
              onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
              sx={{ mb: 1.5 }}
              size="small"
              placeholder="e.g., Main Navigation Tree"
            />

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
              value={editForm.min_version}
              onChange={(e) => setEditForm({ ...editForm, min_version: e.target.value })}
              sx={{ mb: 1.5 }}
              size="small"
              placeholder="e.g., 1.0"
            />

            <TextField
              margin="dense"
              label="Max Version"
              fullWidth
              variant="outlined"
              value={editForm.max_version}
              onChange={(e) => setEditForm({ ...editForm, max_version: e.target.value })}
              sx={{ mb: 1.5 }}
              size="small"
              placeholder="e.g., 2.0"
            />

            <TextField
              margin="dense"
              label="Company"
              fullWidth
              variant="outlined"
              value={editForm.company}
              onChange={(e) => setEditForm({ ...editForm, company: e.target.value })}
              sx={{ mb: 1.5 }}
              size="small"
              placeholder="e.g., brand_a, brand_b, brand_c"
            />

            <FormControlLabel
              control={
                <Switch
                  size="small"
                  checked={editForm.is_media === true}
                  onChange={(_, checked) =>
                    setEditForm({ ...editForm, is_media: checked })
                  }
                  inputProps={{ 'aria-label': 'is_media switch (edit)' }}
                />
              }
              label="Is media"
              sx={{ mb: 1, ml: 0.5 }}
            />
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ display: 'block', mb: 1.5, ml: 1.5 }}
            >
              Mark this UI as a media surface so the monitor's Tier-2 playback
              arm answers <em>playing / paused / stopped</em>. Off (default) means
              playback is <em>not_applicable</em> on this UI.
            </Typography>
          </Box>
        </DialogContent>
        <DialogActions sx={{ pt: 1, pb: 2, px: 3, gap: 1 }}>
          <Button onClick={closeEditModal} size="small" variant="outlined" disabled={submitting}>
            Cancel
          </Button>
          <Button
            onClick={handleSaveEdit}
            variant="contained"
            size="small"
            disabled={!editForm.name.trim() || editForm.models.length === 0 || submitting}
          >
            {submitting ? <CircularProgress size={16} sx={{ mr: 1 }} /> : null}
            Save
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
