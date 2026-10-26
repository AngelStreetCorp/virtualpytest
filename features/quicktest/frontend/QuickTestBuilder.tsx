/**
 * QuickTestBuilder — a simple, linear "shopping list" test-case builder.
 *
 * Users take control of a device, pick a user interface, then add an ordered
 * list of steps (Go to node / Action / Verification / Wait), each with a
 * stop-or-continue-on-fail choice, and run it. There is NO new storage or
 * executor: the list compiles to the standard testcase `graph_json`
 * (compileStepsToGraph) and runs through the existing /server/testcase save +
 * execute routes — same per-step screenshot report as goto.py, same
 * testcase_definitions storage, openable later in the full visual TestCaseBuilder.
 */

import {
  Add as AddIcon,
  ArrowDownward as DownIcon,
  ArrowUpward as UpIcon,
  Loop as LoopIcon,
  PlayArrow as RunIcon,
  UnfoldLess as UngroupIcon,
  AltRoute as GotoIcon,
  TouchApp as ActionIcon,
  FactCheckOutlined as VerifyIcon,
  HourglassEmpty as WaitIcon,
  AutoAwesome as SparkleIcon,
  Search as SearchIcon,
  DeleteOutline as DeleteOutlineIcon,
  Send as SendIcon,
} from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  InputBase,
  ListSubheader,
  MenuItem,
  Paper,
  Snackbar,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import React from 'react';

import { BuilderPageLayout } from '../../../frontend/src/components/common/builder';
import { StyledDialog } from '../../../frontend/src/components/common/StyledDialog';
import { DeviceControlPanels } from '../../../frontend/src/components/common/DeviceControlPanels';
import { ExecutionProgressOverlay } from '../../../frontend/src/components/common/ExecutionProgressOverlay';
import { VariantSelector } from '../../../frontend/src/components/common/VariantSelector';
import { ExecutableFavoriteStar } from '../../../frontend/src/components/common/DeviceFavoriteStar';
import { DeviceFavoriteGroupHeader } from '../../../frontend/src/components/common/DeviceFavoriteGroupHeader';
import { useExecutableFavorites } from '../../../frontend/src/hooks/useExecutableFavorites';
import { QuickTestInputsBar } from './components/QuickTestInputsBar';
import { AIEditPreview } from '../../../frontend/src/components/testcase/ai/AIEditPreview';
import { RunWithInputsDialog } from '../../../frontend/src/components/testcase/RunWithInputsDialog';
import { TestCaseBuilderHeader } from '../../../frontend/src/components/testcase/builder/TestCaseBuilderHeader';
import { InlineActionConfig } from '../../../frontend/src/components/testcase/blocks/InlineActionConfig';
import { InlineVerificationConfig } from '../../../frontend/src/components/testcase/blocks/InlineVerificationConfig';
import { DeviceDataProvider } from '../../../frontend/src/contexts/device/DeviceDataContext';
import { NavigationConfigProvider } from '../../../frontend/src/contexts/navigation/NavigationConfigContext';
import { VNCStateProvider } from '../../../frontend/src/contexts/VNCStateContext';
import { useQuickTestBuilder } from './hooks/useQuickTestBuilder';
import {
  LoopBreak,
  QUICK_LOOP_BREAK_LABELS,
  QUICK_ON_FAIL_LABELS,
  QUICK_STEP_TYPE_LABELS,
  QuickStepOnFail,
  QuickStepType,
  QuickTestLoop,
  QuickTestStep,
  isQuickLoop,
} from './types/QuickTest_Types';
import { ActionBlockData, VerificationBlockData } from '../../../frontend/src/types/testcase/TestCase_Types';
import { asPlaceholder, placeholderName } from '../../../frontend/src/utils/testcase/scriptInputUtils';
import { useAgentChatPalette } from '../../../frontend/src/constants/agentChatTheme';

const STEP_TYPES: QuickStepType[] = ['goto', 'action', 'verification', 'wait'];

const isInlineType = (t: QuickStepType) => t === 'action' || t === 'verification';

// Human label for a step (used in the execution overlay, which already prefixes
// "STEP N:" — so the label itself must NOT repeat the step number).
const stepLabel = (step: QuickTestStep): string => {
  switch (step.type) {
    case 'goto':
      return `Go to ${step.targetNodeLabel || 'node'}`;
    case 'wait':
      return `Wait ${step.waitMs ?? 1000}ms`;
    case 'action':
      return 'Action';
    case 'verification':
      return 'Verification';
    default:
      return 'Step';
  }
};

const STEP_ICONS: Record<QuickStepType, React.ElementType> = {
  goto: GotoIcon,
  action: ActionIcon,
  verification: VerifyIcon,
  wait: WaitIcon,
};

type Palette = ReturnType<typeof useAgentChatPalette>;

// Execution accent per block status: gold while running, green on pass, red on fail.
const stepAccent = (status: string | undefined, P: Palette): string | undefined => {
  switch (status) {
    case 'executing': return P.accent;
    case 'pending': return P.textMuted;
    case 'success': return P.success;
    case 'failure':
    case 'error': return P.error;
    default: return undefined;
  }
};

const QuickTestBuilderContent: React.FC = () => {
  const h = useQuickTestBuilder();
  const P = useAgentChatPalette();
  const [search, setSearch] = React.useState('');
  const executableFavorites = useExecutableFavorites();
  const matchingTests = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return h.testcaseList;
    return h.testcaseList.filter((tc) =>
      [tc.testcase_name, tc.userinterface_name, tc.variant].some((v) => (v || '').toLowerCase().includes(q)),
    );
  }, [h.testcaseList, search]);
  // Starred quick tests are pinned first (TASK-100); the search still decides what is listed.
  const favoriteTests = matchingTests.filter((tc) => executableFavorites.isFavorite('testcase', tc.testcase_id));
  const otherTests = matchingTests.filter((tc) => !executableFavorites.isFavorite('testcase', tc.testcase_id));
  const visibleTests = [...favoriteTests, ...otherTests];

  // Shared look for the compact selects in a step row (Type / On fail).
  const compactSelectSx = {
    '& .MuiInputBase-root': { fontSize: '0.8rem', borderRadius: 1.5 },
    '& .MuiOutlinedInput-notchedOutline': { borderColor: P.borderColor },
  };

  const exec = h.unifiedExecution.state;

  // ---- per-step inline config ---------------------------------------------
  // Variables are SELECTED here, never created — they're defined once in the
  // Variables bar above the list (or auto-created by typing {name} in a param).
  const renderStepConfig = (step: QuickTestStep) => {
    switch (step.type) {
      case 'goto': {
        const nodeVariables = h.inputs.filter((i) => !i.protected && i.type === 'node');
        const value = step.targetNodeLabel || '';
        // A placeholder whose variable no longer exists (e.g. just renamed) —
        // keep it selectable but visibly broken instead of blanking the field.
        const orphanPlaceholder =
          placeholderName(value) && !nodeVariables.some((v) => asPlaceholder(v.name) === value)
            ? value
            : null;
        return (
          <TextField
            select
            size="small"
            label="Target node"
            value={value}
            onChange={(e) => h.updateStep(step.id, { targetNodeLabel: e.target.value })}
            disabled={!h.navNodes.length}
            sx={{ minWidth: 240 }}
          >
            {nodeVariables.length > 0 && <ListSubheader>Variables</ListSubheader>}
            {nodeVariables.map((v) => (
              <MenuItem
                key={v.name}
                value={asPlaceholder(v.name)}
                sx={{ fontStyle: 'italic', color: P.textMuted }}
              >
                {asPlaceholder(v.name)}
              </MenuItem>
            ))}
            {orphanPlaceholder && (
              <MenuItem value={orphanPlaceholder} sx={{ fontStyle: 'italic', color: 'error.main' }}>
                {orphanPlaceholder} (missing)
              </MenuItem>
            )}
            {nodeVariables.length > 0 && <Divider />}
            <ListSubheader>Nodes</ListSubheader>
            {h.navNodes
              .filter((n: any) => n.label && n.node_type !== 'entry')
              .map((n: any) => (
                <MenuItem key={n.node_id || n.label} value={n.label}>
                  {n.label}
                </MenuItem>
              ))}
          </TextField>
        );
      }
      case 'action':
      case 'verification':
        // Configured inline below the header row (see renderInlineConfig).
        return null;
      case 'wait': {
        const numberVariables = h.inputs.filter((i) => !i.protected && i.type === 'number');
        const isVariable = typeof step.waitMs === 'string';
        // Switching to a variable only SELECTS an existing number variable —
        // disabled (with a hint) when none is defined in the Variables bar.
        const canUseVariable = isVariable || numberVariables.length > 0;
        const toggle = (
          <Tooltip
            title={
              isVariable
                ? 'Use a fixed value'
                : canUseVariable
                  ? 'Use a variable'
                  : 'Add a number variable in the Variables bar first'
            }
          >
            <span>
              <IconButton
                size="small"
                color={isVariable ? 'secondary' : 'default'}
                disabled={!canUseVariable}
                onClick={() => {
                  if (isVariable) {
                    // Back to a fixed value: seed from the variable's default if numeric.
                    const varName = placeholderName(step.waitMs);
                    const def = Number(h.inputs.find((i) => i.name === varName)?.default);
                    h.updateStep(step.id, { waitMs: Number.isNaN(def) || !def ? 1000 : def });
                  } else {
                    h.updateStep(step.id, { waitMs: asPlaceholder(numberVariables[0].name) });
                  }
                }}
              >
                <Typography variant="caption" sx={{ fontWeight: 700 }}>
                  {'{x}'}
                </Typography>
              </IconButton>
            </span>
          </Tooltip>
        );
        if (isVariable) {
          const orphan = !numberVariables.some((v) => asPlaceholder(v.name) === step.waitMs);
          return (
            <Stack direction="row" spacing={0.5} alignItems="center">
              <TextField
                select
                size="small"
                label="Wait (ms)"
                value={step.waitMs}
                onChange={(e) => h.updateStep(step.id, { waitMs: e.target.value })}
                sx={{ width: 180 }}
              >
                {numberVariables.map((v) => (
                  <MenuItem
                    key={v.name}
                    value={asPlaceholder(v.name)}
                    sx={{ fontStyle: 'italic', color: P.textMuted }}
                  >
                    {asPlaceholder(v.name)}
                  </MenuItem>
                ))}
                {orphan && (
                  <MenuItem value={step.waitMs as string} sx={{ fontStyle: 'italic', color: 'error.main' }}>
                    {step.waitMs} (missing)
                  </MenuItem>
                )}
              </TextField>
              {toggle}
            </Stack>
          );
        }
        return (
          <Stack direction="row" spacing={0.5} alignItems="center">
            <TextField
              size="small"
              type="number"
              label="Wait (ms)"
              value={step.waitMs ?? 1000}
              onChange={(e) => h.updateStep(step.id, { waitMs: Number(e.target.value) })}
              sx={{ width: 160 }}
            />
            {toggle}
          </Stack>
        );
      }
      default:
        return null;
    }
  };

  // Full-width inline editor for action/verification steps — the SAME no-modal
  // components the visual TestCaseBuilder block uses (with the reference picker).
  const renderInlineConfig = (step: QuickTestStep) => {
    if (!isInlineType(step.type)) return null;
    if (!h.areActionsLoaded) {
      return (
        <Typography variant="caption" color="text.secondary" sx={{ pt: 0.75, display: 'block' }}>
          Take control of a device to configure this {step.type}.
        </Typography>
      );
    }
    const onUpdate = (partial: any) =>
      h.updateStep(step.id, { data: { ...(step.data as any), ...partial } });
    return (
      <Box sx={{ pt: 1 }}>
        {step.type === 'action' ? (
          <InlineActionConfig data={(step.data as ActionBlockData) || { actions: [] }} onUpdate={onUpdate} />
        ) : (
          <InlineVerificationConfig
            data={(step.data as VerificationBlockData) || { verifications: [] }}
            onUpdate={onUpdate}
            userinterfaceName={h.userinterfaceName}
          />
        )}
      </Box>
    );
  };

  // ---- one step row (shared by top-level steps and loop children) ---------
  // `inLoop` swaps the right-side dropdown from onFail (Stop/Continue) to the
  // loop break behavior (Break on fail / Continue / Break on success) — same slot.
  const renderStepRow = (
    step: QuickTestStep,
    opts: {
      numberLabel: string;
      /** Loop children print their number in the card; top-level rows get it in the timeline dot. */
      showNumber?: boolean;
      inLoop: boolean;
      onUp: () => void;
      onDown: () => void;
      upDisabled: boolean;
      downDisabled: boolean;
    },
  ) => {
    const blockState = exec.blockStates.get(`node-${step.id}`);
    const accent = stepAccent(blockState?.status, P);
    return (
      <Box
        key={step.id}
        component={Paper}
        elevation={0}
        sx={{
          px: 1.5,
          py: 1,
          borderRadius: 2,
          border: `1px solid ${accent || P.borderColor}`,
          boxShadow: accent ? `0 0 0 1px ${accent}` : 'none',
          transition: 'border-color 0.2s, box-shadow 0.2s',
          '&:hover .qt-row-actions': { opacity: 1 },
        }}
      >
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          {opts.showNumber && (
            <Typography sx={{ fontSize: '0.72rem', color: P.textMuted, minWidth: 24, fontVariantNumeric: 'tabular-nums' }}>
              {opts.numberLabel}
            </Typography>
          )}

          <TextField
            select
            size="small"
            value={step.type}
            onChange={(e) => h.changeStepType(step.id, e.target.value as QuickStepType)}
            inputProps={{ 'aria-label': 'Type' }}
            SelectProps={{
              renderValue: (v) => {
                const Icon = STEP_ICONS[v as QuickStepType];
                return (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, fontWeight: 600 }}>
                    <Icon sx={{ fontSize: 16, color: P.accentText }} />
                    {QUICK_STEP_TYPE_LABELS[v as QuickStepType]}
                  </Box>
                );
              },
            }}
            sx={{ width: 160, ...compactSelectSx, '& .MuiInputBase-root': { ...compactSelectSx['& .MuiInputBase-root'], bgcolor: P.hoverBg } }}
          >
            {STEP_TYPES.map((t) => {
              const Icon = STEP_ICONS[t];
              return (
                <MenuItem key={t} value={t} sx={{ gap: 1 }}>
                  <Icon sx={{ fontSize: 16, color: P.accentText }} />
                  {QUICK_STEP_TYPE_LABELS[t]}
                </MenuItem>
              );
            })}
          </TextField>

          {renderStepConfig(step)}

          <Box sx={{ flex: 1 }} />

          {opts.inLoop ? (
            <TextField
              select
              size="small"
              value={step.loopBreak ?? 'onFailure'}
              onChange={(e) => h.updateStep(step.id, { loopBreak: e.target.value as LoopBreak })}
              inputProps={{ 'aria-label': 'On fail' }}
              sx={{ width: 150, ...compactSelectSx }}
            >
              {(['onFailure', 'continue', 'onSuccess'] as LoopBreak[]).map((v) => (
                <MenuItem key={v} value={v}>
                  {QUICK_LOOP_BREAK_LABELS[v]}
                </MenuItem>
              ))}
            </TextField>
          ) : (
            <TextField
              select
              size="small"
              value={step.onFail}
              onChange={(e) => h.updateStep(step.id, { onFail: e.target.value as QuickStepOnFail })}
              inputProps={{ 'aria-label': 'On fail' }}
              sx={{ width: 150, ...compactSelectSx }}
            >
              {(['stop', 'continue'] as QuickStepOnFail[]).map((v) => (
                <MenuItem key={v} value={v}>
                  {QUICK_ON_FAIL_LABELS[v]}
                </MenuItem>
              ))}
            </TextField>
          )}

          <Box className="qt-row-actions" sx={{ display: 'flex', alignItems: 'center', opacity: 0.35, transition: 'opacity 0.15s' }}>
            <Tooltip title="Run this step">
              <span>
                <IconButton
                  size="small"
                  disabled={!h.isControlActive || exec.isExecuting}
                  onClick={() => h.handleRunStep(step)}
                  sx={{ color: P.accentText }}
                >
                  <RunIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>
            <IconButton size="small" disabled={opts.upDisabled} onClick={opts.onUp} aria-label="Move up">
              <UpIcon fontSize="small" />
            </IconButton>
            <IconButton size="small" disabled={opts.downDisabled} onClick={opts.onDown} aria-label="Move down">
              <DownIcon fontSize="small" />
            </IconButton>
            <IconButton size="small" onClick={() => h.removeStep(step.id)} aria-label="Delete step" sx={{ '&:hover': { color: P.error } }}>
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Box>
        </Stack>
        {renderInlineConfig(step)}
      </Box>
    );
  };

  // ---- loop iterations field (fixed number <-> {variable}, like wait) -------
  const renderIterationsField = (loop: QuickTestLoop) => {
    const numberVariables = h.inputs.filter((i) => !i.protected && i.type === 'number');
    const isVariable = typeof loop.iterations === 'string';
    const canUseVariable = isVariable || numberVariables.length > 0;
    const toggle = (
      <Tooltip
        title={
          isVariable
            ? 'Use a fixed count'
            : canUseVariable
              ? 'Use a variable'
              : 'Add a number variable in the Variables bar first'
        }
      >
        <span>
          <IconButton
            size="small"
            color={isVariable ? 'secondary' : 'default'}
            disabled={!canUseVariable}
            onClick={() => {
              if (isVariable) {
                const varName = placeholderName(loop.iterations);
                const def = Number(h.inputs.find((i) => i.name === varName)?.default);
                h.updateLoop(loop.id, { iterations: Number.isNaN(def) || !def ? 2 : def });
              } else {
                h.updateLoop(loop.id, { iterations: asPlaceholder(numberVariables[0].name) });
              }
            }}
          >
            <Typography variant="caption" sx={{ fontWeight: 700 }}>
              {'{x}'}
            </Typography>
          </IconButton>
        </span>
      </Tooltip>
    );
    if (isVariable) {
      const orphan = !numberVariables.some((v) => asPlaceholder(v.name) === loop.iterations);
      return (
        <Stack direction="row" spacing={0.5} alignItems="center">
          <TextField
            select
            size="small"
            inputProps={{ 'aria-label': 'Repeat' }}
            value={loop.iterations}
            onChange={(e) => h.updateLoop(loop.id, { iterations: e.target.value })}
            sx={{ width: 150 }}
          >
            {numberVariables.map((v) => (
              <MenuItem
                key={v.name}
                value={asPlaceholder(v.name)}
                sx={{ fontStyle: 'italic', color: P.textMuted }}
              >
                {asPlaceholder(v.name)}
              </MenuItem>
            ))}
            {orphan && (
              <MenuItem value={loop.iterations as string} sx={{ fontStyle: 'italic', color: 'error.main' }}>
                {loop.iterations} (missing)
              </MenuItem>
            )}
          </TextField>
          {toggle}
        </Stack>
      );
    }
    return (
      <Stack direction="row" spacing={0.5} alignItems="center">
        <TextField
          size="small"
          type="number"
          value={loop.iterations}
          onChange={(e) => h.updateLoop(loop.id, { iterations: Math.max(1, Number(e.target.value)) })}
          inputProps={{ min: 1, 'aria-label': 'Repeat' }}
          sx={{ width: 90 }}
        />
        {toggle}
      </Stack>
    );
  };

  // ---- a loop container: header (repeat N + ungroup) + indented child rows --
  const renderLoop = (loop: QuickTestLoop, index: number) => {
    const loopState = exec.blockStates.get(`loop-${loop.id}`);
    const accent = stepAccent(loopState?.status, P);
    return (
      <Box
        key={loop.id}
        sx={{
          p: 1.5,
          borderRadius: 2,
          border: `1px solid ${accent || `${P.accent}99`}`,
          bgcolor: `${P.accent}0f`,
        }}
      >
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <Typography sx={{ fontSize: '0.85rem', fontWeight: 600 }}>Repeat</Typography>
          {renderIterationsField(loop)}
          <Typography sx={{ fontSize: '0.85rem', color: P.textSecondary }}>times</Typography>

          <Box sx={{ flex: 1 }} />

          <Button
            size="small"
            variant="text"
            startIcon={<UngroupIcon fontSize="small" />}
            onClick={() => h.removeLoop(loop.id)}
            title="Ungroup — move these steps back out of the loop"
            sx={{ textTransform: 'none', color: P.textSecondary }}
          >
            Ungroup
          </Button>
          <IconButton size="small" disabled={index === 0} onClick={() => h.moveLoop(loop.id, -1)} aria-label="Move loop up">
            <UpIcon fontSize="small" />
          </IconButton>
          <IconButton
            size="small"
            disabled={index === h.units.length - 1}
            onClick={() => h.moveLoop(loop.id, 1)}
            aria-label="Move loop down"
          >
            <DownIcon fontSize="small" />
          </IconButton>
        </Stack>

        <Stack spacing={1} sx={{ mt: 1.25 }}>
          {loop.steps.map((child, ci) =>
            renderStepRow(child, {
              numberLabel: `${index + 1}.${ci + 1}`,
              showNumber: true,
              inLoop: true,
              onUp: () => h.moveStep(child.id, -1),
              onDown: () => h.moveStep(child.id, 1),
              upDisabled: false,
              downDisabled: false,
            }),
          )}

          {loop.steps.length === 0 && (
            <Typography variant="caption" color="text.secondary" sx={{ py: 0.5 }}>
              Empty loop — add steps to repeat.
            </Typography>
          )}

          {renderAddRow((t) => h.addStepInLoop(loop.id, t), false)}
        </Stack>
      </Box>
    );
  };

  // ---- "Add" row: one dashed strip with every step type (+ Loop at top level) --
  const renderAddRow = (onAdd: (t: QuickStepType) => void, withLoop: boolean) => (
    <Box
      sx={{
        display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 0.25,
        px: 0.75, py: 0.5, borderRadius: 2, border: `1px dashed ${P.borderColor}`,
      }}
    >
      <Typography sx={{ fontSize: '0.72rem', color: P.textMuted, px: 0.75 }}>Add</Typography>
      {STEP_TYPES.map((t) => {
        const Icon = STEP_ICONS[t];
        return (
          <Button
            key={t}
            size="small"
            startIcon={<Icon sx={{ fontSize: '16px !important' }} />}
            disabled={!h.isControlActive}
            onClick={() => onAdd(t)}
            sx={{ textTransform: 'none', fontSize: '0.78rem', color: P.textSecondary, '&:hover': { color: P.accentText, bgcolor: P.hoverBg } }}
          >
            {QUICK_STEP_TYPE_LABELS[t]}
          </Button>
        );
      })}
      {withLoop && (
        <Button
          size="small"
          startIcon={<LoopIcon sx={{ fontSize: '16px !important' }} />}
          onClick={h.addLoop}
          title="Add a loop, then add steps inside it to repeat them"
          sx={{ textTransform: 'none', fontSize: '0.78rem', color: P.accentText, '&:hover': { bgcolor: `${P.accent}1a` } }}
        >
          Loop
        </Button>
      )}
    </Box>
  );

  return (
    <BuilderPageLayout>
      {/* Top bar — the SAME shared header as TestCaseBuilder/CampaignBuilder
          (uniform look & feel across builders). QuickTest has no AI mode,
          undo/redo or Versions, so those slots are simply omitted. */}
      <TestCaseBuilderHeader
        builderType="QuickTest"
        selectedHost={h.selectedHost}
        selectedDeviceId={h.selectedDeviceId}
        isControlActive={h.isControlActive}
        isControlLoading={h.isControlLoading}
        isRemotePanelOpen={h.isRemotePanelOpen}
        availableHosts={h.availableHosts}
        isDeviceLocked={h.isDeviceLocked}
        handleDeviceSelect={h.handleDeviceSelect as any}
        handleDeviceControl={h.handleDeviceControl as any}
        handleToggleRemotePanel={h.handleToggleRemotePanel}
        compatibleInterfaceNames={h.compatibleInterfaceNames}
        userinterfaceName={h.userinterfaceName}
        setUserinterfaceName={h.setUserinterfaceName}
        interfaceExtra={
          h.userinterfaceName ? (
            <VariantSelector
              userinterfaceName={h.userinterfaceName}
              value={h.variant}
              onChange={h.setVariant}
              size="small"
              fullWidth={false}
            />
          ) : undefined
        }
        testcaseName="" /* name lives in the big field below; keep header title fixed-width so it doesn't reflow while typing */
        hasUnsavedChanges={false}
        handleNew={h.handleNew}
        hideLoad /* saved quick tests are listed in the left rail instead */
        setSaveDialogOpen={h.setSaveDialogOpen}
        onSave={() => (h.testcaseName.trim() ? h.handleSave() : h.setSaveDialogOpen(true))}
        saveDisabled={!h.allSteps.length || !h.userinterfaceName}
        saveTitle={
          !h.allSteps.length ? 'Add at least one step' :
          !h.userinterfaceName ? 'Select a userinterface first' :
          'Save quick test'
        }
        isSaving={h.isSaving}
        handleExecute={h.handleExecute}
        isExecuting={exec.isExecuting}
        isExecutable={h.isExecutable}
        runButtonSx={{
          px: 2, fontWeight: 600, textTransform: 'none', boxShadow: 'none',
          backgroundColor: P.accent, color: '#1a1a1a',
          '&:hover': { backgroundColor: P.accentHover, boxShadow: 'none' },
          '&:disabled': { backgroundColor: P.hoverBg, color: P.textMuted },
        }}
      />

      {/* Saved quick tests rail + step list — same "rail beside editor" layout as Virtual Scripts. */}
      <Box sx={{ flex: 1, minHeight: 0, display: 'flex', gap: 1, p: 1, overflow: 'hidden' }}>
        <Paper variant="outlined" sx={{ width: 230, display: 'flex', flexDirection: 'column', borderRadius: 2, borderColor: P.borderColor }}>
          {/* Search + New on one row; the page header already names the builder. */}
          <Box sx={{ px: 1.5, pt: 1.25, pb: 1, display: 'flex', alignItems: 'center', gap: 0.75 }}>
            <InputBase
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search tests"
              startAdornment={<SearchIcon sx={{ fontSize: 16, color: P.textMuted, mr: 0.75 }} />}
              endAdornment={
                h.isLoadingTestCases && !h.testcaseList.length ? (
                  <CircularProgress size={12} sx={{ color: P.accent, ml: 0.5 }} />
                ) : undefined
              }
              sx={{
                flex: 1, minWidth: 0, height: 30, px: 1, fontSize: '0.8rem',
                bgcolor: P.inputBg, border: `1px solid ${P.borderColor}`, borderRadius: 1.5,
                '&.Mui-focused': { borderColor: P.accent },
              }}
            />
            <Tooltip title="New quick test">
              <IconButton size="small" onClick={h.handleNew} sx={{ flexShrink: 0, color: P.accentText, border: `1px solid ${P.borderColor}`, borderRadius: 1.5, p: 0.5 }}>
                <AddIcon sx={{ fontSize: 18 }} />
              </IconButton>
            </Tooltip>
          </Box>
          <Box sx={{ overflow: 'auto', flex: 1, px: 1, pb: 1 }}>
            {visibleTests.map((tc, index) => {
              const selected = tc.testcase_id === h.currentTestcaseId;
              const meta = [tc.userinterface_name, tc.variant].filter(Boolean).join(' · ');
              return (
                <React.Fragment key={tc.testcase_id}>
                {favoriteTests.length > 0 && index === 0 && <DeviceFavoriteGroupHeader kind="favorites" inline />}
                {favoriteTests.length > 0 && otherTests.length > 0 && index === favoriteTests.length && (
                  <DeviceFavoriteGroupHeader kind="allItems" inline />
                )}
                <Box
                  title={tc.testcase_name}
                  onClick={() => h.handleLoad(tc.testcase_id)}
                  sx={{
                    display: 'flex', alignItems: 'center', gap: 0.5, px: 1, py: 0.75, mb: 0.25, borderRadius: 1.5, cursor: 'pointer',
                    bgcolor: selected ? `${P.accent}26` : 'transparent',
                    '&:hover': { bgcolor: selected ? `${P.accent}26` : P.hoverBg },
                    '&:hover .qt-delete': { opacity: 1 },
                  }}
                >
                  <ExecutableFavoriteStar kind="testcase" itemId={tc.testcase_id} />
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography noWrap sx={{ fontSize: '0.82rem', lineHeight: 1.35, fontWeight: selected ? 600 : 400, color: selected ? P.accentText : P.textPrimary }}>
                      {tc.testcase_name}
                    </Typography>
                    {meta && (
                      <Typography noWrap sx={{ fontSize: '0.68rem', lineHeight: 1.3, color: P.textMuted }}>{meta}</Typography>
                    )}
                  </Box>
                  <Tooltip title="Delete quick test">
                    <IconButton
                      className="qt-delete"
                      size="small"
                      onClick={(e) => {
                        e.stopPropagation();
                        h.handleDelete(tc.testcase_id);
                      }}
                      sx={{ p: 0.25, opacity: selected ? 1 : 0, transition: 'opacity 0.15s', color: P.textMuted, '&:hover': { color: P.error } }}
                    >
                      <DeleteOutlineIcon sx={{ fontSize: 16 }} />
                    </IconButton>
                  </Tooltip>
                </Box>
                </React.Fragment>
              );
            })}
            {!h.isLoadingTestCases && h.testcaseList.length === 0 && (
              <Typography variant="caption" sx={{ p: 2, display: 'block', color: 'text.secondary' }}>
                No saved quick tests yet.
              </Typography>
            )}
            {h.testcaseList.length > 0 && visibleTests.length === 0 && (
              <Typography variant="caption" sx={{ p: 2, display: 'block', color: 'text.secondary' }}>
                No test matches.
              </Typography>
            )}
          </Box>
        </Paper>

        <Box sx={{ flex: 1, overflow: 'auto', border: `1px solid ${P.borderColor}`, borderRadius: 2, p: 2 }}>
        {/* The test on the page-tone area: a header card (title + variables) and a steps card. */}
        <Box sx={{ maxWidth: 1000, mx: 'auto' }}>
          <Box component={Paper} elevation={0} sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 3, p: 2, mb: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 1.5 }}>
            <InputBase
              fullWidth
              placeholder="Untitled quick test"
              value={h.testcaseName}
              onChange={(e) => h.setTestcaseName(e.target.value)}
              inputProps={{ 'aria-label': 'Test name' }}
              sx={{ fontSize: '1.3rem', fontWeight: 600, borderRadius: 1, px: 0.5, mx: -0.5, '&:hover, &.Mui-focused': { bgcolor: P.hoverBg } }}
            />
            <Typography noWrap sx={{ fontSize: '0.75rem', color: P.textMuted, flexShrink: 0, textAlign: 'right' }}>
              {[
                h.userinterfaceName || 'No interface selected',
                h.userinterfaceName && h.variant ? h.variant : '',
                `${h.allSteps.length} step${h.allSteps.length === 1 ? '' : 's'}`,
                h.units.filter(isQuickLoop).length ? `${h.units.filter(isQuickLoop).length} loop${h.units.filter(isQuickLoop).length === 1 ? '' : 's'}` : '',
                h.inputs.length ? `${h.inputs.length} variable${h.inputs.length === 1 ? '' : 's'}` : '',
              ].filter(Boolean).join(' · ')}
            </Typography>
          </Box>

          {/* Input variables — make the test a reusable template. Also auto-
              populated when a step references an unknown {name}. */}
          {/* Variables on a soft inset so the header card reads as title + variables */}
          <Box sx={{ bgcolor: P.hoverBg, borderRadius: 2, px: 1.5, py: 1, '& > *': { mb: '0 !important' } }}>
          <QuickTestInputsBar
            inputs={h.inputs}
            referencedNames={h.referencedNames}
            navNodes={h.navNodes}
            onAdd={h.addInput}
            onUpdate={h.updateInput}
            onRemove={h.removeInput}
            disabled={!h.isControlActive}
          />
          </Box>
          </Box>

          {/* AI edit: describe a change, review the proposed steps, Apply (TASK-36 §3). */}
          <Box
            sx={{
              display: 'flex', alignItems: 'center', gap: 1, mb: 2, pl: 1.25, pr: 0.5, py: 0.5,
              borderRadius: 2, border: `1px solid ${P.borderColor}`, bgcolor: P.sidebarBg,
              '&:focus-within': { borderColor: P.accent },
              opacity: h.isControlActive ? 1 : 0.7,
            }}
          >
            <SparkleIcon sx={{ fontSize: 18, color: P.accentText }} />
            <InputBase
              fullWidth
              placeholder={
                h.isControlActive
                  ? 'Ask AI to change the steps, e.g. "add a check that the cart icon is shown"'
                  : 'Take control of a device to edit the steps with AI'
              }
              value={h.aiEditPrompt}
              onChange={(e) => h.setAiEditPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && h.aiEditPrompt.trim() && !h.aiEdit.isEditing) h.aiEdit.proposeEdit(h.aiEditPrompt, h.graph);
              }}
              disabled={!h.isControlActive || h.aiEdit.isEditing}
              sx={{ fontSize: '0.85rem' }}
            />
            <Tooltip title="Send">
              <span>
                <IconButton
                  size="small"
                  aria-label="Send"
                  onClick={() => h.aiEdit.proposeEdit(h.aiEditPrompt, h.graph)}
                  disabled={!h.isControlActive || !h.aiEditPrompt.trim() || h.aiEdit.isEditing}
                  sx={{ color: P.accentText }}
                >
                  {h.aiEdit.isEditing ? <CircularProgress size={16} /> : <SendIcon sx={{ fontSize: 18 }} />}
                </IconButton>
              </span>
            </Tooltip>
          </Box>
          {h.aiEdit.error && (
            <Alert severity="warning" onClose={h.aiEdit.clear} sx={{ mb: 1.5 }}>
              {h.aiEdit.error}
            </Alert>
          )}
          {h.aiEdit.proposal && (
            <Box sx={{ mb: 1.5 }}>
              <AIEditPreview proposal={h.aiEdit.proposal} onApply={h.applyAIEdit} onCancel={h.aiEdit.clear} />
            </Box>
          )}

          <Box component={Paper} elevation={0} sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 3, p: 2 }}>
          {/* Steps as a numbered timeline: a dot per unit on a rail, the add strip at the end */}
          <Box sx={{ position: 'relative' }}>
            <Box sx={{ position: 'absolute', left: 13, top: 14, bottom: 14, width: '1px', bgcolor: P.borderColor }} />
            <Stack spacing={1.25}>
              {h.units.map((unit, index) => {
                const loop = isQuickLoop(unit);
                const state = exec.blockStates.get(loop ? `loop-${unit.id}` : `node-${unit.id}`);
                const accent = stepAccent(state?.status, P);
                return (
                  <Box key={unit.id} sx={{ display: 'grid', gridTemplateColumns: '28px minmax(0, 1fr)', gap: 1.25, alignItems: 'start' }}>
                    <Box
                      sx={{
                        mt: 1.1, width: 26, height: 26, borderRadius: '50%', zIndex: 1,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: '0.72rem', fontWeight: 600, fontVariantNumeric: 'tabular-nums',
                        bgcolor: accent ? accent : loop ? `${P.accent}26` : P.surface,
                        color: accent ? '#fff' : loop ? P.accentText : P.textSecondary,
                        border: `1px solid ${accent || (loop ? P.accent : P.borderColor)}`,
                      }}
                    >
                      {loop ? <LoopIcon sx={{ fontSize: 15 }} /> : index + 1}
                    </Box>
                    {loop
                      ? renderLoop(unit, index)
                      : renderStepRow(unit, {
                          numberLabel: String(index + 1),
                          inLoop: false,
                          onUp: () => h.moveStep(unit.id, -1),
                          onDown: () => h.moveStep(unit.id, 1),
                          upDisabled: index === 0,
                          downDisabled: index === h.units.length - 1,
                        })}
                  </Box>
                );
              })}

              <Box sx={{ display: 'grid', gridTemplateColumns: '28px minmax(0, 1fr)', gap: 1.25, alignItems: 'center' }}>
                <Box sx={{ width: 26, height: 26, borderRadius: '50%', zIndex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', bgcolor: P.background, border: `1px dashed ${P.borderColor}`, color: P.textMuted }}>
                  <AddIcon sx={{ fontSize: 15 }} />
                </Box>
                {renderAddRow(h.addStep, true)}
              </Box>
            </Stack>
          </Box>
          {!h.isControlActive && (
            <Typography variant="caption" sx={{ display: 'block', mt: 1, ml: 4.75, color: P.textMuted }}>
              Select a user interface and take control to add steps
            </Typography>
          )}
          </Box>
        </Box>
        </Box>
      </Box>

      {/* Execution progress overlay */}
      <ExecutionProgressOverlay
        variant="testcase"
        currentBlockId={exec.currentBlockId}
        blockStates={exec.blockStates}
        isExecuting={exec.isExecuting}
        executionResult={exec.result}
        nodes={[
          ...h.allSteps.map((step) => ({
            id: `node-${step.id}`,
            data: { label: stepLabel(step) },
          })),
          ...h.units.filter(isQuickLoop).map((loop) => ({
            id: `loop-${loop.id}`,
            data: { label: `Loop ×${loop.iterations}` },
          })),
        ]}
        onStop={() => {}}
        onClose={() => h.unifiedExecution.resetExecution()}
      />

      {/* Remote / AV panels — same stream + remote as TestCaseBuilder */}
      <DeviceControlPanels
        showRemotePanel={h.showRemotePanel}
        showAVPanel={h.showAVPanel}
        selectedHost={h.selectedHost}
        selectedDeviceId={h.selectedDeviceId}
        isControlActive={h.isControlActive}
        userinterfaceName={h.userinterfaceName}
        isAVPanelCollapsed={h.isAVPanelCollapsed}
        isAVPanelMinimized={h.isAVPanelMinimized}
        captureMode={h.captureMode}
        isVerificationVisible={h.isVerificationVisible}
        // QuickTest has no sidebar — pin the stream to the far left instead of
        // offsetting it by a phantom sidebar width.
        isSidebarOpen={false}
        // The panels are absolutely positioned inside BuilderPageLayout, whose
        // own bottom already sits at the footer (position:fixed; bottom:32). So
        // the footer space is ALREADY reserved — footerHeight must be 0 here, or
        // it double-counts and the panels float ~32px too high. 0 -> bottom:10px
        // -> panels sit just above the footer.
        footerHeight={0}
        handleDisconnectComplete={h.handleDisconnectComplete}
        handleAVPanelCollapsedChange={h.handleAVPanelCollapsedChange}
        handleAVPanelMinimizedChange={h.handleAVPanelMinimizedChange}
        handleCaptureModeChange={h.handleCaptureModeChange}
        isMobileOrientationLandscape={h.isMobileOrientationLandscape}
        handleMobileOrientationChange={h.handleMobileOrientationChange}
      />

      {/* Run-with-inputs dialog — pick values for the test's variables (defaults
          pre-filled; values are stamped per run, never saved). */}
      <RunWithInputsDialog
        open={h.runInputsOpen}
        inputs={h.runnableInputs}
        navNodes={h.navNodes}
        testcaseName={h.testcaseName.trim() || undefined}
        onRun={h.handleRunWithInputs}
        onCancel={() => h.setRunInputsOpen(false)}
      />

      {/* Save dialog */}
      <StyledDialog
        open={h.saveDialogOpen}
        onClose={() => h.setSaveDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Name this quick test</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            label="Test case name"
            value={h.testcaseName}
            onChange={(e) => h.setTestcaseName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && h.testcaseName.trim()) h.handleSave();
            }}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => h.setSaveDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            startIcon={h.isSaving ? <CircularProgress size={14} /> : undefined}
            disabled={!h.testcaseName.trim() || h.isSaving}
            onClick={h.handleSave}
          >
            {h.isSaving ? 'Saving...' : 'Save'}
          </Button>
        </DialogActions>
      </StyledDialog>

      {/* Snackbar */}
      <Snackbar
        open={h.snackbar.open}
        autoHideDuration={4000}
        onClose={() => h.setSnackbar({ ...h.snackbar, open: false })}
      >
        <Alert
          severity={h.snackbar.severity}
          onClose={() => h.setSnackbar({ ...h.snackbar, open: false })}
          sx={{ width: '100%' }}
        >
          {h.snackbar.message}
        </Alert>
      </Snackbar>
    </BuilderPageLayout>
  );
};

// VNCStateProvider: a web device's player (VNCStream, PlaywrightWebTerminal) reads it once control
// is taken; without it the page crashed on any host_vnc target (BUG-0192).
const QuickTestBuilder: React.FC = () => (
  <NavigationConfigProvider>
    <DeviceDataProvider>
      <VNCStateProvider>
        <QuickTestBuilderContent />
      </VNCStateProvider>
    </DeviceDataProvider>
  </NavigationConfigProvider>
);

export default QuickTestBuilder;
