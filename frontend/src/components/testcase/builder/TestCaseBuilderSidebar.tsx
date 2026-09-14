import React from 'react';
import { Box, Typography, IconButton } from '@mui/material';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import { TestCaseToolbox } from './TestCaseToolbox';
import { AIModePanel } from '../ai/AIModePanel';

interface TestCaseBuilderSidebarProps {
  actualMode: 'light' | 'dark';
  creationMode: 'visual' | 'ai';
  isSidebarOpen: boolean;
  toggleSidebar: () => void;
  
  // Toolbox Props
  categoryTabs?: any[];
  toolboxConfig?: any;
  
  // State props for showing helpful messages
  selectedDeviceId?: string | null;
  isControlActive?: boolean;
  areActionsLoaded?: boolean;
  userinterfaceName?: string;
  selectedHost?: any; // Add selectedHost for take control data
  
  // Progress Bar Control
  onCloseProgressBar?: () => void;

  // AI Panel wiring
  aiPrompt?: string;
  setAiPrompt?: (prompt: string) => void;
  isGenerating?: boolean;
  handleGenerateWithAI?: () => void;
  hasLastGeneration?: boolean;
  handleShowLastGeneration?: () => void;
}

export const TestCaseBuilderSidebar: React.FC<TestCaseBuilderSidebarProps> = ({
  actualMode,
  creationMode,
  toggleSidebar,
  toolboxConfig,
  selectedDeviceId,
  isControlActive,
  areActionsLoaded,
  userinterfaceName,
  selectedHost,
  onCloseProgressBar,
  aiPrompt,
  setAiPrompt,
  isGenerating,
  handleGenerateWithAI,
  hasLastGeneration,
  handleShowLastGeneration,
}) => {
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
          {creationMode === 'visual' ? 'Toolbox' : 'AI Generator'}
        </Typography>
        <IconButton
          size="small"
          onClick={toggleSidebar}
          sx={{
            color: 'text.secondary',
            '&:hover': { color: 'primary.main' },
          }}
        >
          <ChevronLeftIcon />
        </IconButton>
      </Box>
      
      {/* Sidebar Content */}
      <Box sx={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {creationMode === 'visual' ? (
          toolboxConfig ? (
            <TestCaseToolbox 
              toolboxConfig={toolboxConfig} 
              onCloseProgressBar={onCloseProgressBar}
              selectedHost={selectedHost}
              selectedDeviceId={selectedDeviceId}
              userinterfaceName={userinterfaceName}
            />
          ) : (
            <Box sx={{ p: 2, textAlign: 'center'}}>
              <Typography variant="caption" fontSize={16} fontWeight="bold" color="text.secondary">
                {!selectedDeviceId 
                  ? '1. Select a device' 
                  : !isControlActive
                  ? '2. Take control'
                  : !areActionsLoaded
                  ? '3. Loading device capabilities...'
                  : !userinterfaceName 
                  ? '4. Select an interface'
                  : '5. Loading toolbox...'}
              </Typography>
            </Box>
          )
        ) : (
          <AIModePanel 
            aiPrompt={aiPrompt}
            setAiPrompt={setAiPrompt}
            isGenerating={isGenerating}
            handleGenerateWithAI={handleGenerateWithAI}
            hasLastGeneration={hasLastGeneration}
            handleShowLastGeneration={handleShowLastGeneration}
            isControlActive={isControlActive}
          />
        )}
      </Box>
    </>
  );
};

