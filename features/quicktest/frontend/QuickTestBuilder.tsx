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
  Delete as DeleteIcon,
  Loop as LoopIcon,
  PlayArrow as RunIcon,
  UnfoldLess as UngroupIcon,
} from '@mui/icons-material';
import {
  alpha,
  Alert,
  Box,
  Button,
  CircularProgress,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  ListSubheader,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
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
import { QuickTestInputsBar } from './components/QuickTestInputsBar';
import { RunWithInputsDialog } from '../../../frontend/src/components/testcase/RunWithInputsDialog';
import { TestCaseBuilderHeader } from '../../../frontend/src/components/testcase/builder/TestCaseBuilderHeader';
import { InlineActionConfig } from '../../../frontend/src/components/testcase/blocks/InlineActionConfig';
import { InlineVerificationConfig } from '../../../frontend/src/components/testcase/blocks/InlineVerificationConfig';
import { DeviceDataProvider } from '../../../frontend/src/contexts/device/DeviceDataContext';
import { NavigationConfigProvider } from '../../../frontend/src/contexts/navigation/NavigationConfigContext';
import { useTheme } from '../../../frontend/src/contexts/ThemeContext';
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

// Execution accent per block status: blue while running, green on pass, red on fail.
const STEP_ACCENT: Record<string, string> = {
  executing: 'primary.main',
  pending: 'primary.light',
  success: 'success.main',
  failure: 'error.main',
  error: 'error.main',
};

const QuickTestBuilderContent: React.FC = () => {
  const h = useQuickTestBuilder();
  const { actualMode } = useTheme();

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
                sx={{ fontStyle: 'italic', color: 'secondary.main' }}
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
                    sx={{ fontStyle: 'italic', color: 'secondary.main' }}
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
        <Typography variant="caption" color="text.secondary" sx={{ pl: 5, display: 'block' }}>
          Take control of a device to configure this {step.type}.
        </Typography>
      );
    }
    const onUpdate = (partial: any) =>
      h.updateStep(step.id, { data: { ...(step.data as any), ...partial } });
    return (
      <Box sx={{ pl: 5, pt: 1 }}>
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
      inLoop: boolean;
      onUp: () => void;
      onDown: () => void;
      upDisabled: boolean;
      downDisabled: boolean;
    },
  ) => {
    const blockState = exec.blockStates.get(`node-${step.id}`);
    const accent = blockState ? STEP_ACCENT[blockState.status] : undefined;
    return (
      <Paper
        key={step.id}
        variant="outlined"
        sx={{
          p: 1.5,
          transition: 'border-color 0.2s, background-color 0.2s',
          ...(accent
            ? {
                borderColor: accent,
                borderWidth: 2,
                backgroundColor: (theme) => alpha(theme.palette.text.primary, 0.02),
              }
            : {}),
        }}
      >
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <Typography variant="caption" sx={{ width: 28, textAlign: 'right', opacity: 0.6 }}>
            {opts.numberLabel}
          </Typography>

          <TextField
            select
            size="small"
            label="Type"
            value={step.type}
            onChange={(e) => h.changeStepType(step.id, e.target.value as QuickStepType)}
            sx={{ width: 150 }}
          >
            {STEP_TYPES.map((t) => (
              <MenuItem key={t} value={t}>
                {QUICK_STEP_TYPE_LABELS[t]}
              </MenuItem>
            ))}
          </TextField>

          {renderStepConfig(step)}

          {opts.inLoop ? (
            <TextField
              select
              size="small"
              label="On fail"
              value={step.loopBreak ?? 'onFailure'}
              onChange={(e) => h.updateStep(step.id, { loopBreak: e.target.value as LoopBreak })}
              sx={{ width: 160 }}
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
              label="On fail"
              value={step.onFail}
              onChange={(e) => h.updateStep(step.id, { onFail: e.target.value as QuickStepOnFail })}
              sx={{ width: 160 }}
            >
              {(['stop', 'continue'] as QuickStepOnFail[]).map((v) => (
                <MenuItem key={v} value={v}>
                  {QUICK_ON_FAIL_LABELS[v]}
                </MenuItem>
              ))}
            </TextField>
          )}

          <Box sx={{ flex: 1 }} />

          <IconButton
            size="small"
            color="success"
            title="Run this step"
            disabled={!h.isControlActive || exec.isExecuting}
            onClick={() => h.handleRunStep(step)}
          >
            <RunIcon fontSize="small" />
          </IconButton>
          <IconButton size="small" disabled={opts.upDisabled} onClick={opts.onUp}>
            <UpIcon fontSize="small" />
          </IconButton>
          <IconButton size="small" disabled={opts.downDisabled} onClick={opts.onDown}>
            <DownIcon fontSize="small" />
          </IconButton>
          <IconButton size="small" color="error" onClick={() => h.removeStep(step.id)}>
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Stack>
        {renderInlineConfig(step)}
      </Paper>
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
            label="Repeat"
            value={loop.iterations}
            onChange={(e) => h.updateLoop(loop.id, { iterations: e.target.value })}
            sx={{ width: 150 }}
          >
            {numberVariables.map((v) => (
              <MenuItem
                key={v.name}
                value={asPlaceholder(v.name)}
                sx={{ fontStyle: 'italic', color: 'secondary.main' }}
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
          label="Repeat"
          value={loop.iterations}
          onChange={(e) => h.updateLoop(loop.id, { iterations: Math.max(1, Number(e.target.value)) })}
          inputProps={{ min: 1 }}
          sx={{ width: 90 }}
        />
        {toggle}
      </Stack>
    );
  };

  // ---- a loop container: header (repeat N + ungroup) + indented child rows --
  const renderLoop = (loop: QuickTestLoop, index: number) => {
    const loopState = exec.blockStates.get(`loop-${loop.id}`);
    const accent = loopState ? STEP_ACCENT[loopState.status] : undefined;
    return (
      <Paper
        key={loop.id}
        variant="outlined"
        sx={{
          p: 1.5,
          borderLeft: 4,
          borderLeftColor: accent || 'primary.main',
          backgroundColor: (theme) => alpha(theme.palette.primary.main, 0.04),
          ...(accent ? { borderColor: accent, borderWidth: 2, borderLeftWidth: 4 } : {}),
        }}
      >
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <LoopIcon fontSize="small" color="primary" />
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            Loop {index + 1}
          </Typography>
          {renderIterationsField(loop)}
          <Typography variant="caption" color="text.secondary">
            times
          </Typography>

          <Box sx={{ flex: 1 }} />

          <Button
            size="small"
            variant="text"
            startIcon={<UngroupIcon fontSize="small" />}
            onClick={() => h.removeLoop(loop.id)}
            title="Ungroup — move these steps back out of the loop"
          >
            Ungroup
          </Button>
          <IconButton size="small" disabled={index === 0} onClick={() => h.moveLoop(loop.id, -1)}>
            <UpIcon fontSize="small" />
          </IconButton>
          <IconButton
            size="small"
            disabled={index === h.units.length - 1}
            onClick={() => h.moveLoop(loop.id, 1)}
          >
            <DownIcon fontSize="small" />
          </IconButton>
        </Stack>

        <Stack
          spacing={1}
          sx={{
            mt: 1,
            pl: 2,
            ml: 1,
            borderLeft: '2px dashed',
            borderLeftColor: 'divider',
          }}
        >
          {loop.steps.map((child, ci) =>
            renderStepRow(child, {
              numberLabel: `${index + 1}.${ci + 1}`,
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

          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', pt: 0.5 }}>
            {STEP_TYPES.map((t) => (
              <Button
                key={t}
                size="small"
                variant="text"
                startIcon={<AddIcon />}
                disabled={!h.isControlActive}
                onClick={() => h.addStepInLoop(loop.id, t)}
              >
                {QUICK_STEP_TYPE_LABELS[t]}
              </Button>
            ))}
          </Stack>
        </Stack>
      </Paper>
    );
  };

  return (
    <BuilderPageLayout>
      {/* Top bar — the SAME shared header as TestCaseBuilder/CampaignBuilder
          (uniform look & feel across builders). QuickTest has no AI mode,
          undo/redo or Versions, so those slots are simply omitted. */}
      <TestCaseBuilderHeader
        actualMode={actualMode}
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
      />

      {/* Saved quick tests rail + step list — same "rail beside editor" layout as Virtual Scripts. */}
      <Box sx={{ flex: 1, minHeight: 0, display: 'flex', gap: 1, p: 1, overflow: 'hidden' }}>
        <Paper sx={{ width: 230, display: 'flex', flexDirection: 'column' }}>
          <Box sx={{ p: 1, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
            <Typography variant="subtitle2">Saved tests</Typography>
            {h.isLoadingTestCases && <CircularProgress size={14} />}
          </Box>
          <Divider />
          <List dense disablePadding sx={{ overflow: 'auto', flex: 1 }}>
            {h.testcaseList.map((tc) => (
              <ListItem
                key={tc.testcase_id}
                disablePadding
                secondaryAction={
                  <IconButton
                    edge="end"
                    size="small"
                    color="error"
                    onClick={() => h.handleDelete(tc.testcase_id)}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                }
              >
                <Tooltip title={tc.testcase_name} placement="right" enterDelay={400}>
                  <ListItemButton
                    selected={tc.testcase_id === h.currentTestcaseId}
                    onClick={() => h.handleLoad(tc.testcase_id)}
                  >
                    <ListItemText
                      primary={tc.testcase_name}
                      secondary={[tc.userinterface_name, tc.variant].filter(Boolean).join(' · ') || undefined}
                      primaryTypographyProps={{ noWrap: true }}
                      secondaryTypographyProps={{ noWrap: true }}
                    />
                  </ListItemButton>
                </Tooltip>
              </ListItem>
            ))}
            {!h.isLoadingTestCases && h.testcaseList.length === 0 && (
              <Typography variant="caption" sx={{ p: 2, display: 'block', color: 'text.secondary' }}>
                No saved quick tests yet.
              </Typography>
            )}
          </List>
        </Paper>

        <Box sx={{ flex: 1, overflow: 'auto' }}>
        <Box sx={{ maxWidth: 1000, mx: 'auto', p: 2 }}>
          <TextField
            variant="standard"
            fullWidth
            placeholder="Untitled quick test"
            value={h.testcaseName}
            onChange={(e) => h.setTestcaseName(e.target.value)}
            InputProps={{ disableUnderline: false, sx: { fontSize: '1.25rem', fontWeight: 500 } }}
            sx={{ mb: 2 }}
          />

          {/* Input variables — make the test a reusable template. Also auto-
              populated when a step references an unknown {name}. */}
          <QuickTestInputsBar
            inputs={h.inputs}
            referencedNames={h.referencedNames}
            navNodes={h.navNodes}
            onAdd={h.addInput}
            onUpdate={h.updateInput}
            onRemove={h.removeInput}
            disabled={!h.isControlActive}
          />

          <Stack spacing={1.5}>
            {h.units.map((unit, index) =>
              isQuickLoop(unit)
                ? renderLoop(unit, index)
                : renderStepRow(unit, {
                    numberLabel: String(index + 1),
                    inLoop: false,
                    onUp: () => h.moveStep(unit.id, -1),
                    onDown: () => h.moveStep(unit.id, 1),
                    upDisabled: index === 0,
                    downDisabled: index === h.units.length - 1,
                  }),
            )}
          </Stack>

          {/* Add step — enabled only once a device is under control */}
          <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: 'wrap', alignItems: 'center' }}>
            {STEP_TYPES.map((t) => (
              <Button
                key={t}
                size="small"
                variant="outlined"
                startIcon={<AddIcon />}
                disabled={!h.isControlActive}
                onClick={() => h.addStep(t)}
              >
                {QUICK_STEP_TYPE_LABELS[t]}
              </Button>
            ))}
            <Box sx={{ flex: 1 }} />
            <Button
              size="small"
              variant="outlined"
              color="primary"
              startIcon={<LoopIcon />}
              onClick={h.addLoop}
              title="Add a loop, then add steps inside it to repeat them"
            >
              Loop
            </Button>
            {!h.isControlActive && (
              <Typography variant="caption" color="text.secondary" sx={{ ml: 1, width: '100%' }}>
                Select a user interface and take control to add steps
              </Typography>
            )}
          </Stack>
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

const QuickTestBuilder: React.FC = () => (
  <NavigationConfigProvider>
    <DeviceDataProvider>
      <QuickTestBuilderContent />
    </DeviceDataProvider>
  </NavigationConfigProvider>
);

export default QuickTestBuilder;
