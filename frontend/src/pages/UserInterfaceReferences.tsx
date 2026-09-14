import {
  ArrowBack as ArrowBackIcon,
  History as HistoryIcon,
  Search as SearchIcon,
} from '@mui/icons-material';
import {
  Alert,
  Box,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  IconButton,
  InputAdornment,
  MenuItem,
  Paper,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { ReferenceHistoryModal } from '../components/verification/ReferenceHistoryModal';
import { ReferenceImagePreview } from '../components/verification/ReferenceImagePreview';
import {
  UserInterfaceReference,
  useUserInterfaceReferences,
} from '../hooks/pages/useUserInterfaceReferences';
import { invalidateSignedUrl } from '../utils/infrastructure/cloudflareUtils';

type TypeFilter = 'all' | 'image' | 'text';

// Fixed-width, space-padded row so `x`/`y`/`w`/`h` line up vertically
// across every row. Requires a monospace font + whiteSpace:'pre' on the
// cell. Label is padded to 5 ("area "/"fuzzy"); each value to 4 chars
// (handles 4-digit capture coords like 1920/1080).
const COORD_W = 4;
const fmtAreaRow = (
  label: 'area' | 'fuzzy',
  x: number,
  y: number,
  w: number,
  h: number,
): string => {
  const v = (n: number) => String(Math.round(n ?? 0)).padEnd(COORD_W);
  return `${label.padEnd(5)} x:${v(x)} y:${v(y)} w:${v(w)} h:${v(h)}`;
};

const formatArea = (area: UserInterfaceReference['area']): string => {
  if (!area || (area.width === 0 && area.height === 0 && area.x === 0 && area.y === 0)) {
    return '—';
  }
  return fmtAreaRow('area', area.x, area.y, area.width, area.height);
};

// Fuzzy match area (fx/fy/fwidth/fheight) — optional, only set on
// references whose verification uses a fuzzy search region.
const formatFuzzy = (area: UserInterfaceReference['area']): string => {
  if (
    !area ||
    area.fx === undefined ||
    area.fy === undefined ||
    area.fwidth === undefined ||
    area.fheight === undefined
  ) {
    return '—';
  }
  return fmtAreaRow('fuzzy', area.fx, area.fy, area.fwidth, area.fheight);
};

const formatDate = (iso: string | undefined): string => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
};

const UserInterfaceReferencesPage: React.FC = () => {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const decodedName = name ? decodeURIComponent(name) : '';

  const { references, loading, error, refetch } = useUserInterfaceReferences(decodedName);

  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all');
  // Reference whose version history is open in the modal (null = closed).
  const [historyRef, setHistoryRef] = useState<UserInterfaceReference | null>(null);

  // After a restore the live R2 key was overwritten in place — drop its cached
  // signed URL so previews re-sign to the restored bytes, then refetch the list.
  const handleRestored = () => {
    if (historyRef?.url) invalidateSignedUrl(historyRef.url);
    refetch();
  };

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim().toLowerCase()), 150);
    return () => clearTimeout(t);
  }, [search]);

  const filtered = useMemo(() => {
    const list = references.filter((ref) => {
      if (typeFilter !== 'all' && ref.type !== typeFilter) return false;
      if (!debouncedSearch) return true;
      const nameMatch = ref.name.toLowerCase().includes(debouncedSearch);
      const textMatch =
        ref.type === 'text' && ref.text
          ? ref.text.toLowerCase().includes(debouncedSearch)
          : false;
      return nameMatch || textMatch;
    });
    return [...list].sort((a, b) => {
      if (a.type !== b.type) return a.type === 'image' ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  }, [references, debouncedSearch, typeFilter]);

  const totals = useMemo(() => {
    let images = 0;
    let texts = 0;
    for (const r of references) {
      if (r.type === 'image') images += 1;
      else texts += 1;
    }
    return { total: references.length, images, texts };
  }, [references]);

  const renderTableBody = () => {
    if (references.length === 0) {
      return (
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
            No references for this interface
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 420 }}>
            Image and text references are created from the Verification editor when capturing
            references in the Navigation editor.
          </Typography>
        </Box>
      );
    }

    if (filtered.length === 0) {
      return (
        <Box sx={{ py: 4, textAlign: 'center' }}>
          <Typography color="text.secondary">No references match these filters.</Typography>
        </Box>
      );
    }

    return (
      <TableContainer component={Paper} variant="outlined" sx={{ boxShadow: 'none' }}>
        <Table
          size="small"
          sx={{
            tableLayout: 'fixed',
            '& .MuiTableCell-root': { py: 0.5, px: 1 },
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
              <TableCell align="center" sx={{ width: '5%' }}>
                <strong>Type</strong>
              </TableCell>
              <TableCell sx={{ width: '19%' }}>
                <strong>Name</strong>
              </TableCell>
              <TableCell sx={{ width: '22%' }}>
                <strong>Preview</strong>
              </TableCell>
              <TableCell sx={{ width: '15%' }}>
                <strong>Area</strong>
              </TableCell>
              <TableCell align="center" sx={{ width: '7%' }}>
                <strong>Shared</strong>
              </TableCell>
              <TableCell sx={{ width: '11%' }}>
                <strong>Created</strong>
              </TableCell>
              <TableCell sx={{ width: '11%' }}>
                <strong>Updated</strong>
              </TableCell>
              <TableCell align="center" sx={{ width: '10%' }}>
                <strong>History</strong>
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {filtered.map((ref) => (
              <TableRow key={ref.id}>
                <TableCell align="center">
                  <Typography component="span" sx={{ fontSize: '1rem' }}>
                    {ref.type === 'image' ? '🖼️' : '📝'}
                  </Typography>
                </TableCell>
                <TableCell sx={{ wordBreak: 'break-word' }}>{ref.name || '—'}</TableCell>
                <TableCell>
                  {ref.type === 'image' ? (
                    ref.url ? (
                      <ReferenceImagePreview
                        referenceUrl={ref.url}
                        thumbnail
                        thumbnailMaxWidth={120}
                        thumbnailMaxHeight={68}
                      />
                    ) : (
                      <Typography variant="body2" color="text.secondary">
                        no image
                      </Typography>
                    )
                  ) : (
                    <Typography
                      variant="body2"
                      sx={{
                        fontFamily: 'monospace',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        maxHeight: 80,
                        overflow: 'auto',
                      }}
                    >
                      {ref.text || '—'}
                    </Typography>
                  )}
                </TableCell>
                <TableCell
                  sx={{ fontFamily: 'monospace', fontSize: '0.75rem', whiteSpace: 'pre' }}
                >
                  <Box>{formatArea(ref.area)}</Box>
                  {formatFuzzy(ref.area) !== '—' && (
                    <Box sx={{ color: 'text.secondary', mt: 0.25 }}>
                      {formatFuzzy(ref.area)}
                    </Box>
                  )}
                </TableCell>
                <TableCell align="center">
                  {ref.shared ? <Chip size="small" label="Shared" /> : null}
                </TableCell>
                <TableCell sx={{ fontSize: '0.75rem' }}>{formatDate(ref.created_at)}</TableCell>
                <TableCell sx={{ fontSize: '0.75rem' }}>{formatDate(ref.updated_at)}</TableCell>
                <TableCell align="center">
                  <IconButton
                    size="small"
                    title="Version history"
                    onClick={() => setHistoryRef(ref)}
                  >
                    <HistoryIcon fontSize="small" />
                  </IconButton>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    );
  };

  return (
    <Box>
      <Box sx={{ mb: 1 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <IconButton
            size="small"
            onClick={() => navigate('/configuration/interface')}
            title="Back to Interfaces"
          >
            <ArrowBackIcon />
          </IconButton>
          <Typography variant="h4" sx={{ m: 0 }}>
            References — {decodedName}
          </Typography>
        </Box>
        {!loading && references.length > 0 && (
          <Typography
            variant="body2"
            color="textSecondary"
            sx={{ ml: '42px', mt: 0.25 }}
          >
            {filtered.length} of {totals.total} references ({totals.images} image,{' '}
            {totals.texts} text)
          </Typography>
        )}
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {error}
        </Alert>
      )}

      <Card sx={{ boxShadow: 1 }}>
        <CardContent sx={{ p: 1, '&:last-child': { pb: 1 } }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
            <TextField
              size="small"
              placeholder="Search by name or text…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon fontSize="small" />
                  </InputAdornment>
                ),
              }}
              sx={{ flex: 1, maxWidth: 480 }}
            />
            <Select
              size="small"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value as TypeFilter)}
              sx={{ minWidth: 140 }}
            >
              <MenuItem value="all">All types</MenuItem>
              <MenuItem value="image">🖼️ Image</MenuItem>
              <MenuItem value="text">📝 Text</MenuItem>
            </Select>
          </Box>

          {loading ? (
            <Box
              sx={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                py: 8,
              }}
            >
              <CircularProgress size={40} sx={{ mb: 2 }} />
              <Typography variant="h6" color="text.secondary">
                Loading references…
              </Typography>
            </Box>
          ) : (
            renderTableBody()
          )}
        </CardContent>
      </Card>

      <ReferenceHistoryModal
        open={historyRef !== null}
        onClose={() => setHistoryRef(null)}
        reference={
          historyRef ? { id: historyRef.id, name: historyRef.name, type: historyRef.type } : null
        }
        onRestored={handleRestored}
      />
    </Box>
  );
};

export default UserInterfaceReferencesPage;
