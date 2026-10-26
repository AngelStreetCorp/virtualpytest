import { Box } from '@mui/material';
import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import toast from 'react-hot-toast';

import { VNCStateProvider } from '../../contexts/VNCStateContext';
import { useStream } from '../../hooks/controller';
import { useRunningLog } from '../../hooks/rec/useRunningLog';
import { useRecModalModes } from '../../hooks/rec/useRecModalModes';
import { useStreamTransport } from '../../hooks/controller/useStreamTransport';
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
import type { LiveStreamTransport, WhepStatus } from '../../types/controller/WebRTC_Types';
import { Host, Device } from '../../types/common/Host_Types';
import { getZIndex } from '../../utils/zIndexUtils';
import { getLockTimingLines } from '../../utils/recUtils';
import { whepFallbackNotice } from '../../utils/whepFallback';
import { AIExecutionPanel } from '../ai';
import { RecGotoNodePanel } from './RecGotoNodePanel';
import { RecRunScriptPanel } from './RecRunScriptPanel';
import { RecVoicePanel } from './RecVoicePanel';
import { PromptDisambiguation } from '../ai/PromptDisambiguation';
import { AIImageQueryModal } from '../monitoring';
import { ConfirmDialog } from '../common/ConfirmDialog';

import { RecStreamModalHeader } from './RecStreamModalHeader';
import { RecStreamContainer } from './RecStreamContainer';
import { CaptionPlaybackPlayer } from './CaptionPlaybackPlayer';
import { CAPTION_PROFILE, DEFAULT_DELAY_S } from '../../utils/captionPlayback';
import { LolLiveOverlay } from '../game/lol/LolLiveOverlay';
import { RecPanelManager } from './RecPanelManager';
import { ScriptRunningOverlay } from './ScriptRunningOverlay';
import { RunningScriptNameBadge } from './RunningScriptNameBadge';
import { DeviceLockBadge, lockBadgeShows } from './DeviceLockBadge';
import { useBackToClose } from '../../hooks/useBackToClose';
import { TYPOGRAPHY } from '../../constants/typography';

interface RecHostStreamModalProps {
  host: Host;
  device?: Device;
  isOpen: boolean;
  onClose: () => void;
  showRemoteByDefault?: boolean;
  initialPoster?: string | null;
  // Forwarded to RecStreamModalHeader — hides power-user controls for the
  // mobile device-control page. Defaults to false, so all other callers of
  // this modal are unaffected.
  minimalControls?: boolean;
  reusePreviewStream?: boolean;
  // Open in archive mode at this host time of day (seconds since midnight, h*3600+m*60+s), e.g. from the Timeline page.
  initialArchiveTime?: number | null;
  onPersistentStreamTargetChange?: (target: HTMLElement | null) => void;
  onPersistentStreamStateChange?: (state: { muted: boolean; interactive: boolean; shouldPause: boolean; onPlayerReady: () => void; transport: LiveStreamTransport; reconnectKey: string; onWebRTCFailed: (reason: string) => void; onWebRTCStatusChange: (status: WhepStatus) => void }) => void;
}

export const RecHostStreamModal: React.FC<RecHostStreamModalProps> = ({
  host,
  device,
  isOpen,
  onClose,
  showRemoteByDefault = false,
  initialPoster = null,
  minimalControls = false,
  reusePreviewStream = false,
  initialArchiveTime = null,
  onPersistentStreamTargetChange,
  onPersistentStreamStateChange,
}) => {
  // Before the early return: hooks cannot be called conditionally. Lets the system Back
  // button close this modal rather than navigating the page underneath it.
  useBackToClose(isOpen && Boolean(host), onClose);

  if (!isOpen || !host) return null;

  return (
    <VNCStateProvider>
      <RecHostStreamModalContent
        host={host}
        device={device}
        onClose={onClose}
        showRemoteByDefault={showRemoteByDefault}
        initialPoster={initialPoster}
        minimalControls={minimalControls}
        reusePreviewStream={reusePreviewStream}
        initialArchiveTime={initialArchiveTime}
        onPersistentStreamTargetChange={onPersistentStreamTargetChange}
        onPersistentStreamStateChange={onPersistentStreamStateChange}
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
  minimalControls: boolean;
  reusePreviewStream: boolean;
  initialArchiveTime: number | null;
  onPersistentStreamTargetChange?: (target: HTMLElement | null) => void;
  onPersistentStreamStateChange?: (state: { muted: boolean; interactive: boolean; shouldPause: boolean; onPlayerReady: () => void; transport: LiveStreamTransport; reconnectKey: string; onWebRTCFailed: (reason: string) => void; onWebRTCStatusChange: (status: WhepStatus) => void }) => void;
}> = ({ host, device, onClose, showRemoteByDefault, initialPoster, minimalControls, reusePreviewStream, initialArchiveTime, onPersistentStreamTargetChange, onPersistentStreamStateChange }) => {
  const deviceId = device?.device_id || 'device1';
  const { showError, showWarning } = useToast();

  // Hide the global floating "Ask AI" Fab while this fullscreen stream modal is open.
  const { pushFloatingButtonSuppress, popFloatingButtonSuppress } = useAIContext();
  useEffect(() => {
    pushFloatingButtonSuppress();
    return () => popFloatingButtonSuppress();
  }, [pushFloatingButtonSuppress, popFloatingButtonSuppress]);

  const { isDesktopDevice, isMobileModel, hasPowerControl, canTakeControl } = useRecDeviceChecks(device);

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

  const modes = useRecModalModes(
    showRemoteByDefault,
    isControlActive,
    isDesktopDevice,
    initialArchiveTime != null,
    !!host.system_stats?.monitor_overlay_on?.includes(deviceId),
  );

  const quality = useRecQualitySwitch(host, deviceId, showError);

  // HLS / WebRTC live view toggle (RTC button next to the quality group).
  const streamTransport = useStreamTransport(host.host_name, deviceId, device?.stream_protocol);
  const deviceLabel = device?.device_name || deviceId;
  const handleWebRTCFailed = useCallback(
    (reason: string) => {
      streamTransport.setTransport('hls');
      // Scoped to the device: the id is per device (not per page) so six devices failing give
      // six bell rows instead of one that overwrites the others, and the link goes to that
      // device instead of whatever page the modal was opened from — a modal never changes the
      // URL, so `to` used to default to the heatmap the operator was looking at.
      const { message, ...options } = whepFallbackNotice({ hostName: host.host_name, deviceLabel, deviceId, reason });
      showError(message, options);
    },
    [streamTransport.setTransport, showError, host.host_name, deviceLabel, deviceId],
  );

  const [currentSegmentUrl, setCurrentSegmentUrl] = useState<string | null>(null);
  const capture = useRecCaptureActions(
    host,
    device,
    currentSegmentUrl,
    modes.isLiveMode,
    modes.restartMode,
    streamTransport.transport
  );

  const layout = useRecStreamLayout(
    modes.showRemote,
    modes.showWeb,
    isDesktopDevice,
    isControlActive
  );

  // The real rendered stream box, measured by RecStreamContainer. layout.finalStreamContainerDimensions
  // is a pre-render estimate that assumes a fixed 16:9 aspect and is wrong for portrait/landscape
  // mobile video (see comment in RecStreamContainer) — panels positioned on top of the video, like the
  // Android mobile tap/element overlay, need the measured box or they misalign in landscape.
  const [measuredStreamRect, setMeasuredStreamRect] = useState<{
    width: number;
    height: number;
    x: number;
    y: number;
  } | null>(null);
  const overlayStreamContainerDimensions = measuredStreamRect ?? layout.finalStreamContainerDimensions;
  const handleMeasuredAreaChange = useCallback(
    (rect: { width: number; height: number; x: number; y: number }) => {
      setMeasuredStreamRect((prev) =>
        prev &&
        prev.width === rect.width &&
        prev.height === rect.height &&
        prev.x === rect.x &&
        prev.y === rect.y
          ? prev
          : rect,
      );
    },
    [],
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

  // An AI prompt run is a testcase execution, which writes the same running.log as a
  // deployment — poll it during the run so the step/action/verification overlay shows.
  const [isAiExecuting, setIsAiExecuting] = useState(false);
  // One panel at a time from the Actions menu; the AI flag itself lives in useRecModalModes.
  const [activePanel, setActivePanel] = useState<'ai' | 'goto' | 'script' | 'voice' | null>(null);
  const { aiAgentMode, handleToggleAiAgent } = modes;
  const handleSelectPanel = useCallback(
    (panel: 'ai' | 'goto' | 'script' | 'voice') => {
      const closing = activePanel === panel;
      // Leaving the AI panel (closing it or switching to Go to node / Run script) turns AI mode off.
      if (activePanel === 'ai' && aiAgentMode) handleToggleAiAgent();
      if (closing) {
        setActivePanel(null);
        return;
      }
      if (panel === 'ai') {
        if (!isControlActive) {
          handleToggleAiAgent(); // shows the "take control first" warning
          return;
        }
        if (!aiAgentMode) handleToggleAiAgent();
      }
      setActivePanel(panel);
    },
    [activePanel, aiAgentMode, handleToggleAiAgent, isControlActive],
  );
  // AI mode can be reset by other modes (live/archive, monitoring, restart): follow it.
  useEffect(() => {
    if (activePanel === 'ai' && !aiAgentMode) setActivePanel(null);
  }, [activePanel, aiAgentMode]);
  useEffect(() => {
    if (!isControlActive) setActivePanel((p) => (p === 'goto' || p === 'script' || p === 'voice' ? null : p));
  }, [isControlActive]);
  const { logData: runningLogData } = useRunningLog(
    host,
    device?.device_id,
    Boolean((device?.has_running_deployment || isAiExecuting) && device?.device_id)
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

  // TASK-103: a caption_playback device is watched delay_s behind live from the archive, with captions.
  const captionPlayback = useMemo(() => {
    if (isControlActive || host.system_stats?.monitor_profiles?.[deviceId] !== CAPTION_PROFILE) return null;
    return { delayS: host.system_stats?.monitor_profile_params?.[deviceId]?.delay_s ?? DEFAULT_DELAY_S };
  }, [isControlActive, host.system_stats, deviceId]);

  const handleReleaseControl = useCallback(() => {
    modes.resetOnReleaseControl();
  }, [modes]);

  // Belt-and-braces for the Control button's `disabled`: a click that lands on a
  // stale render (capabilities just arrived, view re-rendered) must not lock a
  // device that has no remote to drive.
  const handleToggleControl = useCallback(() => {
    if (!canTakeControl) {
      showWarning('No remote configured for this device');
      return;
    }
    handleDeviceControl();
  }, [canTakeControl, handleDeviceControl, showWarning]);

  // LoL zones/inputs overlay: off by default, offered on desktop (host_vnc) devices only.
  const [lolOverlayOn, setLolOverlayOn] = useState(false);

  const [isMuted, setIsMuted] = useState<boolean>(true);
  const canReusePreviewStream =
    reusePreviewStream &&
    modes.isLiveMode &&
    !modes.restartMode &&
    (streamTransport.transport === 'hls' || device?.device_model !== 'host_vnc');
  const [persistentWhepStatus, setPersistentWhepStatus] = useState<WhepStatus>('idle');
  useEffect(() => {
    onPersistentStreamStateChange?.({
      muted: isMuted,
      interactive: isControlActive,
      shouldPause: quality.shouldPausePlayer,
      onPlayerReady: quality.handlePlayerReady,
      transport: streamTransport.transport,
      reconnectKey: quality.currentQuality,
      onWebRTCFailed: handleWebRTCFailed,
      onWebRTCStatusChange: setPersistentWhepStatus,
    });
  }, [isMuted, isControlActive, quality.shouldPausePlayer, quality.handlePlayerReady, quality.currentQuality, streamTransport.transport, handleWebRTCFailed, onPersistentStreamStateChange]);

  // Hide the captured preview poster once the modal player has actually started
  // playing, or after a safety timeout. Skips entirely if we had no poster to show.
  const [posterVisible, setPosterVisible] = useState<boolean>(!!initialPoster && !reusePreviewStream);
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
          streamTransport={streamTransport.transport}
          streamProtocol={device?.stream_protocol}
          onToggleStreamTransport={streamTransport.toggleTransport}
          isMuted={isMuted}
          isControlActive={isControlActive}
          isControlLoading={isControlLoading}
          canTakeControl={canTakeControl}
          showWeb={modes.showWeb}
          isDesktopDevice={isDesktopDevice}
          hasPowerControl={!!hasPowerControl}
          minimalControls={minimalControls}
          onScreenshot={capture.handleScreenshot}
          onOpenFullscreen={handleOpenFullscreen}
          onAIImageQuery={capture.handleAIImageQuery}
          onToggleLiveMode={modes.handleToggleLiveMode}
          onQualityChange={quality.handleQualityChange}
          onToggleMute={() => setIsMuted((prev) => !prev)}
          onToggleControl={handleToggleControl}
          onToggleMonitoring={modes.handleToggleMonitoring}
          lolOverlayAvailable={isDesktopDevice}
          lolOverlayOn={lolOverlayOn}
          onToggleLolOverlay={() => setLolOverlayOn((v) => !v)}
          onToggleRestart={modes.handleToggleRestart}
          activePanel={activePanel}
          onSelectPanel={handleSelectPanel}
          onToggleWeb={modes.handleToggleWeb}
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

          {captionPlayback ? (
            <CaptionPlaybackPlayer host={host} deviceId={deviceId} delayS={captionPlayback.delayS} />
          ) : (
          <RecStreamContainer
            host={host}
            device={device}
            streamUrl={streamUrl || undefined}
            isLoadingUrl={isLoadingUrl}
            urlError={urlError}
            monitoringMode={modes.monitoringMode}
            restartMode={modes.restartMode}
            isLiveMode={modes.isLiveMode}
            archiveSeek={initialArchiveTime != null ? { time: initialArchiveTime, nonce: 1 } : null}
            isControlActive={isControlActive}
            currentQuality={quality.currentQuality}
            isQualitySwitching={quality.isQualitySwitching}
            shouldPausePlayer={quality.shouldPausePlayer}
            streamTransport={streamTransport.transport}
            onWebRTCFailed={handleWebRTCFailed}
            isMuted={isMuted}
            isMobileModel={isMobileModel}
            showRemote={modes.showRemote}
            showWeb={modes.showWeb}
            finalStreamContainerDimensions={layout.finalStreamContainerDimensions}
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
            captureFps={monitoringData.captureFps}
            onMeasuredAreaChange={handleMeasuredAreaChange}
            persistentStream={canReusePreviewStream}
            onPersistentStreamTargetChange={onPersistentStreamTargetChange}
            persistentWebRtcStatus={persistentWhepStatus}
          />
          )}

          {lolOverlayOn && isDesktopDevice && <LolLiveOverlay host={host} />}

          <RecPanelManager
            host={host}
            device={device}
            showRemote={modes.showRemote}
            showWeb={modes.showWeb}
            isControlActive={isControlActive}
            isDesktopDevice={isDesktopDevice}
            finalStreamContainerDimensions={overlayStreamContainerDimensions}
            onReleaseControl={handleReleaseControl}
          />

          {activePanel === 'goto' && isControlActive && device && (
            <RecGotoNodePanel
              host={host}
              device={device}
              isControlActive={isControlActive}
              onClose={() => setActivePanel(null)}
            />
          )}

          {activePanel === 'voice' && isControlActive && device && (
            <RecVoicePanel
              host={host}
              device={device}
              isControlActive={isControlActive}
              onClose={() => setActivePanel(null)}
            />
          )}

          {activePanel === 'script' && isControlActive && device && (
            <RecRunScriptPanel
              host={host}
              device={device}
              isControlActive={isControlActive}
              onClose={() => setActivePanel(null)}
            />
          )}

          <AIExecutionPanel
            host={host}
            device={device!}
            isControlActive={isControlActive}
            isVisible={activePanel === 'ai' && modes.aiAgentMode && isControlActive}
            onClose={() => handleSelectPanel('ai')}
            onDisambiguationDataChange={handleDisambiguationDataChange}
            onExecutingChange={setIsAiExecuting}
          />

          {runningLogData && (
            <ScriptRunningOverlay
              logData={runningLogData}
              scriptNameRightOffset={layout.scriptNameRightOffset}
            />
          )}

          {/* Bottom-right carries the SCRIPT only. It used to print the owner here as well, and
              once DeviceLockBadge took the operator name to bottom-left the same words
              appeared in both corners — verified live, where a manual-control tile read the
              operator's name twice: once in the blue lock and once in this black pill. One
              corner, one fact: WHO is on the device (left, blue lock), WHAT is running
              (right, here). */}
          {!runningLogData && hasNamedDeployment && (
            <RunningScriptNameBadge
              scriptName={deploymentScriptLabel}
              sx={{
                right: layout.scriptNameRightOffset || 8,
                bottom: 8,
                zIndex: 25,
                // Same reasoning as the tile: RunningScriptNameBadge's 85% default is wide
                // enough to reach the blue lock at bottom-left on a narrow stream area.
                maxWidth: lockBadgeShows(lockOwnerLabel) ? '46%' : '85%',
              }}
              textSx={{ fontWeight: 'bold', fontSize: TYPOGRAPHY.caption.size }}
            />
          )}

          {/* Who holds the device, bottom-left (owner 2026-10-22). Names the operator only —
              the script name already has the bottom-right badge above. Suppressed while the
              running-log overlay is up: that overlay already owns this corner with its own
              lock chip, and the two stacked on top of each other unreadably. */}
          {!runningLogData && (
            <DeviceLockBadge
              ownerName={lockOwnerLabel}
              scriptLockActive={hasNamedDeployment}
              timing={lockTiming}
              sx={{ zIndex: 25 }}
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
