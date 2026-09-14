/**
 * Interactivity Manager Hook
 *
 * Coordinates automatic UI updates based on detected entities in user prompts and AI responses.
 * Provides pre-prompt and post-response interactivity to make the AgentChat experience more fluid.
 */

import { useCallback, useState } from 'react';
import { analyzeTextForEntities, getRecommendedUIActions, DetectedEntities, AvailableEntities } from '../../utils/entityDetection';
import { useHostData } from '../useHostManager';

export interface InteractivityState {
  isAnalyzing: boolean;
  lastDetectedEntities: DetectedEntities | null;
  autoSelectedItems: {
    device?: boolean;
    userinterface?: boolean;
    testcase?: boolean;
    campaign?: boolean;
  };
}

export interface UIUpdateActions {
  setSelectedDevice: (device: string) => void;
  setSelectedUserInterface: (ui: string) => void;
  setSelectedTestCase: (testcase: string) => void;
  setSelectedCampaign: (campaign: string) => void;
  setShowContentViewer: (show: boolean) => void;
  setActiveContentTab: (tab: 'device-preview' | 'navigation' | 'testcase' | 'campaign' | 'heatmap' | 'alerts') => void;
}

export const useInteractivityManager = (
  uiActions: UIUpdateActions,
  currentSelections: {
    device?: string;
    userinterface?: string;
    testcase?: string;
    campaign?: string;
  },
  testCaseList: Array<{ testcase_id: string; testcase_name: string }>,
  campaignList: Array<{ campaign_id: string; campaign_name: string }>,
  availableUserInterfaces: Array<{ name: string; id?: string }>
) => {
  const [state, setState] = useState<InteractivityState>({
    isAnalyzing: false,
    lastDetectedEntities: null,
    autoSelectedItems: {}
  });

  const { getAllHosts } = useHostData();

  /**
   * Build available entities object for detection
   */
  const buildAvailableEntities = useCallback((): AvailableEntities => {
    const hosts = getAllHosts();

    // Flatten devices from all hosts
    const devices = hosts.flatMap(host =>
      (host.devices || []).map(device => ({
        device_id: device.device_id,
        device_name: device.device_name || device.device_id,
        host_name: host.host_name
      }))
    );

    return {
      devices,
      hosts: hosts.map(h => ({ host_name: h.host_name, host_id: h.host_name })),
      userinterfaces: availableUserInterfaces.map(ui => ({ name: ui.name, id: ui.id })),
      testcases: testCaseList,
      campaigns: campaignList
    };
  }, [getAllHosts, availableUserInterfaces, testCaseList, campaignList]);

  /**
   * Apply detected entities to UI state
   */
  const applyEntitiesToUI = useCallback((detectedEntities: DetectedEntities) => {
    const recommendations = getRecommendedUIActions(detectedEntities, currentSelections);

    // Skip if confidence is too low
    if (recommendations.confidence < 0.6) {
      console.log('[Interactivity] Low confidence, skipping auto-updates');
      return;
    }

    console.log('[Interactivity] Applying detected entities:', detectedEntities);
    console.log('[Interactivity] UI recommendations:', recommendations);

    // Track what we're auto-selecting
    const autoSelected: typeof state.autoSelectedItems = {};

    // Apply device selection
    if (recommendations.updateSelections.device) {
      const deviceValue = recommendations.updateSelections.device;
      // Find the host for this device to create the combined "host:device" format
      const hosts = getAllHosts();
      for (const host of hosts) {
        const device = host.devices?.find(d => d.device_id === deviceValue);
        if (device) {
          uiActions.setSelectedDevice(deviceValue); // Set device_id
          autoSelected.device = true;
          break;
        }
      }
    }

    // Apply userinterface selection
    if (recommendations.updateSelections.userinterface) {
      uiActions.setSelectedUserInterface(recommendations.updateSelections.userinterface);
      autoSelected.userinterface = true;
    }

    // Apply testcase selection
    if (recommendations.updateSelections.testcase) {
      uiActions.setSelectedTestCase(recommendations.updateSelections.testcase);
      autoSelected.testcase = true;
    }

    // Apply campaign selection
    if (recommendations.updateSelections.campaign) {
      uiActions.setSelectedCampaign(recommendations.updateSelections.campaign);
      autoSelected.campaign = true;
    }

    // Show content viewer if recommended
    if (recommendations.showContentViewer) {
      uiActions.setShowContentViewer(true);
      uiActions.setActiveContentTab(recommendations.activeTab);
    }

    // Update state
    setState(prev => ({
      ...prev,
      lastDetectedEntities: detectedEntities,
      autoSelectedItems: { ...prev.autoSelectedItems, ...autoSelected }
    }));

    // Clear auto-selection flags after a delay (visual feedback)
    setTimeout(() => {
      setState(prev => ({
        ...prev,
        autoSelectedItems: {}
      }));
    }, 3000);

  }, [buildAvailableEntities, currentSelections, getAllHosts, uiActions]);

  /**
   * Analyze text and apply to UI (main entry point)
   */
  const analyzeAndApply = useCallback(async (text: string, source: 'prompt' | 'response') => {
    if (!text.trim()) return;

    setState(prev => ({ ...prev, isAnalyzing: true }));

    try {
      console.log(`[Interactivity] Analyzing ${source}:`, text.substring(0, 100) + '...');

      const availableEntities = buildAvailableEntities();
      const detectedEntities = analyzeTextForEntities(text, availableEntities);

      if (Object.keys(detectedEntities).length > 0) {
        console.log(`[Interactivity] Detected entities in ${source}:`, detectedEntities);
        applyEntitiesToUI(detectedEntities);
      } else {
        console.log(`[Interactivity] No entities detected in ${source}`);
      }
    } catch (error) {
      console.error('[Interactivity] Error analyzing text:', error);
    } finally {
      setState(prev => ({ ...prev, isAnalyzing: false }));
    }
  }, [buildAvailableEntities, applyEntitiesToUI]);

  /**
   * Pre-prompt analysis (before sending to AI)
   */
  const analyzePrompt = useCallback((prompt: string) => {
    return analyzeAndApply(prompt, 'prompt');
  }, [analyzeAndApply]);

  /**
   * Post-response analysis (after AI responds)
   */
  const analyzeResponse = useCallback((response: string) => {
    return analyzeAndApply(response, 'response');
  }, [analyzeAndApply]);

  /**
   * Clear auto-selection state
   */
  const clearAutoSelections = useCallback(() => {
    setState(prev => ({
      ...prev,
      autoSelectedItems: {},
      lastDetectedEntities: null
    }));
  }, []);

  /**
   * Get visual feedback for auto-selected items
   */
  const getAutoSelectionFeedback = useCallback(() => {
    return {
      device: state.autoSelectedItems.device,
      userinterface: state.autoSelectedItems.userinterface,
      testcase: state.autoSelectedItems.testcase,
      campaign: state.autoSelectedItems.campaign
    };
  }, [state.autoSelectedItems]);

  return {
    // State
    isAnalyzing: state.isAnalyzing,
    lastDetectedEntities: state.lastDetectedEntities,

    // Actions
    analyzePrompt,
    analyzeResponse,
    clearAutoSelections,

    // Feedback
    getAutoSelectionFeedback
  };
};
