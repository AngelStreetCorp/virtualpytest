import React, { useState } from 'react';
import {
  Box,
  Typography,
  TextField,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Alert,
  CircularProgress,
  Paper,
  DialogTitle,
  DialogContent,
  DialogActions,
  List,
  ListItem,
} from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import WarningIcon from '@mui/icons-material/Warning';
import { useTestCaseBuilder } from '../../../contexts/testcase/TestCaseBuilderContext';
import { useTestCaseAI } from '../../../hooks/testcase';
import { APP_CONFIG } from '../../../config/constants';
import type { TestCaseGraph } from '../../../types/testcase/TestCase_Types';
import { StyledDialog } from '../../common/StyledDialog';

interface AIPromptModeProps {
  onGraphGenerated: (graph: TestCaseGraph, analysis: string) => void;
  onCancel: () => void;
}

export const AIPromptMode: React.FC<AIPromptModeProps> = ({ onGraphGenerated, onCancel }) => {
  const { availableInterfaces, userinterfaceName, setUserinterfaceName } = useTestCaseBuilder();
  const { generateTestCaseFromPrompt, saveDisambiguationAndRegenerate } = useTestCaseAI();
  
  const [prompt, setPrompt] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generatedGraph, setGeneratedGraph] = useState<TestCaseGraph | null>(null);
  const [analysis, setAnalysis] = useState<string>('');
  
  // Disambiguation state
  const [needsDisambiguation, setNeedsDisambiguation] = useState(false);
  const [ambiguities, setAmbiguities] = useState<any[]>([]);
  const [disambiguationSelections, setDisambiguationSelections] = useState<Record<string, string>>({});

  const handleGenerate = async () => {
    if (!prompt.trim()) {
      setError('Please enter a prompt');
      return;
    }
    
    if (!userinterfaceName) {
      setError('Please select a user interface');
      return;
    }

    setIsGenerating(true);
    setError(null);
    setGeneratedGraph(null);
    setNeedsDisambiguation(false);

    try {
      const result = await generateTestCaseFromPrompt(
        prompt,
        userinterfaceName,
        APP_CONFIG.DEFAULT_DEVICE_ID,
        APP_CONFIG.DEFAULT_TEAM_ID
      );

      if (result.needs_disambiguation) {
        // Show disambiguation UI
        setNeedsDisambiguation(true);
        setAmbiguities(result.ambiguities || []);
        setError(null);
      } else if (result.success && result.graph) {
        // Success - show generated graph
        setGeneratedGraph(result.graph);
        setAnalysis(result.analysis || '');
        setError(null);
      } else {
        // Not feasible or error
        setError(result.error || 'Generation failed');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error occurred');
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDisambiguationSave = async () => {
    // Validate all ambiguities are resolved
    const unresolvedCount = ambiguities.filter(amb => !disambiguationSelections[amb.phrase]).length;
    
    if (unresolvedCount > 0) {
      setError(`Please resolve all ${unresolvedCount} ambiguities`);
      return;
    }

    setIsGenerating(true);
    setError(null);

    try {
      const selections = Object.entries(disambiguationSelections).map(([phrase, resolved]) => ({
        phrase,
        resolved,
      }));

      const result = await saveDisambiguationAndRegenerate(
        prompt,
        selections,
        userinterfaceName,
        APP_CONFIG.DEFAULT_DEVICE_ID,
        APP_CONFIG.DEFAULT_TEAM_ID
      );

      if (result.success && result.graph) {
        setGeneratedGraph(result.graph);
        setAnalysis(result.analysis || '');
        setNeedsDisambiguation(false);
        setError(null);
      } else {
        setError(result.error || 'Regeneration failed');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error occurred');
    } finally {
      setIsGenerating(false);
    }
  };

  const handleKeepGraph = () => {
    if (generatedGraph) {
      onGraphGenerated(generatedGraph, analysis);
    }
  };

  const handleClear = () => {
    setPrompt('');
    setGeneratedGraph(null);
    setAnalysis('');
    setError(null);
    setNeedsDisambiguation(false);
    setAmbiguities([]);
    setDisambiguationSelections({});
  };

  return (
    <Box
      sx={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        p: 4,
        background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.05) 0%, rgba(168, 85, 247, 0.05) 100%)',
      }}
    >
      <Paper
        elevation={3}
        sx={{
          maxWidth: 800,
          width: '100%',
          p: 4,
          borderRadius: 3,
        }}
      >
        {/* Header */}
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 3 }}>
          <AutoAwesomeIcon sx={{ fontSize: 40, mr: 2, color: 'primary.main' }} />
          <Box>
            <Typography variant="h5" fontWeight="bold">
              AI Test Case Generator
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Describe your test in natural language
            </Typography>
          </Box>
        </Box>

        {/* Generated Graph Success */}
        {generatedGraph && (
          <Alert severity="success" icon={<CheckCircleIcon />} sx={{ mb: 3 }}>
            <Typography variant="body2" fontWeight="bold">
              Graph Generated Successfully!
            </Typography>
            <Typography variant="caption">
              {generatedGraph.nodes?.length || 0} nodes, {generatedGraph.edges?.length || 0} edges
            </Typography>
            {analysis && (
              <Typography variant="body2" sx={{ mt: 1, fontStyle: 'italic' }}>
                AI: {analysis}
              </Typography>
            )}
          </Alert>
        )}

        {/* Error */}
        {error && (
          <Alert severity="error" icon={<ErrorIcon />} sx={{ mb: 3 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Prompt Input */}
        <TextField
          label="Describe your test case"
          placeholder="e.g., Go to live TV and verify audio is playing"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          fullWidth
          multiline
          rows={4}
          sx={{ mb: 3 }}
          disabled={isGenerating}
        />

        {/* User Interface Selection */}
        <FormControl fullWidth sx={{ mb: 3 }}>
          <InputLabel>User Interface</InputLabel>
          <Select
            value={userinterfaceName}
            label="User Interface"
            onChange={(e) => setUserinterfaceName(e.target.value)}
            disabled={isGenerating}
          >
            {availableInterfaces.map((ui: any) => (
              <MenuItem key={ui.id} value={ui.userinterface_name}>
                {ui.display_name || ui.userinterface_name}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        {/* Actions */}
        <Box sx={{ display: 'flex', gap: 2, justifyContent: 'space-between' }}>
          <Button
            variant="outlined"
            onClick={generatedGraph ? handleClear : onCancel}
            disabled={isGenerating}
          >
            {generatedGraph ? 'Clear & Try Again' : 'Cancel'}
          </Button>

          {generatedGraph ? (
            <Button
              variant="contained"
              color="success"
              startIcon={<CheckCircleIcon />}
              onClick={handleKeepGraph}
              size="large"
            >
              Keep & Edit in Visual Mode
            </Button>
          ) : (
            <Button
              variant="contained"
              startIcon={<AutoAwesomeIcon />}
              onClick={handleGenerate}
              disabled={isGenerating || !prompt.trim() || !userinterfaceName}
              size="large"
            >
              {isGenerating ? <CircularProgress size={24} /> : 'Generate Test Case'}
            </Button>
          )}
        </Box>

        {/* Node Count Preview (when generating) */}
        {isGenerating && (
          <Box sx={{ mt: 3, textAlign: 'center' }}>
            <CircularProgress />
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
              AI is analyzing your prompt...
            </Typography>
          </Box>
        )}
      </Paper>

      {/* Disambiguation Dialog */}
      <StyledDialog open={needsDisambiguation} onClose={() => {}} maxWidth="md" fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center' }}>
            <WarningIcon sx={{ mr: 1, color: 'warning.main' }} />
            Disambiguation Required
          </Box>
        </DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 3 }}>
            Some terms in your prompt are ambiguous. Please select the correct navigation nodes.
          </Alert>

          <List>
            {ambiguities.map((ambiguity, index) => (
              <ListItem key={index} sx={{ flexDirection: 'column', alignItems: 'flex-start', mb: 2 }}>
                <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 1 }}>
                  "{ambiguity.phrase}" could mean:
                </Typography>
                <FormControl fullWidth>
                  <InputLabel>Select correct node</InputLabel>
                  <Select
                    value={disambiguationSelections[ambiguity.phrase] || ''}
                    label="Select correct node"
                    onChange={(e) =>
                      setDisambiguationSelections((prev) => ({
                        ...prev,
                        [ambiguity.phrase]: e.target.value,
                      }))
                    }
                  >
                    {ambiguity.candidates?.map((candidate: string) => (
                      <MenuItem key={candidate} value={candidate}>
                        {candidate}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </ListItem>
            ))}
          </List>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNeedsDisambiguation(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleDisambiguationSave}
            disabled={isGenerating}
          >
            {isGenerating ? <CircularProgress size={24} /> : 'Save & Regenerate'}
          </Button>
        </DialogActions>
      </StyledDialog>
    </Box>
  );
};

