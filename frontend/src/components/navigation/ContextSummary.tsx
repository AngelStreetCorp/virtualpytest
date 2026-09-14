import React, { useState } from 'react';
import {
  Box,
  Typography,
  Paper,
  Chip,
  Collapse,
  IconButton,
  Divider,
  Grid
} from '@mui/material';
import {
  ExpandMore as ExpandIcon,
  ExpandLess as CollapseIcon,
  DevicesOther as DeviceIcon,
  Speed as StrategyIcon,
  ListAlt as ItemsIcon
} from '@mui/icons-material';
import type { ExplorationContext } from '../../types/exploration';

interface ContextSummaryProps {
  context: ExplorationContext | null;
}

export const ContextSummary: React.FC<ContextSummaryProps> = ({ context }) => {
  const [expanded, setExpanded] = useState(false);

  if (!context) {
    return null;
  }

  const {
    device_model,
    strategy,
    has_dump_ui,
    predicted_items,
    current_step,
    total_steps,
    original_prompt
  } = context;

  const progressPercent = total_steps > 0 ? Math.round((current_step / total_steps) * 100) : 0;

  return (
    <Paper variant="outlined" sx={{ mb: 2, border: '1px solid white' }}>
      {/* Collapsed Summary */}
      <Box
        sx={{
          p: 2,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer'
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
          <Chip
            icon={<DeviceIcon />}
            label={device_model}
            size="small"
            variant="outlined"
          />
          {strategy && (
            <Chip
              icon={<StrategyIcon />}
              label={strategy.replace('_', ' ')}
              size="small"
              color={has_dump_ui ? 'success' : 'default'}
              variant="outlined"
            />
          )}
          {predicted_items.length > 0 && (
            <Chip
              icon={<ItemsIcon />}
              label={`${predicted_items.length} items`}
              size="small"
              variant="outlined"
            />
          )}
          <Chip
            label={`${progressPercent}% complete`}
            size="small"
            color="primary"
          />
        </Box>

        <IconButton size="small">
          {expanded ? <CollapseIcon /> : <ExpandIcon />}
        </IconButton>
      </Box>

      {/* Expanded Details */}
      <Collapse in={expanded}>
        <Divider />
        <Box sx={{ p: 2 }}>
          <Grid container spacing={2}>
            {/* Original Prompt */}
            {original_prompt && (
              <Grid item xs={12}>
                <Typography variant="caption" color="text.secondary">
                  Original Goal:
                </Typography>
                <Typography variant="body2">{original_prompt}</Typography>
              </Grid>
            )}

            {/* Device */}
            <Grid item xs={12} sm={6}>
              <Typography variant="caption" color="text.secondary">
                Device Model:
              </Typography>
              <Typography variant="body2">{device_model}</Typography>
            </Grid>

            {/* Strategy */}
            <Grid item xs={12} sm={6}>
              <Typography variant="caption" color="text.secondary">
                Strategy:
              </Typography>
              <Typography variant="body2">
                {strategy || 'Not detected'}
                {has_dump_ui && (
                  <Chip
                    label="dump_ui available"
                    size="small"
                    color="success"
                    sx={{ ml: 1 }}
                  />
                )}
              </Typography>
            </Grid>

            {/* Progress */}
            <Grid item xs={12} sm={6}>
              <Typography variant="caption" color="text.secondary">
                Progress:
              </Typography>
              <Typography variant="body2">
                {current_step} / {total_steps} items ({progressPercent}%)
              </Typography>
            </Grid>

            {/* Predicted Items */}
            {predicted_items.length > 0 && (
              <Grid item xs={12}>
                <Typography variant="caption" color="text.secondary">
                  Items:
                </Typography>
                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
                  {predicted_items.map(item => (
                    <Chip key={item} label={item} size="small" />
                  ))}
                </Box>
              </Grid>
            )}
          </Grid>
        </Box>
      </Collapse>
    </Paper>
  );
};

