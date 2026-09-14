/**
 * TestCase Toolbox Component
 * 
 * Left sidebar toolbox for the testcase builder.
 * Uses shared toolbox components for consistency with CampaignToolbox.
 */

import React, { useState, useMemo, useEffect } from 'react';
import { Box, Typography } from '@mui/material';
import { ScriptIOSections } from './ScriptIOSections';
import { useTestCaseBuilder } from '../../../contexts/testcase/TestCaseBuilderContext';
import { useReactFlow } from 'reactflow';

// Shared builder components
import {
  ToolboxSearchBox,
  ToolboxMainTabs,
  ToolboxMainTabValue,
  DraggableCommand,
} from '../../common/builder';

interface TestCaseToolboxProps {
  toolboxConfig: any;
  onCloseProgressBar?: () => void;
  selectedHost?: any;
  selectedDeviceId?: string | null;
  userinterfaceName?: string;
}

export const TestCaseToolbox: React.FC<TestCaseToolboxProps> = ({ 
  toolboxConfig,
  onCloseProgressBar,
  selectedHost,
  selectedDeviceId,
  userinterfaceName: userinterface
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [activeMainTab, setActiveMainTab] = useState<ToolboxMainTabValue>('blocks');
  const reactFlowInstance = useReactFlow();

  // Access Script I/O state from context
  const {
    scriptInputs,
    setScriptInputs,
    scriptOutputs,
    setScriptOutputs,
    scriptVariables,
    setScriptVariables,
    scriptMetadata,
    setScriptMetadata,
  } = useTestCaseBuilder();

  // Initialize default inputs from take control data
  useEffect(() => {
    const hostName = selectedHost?.host_name || '';
    const deviceName = selectedDeviceId || '';
    const userinterfaceName = userinterface || '';
    const selectedDevice = selectedHost?.devices?.find((d: any) => d.device_id === selectedDeviceId);
    const deviceModelName = selectedDevice?.device_model || '';

    const hasHostInput = scriptInputs.some(input => input.name === 'host_name');
    const hasDeviceInput = scriptInputs.some(input => input.name === 'device_name');
    const hasUserinterfaceInput = scriptInputs.some(input => input.name === 'userinterface_name');
    const hasDeviceModelInput = scriptInputs.some(input => input.name === 'device_model_name');

    const defaultInputs = [];
    
    if (!hasHostInput) {
      defaultInputs.push({
        name: 'host_name',
        type: 'string',
        required: true,
        protected: true,
        default: hostName,
      });
    }
    
    if (!hasDeviceInput) {
      defaultInputs.push({
        name: 'device_name',
        type: 'string',
        required: true,
        protected: true,
        default: deviceName,
      });
    }
    
    if (!hasDeviceModelInput) {
      defaultInputs.push({
        name: 'device_model_name',
        type: 'string',
        required: true,
        protected: true,
        default: deviceModelName,
      });
    }
    
    if (!hasUserinterfaceInput) {
      defaultInputs.push({
        name: 'userinterface_name',
        type: 'string',
        required: true,
        protected: true,
        default: userinterfaceName,
      });
    }

    if (defaultInputs.length > 0) {
      setScriptInputs([...defaultInputs, ...scriptInputs]);
    } else {
      const updatedInputs = scriptInputs.map(input => {
        if (input.name === 'host_name' && input.protected) {
          return { ...input, default: hostName };
        }
        if (input.name === 'device_name' && input.protected) {
          return { ...input, default: deviceName };
        }
        if (input.name === 'userinterface_name' && input.protected) {
          return { ...input, default: userinterfaceName };
        }
        if (input.name === 'device_model_name' && input.protected) {
          return { ...input, default: deviceModelName };
        }
        return input;
      });
      
      const hasChanged = updatedInputs.some((input, idx) => 
        input.default !== scriptInputs[idx].default
      );
      
      if (hasChanged) {
        setScriptInputs(updatedInputs);
      }
    }
  }, [selectedHost, selectedDeviceId, userinterface, scriptInputs.length]);

  // Handle null/undefined toolboxConfig
  if (!toolboxConfig || typeof toolboxConfig !== 'object') {
    return null;
  }

  // Filter toolbox config based on search term
  const filteredToolboxConfig = useMemo(() => {
    if (!searchTerm.trim()) {
      return toolboxConfig;
    }

    const searchLower = searchTerm.toLowerCase().trim();
    const filtered: any = {};

    Object.keys(toolboxConfig).forEach((tabKey) => {
      const tabConfig = toolboxConfig[tabKey];
      const filteredGroups = tabConfig.groups
        .map((group: any) => ({
          ...group,
          commands: group.commands.filter((command: any) => 
            (command.label || '').toLowerCase().includes(searchLower) ||
            (command.description || '').toLowerCase().includes(searchLower) ||
            (command.type || '').toLowerCase().includes(searchLower)
          )
        }))
        .filter((group: any) => group.commands.length > 0);

      if (filteredGroups.length > 0) {
        filtered[tabKey] = {
          ...tabConfig,
          groups: filteredGroups
        };
      }
    });

    return filtered;
  }, [toolboxConfig, searchTerm]);
  
  // I/O Section Handlers
  const handleAddInput = () => {
    const newInput = { name: `input_${scriptInputs.length + 1}`, type: 'string', required: false };
    setScriptInputs([...scriptInputs, newInput]);
  };
  
  const handleAddOutput = () => {
    const newOutput = { name: `output_${scriptOutputs.length + 1}`, type: 'string' };
    setScriptOutputs([...scriptOutputs, newOutput]);
  };
  
  const handleAddVariable = () => {
    const newVariable = { name: `var_${scriptVariables.length + 1}`, type: 'string' };
    setScriptVariables([...scriptVariables, newVariable]);
  };
  
  const handleAddMetadataField = () => {
    const newField = { name: `field_${scriptMetadata.length + 1}` };
    setScriptMetadata([...scriptMetadata, newField]);
  };
  
  const handleRemoveInput = (name: string) => {
    setScriptInputs(scriptInputs.filter(input => input.name !== name));
  };
  
  const handleRemoveOutput = (name: string) => {
    setScriptOutputs(scriptOutputs.filter(output => output.name !== name));
  };
  
  const handleRemoveVariable = (name: string) => {
    setScriptVariables(scriptVariables.filter((variable: any) => variable.name !== name));
  };
  
  const handleRemoveMetadataField = (name: string) => {
    setScriptMetadata(scriptMetadata.filter(field => field.name !== name));
  };
  
  const handleFocusSourceBlock = (blockId: string) => {
    const node = reactFlowInstance?.getNode(blockId);
    if (node && reactFlowInstance) {
      reactFlowInstance.setCenter(node.position.x + 100, node.position.y + 50, { zoom: 1.5, duration: 800 });
    }
  };

  // Calculate totals
  const totalBlocks = useMemo(() => {
    if (!toolboxConfig) return 0;
    return Object.values(toolboxConfig).reduce((total: number, tab: any) => {
      return total + (tab.groups?.reduce((sum: number, g: any) => sum + g.commands.length, 0) || 0);
    }, 0);
  }, [toolboxConfig]);

  const totalConfig = scriptInputs.length + scriptOutputs.length + scriptVariables.length + scriptMetadata.length;

  return (
    <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Main Tab Selector - Shared Component */}
      <ToolboxMainTabs
        activeTab={activeMainTab}
        onTabChange={setActiveMainTab}
        blocksCount={totalBlocks}
        configCount={totalConfig}
      />

      {/* BLOCKS TAB CONTENT */}
      {activeMainTab === 'blocks' && (
        <>
          <ToolboxSearchBox
            value={searchTerm}
            onChange={setSearchTerm}
            placeholder="Search commands..."
          />

          <Box sx={{ flex: 1, overflowY: 'auto', p: 0.5 }}>
            {Object.keys(filteredToolboxConfig).length === 0 ? (
              <Box sx={{ p: 2, textAlign: 'center' }}>
                <Typography variant="caption" color="text.secondary">
                  {searchTerm ? `No commands found for "${searchTerm}"` : 'No commands available'}
                </Typography>
              </Box>
            ) : (
              // The toolbox now offers a handful of GENERIC blocks (one per
              // category), so they render directly draggable — no accordion to
              // expand first. Each DraggableCommand carries its own accent +
              // label and is dropped straight onto the canvas.
              <>
                {Object.keys(filteredToolboxConfig).map((tabKey) => {
                  const tabConfig = filteredToolboxConfig[tabKey];
                  return tabConfig.groups.map((group: any, groupIdx: number) =>
                    group.commands.map((command: any, cmdIdx: number) => (
                      <DraggableCommand
                        key={`${tabKey}-${groupIdx}-${cmdIdx}`}
                        command={command}
                        onCloseProgressBar={onCloseProgressBar}
                      />
                    )),
                  );
                })}
              </>
            )}
          </Box>
        </>
      )}

      {/* CONFIG TAB CONTENT */}
      {activeMainTab === 'config' && (
        <Box sx={{ flex: 1, overflowY: 'auto' }}>
          <ScriptIOSections
            inputs={scriptInputs}
            outputs={scriptOutputs}
            variables={scriptVariables}
            metadata={scriptMetadata}
            onAddInput={handleAddInput}
            onAddOutput={handleAddOutput}
            onAddVariable={handleAddVariable}
            onAddMetadataField={handleAddMetadataField}
            onRemoveInput={handleRemoveInput}
            onRemoveOutput={handleRemoveOutput}
            onRemoveVariable={handleRemoveVariable}
            onRemoveMetadataField={handleRemoveMetadataField}
            onFocusSourceBlock={handleFocusSourceBlock}
            onUpdateOutputs={setScriptOutputs}
            onUpdateVariables={setScriptVariables}
            onUpdateMetadata={setScriptMetadata}
          />
        </Box>
      )}
    </Box>
  );
};
