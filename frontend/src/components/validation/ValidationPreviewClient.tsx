'use client';

import { PlayArrow as PlayArrowIcon, Visibility as VisibilityIcon } from '@mui/icons-material';
import {
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
  Box,
  Chip,
  Divider,
  CircularProgress,
  Checkbox,
  FormControl,
  Select,
  MenuItem,
  ListItemText,
  SelectChangeEvent,
  List,
  ListItem,
} from '@mui/material';
import { useState, useEffect } from 'react';

// Tree names are stored in the DB with a " - Subtree" suffix
// (e.g. "apps - Subtree"). Strip it so chips/dropdown show just "apps".
const cleanTreeName = (name: string) =>
  name.replace(/\s*-\s*Subtree\s*$/i, '').trim() || name;

import { useValidation } from '../../hooks/validation';
import { StyledDialog } from '../common/StyledDialog';

interface ValidationPreviewClientProps {
  treeId: string;
  onClose?: () => void;
  selectedHost?: any;
  selectedDeviceId?: string | null;
}

export default function ValidationPreviewClient({ treeId, onClose, selectedHost, selectedDeviceId }: ValidationPreviewClientProps) {
  const validation = useValidation(treeId, selectedHost, selectedDeviceId);
  const [selectedEdges, setSelectedEdges] = useState<Set<string>>(new Set());
  // Tree filter: empty set === no filter (show all). Populated set === only show
  // rows whose tree_id is in the set. Reset whenever the preview reloads.
  const [treeFilter, setTreeFilter] = useState<Set<string>>(new Set());

  useEffect(() => {
    setTreeFilter(new Set());
  }, [validation.preview]);

  // Load preview data when component mounts if not already loaded
  useEffect(() => {
    if (!validation.preview && !validation.isLoadingPreview && !validation.validationError) {
      validation.loadPreview();
    }
  }, [validation.preview, validation.isLoadingPreview, validation.validationError, validation.loadPreview]);

  // Auto-select all edges when preview loads. Every preview row corresponds
  // 1:1 to a real edge the runner will execute.
  useEffect(() => {
    if (validation.preview?.edges) {
      const allEdgeIds = validation.preview.edges.map((edge) => String(edge.step_number));
      setSelectedEdges(new Set(allEdgeIds));
    }
  }, [validation.preview]);

  // Close preview when validation starts
  useEffect(() => {
    if (validation.isValidating && onClose) {
      onClose();
    }
  }, [validation.isValidating, onClose]);

  const handleEdgeToggle = (edgeId: string) => {
    setSelectedEdges((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(edgeId)) newSet.delete(edgeId);
      else newSet.add(edgeId);
      return newSet;
    });
  };

  const isEdgeVisible = (edge: { tree_id?: string }) =>
    treeFilter.size === 0 || (edge.tree_id !== undefined && treeFilter.has(edge.tree_id));

  const handleSelectAll = () => {
    if (validation.preview?.edges) {
      // Select-all only affects rows currently visible under the active tree filter.
      const visibleEdgeIds = validation.preview.edges
        .filter(isEdgeVisible)
        .map((edge) => String(edge.step_number));
      setSelectedEdges((prev) => {
        const next = new Set(prev);
        visibleEdgeIds.forEach((id) => next.add(id));
        return next;
      });
    }
  };

  const handleDeselectAll = () => {
    if (!validation.preview?.edges) return;
    if (treeFilter.size === 0) {
      setSelectedEdges(new Set());
      return;
    }
    const visibleEdgeIds = new Set(
      validation.preview.edges.filter(isEdgeVisible).map((edge) => String(edge.step_number)),
    );
    setSelectedEdges((prev) => {
      const next = new Set(prev);
      visibleEdgeIds.forEach((id) => next.delete(id));
      return next;
    });
  };

  const handleRunValidation = () => {
    if (!validation.preview?.edges) return;

    // Send selected step_numbers to the script. The runner executes exactly
    // these rows in order (no dedupe), so the report row count matches
    // preview-row-count 1:1.
    const stepNumbers = validation.preview.edges
      .filter((edge) => selectedEdges.has(String(edge.step_number)))
      .map((edge) => String(edge.step_number));
    console.log(`[@component:ValidationPreview] Running validation with ${stepNumbers.length} step(s)`);
    validation.runValidation(stepNumbers);
  };

  // Show error dialog if there's a persistent error
  if (validation.validationError && !validation.isLoadingPreview) {
    return (
      <StyledDialog open={true} maxWidth="md" fullWidth>
        <DialogTitle>Validation Preview Error</DialogTitle>
        <DialogContent>
          <Box py={1}>
            <Typography color="error" gutterBottom>
              Failed to load validation preview:
            </Typography>
            <Typography variant="body2" color="textSecondary">
              {validation.validationError}
            </Typography>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Close</Button>
          <Button 
            variant="outlined" 
            onClick={() => {
              validation.loadPreview();
            }}
          >
            Retry
          </Button>
        </DialogActions>
      </StyledDialog>
    );
  }

  // Only show dialog when there's preview data or when loading
  if (!validation.preview && !validation.isLoadingPreview) {
    return null;
  }

  // Show loading dialog
  if (!validation.preview && validation.isLoadingPreview) {
    return (
      <StyledDialog open={true} maxWidth="md" fullWidth>
        <DialogTitle>Validation Preview</DialogTitle>
        <DialogContent>
          <Box display="flex" justifyContent="center" alignItems="center" py={1}>
            <CircularProgress size={24} sx={{ mr: 2 }} />
            <Typography>Loading validation preview...</Typography>
          </Box>
        </DialogContent>
      </StyledDialog>
    );
  }

  const selectedCount = selectedEdges.size;
  const totalCount = validation.preview?.edges?.length || 0;

  // Build the tree filter toolbar: only show it when more than one tree is referenced.
  const treesById = validation.preview?.trees ?? {};
  const referencedTreeIds = Array.from(
    new Set((validation.preview?.edges ?? []).map((edge) => edge.tree_id).filter(Boolean) as string[]),
  );
  // Root first, then subtrees alphabetically by name.
  referencedTreeIds.sort((a, b) => {
    const ta = treesById[a];
    const tb = treesById[b];
    if (ta?.is_root && !tb?.is_root) return -1;
    if (!ta?.is_root && tb?.is_root) return 1;
    return (ta?.name ?? a).localeCompare(tb?.name ?? b);
  });
  const showTreeFilter = referencedTreeIds.length > 1;

  const visibleEdges = (validation.preview?.edges ?? []).filter(isEdgeVisible);
  const visibleSelectedCount = visibleEdges.filter((edge) => selectedEdges.has(String(edge.step_number))).length;
  const canSelectAll = visibleEdges.length > 0;

  return (
    <StyledDialog open={true} maxWidth="md" fullWidth>
      <DialogTitle>
        <Box display="flex" alignItems="center" gap={1}>
          <VisibilityIcon />
          <Typography variant="h6">Validation Preview</Typography>
        </Box>
      </DialogTitle>

      <DialogContent>
        <Box sx={{ mb: 0.75, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
          <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 500 }}>
            {selectedCount}/{totalCount} selected
          </Typography>
          <Typography
            variant="caption"
            color={canSelectAll ? 'primary.main' : 'text.disabled'}
            sx={{ cursor: canSelectAll ? 'pointer' : 'default' }}
            onClick={canSelectAll ? handleSelectAll : undefined}
          >
            select all
          </Typography>
          <Typography variant="caption" color="text.disabled">-</Typography>
          <Typography
            variant="caption"
            color={visibleSelectedCount > 0 ? 'primary.main' : 'text.disabled'}
            sx={{ cursor: visibleSelectedCount > 0 ? 'pointer' : 'default' }}
            onClick={visibleSelectedCount > 0 ? handleDeselectAll : undefined}
          >
            unselect all
          </Typography>
          {showTreeFilter && (
            <FormControl size="small" sx={{ ml: 'auto', width: 140, flexShrink: 0 }}>
              <Select
                multiple
                displayEmpty
                value={Array.from(treeFilter)}
                onChange={(e: SelectChangeEvent<string[]>) =>
                  setTreeFilter(new Set(e.target.value as string[]))
                }
                renderValue={(selected) => {
                  const arr = selected as string[];
                  return arr.length === 0 ? 'Trees' : `Trees (${arr.length})`;
                }}
              >
                {referencedTreeIds.map((tid) => {
                  const tree = treesById[tid];
                  const cleaned = tree ? cleanTreeName(tree.name) : tid;
                  const label = tree?.is_root ? `Root: ${cleaned}` : cleaned;
                  return (
                    <MenuItem key={tid} value={tid} dense>
                      <Checkbox size="small" checked={treeFilter.has(tid)} />
                      <ListItemText primary={label} primaryTypographyProps={{ variant: 'body2' }} />
                    </MenuItem>
                  );
                })}
              </Select>
            </FormControl>
          )}
        </Box>

        <Divider sx={{ my: 0 }} />

        <List dense disablePadding>
          {visibleEdges.map((edge, index) => {
            const edgeId = String(edge.step_number);
            const isSelected = selectedEdges.has(edgeId);
            const tree = edge.tree_id ? treesById[edge.tree_id] : undefined;
            const treeBadgeLabel = tree
              ? tree.is_root
                ? `Root: ${cleanTreeName(tree.name)}`
                : cleanTreeName(tree.name)
              : edge.tree_id
                ? edge.tree_id
                : null;

            return (
              <ListItem
                key={edgeId}
                divider
                disableGutters
                sx={{ display: 'flex', alignItems: 'center', gap: 0.75, px: 1, py: 0.5 }}
              >
                <Typography
                  variant="body2"
                  fontWeight="bold"
                  sx={{ fontSize: '14px', flex: '0 0 auto', whiteSpace: 'nowrap' }}
                >
                  {index + 1}. {edge.from_name} → {edge.to_name}
                </Typography>
                <Box sx={{ ml: 'auto', display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                  {treeBadgeLabel && (
                    <Chip
                      label={treeBadgeLabel}
                      size="small"
                      color={tree?.is_root ? 'success' : 'secondary'}
                      variant="outlined"
                      title={tree?.is_root ? 'Root tree' : 'Subtree'}
                    />
                  )}
                  {edge.has_verifications && (
                    <Chip
                      label="Has Verifications"
                      size="small"
                      color="info"
                      variant="outlined"
                    />
                  )}
                  {edge.actions && edge.actions.length > 0 && (
                    <Chip
                      label={`${edge.actions.length} actions`}
                      size="small"
                      color="default"
                      variant="outlined"
                    />
                  )}
                </Box>
                <Checkbox
                  checked={isSelected}
                  onChange={() => handleEdgeToggle(edgeId)}
                  color="primary"
                  size="small"
                  sx={{ p: 0.25, flexShrink: 0 }}
                />
              </ListItem>
            );
          })}
        </List>
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          startIcon={<PlayArrowIcon />}
          onClick={handleRunValidation}
          disabled={selectedCount === 0}
        >
          Run
        </Button>
      </DialogActions>
    </StyledDialog>
  );
}
