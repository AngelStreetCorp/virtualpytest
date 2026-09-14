/**
 * Navigation Node Selector
 *
 * Dropdown of node labels available in a userinterface's tree hierarchy.
 * Drives the --node CLI flag of the goto script on the RunTests modal.
 *
 * Mirrors EdgeKpiSelector — hierarchy walk lives server-side
 * (/server/navigationTrees/nodes), this component just renders.
 */

import React, { useEffect } from 'react';
import { Box, FormControl, InputLabel, Select, MenuItem, Typography, useTheme } from '@mui/material';

import { useNavigationNodes } from '../../hooks/script/useNavigationNodes';
import { AGENT_CHAT_PALETTE } from '../../constants/agentChatTheme';

interface NavigationNodeSelectorProps {
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
   * When true, the node is OPTIONAL: a "(none)" choice is offered and nothing is
   * auto-selected (default empty). Used by standby_measurement's standby-mode
   * precondition, which may be skipped. A node's display_name is still shown as
   * the primary label when set — but every node is listed regardless, so the
   * picker is never empty just because no display names have been configured.
   */
  allowNone?: boolean;
  /**
   * Optional substrings (case-insensitive); a node is listed only if its label
   * contains AT LEAST ONE of them. e.g. ['standby_eco','standby_fast',
   * 'standby_active'] restricts the picker to the standby mode nodes.
   */
  labelIncludesAny?: string[];
}

export const NavigationNodeSelector: React.FC<NavigationNodeSelectorProps> = ({
  userinterfaceName,
  variant,
  value = '',
  onChange,
  label = 'node',
  disabled = false,
  size = 'small',
  fullWidth = true,
  allowNone = false,
  labelIncludesAny,
}) => {
  const theme = useTheme();
  const isDarkMode = theme.palette.mode === 'dark';
  const PALETTE = AGENT_CHAT_PALETTE;

  const { nodes: allNodes, loading } = useNavigationNodes(userinterfaceName, variant);

  // Optional substring filter (e.g. the standby mode nodes). Keyed on a
  // serialized string so the memo + effects stay stable across renders even
  // though the caller passes an inline array literal.
  const filterKey = (labelIncludesAny || []).join('|').toLowerCase();
  const nodes = React.useMemo(() => {
    if (!filterKey) return allNodes;
    const needles = filterKey.split('|').filter(Boolean);
    return allNodes.filter((n) => {
      const l = n.label.toLowerCase();
      return needles.some((s) => l.includes(s));
    });
  }, [allNodes, filterKey]);

  // Reset if the selected label is no longer in the list (e.g. user switched
  // userinterface). Same defensive reset as EdgeKpiSelector.
  useEffect(() => {
    if (value && nodes.length > 0 && !nodes.some((n) => n.label === value)) {
      onChange('');
    }
  }, [nodes, value, onChange]);

  // Preselect a default when the field is empty: prefer 'home' (matches the
  // goto.py CLI default at test_scripts/goto.py:144) and fall back to the first
  // entry. Skipped when allowNone — an optional precondition must default to
  // empty, never force-select an unrelated node like 'home'.
  useEffect(() => {
    if (allowNone || value || loading || nodes.length === 0) return;
    const homeNode = nodes.find((n) => n.label.toLowerCase() === 'home');
    onChange((homeNode ?? nodes[0]).label);
  }, [allowNone, nodes, value, loading, onChange]);

  // Show the friendly display name for the selected value when one exists.
  const displayForValue = (v: string): string => {
    const match = nodes.find((n) => n.label === v);
    return (match?.display_name || v) as string;
  };

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
      : allowNone
        ? '(none)'
        : nodes.length === 0
          ? '(no nodes)'
          : '(select)';

  return (
    <FormControl
      size={size}
      fullWidth={fullWidth}
      // With allowNone the "(none)" choice is always valid, so don't disable
      // the field just because the filtered node list came back empty.
      disabled={disabled || !userinterfaceName || loading || (!allowNone && nodes.length === 0)}
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
            <em>(none — skip)</em>
          </MenuItem>
        )}
        {nodes.map((n) => (
          <MenuItem key={n.node_id} value={n.label}>
            {n.display_name ? (
              // Friendly name as the primary label, raw node label as subtext.
              <Box sx={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
                <span>{n.display_name}</span>
                <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem' }}>
                  {n.label}
                </Typography>
              </Box>
            ) : (
              n.label
            )}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
};
