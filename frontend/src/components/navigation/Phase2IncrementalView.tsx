import React from 'react';
import {
  Box,
  Typography,
  LinearProgress,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Chip,
  Paper,
  Alert
} from '@mui/material';
import {
  CheckCircle as SuccessIcon,
  Error as ErrorIcon,
  HourglassEmpty as PendingIcon,
  PlayArrow as InProgressIcon
} from '@mui/icons-material';
import type { ExplorationContext } from '../../types/exploration';

interface Phase2IncrementalViewProps {
  context: ExplorationContext | null;
  error?: string | null;
  selectedNodes?: Set<string>;
  onToggleNode?: (nodeName: string) => void;
}

export const Phase2IncrementalView: React.FC<Phase2IncrementalViewProps> = ({
  context,
  error,
  selectedNodes = new Set(),
  onToggleNode
}) => {
  if (!context) {
    return (
      <Box sx={{ p: 2 }}>
        <Typography color="text.secondary">No context available</Typography>
      </Box>
    );
  }

  const { predicted_items, current_step, total_steps, completed_items, failed_items } = context;
  const progress = total_steps > 0 ? (current_step / total_steps) * 100 : 0;

  return (
    <Box>
      {/* Progress Bar */}
      <Box sx={{ mb: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
          <Typography variant="body2" fontWeight="bold">
            Creating and Testing Items
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {current_step} / {total_steps}
          </Typography>
        </Box>
        <LinearProgress variant="determinate" value={progress} sx={{ height: 8, borderRadius: 1 }} />
        <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
          {Math.round(progress)}% complete
        </Typography>
      </Box>

      {/* Error Alert */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          <Typography variant="body2" fontWeight="bold">Stopped on error:</Typography>
          <Typography variant="body2">{error}</Typography>
        </Alert>
      )}

      {/* Items List */}
      <Paper variant="outlined" sx={{ maxHeight: 300, overflow: 'auto', border: '1px solid white' }}>
        <List dense>
          {predicted_items.map((item, index) => {
            const isCompleted = completed_items.includes(item);
            const isFailed = failed_items.some(f => f.item === item);
            const isCurrent = index === current_step && !isCompleted && !isFailed;
            const isSelected = selectedNodes.has(item);

            let icon = <PendingIcon color="disabled" />;
            let statusChip = <Chip 
              label="Pending" 
              size="small" 
              variant="outlined"
              onClick={() => onToggleNode?.(item)}
              sx={{ 
                cursor: 'pointer',
                bgcolor: isSelected ? 'primary.dark' : 'grey.800',
                opacity: isSelected ? 1 : 0.5
              }}
            />;

            if (isCompleted) {
              icon = <SuccessIcon color="success" />;
              statusChip = <Chip 
                label="✓ Tested" 
                size="small" 
                color="success"
                onClick={() => onToggleNode?.(item)}
                sx={{ 
                  cursor: 'pointer',
                  opacity: isSelected ? 1 : 0.5
                }}
              />;
            } else if (isFailed) {
              icon = <ErrorIcon color="error" />;
              statusChip = <Chip 
                label="Failed" 
                size="small" 
                color="error"
                onClick={() => onToggleNode?.(item)}
                sx={{ 
                  cursor: 'pointer',
                  opacity: isSelected ? 1 : 0.5
                }}
              />;
            } else if (isCurrent) {
              icon = <InProgressIcon color="primary" />;
              statusChip = <Chip 
                label="Testing..." 
                size="small" 
                color="primary"
                onClick={() => onToggleNode?.(item)}
                sx={{ 
                  cursor: 'pointer',
                  opacity: isSelected ? 1 : 0.5
                }}
              />;
            }

            return (
              <ListItem
                key={item}
                sx={{
                  bgcolor: isCurrent ? 'action.hover' : 'transparent',
                  borderLeft: isCurrent ? 3 : 0,
                  borderColor: 'primary.main'
                }}
              >
                <ListItemIcon sx={{ minWidth: 40 }}>{icon}</ListItemIcon>
                <ListItemText
                  primary={item}
                  primaryTypographyProps={{
                    fontWeight: isCurrent ? 'bold' : 'normal',
                    color: isCompleted ? 'success.main' : isFailed ? 'error.main' : 'text.primary'
                  }}
                />
                {statusChip}
              </ListItem>
            );
          })}
        </List>
      </Paper>

      {/* Sub-steps (for current item) */}
      {current_step < total_steps && !error && (
        <Box sx={{ mt: 2, p: 2, bgcolor: 'action.hover', borderRadius: 1 }}>
          <Typography variant="caption" color="text.secondary" display="block">
            Current item steps:
          </Typography>
          <Typography variant="body2" sx={{ mt: 0.5 }}>
            1. Create node ✓<br />
            2. Create edge ✓<br />
            3. Test edge (execute_edge) ⏳<br />
            4. Capture screenshot...
          </Typography>
        </Box>
      )}
    </Box>
  );
};

