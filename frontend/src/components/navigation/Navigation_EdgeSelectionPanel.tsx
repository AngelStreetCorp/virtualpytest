import { Close as CloseIcon } from '@mui/icons-material';
import { Box, Typography, Button, IconButton, Paper, LinearProgress, Alert } from '@mui/material';
import React, { useEffect, useMemo } from 'react';
import { useReactFlow, useNodes } from 'reactflow';

import { useEdge } from '../../hooks/navigation/useEdge';
import { useNavigation } from '../../contexts/navigation/NavigationContext';
import { useValidationColors } from '../../hooks/validation/useValidationColors';
import { Host } from '../../types/common/Host_Types';
import { UINavigationEdge, EdgeForm } from '../../types/pages/Navigation_Types';
import { EdgeMetricData } from '../../types/navigation/Metrics_Types';
import { getZIndex } from '../../utils/zIndexUtils';
import { computeConditionalEdgeIds, findSiblingWithActions, getConditionalRole } from '../../utils/conditionalEdgeUtils';

// Per-action execution meta the executor honours: `iterator` (repeat count,
// default 1) and the post-action settle `wait_time` (ms), which the host
// resolves from params.wait_time or the action top-level. Returned split so
// each renders in its own fixed column ("x2" | "wait:2000"). Mirrors the
// helper in Navigation_NodeGotoPanel.tsx so the Edge Selection action rows
// align identically to the Go To preview.
function getActionMeta(action: any): { iter: string; wait: string } {
  const rawWait = action?.params?.wait_time ?? action?.wait_time ?? 0;
  const waitMs = Number(rawWait) > 0 ? Number(rawWait) : 0;
  const wait = waitMs > 0 ? `wait:${waitMs}` : '';
  // "Repeat until" actions repeat conditionally, so there's no meaningful
  // fixed count — show "repeat". The condition can be node-based
  // (target_node_id) or verification-based (verifications[]); gating only on
  // verifications.length missed node-based repeats and fell back to the stale
  // `iterator`, showing "x5" while the Edit dialog showed "Until appears".
  const ru = action?.repeat_until;
  if (ru && (ru.condition || ru.target_node_id || ru.verifications?.length)) {
    return { iter: 'repeat', wait };
  }
  const iterator = Number(action?.iterator) > 0 ? Number(action.iterator) : 1;
  return { iter: `x${iterator}`, wait };
}

// Shorter display names for the commands whose full name eats the width the
// meta columns need. The panel is 360px wide, so "press key" pushed
// `wait:1000` past the right border on press_key rows — by far the most
// common action.
const COMMAND_LABELS: Record<string, string> = {
  press_key: 'key',
};

// Compact `command param` rendering used for the action's command column.
// wait_time and iterator are NOT folded in here — they render in their own
// columns below so rows line up like a table (same shape as the Go To panel).
function formatActionDisplay(action: any): string {
  if (!action.command) return 'No action selected';
  const commandDisplay = COMMAND_LABELS[action.command] ?? action.command.replace(/_/g, ' ').trim();
  const params = action.params || {};
  const paramParts: string[] = [];
  switch (action.command) {
    case 'press_key':
      if (params.key) paramParts.push(`${params.key}`);
      break;
    case 'input_text':
      if (params.text) paramParts.push(`"${params.text}"`);
      break;
    case 'click_element':
      // Backend uses single parameter: selector (web) or element_id (remote)
      if (params.selector) paramParts.push(`${params.selector}`);
      if (params.element_id) paramParts.push(`${params.element_id}`);
      break;
    case 'click_element_by_id':
      if (params.element_id) paramParts.push(`${params.element_id}`);
      break;
    case 'tap_coordinates':
      if (params.x !== undefined && params.y !== undefined) {
        paramParts.push(`(${params.x}, ${params.y})`);
      }
      break;
    case 'swipe':
      if (params.direction) paramParts.push(`${params.direction}`);
      break;
    case 'launch_app':
    case 'close_app':
      if (params.package) paramParts.push(`${params.package}`);
      break;
    case 'wait':
      if (params.duration) paramParts.push(`${params.duration}s`);
      break;
    case 'scroll':
      if (params.direction) paramParts.push(`${params.direction}`);
      if (params.amount) paramParts.push(`${params.amount}x`);
      break;
  }
  const paramDisplay = paramParts.length > 0 ? ` ${paramParts.join(', ')}` : '';
  return `${commandDisplay}${paramDisplay}`;
}

// One action row: numbered prefix in a fixed command column, then iterator
// and wait_time in their own fixed columns. Same column widths as the
// Go To preview's ActionSubList so the two panels visually line up.
const ActionRow: React.FC<{
  prefix: string;
  action: any;
  color?: string;
}> = ({ prefix, action, color }) => {
  const meta = getActionMeta(action);
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'baseline',
        fontFamily: 'monospace',
        fontSize: '0.75rem',
        color: color || 'text.primary',
        mb: 0.3,
        // Row itself never exceeds the panel: the command column ellipsizes
        // and the wait column clamps rather than pushing content out.
        minWidth: 0,
        overflow: 'hidden',
      }}
    >
      <Box
        component="span"
        sx={{
          flex: '0 0 20ch',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        {prefix} {formatActionDisplay(action)}
      </Box>
      <Box
        component="span"
        sx={{ flex: '0 0 6ch', color: 'text.disabled', fontSize: '0.72rem' }}
      >
        {meta.iter}
      </Box>
      <Box
        component="span"
        sx={{
          flex: '1 1 auto',
          minWidth: 0,
          color: 'text.disabled',
          fontSize: '0.72rem',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        {meta.wait}
      </Box>
    </Box>
  );
};

interface EdgeSelectionPanelProps {
  selectedEdge: UINavigationEdge;
  onClose: () => void;
  onEdit: () => void;
  onDelete: () => void;
  setEdgeForm: React.Dispatch<React.SetStateAction<EdgeForm>>;
  setIsEdgeDialogOpen: (open: boolean) => void;

  // Device control props
  isControlActive?: boolean;
  selectedHost?: Host; // Make optional to fix regression
  selectedDeviceId?: string; // Add selectedDeviceId prop

  // Positioning for multiple panels
  panelIndex?: number;

  // Add props for passing labels to the edit dialog
  onEditWithLabels?: (fromLabel: string, toLabel: string) => void;
  
  // Current edge form state (for running updated actions)
  currentEdgeForm?: EdgeForm | null;

  // NEW: Specific action set to display (if provided, use this instead of extracting from edge)
  actionSet?: any;
  // Metrics props - passed from NavigationEditor
  edgeMetrics?: EdgeMetricData | null;
  // Tree ID for navigation context
  treeId?: string | null;
}

export const EdgeSelectionPanel: React.FC<EdgeSelectionPanelProps> = React.memo(
  ({
    selectedEdge,
    onClose,
    onEdit: _onEdit,
    onDelete,
    setEdgeForm,
    setIsEdgeDialogOpen,

    isControlActive = false,
    selectedHost,
    selectedDeviceId,
    panelIndex = 0,
    onEditWithLabels,
    actionSet, // NEW: specific action set to display
    edgeMetrics,
    treeId,
  }) => {
    const { getEdges } = useReactFlow();
    // Subscribe to the live nodes (useNodes is reactive; getNodes() is a
    // non-reactive snapshot) so the direction labels below re-derive the moment
    // a node is renamed — no need to reselect the edge.
    const rfNodes = useNodes();

    // Per-action-set direction labels. Resolve them LIVE from the edge's
    // source/target node ids so a node rename shows up immediately. We do NOT
    // trust action_set.label as the primary source: it is a denormalized
    // "from → to" string snapshotted when the edge was drawn, and although the
    // node-save path now keeps it in sync, a live lookup is authoritative and
    // never goes stale. It stays only as the fallback when a node id can't be
    // resolved (e.g. the node isn't present in the current graph/viewport).
    //
    // Orientation follows the canonical rule shared with useEdge.executeActionSet:
    // action_sets[0] is the forward set (source → target); any other set is the
    // backward one (target → source), so its labels are swapped.
    //
    // We deliberately do NOT parse action_set.id by splitting on "_to_": most
    // ids encode labels ("home_to_settings") but the unlink-conditional path
    // (NavigationContext saveEdge) mints node-id + timestamp ids like
    // "node-1755855570316_to_node-1761512641087_1779363058361", which that
    // split turned into the raw, timestamp-suffixed node id shown in the panel.
    // Each action-set card reads its OWN travel direction: the forward set
    // (action_sets[0]) is source → target, and the reverse set (action_sets[1])
    // is target → source. So a bidirectional edge's two cards show opposite
    // directions (e.g. apps_netflix → netflix_home and netflix_home →
    // apps_netflix) and never look identical — each card's own source is on the
    // left, its own target on the right.
    const { fromLabel, toLabel } = useMemo(() => {
      const sourceNode = rfNodes.find((node) => node.id === selectedEdge.source);
      const targetNode = rfNodes.find((node) => node.id === selectedEdge.target);

      const sourceLabel = (sourceNode?.data as any)?.label as string | undefined;
      const targetLabel = (targetNode?.data as any)?.label as string | undefined;

      if (sourceLabel && targetLabel) {
        const actionSets = (selectedEdge.data?.action_sets as any[]) || [];
        // No actionSet (fallback panel) or the forward set → source → target;
        // the reverse set (index 1) → target → source.
        const isForward = !actionSet?.id || actionSet.id === actionSets[0]?.id;
        return isForward
          ? { fromLabel: sourceLabel, toLabel: targetLabel }
          : { fromLabel: targetLabel, toLabel: sourceLabel };
      }

      // Fallback: the denormalized "from → to" copy stored on the action set
      // (already direction-correct, but can be stale after a rename).
      const actionSetLabel: string | undefined = actionSet?.label;
      if (actionSetLabel && actionSetLabel.includes('→')) {
        const [from, to] = actionSetLabel.split('→');
        return { fromLabel: from.trim(), toLabel: to.trim() };
      }

      // Last resort: raw node ids.
      return {
        fromLabel: sourceLabel || selectedEdge.source,
        toLabel: targetLabel || selectedEdge.target,
      };
    }, [rfNodes, selectedEdge.source, selectedEdge.target, selectedEdge.data, actionSet]);

    // Is the selected edge a variant edge (carries a per-variant override, or is
    // variant-only) in the current viewing scope? useResolvedTree stamps
    // `_show_variant_chip` on exactly those edges when the canvas is on a
    // variant; base view never sets it. Drives the panel's blue border + "v"
    // badge so a variant edge's panel is visually distinct from a base one.
    const isVariantEdge = (selectedEdge.data as any)?._show_variant_chip === true;

    // Is the currently-shown action set the conditional FORWARD set?
    // Conditional applies only to the forward direction (action_sets[0]); the
    // reverse (action_sets[1]) is always independent. Detection itself is the
    // shared structural rule (see utils/navigation/conditionalEdge), so this
    // always agrees with the canvas colour and the Edit dialog badge.
    const isCurrentActionSetShared = useMemo(() => {
      if (!actionSet?.id) return false;

      // Reverse action set (index 1) is never conditional.
      const edgeActionSets = selectedEdge.data?.action_sets || [];
      if (edgeActionSets.length >= 2 && edgeActionSets[1]?.id === actionSet.id) {
        return false;
      }

      // Forward action set → conditional iff the edge is in a conditional group.
      return computeConditionalEdgeIds(getEdges() as any).has(selectedEdge.id);
    }, [actionSet?.id, selectedEdge.id, selectedEdge.data?.action_sets, getEdges]);
    
    // Conditional ROLE derived from action-ownership (not a stored flag): the
    // 'main' owns the actions and is fully editable (edits propagate to every
    // branch); a 'sibling' borrows them and editing it unlinks it. Only meaningful
    // for the forward action set (handled inside getConditionalRole via the
    // structural detection). null when the edge isn't conditional.
    const conditionalRole = useMemo(
      () => (isCurrentActionSetShared ? getConditionalRole(selectedEdge.id, getEdges() as any) : null),
      [isCurrentActionSetShared, selectedEdge.id, getEdges],
    );

    // Use edge hook only for action execution - initialize lazily
    const edgeHook = useEdge({
      selectedHost: selectedHost || null,
      selectedDeviceId: selectedDeviceId || null,
      isControlActive,
      treeId: treeId || null,
    });

    // True while a save/delete DB mutation is in flight — disables Edit/Delete so
    // a second click can't fire a concurrent (and corrupting) request.
    const { isLoading: isMutating } = useNavigation();
    
    // Get validation colors for confidence-based styling
    const { getEdgeColors } = useValidationColors([]);

    // Get actions from actionSet, or from sibling if conditional edge with empty actions
    const { actions, retryActions, failureActions } = useMemo(() => {
      const baseActions = actionSet?.actions || [];
      const baseRetry = actionSet?.retry_actions || [];
      const baseFailure = actionSet?.failure_actions || [];
      
      // If we have actions, use them
      if (baseActions.length > 0) {
        return { actions: baseActions, retryActions: baseRetry, failureActions: baseFailure };
      }
      
      // Empty actions + conditional = look up sibling
      if (isCurrentActionSetShared && actionSet?.id) {
        const sibling = findSiblingWithActions(selectedEdge.id, selectedEdge.source, actionSet.id, getEdges());
        if (sibling?.data?.action_sets?.[0]) {
          const siblingForward = sibling.data.action_sets[0];
          return {
            actions: siblingForward.actions || [],
            retryActions: siblingForward.retry_actions || [],
            failureActions: siblingForward.failure_actions || []
          };
        }
      }
      
      return { actions: baseActions, retryActions: baseRetry, failureActions: baseFailure };
    }, [actionSet, isCurrentActionSetShared, selectedEdge.id, selectedEdge.source, getEdges]);
    
    const hasActions = actions.length > 0;
    const hasRetryActions = retryActions.length > 0;
    const hasFailureActions = failureActions.length > 0;
    
    // Simple canRunActions check using props only
    const canRunActions = isControlActive === true && 
                         selectedHost !== null && 
                         hasActions && 
                         !edgeHook.actionHook.loading;

    // Memoize the clearResults function to avoid recreating it on every render
    const clearResults = useMemo(() => edgeHook.clearResults, [edgeHook.clearResults]);

    // Clear run results when edge selection changes
    useEffect(() => {
      clearResults();
    }, [selectedEdge.id, clearResults]);

    // Check if edge can be deleted using hook function
    const isProtectedEdge = edgeHook.isProtectedEdge(selectedEdge);

    // Get confidence-based colors for the edge
    const edgeColors = useMemo(() => {
      return getEdgeColors(selectedEdge.id, edgeMetrics);
    }, [getEdgeColors, selectedEdge.id, edgeMetrics]);

    // Edge has an optional KPI threshold (ms). When > 0, the KPI chip shades
    // green if the average is at/below threshold, red if over. Threshold = 0
    // disables that signal — chip stays neutral. Lives per-direction on the
    // active action_set, edited in the Edit Edge dialog.
    const kpiThresholdMs = (actionSet as any)?.threshold ?? 0;

    // Format metrics display.
    // Layout intent (matches Node panel):
    //   Left row of small chips: success rate · action time · volume · score
    //   Right edge of header: KPI chip (always shown, even if no data — disabled
    //   grey for "0s") so node and edge headers line up consistently.
    const metricsDisplay = useMemo(() => {
      const noData = !edgeMetrics;
      const successRatePercent = noData ? 0 : Math.round(edgeMetrics.success_rate * 100);
      const confidenceScore = noData ? 0 : Math.round(edgeMetrics.confidence * 10);
      const volume = noData ? 0 : edgeMetrics.volume;

      // Action chip: actions + final_wait, never verification. .toFixed(2).
      const timeText = !noData && edgeMetrics.avg_action_time > 0
        ? `${(edgeMetrics.avg_action_time / 1000).toFixed(2)}s`
        : '0s';

      // KPI: pixel-perfect on-screen time. Always render the chip for layout
      // consistency with the Node panel. Disabled grey when no sample yet.
      const kpiVolume = edgeMetrics?.kpi_volume ?? 0;
      const kpiMs = edgeMetrics?.avg_kpi_ms ?? 0;
      const kpiHasData = kpiVolume > 0 && kpiMs > 0;
      const kpiText = kpiHasData ? `${(kpiMs / 1000).toFixed(2)}s` : '0s';

      // Threshold-based KPI color:
      //   threshold > 0 + has data + KPI ≤ threshold → green (under budget)
      //   threshold > 0 + has data + KPI > threshold → red (over budget)
      //   threshold = 0 OR no data                   → neutral grey/white
      let kpiBorderColor = '#666';
      let kpiTextColor = '#666';
      if (kpiHasData) {
        if (kpiThresholdMs > 0) {
          if (kpiMs <= kpiThresholdMs) {
            kpiBorderColor = '#22c55e';
            kpiTextColor = '#22c55e';
          } else {
            kpiBorderColor = '#ef4444';
            kpiTextColor = '#ef4444';
          }
        } else {
          // Has data but no threshold defined — neutral white-ish.
          kpiBorderColor = '#bbb';
          kpiTextColor = '#bbb';
        }
      }

      return {
        successRateText: noData ? 'No data' : `${successRatePercent}%`,
        successRateColor: noData || volume === 0
          ? '#666'
          : (successRatePercent >= 90 ? '#22c55e' : successRatePercent >= 70 ? '#f59e0b' : '#ef4444'),
        confidenceScore,
        confidenceColor: noData ? '#666' : edgeColors.stroke,
        volumeText: `${volume}`,
        timeText,
        kpiText,
        kpiBorderColor,
        kpiTextColor,
        kpiHasData,
      };
    }, [edgeMetrics, edgeColors, kpiThresholdMs]);

    const handleEdit = () => {
      // Simple edge form creation
      const edgeForm = edgeHook.createEdgeForm(selectedEdge);
      
      // Direction detection based on edge type:
      // - Unidirectional edges (entry/action): always forward (only 1 action set)
      // - Bidirectional edges (screen/menu): detect from action set ID (index 0 = forward, index 1 = reverse)
      if (edgeForm.action_sets?.length === 1) {
        // Unidirectional edge - always forward
        edgeForm.direction = 'forward';
      } else if (actionSet?.id && edgeForm.action_sets?.length >= 2) {
        // Bidirectional edge - detect from action set ID
        edgeForm.direction = actionSet.id === edgeForm.action_sets[0].id ? 'forward' : 'reverse';
      }
      
      setEdgeForm(edgeForm);
      setIsEdgeDialogOpen(true);
      // Do NOT call onClose() here. The parent's `onClose` resolves to
      // `resetSelection` (sets selectedEdge = null), and React batches it
      // with the setIsEdgeDialogOpen(true) above. When the dialog mounts,
      // its init useEffect reads `_selectedEdge?.data?.action_sets || []`
      // and gets `[]` because selectedEdge has been nulled in the same
      // commit. That cascades: edgeForm.action_sets gets clobbered to [],
      // handleActionsChange can't spread an empty array (so user edits
      // never reach edgeForm), and Save submits an empty override
      // (variant entry ends up with no action_sets → reverts to base).
      // Leave the selection panel rendered behind the dialog overlay.

      if (onEditWithLabels) {
        onEditWithLabels(fromLabel, toLabel);
      }
    };

    // Execute actions using actionSet data
    const handleRunActions = async () => {
      await edgeHook.executeEdgeActions(
        selectedEdge,
        actions,
        retryActions,
        failureActions,
        actionSet?.id
      );
    };

    return (
      <Paper
        sx={{
          position: 'absolute',
          top: 16,
          right: 16 + panelIndex * 380, // Stack panels to the left (higher index = further left)
          width: 360,
          p: 1.5,
          zIndex: getZIndex('NAVIGATION_EDGE_PANEL'),
          // Variant edge → blue outline so the panel is unmistakably a variant's
          // (matches the canvas "v" badge colour). Base → thin white outline.
          border: isVariantEdge ? '2px solid #1976d2' : '1px solid white',
          borderLeft: `4px solid ${edgeColors.stroke}`, // Show confidence color as left border
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <Box>
          <Box
            sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}
          >
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: 1 }}>
              {/* Variant "v" badge — only on a variant edge, matching the
                  canvas mid-edge chip so the panel's scope is obvious. */}
              {isVariantEdge && (
                <Typography
                  variant="caption"
                  sx={{
                    fontSize: '0.75rem',
                    fontWeight: 'bold',
                    color: '#fff',
                    backgroundColor: '#1976d2',
                    padding: '2px 7px',
                    borderRadius: '4px',
                    lineHeight: 1.2,
                  }}
                >
                  v
                </Typography>
              )}
              {/* Success Rate */}
              <Typography
                variant="caption"
                sx={{
                  fontSize: '0.75rem',
                  fontWeight: 'bold',
                  color: metricsDisplay.successRateColor,
                  padding: '2px 6px',
                  borderRadius: '4px',
                  backgroundColor: 'rgba(255,255,255,0.1)',
                }}
              >
                {metricsDisplay.successRateText}
              </Typography>

              {/* Action time */}
              <Typography
                variant="caption"
                sx={{
                  fontSize: '0.75rem',
                  fontWeight: 'bold',
                  color: '#666',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  backgroundColor: 'rgba(255,255,255,0.1)',
                }}
                title="Average edge action time: actions + final_wait, never verification"
              >
               {metricsDisplay.timeText}
              </Typography>

              {/* Volume */}
              <Typography
                variant="caption"
                sx={{
                  fontSize: '0.75rem',
                  fontWeight: 'bold',
                  color: '#666',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  backgroundColor: 'rgba(255,255,255,0.1)',
                }}
              >
                #{metricsDisplay.volumeText}
              </Typography>

              {/* Confidence score — same size as the rest, aligned left so
                  the right edge has only the KPI chip. */}
              <Typography
                variant="caption"
                sx={{
                  fontSize: '0.75rem',
                  fontWeight: 'bold',
                  color: metricsDisplay.confidenceColor,
                  padding: '2px 6px',
                  borderRadius: '4px',
                  backgroundColor: 'rgba(255,255,255,0.1)',
                  border: `1px solid ${metricsDisplay.confidenceColor}`,
                  minWidth: '28px',
                  textAlign: 'center',
                }}
                title="Confidence score (0–10)"
              >
                {metricsDisplay.confidenceScore}
              </Typography>
            </Box>

            {/* KPI chip — always rendered for layout consistency with the
                Node panel. Threshold-driven color: green ≤ threshold, red
                over, neutral grey otherwise. Disabled grey when no sample.
                When the most recent measurement has a report URL (carried
                in edgeMetrics.kpi_report_url from the RPC), the chip is
                rendered as an <a> linking to it. */}
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Typography
                component={edgeMetrics?.kpi_report_url ? 'a' : 'span'}
                href={edgeMetrics?.kpi_report_url || undefined}
                target={edgeMetrics?.kpi_report_url ? '_blank' : undefined}
                rel={edgeMetrics?.kpi_report_url ? 'noopener noreferrer' : undefined}
                variant="caption"
                sx={{
                  fontSize: '0.75rem',
                  fontWeight: 'bold',
                  color: metricsDisplay.kpiTextColor,
                  padding: '2px 6px',
                  borderRadius: '4px',
                  backgroundColor: 'rgba(255,255,255,0.1)',
                  border: `1px solid ${metricsDisplay.kpiBorderColor}`,
                  textAlign: 'center',
                  opacity: metricsDisplay.kpiHasData ? 1 : 0.5,
                  whiteSpace: 'nowrap',
                  cursor: edgeMetrics?.kpi_report_url ? 'pointer' : 'default',
                  textDecoration: 'none',
                  '&:hover': edgeMetrics?.kpi_report_url ? {
                    backgroundColor: 'rgba(255,255,255,0.18)',
                  } : undefined,
                }}
                title={
                  metricsDisplay.kpiHasData
                    ? `KPI: avg pixel-perfect time. Threshold ${kpiThresholdMs > 0 ? `${kpiThresholdMs}ms` : '(not set)'}.${edgeMetrics?.kpi_report_url ? ' Click to open the latest report.' : ''}`
                    : 'KPI: no sample yet. Edit Edge dialog → Threshold (ms)'
                }
              >
                KPI:&nbsp;{metricsDisplay.kpiText}
              </Typography>
            </Box>
            <IconButton
              size="small"
              onClick={(e) => {
                e.stopPropagation(); // Prevent event from bubbling to ReactFlow pane
                onClose();
              }}
              sx={{ p: 0.25 }}
            >
              <CloseIcon fontSize="small" />
            </IconButton>
          </Box>

          {/* Show From/To information with actual node labels */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography
              variant="body2"
              title={fromLabel}
              sx={{
                fontSize: '0.8rem',
                fontWeight: 'bold',
                color: '#1976d2',
                minWidth: 0,
                flex: '1 1 0',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {fromLabel}
            </Typography>
            <Typography variant="body1" sx={{ fontSize: '1rem', flexShrink: 0 }}>
              →
            </Typography>
            <Typography
              variant="body2"
              title={toLabel}
              sx={{
                fontSize: '0.8rem',
                fontWeight: 'bold',
                color: '#4caf50',
                minWidth: 0,
                flex: '1 1 0',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {toLabel}
            </Typography>
          </Box>
          <Typography
            variant="caption"
            sx={{ display: 'block', fontSize: '0.7rem', color: 'text.secondary', lineHeight: 1.2, mb: 0.75 }}
          >
            Final wait: {(actionSet as any)?.final_wait_time ?? 0}ms
          </Typography>

          {/* Conditional role banner. MAIN: edits propagate to all branches (no
              unlink). SIBLING: editing unlinks it into an independent edge. */}
          {conditionalRole === 'main' && (
            <Alert severity="success" icon={false} sx={{ mb: 1, py: 0.5, fontSize: '0.75rem' }}>
              <Typography variant="caption" sx={{ fontSize: '0.7rem', fontWeight: 'bold' }}>
                🔷 Conditional Edge · main — edits to these actions apply to all branches.
              </Typography>
            </Alert>
          )}
          {conditionalRole === 'sibling' && (
            <Alert severity="warning" icon={false} sx={{ mb: 1, py: 0.5, fontSize: '0.75rem' }}>
              <Typography variant="caption" sx={{ fontSize: '0.7rem', fontWeight: 'bold' }}>
                🔷 Conditional Edge · sibling — borrows the main's actions. Editing will unlink this edge and make it independent.
              </Typography>
            </Alert>
          )}

          {/* Show main actions list */}
          {(actions?.length || 0) > 0 && (
            <Box sx={{ mb: 1 }}>
              <Typography
                variant="caption"
                sx={{ fontWeight: 'bold', fontSize: '0.7rem', mb: 0.5, display: 'block' }}
              >
                Main Actions:
              </Typography>
              {actions?.map((action: any, index: number) => (
                <ActionRow key={index} prefix={`${index + 1}.`} action={action} />
              ))}
            </Box>
          )}

          {/* Show retry actions list */}
          {hasRetryActions && (
            <Box sx={{ mb: 1 }}>
              <Typography
                variant="caption"
                sx={{
                  fontWeight: 'bold',
                  fontSize: '0.7rem',
                  mb: 0.5,
                  display: 'block',
                  color: 'warning.main',
                }}
              >
                Retry Actions (if main actions fail):
              </Typography>
              {retryActions?.map((action: any, index: number) => (
                <ActionRow
                  key={`retry-${index}`}
                  prefix={`R${index + 1}.`}
                  action={action}
                  color="warning.main"
                />
              ))}
            </Box>
          )}

          {/* Show failure actions list */}
          {hasFailureActions && (
            <Box sx={{ mb: 1 }}>
              <Typography
                variant="caption"
                sx={{
                  fontWeight: 'bold',
                  fontSize: '0.7rem',
                  mb: 0.5,
                  display: 'block',
                  color: 'error.main',
                }}
              >
                Failure Actions (if retry actions fail):
              </Typography>
              {failureActions?.map((action: any, index: number) => (
                <ActionRow
                  key={`failure-${index}`}
                  prefix={`F${index + 1}.`}
                  action={action}
                  color="error.main"
                />
              ))}
            </Box>
          )}

          <Box sx={{ mt: 0.5, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
            {/* Edit and Delete buttons */}
            <Box sx={{ display: 'flex', gap: 0.5 }}>
              <Button
                size="small"
                variant="outlined"
                sx={{ fontSize: '0.75rem', px: 1, flex: 1 }}
                onClick={handleEdit}
                disabled={!isControlActive || !selectedHost || isMutating}
                title={
                  !isControlActive || !selectedHost ? 'Device control required to edit edges' : ''
                }
              >
                Edit
              </Button>
              {/* Only show delete button if not a protected edge */}
              {!isProtectedEdge && (
                <Button
                  size="small"
                  variant="outlined"
                  color="error"
                  sx={{ fontSize: '0.75rem', px: 1, flex: 1 }}
                  onClick={onDelete}
                  disabled={isMutating}
                >
                  {isMutating ? 'Deleting…' : 'Delete'}
                </Button>
              )}
            </Box>

            {/* Run button - only shown when actions exist */}
            {hasActions && (
              <Button
                size="small"
                variant="contained"
                sx={{ fontSize: '0.75rem', px: 1 }}
                onClick={handleRunActions}
                disabled={!canRunActions}
                title={
                  !isControlActive || !selectedHost ? 'Device control required to test actions' : ''
                }
              >
                {edgeHook.actionHook.loading ? 'Running...' : 'Run'}
              </Button>
            )}

            {/* Linear Progress - shown when running */}
            {edgeHook.actionHook.loading && <LinearProgress sx={{ mt: 0.5, borderRadius: 1 }} />}

            {/* Run result display - with scrolling */}
            {edgeHook.runResult && (
              <Box
                sx={{
                  mt: 0.5,
                  p: 0.5,
                  bgcolor: edgeHook.runResult.includes('✅ Execution')
                    ? 'success.light'
                    : edgeHook.runResult.includes('❌ Execution') ||
                        (edgeHook.runResult.includes('❌') && !edgeHook.runResult.includes('✅'))
                      ? 'error.light'
                      : edgeHook.runResult.includes('⚠️')
                        ? 'warning.light'
                        : 'success.light',
                  borderRadius: 0.5,
                  maxHeight: '150px', // Limit height to enable scrolling
                  overflow: 'auto', // Enable scrolling
                  border: '1px solid rgba(0, 0, 0, 0.12)', // Add subtle border
                }}
              >
                <Typography
                  variant="caption"
                  sx={{
                    fontFamily: 'monospace',
                    whiteSpace: 'pre-line',
                    fontSize: '0.7rem', // Slightly smaller font for compactness
                    lineHeight: 1.2, // Tighter line spacing
                  }}
                >
                  {edgeHook.formatRunResult(edgeHook.runResult)}
                </Typography>
              </Box>
            )}

            {/* Verification report for the repeat_until ("press until appears/
                disappears") leg — the evidence frame that drove pass/fail.
                Mirrors goto's "View report" link. */}
            {edgeHook.runReportUrl && (
              <Typography variant="caption" sx={{ display: 'block', mt: 0.5 }}>
                <a
                  href={edgeHook.runReportUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: '#1976d2', textDecoration: 'underline', fontWeight: 'bold' }}
                >
                  🔍 View verification report
                </a>
              </Typography>
            )}
          </Box>
        </Box>
      </Paper>
    );
  },
);
