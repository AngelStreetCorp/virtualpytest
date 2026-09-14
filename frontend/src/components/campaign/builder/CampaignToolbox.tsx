/**
 * Campaign Toolbox Component
 * 
 * Left sidebar toolbox for the campaign builder.
 * Uses shared toolbox components for consistency with TestCaseToolbox.
 */

import React, { useState, useEffect, useMemo } from 'react';
import { Box, Typography, IconButton } from '@mui/material';
import { ChevronLeft as ChevronLeftIcon } from '@mui/icons-material';
import { useCampaignBuilder } from '../../../contexts/campaign/CampaignBuilderContext';
import { CampaignToolboxItem, CampaignDragData } from '../../../types/pages/CampaignGraph_Types';
import { buildServerUrl } from '../../../utils/buildUrlUtils';
import { getCachedTestCaseList } from '../../../utils/testcaseCache';
import { ScriptIOSections } from '../../testcase/builder/ScriptIOSections';
import { extractStandardBlockGroups } from '../../../utils/toolboxBuilder';

// Shared builder components
import {
  ToolboxSearchBox,
  ToolboxMainTabs,
  ToolboxMainTabValue,
  ToolboxAccordion,
  TOOLBOX_TAB_COLORS,
  DraggableToolboxItem,
  DraggableCommand,
} from '../../common/builder';

interface CampaignToolboxProps {
  actualMode: 'light' | 'dark';
  toggleSidebar: () => void;
  onDragStart?: (item: CampaignToolboxItem) => void;
  standardBlocks?: any[];
}

export const CampaignToolbox: React.FC<CampaignToolboxProps> = ({ 
  actualMode, 
  toggleSidebar, 
  onDragStart,
  standardBlocks = [],
}) => {
  const {
    campaignInputs,
    campaignOutputs,
    campaignReports,
    addCampaignInput,
    addCampaignOutput,
    addCampaignReportField,
    removeCampaignInput,
    removeCampaignOutput,
    removeCampaignReportField,
  } = useCampaignBuilder();

  // Toolbox items
  const [testCases, setTestCases] = useState<CampaignToolboxItem[]>([]);
  const [scripts, setScripts] = useState<CampaignToolboxItem[]>([]);
  
  // Search and tab state
  const [searchQuery, setSearchQuery] = useState('');
  const [activeMainTab, setActiveMainTab] = useState<ToolboxMainTabValue>('blocks');
  const [expandedTab, setExpandedTab] = useState<string | null>(null);

  // Transform standardBlocks using toolboxBuilder utility
  const standardToolboxGroups = useMemo(() => {
    if (!standardBlocks || standardBlocks.length === 0) return [];
    return extractStandardBlockGroups(standardBlocks);
  }, [standardBlocks]);

  // Load available executables
  useEffect(() => {
    loadTestCases();
    loadScripts();
  }, []);

  const loadTestCases = async () => {
    try {
      const data = await getCachedTestCaseList(buildServerUrl('/server/testcase/list'));
      
      if (!data.success || !data.testcases) {
        console.error('[@CampaignToolbox] Invalid response format:', data);
        return;
      }
      
      const items: CampaignToolboxItem[] = data.testcases.map((tc: any) => ({
        id: tc.testcase_id,
        type: 'testcase' as const,
        label: tc.testcase_name,
        icon: '🌳',
        category: 'testcases' as const,
        executableId: tc.testcase_id,
        executableType: 'testcase' as const,
        executableName: tc.testcase_name,
        description: tc.description,
        tags: tc.tags || [],
        folder: tc.folder,
      }));
      
      setTestCases(items);
      console.log('[@CampaignToolbox] Loaded testcases:', items.length);
    } catch (error) {
      console.error('[@CampaignToolbox] Error loading testcases:', error);
    }
  };

  const loadScripts = async () => {
    try {
      const apiUrl = buildServerUrl('/server/script/list');
      const response = await fetch(apiUrl);
      if (!response.ok) {
        console.error('[@CampaignToolbox] Failed to load scripts:', response.status);
        return;
      }
      
      const data = await response.json();
      if (!data.success || !data.scripts) {
        console.error('[@CampaignToolbox] Invalid response format:', data);
        return;
      }
      
      const items: CampaignToolboxItem[] = data.scripts.map((scriptName: string) => ({
        id: scriptName,
        type: 'script' as const,
        label: scriptName,
        icon: '▶️',
        category: 'scripts' as const,
        executableId: scriptName,
        executableType: 'script' as const,
        executableName: scriptName,
      }));
      
      setScripts(items);
      console.log('[@CampaignToolbox] Loaded scripts:', items.length);
    } catch (error) {
      console.error('[@CampaignToolbox] Error loading scripts:', error);
    }
  };

  // Handle drag start for toolbox items
  const handleToolboxItemDragStart = (e: React.DragEvent, item: CampaignToolboxItem) => {
    const dragData: CampaignDragData = {
      type: 'toolbox-item',
      toolboxItem: item,
    };
    e.dataTransfer.setData('application/json', JSON.stringify(dragData));
    e.dataTransfer.effectAllowed = 'copy';
    
    if (onDragStart) {
      onDragStart(item);
    }
  };

  // Handle accordion expand
  const handleExpandChange = (id: string, expanded: boolean) => {
    setExpandedTab(expanded ? id : null);
  };

  // Filter items by search
  const filterItems = (items: CampaignToolboxItem[]) => {
    if (!searchQuery) return items;
    const query = searchQuery.toLowerCase();
    return items.filter(item =>
      item.label.toLowerCase().includes(query) ||
      item.description?.toLowerCase().includes(query)
    );
  };

  const filteredTestCases = filterItems(testCases);
  const filteredScripts = filterItems(scripts);
  const isSearching = searchQuery.trim() !== '';

  // Transform campaign data to match ScriptIOSections interface
  const inputs = campaignInputs.map(input => ({
    name: input.name,
    type: input.type || 'string',
    required: false,
    default: input.defaultValue,
  }));

  const outputs = campaignOutputs.map(output => ({
    name: output.name,
    type: 'string',
  }));

  const metadata = campaignReports.fields.map(field => ({
    name: field.name,
    value: undefined,
  }));

  const variables: any[] = [];

  // I/O Section handlers
  const handleAddInput = () => {
    const name = prompt('Enter input name:');
    if (name && name.trim()) {
      addCampaignInput({ name: name.trim(), type: 'string', defaultValue: '' });
    }
  };

  const handleAddOutput = () => {
    const name = prompt('Enter output name:');
    if (name && name.trim()) {
      addCampaignOutput({ name: name.trim() });
    }
  };

  const handleAddMetadata = () => {
    const name = prompt('Enter report field name:');
    if (name && name.trim()) {
      addCampaignReportField({ name: name.trim() });
    }
  };

  const handleAddVariable = () => {
    console.log('[@CampaignToolbox] Variables not supported for campaigns');
  };

  // Calculate totals
  const totalBlocks = testCases.length + scripts.length + (standardToolboxGroups[0]?.commands?.length || 0);
  const totalConfig = inputs.length + outputs.length + metadata.length;

  return (
    <>
      {/* Sidebar Header */}
      <Box
        sx={{
          px: 2,
          py: 1.5,
          height: '40px',
          borderBottom: 1,
          borderColor: 'divider',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          background: actualMode === 'dark' ? '#1e293b' : '#ffffff',
        }}
      >
        <Typography variant="subtitle1" fontWeight="bold">
          Toolbox
        </Typography>
        <IconButton
          size="small"
          onClick={toggleSidebar}
          sx={{ color: 'text.secondary', '&:hover': { color: 'primary.main' } }}
        >
          <ChevronLeftIcon />
        </IconButton>
      </Box>

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
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="Search executables..."
          />

          <Box sx={{ flex: 1, overflowY: 'auto', p: 0.5 }}>
            {/* STANDARD Category */}
            {standardToolboxGroups && standardToolboxGroups.length > 0 && (
              <ToolboxAccordion
                id="standard"
                title="Standard"
                count={standardToolboxGroups[0]?.commands?.length || 0}
                accentColor={TOOLBOX_TAB_COLORS.standard}
                expanded={expandedTab === 'standard'}
                onExpandChange={handleExpandChange}
                forceExpanded={isSearching}
              >
                {standardToolboxGroups.map((group: any, groupIdx: number) => (
                  <React.Fragment key={`standard-group-${groupIdx}`}>
                    {standardToolboxGroups.length > 1 && (
                      <Typography 
                        fontSize={11} 
                        sx={{ color: 'text.disabled', px: 0.5, py: 0.5, mt: groupIdx > 0 ? 1 : 0 }}
                      >
                        {group.groupName}
                      </Typography>
                    )}
                    {group.commands.map((command: any, cmdIdx: number) => (
                      <DraggableCommand 
                        key={`${group.groupName}-${cmdIdx}`} 
                        command={command}
                      />
                    ))}
                  </React.Fragment>
                ))}
              </ToolboxAccordion>
            )}

            {/* TESTCASES Category */}
            <ToolboxAccordion
              id="testcases"
              title="TestCases"
              count={filteredTestCases.length}
              accentColor={TOOLBOX_TAB_COLORS.testcases}
              expanded={expandedTab === 'testcases'}
              onExpandChange={handleExpandChange}
              forceExpanded={isSearching}
            >
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                {filteredTestCases.map((item) => (
                  <DraggableToolboxItem
                    key={item.id}
                    label={item.label}
                    subtitle={item.folder}
                    accentColor={TOOLBOX_TAB_COLORS.testcases}
                    onDragStart={(e) => handleToolboxItemDragStart(e, item)}
                  />
                ))}
              </Box>
            </ToolboxAccordion>

            {/* SCRIPTS Category */}
            <ToolboxAccordion
              id="scripts"
              title="Scripts"
              count={filteredScripts.length}
              accentColor={TOOLBOX_TAB_COLORS.scripts}
              expanded={expandedTab === 'scripts'}
              onExpandChange={handleExpandChange}
              forceExpanded={isSearching}
            >
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                {filteredScripts.map((item) => (
                  <DraggableToolboxItem
                    key={item.id}
                    label={item.label}
                    accentColor={TOOLBOX_TAB_COLORS.scripts}
                    onDragStart={(e) => handleToolboxItemDragStart(e, item)}
                  />
                ))}
              </Box>
            </ToolboxAccordion>
          </Box>
        </>
      )}

      {/* CONFIG TAB CONTENT */}
      {activeMainTab === 'config' && (
        <Box sx={{ flex: 1, overflowY: 'auto' }}>
          <ScriptIOSections
            inputs={inputs}
            outputs={outputs}
            variables={variables}
            metadata={metadata}
            onAddInput={handleAddInput}
            onAddOutput={handleAddOutput}
            onAddVariable={handleAddVariable}
            onAddMetadataField={handleAddMetadata}
            onRemoveInput={removeCampaignInput}
            onRemoveOutput={removeCampaignOutput}
            onRemoveVariable={() => {}}
            onRemoveMetadataField={removeCampaignReportField}
            onFocusSourceBlock={() => {}}
            onUpdateOutputs={() => {}}
            onUpdateVariables={() => {}}
            onUpdateMetadata={() => {}}
          />
        </Box>
      )}
    </>
  );
};
