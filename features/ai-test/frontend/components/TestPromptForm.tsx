import React, { useMemo } from 'react';
import {
  Box,
  InputBase,
  Select,
  MenuItem,
  Button,
  Chip,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import AutorenewIcon from '@mui/icons-material/Autorenew';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import { TestPromptFormState, TestPromptRunMode, LinkedTestcase } from '../types/TestPrompt_Types';
import { useAgentChatPalette } from '../../../../frontend/src/constants/agentChatTheme';
import { isFeatureEnabled } from '../../../../frontend/src/config/features';

interface TestPromptFormProps {
  formState: TestPromptFormState;
  updateFormField: <K extends keyof TestPromptFormState>(field: K, value: TestPromptFormState[K]) => void;
  navNodes: any[];
  isControlActive: boolean;
  isFormValid: boolean;
  isExecuting: boolean;
  runMode: TestPromptRunMode;
  onRunModeChange: (mode: TestPromptRunMode) => void;
  linkedTestcase: LinkedTestcase | null;
  onRun: (options?: { regenerate?: boolean }) => void;
  onUnlinkTestcase: () => void;
}

export const TestPromptForm: React.FC<TestPromptFormProps> = ({
  formState,
  updateFormField,
  navNodes,
  isControlActive,
  isFormValid,
  isExecuting,
  runMode,
  onRunModeChange,
  linkedTestcase,
  onRun,
  onUnlinkTestcase,
}) => {
  const P = useAgentChatPalette();
  const disabled = !isControlActive;

  const screenOptions = useMemo(() => {
    return navNodes
      .filter((n: any) => (n.node_id || n.id) && (n.label || n.data?.label))
      // node_id is what navigation resolves (the server's pre-navigation and the unified
      // graph); the row UUID in n.id is not found there (BUG-0226).
      .map((n: any) => ({ id: n.node_id || n.id, label: n.label || n.data.label }));
  }, [navNodes]);

  const handleScreenChange = (nodeId: string) => {
    const node = screenOptions.find(s => s.id === nodeId);
    updateFormField('targetScreenNodeId', nodeId);
    updateFormField('targetScreenLabel', node?.label || '');
  };

  // Inset field card: label on top, borderless input, gold border on focus.
  const fieldCard = {
    flex: 1, minWidth: 0, px: 1.5, py: 1, borderRadius: 2,
    bgcolor: P.sidebarBg, border: `1px solid ${P.borderColor}`,
    transition: 'border-color 0.15s',
    '&:focus-within': { borderColor: P.accent },
  };
  const fieldLabel = { display: 'block', fontSize: '0.7rem', fontWeight: 600, color: P.textSecondary, mb: 0.5 };
  const MODE_HINTS: Record<TestPromptRunMode, string> = {
    explore: 'The AI drives the device step by step and judges the criteria',
    graph: '',
    auto: '',
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, p: 2.5, opacity: disabled ? 0.5 : 1, pointerEvents: disabled ? 'none' : 'auto' }}>
      {/* Title row: name as the heading, start screen under it */}
      <Box>
        <InputBase
          value={formState.name}
          onChange={e => updateFormField('name', e.target.value)}
          placeholder="Untitled prompt"
          fullWidth
          inputProps={{ 'aria-label': 'Name' }}
          sx={{
            fontSize: '1.2rem', fontWeight: 600, color: P.textPrimary,
            borderRadius: 1, px: 0.5, mx: -0.5,
            '&:hover': { bgcolor: P.hoverBg },
            '&.Mui-focused': { bgcolor: P.hoverBg },
          }}
        />
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mt: 0.25 }}>
          <Typography sx={{ fontSize: '0.78rem', color: P.textSecondary }}>Starts on screen</Typography>
          <Select
            variant="standard"
            disableUnderline
            displayEmpty
            value={formState.targetScreenNodeId}
            onChange={e => handleScreenChange(e.target.value)}
            inputProps={{ 'aria-label': 'Target Screen' }}
            sx={{
              fontSize: '0.78rem', fontWeight: 600, color: formState.targetScreenNodeId ? P.accentText : P.textMuted,
              '& .MuiSelect-select': { py: 0.25, px: 0.75, borderRadius: 1 },
              '& .MuiSelect-select:hover': { bgcolor: P.hoverBg },
              '& .MuiSvgIcon-root': { color: P.textMuted },
            }}
          >
            <MenuItem value=""><em>any (none)</em></MenuItem>
            {screenOptions.map(s => (
              <MenuItem key={s.id} value={s.id}>{s.label}</MenuItem>
            ))}
          </Select>
        </Box>
      </Box>

      {/* Prompt + pass criteria side by side */}
      <Box sx={{ display: 'flex', gap: 1.5 }}>
        <Box sx={fieldCard}>
          <Typography component="label" htmlFor="tp-prompt" sx={fieldLabel}>Prompt</Typography>
          <InputBase
            id="tp-prompt"
            value={formState.prompt}
            onChange={e => updateFormField('prompt', e.target.value)}
            multiline
            minRows={2}
            maxRows={6}
            fullWidth
            placeholder="Go to home, check the tvguide section"
            sx={{ fontSize: '0.9rem', lineHeight: 1.5, color: P.textPrimary, p: 0 }}
          />
        </Box>
        <Box sx={fieldCard}>
          <Typography component="label" htmlFor="tp-criteria" sx={fieldLabel}>Pass when</Typography>
          <InputBase
            id="tp-criteria"
            value={formState.acceptanceCriteria}
            onChange={e => updateFormField('acceptanceCriteria', e.target.value)}
            multiline
            minRows={2}
            maxRows={6}
            fullWidth
            placeholder="Live TV visible, no error popup"
            sx={{ fontSize: '0.9rem', lineHeight: 1.5, color: P.textPrimary, p: 0 }}
          />
        </Box>
      </Box>

      {/* Row 3: run mode + Run */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
        <ToggleButtonGroup
          size="small"
          exclusive
          value={runMode}
          onChange={(_, mode) => mode && onRunModeChange(mode)}
          disabled={isExecuting}
          sx={{
            bgcolor: P.sidebarBg, p: 0.375, borderRadius: 2, gap: 0.375,
            '& .MuiToggleButton-root': {
              border: '1px solid transparent !important', borderRadius: '6px !important',
              textTransform: 'none', fontWeight: 500, color: P.textSecondary, py: 0.4,
              '&:hover': { bgcolor: P.hoverBg },
            },
            '& .MuiToggleButton-root.Mui-selected': {
              bgcolor: P.surface, color: P.accentText, fontWeight: 600,
              borderColor: `${P.borderColor} !important`,
              '&:hover': { bgcolor: P.surface },
            },
          }}
        >
          <ToggleButton value="explore" sx={{ px: 1.5, fontSize: 11 }} title="The AI agent drives the device step by step and judges the acceptance criteria">
            Explore
          </ToggleButton>
          <ToggleButton value="graph" sx={{ px: 1.5, fontSize: 11 }} title="Run the prompt as a testcase graph on the testcase executor">
            Run graph
          </ToggleButton>
          <ToggleButton value="auto" sx={{ px: 1.5, fontSize: 11 }} title="Replay the linked testcase; if it fails, explore with the AI agent. A decision model (Jev) also judges why it failed — logged only for now">
            Auto
          </ToggleButton>
        </ToggleButtonGroup>

        {MODE_HINTS[runMode] && (
          <Typography variant="caption" sx={{ color: P.textMuted }}>{MODE_HINTS[runMode]}</Typography>
        )}
        {(runMode === 'graph' || runMode === 'auto') && (linkedTestcase ? (
          <>
            <Chip
              size="small"
              label={`Replays ${linkedTestcase.name || linkedTestcase.id.slice(0, 8)}`}
              onDelete={isExecuting ? undefined : onUnlinkTestcase}
              title="Linked testcase — remove to unlink (the testcase is kept)"
              sx={{ height: 22, fontSize: '0.7rem', color: P.textSecondary, borderColor: P.borderColor }}
              variant="outlined"
            />
            <Button
              size="small"
              startIcon={<AutorenewIcon />}
              onClick={() => onRun({ regenerate: true })}
              disabled={!isFormValid || isExecuting}
              title="Generate a new graph from the prompt and run it (the linked testcase is not changed)"
              sx={{ fontSize: 11, color: P.textSecondary }}
            >
              Regenerate
            </Button>
            {/* New tab: this page keeps its Take Control. QuickTest opens linear graphs only
                and says so for others. */}
            {isFeatureEnabled('quicktest') && (
              <Button
                size="small"
                startIcon={<OpenInNewIcon />}
                href={`/builder/quick-test?testcase=${linkedTestcase.id}`}
                target="_blank"
                title="Edit the linked testcase as a step list"
                sx={{ fontSize: 11, color: P.textSecondary }}
              >
                QuickTest
              </Button>
            )}
            <Button
              size="small"
              startIcon={<OpenInNewIcon />}
              href={`/builder/test-builder?testcase=${linkedTestcase.id}`}
              target="_blank"
              title="Edit the linked testcase as a graph"
              sx={{ fontSize: 11, color: P.textSecondary }}
            >
              Test Builder
            </Button>
          </>
        ) : (
          <Typography variant="caption" sx={{ color: P.textMuted }}>
            {runMode === 'auto'
              ? 'No linked testcase yet: Auto explores. Save a run as a testcase to replay it'
              : 'Generates a graph from the prompt, then runs it — save it as a testcase to replay it'}
          </Typography>
        ))}

        <Box sx={{ flex: 1 }} />
        <Button
          variant="contained"
          startIcon={<PlayArrowIcon />}
          onClick={() => onRun()}
          disabled={!isFormValid || isExecuting}
          disableElevation
          sx={{
            px: 3, py: 0.75, borderRadius: 2, textTransform: 'none', fontWeight: 600, fontSize: '0.9rem',
            bgcolor: P.accent, color: '#1a1a1a',
            '&:hover': { bgcolor: P.accentHover },
            '&.Mui-disabled': { bgcolor: P.hoverBg, color: P.textMuted },
          }}
        >
          {isExecuting ? 'Running...' : 'Run'}
        </Button>
      </Box>
    </Box>
  );
};
