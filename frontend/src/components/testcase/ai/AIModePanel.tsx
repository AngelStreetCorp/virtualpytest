import React from 'react';
import { Alert, Box, Typography, TextField, Button, ToggleButton, ToggleButtonGroup } from '@mui/material';
import { AIEditControls } from '../../../hooks/testcase/useAIGraphEdit';
import { AIEditPreview } from './AIEditPreview';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import VisibilityIcon from '@mui/icons-material/Visibility';
import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../../constants/typography';

interface AIModePanelProps {
  aiPrompt?: string;
  setAiPrompt?: (prompt: string) => void;
  isGenerating?: boolean;
  handleGenerateWithAI?: () => void;
  hasLastGeneration?: boolean;
  handleShowLastGeneration?: () => void;
  isControlActive?: boolean;
  /** "Edit open graph": change the canvas' step-list graph by prompt (TASK-36 §3). */
  aiEdit?: AIEditControls;
}

export const AIModePanel: React.FC<AIModePanelProps> = ({
  aiPrompt = '',
  setAiPrompt = () => {},
  isGenerating = false,
  handleGenerateWithAI = () => {},
  hasLastGeneration = false,
  handleShowLastGeneration = () => {},
  isControlActive = true,
  aiEdit,
}) => {
  const editing = aiEdit?.mode === 'edit';
  const P = useAgentChatPalette();
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, p: 1.5, flex: 1, overflowY: 'auto' }}>
      <Typography variant="subtitle2" fontWeight="bold">
        AI Test Generator
      </Typography>
      {aiEdit && (
        <ToggleButtonGroup
          size="small"
          exclusive
          fullWidth
          value={aiEdit.mode}
          onChange={(_, mode) => mode && aiEdit.setMode(mode)}
          disabled={isGenerating || aiEdit.isEditing}
        >
          <ToggleButton value="new" sx={{ fontSize: TYPOGRAPHY.microMeta.size }}>New graph</ToggleButton>
          <ToggleButton value="edit" sx={{ fontSize: TYPOGRAPHY.microMeta.size }}>Edit open graph</ToggleButton>
        </ToggleButtonGroup>
      )}
      <TextField
        multiline
        rows={6}
        placeholder={
          !isControlActive
            ? "Take control of the device first to enter a prompt"
            : editing
            ? "e.g., Add a check that the cart icon is shown"
            : "e.g., Go to live TV and verify audio is playing"
        }
        value={aiPrompt}
        onChange={(e) => setAiPrompt(e.target.value)}
        size="small"
        fullWidth
        disabled={!isControlActive || isGenerating || !!aiEdit?.isEditing}
      />
      
      {/* Action Buttons */}
      {editing && aiEdit ? (
        <>
          <Button
            variant="contained"
            startIcon={<AutoAwesomeIcon />}
            onClick={aiEdit.propose}
            disabled={!isControlActive || aiEdit.isEditing || !aiPrompt.trim()}
            fullWidth
            size="small"
          >
            {aiEdit.isEditing ? 'Editing...' : 'Edit'}
          </Button>
          {aiEdit.error && <Alert severity="warning" onClose={aiEdit.cancel}>{aiEdit.error}</Alert>}
          {aiEdit.proposal && (
            <AIEditPreview proposal={aiEdit.proposal} onApply={aiEdit.apply} onCancel={aiEdit.cancel} />
          )}
        </>
      ) : (
      <Box sx={{ display: 'flex', gap: 1 }}>
        <Button
          variant="contained"
          startIcon={<AutoAwesomeIcon />}
          onClick={handleGenerateWithAI}
          disabled={!isControlActive || isGenerating || !aiPrompt.trim()}
          fullWidth
          size="small"
        >
          {isGenerating ? 'Generating...' : 'Generate'}
        </Button>
        
        {hasLastGeneration && (
          <Button
            variant="outlined"
            startIcon={<VisibilityIcon />}
            onClick={handleShowLastGeneration}
            size="small"
            sx={{ minWidth: '120px' }}
          >
            View Last
          </Button>
        )}
      </Box>
      )}
      
      {/* Sample prompts */}
      <Box sx={{ mt: 1 }}>
        <Typography variant="caption" fontWeight="bold" color="text.secondary">
          Examples:
        </Typography>
        {[
          'Go to live TV and check audio',
          'Navigate to settings',
          'Play first recording'
        ].map((example, idx) => (
          <Typography
            key={idx}
            variant="caption"
            sx={{
              display: 'block',
              mt: 0.5,
              cursor: 'pointer',
              color: P.accentText,
              '&:hover': { textDecoration: 'underline' }
            }}
            onClick={() => setAiPrompt(example)}
          >
            • {example}
          </Typography>
        ))}
      </Box>
    </Box>
  );
};

