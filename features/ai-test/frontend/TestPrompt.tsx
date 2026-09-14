import React from 'react';
import {
  Box,
  Typography,
  Snackbar,
  Alert,
  Paper,
  Button,
  Chip,
  List,
  ListItemButton,
  ListItemText,
  IconButton,
  Divider,
  CircularProgress,
} from '@mui/material';
import SaveIcon from '@mui/icons-material/Save';
import AddCircleOutlineIcon from '@mui/icons-material/AddCircleOutline';
import DeleteIcon from '@mui/icons-material/Delete';
import StarIcon from '@mui/icons-material/Star';
import { RecHostPreview } from '../../../frontend/src/components/rec/RecHostPreview';
import { UserinterfaceSelector } from '../../../frontend/src/components/common/UserinterfaceSelector';
import { NavigationEditorDeviceControls } from '../../../frontend/src/components/navigation/Navigation_NavigationEditor_DeviceControls';
import { TestPromptForm } from './components/TestPromptForm';
import { TestPromptResults } from './components/TestPromptResults';
import { NavigationConfigProvider } from '../../../frontend/src/contexts/navigation/NavigationConfigContext';
import { NavigationEditorProvider } from '../../../frontend/src/contexts/navigation/NavigationEditorProvider';
import { useTestPromptPage } from './hooks/useTestPromptPage';
import { AGENT_CHAT_PALETTE as P } from '../../../frontend/src/constants/agentChatTheme';

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

const TestPromptContent: React.FC = () => {
  const hookData = useTestPromptPage();

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
        <Box sx={{ px: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: `1px solid ${P.borderColor}`, height: '46px', flexShrink: 0 }}>
          <Typography variant="subtitle2" fontWeight={700} sx={{ color: P.textPrimary }}>Test Prompt</Typography>
          <IconButton size="small" onClick={hookData.resetForm} title="New prompt" sx={{ color: P.accent }}>
            <AddCircleOutlineIcon />
          </IconButton>
        </Box>

        {hookData.isLoadingPrompts ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={24} />
          </Box>
        ) : hookData.savedPrompts.length === 0 ? (
          <Typography variant="body2" sx={{ color: P.textMuted, p: 2, textAlign: 'center' }}>
            No saved prompts yet
          </Typography>
        ) : (
          <List dense sx={{ flex: 1, overflow: 'auto', py: 0 }}>
            {hookData.savedPrompts.map(p => (
              <ListItemButton
                key={p.id}
                selected={hookData.currentPromptId === p.id}
                onClick={() => hookData.handleLoad(p.id)}
                sx={{ py: 0.5, px: 1.5, gap: 0.5, minHeight: 36, '&:hover': { bgcolor: P.hoverBg }, '&.Mui-selected': { bgcolor: P.surface, '&:hover': { bgcolor: P.surface } } }}
              >
                <ListItemText
                  primary={<Typography variant="body2" noWrap sx={{ fontSize: '0.82rem', lineHeight: 1.3, color: P.textPrimary }}>{p.name}</Typography>}
                  secondary={p.userinterface_name}
                  secondaryTypographyProps={{ variant: 'caption', noWrap: true, sx: { fontSize: '0.68rem', lineHeight: 1.2, color: P.textMuted } }}
                  sx={{ minWidth: 0, my: 0 }}
                />
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexShrink: 0 }}>
                  <Chip
                    size="small"
                    label={`v${p.version}`}
                    variant="outlined"
                    sx={{ height: 18, fontSize: '0.65rem', borderColor: p.mode === 'prod' ? P.gold : P.borderColor, color: p.mode === 'prod' ? P.gold : P.textSecondary }}
                  />
                  <IconButton
                    size="small"
                    onClick={e => { e.stopPropagation(); hookData.handleDelete(p.id); }}
                    sx={{ p: 0.25, color: P.textMuted, '&:hover': { color: P.error } }}
                  >
                    <DeleteIcon sx={{ fontSize: 16 }} />
                  </IconButton>
                </Box>
              </ListItemButton>
            ))}
          </List>
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
              <>
                <Chip
                  size="small"
                  label={`v${hookData.currentVersion}`}
                  variant="outlined"
                  sx={{ height: 20, fontSize: '0.7rem', borderColor: P.borderColor, color: P.textSecondary }}
                />
                <Chip
                  size="small"
                  label={hookData.currentMode}
                  sx={{ height: 20, fontSize: '0.7rem', bgcolor: hookData.currentMode === 'prod' ? P.gold : P.surface, color: hookData.currentMode === 'prod' ? '#000' : P.textSecondary, borderColor: P.borderColor }}
                />
              </>
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
                variant="outlined"
                startIcon={<StarIcon />}
                onClick={hookData.handlePromote}
                sx={{ fontSize: 11, py: 0.5, px: 1.5, borderColor: P.gold, color: P.gold, '&:hover': { bgcolor: `${P.gold}22` } }}
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
            <Paper variant="outlined" sx={{ m: 2, mb: 0, bgcolor: P.surface, borderColor: P.borderColor }}>
              <TestPromptForm
                formState={hookData.formState}
                updateFormField={hookData.updateFormField}
                navNodes={hookData.navNodes}
                isControlActive={hookData.isControlActive}
                isFormValid={hookData.isFormValid}
                isExecuting={hookData.isExecuting}
                onRun={hookData.handleRunTestPrompt}
              />
            </Paper>
          )}

          {/* Results */}
          {hookData.executions.length > 0 && (
            <Box sx={{ m: 2 }}>
              <TestPromptResults
                executions={hookData.executions}
                onSubmitFeedback={hookData.handleSubmitFeedback}
                liveEventsByExecutionId={hookData.liveEventsByExecutionId}
              />
            </Box>
          )}
        </Box>
      </Box>

      {/* Device stream preview — very bottom-left of window */}
      {hookData.isControlActive && hookData.selectedHost && (
        <Box sx={{
          position: 'fixed',
          bottom: 4,
          left: 4,
          width: 240,
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
