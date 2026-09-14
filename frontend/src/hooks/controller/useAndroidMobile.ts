import { useState, useRef, useCallback, useMemo, useEffect } from 'react';

import { Host } from '../../types/common/Host_Types';
import { AndroidElement, AndroidApp } from '../../types/controller/Remote_Types';

import { useControllerApi } from './useControllerApi';
interface AndroidMobileLayoutConfig {
  containerWidth: number;
  containerHeight: number;
  deviceResolution: {
    width: number;
    height: number;
  };
  overlayConfig: {
    defaultPosition: {
      left: string;
      top: string;
    };
    defaultScale: {
      x: number;
      y: number;
    };
  };
  autoDumpDelay: number;
}

export function useAndroidMobile(selectedHost: Host | null, deviceId: string | null, onOrientationChange?: (isLandscape: boolean) => void) {
  // Simple validation - no complex memoization
  if (!selectedHost || !deviceId) {
    console.warn('[@hook:useAndroidMobile] Missing host or deviceId');
  }

  // Configuration
  const layoutConfig: AndroidMobileLayoutConfig = useMemo(
    () => ({
      containerWidth: 300,
      containerHeight: 600,
      deviceResolution: {
        width: 1080,
        height: 2340,
      },
      overlayConfig: {
        defaultPosition: {
          left: '74px',
          top: '186px',
        },
        defaultScale: {
          x: 0.198,
          y: 0.195,
        },
      },
      autoDumpDelay: 1200,
    }),
    [],
  );

  // State management - initialize with default connection state
  const [isConnected_internal, setIsConnected] = useState(false);
  const [androidScreenshot, setAndroidScreenshot] = useState<string | null>(null);
  const [androidElements, setAndroidElements] = useState<AndroidElement[]>([]);
  const [androidApps, setAndroidApps] = useState<AndroidApp[]>([]);
  const [showOverlay, setShowOverlay] = useState(false);
  const [selectedElement, setSelectedElement] = useState('');
  const [selectedApp, setSelectedApp] = useState('');
  const [isDumpingUI, setIsDumpingUI] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isRefreshingApps, setIsRefreshingApps] = useState(false);
  
  // Manual orientation state - default to portrait
  const [isLandscape, setIsLandscape] = useState(false);

  // Auto-connect when host and deviceId are available
  useEffect(() => {
    if (selectedHost && deviceId) {
      setIsConnected(true);
    } else {
      setIsConnected(false);
    }
  }, [selectedHost, deviceId]);

  // Reset overlay state on mount or when host/deviceId changes (e.g., release and take control)
  useEffect(() => {
    console.log('[@hook:useAndroidMobile] Resetting overlay state (mount or host/device change)');
    setAndroidElements([]);
    setShowOverlay(false);
    setSelectedElement('');
    setIsLandscape(false); // Reset orientation to portrait
  }, [selectedHost, deviceId]);

  // Toggle orientation manually
  const toggleOrientation = useCallback(() => {
    setIsLandscape(prev => {
      const newOrientation = !prev;
      console.log(`[@hook:useAndroidMobile] Manual orientation toggle: ${newOrientation ? 'landscape' : 'portrait'}`);
      onOrientationChange?.(newOrientation);
      return newOrientation;
    });
  }, [onOrientationChange]);

  // Note: Debug logging removed to reduce console spam

  const screenshotRef = useRef<HTMLImageElement>(null);
  const { postToHost, executeRemoteCommand } = useControllerApi(selectedHost, deviceId);

  // Note: Hook lifecycle logging removed to reduce console spam

  // Action handlers
  const handleTap = useCallback(
    async (x: number, y: number) => {
      if (!selectedHost) {
        console.warn('[@hook:useAndroidMobile] No host data available for tap action');
        return { success: false, error: 'No host data available' };
      }

      try {
        const result = await postToHost('/server/remote/tapCoordinates', {
          x,
          y,
        }, { includeDeviceId: true });
        return result;
      } catch (error) {
        console.error('[@hook:useAndroidMobile] Tap error:', error);
        return { success: false, error: 'Network error' };
      }
    },
    [selectedHost, deviceId],
  );

  const refreshScreenshot = useCallback(async () => {
    if (!selectedHost) {
      console.warn('[@hook:useAndroidMobile] No host data available for screenshot');
      return;
    }

    try {
      const result = await postToHost('/server/remote/takeScreenshot', {}, { includeDeviceId: true });
      if (result.success && result.screenshot) {
        setAndroidScreenshot(result.screenshot);
      }
    } catch (error) {
      console.error('[@hook:useAndroidMobile] Screenshot error:', error);
    }
  }, [selectedHost, deviceId]);

  const refreshElements = useCallback(async () => {
    if (!selectedHost) {
      console.warn('[@hook:useAndroidMobile] No host data available for elements');
      return;
    }

    setIsDumpingUI(true);
    try {
      const result = await postToHost('/server/remote/screenshotAndDump', {}, { includeDeviceId: true });
      if (result.success) {
        // Update elements if available
        if (result.elements) {
          setAndroidElements(result.elements);
          console.log(`[@hook:useAndroidMobile] Updated ${result.elements.length} UI elements`);
          
          // Copy dump to clipboard - use the same format as backend logs
          try {
            const dumpText = result.elements.map((el: any, index: number) => {
              // Get display name (same priority as backend logs: contentDesc → text → className)
              let name = '';
              if (el.contentDesc && el.contentDesc !== '<no content-desc>') {
                name = el.contentDesc;
              } else if (el.text && el.text !== '<no text>') {
                name = `"${el.text}"`;
              } else {
                name = el.className ? el.className.split('.').pop() : 'Unknown';
              }
              
              // Calculate position from bounds object (backend already parsed it)
              const x = el.bounds.left;
              const y = el.bounds.top;
              const width = el.bounds.right - el.bounds.left;
              const height = el.bounds.bottom - el.bounds.top;
              
              // Use same format as backend logs
              const xpathInfo = el.xpath ? ` | XPath: ${el.xpath}` : '';
              return `${index + 1}. ${name} | Index: ${el.id} | Order: ${index + 1} | X: ${x} | Y: ${y} | Width: ${width} | Height: ${height}${xpathInfo}`;
            }).join('\n');
            
            await navigator.clipboard.writeText(dumpText);
            console.log(`[@hook:useAndroidMobile] ✅ Copied ${result.elements.length} elements to clipboard`);
          } catch (clipboardError) {
            console.error('[@hook:useAndroidMobile] Failed to copy dump to clipboard:', clipboardError);
            // Show error to user if clipboard fails (could be permissions or HTTPS requirement)
            alert('Failed to copy to clipboard. Make sure you are using HTTPS or localhost.');
          }
        }
        

        
        // Update screenshot if available
        if (result.screenshot) {
          setAndroidScreenshot(result.screenshot);
        }
      }
    } catch (error) {
      console.error('[@hook:useAndroidMobile] Elements error:', error);
    } finally {
      setIsDumpingUI(false);
    }
  }, [selectedHost, deviceId]);

  const refreshApps = useCallback(async () => {
    if (!selectedHost) {
      console.warn('[@hook:useAndroidMobile] No host data available for apps');
      return;
    }

    setIsRefreshingApps(true);
    try {
      const result = await postToHost('/server/remote/getApps', {}, { includeDeviceId: true });
      if (result.success && result.apps) {
        setAndroidApps(result.apps);
      }
    } catch (error) {
      console.error('[@hook:useAndroidMobile] Apps error:', error);
    } finally {
      setIsRefreshingApps(false);
    }
  }, [selectedHost, deviceId]);

  // Additional methods expected by the component
  const handleDisconnect = useCallback(async () => {
    console.log('[@hook:useAndroidMobile] Disconnecting...');
    setIsDisconnecting(true);
    // Add disconnect logic here if needed
    setIsConnected(false);
    setIsDisconnecting(false);
  }, []);

  const handleOverlayElementClick = useCallback(
    async (element: AndroidElement) => {
      if (!selectedHost) {
        console.warn('[@hook:useAndroidMobile] No host data available for element click');
        return;
      }

      console.log(`[@hook:useAndroidMobile] Element clicked: ${element.id}`);
      
      // Copy element info to clipboard - same format as backend logs
      try {
        // Get display name
        let name = '';
        if (element.contentDesc && element.contentDesc !== '<no content-desc>') {
          name = element.contentDesc;
        } else if (element.text && element.text !== '<no text>') {
          name = `"${element.text}"`;
        } else {
          name = element.className ? (element.className.split('.').pop() || 'Unknown') : 'Unknown';
        }
        
        // Calculate position from bounds object
        const x = element.bounds.left;
        const y = element.bounds.top;
        const width = element.bounds.right - element.bounds.left;
        const height = element.bounds.bottom - element.bounds.top;
        
        // Build element info - simple and clean like backend logs
        const elementInfo = `Element: ${name} | Index: ${element.id} | X: ${x} | Y: ${y} | Width: ${width} | Height: ${height}${element.xpath ? ` | XPath: ${element.xpath}` : ''}`;
        
        await navigator.clipboard.writeText(elementInfo);
        console.log(`[@hook:useAndroidMobile] ✅ Copied element info to clipboard: ${elementInfo}`);
      } catch (clipboardError) {
        console.error('[@hook:useAndroidMobile] Failed to copy element info to clipboard:', clipboardError);
      }
      
      try {
        const result = await executeRemoteCommand(
          'click_element_by_id',
          { element_id: element.id },
          {},
          { includeDeviceId: true },
        );
        console.log('[@hook:useAndroidMobile] Element click result:', result);
      } catch (error) {
        console.error('[@hook:useAndroidMobile] Element click error:', error);
      }
    },
    [selectedHost, deviceId],
  );

  const handleRemoteCommand = useCallback(
    async (command: string, params?: any) => {
      if (!selectedHost) {
        console.warn('[@hook:useAndroidMobile] No host data available for remote command');
        return { success: false, error: 'No host data available' };
      }

      console.log(`[@hook:useAndroidMobile] Executing remote command: ${command}`, params);
      try {
        let requestBody;

        if (command === 'LAUNCH_APP' && params?.package) {
          requestBody = {
            host_name: selectedHost.host_name,
            device_id: deviceId,
            command: 'launch_app',
            params: { package: params.package },
          };
        } else if (command.startsWith('SWIPE_')) {
          // Handle swipe commands properly - send as command, not key
          requestBody = {
            host_name: selectedHost.host_name,
            device_id: deviceId,
            command: command, // Send swipe commands directly as commands
            params: params || {},
          };
        } else if (command === 'CLICK_ELEMENT_BY_ID') {
          // Click by element ID - use click_element_by_id
          requestBody = {
            host_name: selectedHost.host_name,
            device_id: deviceId,
            command: 'click_element_by_id',
            params: params || {},
          };
        } else if (command === 'CLICK_ELEMENT_BY_TEXT') {
          // Click by text - use click_element (backend expects 'element_id' param for text search)
          requestBody = {
            host_name: selectedHost.host_name,
            device_id: deviceId,
            command: 'click_element',
            params: { element_id: params?.text || params?.element_id },
          };
        } else if (command === 'FIND_ELEMENT') {
          // Find element - use dump_elements and search in result
          requestBody = {
            host_name: selectedHost.host_name,
            device_id: deviceId,
            command: 'find_element',
            params: params || {},
          };
        } else {
          requestBody = {
            host_name: selectedHost.host_name,
            device_id: deviceId,
            command: 'press_key',
            params: { key: command },
          };
        }

        const result = await executeRemoteCommand(
          requestBody.command,
          requestBody.params || {},
          {},
          { includeDeviceId: true },
        );
        console.log('[@hook:useAndroidMobile] Remote command result:', result);
        return result;
      } catch (error) {
        console.error('[@hook:useAndroidMobile] Remote command error:', error);
        return { success: false, error: String(error) };
      }
    },
    [selectedHost, deviceId],
  );

  const clearElements = useCallback(() => {
    console.log('[@hook:useAndroidMobile] Clearing elements');
    setAndroidElements([]);
    setSelectedElement('');
    setShowOverlay(false);
  }, []);

  const handleGetApps = useCallback(async () => {
    await refreshApps();
  }, [refreshApps]);

  const handleDumpUIWithLoading = useCallback(async () => {
    await refreshElements();
  }, [refreshElements]);

  // Session info
  const session = useMemo(
    () => ({
      connected: isConnected_internal,
      connectionInfo: isConnected_internal ? 'Connected' : 'Disconnected',
    }),
    [isConnected_internal],
  );

  return {
    // Configuration
    layoutConfig,

    // State
    isConnected: isConnected_internal,
    androidScreenshot,
    androidElements,
    androidApps,
    showOverlay,
    selectedElement,
    selectedApp,
    isDumpingUI,
    isDisconnecting,
    isRefreshingApps,
    
    // Manual orientation
    isLandscape,
    toggleOrientation,

    // Refs
    screenshotRef,

    // Actions
    handleTap,
    refreshScreenshot,
    refreshElements,
    refreshApps,
    handleDisconnect,
    handleOverlayElementClick,
    handleRemoteCommand,
    clearElements,
    handleGetApps,
    handleDumpUIWithLoading,

    // Setters
    setShowOverlay,
    setSelectedElement,
    setSelectedApp,
    setIsConnected,
    setIsDisconnecting,

    // Session info
    session,

    // Host and device data
    hostData: selectedHost,
    deviceData: selectedHost?.devices?.find((d) => d.device_id === deviceId),
  };
}
