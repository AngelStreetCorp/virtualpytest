import { useState, useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from 'react';

import { useToast } from '../useToast';

export interface RecModalModesState {
  showRemote: boolean;
  showWeb: boolean;
  monitoringMode: boolean;
  aiAgentMode: boolean;
  restartMode: boolean;
  isLiveMode: boolean;
}

export interface RecModalModesActions {
  setShowRemote: Dispatch<SetStateAction<boolean>>;
  setShowWeb: Dispatch<SetStateAction<boolean>>;
  handleToggleRemote: () => void;
  handleToggleWeb: () => void;
  handleToggleMonitoring: () => void;
  handleToggleAiAgent: () => void;
  handleToggleRestart: () => void;
  handleToggleLiveMode: () => void;
  resetOnReleaseControl: () => void;
  resetOnClose: () => void;
}

/**
 * Manages REC modal mode toggles (remote, web, monitoring, AI agent, restart, live/archive).
 * Mutually exclusive modes: enabling one disables others where appropriate.
 */
export const useRecModalModes = (
  showRemoteByDefault: boolean,
  isControlActive: boolean,
  isDesktopDevice: boolean
): RecModalModesState & RecModalModesActions => {
  const [showRemote, setShowRemote] = useState<boolean>(showRemoteByDefault);
  const [showWeb, setShowWeb] = useState<boolean>(false);
  const [monitoringMode, setMonitoringMode] = useState<boolean>(false);
  const [aiAgentMode, setAiAgentMode] = useState<boolean>(false);
  const [restartMode, setRestartMode] = useState<boolean>(false);
  const [isLiveMode, setIsLiveMode] = useState<boolean>(true);
  const { showWarning } = useToast();

  const prevControlActiveRef = useRef<boolean>(isControlActive);
  useEffect(() => {
    if (isControlActive && !prevControlActiveRef.current) {
      if (isDesktopDevice) {
        setShowWeb(true);
      } else {
        setShowRemote(true);
      }
    }
    prevControlActiveRef.current = isControlActive;
  }, [isControlActive, isDesktopDevice]);

  const handleToggleRemote = useCallback(() => {
    if (!isControlActive) {
      showWarning('Please take control of the device first');
      return;
    }
    setShowRemote((prev) => !prev);
  }, [isControlActive, showWarning]);

  const handleToggleWeb = useCallback(() => {
    if (!isControlActive) {
      showWarning('Please take control of the device first');
      return;
    }
    setShowWeb((prev) => !prev);
  }, [isControlActive, showWarning]);

  const handleToggleMonitoring = useCallback(() => {
    setMonitoringMode((prev) => {
      const newMode = !prev;
      if (newMode) {
        setAiAgentMode(false);
        setRestartMode(false);
      }
      return newMode;
    });
  }, []);

  const handleToggleAiAgent = useCallback(() => {
    if (!isControlActive) {
      showWarning('Please take control of the device first to enable AI agent');
      return;
    }
    setAiAgentMode((prev) => {
      const newMode = !prev;
      if (newMode) {
        setMonitoringMode(false);
        setRestartMode(false);
      }
      return newMode;
    });
  }, [isControlActive, showWarning]);

  const handleToggleRestart = useCallback(() => {
    if (!isControlActive) {
      showWarning('Please take control of the device first to enable restart mode');
      return;
    }
    setRestartMode((prev) => {
      const newMode = !prev;
      if (newMode) {
        setMonitoringMode(false);
        setAiAgentMode(false);
      }
      return newMode;
    });
  }, [isControlActive, showWarning]);

  const handleToggleLiveMode = useCallback(() => {
    setIsLiveMode((prev) => {
      const newMode = !prev;
      if (!newMode) {
        setShowRemote(false);
        setAiAgentMode(false);
        setRestartMode(false);
        setMonitoringMode(false);
      }
      return newMode;
    });
  }, []);

  const resetOnReleaseControl = useCallback(() => {
    setShowRemote(false);
    setShowWeb(false);
  }, []);

  const resetOnClose = useCallback(() => {
    setShowRemote(false);
    setShowWeb(false);
    setMonitoringMode(false);
    setAiAgentMode(false);
    setRestartMode(false);
  }, []);

  return {
    showRemote,
    showWeb,
    monitoringMode,
    aiAgentMode,
    restartMode,
    isLiveMode,
    setShowRemote,
    setShowWeb,
    handleToggleRemote,
    handleToggleWeb,
    handleToggleMonitoring,
    handleToggleAiAgent,
    handleToggleRestart,
    handleToggleLiveMode,
    resetOnReleaseControl,
    resetOnClose,
  };
};
