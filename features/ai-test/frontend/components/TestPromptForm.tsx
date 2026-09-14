import React, { useMemo } from 'react';
import {
  Box,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Button,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import { TestPromptFormState } from '../types/TestPrompt_Types';
import { AGENT_CHAT_PALETTE as P } from '../../../../frontend/src/constants/agentChatTheme';

interface TestPromptFormProps {
  formState: TestPromptFormState;
  updateFormField: <K extends keyof TestPromptFormState>(field: K, value: TestPromptFormState[K]) => void;
  navNodes: any[];
  isControlActive: boolean;
  isFormValid: boolean;
  isExecuting: boolean;
  onRun: () => void;
}

export const TestPromptForm: React.FC<TestPromptFormProps> = ({
  formState,
  updateFormField,
  navNodes,
  isControlActive,
  isFormValid,
  isExecuting,
  onRun,
}) => {
  const disabled = !isControlActive;

  const screenOptions = useMemo(() => {
    return navNodes
      .filter((n: any) => (n.id || n.node_id) && (n.label || n.data?.label))
      .map((n: any) => ({ id: n.id || n.node_id, label: n.label || n.data.label }));
  }, [navNodes]);

  const handleScreenChange = (nodeId: string) => {
    const node = screenOptions.find(s => s.id === nodeId);
    updateFormField('targetScreenNodeId', nodeId);
    updateFormField('targetScreenLabel', node?.label || '');
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, p: 2, opacity: disabled ? 0.5 : 1, pointerEvents: disabled ? 'none' : 'auto' }}>
      {/* Row 1: Name + Target Screen */}
      <Box sx={{ display: 'flex', gap: 1.5 }}>
        <TextField
          label="Name"
          value={formState.name}
          onChange={e => updateFormField('name', e.target.value)}
          size="small"
          sx={{ flex: 1 }}
          placeholder="e.g. Home Validation"
        />
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel>Target Screen</InputLabel>
          <Select
            value={formState.targetScreenNodeId}
            label="Target Screen"
            onChange={e => handleScreenChange(e.target.value)}
          >
            <MenuItem value=""><em>None</em></MenuItem>
            {screenOptions.map(s => (
              <MenuItem key={s.id} value={s.id}>{s.label}</MenuItem>
            ))}
          </Select>
        </FormControl>
      </Box>

      {/* Row 2: Prompt + Acceptance Criteria side by side */}
      <Box sx={{ display: 'flex', gap: 1.5 }}>
        <TextField
          label="Prompt"
          value={formState.prompt}
          onChange={e => updateFormField('prompt', e.target.value)}
          multiline
          minRows={2}
          maxRows={6}
          sx={{ flex: 1 }}
          placeholder="What the AI should do...&#10;e.g. Go to home, check the tvguide section"
        />
        <TextField
          label="Acceptance Criteria"
          value={formState.acceptanceCriteria}
          onChange={e => updateFormField('acceptanceCriteria', e.target.value)}
          multiline
          minRows={2}
          maxRows={6}
          sx={{ flex: 1 }}
          placeholder="How to confirm it passed...&#10;e.g. Live TV visible, no error popup"
        />
      </Box>

      {/* Row 3: Run button */}
      <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button
          variant="contained"
          startIcon={<PlayArrowIcon />}
          onClick={onRun}
          disabled={!isFormValid || isExecuting}
          sx={{ px: 3, bgcolor: P.accent, color: '#000', '&:hover': { bgcolor: P.accentHover }, '&.Mui-disabled': { bgcolor: P.surface, color: P.textMuted } }}
        >
          {isExecuting ? 'Running...' : 'Run'}
        </Button>
      </Box>
    </Box>
  );
};
