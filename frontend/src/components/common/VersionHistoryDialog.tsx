import React from 'react';
import {
  Box,
  Button,
  Chip,
  DialogActions,
  DialogContent,
  DialogTitle,
  Paper,
  Stack,
  Typography,
} from '@mui/material';

import { StyledDialog } from './StyledDialog';

export interface VersionHistoryRow {
  version_number: number;
  modified_at?: string | null;
  snapshot_timestamp?: string | null;
  modified_by?: string | null;
  created_by?: string | null;
  changes_summary?: string | null;
  change_description?: string | null;
  restored_from_version?: number | null;
}

interface VersionHistoryDialogProps {
  open: boolean;
  title: string;
  rows: VersionHistoryRow[];
  loading?: boolean;
  currentVersion?: number | null;
  restoringVersion?: number | null;
  emptyMessage: string;
  onClose: () => void;
  onRestore: (versionNumber: number) => void | Promise<void>;
}

const formatTimestamp = (value?: string | null) => {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return `${date.toLocaleDateString()} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
};

const resolveNotes = (row: VersionHistoryRow) => {
  if (row.changes_summary) return row.changes_summary;
  if (row.change_description) return row.change_description;
  if (row.restored_from_version) return `Restored from version ${row.restored_from_version}`;
  return '';
};

export const VersionHistoryDialog: React.FC<VersionHistoryDialogProps> = ({
  open,
  title,
  rows,
  loading = false,
  currentVersion = null,
  restoringVersion = null,
  emptyMessage,
  onClose,
  onRestore,
}) => {
  return (
    <StyledDialog open={open} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle sx={{ borderBottom: 1, borderColor: 'divider', pb: 1.5 }}>
        {title}
      </DialogTitle>
      <DialogContent sx={{ pt: 2 }}>
        {loading ? (
          <Typography sx={{ py: 2 }}>Loading version history...</Typography>
        ) : rows.length === 0 ? (
          <Typography color="text.secondary" sx={{ py: 2 }}>
            {emptyMessage}
          </Typography>
        ) : (
          <Box sx={{ overflowX: 'auto' }}>
            <Stack spacing={1} sx={{ minWidth: 760 }}>
              <Box
                sx={{
                  display: 'grid',
                  gridTemplateColumns: '120px 190px 160px minmax(160px, 1fr) 110px',
                  gap: 1,
                  px: 1,
                  color: 'text.secondary',
                  typography: 'caption',
                }}
              >
                <Box>Version</Box>
                <Box>Date</Box>
                <Box>Updated by</Box>
                <Box>Notes</Box>
                <Box sx={{ textAlign: 'right' }}>Action</Box>
              </Box>

              {rows.map((row) => {
                const timestamp = row.modified_at || row.snapshot_timestamp;
                const isLatest = currentVersion === row.version_number;
                return (
                  <Paper
                    key={row.version_number}
                    variant="outlined"
                    sx={{
                      px: 1,
                      py: 1,
                      display: 'grid',
                      gridTemplateColumns: '120px 190px 160px minmax(160px, 1fr) 110px',
                      gap: 1,
                      alignItems: 'center',
                    }}
                  >
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {row.version_number}
                      </Typography>
                      {isLatest ? <Chip label="Latest" size="small" color="secondary" /> : null}
                    </Box>
                    <Typography variant="body2">{formatTimestamp(timestamp)}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {row.modified_by || row.created_by || '-'}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ minWidth: 0 }}>
                      {resolveNotes(row) || '-'}
                    </Typography>
                    <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                      {isLatest ? null : (
                        <Button
                          size="small"
                          variant="outlined"
                          onClick={() => onRestore(row.version_number)}
                          disabled={restoringVersion === row.version_number}
                        >
                          {restoringVersion === row.version_number ? 'Restoring...' : 'Restore'}
                        </Button>
                      )}
                    </Box>
                  </Paper>
                );
              })}
            </Stack>
          </Box>
        )}
      </DialogContent>
      <DialogActions sx={{ borderTop: 1, borderColor: 'divider', px: 3, py: 2 }}>
        <Button onClick={onClose} variant="outlined">
          Close
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};
