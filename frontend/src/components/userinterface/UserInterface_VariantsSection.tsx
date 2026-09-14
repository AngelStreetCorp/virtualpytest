/**
 * UserInterface — Manage Variants Modal
 *
 * Single-modal layout. Owns its Dialog. Title `Manage variants — <ui>`.
 *
 * Top: existing variants list. Each row has Edit (✎) and Delete (🗑) icon
 * buttons. Edit expands the row inline into Name + Description fields so
 * both can be changed in one Save (rename + description PUT issued back-to-
 * back). Delete swaps the row for an inline confirmation.
 *
 * Bottom: a collapsed `+ Add variant` button. Clicking it expands an inline
 * form (Name + Description + Create-from + Add + Cancel). The form is hidden
 * by default so it never visually competes with the existing-variants list.
 *
 * See docs/agent/navigation/VARIANT.md § "Manage Variants modal" for the spec.
 */

import {
  Add as AddIcon,
  Close as CloseIcon,
  Delete as DeleteIcon,
  Edit as EditIcon,
} from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  IconButton,
  InputLabel,
  List,
  ListItem,
  ListItemSecondaryAction,
  ListItemText,
  MenuItem,
  Select,
  Snackbar,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import React, { useEffect, useMemo, useState } from 'react';

import { StyledDialog } from '../common/StyledDialog';
import {
  useUserInterfaceVariants,
  type UserInterfaceVariant,
} from '../../hooks/userinterface/useUserInterfaceVariants';
import { TOAST_AUTO_HIDE_DURATION, TOAST_POSITION } from '../../constants/toastConfig';

interface UserInterface_VariantsSectionProps {
  open: boolean;
  onClose: () => void;
  userInterfaceId: string;
  userInterfaceName?: string;
}

// Mirrors the SQL CHECK constraint on userinterface_variants.name and the
// regex used by _validate_variant_name in server_userinterface_routes.py.
// Names are stored lowercase in the DB; the input box auto-lowercases as
// users type so they never see a "must be lowercase" error.
const VARIANT_NAME_PATTERN = /^[a-z0-9._-]{1,64}$/;
const VARIANT_NAME_PLACEHOLDER =
  'provider-platform(-language) (e.g. example-v2 or example-v2-en)';
const RESERVED_NAME = '__base__';
// Sentinel value used in the Create-from <Select> for "Base" (= source_variant null).
const BASE_SOURCE_SENTINEL = '__base__';

const isValidVariantName = (name: string): boolean =>
  VARIANT_NAME_PATTERN.test(name) && name !== RESERVED_NAME;

interface AddFormState {
  open: boolean;
  name: string;
  description: string;
  /** The Select's currently-chosen string value. BASE_SOURCE_SENTINEL means Base
   *  (translated to source_variant=null on submit). */
  sourceVariant: string;
  submitting: boolean;
  serverError: string | null;
}

const EMPTY_ADD_FORM: AddFormState = {
  open: false,
  name: '',
  description: '',
  sourceVariant: BASE_SOURCE_SENTINEL,
  submitting: false,
  serverError: null,
};

interface InlineEditState {
  oldName: string;
  oldDescription: string;
  newName: string;
  newDescription: string;
  submitting: boolean;
  serverError: string | null;
}

interface InlineDeleteState {
  name: string;
  submitting: boolean;
  serverError: string | null;
}

interface ToastState {
  open: boolean;
  severity: 'success' | 'error' | 'info';
  message: string;
}

const EMPTY_TOAST: ToastState = { open: false, severity: 'info', message: '' };

const UserInterface_VariantsSection: React.FC<UserInterface_VariantsSectionProps> = ({
  open,
  onClose,
  userInterfaceId,
  userInterfaceName,
}) => {
  const {
    variants,
    loading,
    error,
    addVariant,
    updateVariant,
    deleteVariant,
    renameVariant,
  } = useUserInterfaceVariants(userInterfaceId);

  const [addForm, setAddForm] = useState<AddFormState>(EMPTY_ADD_FORM);
  const [editRow, setEditRow] = useState<InlineEditState | null>(null);
  const [deleteRow, setDeleteRow] = useState<InlineDeleteState | null>(null);
  const [toast, setToast] = useState<ToastState>(EMPTY_TOAST);

  // Reset transient state every time the modal opens.
  useEffect(() => {
    if (!open) return;
    setAddForm(EMPTY_ADD_FORM);
    setEditRow(null);
    setDeleteRow(null);
  }, [open]);

  const variantsCount = variants.length;

  // ---- Add-variant form ------------------------------------------------
  const addNameError = useMemo<string | null>(() => {
    if (addForm.serverError) return addForm.serverError;
    if (!addForm.name) return null; // don't yell while typing
    if (!isValidVariantName(addForm.name)) {
      if (addForm.name === RESERVED_NAME) {
        return `'${RESERVED_NAME}' is reserved`;
      }
      return `Name must match ${VARIANT_NAME_PATTERN.source}`;
    }
    return null;
  }, [addForm.name, addForm.serverError]);

  const addDisabled =
    !isValidVariantName(addForm.name) ||
    addForm.description.trim().length === 0 ||
    addForm.submitting;

  const openAddForm = () =>
    setAddForm({ ...EMPTY_ADD_FORM, open: true });
  const closeAddForm = () => {
    if (addForm.submitting) return;
    setAddForm(EMPTY_ADD_FORM);
  };

  const handleAddSubmit = async () => {
    if (!isValidVariantName(addForm.name)) return;
    if (addForm.description.trim().length === 0) return;
    setAddForm((s) => ({ ...s, submitting: true, serverError: null }));
    const sourceVariant =
      addForm.sourceVariant === BASE_SOURCE_SENTINEL ? null : addForm.sourceVariant;
    try {
      const result = await addVariant(
        addForm.name,
        addForm.description.trim(),
        sourceVariant,
      );
      const message = (() => {
        if (sourceVariant === null) {
          const hidden = result.hidden_rows;
          const total = (hidden?.nodes ?? 0) + (hidden?.edges ?? 0);
          return total > 0
            ? `Variant '${addForm.name}' added. Hidden on ${hidden?.nodes ?? 0} nodes and ${hidden?.edges ?? 0} edges.`
            : `Variant '${addForm.name}' added.`;
        }
        const cloned = result.cloned_rows;
        const total = (cloned?.nodes ?? 0) + (cloned?.edges ?? 0);
        return total > 0
          ? `Variant '${addForm.name}' cloned from '${sourceVariant}' (copied to ${cloned?.nodes ?? 0} nodes and ${cloned?.edges ?? 0} edges).`
          : `Variant '${addForm.name}' cloned from '${sourceVariant}'.`;
      })();
      setAddForm(EMPTY_ADD_FORM);
      setToast({ open: true, severity: 'success', message });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setAddForm((s) => ({ ...s, submitting: false, serverError: message }));
    }
  };

  // ---- Inline edit (name + description together) ----------------------
  const startEdit = (variant: UserInterfaceVariant) => {
    setDeleteRow(null);
    setEditRow({
      oldName: variant.name,
      oldDescription: variant.description ?? '',
      newName: variant.name,
      newDescription: variant.description ?? '',
      submitting: false,
      serverError: null,
    });
  };
  const cancelEdit = () => setEditRow(null);

  const editNameError = useMemo<string | null>(() => {
    if (!editRow) return null;
    if (editRow.serverError) return editRow.serverError;
    if (!editRow.newName) return null;
    if (!isValidVariantName(editRow.newName)) {
      if (editRow.newName === RESERVED_NAME) {
        return `'${RESERVED_NAME}' is reserved`;
      }
      return `Name must match ${VARIANT_NAME_PATTERN.source}`;
    }
    return null;
  }, [editRow]);

  const editDirty = Boolean(
    editRow &&
      (editRow.newName !== editRow.oldName ||
        editRow.newDescription !== editRow.oldDescription),
  );
  const editSubmittable = Boolean(
    editRow &&
      editDirty &&
      isValidVariantName(editRow.newName) &&
      editRow.newDescription.trim().length > 0 &&
      !editRow.submitting,
  );

  const handleEditSubmit = async () => {
    if (!editRow) return;
    if (!editSubmittable) return;

    const { oldName, oldDescription, newName, newDescription } = editRow;
    const nameChanged = newName !== oldName;
    const descChanged = newDescription !== oldDescription;
    setEditRow((s) => (s ? { ...s, submitting: true, serverError: null } : s));

    try {
      let finalName = oldName;
      let renameDetail = '';
      if (nameChanged) {
        const rows = await renameVariant(oldName, newName);
        finalName = newName;
        if (rows.nodes + rows.edges > 0) {
          renameDetail = ` (rewrote ${rows.nodes} nodes, ${rows.edges} edges)`;
        }
      }
      if (descChanged) {
        await updateVariant(finalName, newDescription.trim());
      }

      const messageParts: string[] = [];
      if (nameChanged) {
        messageParts.push(`Renamed '${oldName}' → '${newName}'${renameDetail}`);
      }
      if (descChanged) {
        messageParts.push(
          nameChanged ? 'description updated' : `Updated description for '${finalName}'`,
        );
      }
      setEditRow(null);
      setToast({
        open: true,
        severity: 'success',
        message: `${messageParts.join(', ')}.`,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setEditRow((s) => (s ? { ...s, submitting: false, serverError: message } : s));
    }
  };

  // ---- Inline delete ---------------------------------------------------
  const startDelete = (variant: UserInterfaceVariant) => {
    setEditRow(null);
    setDeleteRow({ name: variant.name, submitting: false, serverError: null });
  };
  const cancelDelete = () => setDeleteRow(null);

  const handleDeleteSubmit = async () => {
    if (!deleteRow) return;
    const { name } = deleteRow;
    setDeleteRow((s) => (s ? { ...s, submitting: true, serverError: null } : s));
    try {
      const rows = await deleteVariant(name);
      const detail =
        rows.nodes + rows.edges > 0
          ? ` (stripped overrides from ${rows.nodes} nodes, ${rows.edges} edges)`
          : '';
      setDeleteRow(null);
      setToast({
        open: true,
        severity: 'success',
        message: `Variant '${name}' deleted${detail}.`,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setDeleteRow((s) => (s ? { ...s, submitting: false, serverError: message } : s));
    }
  };

  const handleClose = () => {
    if (addForm.submitting || editRow?.submitting || deleteRow?.submitting) return;
    onClose();
  };

  // Render one variant row. When that row is currently being edited or
  // deleted the row content is replaced by an inline form (no nested Dialog).
  const renderVariantRow = (variant: UserInterfaceVariant) => {
    const isEditing = editRow?.oldName === variant.name;
    const isDeleting = deleteRow?.name === variant.name;

    if (isEditing && editRow) {
      return (
        <ListItem key={variant.name} divider sx={{ display: 'block', py: 1.5 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <TextField
              autoFocus
              size="small"
              label="Name"
              required
              value={editRow.newName}
              onChange={(e) =>
                setEditRow((s) =>
                  s
                    ? { ...s, newName: e.target.value.toLowerCase(), serverError: null }
                    : s,
                )
              }
              error={Boolean(editNameError)}
              helperText={editNameError || undefined}
              placeholder={VARIANT_NAME_PLACEHOLDER}
              InputLabelProps={{ shrink: true }}
              disabled={editRow.submitting}
              fullWidth
            />
            <TextField
              size="small"
              label="Description"
              required
              value={editRow.newDescription}
              onChange={(e) =>
                setEditRow((s) =>
                  s ? { ...s, newDescription: e.target.value } : s,
                )
              }
              placeholder="What does this variant change?"
              InputLabelProps={{ shrink: true }}
              disabled={editRow.submitting}
              fullWidth
            />
            <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1 }}>
              <Button
                size="small"
                variant="outlined"
                onClick={cancelEdit}
                disabled={editRow.submitting}
              >
                Cancel
              </Button>
              <Button
                size="small"
                variant="contained"
                onClick={handleEditSubmit}
                disabled={!editSubmittable}
                startIcon={
                  editRow.submitting ? <CircularProgress size={14} /> : undefined
                }
              >
                Save
              </Button>
            </Box>
          </Box>
        </ListItem>
      );
    }

    if (isDeleting && deleteRow) {
      return (
        <ListItem key={variant.name} divider sx={{ display: 'block', py: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
            <Typography variant="body2" sx={{ flex: 1 }}>
              Delete <strong>&apos;{deleteRow.name}&apos;</strong>? This strips every
              override entry that references it from this userinterface&apos;s nodes and
              edges.
            </Typography>
            <Button
              size="small"
              variant="contained"
              color="error"
              onClick={handleDeleteSubmit}
              disabled={deleteRow.submitting}
              startIcon={
                deleteRow.submitting ? <CircularProgress size={14} /> : undefined
              }
            >
              Confirm Delete
            </Button>
            <Button
              size="small"
              variant="outlined"
              onClick={cancelDelete}
              disabled={deleteRow.submitting}
            >
              Cancel
            </Button>
          </Box>
          {deleteRow.serverError ? (
            <Alert severity="error" sx={{ mt: 1 }}>
              {deleteRow.serverError}
            </Alert>
          ) : null}
        </ListItem>
      );
    }

    return (
      <ListItem key={variant.name} divider sx={{ pr: 11 }}>
        <ListItemText
          primary={
            <Box component="span" sx={{ display: 'inline', fontSize: '0.875rem' }}>
              <Typography component="span" variant="body2">
                {variant.name}
              </Typography>
              <Typography
                component="span"
                variant="body2"
                color={variant.description ? 'text.secondary' : 'text.disabled'}
                sx={{ ml: 1 }}
              >
                — {variant.description || '(no description)'}
              </Typography>
            </Box>
          }
        />
        <ListItemSecondaryAction>
          <Tooltip title="Edit name and description">
            <IconButton
              edge="end"
              size="small"
              aria-label={`Edit variant ${variant.name}`}
              onClick={() => startEdit(variant)}
              sx={{ mr: 0.5 }}
            >
              <EditIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Delete variant">
            <IconButton
              edge="end"
              size="small"
              aria-label={`Delete variant ${variant.name}`}
              onClick={() => startDelete(variant)}
              color="error"
            >
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </ListItemSecondaryAction>
      </ListItem>
    );
  };

  return (
    <StyledDialog
      open={open}
      onClose={handleClose}
      maxWidth="md"
      fullWidth
      sx={{
        '& .MuiDialog-paper': {
          // Fixed height so the modal does not flash between empty / loaded / form-expanded states.
          height: 600,
          // Override StyledDialog's primary border with white to match the rest of the dialogs in the app.
          borderColor: 'common.white',
        },
      }}
    >
      <DialogTitle sx={{ pb: 1 }}>
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 1,
          }}
        >
          <Typography variant="h6">
            Manage variants
            {userInterfaceName ? ` — ${userInterfaceName}` : ''}
          </Typography>
          <IconButton
            onClick={handleClose}
            size="small"
            aria-label="Close manage variants"
          >
            <CloseIcon />
          </IconButton>
        </Box>
      </DialogTitle>

      <DialogContent sx={{ pt: 1, display: 'flex', flexDirection: 'column', overflow: 'auto' }}>
        {error ? (
          <Alert severity="error" sx={{ mb: 1 }}>
            {error}
          </Alert>
        ) : null}

        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
            <CircularProgress size={24} />
          </Box>
        ) : variantsCount === 0 ? (
          <Box sx={{ py: 2 }}>
            <Typography variant="body2" color="text.secondary">
              No variants yet.
            </Typography>
          </Box>
        ) : (
          <List dense disablePadding>
            {variants.map(renderVariantRow)}
          </List>
        )}

        <Divider sx={{ my: 2 }} />

        {/* Collapsed-by-default Add-variant area */}
        {addForm.open ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            <Typography variant="subtitle2" color="text.secondary">
              Add new variant
            </Typography>
            <TextField
              autoFocus
              label="Name"
              fullWidth
              size="small"
              variant="outlined"
              required
              value={addForm.name}
              onChange={(e) =>
                setAddForm((s) => ({
                  ...s,
                  name: e.target.value.toLowerCase(),
                  serverError: null,
                }))
              }
              placeholder={VARIANT_NAME_PLACEHOLDER}
              error={Boolean(addNameError)}
              helperText={addNameError || undefined}
              InputLabelProps={{ shrink: true }}
              disabled={addForm.submitting}
            />
            <TextField
              label="Description"
              fullWidth
              size="small"
              variant="outlined"
              required
              value={addForm.description}
              onChange={(e) =>
                setAddForm((s) => ({ ...s, description: e.target.value }))
              }
              placeholder="What does this variant change?"
              InputLabelProps={{ shrink: true }}
              disabled={addForm.submitting}
            />
            <FormControl size="small" fullWidth>
              <InputLabel id="variant-source-label">Create from</InputLabel>
              <Select
                labelId="variant-source-label"
                label="Create from"
                value={addForm.sourceVariant}
                onChange={(e) =>
                  setAddForm((s) => ({
                    ...s,
                    sourceVariant: e.target.value as string,
                  }))
                }
                disabled={loading || addForm.submitting}
              >
                <MenuItem value={BASE_SOURCE_SENTINEL}>Base</MenuItem>
                {variants.map((v) => (
                  <MenuItem key={v.name} value={v.name}>
                    {v.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1 }}>
              <Button
                size="small"
                variant="outlined"
                onClick={closeAddForm}
                disabled={addForm.submitting}
              >
                Cancel
              </Button>
              <Button
                onClick={handleAddSubmit}
                variant="contained"
                color="primary"
                size="small"
                startIcon={
                  addForm.submitting ? <CircularProgress size={14} /> : <AddIcon />
                }
                disabled={addDisabled}
              >
                Add variant
              </Button>
            </Box>
          </Box>
        ) : (
          <Box sx={{ display: 'flex', justifyContent: 'flex-start' }}>
            <Button
              onClick={openAddForm}
              variant="outlined"
              color="primary"
              size="small"
              startIcon={<AddIcon />}
            >
              Add variant
            </Button>
          </Box>
        )}
      </DialogContent>

      <Snackbar
        open={toast.open}
        autoHideDuration={
          toast.severity === 'error'
            ? TOAST_AUTO_HIDE_DURATION.error
            : TOAST_AUTO_HIDE_DURATION.success
        }
        onClose={() => setToast(EMPTY_TOAST)}
        anchorOrigin={TOAST_POSITION.anchorOrigin}
        sx={TOAST_POSITION.sx}
      >
        <Alert
          severity={toast.severity}
          onClose={() => setToast(EMPTY_TOAST)}
          sx={{ width: '100%' }}
        >
          {toast.message}
        </Alert>
      </Snackbar>
    </StyledDialog>
  );
};

export default UserInterface_VariantsSection;
