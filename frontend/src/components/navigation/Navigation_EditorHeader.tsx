import { AppBar, Toolbar, Typography, Box, Button, CircularProgress, DialogTitle, DialogContent, DialogActions, List, ListItem, IconButton, Chip, Tooltip } from '@mui/material';
import { History as HistoryIcon, Restore as RestoreIcon, Publish as PublishIcon } from '@mui/icons-material';
import React from 'react';
import { useNavigate } from 'react-router-dom';

import { ConfirmDialog } from '../common/ConfirmDialog';
import { StyledDialog } from '../common/StyledDialog';
import { useUserInterface, clearUserInterfaceCaches } from '../../hooks/pages/useUserInterface';
import { useNavigation } from '../../contexts/navigation/NavigationContext';
import { useNavigationStack } from '../../contexts/navigation/NavigationStackContext';
import { useDeviceControlWithForceUnlock } from '../../hooks/useDeviceControlWithForceUnlock';
import { useHostControl } from '../../hooks/useHostManager';
import { useToast } from '../../hooks/useToast';
import { buildServerUrl } from '../../utils/buildUrlUtils';

import NavigationEditorActionButtons from './Navigation_NavigationEditor_ActionButtons';
import NavigationEditorDeviceControls from './Navigation_NavigationEditor_DeviceControls';
import NavigationEditorTreeControls from './Navigation_NavigationEditor_TreeControls';
import NavigationViewingScopeChip from './Navigation_ViewingScopeChip';
import LocalizeButton, { LocalizeCandidate } from './Navigation_LocalizeButton';
import { ValidationButtonClient } from '../validation';

export const NavigationEditorHeader: React.FC<{
  hasUnsavedChanges: boolean;
  focusNodeId: string | null;
  availableFocusNodes: any[];
  maxDisplayDepth: number;
  totalNodes: number;
  visibleNodes: number;
  isLoading: boolean;
  error: string | null;
  isLocked: boolean;
  treeId: string;
  selectedHost: any; // Full host object
  selectedDeviceId?: string | null; // Selected device ID
  isRemotePanelOpen: boolean;
  // Host data (filtered by interface models)
  availableHosts: any[];

  // Phase 4 §3.5 — canvas viewing scope (Base or a variant name).
  userInterfaceId?: string | null;
  viewingScope?: string | null;
  onViewingScopeChange?: (next: string | null) => void;
  // Show/hide rows disabled on the active variant (ghosted on the canvas).
  // The toggle is only meaningful in a single-variant scope and is rendered as
  // a per-variant eye inside the viewing-scope dropdown (not the toolbar).
  showDisabledOnVariant?: boolean;
  onToggleShowDisabledOnVariant?: () => void;

  onAddNewNode: () => void;
  onFitView: () => void;
  onSaveToConfig: () => void;
  onDiscardChanges: () => void;
  onFocusNodeChange: (nodeId: string | null) => void;
  onDepthChange: (depth: number) => void;
  onResetFocus: () => void;
  onToggleRemotePanel: () => void;
  onControlStateChange: (active: boolean) => void;
  onDeviceSelect: (host: any, deviceId: string | null) => void;
  onUpdateNode?: (nodeId: string, updatedData: any) => void;
  onUpdateEdge?: (edgeId: string, updatedData: any) => void;
  onToggleAIGeneration?: () => void;
}> = ({
  hasUnsavedChanges,
  focusNodeId,
  availableFocusNodes,
  maxDisplayDepth,
  totalNodes,
  visibleNodes,
  isLoading,
  error,
  isLocked,
  treeId,
  selectedHost,
  selectedDeviceId,
  isRemotePanelOpen,
  // Host data (filtered by interface models)
  availableHosts,
  userInterfaceId,
  viewingScope,
  onViewingScopeChange,
  showDisabledOnVariant,
  onToggleShowDisabledOnVariant,
  onAddNewNode,
  onFitView,
  onSaveToConfig,
  onDiscardChanges,
  onFocusNodeChange,
  onDepthChange,
  onResetFocus,
  onToggleRemotePanel,
  onControlStateChange,
  onDeviceSelect,
}) => {
  // Get toast notifications
  const { showError, showSuccess } = useToast();

  // Get navigation context for current position updates and undo/redo
  const { updateCurrentPosition, undo, redo, canUndo, canRedo, userInterface, nodes, setSelectedNode } = useNavigation();

  // Dev/prod scope. The editor shows either the dev row (editable) or its prod
  // snapshot (read-only); both share the interface name, disambiguated by mode.
  const navigateRouter = useNavigate();
  const { getUserInterfaceByName, publishUserInterface } = useUserInterface();
  const uiModeView: 'dev' | 'prod' = userInterface?.mode === 'prod' ? 'prod' : 'dev';
  const isProdView = uiModeView === 'prod';
  const [prodVersion, setProdVersion] = React.useState<number | null>(null);
  const [hasProd, setHasProd] = React.useState<boolean>(isProdView);
  const [publishConfirmOpen, setPublishConfirmOpen] = React.useState(false);
  const [publishing, setPublishing] = React.useState(false);

  React.useEffect(() => {
    if (!userInterface?.name) return;
    if (isProdView) {
      setHasProd(true);
      setProdVersion(userInterface?.published_version ?? null);
      return;
    }
    getUserInterfaceByName(userInterface.name, 'prod')
      .then((prod: any) => {
        setHasProd(true);
        setProdVersion(prod?.published_version ?? null);
      })
      .catch(() => {
        setHasProd(false);
        setProdVersion(null);
      });
  }, [userInterface?.name, userInterface?.published_version, isProdView, getUserInterfaceByName]);

  const handleToggleUiMode = () => {
    if (!userInterface?.name) return;
    if (!isProdView && hasUnsavedChanges) {
      showError('Save or discard your changes before switching to prod view');
      return;
    }
    const base = `/navigation-editor/${encodeURIComponent(userInterface.name)}`;
    navigateRouter(isProdView ? base : `${base}?mode=prod`);
  };

  const handlePublish = async () => {
    if (!userInterface?.id) return;
    try {
      setPublishing(true);
      const result = await publishUserInterface(userInterface);
      clearUserInterfaceCaches();
      setHasProd(true);
      setProdVersion(result.version);
      showSuccess(`Published "${userInterface.name}" to prod (v${result.version})`);
    } catch (e) {
      showError(e instanceof Error ? e.message : 'Failed to publish');
    } finally {
      setPublishing(false);
      setPublishConfirmOpen(false);
    }
  };

  // Version history state
  const [versionHistoryOpen, setVersionHistoryOpen] = React.useState(false);
  const [treeVersions, setTreeVersions] = React.useState<any[]>([]);
  const [loadingVersions, setLoadingVersions] = React.useState(false);
  const [restoringVersion, setRestoringVersion] = React.useState<number | null>(null);
  const [currentVersion, setCurrentVersion] = React.useState<number | null>(null);
  const [hasVersionHistory, setHasVersionHistory] = React.useState<boolean>(false);

  // Get navigation stack for breadcrumb display
  const { isNested, currentLevel } = useNavigationStack();

  // Get device locking functionality from HostManager
  const { isDeviceLocked } = useHostControl();

  // Function to reset current node ID
  const resetCurrentNodeId = React.useCallback(() => {
    console.log('[@component:NavigationEditorHeader] Resetting current node ID');
    updateCurrentPosition(null, null);
  }, [updateCurrentPosition]);

  // Enhanced reset focus handler that also resets current node ID
  const handleResetFocus = React.useCallback(() => {
    console.log('[@component:NavigationEditorHeader] Resetting focus and current node ID');
    onResetFocus(); // Reset the focus/filter
    resetCurrentNodeId(); // Reset the current node ID
  }, [onResetFocus, resetCurrentNodeId]);

  // Use shared device control hook with force unlock
  const {
    isControlActive,
    isControlLoading,
    controlError,
    handleDeviceControl,
    clearError,
    confirmDialogState,
    confirmDialogHandleConfirm,
    confirmDialogHandleCancel,
  } = useDeviceControlWithForceUnlock({
    host: selectedHost,
    device_id: selectedDeviceId || null,
    sessionId: 'navigation-editor-session',
    autoCleanup: true,
    tree_id: treeId,
    onControlStateChange: (active: boolean) => {
      onControlStateChange(active);
      if (!active) {
        resetCurrentNodeId();
      }
    },
  });

  // Show control errors
  React.useEffect(() => {
    if (controlError) {
      showError(controlError);
      clearError();
    }
  }, [controlError, showError, clearError]);

  // Debug logging for device selection changes
  React.useEffect(() => {
    if (selectedHost && selectedDeviceId) {
      const device = selectedHost.devices?.find((d: any) => d.device_id === selectedDeviceId);
      if (device) {
        console.log(
          `[@component:NavigationEditorHeader] Device selected: ${device.device_name} (${device.device_model}) on host ${selectedHost.host_name}`,
        );
      }
    }
  }, [selectedHost, selectedDeviceId]);

  // Load tree version history
  const loadVersionHistory = React.useCallback(async (showLoading: boolean = true) => {
    if (!treeId) return;

    if (showLoading) setLoadingVersions(true);
    try {
      const response = await fetch(buildServerUrl(`/server/navigationTrees/${treeId}/history`));

      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          // Only show the most recent 10 versions
          const versions = (data.versions || []).slice(0, 10);
          setTreeVersions(versions);
          // Check if we have any history (more than just the current working version)
          setHasVersionHistory(versions.length > 1); // At least 2 versions means history is available
          // Find current version (latest non-restore version)
          const current = versions.find((v: any) => v.modification_type !== 'restore');
          setCurrentVersion(current?.version_number || null);
        }
      } else {
        setHasVersionHistory(false);
        if (showLoading) showError('Failed to load version history');
      }
    } catch (error) {
      console.error('[@component:NavigationEditorHeader] Error loading version history:', error);
      setHasVersionHistory(false);
      if (showLoading) showError('Error loading version history');
    } finally {
      if (showLoading) setLoadingVersions(false);
    }
  }, [treeId, showError]);

  // Restore to a specific version. Restoring replaces the whole hierarchy and can
  // take a while on large trees — every restore icon is disabled while one runs,
  // so a second click can't launch a concurrent restore.
  const restoreVersion = React.useCallback(async (versionNumber: number) => {
    if (!treeId || restoringVersion !== null) return;
    setRestoringVersion(versionNumber);

    try {
      const response = await fetch(buildServerUrl(`/server/navigationTrees/${treeId}/restore/${versionNumber}`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        // restored_by must be a user uuid; omit it rather than send a label
        body: JSON.stringify({})
      });

      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          showSuccess(`Successfully restored to version ${versionNumber} (created version ${data.new_version})`);
          setVersionHistoryOpen(false);
          // Trigger a reload of the tree (keep buttons disabled until the reload lands)
          window.location.reload();
          return;
        }
        showError(data.error || 'Failed to restore version');
      } else {
        showError('Failed to restore version');
      }
    } catch (error) {
      console.error('[@component:NavigationEditorHeader] Error restoring version:', error);
      showError('Error restoring version');
    }
    setRestoringVersion(null);
  }, [treeId, restoringVersion, showSuccess, showError]);

  // Open version history dialog - reuse cached versions if already loaded
  const handleOpenVersionHistory = React.useCallback(() => {
    setVersionHistoryOpen(true);
    if (treeVersions.length === 0) {
      loadVersionHistory();
    }
  }, [loadVersionHistory, treeVersions.length]);

  // Load version history on component mount (populates treeVersions for instant dialog open)
  React.useEffect(() => {
    if (treeId && !isLocked) {
      loadVersionHistory(false);
    }
  }, [treeId, isLocked, loadVersionHistory]);

  return (
    <>
      <AppBar position="static" color="default" elevation={1}>
        <Toolbar variant="dense" sx={{ minHeight: 44, px: 2 }}>
          {/* Flex Layout with 4 sections - responsive */}
          <Box
            sx={{
              display: 'flex',
              gap: 2,
              alignItems: 'center',
              width: '100%',
              justifyContent: 'space-between',
            }}
          >
            {/* Section 1: Tree Name and Status */}
            <Box sx={{ display: 'flex', alignItems: 'center', minWidth: 0, flex: '0 0 auto' }}>
              <Typography
                variant="h6"
                sx={{
                  fontWeight: 'medium',
                  color: 'text.primary',
                  fontSize: '1rem',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {isNested ? currentLevel?.treeName || 'Sub-tree' : 'root'}
                {hasUnsavedChanges && (
                  <Typography component="span" sx={{ color: 'warning.main', ml: 0.5 }}>
                    *
                  </Typography>
                )}
              </Typography>
            </Box>

            {/* Section 2: Tree Controls */}
            <Box sx={{ flex: '0 1 auto', minWidth: 0 }}>
              <NavigationEditorTreeControls
                focusNodeId={focusNodeId}
                availableFocusNodes={availableFocusNodes}
                maxDisplayDepth={maxDisplayDepth}
                totalNodes={totalNodes}
                visibleNodes={visibleNodes}
                onFocusNodeChange={onFocusNodeChange}
                onDepthChange={onDepthChange}
                onResetFocus={handleResetFocus}
              />
            </Box>

            {/* Section 3: Action Buttons */}
            <Box sx={{ flex: '0 1 auto', minWidth: 0, display: 'flex', alignItems: 'center', gap: 1 }}>
              {/* Validate button sits to the left of the variant chip for
                  visual coherence with the rest of the toolbar. */}
              <ValidationButtonClient
                treeId={treeId}
                disabled={
                  isLoading || !!error || !selectedHost || !selectedDeviceId || !isControlActive || !treeId
                }
                selectedHost={selectedHost}
                selectedDeviceId={selectedDeviceId || null}
              />
              {/* Phase 4 §3.5 — canvas viewing scope chip (Base | <variant>).
                  The show/hide-disabled-rows toggle lives INSIDE this dropdown
                  as a per-variant eye (see canToggleDisabledOnVariant note on the
                  props) so selecting a variant never shifts the toolbar layout. */}
              {onViewingScopeChange && (
                <NavigationViewingScopeChip
                  userInterfaceId={userInterfaceId}
                  scope={viewingScope ?? null}
                  onScopeChange={onViewingScopeChange}
                  disabled={isLoading || !!error}
                  showDisabled={showDisabledOnVariant}
                  onToggleShowDisabled={onToggleShowDisabledOnVariant}
                />
              )}
              {/* Dev/prod scope chip — only rendered once a prod version exists.
                  Click toggles between the dev row and its prod snapshot. */}
              {hasProd && (
                <Tooltip
                  title={
                    isProdView
                      ? 'Viewing the published prod version (read-only). Click to switch to dev.'
                      : 'Viewing the editable dev version. Click to view prod.'
                  }
                >
                  <Chip
                    label={isProdView ? `PROD${prodVersion ? ` v${prodVersion}` : ''}` : 'DEV'}
                    size="small"
                    onClick={handleToggleUiMode}
                    sx={{
                      height: 24,
                      fontWeight: 600,
                      fontSize: '0.7rem',
                      cursor: 'pointer',
                      ...(isProdView
                        ? { bgcolor: '#b8860b', color: '#fff', '&:hover': { bgcolor: '#9a7209' } }
                        : {}),
                    }}
                    variant={isProdView ? 'filled' : 'outlined'}
                  />
                </Tooltip>
              )}
              {/* Publish button — dev view only. */}
              {!isProdView && (
                <Tooltip
                  title={
                    hasUnsavedChanges
                      ? 'Save your changes first, then publish'
                      : hasProd
                        ? `Overwrite prod v${prodVersion ?? '?'} with the current dev content`
                        : 'Create the production version from the current dev content'
                  }
                >
                  <span>
                    <Button
                      variant="outlined"
                      startIcon={publishing ? <CircularProgress size={14} /> : <PublishIcon />}
                      onClick={() => setPublishConfirmOpen(true)}
                      size="small"
                      disabled={isLoading || !!error || publishing || hasUnsavedChanges || !userInterface?.id}
                      sx={{
                        minWidth: 'auto',
                        height: 32,
                        whiteSpace: 'nowrap',
                        fontSize: '0.75rem',
                        textTransform: 'none',
                      }}
                    >
                      Publish
                    </Button>
                  </span>
                </Tooltip>
              )}
              <NavigationEditorActionButtons
              treeId={treeId}
              isLocked={isLocked}
              hasUnsavedChanges={hasUnsavedChanges}
              isLoading={isLoading}
              error={error}
              selectedHost={selectedHost}
              selectedDeviceId={selectedDeviceId || null}
              isControlActive={isControlActive}
              onAddNewNode={onAddNewNode}
              onFitView={onFitView}
              onSaveToConfig={onSaveToConfig}
              onDiscardChanges={onDiscardChanges}
              onUndo={undo}
              onRedo={redo}
              canUndo={canUndo}
              canRedo={canRedo}
            />

              {/* Version History Button */}
              <Tooltip title={
                isLocked
                  ? 'Tree is locked - unlock to access history'
                  : !hasVersionHistory
                    ? 'No version history available - save your tree first'
                    : 'View and restore previous versions'
              }>
                <span>
                  <Button
                    variant="outlined"
                    startIcon={<HistoryIcon />}
                    onClick={handleOpenVersionHistory}
                    size="small"
                    sx={{
                      minWidth: 'auto',
                      height: 32,
                      whiteSpace: 'nowrap',
                      fontSize: '0.75rem',
                      textTransform: 'none',
                    }}
                    disabled={isLocked || !hasVersionHistory}
                  >
                    History
                  </Button>
                </span>
              </Tooltip>
            </Box>

            {/* Section 4: Device Controls - now with proper device-oriented locking */}
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: '0 0 auto' }}>
              <NavigationEditorDeviceControls
                selectedHost={selectedHost}
                selectedDeviceId={selectedDeviceId || null}
                isControlActive={isControlActive}
                isControlLoading={isControlLoading}
                isRemotePanelOpen={isRemotePanelOpen}
                availableHosts={availableHosts}
                isDeviceLocked={(deviceKey: string) => {
                  // Parse deviceKey format: "hostname:device_id"
                  const [hostName, deviceId] = deviceKey.includes(':')
                    ? deviceKey.split(':')
                    : [deviceKey, 'device1'];

                  const host = availableHosts.find((h) => h.host_name === hostName);
                  return isDeviceLocked(host, deviceId);
                }}
                onDeviceSelect={onDeviceSelect}
                onTakeControl={handleDeviceControl}
                onToggleRemotePanel={onToggleRemotePanel}
              />
              
              {/* Localize Button - identify which node the live screen matches.
                  Replaces the (unused) AI generate button. Highlights the top
                  candidate on the canvas. */}
              <LocalizeButton
                hostName={selectedHost?.host_name}
                deviceId={selectedDeviceId}
                userinterfaceName={userInterface?.name}
                variant={viewingScope ?? null}
                disabled={!isControlActive || !selectedHost || !selectedDeviceId}
                disabledTitle="Take control of a device to localize"
                onCandidates={(candidates: LocalizeCandidate[]) => {
                  const top = candidates[0];
                  if (!top) return;
                  const match = nodes.find(
                    (n) => n.id === top.node_id || (n.data as any)?.node_id === top.node_id,
                  );
                  if (match) setSelectedNode(match);
                }}
              />
            </Box>
          </Box>
        </Toolbar>
      </AppBar>

      {/* Confirmation Dialog - for force unlock */}
      <ConfirmDialog
        open={confirmDialogState.open}
        title={confirmDialogState.title}
        message={confirmDialogState.message}
        confirmText={confirmDialogState.confirmText}
        cancelText={confirmDialogState.cancelText}
        confirmColor={confirmDialogState.confirmColor}
        onConfirm={confirmDialogHandleConfirm}
        onCancel={confirmDialogHandleCancel}
      />

      {/* Publish confirmation */}
      <ConfirmDialog
        open={publishConfirmOpen}
        title={`Publish "${userInterface?.name ?? ''}" to production?`}
        message={
          hasProd
            ? `Overwrites prod v${prodVersion ?? '?'} with the current dev content. Prod metrics & history are preserved.`
            : 'Creates the production version as a full copy of the current dev content.'
        }
        confirmText="Publish"
        onConfirm={handlePublish}
        onCancel={() => setPublishConfirmOpen(false)}
      />

      {/* Validation components are now rendered by ValidationButtonClient when needed */}

      {/* Version History Dialog */}
      <StyledDialog
        open={versionHistoryOpen}
        onClose={() => setVersionHistoryOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle sx={{ pb: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Typography variant="h6">Tree Version History</Typography>
        </DialogTitle>
        <DialogContent sx={{ pt: 0, pb: 1 }}>
          {loadingVersions ? (
            <Typography sx={{ py: 2 }}>Loading version history...</Typography>
          ) : treeVersions.length <= 1 ? (
            <Box sx={{ textAlign: 'center', py: 2 }}>
              <Typography variant="h6" color="text.secondary" gutterBottom>
                No Version History
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Save your tree to create the first version and enable history.
              </Typography>
            </Box>
          ) : (
            <List sx={{ py: 0 }} dense>
              {treeVersions.map((version) => (
                <ListItem key={version.version_number} divider sx={{ py: 0.5 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', width: '100%', gap: 3 }}>
                    {/* Column 1: Version (wider) */}
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: 250, flexShrink: 0 }}>
                      <Typography variant="body2" sx={{ fontWeight: 'medium' }}>
                        Version {version.version_number}
                      </Typography>
                      {currentVersion === version.version_number && (
                        <Chip label="CURRENT" color="primary" size="small" />
                      )}
                    </Box>

                    {/* Column 2: Date/Time (wider) */}
                    <Typography variant="body2" color="text.secondary" sx={{ width: 200, flexShrink: 0 }}>
                      {new Date(version.created_at).toLocaleDateString()} {new Date(version.created_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                    </Typography>

                    {/* Column 3: Tree Info (much wider) */}
                    {version.tree_data && (
                      <Typography variant="body2" color="text.secondary" sx={{ width: 280, flexShrink: 0 }}>
                        {version.tree_data.total_trees} trees • {version.tree_data.total_nodes} nodes • {version.tree_data.total_edges} edges • {version.tree_data.total_trees - 1} subtrees
                      </Typography>
                    )}

                    {/* Restore Button (right-aligned) */}
                    {currentVersion !== version.version_number && (
                      <IconButton
                        onClick={() => restoreVersion(version.version_number)}
                        title={`Restore to version ${version.version_number}`}
                        size="small"
                        sx={{ marginLeft: 'auto' }}
                        disabled={restoringVersion !== null}
                      >
                        {restoringVersion === version.version_number ? (
                          <CircularProgress size={18} />
                        ) : (
                          <RestoreIcon />
                        )}
                      </IconButton>
                    )}
                  </Box>
                </ListItem>
              ))}
            </List>
          )}
        </DialogContent>
        <DialogActions sx={{ pt: 1, pb: 2, px: 3 }}>
          <Button onClick={() => setVersionHistoryOpen(false)} size="small" variant="outlined" disabled={restoringVersion !== null}>
            Close
          </Button>
        </DialogActions>
      </StyledDialog>
    </>
  );
};

export default NavigationEditorHeader;
