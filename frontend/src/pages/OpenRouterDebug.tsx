import {
  SmartToy as AIIcon,
  Send as SendIcon,
  Clear as ClearIcon,
} from '@mui/icons-material';
import {
  Box,
  Button,
  Card,
  CardContent,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  TextField,
  Typography,
  CircularProgress,
  Divider,
} from '@mui/material';
import React, { useState, useRef, useEffect } from 'react';

import { buildServerUrl } from '../utils/buildUrlUtils';
import { useToast } from '../hooks/useToast';

interface LogEntry {
  timestamp: string;
  level: 'info' | 'error' | 'success';
  source: 'frontend' | 'server' | 'host';
  message: string;
}

const OpenRouterDebug: React.FC = () => {
  // State
  const [selectedModel, setSelectedModel] = useState('qwen/qwen-2.5-vl-7b-instruct');
  const [selectedTemplate, setSelectedTemplate] = useState('ai_central_format');
  const [prompt, setPrompt] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);

  // Refs
  const logsEndRef = useRef<HTMLDivElement>(null);

  // Hooks
  const toast = useToast();

  // Available models
  const models = [
    { value: 'qwen/qwen-2.5-vl-7b-instruct', label: 'Qwen 2.5 VL 7B (Default)' },
    { value: 'microsoft/phi-3-mini-128k-instruct', label: 'Microsoft Phi-3 Mini 128K' },
    { value: 'deepseek/deepseek-chat', label: 'DeepSeek Chat' },
  ];

  // Available prompt templates
  const promptTemplates = [
    {
      value: 'ai_central_format',
      label: 'AI Central Format (Current)',
      template: `You are controlling a TV application on a device (android_mobile).
Your task is to navigate through the app using available commands provided.

Task: "go to live"
Device: android_mobile

Navigation: Nodes label used to navigate in app with navigation function
['ENTRY', 'home', 'home_tvguide', 'live_fullscreen', 'live', 'home_movies', 'home_replay', 'home_saved', 'tvguide_livetv', 'live_fullscreen_audiomenu', 'live_fullscreen_chup', 'live_fullscreen_chdown', 'live_chup', 'live_chdown', 'live_volumeup', 'live_volumedown', 'live_audiomenu']

Action: Actions available to control the device
click_element(remote): Click UI element, press_key(remote): Press keyboard key

Verification: Verification available to check the device
waitForImageToAppear(verification_image): Wait for image to appear on screen

Rules:
- "go to node X" → execute_navigation, target_node="X"
- "click X" → click_element, element_id="X"  
- "press X" → press_key, key="X"
- PRIORITIZE navigation over manual actions
- ALWAYS specify action_type in params

CRITICAL: You MUST include an "analysis" field explaining your reasoning.

Example response format:
{"analysis": "Task requires navigating to live content. Since 'live' node is available, I'll navigate there directly.", "feasible": true, "plan": [{"step": 1, "command": "execute_navigation", "params": {"target_node": "live", "action_type": "navigation"}, "description": "Navigate to live content"}]}

If task is not possible:
{"analysis": "Task cannot be completed because the requested node does not exist in the navigation tree.", "feasible": false, "plan": []}

RESPOND WITH JSON ONLY. ANALYSIS FIELD IS REQUIRED`
    },
    {
      value: 'legacy_format',
      label: 'Legacy Format (Old)',
      template: `You are controlling a TV application on a device (STB/mobile/PC).
Your task is to navigate through the app using available commands provided.

Task: "go to live"
Device: android_mobile
Nodes: ["ENTRY", "home", "home_tvguide", "live_fullscreen", "live", "home_movies", "home_replay", "home_saved", "tvguide_livetv", "live_fullscreen_audiomenu", "live_fullscreen_chup", "live_fullscreen_chdown", "live_chup", "live_chdown", "live_volumeup", "live_volumedown", "live_audiomenu"]

Commands: ["execute_navigation", "click_element", "press_key", "wait"]

Rules:
- "go to node X" → execute_navigation, target_node="X"
- "click X" → click_element, element_id="X"
- "press X" → press_key, key="X"

CRITICAL: You MUST include an "analysis" field explaining your reasoning.

Example response format:
{"analysis": "Task requires navigating to live content. Since live node is available, I will navigate there directly.", "feasible": true, "plan": [{"step": 1, "command": "execute_navigation", "params": {"target_node": "live"}, "description": "Navigate to live content"}]}

If task is not possible:
{"analysis": "Task cannot be completed because the requested node does not exist in the navigation tree.", "feasible": false, "plan": []}

RESPOND WITH JSON ONLY. ANALYSIS FIELD IS REQUIRED`
    },
    {
      value: 'complex_navigation',
      label: 'Complex Navigation Test',
      template: `You are controlling a TV application on a device (android_mobile).
Your task is to navigate through the app using available commands provided.

Task: "go to live fullscreen and change channel up"
Device: android_mobile

Navigation: Nodes label used to navigate in app with navigation function
['ENTRY', 'home', 'home_tvguide', 'live_fullscreen', 'live', 'home_movies', 'home_replay', 'home_saved', 'tvguide_livetv', 'live_fullscreen_audiomenu', 'live_fullscreen_chup', 'live_fullscreen_chdown', 'live_chup', 'live_chdown', 'live_volumeup', 'live_volumedown', 'live_audiomenu']

Action: Actions available to control the device
click_element(remote): Click UI element, press_key(remote): Press keyboard key, press_key(remote): Press CHANNEL_UP key

Verification: Verification available to check the device
waitForImageToAppear(verification_image): Wait for image to appear on screen

Rules:
- "go to node X" → execute_navigation, target_node="X"
- "click X" → click_element, element_id="X"  
- "press X" → press_key, key="X"
- PRIORITIZE navigation over manual actions
- ALWAYS specify action_type in params

CRITICAL: You MUST include an "analysis" field explaining your reasoning.

Example response format:
{"analysis": "Task requires navigating to live fullscreen then changing channel. I'll navigate to live_fullscreen_chup node directly.", "feasible": true, "plan": [{"step": 1, "command": "execute_navigation", "params": {"target_node": "live_fullscreen_chup", "action_type": "navigation"}, "description": "Navigate to live fullscreen and change channel up"}]}

RESPOND WITH JSON ONLY. ANALYSIS FIELD IS REQUIRED`
    },
    {
      value: 'custom',
      label: 'Custom Prompt',
      template: ''
    }
  ];

  // Auto-scroll logs to bottom
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  // Update prompt when template changes
  useEffect(() => {
    const template = promptTemplates.find(t => t.value === selectedTemplate);
    if (template && template.template) {
      setPrompt(template.template);
    }
  }, [selectedTemplate]);

  // Initialize with default template
  useEffect(() => {
    const defaultTemplate = promptTemplates.find(t => t.value === 'ai_central_format');
    if (defaultTemplate) {
      setPrompt(defaultTemplate.template);
    }
  }, []);

  // Add log entry
  const addLog = (source: LogEntry['source'], level: LogEntry['level'], message: string) => {
    const logEntry: LogEntry = {
      timestamp: new Date().toLocaleTimeString(),
      level,
      source,
      message,
    };
    setLogs(prev => [...prev, logEntry]);
  };

  // Clear logs
  const clearLogs = () => {
    setLogs([]);
    addLog('frontend', 'info', 'Logs cleared');
  };

  // Execute OpenRouter test
  const executeTest = async () => {
    if (!prompt.trim()) {
      toast.showError('Please enter a prompt');
      return;
    }

    setIsLoading(true);
    const templateLabel = promptTemplates.find(t => t.value === selectedTemplate)?.label || selectedTemplate;
    addLog('frontend', 'info', `Starting OpenRouter test with model: ${selectedModel}`);
    addLog('frontend', 'info', `Using template: ${templateLabel}`);
    addLog('frontend', 'info', `Prompt length: ${prompt.length} characters`);

    try {
      // Call the AI utils directly through the debug endpoint
      const response = await fetch(buildServerUrl('/server/ai-tools/debug/openrouter'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model: selectedModel,
          prompt: prompt,
          max_tokens: 1000,
          temperature: 0.0,
        }),
      });

      addLog('server', 'info', `Server response status: ${response.status}`);

      const result = await response.json();
      addLog('server', 'info', `Response body: ${JSON.stringify(result)}`);
      
      if (response.ok && result.success) {
        addLog('server', 'success', 'OpenRouter call successful');
        addLog('host', 'info', `Provider used: ${result.provider_used || 'unknown'}`);
        addLog('host', 'info', `Response length: ${result.content?.length || 0} characters`);
        
        if (result.content) {
          addLog('host', 'success', `AI Response: ${result.content}`);
          
          // Try to parse as JSON to validate
          try {
            const parsed = JSON.parse(result.content);
            addLog('frontend', 'success', 'Response is valid JSON');
            addLog('frontend', 'info', `Parsed fields: ${Object.keys(parsed).join(', ')}`);
          } catch (e) {
            addLog('frontend', 'error', `Response is not valid JSON: ${e}`);
          }
        } else {
          addLog('frontend', 'error', 'Response content is empty');
        }
        
        toast.showSuccess('OpenRouter test completed successfully');
      } else {
        const errorMsg = result.error || 'Unknown error';
        addLog('server', 'error', `Server error: ${errorMsg}`);
        addLog('server', 'error', `Response OK: ${response.ok}, Result Success: ${result.success}`);
        addLog('server', 'error', `Full result: ${JSON.stringify(result)}`);
        toast.showError(`Test failed: ${errorMsg}`);
      }
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : 'Unknown error';
      addLog('frontend', 'error', `Network error: ${errorMsg}`);
      toast.showError(`Network error: ${errorMsg}`);
    } finally {
      setIsLoading(false);
    }
  };

  // Get log color based on level and source
  const getLogColor = (entry: LogEntry) => {
    if (entry.level === 'error') return '#f44336';
    if (entry.level === 'success') return '#4caf50';
    
    switch (entry.source) {
      case 'frontend': return '#2196f3';
      case 'server': return '#ff9800';
      case 'host': return '#9c27b0';
      default: return '#666';
    }
  };

  return (
    <Box sx={{ p: 3, maxWidth: 1200, mx: 'auto' }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 3 }}>
        <AIIcon sx={{ mr: 2, fontSize: 32, color: 'primary.main' }} />
        <Typography variant="h4" component="h1">
          OpenRouter
        </Typography>
      </Box>

      <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
        Test OpenRouter AI models directly with custom prompts and view detailed logs.
      </Typography>

      {/* Test Form */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2 }}>
            Test Configuration
          </Typography>

          {/* Model Selection */}
          <FormControl fullWidth sx={{ mb: 2 }}>
            <InputLabel>AI Model</InputLabel>
            <Select
              value={selectedModel}
              label="AI Model"
              onChange={(e) => setSelectedModel(e.target.value)}
              disabled={isLoading}
            >
              {models.map((model) => (
                <MenuItem key={model.value} value={model.value}>
                  {model.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          {/* Prompt Template Selection */}
          <FormControl fullWidth sx={{ mb: 2 }}>
            <InputLabel>Prompt Template</InputLabel>
            <Select
              value={selectedTemplate}
              label="Prompt Template"
              onChange={(e) => setSelectedTemplate(e.target.value)}
              disabled={isLoading}
            >
              {promptTemplates.map((template) => (
                <MenuItem key={template.value} value={template.value}>
                  {template.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          {/* Prompt Input */}
          <TextField
            label="Prompt"
            multiline
            rows={12}
            fullWidth
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={isLoading}
            sx={{ mb: 2 }}
            placeholder="Enter your prompt here..."
          />

          {/* Action Buttons */}
          <Box sx={{ display: 'flex', gap: 2 }}>
            <Button
              variant="contained"
              startIcon={isLoading ? <CircularProgress size={20} /> : <SendIcon />}
              onClick={executeTest}
              disabled={isLoading || !prompt.trim()}
              sx={{ minWidth: 120 }}
            >
              {isLoading ? 'Testing...' : 'Execute'}
            </Button>

            <Button
              variant="outlined"
              startIcon={<ClearIcon />}
              onClick={clearLogs}
              disabled={isLoading}
            >
              Clear Logs
            </Button>
          </Box>
        </CardContent>
      </Card>

      {/* Logs Display */}
      <Card>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2 }}>
            Debug Logs ({logs.length})
          </Typography>

          <Paper
            sx={{
              height: 400,
              overflow: 'auto',
              p: 2,
              backgroundColor: '#1a1a1a',
              fontFamily: 'monospace',
            }}
          >
            {logs.length === 0 ? (
              <Typography sx={{ color: '#666', fontStyle: 'italic' }}>
                No logs yet. Execute a test to see logs here.
              </Typography>
            ) : (
              logs.map((entry, index) => (
                <Box key={index} sx={{ mb: 1 }}>
                  <Typography
                    component="div"
                    sx={{
                      fontSize: '0.875rem',
                      color: getLogColor(entry),
                      fontFamily: 'monospace',
                      wordBreak: 'break-word',
                    }}
                  >
                    <Box component="span" sx={{ color: '#888' }}>
                      [{entry.timestamp}]
                    </Box>{' '}
                    <Box component="span" sx={{ fontWeight: 'bold', textTransform: 'uppercase' }}>
                      [{entry.source}]
                    </Box>{' '}
                    {entry.message}
                  </Typography>
                  {index < logs.length - 1 && (
                    <Divider sx={{ my: 0.5, borderColor: '#333' }} />
                  )}
                </Box>
              ))
            )}
            <div ref={logsEndRef} />
          </Paper>
        </CardContent>
      </Card>
    </Box>
  );
};

export default OpenRouterDebug;
