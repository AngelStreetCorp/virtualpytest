import { useState, useEffect, useRef } from 'react';

import { buildServerUrl } from '../utils/buildUrlUtils';
import { api } from '../utils/apiClient';

interface ScriptParameter {
  name: string;
  type: 'positional' | 'optional';
  required: boolean;
  help: string;
  default?: string;
  choices?: string[];
  dataType?: string;
  description?: string;
}

interface ScriptAnalysis {
  success: boolean;
  parameters: ScriptParameter[];
  script_name: string;
  has_parameters: boolean;
  error?: string;
  has_userinterface_param?: boolean;
  userinterface_param?: string;
}

interface UseRunParams {
  selectedScript: string;
  selectedDevice: string;
  selectedHost: string;
  showWizard: boolean;
  // When the selected executable is a DB-stored virtual script, analyze its
  // source via virtual_script_id instead of looking for a disk file.
  virtualScriptId?: string;
}

export const useRun = ({ selectedScript, selectedDevice, selectedHost, showWizard, virtualScriptId }: UseRunParams) => {
  const [scriptAnalysis, setScriptAnalysis] = useState<ScriptAnalysis | null>(null);
  const [parameterValues, setParameterValues] = useState<Record<string, string>>({});
  const [analyzingScript, setAnalyzingScript] = useState<boolean>(false);
  
  // Deduplication protection for script analysis
  const isAnalysisInProgress = useRef(false);
  const currentAnalysisKey = useRef<string | null>(null);

  // Get default value for parameter
  const getDefaultParameterValue = (param: ScriptParameter): string => {
    // userinterface_name should be selected via UserinterfaceSelector component
    // based on device model compatibility - don't auto-populate here
    if (param.name === 'device') {
      return selectedDevice || '';
    } else if (param.name === 'host') {
      return selectedHost || '';
    } else if (param.name === 'goto_live') {
      return 'true';  // Default value for goto_live parameter
    } else if (param.default) {
      // Use the script's defined default value (e.g., 'info' for get_info.py, 'home' for goto.py)
      return param.default;
    }
    return '';
  };

  // Analyze script parameters when script selection changes
  useEffect(() => {
    const analyzeScript = async () => {
      if (!selectedScript || !showWizard) {
        setScriptAnalysis(null);
        setParameterValues({});
        return;
      }

      // Create analysis key for deduplication (only script matters for analysis)
      const analysisKey = selectedScript;
      
      // Deduplication protection - prevent duplicate analysis requests
      if (isAnalysisInProgress.current && currentAnalysisKey.current === analysisKey) {
        console.log(`[useRun] Script analysis already in progress for ${analysisKey}, ignoring duplicate request`);
        return;
      }

      // Mark analysis as in progress
      isAnalysisInProgress.current = true;
      currentAnalysisKey.current = analysisKey;

      // Skip analysis for AI test cases - they have predefined parameters
      if (selectedScript.startsWith('ai_testcase_')) {
        // AI test cases have standard parameters: userinterface_name --host --device
        const aiAnalysis: ScriptAnalysis = {
          success: true,
          script_name: selectedScript,
          parameters: [
            {
              name: 'userinterface_name',
              type: 'positional',
              required: true,
              help: 'User interface name (e.g., example_mobile)',
              default: undefined
            },
            {
              name: 'host',
              type: 'optional',
              required: true,
              help: 'Host name',
              default: undefined
            },
            {
              name: 'device',
              type: 'optional', 
              required: true,
              help: 'Device ID',
              default: undefined
            }
          ],
          has_parameters: true,
          has_userinterface_param: true,
          userinterface_param: 'userinterface_name'
        };
        
        setScriptAnalysis(aiAnalysis);
        setAnalyzingScript(false);
        return;
      }

      setAnalyzingScript(true);
      try {
        const analysis: ScriptAnalysis = await api.post(buildServerUrl('/server/script/analyze'), {
          script_name: selectedScript,
          ...(virtualScriptId ? { virtual_script_id: virtualScriptId } : {}),
        });

        if (analysis.success) {
          setScriptAnalysis(analysis);

          // Pre-fill parameter values with smart defaults
          const newParameterValues: Record<string, string> = {};
          analysis.parameters.forEach((param) => {
            newParameterValues[param.name] = getDefaultParameterValue(param);
          });
          setParameterValues(newParameterValues);
        } else {
          setScriptAnalysis(null);
          setParameterValues({});
        }
      } catch (error) {
        console.error('Error analyzing script:', error);
        setScriptAnalysis(null);
        setParameterValues({});
      } finally {
        setAnalyzingScript(false);
        // Clear deduplication flags
        isAnalysisInProgress.current = false;
        currentAnalysisKey.current = null;
      }
    };

    analyzeScript();
  }, [selectedScript, showWizard, virtualScriptId]); // Re-analyze when script, wizard visibility, or virtual id changes

  // Update parameter values when device/host changes
  useEffect(() => {
    if (scriptAnalysis) {
      const updatedValues = { ...parameterValues };
      
      scriptAnalysis.parameters.forEach((param) => {
        // userinterface_name handled by UserinterfaceSelector - don't auto-update
        if (param.name === 'device') {
          updatedValues[param.name] = selectedDevice || '';
        } else if (param.name === 'host') {
          updatedValues[param.name] = selectedHost || '';
        }
      });
      
      setParameterValues(updatedValues);
    }
  }, [selectedDevice, selectedHost, scriptAnalysis]);

  const handleParameterChange = (paramName: string, value: string) => {
    setParameterValues((prev) => ({
      ...prev,
      [paramName]: value,
    }));
  };

  const validateParameters = () => {
    if (!scriptAnalysis) return { valid: true, errors: [] };

    const errors: string[] = [];

    scriptAnalysis.parameters.forEach((param) => {
      const value = parameterValues[param.name]?.trim();
      if (param.required && !value) {
        errors.push(`${param.name} is required`);
      }
    });

    return { valid: errors.length === 0, errors };
  };

  return {
    scriptAnalysis,
    parameterValues,
    analyzingScript,
    handleParameterChange,
    validateParameters,
  };
};
