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
import { Box, FormControl, InputLabel, Select, MenuItem, Tooltip, Typography } from '@mui/material';

import { KpiActionSet, useKpiActionSets } from '../../hooks/script/useKpiActionSets';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';

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
  /**
   * When true, judge each edge by its REVERSE direction instead of its own:
   * every edge is listed, and those whose reverse has no actions or can't be
   * measured are shown in red and can't be selected (tooltip says what to fix). Used by
   * standby_measurement, which picks the into-standby edge but times the
   * reverse wake (standby → live/home).
   */
  requireReverseKpi?: boolean;
}

/** Why the reverse direction of `a` can't be run and measured, or null. */
const reverseKpiBlocker = (a: KpiActionSet): string | null => {
  if (!a.reverse_label) {
    return `"${a.label}" has no reverse direction, so the wake can't be timed.`;
  }
  if (!a.reverse_has_actions) {
    return (
      `The wake "${a.reverse_label}" has no actions, so it can't be run. In the ` +
      `edge editor, add its actions (e.g. POWER) for this variant.`
    );
  }
  if (a.reverse_kpi) return null;
  return (
    `The wake "${a.reverse_label}" has no KPI measurement. In the edge editor, ` +
    `add KPI references to "${a.reverse_label}", or enable "Use target node ` +
    `verifications" with a verification (or fingerprint) on "${a.from_label}".`
  );
};

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
  requireReverseKpi = false,
}) => {
  const livePalette = useAgentChatPalette();

  const { actionSets: allActionSets, loading } = useKpiActionSets(
    userinterfaceName,
    variant,
    !requireReverseKpi,
  );

  // Apply the optional target-node filter (exact to_label match). Keyed on the
  // normalized string so the memo (and the effects below) stay stable.
  const toLabelNeedle = (toLabelEquals || '').trim().toLowerCase();
  const actionSets = React.useMemo(() => {
    if (!toLabelNeedle) return allActionSets;
    return allActionSets.filter((a) => (a.to_label || '').trim().toLowerCase() === toLabelNeedle);
  }, [allActionSets, toLabelNeedle]);

  const blockerFor = React.useCallback(
    (a: KpiActionSet) => (requireReverseKpi ? reverseKpiBlocker(a) : null),
    [requireReverseKpi],
  );
  const selectable = React.useMemo(
    () => actionSets.filter((a) => !blockerFor(a)),
    [actionSets, blockerFor],
  );

  // Reset if the selected label is no longer in the list (e.g. user switched
  // userinterface, or it's now filtered out). Same defensive reset as VariantSelector.
  useEffect(() => {
    if (value && actionSets.length > 0 && !selectable.some((a) => a.label === value)) {
      onChange('');
    }
  }, [actionSets, selectable, value, onChange]);

  // Preselect a default when the field is empty: prefer the ENTRY → home
  // action_set (present in every tree) and fall back to the first entry. With a
  // filter active, ENTRY → home is filtered out and the first match wins.
  // Blocked (red) edges are never preselected.
  // Skipped entirely when allowNone: an empty closing edge is a valid choice.
  useEffect(() => {
    if (allowNone || value || loading || selectable.length === 0) return;
    const entryToHome = selectable.find(
      (a) =>
        a.from_label.toLowerCase() === 'entry' &&
        a.to_label.toLowerCase() === 'home',
    );
    onChange((entryToHome ?? selectable[0]).label);
  }, [allowNone, selectable, value, loading, onChange]);

  const styles = {
    height: size === 'small' ? 32 : 40,
    fontSize: size === 'small' ? '0.85rem' : '0.875rem',
    bgcolor: livePalette.inputBg,
    borderRadius: 1.5,
    '& .MuiOutlinedInput-notchedOutline': {
      borderColor: livePalette.borderColor,
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
      <InputLabel shrink sx={{ fontSize: TYPOGRAPHY.caption.size }}>
        {label}
      </InputLabel>
      <Select
        value={value || ''}
        label={label}
        notched
        onChange={(e) => {
          const next = (e.target.value as string) || '';
          // Blocked rows stay clickable so their tooltip shows; ignore the pick.
          const picked = actionSets.find((a) => a.label === next);
          if (picked && blockerFor(picked)) return;
          onChange(next);
        }}
        sx={styles}
        renderValue={(v) => (v ? displayForValue(v as string) : placeholder)}
        displayEmpty
      >
        {allowNone && (
          <MenuItem value="">
            <em>(none)</em>
          </MenuItem>
        )}
        {actionSets.map((a) => {
          const blocker = blockerFor(a);
          // Key on label, not action_set_id: conditional siblings share the
          // owner's action_set_id (distinct labels), so id alone collides.
          // Not `disabled`: MUI drops pointer events on disabled items, which
          // would also kill the tooltip. onChange ignores blocked picks instead.
          const item = (
          <MenuItem
            key={a.label}
            value={a.label}
            aria-disabled={blocker ? true : undefined}
            sx={blocker ? { color: 'error.main', cursor: 'not-allowed' } : undefined}
          >
            {a.kpi_name ? (
              // Friendly name as the primary label, raw edge name as subtext.
              <Box sx={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
                <span>{a.kpi_name}</span>
                <Typography variant="caption" color="text.secondary" sx={{ fontSize: TYPOGRAPHY.caption.size }}>
                  {a.label}
                </Typography>
              </Box>
            ) : (
              a.label
            )}
          </MenuItem>
          );
          return blocker ? (
            <Tooltip key={a.label} title={blocker} placement="left" arrow>
              {item}
            </Tooltip>
          ) : (
            item
          );
        })}
      </Select>
    </FormControl>
  );
};
