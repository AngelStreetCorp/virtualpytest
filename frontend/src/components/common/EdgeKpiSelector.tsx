/**
 * KPI Edge Selector
 *
 * Dropdown of action_set labels (e.g. "live → live_fullscreen") that are
 * configured to produce KPI measurements for a given userinterface. Drives
 * the --edge CLI flag of the kpi_measurement script on the RunTests modal.
 *
 * Filtering / hierarchy walk lives server-side in
 * /server/navigationTrees/kpi-action-sets — this component just renders.
 */

import React, { useEffect } from 'react';
import { Box, FormControl, InputLabel, Select, MenuItem, Typography, useTheme } from '@mui/material';

import { useKpiActionSets } from '../../hooks/script/useKpiActionSets';
import { AGENT_CHAT_PALETTE } from '../../constants/agentChatTheme';

interface EdgeKpiSelectorProps {
  userinterfaceName?: string;
  /** Active variant name; empty / undefined / 'base' all resolve to base scope. */
  variant?: string | null;
  value?: string;
  onChange: (label: string) => void;
  label?: string;
  disabled?: boolean;
  size?: 'small' | 'medium';
  fullWidth?: boolean;
  /**
   * Optional target-node label (case-insensitive, exact). When set, only
   * action_sets whose DESTINATION node label equals it are offered — e.g.
   * "standby" restricts the dropdown to edges INTO the standby node for
   * standby_measurement, regardless of the source node the tree wires it from
   * (live → standby, home → standby, …). Matching to_label (not a whole-label
   * substring) also avoids catching "→ standby_active/eco/fast", which belong
   * to the separate standby_mode_node picker.
   */
  toLabelEquals?: string;
  /**
   * When true, offer a leading "(none)" option (value '') and DON'T auto-select
   * a default when empty — so the field can legitimately be left blank. Used by
   * kpi_measurement's optional --closing_edge, where empty means "no closure".
   * Mirrors NavigationNodeSelector's allowNone.
   */
  allowNone?: boolean;
}

export const EdgeKpiSelector: React.FC<EdgeKpiSelectorProps> = ({
  userinterfaceName,
  variant,
  value = '',
  onChange,
  label = 'edge',
  disabled = false,
  size = 'small',
  fullWidth = true,
  toLabelEquals,
  allowNone = false,
}) => {
  const theme = useTheme();
  const isDarkMode = theme.palette.mode === 'dark';
  const PALETTE = AGENT_CHAT_PALETTE;

  const { actionSets: allActionSets, loading } = useKpiActionSets(userinterfaceName, variant);

  // Apply the optional target-node filter (exact to_label match). Keyed on the
  // normalized string so the memo (and the effects below) stay stable.
  const toLabelNeedle = (toLabelEquals || '').trim().toLowerCase();
  const actionSets = React.useMemo(() => {
    if (!toLabelNeedle) return allActionSets;
    return allActionSets.filter((a) => (a.to_label || '').trim().toLowerCase() === toLabelNeedle);
  }, [allActionSets, toLabelNeedle]);

  // Reset if the selected label is no longer in the list (e.g. user switched
  // userinterface, or it's now filtered out). Same defensive reset as VariantSelector.
  useEffect(() => {
    if (value && actionSets.length > 0 && !actionSets.some((a) => a.label === value)) {
      onChange('');
    }
  }, [actionSets, value, onChange]);

  // Preselect a default when the field is empty: prefer the ENTRY → home
  // action_set (present in every tree) and fall back to the first entry. With a
  // filter active, ENTRY → home is filtered out and the first match wins.
  // Skipped entirely when allowNone: an empty closing edge is a valid choice.
  useEffect(() => {
    if (allowNone || value || loading || actionSets.length === 0) return;
    const entryToHome = actionSets.find(
      (a) =>
        a.from_label.toLowerCase() === 'entry' &&
        a.to_label.toLowerCase() === 'home',
    );
    onChange((entryToHome ?? actionSets[0]).label);
  }, [allowNone, actionSets, value, loading, onChange]);

  const styles = {
    height: size === 'small' ? 32 : 40,
    fontSize: size === 'small' ? '0.85rem' : '0.875rem',
    bgcolor: isDarkMode ? PALETTE.inputBg : '#fff',
    borderRadius: 1.5,
    '& .MuiOutlinedInput-notchedOutline': {
      borderColor: isDarkMode ? PALETTE.borderColor : 'grey.300',
    },
  };

  const placeholder = !userinterfaceName
    ? '(pick userinterface)'
    : loading
      ? 'loading…'
      : actionSets.length === 0
        ? '(no KPI edges)'
        : allowNone
          ? '(none)'
          : '(select)';

  // The selected value is the action_set label (the --edge contract). When that
  // action_set carries a friendly kpi_name, show the name in the closed field
  // instead of the raw label; otherwise show the label as before.
  const displayForValue = (v: string): string => {
    const match = actionSets.find((a) => a.label === v);
    return (match?.kpi_name || v) as string;
  };

  return (
    <FormControl
      size={size}
      fullWidth={fullWidth}
      disabled={disabled || !userinterfaceName || loading || actionSets.length === 0}
    >
      <InputLabel shrink sx={{ fontSize: '0.75rem' }}>
        {label}
      </InputLabel>
      <Select
        value={value || ''}
        label={label}
        notched
        onChange={(e) => onChange((e.target.value as string) || '')}
        sx={styles}
        renderValue={(v) => (v ? displayForValue(v as string) : placeholder)}
        displayEmpty
      >
        {allowNone && (
          <MenuItem value="">
            <em>(none)</em>
          </MenuItem>
        )}
        {actionSets.map((a) => (
          // Key on label, not action_set_id: conditional siblings share the
          // owner's action_set_id (distinct labels), so id alone collides.
          <MenuItem key={a.label} value={a.label}>
            {a.kpi_name ? (
              // Friendly name as the primary label, raw edge name as subtext.
              <Box sx={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
                <span>{a.kpi_name}</span>
                <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem' }}>
                  {a.label}
                </Typography>
              </Box>
            ) : (
              a.label
            )}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
};
