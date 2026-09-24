import {
  KeyboardArrowDown as ArrowDownIcon,
  KeyboardArrowRight as ArrowRightIcon,
  OpenInFull as ExpandEditorIcon,
  CloseFullscreen as RestoreEditorIcon,
} from '@mui/icons-material';
import {
  Box,
  Typography,
  IconButton,
  Collapse,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Tooltip,
} from '@mui/material';
import React from 'react';

import { StyledDialog } from '../../common/StyledDialog';
import {
  VerificationEditorLayoutConfig,
  getVerificationEditorLayout,
} from '../../../config/layoutConfig';
import { useVerificationEditor } from '../../../hooks/verification/useVerificationEditor';
import { useReferenceRecapture } from '../../../hooks/verification/useReferenceRecapture';
import { useConfirmDialog } from '../../../hooks/useConfirmDialog';
import { Host } from '../../../types/common/Host_Types';
import { VerificationsList } from '../../verification/VerificationsList';
import { ConfirmDialog } from '../../common/ConfirmDialog';
import { getZIndex } from '../../../utils/zIndexUtils';

import VerificationCapture from './VerificationCapture';

interface DragArea {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface VerificationEditorProps {
  isVisible: boolean;
  selectedHost: Host;
  selectedDeviceId: string;
  captureSourcePath?: string;
  selectedArea?: DragArea | null;
  onAreaSelected?: (area: DragArea) => void;
  onClearSelection?: () => void;
  isCaptureActive: boolean;
  isControlActive?: boolean;
  userinterfaceName?: string; // Required for saving references - defines the app/UI context
  layoutConfig?: VerificationEditorLayoutConfig;
  // Notifies the parent when the capture reference type changes (image/text) so the
  // stream overlay can disable fuzzy-area dragging for text references.
  onReferenceTypeChange?: (type: 'image' | 'text') => void;
  isMaximized?: boolean;
  onToggleMaximized?: () => void;
  sx?: any;
}

export const VerificationEditor: React.FC<VerificationEditorProps> = React.memo(
  ({
    isVisible,
    selectedHost,
    selectedDeviceId,
    captureSourcePath,
    selectedArea,
    onAreaSelected,
    onClearSelection,
    isCaptureActive,
    isControlActive = false,
    userinterfaceName, // Required for saving references
    layoutConfig,
    onReferenceTypeChange,
    isMaximized = false,
    onToggleMaximized,
    sx = {},
  }) => {
    // Extract device from host devices array using selectedDeviceId
    const selectedDevice = React.useMemo(() => {
      return selectedHost?.devices?.find((device) => device.device_id === selectedDeviceId);
    }, [selectedHost, selectedDeviceId]);

    // Use device_model only for layout configuration (UI presentation)
    // But use userinterfaceName for all data lookups (references, verifications)
    const deviceModelForLayout = selectedDevice?.device_model;

    // Use the provided layout config or get it from the model type
    const finalLayoutConfig = React.useMemo(() => {
      const config = layoutConfig || getVerificationEditorLayout(deviceModelForLayout || 'unknown');
      console.log('[@component:VerificationEditor] Layout config recalculated:', {
        selectedDeviceId,
        deviceModelForLayout,
        userinterfaceName,
        providedLayoutConfig: layoutConfig,
        calculatedConfig: config,
        isMobileModel: config.isMobileModel,
        width: config.width,
        height: config.height,
        captureHeight: config.captureHeight,
      });
      return config;
    }, [deviceModelForLayout, layoutConfig, selectedDeviceId, userinterfaceName]);

    // Use the verification editor hook to handle all verification logic
    const verification = useVerificationEditor({
      isVisible,
      selectedHost,
      selectedDeviceId,
      captureSourcePath,
      selectedArea,
      onAreaSelected,
      onClearSelection,
      isCaptureActive,
      isControlActive,
      userinterfaceName, // Pass userinterfaceName to hook for reference saving
    });

    // The reference editor can only meaningfully edit image/text appear & disappear
    // verifications, so restrict the dropdown to just those four commands.
    const editableVerificationTypes = React.useMemo(() => {
      const allowedCommands = new Set([
        'waitForImageToAppear',
        'waitForImageToDisappear',
        'waitForTextToAppear',
        'waitForTextToDisappear',
      ]);
      const filtered: Record<string, any[]> = {};
      Object.entries(verification.availableVerificationTypes || {}).forEach(
        ([category, verifications]) => {
          if (!Array.isArray(verifications)) return;
          const kept = verifications.filter((v: any) => allowedCommands.has(v.command));
          if (kept.length > 0) filtered[category] = kept;
        },
      );
      return filtered;
    }, [verification.availableVerificationTypes]);

    // In-place reference recapture (same area). Confirmation uses the shared
    // ConfirmDialog rendered at the bottom of this component.
    const { recapture, recapturingIndex } = useReferenceRecapture(userinterfaceName);
    const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

    const handleRecaptureReference = React.useCallback(
      (index: number) => {
        const verif = verification.verifications[index];
        const internalKey = (verif?.params as any)?.reference_name;
        if (!internalKey) return;
        const ref = (verification.modelReferences as any)[internalKey];
        const displayName = ref?.name || internalKey;
        // Focus intent: explicit per-verification flag, else whether the reference
        // already carries a learned focus accent.
        const checkFocus = Boolean((verif?.params as any)?.check_focus ?? (ref?.area as any)?.focus);
        confirm({
          title: 'Recapture Reference',
          message:
            `Take a new screenshot and overwrite reference "${displayName}" using its current area?\n\n` +
            'The area and fuzzy area are kept unchanged.' +
            (checkFocus ? '\n\nFocus is on — the selected/focused accent will be re-learned from this capture.' : ''),
          confirmText: 'Recapture',
          confirmColor: 'warning',
          onConfirm: () => {
            void recapture(index, internalKey, checkFocus);
          },
        });
      },
      [verification.verifications, verification.modelReferences, confirm, recapture],
    );

    // Report capture reference type changes upward so the stream overlay can
    // disable fuzzy-area dragging when a text reference is active.
    React.useEffect(() => {
      onReferenceTypeChange?.(verification.referenceType);
    }, [verification.referenceType, onReferenceTypeChange]);

    // Debug logging for component mount/unmount
    React.useEffect(() => {
      console.log('[@component:VerificationEditor] Component mounted with props:', {
        isVisible,
        selectedDeviceId,
        deviceModelForLayout,
        userinterfaceName,
        isCaptureActive,
        layoutConfig: finalLayoutConfig,
        selectedDevice: !!selectedDevice,
      });

      return () => {
        console.log('[@component:VerificationEditor] Component unmounting');
      };
    }, [isVisible, selectedDeviceId, deviceModelForLayout, userinterfaceName, isCaptureActive, finalLayoutConfig, selectedDevice]);

    if (!isVisible) return null;

    return (
      <Box
        sx={{
          width: finalLayoutConfig.width,
          height: finalLayoutConfig.height,
          p: 1,
          display: 'flex',
          flexDirection: 'column',
          gap: 1,
          overflowY: 'auto',
          overflowX: 'hidden',
          '&::-webkit-scrollbar': {
            width: '6px',
          },
          '&::-webkit-scrollbar-track': {
            background: 'rgba(255,255,255,0.1)',
            borderRadius: '3px',
          },
          '&::-webkit-scrollbar-thumb': {
            background: 'rgba(255,255,255,0.3)',
            borderRadius: '3px',
            '&:hover': {
              background: 'rgba(255,255,255,0.5)',
            },
          },
          ...sx,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Typography variant="h6" sx={{ fontSize: '1rem', fontWeight: 600 }}>
            Verification Editor
          </Typography>
          {onToggleMaximized && (
            <Tooltip title={isMaximized ? 'Restore editor' : 'Maximize editor'}>
              <IconButton
                aria-label={isMaximized ? 'Restore Verification Editor' : 'Maximize Verification Editor'}
                size="medium"
                onClick={onToggleMaximized}
                sx={{ p: 1, color: 'inherit' }}
              >
                {isMaximized ? <RestoreEditorIcon /> : <ExpandEditorIcon />}
              </IconButton>
            </Tooltip>
          )}
        </Box>

        {/* =================== CAPTURE SECTION =================== */}
        <VerificationCapture
          verification={verification}
          selectedArea={selectedArea || null}
          onAreaSelected={onAreaSelected}
          captureHeight={finalLayoutConfig.captureHeight}
          isMobileModel={finalLayoutConfig.isMobileModel}
        />

        {/* =================== VERIFICATIONS SECTION =================== */}
        <Box>
          {/* Collapsible toggle button and title */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5 }}>
            <IconButton
              size="small"
              onClick={() =>
                verification.setVerificationsCollapsed(!verification.verificationsCollapsed)
              }
              sx={{ p: 0.25 }}
            >
              {verification.verificationsCollapsed ? (
                <ArrowRightIcon sx={{ fontSize: '1rem' }} />
              ) : (
                <ArrowDownIcon sx={{ fontSize: '1rem' }} />
              )}
            </IconButton>
            <Typography variant="subtitle2" sx={{ fontSize: '0.8rem', fontWeight: 600 }}>
              Verifications
            </Typography>
          </Box>

          {/* Collapsible content */}
          <Collapse in={!verification.verificationsCollapsed}>
            <Box
              sx={{
                '& .MuiTypography-subtitle2': {
                  fontSize: '0.75rem',
                },
                '& .MuiButton-root': {
                  fontSize: '0.7rem',
                },
                '& .MuiTextField-root': {
                  '& .MuiInputLabel-root': {
                    fontSize: '0.75rem',
                  },
                  '& .MuiInputBase-input': {
                    fontSize: '0.75rem',
                  },
                },
                '& .MuiSelect-root': {
                  fontSize: '0.75rem',
                },
                '& .MuiFormControl-root': {
                  '& .MuiInputLabel-root': {
                    fontSize: '0.75rem',
                  },
                },
              }}
            >
              {userinterfaceName && (
                <VerificationsList
                  verifications={verification.verifications}
                  availableVerifications={editableVerificationTypes}
                  onVerificationsChange={verification.handleVerificationsChange}
                  loading={verification.loading}
                  model={userinterfaceName}
                  onTest={verification.handleTest}
                  testResults={verification.testResults}
                  onReferenceSelected={verification.handleReferenceSelected}
                  selectedHost={verification.currentHost || undefined}
                  modelReferences={verification.modelReferences}
                  referencesLoading={verification.referencesLoading}
                  showCollapsible={false}
                  title="Verifications"
                  shared={verification.shared}
                  onSharedChange={verification.setShared}
                  onRecaptureReference={
                    isControlActive ? handleRecaptureReference : undefined
                  }
                  recapturingIndex={recapturingIndex}
                />
              )}
            </Box>
          </Collapse>
        </Box>

        {/* =================== CONFIRMATION DIALOG =================== */}
        <StyledDialog
          open={verification.showConfirmDialog}
          onClose={verification.handleCancelOverwrite}
          PaperProps={{
            sx: {
              backgroundColor: '#2E2E2E',
              color: '#ffffff',
              zIndex: getZIndex('VERIFICATION_EDITOR'),
            },
          }}
        >
          <DialogTitle sx={{ color: '#ffffff', fontSize: '1rem' }}>
            Warning: Overwrite Reference
          </DialogTitle>
          <DialogContent>
            <Typography sx={{ color: '#ffffff', fontSize: '0.875rem' }}>
              A {verification.referenceType} reference named "{verification.referenceName}" already
              exists.
              <br />
              Do you want to overwrite it?
            </Typography>
          </DialogContent>
          <DialogActions sx={{ gap: 1, p: 2 }}>
            <Button
              onClick={verification.handleCancelOverwrite}
              variant="outlined"
              size="small"
              sx={{
                borderColor: '#666',
                color: '#ffffff',
                fontSize: '0.75rem',
                '&:hover': {
                  borderColor: '#888',
                  backgroundColor: 'rgba(255,255,255,0.1)',
                },
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={verification.handleConfirmOverwrite}
              variant="contained"
              size="small"
              sx={{
                bgcolor: '#f44336',
                fontSize: '0.75rem',
                '&:hover': {
                  bgcolor: '#d32f2f',
                },
              }}
            >
              Confirm
            </Button>
          </DialogActions>
        </StyledDialog>

        {/* =================== RECAPTURE CONFIRMATION =================== */}
        <ConfirmDialog
          open={dialogState.open}
          title={dialogState.title}
          message={dialogState.message}
          confirmText={dialogState.confirmText}
          cancelText={dialogState.cancelText}
          confirmColor={dialogState.confirmColor}
          onConfirm={handleConfirm}
          onCancel={handleCancel}
        />
      </Box>
    );
  },
  (prevProps, nextProps) => {
    // Custom comparison function to prevent unnecessary re-renders
    const isVisibleChanged = prevProps.isVisible !== nextProps.isVisible;
    const selectedHostChanged =
      JSON.stringify(prevProps.selectedHost) !== JSON.stringify(nextProps.selectedHost);
    const selectedDeviceIdChanged = prevProps.selectedDeviceId !== nextProps.selectedDeviceId;
    const captureSourcePathChanged = prevProps.captureSourcePath !== nextProps.captureSourcePath;
    const selectedAreaChanged =
      JSON.stringify(prevProps.selectedArea) !== JSON.stringify(nextProps.selectedArea);
    const isCaptureActiveChanged = prevProps.isCaptureActive !== nextProps.isCaptureActive;
    const isControlActiveChanged = prevProps.isControlActive !== nextProps.isControlActive;
    const layoutConfigChanged =
      JSON.stringify(prevProps.layoutConfig) !== JSON.stringify(nextProps.layoutConfig);
    const sxChanged = JSON.stringify(prevProps.sx) !== JSON.stringify(nextProps.sx);
    const onAreaSelectedChanged = prevProps.onAreaSelected !== nextProps.onAreaSelected;
    const onClearSelectionChanged = prevProps.onClearSelection !== nextProps.onClearSelection;

    // Only re-render if meaningful props have changed
    const shouldRerender =
      isVisibleChanged ||
      selectedHostChanged ||
      selectedDeviceIdChanged ||
      captureSourcePathChanged ||
      selectedAreaChanged ||
      isCaptureActiveChanged ||
      isControlActiveChanged ||
      layoutConfigChanged ||
      sxChanged ||
      onAreaSelectedChanged ||
      onClearSelectionChanged;

    if (shouldRerender) {
      console.log('[@component:VerificationEditor] Props changed, re-rendering:', {
        isVisibleChanged,
        selectedHostChanged,
        selectedDeviceIdChanged,
        captureSourcePathChanged,
        selectedAreaChanged,
        isCaptureActiveChanged,
        isControlActiveChanged,
        layoutConfigChanged,
        sxChanged,
        onAreaSelectedChanged,
        onClearSelectionChanged,
      });
    }

    return !shouldRerender; // Return true to skip re-render, false to re-render
  },
);

export default VerificationEditor;
