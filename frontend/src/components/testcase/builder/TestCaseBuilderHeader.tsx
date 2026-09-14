import React from 'react';
import { Box, Button, Typography, CircularProgress } from '@mui/material';
import SaveIcon from '@mui/icons-material/Save';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import AddIcon from '@mui/icons-material/Add';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import HistoryIcon from '@mui/icons-material/History';
import { UserinterfaceSelector } from '../../common/UserinterfaceSelector';
import { NavigationEditorDeviceControls } from '../../navigation/Navigation_NavigationEditor_DeviceControls';
import { UndoRedoDiscardButtons } from '../../common/UndoRedoDiscardButtons';
import { RunButton } from './RunButton';

interface TestCaseBuilderHeaderProps {
  // Theme
  actualMode: 'light' | 'dark';

  // Builder Type (for display) — the SHARED header for TestCase / Campaign /
  // QuickTest, so all builders get the same look & feel.
  builderType?: string;

  // Creation Mode toggle (Visual/AI) — optional; hidden when setCreationMode
  // is not provided (e.g. QuickTest has no AI mode).
  creationMode?: 'visual' | 'ai';
  setCreationMode?: (mode: 'visual' | 'ai') => void;
  
  // Device & Host
  selectedHost: any;
  selectedDeviceId: string | null;
  isControlActive: boolean;
  isControlLoading: boolean;
  isRemotePanelOpen: boolean;
  availableHosts: any[];
  isDeviceLocked: (deviceKey: string) => boolean;
  handleDeviceSelect: (host: any, deviceId: string) => void;
  handleDeviceControl: (host: any, deviceId: string) => void;
  handleToggleRemotePanel: () => void;
  
  // Interface
  compatibleInterfaceNames: string[];
  userinterfaceName: string;
  setUserinterfaceName: (name: string) => void;
  isLoadingTree?: boolean; // Tree loading state for button disable
  // Optional extra control rendered right after the interface selector
  // (e.g. QuickTest's VariantSelector).
  interfaceExtra?: React.ReactNode;
  
  // Test Case
  testcaseName: string;
  hasUnsavedChanges: boolean;
  
  // Actions
  handleNew: () => void;
  // Optional — omit along with hideLoad for a builder that shows its saved
  // items elsewhere (e.g. QuickTest's sidebar rail instead of a Load dialog).
  handleLoadClick?: () => Promise<void>;
  isLoadingTestCases?: boolean;
  // Hides the Load button entirely (e.g. QuickTest's sidebar rail replaces it).
  hideLoad?: boolean;
  setSaveDialogOpen: (open: boolean) => void;
  // Optional Save click override (e.g. QuickTest saves directly when the test
  // already has a name, else opens the save dialog). Defaults to opening the
  // save dialog.
  onSave?: () => void;
  // Versions button renders only when handleOpenVersions is provided.
  handleOpenVersions?: () => void;
  isVersionsEnabled?: boolean;
  handleExecute: () => void;
  // Optional override for the Save button's disabled state + tooltip (e.g.
  // QuickTest disables on empty step list instead of hasUnsavedChanges).
  saveDisabled?: boolean;
  saveTitle?: string;
  // Save-in-flight — swaps the Save icon for a spinner and blocks re-clicks
  // (e.g. QuickTest's direct-save path, which has no dialog to show progress).
  isSaving?: boolean;

  // Execution State
  isExecuting: boolean;
  isExecutable: boolean;

  // Undo/Redo/Discard — optional; rendered only when `undo` is provided.
  undo?: () => void;
  redo?: () => void;
  canUndo?: boolean;
  canRedo?: boolean;
  resetBuilder?: () => void;
  copyBlock?: () => void;
  pasteBlock?: () => void;
  
  // Progress Bar Control
  onCloseProgressBar?: () => void;
}

export const TestCaseBuilderHeader: React.FC<TestCaseBuilderHeaderProps> = ({
  actualMode,
  builderType = 'TestCase', // Default to TestCase for backward compatibility
  creationMode,
  setCreationMode,
  selectedHost,
  selectedDeviceId,
  isControlActive,
  isControlLoading,
  isRemotePanelOpen,
  availableHosts,
  isDeviceLocked,
  handleDeviceSelect,
  handleDeviceControl,
  handleToggleRemotePanel,
  compatibleInterfaceNames,
  userinterfaceName,
  setUserinterfaceName,
  isLoadingTree = false,
  interfaceExtra,
  onSave,
  testcaseName,
  hasUnsavedChanges,
  handleNew,
  handleLoadClick,
  isLoadingTestCases = false,
  hideLoad = false,
  setSaveDialogOpen,
  handleOpenVersions,
  isVersionsEnabled = false,
  handleExecute,
  saveDisabled,
  saveTitle,
  isSaving = false,
  isExecuting,
  isExecutable,
  onCloseProgressBar,
  undo,
  redo = () => {},
  canUndo = false,
  canRedo = false,
  resetBuilder = () => {},
}) => {
  const interfaceDropdownStyles = {
    select: {
      height: 32,
      fontSize: '0.75rem',
      '& .MuiSelect-select': {
        display: 'flex',
        alignItems: 'center',
      },
    },
  };

  return (
    <Box
      sx={{
        px: 2,
        py: 0,
        borderBottom: 1,
        borderColor: 'divider',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: actualMode === 'dark' ? '#111827' : '#ffffff',
        height: '46px',
        flexShrink: 0,
      }}
    >
      {/* SECTION 1: Title + Visual/AI Mode Toggle */}
      <Box sx={{ display: 'flex', alignItems: 'center', minWidth: 0, flex: '0 0 auto', gap: 1 }}>
        <Typography variant="h6" fontWeight="bold" sx={{ whiteSpace: 'nowrap' }}>
          {builderType}
        </Typography>
        {testcaseName && (
          <>
            <Typography variant="h6" sx={{ color: 'text.disabled' }}>
              •
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              {hasUnsavedChanges && (
                <Typography
                  variant="h6"
                  sx={{
                    color: '#f97316', // orange
                    fontWeight: 700,
                  }}
                >
                  *
                </Typography>
              )}
              <Typography
                variant="h6"
                sx={{
                  fontWeight: hasUnsavedChanges ? 700 : 600,
                  color: hasUnsavedChanges ? '#f97316' : 'primary.main',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  maxWidth: 200,
                }}
              >
                {testcaseName}
              </Typography>
            </Box>
          </>
        )}
        {setCreationMode && (
          <>
            <Button
              size="small"
              variant={creationMode === 'visual' ? 'contained' : 'outlined'}
              onClick={() => {
                onCloseProgressBar?.();
                setCreationMode('visual');
              }}
              sx={{ fontSize: 11, py: 0.5, px: 1.5, ml: 1 }}
            >
              Visual
            </Button>
            <Button
              size="small"
              variant={creationMode === 'ai' ? 'contained' : 'outlined'}
              onClick={() => {
                onCloseProgressBar?.();
                setCreationMode('ai');
              }}
              startIcon={<AutoAwesomeIcon fontSize="small" />}
              sx={{ fontSize: 11, py: 0.5, px: 1.5 }}
            >
              AI
            </Button>
          </>
        )}
      </Box>

      {/* SECTION 2: Device Control + Interface Selector */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: '0 0 auto', ml: 2, borderLeft: 1, borderColor: 'divider', pl: 2 }}>
        <NavigationEditorDeviceControls
          selectedHost={selectedHost}
          selectedDeviceId={selectedDeviceId}
          isControlActive={isControlActive}
          isControlLoading={isControlLoading}
          isRemotePanelOpen={isRemotePanelOpen}
          availableHosts={availableHosts}
          isDeviceLocked={isDeviceLocked}
          onDeviceSelect={handleDeviceSelect as any}
          onTakeControl={handleDeviceControl as any}
          onToggleRemotePanel={handleToggleRemotePanel}
          disableTakeControl={!userinterfaceName || isLoadingTree}
          middleContent={
            <>
              <UserinterfaceSelector
                compatibleInterfaces={compatibleInterfaceNames}
                value={userinterfaceName}
                onChange={setUserinterfaceName}
                label="Interface"
                size="small"
                fullWidth={false}
                sx={{ minWidth: 180 }}
                dropdownStyles={interfaceDropdownStyles}
                disabled={!selectedDeviceId}
              />
              {interfaceExtra}
            </>
          }
        />
      </Box>
      
      {/* SECTION 4: Action Buttons */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0, flex: '0 0 auto', ml: 2 }}>
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          {/* Undo/Redo/Discard Buttons — only for builders that support them */}
          {undo && (
            <UndoRedoDiscardButtons
              onUndo={undo}
              onRedo={redo}
              onDiscard={resetBuilder}
              canUndo={canUndo}
              canRedo={canRedo}
              hasUnsavedChanges={hasUnsavedChanges}
              size="small"
            />
          )}

          <Button 
            size="small" 
            variant="outlined" 
            startIcon={<AddIcon />} 
            onClick={() => {
              onCloseProgressBar?.();
              handleNew();
            }}
            disabled={!selectedDeviceId || !isControlActive || !userinterfaceName}
            title={
              !selectedDeviceId ? 'Select a device first' :
              !isControlActive ? 'Take control of device first' :
              !userinterfaceName ? 'Select a userinterface first' : 
              `Create new ${builderType.toLowerCase()}`
            }
          >
            New
          </Button>
          {!hideLoad && (
            <Button
              size="small"
              variant="outlined"
              startIcon={isLoadingTestCases ? <CircularProgress size={16} /> : <FolderOpenIcon />}
              onClick={async () => {
                onCloseProgressBar?.();
                await handleLoadClick?.();
              }}
              disabled={!selectedDeviceId || !isControlActive || isLoadingTestCases}
              title={
                !selectedDeviceId ? 'Select a device first' :
                !isControlActive ? 'Take control of device first' :
                isLoadingTestCases ? 'Loading test cases...' :
                'Load saved test case'
              }
            >
              {isLoadingTestCases ? 'Load...' : 'Load'}
            </Button>
          )}
          {handleOpenVersions && (
            <Button
              size="small"
              variant="outlined"
              startIcon={<HistoryIcon />}
              onClick={() => {
                onCloseProgressBar?.();
                handleOpenVersions();
              }}
              disabled={!isVersionsEnabled}
              title={isVersionsEnabled ? `${builderType} version history` : `Save ${builderType.toLowerCase()} first`}
            >
              Versions
            </Button>
          )}
          <Button
            size="small"
            variant="outlined"
            startIcon={isSaving ? <CircularProgress size={14} /> : <SaveIcon />}
            onClick={() => {
              onCloseProgressBar?.();
              if (onSave) {
                onSave();
              } else {
                setSaveDialogOpen(true);
              }
            }}
            disabled={isSaving || (saveDisabled ?? (!userinterfaceName || !hasUnsavedChanges))}
            title={
              isSaving ? 'Saving...' :
              saveTitle ?? (
                !userinterfaceName ? 'Select a userinterface first' :
                !hasUnsavedChanges ? 'No unsaved changes' :
                'Save test case'
              )
            }
          >
            {isSaving ? 'Saving...' : 'Save'}
          </Button>
          
          <RunButton
            onExecute={() => {
              onCloseProgressBar?.();
              handleExecute();
            }}
            isExecuting={isExecuting}
            isExecutable={isExecutable}
            selectedDeviceId={selectedDeviceId}
            isControlActive={isControlActive}
            userinterfaceName={userinterfaceName}
          />
        </Box>
      </Box>
    </Box>
  );
};
