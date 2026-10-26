import {
  Close as CloseIcon,
  PlayArrow as PlayArrowIcon,
  Route as RouteIcon,
  Error as ErrorIcon,
  CallSplit as CallSplitIcon,
  ExpandLess as ExpandLessIcon,
  ExpandMore as ExpandMoreIcon,
} from '@mui/icons-material';
import {
  Box,
  Typography,
  Button,
  IconButton,
  Paper,
  Chip,
  Divider,
  CircularProgress,
  Alert,
  LinearProgress,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Tooltip,
} from '@mui/material';
import React, { useEffect, useMemo, useState } from 'react';

import { useDeviceData } from '../../contexts/device/DeviceDataContext';
import { useNavigation } from '../../contexts/navigation/NavigationContext';
import { openHostUrl } from '../../utils/buildUrlUtils';
import { useNode } from '../../hooks/navigation/useNode';
import { useValidationColors } from '../../hooks/validation/useValidationColors';
import type { EdgeMetricData, NodeMetricData } from '../../types/navigation/Metrics_Types';
import { UINavigationNode } from '../../types/pages/Navigation_Types';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { AppIcon } from '../../constants/icons';
import { primaryButtonSx } from '../common/PageChrome';
import type { VerificationMode } from '../../utils/navigationExecutionUtils';
import { getZIndex } from '../../utils/zIndexUtils';
import { TYPOGRAPHY } from '../../constants/typography';

const VERIFICATION_MODE_LS_KEY = 'navigation.verificationMode';

function loadVerificationModeFromStorage(): VerificationMode {
  try {
    const v = window.localStorage.getItem(VERIFICATION_MODE_LS_KEY);
    if (v === 'each' || v === 'auto' || v === 'end') return v;
  } catch {
    // ignore — incognito tabs / disabled storage fall through to default
  }
  return 'end';
}

// Compact "command(firstParam)" rendering, shared by the main / retry /
// failure action sub-lists below.
function getActionDisplayText(action: any): string {
  const command = action.command || 'unknown_action';
  const params = action.params || {};
  if (params && Object.keys(params).length > 0) {
    const firstParam = Object.values(params)[0];
    const paramStr = typeof firstParam === 'string' ? firstParam : JSON.stringify(firstParam);
    return paramStr.length > 50
      ? `${command}(${paramStr.substring(0, 50)}...)`
      : `${command}(${paramStr})`;
  }
  return command;
}

// Per-action execution meta the executor honours: `iterator` (repeat count,
// default 1) and the post-action settle `wait_time` (ms), which the host
// resolves from params.wait_time or the action top-level. Returned split so
// each renders in its own fixed column ("x2" | "wait:2000ms").
function getActionMeta(action: any): { iter: string; wait: string } {
  const rawWait = action?.params?.wait_time ?? action?.wait_time ?? 0;
  const waitMs = Number(rawWait) > 0 ? Number(rawWait) : 0;
  const wait = waitMs > 0 ? `wait:${waitMs}ms` : '';
  // "Repeat until" actions have no meaningful fixed count — show "repeat"
  // instead of "x1" so the preview reads truthfully without extra clutter.
  // The condition can be node-based (target_node_id) or verification-based
  // (verifications[]); gating only on verifications.length missed node-based
  // repeats and fell back to the stale `iterator`.
  const ru = action?.repeat_until;
  if (ru && (ru.condition || ru.target_node_id || ru.verifications?.length)) {
    return { iter: 'repeat', wait };
  }
  const iterator = Number(action?.iterator) > 0 ? Number(action.iterator) : 1;
  return { iter: `x${iterator}`, wait };
}

// One action group inside a step. `label` tags the retry/failure groups so the
// preview matches what the executor actually runs (main → retry → failure).
const ActionSubList: React.FC<{ label?: string; actions: any[]; emptyText?: string }> = ({
  label,
  actions,
  emptyText,
}) => {
  const hasActions = !!actions && actions.length > 0;
  if (!hasActions && !emptyText) return null;
  return (
    <Box sx={{ ml: 1.5 }}>
      {label && (
        <Typography
          variant="caption"
          sx={{ fontWeight: 'bold', color: 'text.secondary', display: 'block', mt: 0.25 }}
        >
          {label}
        </Typography>
      )}
      {hasActions ? (
        actions.map((action: any, actionIndex: number) => {
          const meta = getActionMeta(action);
          return (
            <Box
              key={actionIndex}
              sx={{
                display: 'flex',
                alignItems: 'baseline',
                fontFamily: 'monospace',
                fontSize: TYPOGRAPHY.body.size,
                color: 'text.secondary',
                mb: 0,
              }}
            >
              {/* Command column — fixed width so the meta columns line up
                  across every row like a table; long names ellipsize. */}
              <Box
                component="span"
                sx={{
                  flex: '0 0 24ch',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  '&:before': { content: '"- "', fontWeight: 'bold' },
                }}
              >
                {getActionDisplayText(action)}
              </Box>
              <Box
                component="span"
                sx={{ flex: '0 0 7ch', color: 'text.disabled', fontSize: TYPOGRAPHY.caption.size }}
              >
                {meta.iter}
              </Box>
              <Box
                component="span"
                sx={{ flex: '1 1 auto', color: 'text.disabled', fontSize: TYPOGRAPHY.caption.size }}
              >
                {meta.wait}
              </Box>
            </Box>
          );
        })
      ) : (
        <Typography
          variant="body2"
          sx={{ fontSize: TYPOGRAPHY.body.size, color: 'text.secondary', fontStyle: 'italic' }}
        >
          {emptyText}
        </Typography>
      )}
    </Box>
  );
};

interface NodeGotoPanelProps {
  selectedNode: UINavigationNode;
  nodes: UINavigationNode[];
  treeId: string;
  onClose: () => void;
  // Optional current node ID for navigation starting point
  currentNodeId?: string;
  // Device control props (optional for navigation preview)
  selectedHost?: any;
  selectedDeviceId?: string;
  isControlActive?: boolean;
  // Active canvas viewing scope (lowercase variant name, or null for base).
  // Forwarded onto the navigation execute call so the resulting
  // execution_results row carries the same `variant` and metrics aggregate
  // per scope.
  variant?: string | null;
  /**
   * Per-(edge,action_set) metrics for the active scope. Used to compute the
   * goto duration estimate as Σ(edge.avg_action_time + dest_node.avg_verification_time)
   * over the navigation_path returned by the preview.
   */
  edgeMetrics?: Map<string, EdgeMetricData>;
  nodeMetrics?: Map<string, NodeMetricData>;
  /**
   * Called after a successful goto with the executed path + landing node id.
   * NavigationEditor uses it to follow the result into a subtree (switch the
   * canvas + breadcrumb, center the node) when the landing node lives in a
   * subtree rather than the currently-displayed tree.
   */
  onGotoArrived?: (navigationPath: any[] | undefined, finalNodeId: string) => void;
  /** Rendered inside another panel (Take Control overlay): no own frame, title, close or fixed size. */
  embedded?: boolean;
  /** Embedded only: rendered left of the Run button on the same row (the host's node picker). */
  leading?: React.ReactNode;
}

// One step line in the compact view; click to reveal its actions.
const CompactStep: React.FC<{ index: number; step: any }> = ({ index, step }) => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const [open, setOpen] = useState(false);
  const actions: any[] = step.actions ?? [];
  return (
    <Box sx={{ minWidth: 0 }}>
      <Box
        component="button"
        type="button"
        onClick={() => setOpen((v) => !v)}
        sx={{
          display: 'flex',
          alignItems: 'center',
          width: '100%',
          minWidth: 0,
          background: 'none',
          border: 0,
          p: 0,
          cursor: actions.length ? 'pointer' : 'default',
          textAlign: 'left',
          color: P.textSecondary,
          fontSize: TYPOGRAPHY.caption.size,
        }}
      >
        {open ? <ExpandLessIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} /> : <ExpandMoreIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />}
        <Box component="span" sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {index + 1}. {step.from_node_label || t('Start')} → {step.to_node_label || t('Target')} ·{' '}
          {tn(actions.length, '{count} action', '{count} actions')}
        </Box>
      </Box>
      {open &&
        actions.map((action, i) => (
          <Typography
            key={i}
            variant="caption"
            noWrap
            sx={{ display: 'block', ml: 2.5, fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}
          >
            {getActionDisplayText(action)}
          </Typography>
        ))}
    </Box>
  );
};

export const NodeGotoPanel: React.FC<NodeGotoPanelProps> = ({
  embedded = false,
  leading,
  selectedNode,
  nodes,
  treeId,
  onClose,
  currentNodeId,
  selectedHost,
  selectedDeviceId,
  isControlActive = false,
  variant = null,
  edgeMetrics,
  nodeMetrics,
  onGotoArrived,
}) => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const [showSteps, setShowSteps] = useState(false);
  // Verification mode for this goto. Persisted to localStorage so the user's
  // choice sticks across sessions; the dropdown next to the Goto button lets
  // them flip it before clicking.
  // Embedded (Take Control) has no Verify control: it always verifies the destination only.
  const [verificationMode, setVerificationMode] = useState<VerificationMode>(
    embedded ? 'end' : loadVerificationModeFromStorage,
  );
  const handleVerificationModeChange = (next: VerificationMode) => {
    setVerificationMode(next);
    try {
      window.localStorage.setItem(VERIFICATION_MODE_LS_KEY, next);
    } catch {
      // best-effort persistence; don't break the panel if storage rejects
    }
  };

  // Use the consolidated node hook
  const nodeHook = useNode({
    selectedHost,
    selectedDeviceId,
    isControlActive,
    treeId,
    currentNodeId,
    variant,
    verificationMode,
    onGotoArrived,
  });

  // Get validation colors hook for resetting edge colors
  const { resetNavigationEdgeColors } = useValidationColors();

  // Live references for the active UI. The node's inline verification snapshot
  // (params.text / params.image_path) goes stale when a reference is edited
  // elsewhere, and the host now resolves text from the reference at execution
  // (single source of truth). Resolve the same way here so the panel DISPLAYS
  // exactly what will run — otherwise it shows the stale "PLAY" while the goto
  // actually runs the edited "PLAY|CONTINUE".
  const { getModelReferences } = useDeviceData();
  const { userInterface } = useNavigation();
  const liveReferences = useMemo(
    () => (userInterface?.name ? getModelReferences(userInterface.name) : {}),
    [getModelReferences, userInterface?.name],
  );
  const resolveVerificationValue = (verification: any): string | undefined => {
    const params = (verification?.params as any) || {};
    if (verification?.verification_type === 'image') return params.image_path;
    if (verification?.verification_type !== 'text') return undefined;
    // Prefer the live reference text; fall back to the inline snapshot for
    // ad-hoc text verifications that don't point at a saved reference.
    const ref = params.reference_name ? (liveReferences as any)[params.reference_name] : undefined;
    return ref?.text ?? params.text;
  };

  // Estimated goto duration based on historical metrics for the active scope:
  //   ETA = Σ over path of (edge.avg_action_time + dest_node.avg_verification_time)
  //
  // Each step's edge time covers actions + final_wait. The destination node's
  // verification time is added optimistically: per-step verification only fires
  // for the LAST step under the default 'end' mode, but the historical
  // node_metrics.avg_verification_time reflects the cost when it does fire,
  // so summing it for every step gives a conservative (slightly high) ETA.
  // Steps with no metrics yet are skipped from the sum and counted in
  // `unmeasured`. Display: "Estimated: 7.34s (3 of 3 steps measured)".
  const eta = useMemo(() => {
    const transitions = nodeHook.navigationTransitions ?? [];
    if (!transitions.length || !edgeMetrics || !nodeMetrics) {
      return { ms: 0, total: transitions.length, measured: 0 };
    }
    let total_ms = 0;
    let measured = 0;
    for (const step of transitions) {
      const edgeKey = step.edge_id && step.action_set_id
        ? `${step.edge_id}#${step.action_set_id}`
        : step.edge_id ?? '';
      const edge = edgeKey ? edgeMetrics.get(edgeKey) : undefined;
      const node = nodeMetrics.get(step.to_node_id);
      if (edge) {
        total_ms += edge.avg_action_time ?? 0;
        if (node) total_ms += node.avg_verification_time ?? 0;
        measured++;
      }
    }
    return { ms: total_ms, total: transitions.length, measured };
  }, [nodeHook.navigationTransitions, edgeMetrics, nodeMetrics]);

  // Conditional-path summary. When a step traverses a conditional edge, the
  // shown route is only ONE of several possibilities — after the shared action
  // the device may land on a sibling node instead. We surface this so the user
  // knows the preview isn't deterministic and which other screens are possible.
  const conditionalInfo = useMemo(() => {
    const transitions = (nodeHook.navigationTransitions ?? []).filter(
      (t: any) => !t?.is_virtual,
    );
    const hasConditional = transitions.some((t: any) => t?.is_conditional);
    const siblings = new Set<string>();
    transitions.forEach((t: any) => {
      if (t?.is_conditional && Array.isArray(t.sibling_labels)) {
        t.sibling_labels.forEach((label: string) => siblings.add(label));
      }
    });
    return { hasConditional, siblingLabels: Array.from(siblings) };
  }, [nodeHook.navigationTransitions]);

  // Memoize the functions we need to avoid recreating them on every render
  const { clearNavigationMessages, loadNavigationPreview } = useMemo(
    () => ({
      clearNavigationMessages: nodeHook.clearNavigationMessages,
      loadNavigationPreview: nodeHook.loadNavigationPreview,
    }),
    [nodeHook.clearNavigationMessages, nodeHook.loadNavigationPreview],
  );

  // Load navigation preview on component mount and when key dependencies change
  useEffect(() => {
    // Don't reload if we're already at the destination
    if (currentNodeId === selectedNode.id) return;

    // Don't reload if we're currently executing navigation
    if (nodeHook.isExecuting) return;

    // Don't reload if we have an error or execution message (prevent clearing error state)
    if (nodeHook.navigationError || nodeHook.executionMessage) return;

    clearNavigationMessages();
    loadNavigationPreview(selectedNode, nodes);
     
  }, [
    treeId,
    selectedNode.id,
    currentNodeId,
    // Removed selectedNode, clearNavigationMessages, loadNavigationPreview to prevent reloading on success
    // Only reload when the actual IDs change, not when node data updates
    // Don't include nodeHook.navigationError or nodeHook.executionMessage in deps to prevent clearing them
  ]);

  const verifyControl = (
    <FormControl size="small" sx={{ minWidth: 110 }}>
      <InputLabel
        id="goto-verify-label"
        sx={{ fontSize: TYPOGRAPHY.caption.size }}
      >
        Verify
      </InputLabel>
      <Select
        labelId="goto-verify-label"
        label="Verify"
        value={verificationMode}
        onChange={(e) => handleVerificationModeChange(e.target.value as VerificationMode)}
        disabled={nodeHook.isExecuting}
        sx={{
          fontSize: TYPOGRAPHY.caption.size,
          '& .MuiSelect-select': { py: 0.5 },
        }}
        title="When to run verify_node during the goto. End: only the destination. Each: every step. Auto: skip steps where confidence ≥ 0.7."
      >
        <MenuItem value="end" sx={{ fontSize: TYPOGRAPHY.caption.size }}>End only</MenuItem>
        <MenuItem value="each" sx={{ fontSize: TYPOGRAPHY.caption.size }}>Each step</MenuItem>
        <MenuItem value="auto" sx={{ fontSize: TYPOGRAPHY.caption.size }}>Auto</MenuItem>
      </Select>
    </FormControl>
  );

  const statusDisplay = (
    <>
        {nodeHook.isExecuting && (
          <Box sx={{ mt: 1 }}>
            <LinearProgress />
          </Box>
        )}

        {/* Status Display */}
        {nodeHook.navigationError && (
          <Alert
            severity="error"
            variant={embedded ? 'outlined' : 'standard'}
            icon={<ErrorIcon fontSize={embedded ? 'inherit' : undefined} />}
            sx={
              embedded
                ? { mt: 0.5, py: 0, px: 1, fontSize: TYPOGRAPHY.caption.size, alignItems: 'center', wordBreak: 'break-word', '& .MuiAlert-icon': { fontSize: TYPOGRAPHY.navbarItem.size, py: 0.75, mr: 0.75 }, '& .MuiAlert-message': { py: 0.75, minWidth: 0, overflow: 'hidden' } }
                : { mt: 0.5, fontSize: TYPOGRAPHY.body.size, color: 'error.main', backgroundColor: 'error.light', '& .MuiAlert-icon': { color: 'error.main' } }
            }
          >
            <Typography variant="body2" sx={{ fontSize: embedded ? '0.75rem' : undefined, fontWeight: 'bold', mb: 0.5, color: embedded ? 'text.primary' : 'error.main', wordBreak: 'break-word' }}>
              {nodeHook.navigationError}
            </Typography>
            {/* Failure reports. For a conditional step we surface the expected
                target branch AND every sibling that was also checked, so the
                user sees why each possible landing failed — not just one. */}
            {nodeHook.verificationReports && nodeHook.verificationReports.length > 0 ? (
              <Box sx={{ mt: 1 }}>
                {nodeHook.verificationReports
                  .filter((r) => r.debug_report_url)
                  .map((r, i) => (
                    <Typography key={i} variant={embedded ? 'caption' : 'body2'} sx={{ mt: 0.25, display: 'block', fontSize: embedded ? '0.7rem' : undefined }}> // ui-ok: no-literal-font-size - rem, follows the Size picker; icon-adjacent label
                      <a
                        href={r.debug_report_url}
                        onClick={(e) => {
                          e.preventDefault();
                          void openHostUrl(r.debug_report_url as string);
                        }}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ color: P.accentText, textDecoration: 'underline', fontWeight: 'bold' }}
                      >
                        <AppIcon name="search" /> View {r.kind === 'sibling' ? 'sibling' : 'target'} report
                        {r.label ? ` — ${r.label}` : ''}
                      </a>
                    </Typography>
                  ))}
              </Box>
            ) : (
              nodeHook.debugReportUrl && (
                <Typography variant={embedded ? 'caption' : 'body2'} sx={{ mt: 1, display: 'block', fontSize: embedded ? '0.7rem' : undefined }}> // ui-ok: no-literal-font-size - rem, follows the Size picker; icon-adjacent label
                  <a
                    href={nodeHook.debugReportUrl}
                    onClick={(e) => {
                      e.preventDefault();
                      void openHostUrl(nodeHook.debugReportUrl as string);
                    }}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: P.accentText, textDecoration: 'underline', fontWeight: 'bold' }}
                  >
                    <AppIcon name="search" /> View Debug Report
                  </a>
                </Typography>
              )
            )}
          </Alert>
        )}
        {!nodeHook.navigationError && nodeHook.executionMessage && (
          // Passed-but-arrived-on-a-conditional-sibling is shown as a warning
          // (still a success, but the device is NOT on the requested node) so
          // the user notices the divergence; a clean success stays green.
          // While the run is still going the message is progress, never success:
          // neutral info look with the running icon (UI_STYLE: running is never green).
          <Alert
            severity={nodeHook.isExecuting ? 'info' : nodeHook.arrivedOnSibling ? 'warning' : 'success'}
            icon={nodeHook.isExecuting ? <AppIcon name="running" /> : undefined}
            variant={embedded ? 'outlined' : 'standard'}
            sx={
              embedded
                ? { mt: 0.5, py: 0, px: 1, fontSize: TYPOGRAPHY.caption.size, wordBreak: 'break-word', '& .MuiAlert-icon': { fontSize: TYPOGRAPHY.navbarItem.size, py: 0.75, mr: 0.75 }, '& .MuiAlert-message': { py: 0.75, minWidth: 0 } }
                : { mt: 0.5, fontSize: TYPOGRAPHY.body.size }
            }
          >
            <Typography variant="body2" sx={{ fontSize: embedded ? '0.75rem' : undefined, fontWeight: 'bold', mb: 0.5, wordBreak: 'break-word' }}>
              {nodeHook.executionMessage}
            </Typography>
            {nodeHook.arrivedOnSibling && (
              <Typography variant="body2" sx={{ fontSize: embedded ? '0.7rem' : undefined }}> // ui-ok: no-literal-font-size - rem, follows the Size picker; icon-adjacent label
                Conditional edge resolved to sibling{' '}
                <strong>{nodeHook.arrivedOnSibling.node_label}</strong> instead of{' '}
                <strong>{nodeHook.arrivedOnSibling.requested_node_label}</strong>.
              </Typography>
            )}
          </Alert>
        )}
    </>
  );

  if (embedded) {
    const steps = (nodeHook.navigationTransitions ?? []).filter((tr: any) => !tr?.is_virtual) as any[];
    const pathLabels: string[] = steps.length
      ? [steps[0].from_node_label || t('Start'), steps[steps.length - 1].to_node_label || t('Target')]
      : [selectedNode.data.label];
    const etaKnown = eta.total > 0 && eta.measured === eta.total;
    const atDestination = currentNodeId === selectedNode.id;
    // A finished run (ok or failed) must leave Run enabled for an immediate re-run.
    const hasResult = Boolean(nodeHook.navigationError || nodeHook.executionMessage);
    const runDisabled =
      nodeHook.isExecuting ||
      nodeHook.isLoadingPreview ||
      (atDestination && !hasResult) ||
      steps.length === 0;
    const summary = nodeHook.isLoadingPreview
      ? t('Loading navigation steps...')
      : steps.length === 0
        ? atDestination
          ? t('Already at destination')
          : t('No navigation path available')
        : '';
    return (
      <Box
        sx={{ width: '100%', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 0.5 }}
        onClick={(e) => e.stopPropagation()}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
          <Box sx={{ flex: '1 1 0', minWidth: 0, '& .MuiFormControl-root': { width: '100%' } }}>{leading}</Box>
          <Button
            variant="contained"
            size="small"
            startIcon={
              nodeHook.isExecuting ? <CircularProgress size={14} color="inherit" /> : <PlayArrowIcon />
            }
            onClick={() => {
              resetNavigationEdgeColors();
              nodeHook.executeNavigation(selectedNode);
            }}
            disabled={runDisabled}
            sx={{
              ...(primaryButtonSx(P) as object),
              alignSelf: 'stretch',
              fontSize: TYPOGRAPHY.caption.size,
              py: 0,
              minWidth: 0,
              flexShrink: 0,
              whiteSpace: 'nowrap',
            }}
          >
            {nodeHook.isExecuting ? t('Executing...') : t('Run')}
          </Button>
        </Box>

        <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1, minWidth: 0 }}>
          <Typography
            variant="caption"
            sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size, flex: '1 1 0', minWidth: 0, wordBreak: 'break-word' }}
          >
            {summary || pathLabels.join(' → ')}
            {conditionalInfo.hasConditional && (
              <Tooltip
                title={
                  conditionalInfo.siblingLabels.length > 0
                    ? t('Conditional path — could also land on: {nodes}', {
                        nodes: conditionalInfo.siblingLabels.join(', '),
                      })
                    : t('Conditional path — the route shown is one of several possibilities')
                }
              >
                <CallSplitIcon
                  sx={{ fontSize: TYPOGRAPHY.navbarItem.size, color: 'warning.main', ml: 0.5, verticalAlign: 'middle' }}
                />
              </Tooltip>
            )}
          </Typography>
          {steps.length > 0 && (
            <Box sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
              <Typography
                component="button"
                type="button"
                variant="caption"
                onClick={() => setShowSteps((v) => !v)}
                sx={{
                  background: 'none',
                  border: 0,
                  p: 0,
                  cursor: 'pointer',
                  color: P.accentText,
                  fontSize: TYPOGRAPHY.caption.size,
                  textDecoration: 'underline',
                }}
              >
                {showSteps
                  ? t('Hide steps')
                  : tn(steps.length, 'Show steps ({count})', 'Show steps ({count})')}
              </Typography>
              {etaKnown && (
                <Typography
                  component="span"
                  variant="caption"
                  sx={{ color: P.textMuted, fontSize: TYPOGRAPHY.caption.size, ml: 0.75 }}
                >
                  · {t('ETA {seconds} s', { seconds: (eta.ms / 1000).toFixed(1) })}
                </Typography>
              )}
            </Box>
          )}
        </Box>

        {statusDisplay}

        {showSteps && steps.map((tr, i) => <CompactStep key={i} index={i} step={tr} />)}
      </Box>
    );
  }

  return (
    <Paper
      sx={{
        position: 'absolute',
        top: 16,
        right: 16,
        width: 440,
        minHeight: 300,
        maxHeight: 'calc(100vh - 180px)',
        display: 'flex',
        flexDirection: 'column',
        zIndex: getZIndex('NAVIGATION_GOTO_PANEL'),
        overflow: 'hidden',
        border: '1px solid white',
      }}
      onClick={(e) => e.stopPropagation()}
    >
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          p: 2,
          pb: 1,
          flexShrink: 0,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <RouteIcon color="primary" />
          <Typography variant="h6" sx={{ margin: 0, fontSize: TYPOGRAPHY.cardTitle.size }}>
            Go To Node
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          {verifyControl}
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
      </Box>

      {/* Single Scrollable Content Area */}
      <Box
        sx={{
          flex: 1,
          minWidth: 0,
          overflowY: 'auto',
          p: 1,
          pt: 1,
          pb: 0.5,
          '&::-webkit-scrollbar': {
            width: '6px',
          },
          '&::-webkit-scrollbar-track': {
            background: 'rgba(0,0,0,0.1)',
          },
          '&::-webkit-scrollbar-thumb': {
            background: 'rgba(0,0,0,0.3)',

            '&:hover': {
              background: 'rgba(0,0,0,0.5)',
            },
          },
        }}
      >
        {/* Node Information */}
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 1, gap: 2 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
            Target: {selectedNode.data.label}
          </Typography>
          <Chip label={selectedNode.type} size="small" sx={{ fontSize: TYPOGRAPHY.caption.size }} />
        </Box>

        <Box
          sx={{ display: 'flex', gap: 2, mb: 0.5, fontSize: TYPOGRAPHY.body.size, color: 'text.secondary' }}
        >
          <Typography variant="body2">
            <strong>Depth:</strong> {selectedNode.data.depth || 0}
          </Typography>
          <Typography variant="body2">
            <strong>Parent:</strong>{' '}
            {nodeHook.getParentNames(selectedNode.data.parent || [], nodes)}
          </Typography>
        </Box>

        <Divider sx={{ my: 1 }} />

        {/* Navigation Path — ETA badge inline on the right */}
        <Box
          sx={{
            mb: 0.5,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 1,
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0 }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
              Path:{' '}
              {(() => {
                const transitions = nodeHook.navigationTransitions ?? [];
                const start = (transitions[0] as any)?.from_node_label;
                if (!start) return selectedNode.data.label;
                return `${start} → ${selectedNode.data.label}`;
              })()}
            </Typography>
            {/* Conditional-path badge — the shown route is one of several. */}
            {conditionalInfo.hasConditional && (
              <Tooltip
                title={
                  conditionalInfo.siblingLabels.length > 0
                    ? `Conditional path — could also land on: ${conditionalInfo.siblingLabels.join(', ')}`
                    : 'Conditional path — the route shown is one of several possibilities'
                }
              >
                <Chip
                  // ui-ok: no-literal-font-size — `!important` overrides MUI's Chip icon size;
                  // the label is on TYPOGRAPHY.microMeta.size one line below.
                  icon={<CallSplitIcon sx={{ fontSize: '0.85rem !important' }} />} // ui-ok: no-literal-font-size - rem, follows the Size picker; icon-adjacent label
                  label="alt paths"
                  size="small"
                  color="warning"
                  variant="outlined"
                  sx={{ height: 20, fontSize: TYPOGRAPHY.microMeta.size, '& .MuiChip-label': { px: 0.5 } }}
                />
              </Tooltip>
            )}
          </Box>
          <Typography
            variant="caption"
            sx={{
              fontSize: TYPOGRAPHY.caption.size,
              fontWeight: 'bold',
              color: P.textMuted,
              padding: '2px 6px',
              borderRadius: '4px',
              backgroundColor: 'rgba(255,255,255,0.1)',
              whiteSpace: 'nowrap',
            }}
            title={
              eta.total > 0 && eta.measured === eta.total
                ? `Σ over path of (edge.avg_action_time + dest_node.avg_verification_time) — all ${eta.total} step${eta.total === 1 ? '' : 's'} measured`
                : `Hidden — only ${eta.measured} of ${eta.total} step${eta.total === 1 ? '' : 's'} measured`
            }
          >
            ETA:&nbsp;
            {eta.total > 0 && eta.measured === eta.total
              ? `${(eta.ms / 1000).toFixed(2)}s`
              : 'unknown'}
          </Typography>
        </Box>

        {/* Navigation Steps */}
        <Box
          sx={{
            mb: 0.5,
            border: '1px solid',
            borderColor: P.borderColor,
            borderRadius: 1,
            p: 1,
          }}
        >
          <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 0 }}>
            Navigation Steps:
          </Typography>

          {!nodeHook.isLoadingPreview &&
            nodeHook.navigationTransitions &&
            nodeHook.navigationTransitions.length > 0 && (
              <Box>
                {nodeHook.navigationTransitions
                  // Hide synthetic ENTER_SUBTREE / EXIT_SUBTREE transitions.
                  // Virtual edges are pure graph plumbing — pathfinding needs
                  // them to cross tree boundaries but they carry a fake
                  // `enter_subtree(tree_id=…)` action that's not a device
                  // interaction. The host executor already skips them at
                  // dispatch time; this just keeps the preview honest.
                  .filter((t: any) => !t?.is_virtual)
                  .map((transition, index) => {
                  const transitionData = transition as any;
                  return (
                    <Box
                      key={index}
                      sx={{
                        mb: 0,
                        p: 0.5,
                        borderRadius: 1,
                        '&:last-child': { mb: 0 },
                      }}
                    >
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5 }}>
                        <Typography
                          variant="subtitle2"
                          sx={{ fontWeight: 'bold', fontSize: TYPOGRAPHY.body.size }}
                        >
                          {index + 1}.{' '}
                          {transitionData.from_node_label || 'Start'} →{' '}
                          {transitionData.to_node_label || 'Target'}
                        </Typography>
                        {/* Conditional step — destination is one of several. */}
                        {transitionData.is_conditional && (
                          <Tooltip
                            title={
                              transitionData.sibling_labels?.length > 0
                                ? `Conditional — may instead land on: ${transitionData.sibling_labels.join(', ')}`
                                : 'Conditional step — destination is one of several'
                            }
                          >
                            <CallSplitIcon
                              sx={{ fontSize: TYPOGRAPHY.navbarItem.size, color: 'warning.main' }}
                            />
                          </Tooltip>
                        )}
                        {/* Recovery step — inserted at runtime because a previous
                            conditional step landed on a sibling instead of the
                            planned target. This step was NOT in the pre-execution
                            preview; it replaces the original tail. */}
                        {transitionData.is_recovery && (
                          <Tooltip
                            title={
                              transitionData.recovered_from_node_label
                                ? `Re-routed from sibling: ${transitionData.recovered_from_node_label}`
                                : 'Re-routed after conditional sibling detection'
                            }
                          >
                            <Chip
                              label="recovered"
                              size="small"
                              variant="outlined"
                              sx={{
                                height: 18,
                                fontSize: TYPOGRAPHY.microMeta.size,
                                color: P.textSecondary,
                                borderColor: P.borderColor,
                                '& .MuiChip-label': { px: 0.5 }
                              }}
                            />
                          </Tooltip>
                        )}
                      </Box>

                      <ActionSubList
                        actions={transitionData.actions}
                        emptyText="No actions defined"
                      />
                      {transitionData.retryActions && transitionData.retryActions.length > 0 && (
                        <ActionSubList label="Retry:" actions={transitionData.retryActions} />
                      )}
                      {transitionData.failureActions &&
                        transitionData.failureActions.length > 0 && (
                          <ActionSubList label="Failure:" actions={transitionData.failureActions} />
                        )}
                    </Box>
                  );
                })}
              </Box>
            )}

          {!nodeHook.isLoadingPreview &&
            (!nodeHook.navigationTransitions || nodeHook.navigationTransitions.length === 0) && (
              <Typography variant="body2" color="text.secondary">
                {currentNodeId === selectedNode.id
                  ? 'Already at destination'
                  : 'No navigation path available'}
              </Typography>
            )}

          {nodeHook.isLoadingPreview && (
            <Typography variant="body2" color="text.secondary">
              Loading navigation steps...
            </Typography>
          )}
        </Box>

        {/* Node Verifications */}
        <Box
          sx={{
            border: '1px solid',
            borderColor: P.borderColor,
            borderRadius: 1,
            p: 1,
          }}
        >
          {selectedNode.data.verifications && selectedNode.data.verifications.length > 0 ? (
            <>
              <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 1 }}>
                Verifications:
              </Typography>
              <Box>
                {selectedNode.data.verifications.map((verification, index) => {
                  const value = resolveVerificationValue(verification);
                  // Per-leg polling window (ms). 0 = single-frame check (only the
                  // first frame is scored) — the common 'any can pass' gotcha, so
                  // flag it red here for users to spot.
                  const timeoutMs = Number((verification.params as any)?.timeout ?? 0);
                  return (
                    <Box
                      key={verification.command || index}
                      sx={{
                        mb: 0,
                        p: 0.5,

                        '&:last-child': { mb: 0 },
                      }}
                    >
                      <Typography
                        variant="subtitle2"
                        sx={{ fontWeight: 'bold', mb: 0, fontSize: TYPOGRAPHY.body.size }}
                      >
                        {index + 1}. {verification.command || 'Unnamed Verification'}
                        {value && (
                          <span style={{ color: P.accentText, marginLeft: '6px' }}>
                            {value}
                          </span>
                        )}
                        <span
                          style={{
                            color: timeoutMs > 0 ? P.textMuted : P.error,
                            marginLeft: '8px',
                            fontWeight: 'normal',
                          }}
                        >
                          {timeoutMs}ms
                        </span>
                      </Typography>
                    </Box>
                  );
                })}
              </Box>
            </>
          ) : (
            <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 0 }}>
              Verifications: None
            </Typography>
          )}
        </Box>
      </Box>

      {/* Fixed Button at Bottom */}
      <Box
        sx={{
          flexShrink: 0,
          p: 1,
        }}
      >
        <Button
          variant="contained"
          color="primary"
          startIcon={
            nodeHook.isExecuting ? (
              <CircularProgress size={16} color="inherit" />
            ) : (
              <PlayArrowIcon />
            )
          }
          onClick={() => {
            // Reset edge colors before starting new navigation
            resetNavigationEdgeColors();
            nodeHook.executeNavigation(selectedNode);
          }}
          disabled={
            nodeHook.isExecuting ||
            nodeHook.isLoadingPreview ||
            (currentNodeId === selectedNode.id && !(nodeHook.navigationError || nodeHook.executionMessage)) ||
            !nodeHook.navigationTransitions ||
            nodeHook.navigationTransitions.length === 0
            // ✅ REMOVED: Don't check for empty actions - conditional edges may have empty default actions
            // The backend pathfinding ensures only valid paths are returned
          }
          fullWidth
          sx={{ fontSize: TYPOGRAPHY.body.size }}
        >
          {nodeHook.isExecuting
            ? 'Executing...'
            : currentNodeId === selectedNode.id && !(nodeHook.navigationError || nodeHook.executionMessage)
              ? 'Already at destination'
              : 'Run'}
        </Button>

        {statusDisplay}
      </Box>
    </Paper>
  );
};
