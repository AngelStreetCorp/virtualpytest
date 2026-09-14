import { Box } from '@mui/material';
import React, { useState, useCallback, useEffect, useRef } from 'react';
import toast from 'react-hot-toast';

import { VNCStateProvider } from '../../contexts/VNCStateContext';
import { useStream } from '../../hooks/controller';
import { useRunningLog } from '../../hooks/rec/useRunningLog';
import { useRecModalModes } from '../../hooks/rec/useRecModalModes';
import { useRecQualitySwitch } from '../../hooks/rec/useRecQualitySwitch';
import { useRecCaptureActions } from '../../hooks/rec/useRecCaptureActions';
import { useRecStreamLayout, useRecDeviceChecks } from '../../hooks/rec/useRecStreamLayout';
import { useRecModalLifecycle } from '../../hooks/rec/useRecModalLifecycle';
import { useDeviceControlWithForceUnlock } from '../../hooks/useDeviceControlWithForceUnlock';
import { useDeviceLockLabel } from '../../hooks/rec/useDeviceLockLabel';
import { useDeviceScriptLabel } from '../../hooks/rec/useDeviceScriptLabel';
import { useHostControl } from '../../hooks/useHostManager';
import { useToast } from '../../hooks/useToast';
import { useMonitoring } from '../../hooks/monitoring/useMonitoring';
import { useAIContext } from '../../contexts/AIContext';
import type { Ambiguity, AutoCorrection } from '../../types/aiagent/AIDisambiguation_Types';
import { Host, Device } from '../../types/common/Host_Types';
import { getZIndex } from '../../utils/zIndexUtils';
import { calculateVncScaling } from '../../utils/vncUtils';
import { getLockTimingLines } from '../../utils/recUtils';
import { AIExecutionPanel } from '../ai';
import { PromptDisambiguation } from '../ai/PromptDisambiguation';
import { AIImageQueryModal } from '../monitoring';
import { ConfirmDialog } from '../common/ConfirmDialog';

import { RecStreamModalHeader } from './RecStreamModalHeader';
import { RecStreamContainer } from './RecStreamContainer';
import { RecPanelManager } from './RecPanelManager';
import { ScriptRunningOverlay } from './ScriptRunningOverlay';
import { RunningScriptNameBadge } from './RunningScriptNameBadge';

interface RecHostStreamModalProps {
  host: Host;
  device?: Device;
  isOpen: boolean;
  onClose: () => void;
  showRemoteByDefault?: boolean;
  initialPoster?: string | null;
}

export const RecHostStreamModal: React.FC<RecHostStreamModalProps> = ({
  host,
  device,
  isOpen,
  onClose,
  showRemoteByDefault = false,
  initialPoster = null,
}) => {
  if (!isOpen || !host) return null;

  return (
    <VNCStateProvider>
      <RecHostStreamModalContent
        host={host}
        device={device}
        onClose={onClose}
        showRemoteByDefault={showRemoteByDefault}
        initialPoster={initialPoster}
      />
    </VNCStateProvider>
  );
};

const RecHostStreamModalContent: React.FC<{
  host: Host;
  device?: Device;
  onClose: () => void;
  showRemoteByDefault: boolean;
  initialPoster: string | null;
}> = ({ host, device, onClose, showRemoteByDefault, initialPoster }) => {
  const deviceId = device?.device_id || 'device1';
  const { showError } = useToast();

  // Hide the global floating "Ask AI" Fab while this fullscreen stream modal is open.
  const { pushFloatingButtonSuppress, popFloatingButtonSuppress } = useAIContext();
  useEffect(() => {
    pushFloatingButtonSuppress();
    return () => popFloatingButtonSuppress();
  }, [pushFloatingButtonSuppress, popFloatingButtonSuppress]);

  const { isDesktopDevice, isMobileModel, hasPowerControl } = useRecDeviceChecks(device);

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
    host,
    device_id: deviceId,
    sessionId: 'rec-stream-modal-session',
    autoCleanup: true,
    requireTreeId: false,
  });

  const modes = useRecModalModes(showRemoteByDefault, isControlActive, isDesktopDevice);

  const quality = useRecQualitySwitch(host, deviceId, showError);

  const [currentSegmentUrl, setCurrentSegmentUrl] = useState<string | null>(null);
  const capture = useRecCaptureActions(
    host,
    device,
    currentSegmentUrl,
    modes.isLiveMode,
    modes.restartMode
  );

  const layout = useRecStreamLayout(
    modes.showRemote,
    modes.showWeb,
    isDesktopDevice,
    isControlActive
  );

  const handleClose = useCallback(() => {
    quality.stopPolling();
    quality.resetOnClose();
    modes.resetOnClose();
    onClose();
  }, [quality, modes, onClose]);

  useRecModalLifecycle(handleClose);

  const { streamUrl, isLoadingUrl, urlError } = useStream({ host, device_id: deviceId });

  const [currentVideoTime, setCurrentVideoTime] = useState<number>(0);
  const lastVideoTimeUpdateRef = useRef<number>(0);
  const lastVideoTimeValueRef = useRef<number>(-1);

  const monitoringData = useMonitoring({
    host,
    device,
    enabled: modes.monitoringMode,
    archiveMode: !modes.isLiveMode,
    currentVideoTime,
  });

  const { logData: runningLogData } = useRunningLog(
    host,
    device?.device_id,
    Boolean(device?.has_running_deployment && device?.device_id)
  );

  const manualControlLabel = useDeviceLockLabel(host, device);

  // Script/deployment label derived from the lock itself — mirrors the preview card
  // so the modal shows the running script even when `has_running_deployment` is false
  // (or running.log isn't available yet) and there is no full running-log overlay.
  const {
    scriptLabel: deploymentScriptLabel,
    hasNamedScript: hasNamedDeployment,
    scriptOwnerName,
  } = useDeviceScriptLabel(host, device);

  // Who is on the device (manual lock owner, else whoever launched the run).
  const lockOwnerLabel = manualControlLabel || scriptOwnerName;

  // Start-time + live duration for the header lock tooltip (helps spot stale locks).
  const { getDeviceLockInfo } = useHostControl();
  const lockTiming = getLockTimingLines(getDeviceLockInfo(host, deviceId));

  // Open the dedicated quality-focused player in a new tab. Plays the current
  // live stream with deep buffering (no live-edge chasing) — see pages/FullscreenPlayer.
  const handleOpenFullscreen = useCallback(() => {
    if (!streamUrl) return;
    // Normalize to the live manifest, mirroring EnhancedHLSPlayer's streamUrl logic.
    const liveUrl = streamUrl.replace(
      /\/(segments\/)?(output|archive.*?)\.m3u8$/,
      '/segments/output.m3u8',
    );
    const label = device?.device_name || host.host_name;
    // Respect the router proxy basename (/pi4, /mac) so the new tab routes correctly.
    const proxyMatch = window.location.pathname.match(/^\/(pi\d+|mac)\//);
    const base = proxyMatch ? proxyMatch[0].slice(0, -1) : '';
    const url = `${base}/fullscreen-player?src=${encodeURIComponent(liveUrl)}&name=${encodeURIComponent(label)}`;
    window.open(url, '_blank', 'noopener');
  }, [streamUrl, device, host]);

  const [disambiguationData, setDisambiguationData] = useState<{
    ambiguities?: Ambiguity[];
    auto_corrections?: AutoCorrection[];
    available_nodes?: string[];
  } | null>(null);
  const [disambiguationResolve, setDisambiguationResolve] = useState<
    ((selections: Record<string, string>, saveToDb: boolean) => void) | null
  >(null);
  const [disambiguationCancel, setDisambiguationCancel] = useState<(() => void) | null>(null);

  const handleDisambiguationDataChange = useCallback(
    (
      data: { ambiguities?: Ambiguity[]; auto_corrections?: AutoCorrection[]; available_nodes?: string[] },
      resolve: (selections: Record<string, string>, saveToDb: boolean) => void,
      cancel: () => void
    ) => {
      setDisambiguationData(data);
      setDisambiguationResolve(() => resolve);
      setDisambiguationCancel(() => cancel);
    },
    []
  );

  const handleVideoTimeUpdate = useCallback(
    (time: number) => {
      if (modes.isLiveMode || !modes.monitoringMode) return;
      const now =
        typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now();
      if (now - lastVideoTimeUpdateRef.current < 500) return;
      if (lastVideoTimeValueRef.current >= 0 && Math.abs(time - lastVideoTimeValueRef.current) < 0.5)
        return;
      lastVideoTimeUpdateRef.current = now;
      lastVideoTimeValueRef.current = time;
      setCurrentVideoTime(time);
    },
    [modes.isLiveMode, modes.monitoringMode]
  );

  const handleReleaseControl = useCallback(() => {
    modes.resetOnReleaseControl();
  }, [modes]);

  const [isMuted, setIsMuted] = useState<boolean>(true);

  // Hide the captured preview poster once the modal player has actually started
  // playing, or after a safety timeout. Skips entirely if we had no poster to show.
  const [posterVisible, setPosterVisible] = useState<boolean>(!!initialPoster);
  useEffect(() => {
    if (!posterVisible) return;
    const t = setTimeout(() => setPosterVisible(false), 5000);
    return () => clearTimeout(t);
  }, [posterVisible]);

  const handlePlayerReady = useCallback(() => {
    quality.handlePlayerReady();
    setPosterVisible(false);
  }, [quality]);

  // Stable per-device toast ids so repeated control/stream errors REPLACE the
  // existing popup instead of stacking a new one each time. Scoped to this modal
  // and dismissed on unmount below, so the errors only show while it's open.
  const controlErrorToastId = `rec-control-error-${host.host_name}-${deviceId}`;
  const urlErrorToastId = `rec-url-error-${host.host_name}-${deviceId}`;

  useEffect(() => {
    if (controlError) {
      showError(controlError, { id: controlErrorToastId });
      clearError();
    }
  }, [controlError, showError, clearError, controlErrorToastId]);

  useEffect(() => {
    if (urlError) {
      showError(`Stream URL error: ${urlError}`, { id: urlErrorToastId });
    }
  }, [urlError, showError, urlErrorToastId]);

  // Dismiss any lingering error toasts when the modal closes/unmounts, so they
  // never linger over the device grid after the stream view is gone.
  useEffect(() => {
    return () => {
      toast.dismiss(controlErrorToastId);
      toast.dismiss(urlErrorToastId);
    };
  }, [controlErrorToastId, urlErrorToastId]);

  return (
    <Box
      sx={{
        position: 'fixed',
        inset: 0,
        zIndex: getZIndex('MODAL_CONTENT'),
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'rgba(0, 0, 0, 0.9)',
      }}
    >
      <Box
        sx={{
          width: '95vw',
          height: '90vh',
          backgroundColor: 'background.paper',
          borderRadius: 2,
          boxShadow: 24,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        <RecStreamModalHeader
          host={host}
          device={device}
          manualControlLabel={manualControlLabel}
          lockOwnerLabel={lockOwnerLabel}
          scriptLockActive={hasNamedDeployment}
          scriptLockLabel={deploymentScriptLabel}
          lockTiming={lockTiming}
          monitoringMode={modes.monitoringMode}
          restartMode={modes.restartMode}
          isLiveMode={modes.isLiveMode}
          currentQuality={quality.currentQuality}
          isQualitySwitching={quality.isQualitySwitching}
          isMuted={isMuted}
          isControlActive={isControlActive}
          isControlLoading={isControlLoading}
          aiAgentMode={modes.aiAgentMode}
          showWeb={modes.showWeb}
          showRemote={modes.showRemote}
          isDesktopDevice={isDesktopDevice}
          hasPowerControl={!!hasPowerControl}
          onScreenshot={capture.handleScreenshot}
          onOpenFullscreen={handleOpenFullscreen}
          onAIImageQuery={capture.handleAIImageQuery}
          onToggleLiveMode={modes.handleToggleLiveMode}
          onQualityChange={quality.handleQualityChange}
          onToggleMute={() => setIsMuted((prev) => !prev)}
          onToggleControl={handleDeviceControl}
          onToggleMonitoring={modes.handleToggleMonitoring}
          onToggleRestart={modes.handleToggleRestart}
          onToggleAiAgent={modes.handleToggleAiAgent}
          onToggleWeb={modes.handleToggleWeb}
          onToggleRemote={modes.handleToggleRemote}
          onClose={handleClose}
        />

        <Box
          sx={{
            flex: 1,
            display: 'flex',
            overflow: 'hidden',
            backgroundColor: 'black',
            position: 'relative',
          }}
        >
          {initialPoster && posterVisible && (
            <Box
              component="img"
              src={initialPoster}
              alt=""
              sx={{
                position: 'absolute',
                inset: 0,
                width: '100%',
                height: '100%',
                objectFit: 'contain',
                backgroundColor: 'black',
                zIndex: 50,
                pointerEvents: 'none',
              }}
            />
          )}

          <RecStreamContainer
            host={host}
            device={device}
            streamUrl={streamUrl || undefined}
            isLoadingUrl={isLoadingUrl}
            urlError={urlError}
            monitoringMode={modes.monitoringMode}
            restartMode={modes.restartMode}
            isLiveMode={modes.isLiveMode}
            isControlActive={isControlActive}
            currentQuality={quality.currentQuality}
            isQualitySwitching={quality.isQualitySwitching}
            shouldPausePlayer={quality.shouldPausePlayer}
            isMuted={isMuted}
            isMobileModel={isMobileModel}
            showRemote={modes.showRemote}
            showWeb={modes.showWeb}
            finalStreamContainerDimensions={layout.finalStreamContainerDimensions}
            calculateVncScaling={calculateVncScaling}
            onPlayerReady={handlePlayerReady}
            onVideoTimeUpdate={handleVideoTimeUpdate}
            onCurrentSegmentChange={setCurrentSegmentUrl}
            monitoringAnalysis={monitoringData.latestAnalysis || undefined}
            subtitleAnalysis={monitoringData.latestSubtitleAnalysis || undefined}
            languageMenuAnalysis={monitoringData.latestLanguageMenuAnalysis || undefined}
            aiDescription={monitoringData.latestAIDescription || undefined}
            errorTrendData={monitoringData.errorTrendData || undefined}
            analysisTimestamp={monitoringData.analysisTimestamp || undefined}
            isAIAnalyzing={monitoringData.isAIAnalyzing}
          />

          <RecPanelManager
            host={host}
            device={device}
            showRemote={modes.showRemote}
            showWeb={modes.showWeb}
            isControlActive={isControlActive}
            isDesktopDevice={isDesktopDevice}
            finalStreamContainerDimensions={layout.finalStreamContainerDimensions}
            onReleaseControl={handleReleaseControl}
          />

          <AIExecutionPanel
            host={host}
            device={device!}
            isControlActive={isControlActive}
            isVisible={modes.aiAgentMode && isControlActive}
            onDisambiguationDataChange={handleDisambiguationDataChange}
          />

          {runningLogData && (
            <ScriptRunningOverlay
              logData={runningLogData}
              scriptNameRightOffset={layout.scriptNameRightOffset}
            />
          )}

          {!runningLogData && (hasNamedDeployment || lockOwnerLabel) && (
            <RunningScriptNameBadge
              scriptName={hasNamedDeployment ? deploymentScriptLabel : null}
              ownerName={lockOwnerLabel}
              maxChars={30}
              sx={{
                right: layout.scriptNameRightOffset || 8,
                bottom: 8,
                zIndex: 25,
              }}
              textSx={{ fontWeight: 'bold', fontSize: '0.75rem' }}
            />
          )}
        </Box>
      </Box>

      {disambiguationData && disambiguationResolve && disambiguationCancel && (
        <PromptDisambiguation
          ambiguities={disambiguationData.ambiguities ?? []}
          autoCorrections={disambiguationData.auto_corrections}
          availableNodes={disambiguationData.available_nodes}
          onResolve={(selections, saveToDb) => {
            disambiguationResolve(selections, saveToDb);
            setDisambiguationData(null);
          }}
          onCancel={() => {
            disambiguationCancel();
            setDisambiguationData(null);
          }}
          onEditPrompt={() => {
            disambiguationCancel();
            setDisambiguationData(null);
          }}
        />
      )}

      <AIImageQueryModal
        isVisible={capture.isImageQueryVisible}
        imageUrl={capture.capturedImageUrl}
        host={host}
        device={device!}
        onClose={capture.closeImageQuery}
      />

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
    </Box>
  );
};
