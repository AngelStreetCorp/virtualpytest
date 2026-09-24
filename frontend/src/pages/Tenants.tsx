import React, { useState } from 'react';
import {
  Container, Typography, Box, Paper, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Button, IconButton, Chip, Alert, CircularProgress,
  Dialog, DialogTitle, DialogContent, DialogActions, TextField, Stack,
  Tooltip,
} from '@mui/material';
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  Apartment as TenantIcon,
  Refresh as RefreshIcon,
} from '@mui/icons-material';
import { useTenants, Tenant, CreateTenantInput, UpdateTenantInput } from '../hooks/pages/useTenants';
import { useProfile } from '../hooks/auth/useProfile';

const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,62}$/;

const Tenants: React.FC = () => {
  const { isPlatformAdmin } = useProfile();
  const { tenants, loading, error, loadTenants, createTenant, updateTenant, deleteTenant } = useTenants();

  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Tenant | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<Tenant | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!isPlatformAdmin) {
    return (
      <Container maxWidth="lg" sx={{ py: 4 }}>
        <Alert severity="warning">
          The Tenants page is restricted to platform-admin (super admin) accounts.
          Your account does not have that access.
        </Alert>
      </Container>
    );
  }

  const handleCreate = async (input: CreateTenantInput | UpdateTenantInput) => {
    setBusy(true);
    setActionError(null);
    try {
      const result = await createTenant(input);
      if (!result) {
        setActionError(error ?? 'Could not create tenant');
      } else {
        setCreateOpen(false);
      }
    } finally {
      setBusy(false);
    }
  };

  const handleUpdate = async (id: string, input: UpdateTenantInput) => {
    setBusy(true);
    setActionError(null);
    try {
      const result = await updateTenant(id, input);
      if (!result) {
        setActionError(error ?? 'Could not update tenant');
      } else {
        setEditTarget(null);
      }
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (tenant: Tenant) => {
    setBusy(true);
    setActionError(null);
    try {
      const ok = await deleteTenant(tenant.id);
      if (ok) {
        setConfirmDelete(null);
      } else {
        setActionError(error ?? 'Could not delete tenant');
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 3, gap: 2 }}>
        <TenantIcon sx={{ fontSize: 32, color: 'primary.main' }} />
        <Box sx={{ flexGrow: 1 }}>
          <Typography variant="h4" component="h1" fontWeight="bold">
            Tenants
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Each tenant owns its own teams. New public signups land in the default tenant as viewers.
          </Typography>
        </Box>
        <Tooltip title="Refresh">
          <IconButton onClick={() => loadTenants()} disabled={loading}>
            <RefreshIcon />
          </IconButton>
        </Tooltip>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setCreateOpen(true)}
          disabled={loading}
        >
          New Tenant
        </Button>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => loadTenants()}>
          {error}
        </Alert>
      )}
      {actionError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      <Paper>
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Slug</TableCell>
                <TableCell>Description</TableCell>
                <TableCell align="right">Teams</TableCell>
                <TableCell align="right">Users</TableCell>
                <TableCell>Created</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading && tenants.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} align="center" sx={{ py: 4 }}>
                    <CircularProgress />
                  </TableCell>
                </TableRow>
              )}
              {!loading && tenants.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} align="center" sx={{ py: 4 }}>
                    <Typography color="text.secondary">
                      No tenants yet. Click "New Tenant" to create one.
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
              {tenants.map((t) => (
                <TableRow key={t.id} hover>
                  <TableCell>
                    <Stack direction="row" alignItems="center" spacing={1}>
                      <Typography fontWeight={500}>{t.name}</Typography>
                      {t.is_default && (
                        <Chip label="Default" size="small" color="primary" />
                      )}
                    </Stack>
                  </TableCell>
                  <TableCell>
                    <code>{t.slug}</code>
                  </TableCell>
                  <TableCell sx={{ maxWidth: 280 }}>
                    <Typography variant="body2" color="text.secondary" noWrap>
                      {t.description || '—'}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">{t.team_count}</TableCell>
                  <TableCell align="right">{t.user_count}</TableCell>
                  <TableCell>
                    {new Date(t.created_at).toLocaleDateString()}
                  </TableCell>
                  <TableCell align="right">
                    <Tooltip title={t.is_default ? 'Default tenant cannot be deleted' : 'Edit'}>
                      <span>
                        <IconButton size="small" onClick={() => setEditTarget(t)}>
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </span>
                    </Tooltip>
                    <Tooltip title={t.is_default ? 'Default tenant is undeletable' : 'Delete'}>
                      <span>
                        <IconButton
                          size="small"
                          color="error"
                          disabled={t.is_default}
                          onClick={() => setConfirmDelete(t)}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </span>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      {createOpen && (
        <TenantFormDialog
          title="New Tenant"
          submitLabel="Create"
          onSubmit={handleCreate}
          onCancel={() => setCreateOpen(false)}
          busy={busy}
        />
      )}

      {editTarget && (
        <TenantFormDialog
          title={`Edit ${editTarget.name}`}
          submitLabel="Save"
          initial={editTarget}
          onSubmit={(input) => handleUpdate(editTarget.id, input)}
          onCancel={() => setEditTarget(null)}
          busy={busy}
          lockName={editTarget.is_default}
        />
      )}

      <Dialog open={!!confirmDelete} onClose={() => setConfirmDelete(null)}>
        <DialogTitle>Delete tenant?</DialogTitle>
        <DialogContent>
          {confirmDelete && (
            <Typography>
              "{confirmDelete.name}" ({confirmDelete.slug}) will be removed.
              Users with explicit grants lose access; teams stay in place but
              their tenant_id would be invalid — refuse-with-409 if any team
              still references it.
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmDelete(null)} disabled={busy}>
            Cancel
          </Button>
          <Button
            color="error"
            variant="contained"
            disabled={busy}
            onClick={() => confirmDelete && handleDelete(confirmDelete)}
          >
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
};

interface TenantFormDialogProps {
  title: string;
  submitLabel: string;
  initial?: Tenant;
  onSubmit: (input: CreateTenantInput | UpdateTenantInput) => void;
  onCancel: () => void;
  busy: boolean;
  lockName?: boolean;
}

const TenantFormDialog: React.FC<TenantFormDialogProps> = ({
  title, submitLabel, initial, onSubmit, onCancel, busy, lockName,
}) => {
  const [name, setName] = useState(initial?.name ?? '');
  const [slug, setSlug] = useState(initial?.slug ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [footerLogoUrl, setFooterLogoUrl] = useState(initial?.footer_logo_url ?? '');
  const [footerLogoAlt, setFooterLogoAlt] = useState(initial?.footer_logo_alt ?? '');
  const [footerTextColor, setFooterTextColor] = useState(initial?.footer_text_color ?? '');
  const [formError, setFormError] = useState<string | null>(null);

  const submit = () => {
    setFormError(null);
    if (!name.trim()) return setFormError('Name is required');
    if (!slug.trim()) return setFormError('Slug is required');
    if (!SLUG_RE.test(slug)) {
      return setFormError('Slug must match ^[a-z0-9][a-z0-9-]{0,62}$');
    }
    const trimmedLogoUrl = footerLogoUrl.trim();
    if (trimmedLogoUrl && !/^https:\/\//i.test(trimmedLogoUrl)) {
      return setFormError('Footer logo URL must start with https://');
    }
    const trimmedColor = footerTextColor.trim();
    if (trimmedColor && !/^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(trimmedColor)) {
      return setFormError('Text color must be a hex like #1a73e8');
    }
    onSubmit({
      name: name.trim(),
      slug: slug.trim(),
      description: description.trim(),
      footer_logo_url: trimmedLogoUrl,
      footer_logo_alt: footerLogoAlt.trim(),
      footer_text_color: trimmedColor,
    });
  };

  return (
    <Dialog open onClose={onCancel} maxWidth="sm" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {formError && <Alert severity="error">{formError}</Alert>}
          <TextField
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={busy || !!lockName}
            fullWidth
            required
            helperText={lockName ? 'Default tenant name cannot be empty' : ''}
          />
          <TextField
            label="Slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value.toLowerCase())}
            disabled={busy}
            fullWidth
            required
            helperText="URL-safe identifier; ^[a-z0-9][a-z0-9-]{0,62}$"
          />
          <TextField
            label="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={busy}
            fullWidth
            multiline
            minRows={2}
          />
          <Typography variant="overline" sx={{ mt: 1, color: 'text.secondary' }}>
            Footer branding
          </Typography>
          <TextField
            label="Footer logo URL"
            value={footerLogoUrl}
            onChange={(e) => setFooterLogoUrl(e.target.value)}
            disabled={busy}
            fullWidth
            placeholder="https://cdn.example.com/footer-logo.svg"
            helperText="Optional. https:// URL; renders at 28 px height next to the copyright line. Leave blank to fall through to the deployment-level logo."
          />
          <TextField
            label="Footer logo alt text"
            value={footerLogoAlt}
            onChange={(e) => setFooterLogoAlt(e.target.value)}
            disabled={busy}
            fullWidth
            placeholder="Acme logo"
            helperText="Accessibility label; falls back to '<Tenant Name> logo' when empty."
          />
          <TextField
            label="Footer text color"
            value={footerTextColor}
            onChange={(e) => setFooterTextColor(e.target.value)}
            disabled={busy}
            fullWidth
            placeholder="#1a73e8"
            helperText="Optional hex accent (#RGB, #RRGGBB or #RRGGBBAA). Applied to the copyright text."
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel} disabled={busy}>Cancel</Button>
        <Button variant="contained" onClick={submit} disabled={busy}>
          {submitLabel}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default Tenants;