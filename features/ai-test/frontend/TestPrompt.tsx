import React, { useMemo, useState } from 'react';
import {
  Box,
  Typography,
  Snackbar,
  Alert,
  Button,
  Chip,
  IconButton,
  InputBase,
  Tooltip,
  Divider,
  CircularProgress,
} from '@mui/material';
import SaveIcon from '@mui/icons-material/Save';
import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import StarBorderIcon from '@mui/icons-material/StarBorder';
import SearchIcon from '@mui/icons-material/Search';
import { RecHostPreview } from '../../../frontend/src/components/rec/RecHostPreview';
import { ScriptRunningOverlay } from '../../../frontend/src/components/rec/ScriptRunningOverlay';
import { UserinterfaceSelector } from '../../../frontend/src/components/common/UserinterfaceSelector';
import { NavigationEditorDeviceControls } from '../../../frontend/src/components/navigation/Navigation_NavigationEditor_DeviceControls';
import { TestPromptForm } from './components/TestPromptForm';
import { TestPromptResults } from './components/TestPromptResults';
import { NavigationConfigProvider } from '../../../frontend/src/contexts/navigation/NavigationConfigContext';
import { NavigationEditorProvider } from '../../../frontend/src/contexts/navigation/NavigationEditorProvider';
import { useTestPromptPage } from './hooks/useTestPromptPage';
import { useAgentChatPalette } from '../../../frontend/src/constants/agentChatTheme';

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

/** "4m", "2h", "3d" — age of a prompt's last edit for the sidebar. */
const formatAgo = (iso: string) => {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'now';
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
};

const TestPromptContent: React.FC = () => {
  const hookData = useTestPromptPage();
  const P = useAgentChatPalette();
  const [search, setSearch] = useState('');

  // Sidebar: prompts grouped by interface, filtered by the search box.
  const groups = useMemo(() => {
    const q = search.trim().toLowerCase();
    const byUi = new Map<string, typeof hookData.savedPrompts>();
    hookData.savedPrompts
      .filter(p => !q || p.name.toLowerCase().includes(q) || (p.userinterface_name || '').toLowerCase().includes(q))
      .forEach(p => {
        const ui = p.userinterface_name || 'No interface';
        byUi.set(ui, [...(byUi.get(ui) || []), p]);
      });
    return [...byUi.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [hookData.savedPrompts, search]);

  return (
    <Box sx={{ display: 'flex', height: '100%', bgcolor: P.background, color: P.textPrimary }}>
      {/* Sidebar */}
      <Box
        sx={{
          width: 240,
          flexShrink: 0,
          borderRight: `1px solid ${P.borderColor}`,
          display: 'flex',
          flexDirection: 'column',
          bgcolor: P.sidebarBg,
        }}
      >
        <Box sx={{ px: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'space-between', height: '46px', flexShrink: 0 }}>
          <Typography variant="subtitle2" fontWeight={600} sx={{ color: P.textPrimary }}>Test prompts</Typography>
          <Tooltip title="New prompt">
            <IconButton size="small" onClick={hookData.resetForm} sx={{ color: P.accentText, border: `1px solid ${P.borderColor}`, borderRadius: 1.5, p: 0.5 }}>
              <AddIcon sx={{ fontSize: 18 }} />
            </IconButton>
          </Tooltip>
        </Box>

        <Box sx={{ px: 1.5, pb: 1 }}>
          <InputBase
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search prompts"
            startAdornment={<SearchIcon sx={{ fontSize: 16, color: P.textMuted, mr: 0.75 }} />}
            sx={{
              width: '100%', height: 30, px: 1, fontSize: '0.8rem', color: P.textPrimary,
              bgcolor: P.inputBg, border: `1px solid ${P.borderColor}`, borderRadius: 1.5,
              '&.Mui-focused': { borderColor: P.accent },
            }}
          />
        </Box>

        {hookData.isLoadingPrompts ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={24} sx={{ color: P.accent }} />
          </Box>
        ) : hookData.savedPrompts.length === 0 ? (
          <Typography variant="body2" sx={{ color: P.textMuted, p: 2, textAlign: 'center' }}>
            No saved prompts yet
          </Typography>
        ) : groups.length === 0 ? (
          <Typography variant="body2" sx={{ color: P.textMuted, p: 2, textAlign: 'center' }}>
            No prompt matches
          </Typography>
        ) : (
          <Box sx={{ flex: 1, overflow: 'auto', px: 1, pb: 1 }}>
            {groups.map(([ui, prompts]) => (
              <Box key={ui}>
                <Typography variant="caption" noWrap sx={{ display: 'block', px: 1, pt: 1.25, pb: 0.5, fontSize: '0.68rem', color: P.textMuted }}>
                  {ui} · {prompts.length}
                </Typography>
                {prompts.map(p => {
                  const selected = hookData.currentPromptId === p.id;
                  return (
                    <Box
                      key={p.id}
                      onClick={() => hookData.handleLoad(p.id)}
                      sx={{
                        display: 'flex', alignItems: 'center', gap: 0.5, px: 1, py: 0.75, mb: 0.25,
                        borderRadius: 1.5, cursor: 'pointer',
                        bgcolor: selected ? `${P.accent}26` : 'transparent',
                        '&:hover': { bgcolor: selected ? `${P.accent}26` : P.hoverBg },
                        '&:hover .tp-delete': { opacity: 1 },
                      }}
                    >
                      <Box sx={{ minWidth: 0, flex: 1 }}>
                        <Typography noWrap sx={{ fontSize: '0.82rem', lineHeight: 1.35, fontWeight: selected ? 600 : 400, color: selected ? P.accentText : P.textPrimary }}>
                          {p.name}
                        </Typography>
                        <Typography noWrap sx={{ fontSize: '0.68rem', lineHeight: 1.3, color: P.textMuted }}>
                          <Box component="span" sx={{ color: p.mode === 'prod' ? P.gold : P.textMuted, fontWeight: p.mode === 'prod' ? 600 : 400 }}>
                            v{p.version} · {p.mode}
                          </Box>
                          {p.updated_at ? ` · ${formatAgo(p.updated_at)}` : ''}
                        </Typography>
                      </Box>
                      <Tooltip title="Delete prompt">
                        <IconButton
                          className="tp-delete"
                          size="small"
                          onClick={e => { e.stopPropagation(); hookData.handleDelete(p.id); }}
                          sx={{ p: 0.25, opacity: selected ? 1 : 0, transition: 'opacity 0.15s', color: P.textMuted, '&:hover': { color: P.error } }}
                        >
                          <DeleteOutlineIcon sx={{ fontSize: 16 }} />
                        </IconButton>
                      </Tooltip>
                    </Box>
                  );
                })}
              </Box>
            ))}
          </Box>
        )}
      </Box>

      {/* Main Content */}
      <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {/* Header Bar */}
        <Box
          sx={{
            px: 2,
            py: 0,
            borderBottom: `1px solid ${P.borderColor}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            bgcolor: P.surface,
            height: '46px',
            flexShrink: 0,
          }}
        >
          {/* Version indicators */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: '0 0 auto' }}>
            {hookData.currentPromptId && (
              <Chip
                size="small"
                label={`v${hookData.currentVersion} · ${hookData.currentMode}`}
                sx={{
                  height: 22, fontSize: '0.7rem', fontWeight: 600,
                  bgcolor: hookData.currentMode === 'prod' ? `${P.gold}22` : P.hoverBg,
                  color: hookData.currentMode === 'prod' ? P.gold : P.textSecondary,
                  border: `1px solid ${hookData.currentMode === 'prod' ? P.gold : P.borderColor}`,
                }}
              />
            )}
          </Box>

          {/* Device Control + Interface + Save + Promote */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: '0 0 auto' }}>
            <NavigationEditorDeviceControls
              selectedHost={hookData.selectedHost}
              selectedDeviceId={hookData.selectedDeviceId}
              isControlActive={hookData.isControlActive}
              isControlLoading={hookData.isControlLoading}
              isRemotePanelOpen={hookData.isRemotePanelOpen}
              availableHosts={hookData.availableHosts}
              isDeviceLocked={hookData.isDeviceLocked}
              onDeviceSelect={hookData.handleDeviceSelect as any}
              onTakeControl={hookData.handleDeviceControl as any}
              onToggleRemotePanel={hookData.handleToggleRemotePanel}
              disableTakeControl={!hookData.userinterfaceName || hookData.isLoadingTree}
              middleContent={
                <UserinterfaceSelector
                  compatibleInterfaces={hookData.compatibleInterfaceNames}
                  value={hookData.userinterfaceName}
                  onChange={hookData.setUserinterfaceName}
                  label="Interface"
                  size="small"
                  fullWidth={false}
                  sx={{ minWidth: 180 }}
                  dropdownStyles={interfaceDropdownStyles}
                  disabled={!hookData.selectedDeviceId || !!hookData.currentPromptId}
                />
              }
            />

            <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />

            <Button
              size="small"
              variant="outlined"
              startIcon={<SaveIcon />}
              onClick={hookData.handleSave}
              disabled={hookData.isSaving || !hookData.isDirty || !hookData.formState.prompt.trim()}
              title={hookData.isDirty ? 'You have unsaved changes — click to save' : 'No changes to save'}
              sx={{
                fontSize: 11,
                py: 0.5,
                px: 1.5,
                // When the form is dirty, render the button as if it were hovered
                // so the user has a clear visual cue that there are unsaved edits.
                borderColor: hookData.isDirty ? P.accent : P.borderColor,
                color: hookData.isDirty ? P.accent : P.textSecondary,
                bgcolor: hookData.isDirty ? `${P.accent}14` : 'transparent',
                '&:hover': { borderColor: P.accent, color: P.accent, bgcolor: `${P.accent}22` },
                '&.Mui-disabled': { borderColor: P.borderColor, color: P.textMuted, bgcolor: 'transparent' },
              }}
            >
              {hookData.isSaving ? 'Saving...' : 'Save'}
            </Button>

            {hookData.currentPromptId && hookData.currentMode === 'dev' && (
              <Button
                size="small"
                startIcon={<StarBorderIcon />}
                onClick={hookData.handlePromote}
                title="Promote this version to prod"
                sx={{ fontSize: 11, py: 0.5, px: 1.25, color: P.gold, '&:hover': { bgcolor: `${P.gold}1a` } }}
              >
                Promote
              </Button>
            )}
          </Box>
        </Box>

        {/* Content Area */}
        <Box sx={{ flex: 1, overflow: 'auto' }}>
          {/* Prompt when no device */}
          {!hookData.isControlActive && (
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', py: 8 }}>
              <Typography variant="body1" sx={{ color: P.textMuted }}>
                Select a device and take control to start
              </Typography>
            </Box>
          )}

          {/* Form */}
          {hookData.isControlActive && (
            <Box sx={{ m: 2, mb: 0, bgcolor: P.surface, border: `1px solid ${P.borderColor}`, borderRadius: 3 }}>
              <TestPromptForm
                formState={hookData.formState}
                updateFormField={hookData.updateFormField}
                navNodes={hookData.navNodes}
                isControlActive={hookData.isControlActive}
                isFormValid={hookData.isFormValid}
                isExecuting={hookData.isExecuting}
                runMode={hookData.runMode}
                onRunModeChange={hookData.setRunMode}
                linkedTestcase={hookData.linkedTestcase}
                onRun={hookData.handleRunTestPrompt}
                onUnlinkTestcase={hookData.handleUnlinkTestcase}
              />
            </Box>
          )}

          {/* Results */}
          {hookData.executions.length > 0 && (
            <Box sx={{ m: 2, mt: 3 }}>
              <TestPromptResults
                executions={hookData.executions}
                onSubmitFeedback={hookData.handleSubmitFeedback}
                onSaveAsTestcase={hookData.handleSaveAsTestcase}
                explorePreview={hookData.explorePreview}
                buildingFromExploreId={hookData.buildingFromExploreId}
                onProposeFromExplore={hookData.handleProposeFromExplore}
                onApplyExplorePreview={hookData.handleApplyExplorePreview}
                onCancelExplorePreview={hookData.handleCancelExplorePreview}
                liveEventsByExecutionId={hookData.liveEventsByExecutionId}
              />
            </Box>
          )}
        </Box>
      </Box>

      {/* Device stream preview — very bottom-left of window. During a run (either mode) it
          grows and carries the step overlay read from the device's running.log. */}
      {hookData.isControlActive && hookData.selectedHost && (
        <Box sx={{
          position: 'fixed',
          bottom: 4,
          left: 4,
          width: hookData.runningLogData ? 560 : 240,
          transition: 'width 0.2s',
          zIndex: 1300,
          borderRadius: 1,
          overflow: 'hidden',
          boxShadow: '0 4px 20px rgba(0,0,0,0.6)',
          border: `1px solid ${P.borderColor}`,
        }}>
          <RecHostPreview
            host={hookData.selectedHost}
            device={hookData.selectedHost.devices?.find((d: any) => d.device_id === hookData.selectedDeviceId)}
            hideHeader
          />
          {hookData.runningLogData && (
            <ScriptRunningOverlay logData={hookData.runningLogData} scriptNameRightOffset={8} />
          )}
        </Box>
      )}

      {/* Hide Ask AI button on this page */}
      <style>{`.MuiFab-root[aria-label="Ask AI"] { display: none !important; }`}</style>

      {/* Snackbar */}
      <Snackbar
        open={hookData.snackbar.open}
        autoHideDuration={4000}
        onClose={hookData.closeSnackbar}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert onClose={hookData.closeSnackbar} severity={hookData.snackbar.severity} variant="filled">
          {hookData.snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

const TestPrompt: React.FC = () => {
  return (
    <NavigationConfigProvider>
      <NavigationEditorProvider>
        <TestPromptContent />
      </NavigationEditorProvider>
    </NavigationConfigProvider>
  );
};

export default TestPrompt;
