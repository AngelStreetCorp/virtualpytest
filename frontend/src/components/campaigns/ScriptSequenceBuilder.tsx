/**
 * Script Sequence Builder Component
 *
 * Manages the ordered list of scripts/testcases in a campaign. Each row is an
 * Accordion: the summary mirrors RunTests' Selected Items chip + name + actions,
 * and the expanded body edits the script's pre-configured parameters using the
 * same <ScriptParameterRow> the runtime editor uses — so the dropdowns
 * (userinterface, variant, edge, node, choices, bool, password) stay identical.
 */

import React, { useState } from 'react';
import {
  Box,
  Typography,
  Button,
  Card,
  CardContent,
  IconButton,
  TextField,
  Chip,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  DialogTitle,
  DialogContent,
  DialogActions,
  Stack,
} from '@mui/material';
import {
  Add as AddIcon,
  Delete as DeleteIcon,
  ExpandMore as ExpandMoreIcon,
  ArrowUpward as ArrowUpwardIcon,
  ArrowDownward as ArrowDownwardIcon,
} from '@mui/icons-material';
import { ScriptConfiguration } from '../../types/pages/Campaign_Types';
import { ScriptParameterRow } from '../common/ParameterInput/ScriptParameterRow';
import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { getScriptDisplayName, isAIScript } from '../../utils/executionUtils';
import { UnifiedExecutableSelector, ExecutableItem } from '../common/UnifiedExecutableSelector';
import { StyledDialog } from '../common/StyledDialog';

// Framework parameters are configured at runtime, not at campaign-build time.
const FRAMEWORK_PARAMS = ['host', 'device'];

interface ScriptSequenceBuilderProps {
  scripts: ScriptConfiguration[];
  availableScripts: string[];
  aiTestCasesInfo?: any[];
  scriptAnalysisCache: { [scriptName: string]: any };
  deviceModel?: string; // Forwarded to UserinterfaceSelector for compat filtering
  userinterfaceName?: string; // No longer used — siblings drive cascading selectors via script.parameters
  hostName?: string;
  onAddScript: (executableId: string, executableType?: 'script' | 'testcase', executableName?: string) => void;
  onRemoveScript: (index: number) => void;
  onMoveScript?: (fromIndex: number, toIndex: number) => void;
  onUpdateScript: (index: number, updates: Partial<ScriptConfiguration>) => void;
  onLoadScriptAnalysis: (scriptName: string) => Promise<any>;
  hideAddButton?: boolean;
  matchRunTestsStyle?: boolean;
}

export const ScriptSequenceBuilder: React.FC<ScriptSequenceBuilderProps> = ({
  scripts,
  aiTestCasesInfo = [],
  scriptAnalysisCache,
  deviceModel,
  onAddScript,
  onRemoveScript,
  onMoveScript,
  onUpdateScript,
  onLoadScriptAnalysis,
  hideAddButton = false,
  matchRunTestsStyle = false,
}) => {
  const [addScriptDialogOpen, setAddScriptDialogOpen] = useState(false);
  const [selectedExecutableToAdd, setSelectedExecutableToAdd] = useState<ExecutableItem | null>(null);
  const [expandedScript, setExpandedScript] = useState<string | false>(false);
  // Declared input variables per testcase_id (non-protected scriptConfig.inputs),
  // fetched lazily when a testcase row expands. null = load failed / none.
  const [testcaseInputsCache, setTestcaseInputsCache] = useState<Record<string, any[] | null>>({});

  const loadTestcaseInputs = async (testcaseId: string) => {
    if (testcaseId in testcaseInputsCache) return;
    try {
      const data = await api.get<any>(buildServerUrl(`/server/testcase/${testcaseId}`));
      const inputs = (data?.testcase?.graph_json?.scriptConfig?.inputs || []).filter(
        (input: any) => input && !input.protected,
      );
      setTestcaseInputsCache((prev) => ({ ...prev, [testcaseId]: inputs }));
    } catch (e) {
      console.warn(`[@ScriptSequenceBuilder] Failed to load testcase ${testcaseId} inputs:`, e);
      setTestcaseInputsCache((prev) => ({ ...prev, [testcaseId]: null }));
    }
  };

  const handleAddScript = () => {
    if (selectedExecutableToAdd) {
      onAddScript(
        selectedExecutableToAdd.id,
        selectedExecutableToAdd.type,
        selectedExecutableToAdd.name,
      );
      setSelectedExecutableToAdd(null);
      setAddScriptDialogOpen(false);
    }
  };

  const handleScriptParameterChange = (scriptIndex: number, paramName: string, value: string) => {
    const currentScript = scripts[scriptIndex];
    const updatedParameters = {
      ...currentScript.parameters,
      [paramName]: value,
    };
    onUpdateScript(scriptIndex, { parameters: updatedParameters });
  };

  // Testcase input values: empty means "use the testcase's own default", so the
  // key is removed rather than stored as ''.
  const handleTestcaseInputChange = (scriptIndex: number, inputName: string, value: string) => {
    const currentScript = scripts[scriptIndex];
    const updatedParameters = { ...currentScript.parameters };
    if (value === '') {
      delete updatedParameters[inputName];
    } else {
      updatedParameters[inputName] = value;
    }
    onUpdateScript(scriptIndex, { parameters: updatedParameters });
  };

  const handleClearAll = () => {
    [...scripts]
      .map((_, index) => index)
      .sort((a, b) => b - a)
      .forEach((index) => onRemoveScript(index));
  };

  const handleAccordionChange = (scriptId: string, scriptName: string, testcaseId?: string) => (_event: React.SyntheticEvent, isExpanded: boolean) => {
    setExpandedScript(isExpanded ? scriptId : false);
    if (!isExpanded) return;
    if (testcaseId) {
      void loadTestcaseInputs(testcaseId);
    } else if (!scriptAnalysisCache[scriptName]) {
      onLoadScriptAnalysis(scriptName);
    }
  };

  const renderScriptParameters = (script: ScriptConfiguration, scriptIndex: number) => {
    if (script.script_type === 'testcase') {
      const testcaseId = script.testcase_id;
      const declaredInputs = testcaseId ? testcaseInputsCache[testcaseId] : undefined;
      return (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          {/* Per-row values for the testcase's input variables — this is how ONE
              testcase template runs N times in a campaign with different params.
              Empty = the testcase's own default. */}
          {declaredInputs === undefined && testcaseId ? (
            <Typography variant="caption" color="text.secondary">
              Loading testcase inputs…
            </Typography>
          ) : declaredInputs && declaredInputs.length > 0 ? (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, alignItems: 'center', pt: 0.5 }}>
              {declaredInputs.map((input: any) => (
                <TextField
                  key={input.name}
                  size="small"
                  label={input.name}
                  required={input.required}
                  value={script.parameters?.[input.name] ?? ''}
                  placeholder={
                    input.default != null && String(input.default) !== ''
                      ? `default: ${input.default}`
                      : undefined
                  }
                  onChange={(e) => handleTestcaseInputChange(scriptIndex, input.name, e.target.value)}
                  InputLabelProps={{ style: { fontSize: '0.75rem' } }}
                  inputProps={{ style: { fontSize: '0.75rem' } }}
                  sx={{ width: 200 }}
                />
              ))}
            </Box>
          ) : (
            <Typography variant="caption" color="text.secondary">
              This testcase declares no input variables.
            </Typography>
          )}
          <Typography variant="caption" color="text.secondary">
            Values can also reference previous script outputs:
          </Typography>
          <Box sx={{
            p: 1,
            bgcolor: 'background.default',
            borderRadius: 1,
            fontFamily: 'monospace',
            fontSize: '0.75rem',
          }}>
            <div>{'${previous.output_name}'} — get from previous script</div>
            <div>{'${script_1.output_name}'} — get from script #1</div>
          </Box>
        </Box>
      );
    }

    const analysis = scriptAnalysisCache[script.script_name];
    if (!analysis) {
      return (
        <Typography variant="caption" color="text.secondary">
          Loading parameters...
        </Typography>
      );
    }
    if (!analysis.parameters) {
      return (
        <Typography variant="caption" color="text.secondary">
          No parameters available for this script
        </Typography>
      );
    }

    const displayParameters = analysis.parameters.filter((param: any) =>
      !FRAMEWORK_PARAMS.includes(param.name),
    );
    if (displayParameters.length === 0) {
      return (
        <Typography variant="caption" color="text.secondary">
          No configurable parameters for this script
        </Typography>
      );
    }

    const scriptName = (script.script_name || '').replace(/\.py$/, '');

    return (
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, alignItems: 'center', pt: 0.5 }}>
        {displayParameters.map((param: any) => (
          <ScriptParameterRow
            key={param.name}
            param={param}
            value={script.parameters?.[param.name] ?? param.default ?? ''}
            onChange={(value) => handleScriptParameterChange(scriptIndex, param.name, value)}
            allValues={script.parameters || {}}
            scriptName={scriptName}
            deviceModel={deviceModel}
          />
        ))}
      </Box>
    );
  };

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant={matchRunTestsStyle ? 'subtitle1' : 'h6'}>
          {matchRunTestsStyle ? 'Selected Items' : `Script Sequence (${scripts.length} scripts)`}
        </Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          {scripts.length > 0 ? (
            <Typography
              variant="caption"
              color="error.main"
              sx={{ cursor: 'pointer', fontWeight: 500 }}
              onClick={handleClearAll}
            >
              delete all
            </Typography>
          ) : null}
          {!hideAddButton ? (
            <Button
              variant="outlined"
              startIcon={<AddIcon />}
              onClick={() => setAddScriptDialogOpen(true)}
              size="small"
            >
              Add Script
            </Button>
          ) : null}
        </Box>
      </Box>

      {scripts.length === 0 ? (
        <Card
          variant="outlined"
          sx={matchRunTestsStyle ? { minHeight: 88, display: 'flex', alignItems: 'center' } : undefined}
        >
          <CardContent sx={{ textAlign: 'center', py: 4 }}>
            <Typography variant="body2" color="text.secondary">
              No scripts added yet. Click the + button to add one.
            </Typography>
          </CardContent>
        </Card>
      ) : (
        <Stack spacing={matchRunTestsStyle ? 0.5 : 1} sx={matchRunTestsStyle ? { minHeight: 88 } : undefined}>
          {scripts.map((script, index) => {
            const scriptId = `${script.script_name}-${script.order}`;
            const displayName = getScriptDisplayName(script.script_name, aiTestCasesInfo);
            const isTestcase = script.script_type === 'testcase';
            const isExpanded = expandedScript === scriptId;

            if (matchRunTestsStyle) {
              return (
                <Accordion
                  key={scriptId}
                  expanded={isExpanded}
                  onChange={handleAccordionChange(scriptId, script.script_name, script.testcase_id)}
                  disableGutters
                  elevation={0}
                  sx={{
                    border: 1,
                    borderColor: 'divider',
                    borderRadius: 1,
                    '&:before': { display: 'none' },
                  }}
                >
                  <AccordionSummary
                    expandIcon={<ExpandMoreIcon sx={{ fontSize: 18 }} />}
                    sx={{
                      minHeight: 34,
                      px: 1,
                      py: 0,
                      '& .MuiAccordionSummary-content': { my: 0.25 },
                      '&.Mui-expanded': { minHeight: 34 },
                      '& .MuiAccordionSummary-content.Mui-expanded': { my: 0.25 },
                    }}
                  >
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, width: '100%' }}>
                      <Chip
                        label={isTestcase ? 'TC' : 'S'}
                        size="small"
                        color={isTestcase ? 'secondary' : 'primary'}
                        sx={{ height: '16px', fontSize: '0.6rem', minWidth: '24px', flexShrink: 0 }}
                      />
                      <Typography
                        variant="body2"
                        sx={{
                          fontWeight: 600,
                          fontSize: '0.82rem',
                          flex: 1,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {displayName}
                      </Typography>
                      {onMoveScript ? (
                        <>
                          <IconButton
                            size="small"
                            onClick={(e) => { e.stopPropagation(); onMoveScript(index, index - 1); }}
                            disabled={index === 0}
                            sx={{ p: 0.25 }}
                          >
                            <ArrowUpwardIcon sx={{ fontSize: 14 }} />
                          </IconButton>
                          <IconButton
                            size="small"
                            onClick={(e) => { e.stopPropagation(); onMoveScript(index, index + 1); }}
                            disabled={index === scripts.length - 1}
                            sx={{ p: 0.25 }}
                          >
                            <ArrowDownwardIcon sx={{ fontSize: 14 }} />
                          </IconButton>
                        </>
                      ) : null}
                      <IconButton
                        size="small"
                        color="error"
                        onClick={(e) => { e.stopPropagation(); onRemoveScript(index); }}
                        sx={{ p: 0.25 }}
                      >
                        <DeleteIcon sx={{ fontSize: 16 }} />
                      </IconButton>
                    </Box>
                  </AccordionSummary>
                  <AccordionDetails sx={{ px: 1, pt: 0.5, pb: 1 }}>
                    <Stack spacing={1}>
                      <TextField
                        label="Description"
                        value={script.description || ''}
                        onChange={(e) => onUpdateScript(index, { description: e.target.value })}
                        size="small"
                        fullWidth
                        placeholder="Optional description for this script execution..."
                        InputLabelProps={{ style: { fontSize: '0.75rem' } }}
                        inputProps={{ style: { fontSize: '0.75rem' } }}
                      />
                      {renderScriptParameters(script, index)}
                    </Stack>
                  </AccordionDetails>
                </Accordion>
              );
            }

            return (
              <Accordion
                key={scriptId}
                expanded={isExpanded}
                onChange={handleAccordionChange(scriptId, script.script_name, script.testcase_id)}
                elevation={0}
              >
                <AccordionSummary expandIcon={<ExpandMoreIcon sx={{ fontSize: 18 }} />}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, width: '100%', mr: 2 }}>
                    <Chip label={`${index + 1}`} size="small" color="primary" sx={{ minWidth: 32 }} />
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: 1, minWidth: 0 }}>
                      <Typography variant="body1">{displayName}</Typography>
                      {isTestcase ? <Chip label="TestCase" size="small" color="primary" /> : null}
                      {isAIScript(script.script_name) ? <Chip label="AI" size="small" color="primary" /> : null}
                    </Box>
                    <IconButton
                      size="small"
                      onClick={(e) => { e.stopPropagation(); onRemoveScript(index); }}
                    >
                      <DeleteIcon />
                    </IconButton>
                  </Box>
                </AccordionSummary>
                <AccordionDetails>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <TextField
                      label="Description"
                      value={script.description || ''}
                      onChange={(e) => onUpdateScript(index, { description: e.target.value })}
                      size="small"
                      fullWidth
                      placeholder="Optional description for this script execution..."
                    />
                    <Box>
                      <Typography variant="subtitle2" gutterBottom={false} sx={{ mb: 0.75 }}>
                        Parameters
                      </Typography>
                      {renderScriptParameters(script, index)}
                    </Box>
                  </Box>
                </AccordionDetails>
              </Accordion>
            );
          })}
        </Stack>
      )}

      <StyledDialog
        open={addScriptDialogOpen}
        onClose={() => setAddScriptDialogOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>Add Script or Test Case to Campaign</DialogTitle>
        <DialogContent sx={{ minHeight: 400 }}>
          <UnifiedExecutableSelector
            value={selectedExecutableToAdd}
            onChange={setSelectedExecutableToAdd}
            label="Select Script or Test Case"
            placeholder="Search by name..."
            filters={{ folders: true, tags: true, search: true }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddScriptDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleAddScript}
            variant="contained"
            disabled={!selectedExecutableToAdd}
          >
            Add to Campaign
          </Button>
        </DialogActions>
      </StyledDialog>
    </Box>
  );
};
