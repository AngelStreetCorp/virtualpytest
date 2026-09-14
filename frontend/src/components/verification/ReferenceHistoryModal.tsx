import { Close as CloseIcon } from '@mui/icons-material';
import {
  Box,
  Button,
  CircularProgress,
  DialogContent,
  DialogTitle,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import React, { useEffect, useState } from 'react';

import { StyledDialog } from '../common/StyledDialog';
import { useReferenceVersions } from '../../hooks/verification/useReferenceVersions';
import { ReferenceImagePreview } from './ReferenceImagePreview';

interface ReferenceHistoryModalProps {
  open: boolean;
  onClose: () => void;
  reference: { id: string; name: string; type: 'image' | 'text' } | null;
  // Called after a successful restore so the parent can refetch + bust the
  // live signed-URL cache (the live key was overwritten in place).
  onRestored: () => void;
}

const formatDate = (iso: string | undefined): string => {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
};

export const ReferenceHistoryModal: React.FC<ReferenceHistoryModalProps> = ({
  open,
  onClose,
  reference,
  onRestored,
}) => {
  const { versions, loading, restoringId, list, restore } = useReferenceVersions();
  // Version id pending confirm (inline two-step restore).
  const [confirmId, setConfirmId] = useState<string | null>(null);

  useEffect(() => {
    if (open && reference) {
      setConfirmId(null);
      list(reference.id);
    }
  }, [open, reference, list]);

  const handleRestore = async (versionId: string) => {
    if (!reference) return;
    const ok = await restore(reference.id, versionId);
    setConfirmId(null);
    if (ok) {
      onRestored();
      list(reference.id); // refresh — current state is now the new top version
    }
  };

  return (
    <StyledDialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      PaperProps={{
        // Fixed height so the modal doesn't jump/resize with the number of
        // versions (1 row vs 10 vs empty all render at the same size; the body
        // scrolls). StyledDialog supplies the bordered surface over the dark page.
        sx: {
          height: '70vh',
        },
      }}
    >
      <DialogTitle sx={{ py: 1, px: 2, pr: 6, fontSize: '1rem', fontWeight: 600 }}>
        History — {reference?.name}
        <IconButton
          onClick={onClose}
          size="small"
          sx={{ position: 'absolute', right: 8, top: 6 }}
        >
          <CloseIcon fontSize="small" />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers sx={{ p: 0, overflowY: 'auto' }}>
        {loading ? (
          <Box
            sx={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >
            <CircularProgress size={32} />
          </Box>
        ) : versions.length === 0 ? (
          <Box
            sx={{
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              textAlign: 'center',
              px: 4,
            }}
          >
            <Typography color="text.secondary">
              No previous versions yet. A version is saved each time this reference is recaptured.
            </Typography>
          </Box>
        ) : (
          <TableContainer>
            <Table
              size="small"
              sx={{
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
                  <TableCell sx={{ width: '12%' }}>
                    <strong>Version</strong>
                  </TableCell>
                  <TableCell sx={{ width: '36%' }}>
                    <strong>Preview</strong>
                  </TableCell>
                  <TableCell sx={{ width: '30%' }}>
                    <strong>Captured</strong>
                  </TableCell>
                  <TableCell align="right" sx={{ width: '22%' }}>
                    <strong>Action</strong>
                  </TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {versions.map((v) => (
                  <TableRow key={v.id}>
                    <TableCell>v{v.version_number}</TableCell>
                    <TableCell>
                      {v.reference_type === 'reference_image' ? (
                        v.r2_url ? (
                          <ReferenceImagePreview
                            referenceUrl={v.r2_url}
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
                          {v.area?.text ?? '—'}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell sx={{ fontSize: '0.8rem' }}>{formatDate(v.created_at)}</TableCell>
                    <TableCell align="right">
                      {confirmId === v.id ? (
                        <Box sx={{ display: 'inline-flex', gap: 0.5 }}>
                          <Button
                            size="small"
                            variant="contained"
                            color="warning"
                            disabled={restoringId === v.id}
                            onClick={() => handleRestore(v.id)}
                          >
                            {restoringId === v.id ? '…' : 'Confirm'}
                          </Button>
                          <Button size="small" onClick={() => setConfirmId(null)}>
                            Cancel
                          </Button>
                        </Box>
                      ) : (
                        <Button
                          size="small"
                          variant="outlined"
                          disabled={restoringId !== null}
                          onClick={() => setConfirmId(v.id)}
                        >
                          Restore
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </DialogContent>
    </StyledDialog>
  );
};

export default ReferenceHistoryModal;
