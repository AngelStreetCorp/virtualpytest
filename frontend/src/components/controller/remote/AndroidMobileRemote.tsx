import RefreshIcon from '@mui/icons-material/Refresh';
import {
  Box,
  Button,
  Typography,
  CircularProgress,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  TextField,
  DialogTitle,
  DialogContent,
  DialogActions,
  Snackbar,
  Alert,
  Tooltip,
} from '@mui/material';
import React from 'react';
import { createPortal } from 'react-dom';

import { StyledDialog } from '../../common/StyledDialog';
import { DEFAULT_DEVICE_RESOLUTION } from '../../../config/deviceResolutions';
import { hdmiStreamMobileConfig, HDMI_STREAM_HEADER_HEIGHT } from '../../../config/av/hdmiStream';
import { useAndroidMobile } from '../../../hooks/controller/useAndroidMobile';
import { Host } from '../../../types/common/Host_Types';
import { PanelInfo } from '../../../types/controller/Panel_Types';
import { AndroidElement } from '../../../types/controller/Remote_Types';

import { AndroidMobileOverlay } from './AndroidMobileOverlay';

// adb returns package names only, so the launcher shows a readable name derived from the package
// (full package name on hover). Overrides cover packages whose last segment reads badly.
const APP_NAME_OVERRIDES: Record<string, string> = {
  'com.android.chrome': 'Chrome',
  'com.android.vending': 'Play Store',
  'com.google.android.gm': 'Gmail',
  'com.google.android.youtube': 'YouTube',
  'com.google.android.apps.youtube.music': 'YouTube Music',
  'com.spotify.music': 'Spotify',
  'com.whatsapp': 'WhatsApp',
};
const PACKAGE_NOISE = new Set([
  'com', 'org', 'net', 'android', 'google', 'apps', 'app', 'samsung', 'sec', 'microsoft',
  'office', 'mobile', 'client', 'mediaclient', 'activity', 'main', 'launcher',
]);

const appDisplayName = (packageName: string, label: string): string => {
  if (label && label !== packageName) return label;
  if (APP_NAME_OVERRIDES[packageName]) return APP_NAME_OVERRIDES[packageName];
  const parts = packageName.split('.');
  const name = parts.filter((p) => !PACKAGE_NOISE.has(p.toLowerCase())).pop() ?? parts[parts.length - 1];
  return name
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\b\w/g, (c) => c.toUpperCase());
};

interface AndroidMobileRemoteProps {
  host: Host;
  deviceId: string; // Device ID to select the correct device and make API calls
  onDisconnectComplete?: () => void;
  sx?: any;
  // Simplified panel state props
  isCollapsed: boolean;
  panelWidth: string;
  panelHeight: string;
  deviceResolution: { width: number; height: number };
  // Stream collapsed state for overlay coordination
  streamCollapsed?: boolean;
  // Stream minimized state for overlay coordination
  streamMinimized?: boolean;
  // Stream hidden state for overlay coordination
  streamHidden?: boolean;
  // Current capture mode from HDMIStream
  captureMode?: 'stream' | 'screenshot' | 'video';
  // Verification editor visibility state
  isVerificationVisible?: boolean;
  // NEW: Stream container dimensions for modal context
  streamContainerDimensions?: {
    width: number;
    height: number;
    x: number;
    y: number;
  };
  // NEW: Dynamic stream position for overlay alignment
  streamPositionLeft?: string;
  streamPositionBottom?: string;
  // NEW: Orientation change callback to sync with HDMI stream
  onOrientationChange?: (isLandscape: boolean) => void;
  // NEW: Control overlay visibility from parent
  showOverlay?: boolean;
}

export const AndroidMobileRemote = React.memo(
  function AndroidMobileRemote({
    host,
    deviceId,
  
    isCollapsed,
    panelWidth,
    panelHeight,
    deviceResolution,
    streamCollapsed,
    streamMinimized = false,
    streamHidden = false,
    captureMode = 'stream',
    isVerificationVisible = false,
    streamContainerDimensions,
    streamPositionLeft,
    streamPositionBottom,
    onOrientationChange,
    showOverlay = true,
  }: AndroidMobileRemoteProps) {
    const hookResult = useAndroidMobile(host, deviceId, onOrientationChange);

    const {
      // State
      androidElements,
      androidApps,
      selectedElement,
      selectedApp,
      isDumpingUI,
      isRefreshingApps,

      // Manual orientation
      isLandscape,
      screenSize,
      checkOrientation,

      // Actions
      handleOverlayElementClick,
      handleRemoteCommand,
      clearElements,
      handleGetApps,
      handleDumpUIWithLoading,

      // Setters
      setSelectedElement,
      setSelectedApp,

      // Configuration
      layoutConfig,

      // Session info
      session,
    } = hookResult;

    const launcherApps = React.useMemo(
      () =>
        androidApps
          .map((app) => ({ ...app, name: appDisplayName(app.packageName, app.label) }))
          .sort((a, b) => a.name.localeCompare(b.name)),
      [androidApps],
    );

    // Keeps the app-launcher menu the width of its Select instead of the longest package name
    const appSelectRef = React.useRef<HTMLDivElement>(null);

    // Local state for element interaction
    const [elementActionType, setElementActionType] = React.useState<'click_id' | 'click_text' | 'find'>('click_id');
    const [elementActionInput, setElementActionInput] = React.useState('');
    const [typeTextInput, setTypeTextInput] = React.useState('');
    const [isTyping, setIsTyping] = React.useState(false);
    const [isExecutingAction, setIsExecutingAction] = React.useState(false);
    const [actionStatus, setActionStatus] = React.useState<'idle' | 'success' | 'error'>('idle');

    // Modal and toast state
    const [modalOpen, setModalOpen] = React.useState(false);
    const [modalTitle, setModalTitle] = React.useState('');
    const [modalContent, setModalContent] = React.useState<any>(null);
    const [toastOpen, setToastOpen] = React.useState(false);
    const [toastMessage, setToastMessage] = React.useState('');
    const [toastSeverity, setToastSeverity] = React.useState<'success' | 'error'>('success');
    const [waitingForDump, setWaitingForDump] = React.useState(false);

    // Watch for dump completion
    React.useEffect(() => {
      if (waitingForDump && !isDumpingUI) {
        // Dump just completed
        setWaitingForDump(false);
        
        if (androidElements.length > 0) {
          setToastMessage(`✅ Dump succeeded! ${androidElements.length} elements copied to clipboard`);
          setToastSeverity('success');
          setToastOpen(true);
          
          // Only show modal on success
          setModalTitle(`UI Dump (${androidElements.length} elements)`);
          setModalContent(androidElements);
          setModalOpen(true);
        } else {
          // Only show toast on failure (no modal)
          setToastMessage('❌ Dump failed or no elements found');
          setToastSeverity('error');
          setToastOpen(true);
        }
      }
    }, [isDumpingUI, androidElements, waitingForDump]);

    // Debug: Log orientation changes in remote component
    React.useEffect(() => {
      console.log(`[@component:AndroidMobileRemote] Orientation: ${isLandscape ? 'landscape' : 'portrait'}`);
      console.log(`[@component:AndroidMobileRemote] onOrientationChange callback:`, onOrientationChange ? 'defined' : 'undefined');
      // Notify parent component about orientation change
      if (onOrientationChange) {
        console.log(`[@component:AndroidMobileRemote] Calling onOrientationChange with:`, isLandscape);
        onOrientationChange(isLandscape);
      }
    }, [isLandscape, onOrientationChange]);

    // Reset action status after 3 seconds
    React.useEffect(() => {
      if (actionStatus !== 'idle') {
        const timer = setTimeout(() => setActionStatus('idle'), 3000);
        return () => clearTimeout(timer);
      }
    }, [actionStatus]);

    // Handle element interaction action execution
    // Enter: types the field's text (if any) then presses Enter on the phone
    const handleTypeEnter = async () => {
      if (isTyping) return;
      setIsTyping(true);
      try {
        if (typeTextInput) {
          const result = await handleRemoteCommand('INPUT_TEXT', { text: typeTextInput });
          if (!result?.success) {
            setToastMessage(`Text input failed${result?.error ? `: ${result.error}` : ''}`);
            setToastSeverity('error');
            setToastOpen(true);
            return;
          }
          setTypeTextInput('');
        }
        await handleRemoteCommand('ENTER');
      } finally {
        setIsTyping(false);
      }
    };

    const handleElementAction = async () => {
      if (!elementActionInput.trim() || isExecutingAction || isDumpingUI) return;

      setIsExecutingAction(true);
      setActionStatus('idle');

      try {
        let result;
        if (elementActionType === 'click_id') {
          result = await handleRemoteCommand('CLICK_ELEMENT_BY_ID', { element_id: elementActionInput });
        } else if (elementActionType === 'click_text') {
          result = await handleRemoteCommand('CLICK_ELEMENT_BY_TEXT', { text: elementActionInput });
        } else {
          result = await handleRemoteCommand('FIND_ELEMENT', { search_term: elementActionInput });
        }

        // Set visual feedback
        setActionStatus(result?.success ? 'success' : 'error');

        // For find action, show modal with results
        if (elementActionType === 'find') {
          if (result?.success && result?.matches) {
            // Auto-copy to clipboard
            try {
              const resultText = JSON.stringify(result, null, 2);
              await navigator.clipboard.writeText(resultText);
            } catch (error) {
              console.error('Failed to copy:', error);
            }

            // Show success toast
            setToastMessage(`✅ Found ${result.matches.length} element(s)! Copied to clipboard`);
            setToastSeverity('success');
            setToastOpen(true);

            // Show modal with results
            setModalTitle(`Found ${result.matches.length} Element(s)`);
            setModalContent(result.matches);
            setModalOpen(true);
          } else {
            setToastMessage('❌ No elements found');
            setToastSeverity('error');
            setToastOpen(true);
          }
        }
      } catch (error) {
        console.error('Element action error:', error);
        setActionStatus('error');
        setToastMessage('❌ Action failed');
        setToastSeverity('error');
        setToastOpen(true);
      } finally {
        setIsExecutingAction(false);
      }
    };

    // Override dump UI handler to show modal
    const handleDumpUIWithModal = async () => {
      setWaitingForDump(true);
      await handleDumpUIWithLoading();
    };

    // Debug logging for elements state
    React.useEffect(() => {
      // Only log when elements count changes significantly or when there are errors
      if (androidElements.length > 0 && androidElements.length % 10 === 0) {
        console.log('[@component:AndroidMobileRemote] Elements loaded:', androidElements.length);
      }
    }, [androidElements]);

    // Panel integration - prepare panelInfo for overlay
    const overlayScreen = screenSize ?? layoutConfig.deviceResolution;

    const panelInfo: PanelInfo | undefined = React.useMemo(() => {
      // Skip unnecessary recalculations if missing required props
      if (!panelWidth || !panelHeight || !deviceResolution) {
        return undefined;
      }

      // NEW: Use stream container dimensions if provided (modal context)
      if (streamContainerDimensions) {
        const info = {
          position: {
            x: streamContainerDimensions.x,
            y: streamContainerDimensions.y,
          },
          size: {
            width: streamContainerDimensions.width,
            height: streamContainerDimensions.height,
          },
          deviceResolution: DEFAULT_DEVICE_RESOLUTION, // Keep HDMI resolution for overlay positioning
          isCollapsed: false, // In modal context, stream is always expanded
        };
        console.log('[@AndroidMobileRemote] panelInfo with streamContainerDimensions:', info);
        return info;
      }

      // EXISTING: Use HDMI stream config for floating panel context
      // Keep HDMI stream resolution for overlay positioning (visual alignment)
      const hdmiStreamResolution = DEFAULT_DEVICE_RESOLUTION;

      // Get HDMI stream dimensions from config based on stream collapsed state (not panel state)
      const streamConfig = hdmiStreamMobileConfig.panel_layout;
      const currentStreamConfig = streamCollapsed ? streamConfig.collapsed : streamConfig.expanded;

      // Parse dimensions from config or props
      const parsePixels = (value: string) => parseInt(value.replace('px', ''), 10);

      // Use stream panel dimensions from config, not remote panel dimensions
      const streamPanelWidth = parsePixels(currentStreamConfig.width);
      const streamPanelHeight = parsePixels(currentStreamConfig.height);

      // Calculate actual stream content area
      // Use shared header height constant for consistency
      const headerHeight = parsePixels(HDMI_STREAM_HEADER_HEIGHT);
      const streamContentHeight = streamPanelHeight - headerHeight; // Stream panel height minus header

      // Calculate stream width based on centralized device resolution aspect ratio (16:9)
      // For mobile: height is reference, divide by ratio to get width
      const deviceAspectRatio = DEFAULT_DEVICE_RESOLUTION.width / DEFAULT_DEVICE_RESOLUTION.height; // 16:9 = 1.777...
      const streamContentWidth = streamContentHeight / deviceAspectRatio;

      // Calculate stream position - use dynamic props if available, otherwise fall back to config
      let panelX: number;
      let panelY: number;

      if (streamPositionLeft && streamPositionBottom) {
        // Use dynamic positioning from props
        panelX = parsePixels(streamPositionLeft);
        panelY = window.innerHeight - parsePixels(streamPositionBottom) - streamPanelHeight;
      } else {
        // Fall back to config
        panelX =
          'left' in currentStreamConfig.position
            ? parsePixels(currentStreamConfig.position.left)
            : 20;
        panelY =
          window.innerHeight -
          parsePixels(currentStreamConfig.position.bottom || '20px') -
          streamPanelHeight;
      }

      // Calculate content position (accounting for header)
      // Add Y offset when using dynamic positioning (TestCaseBuilder context)
      const yOffset = (streamPositionLeft && streamPositionBottom) ? -30 : 0;
      
      const streamActualPosition = {
        x: panelX + (streamPanelWidth - streamContentWidth) / 2, // Center horizontally
        y: panelY + headerHeight + yOffset, // Position below header + offset adjustment
      };

      const streamActualSize = {
        width: Math.round(streamContentWidth),
        height: Math.round(streamContentHeight-2),
      };

      // Swap panel width and height for landscape mode
      const finalPanelSize = isLandscape
        ? { width: streamActualSize.height, height: streamActualSize.width }
        : streamActualSize;

      // Adjust position for landscape - when height becomes width, Y position needs adjustment
      const finalPosition = isLandscape
        ? {
            x: panelX+20,
            y: window.innerHeight-streamActualSize.height/2-30, // Adjust Y for height difference
          }
        : streamActualPosition;

      const info = {
        position: finalPosition, // Adjusted position for landscape
        size: finalPanelSize, // Swap size for landscape
        deviceResolution: hdmiStreamResolution, // Keep HDMI resolution for overlay positioning
        isCollapsed: streamCollapsed ?? true, // Use stream collapsed state directly, default to collapsed
      };
      return info;
    }, [
      isCollapsed,
      panelWidth,
      panelHeight,
      deviceResolution,
      streamCollapsed,
      streamContainerDimensions,
      // Include dynamic stream offsets so overlay follows sidebar
      streamPositionLeft,
      streamPositionBottom,
      isLandscape, // Recalculate when orientation changes
    ]);



    const getElementDisplayName = (el: AndroidElement): string => {
      let displayName = '';

      // Ensure el and el.id are valid
      if (!el || !el.id) {
        return 'Invalid Element';
      }

      // Debug logging for first few elements (only for development)
      // if (parseInt(String(el.id)) <= 3) {
      //   console.log(`[@component:AndroidMobileRemote] Element ${el.id} debug:`, {
      //     contentDesc: el.contentDesc,
      //     text: el.text,
      //     className: el.className,
      //   });
      // }

      // Priority: ContentDesc → Text → Class Name (same as UIElementsOverlay)
      // Ensure we're working with strings and handle null/undefined safely
      if (
        el.contentDesc &&
        typeof el.contentDesc === 'string' &&
        el.contentDesc !== '<no content-desc>' &&
        el.contentDesc.trim() !== ''
      ) {
        displayName = String(el.contentDesc);
      } else if (
        el.text &&
        typeof el.text === 'string' &&
        el.text !== '<no text>' &&
        el.text.trim() !== ''
      ) {
        displayName = `"${String(el.text)}"`;
      } else {
        const className =
          el.className && typeof el.className === 'string'
            ? el.className.split('.').pop()
            : 'Unknown';
        displayName = String(className || 'Unknown');
      }

      // Prepend element ID with compact format, ensuring both parts are strings
      const fullDisplayName = `${String(el.id)}.${String(displayName)}`;

      // Limit display name length
      if (fullDisplayName.length > 30) {
        return fullDisplayName.substring(0, 27) + '...';
      }
      return fullDisplayName;
    };

    return (
      <>
        <Box
          sx={{
            p: 2,
            flex: 1,
            overflow: 'auto',
            maxWidth: `${layoutConfig.containerWidth}px`,
            margin: '0 auto',
            width: '100%',
            // Prevent the container from affecting global scrollbar
            contain: 'layout style',
          }}
        >
          <Box
            sx={{
              maxWidth: '230px',
              margin: '0 auto',
              width: '100%',
            }}
          >
            {/* App Launcher Section */}
            <Box sx={{ mb: 0 }}>
              <Typography variant="subtitle2" gutterBottom>
                App Launcher ({androidApps.length} apps)
              </Typography>

              <Box sx={{ display: 'flex', gap: 0.5, mb: 1, mt: 0 }}>
                <FormControl fullWidth size="small" ref={appSelectRef} sx={{ minWidth: 0 }}>
                  <InputLabel>Select an app...</InputLabel>
                  <Select
                    value={selectedApp}
                    label="Select an app..."
                    disabled={androidApps.length === 0 || isRefreshingApps}
                    onChange={(e) => {
                      const appPackage = e.target.value;
                      if (appPackage) {
                        setSelectedApp(appPackage);
                        handleRemoteCommand('LAUNCH_APP', { package: appPackage });
                      }
                    }}
                    MenuProps={{
                      PaperProps: {
                        style: {
                          maxHeight: 200,
                          width: appSelectRef.current?.offsetWidth,
                        },
                      },
                    }}
                    renderValue={(value) => {
                      const app = androidApps.find((a) => a.packageName === value);
                      return app ? appDisplayName(app.packageName, app.label) : value;
                    }}
                  >
                    {launcherApps.map((app) => (
                      <MenuItem key={app.packageName} value={app.packageName} sx={{ fontSize: '0.875rem', py: 0.75, px: 1.5 }}>
                        <Tooltip title={app.packageName} placement="left" enterDelay={300}>
                          <Box
                            component="span"
                            sx={{
                              display: 'block',
                              width: '100%',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {app.name}
                          </Box>
                        </Tooltip>
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <Tooltip title="Refresh apps">
                  <span>
                    <Button
                      variant="outlined"
                      size="small"
                      aria-label="Refresh apps"
                      onClick={handleGetApps}
                      disabled={!session.connected || isRefreshingApps}
                      sx={{ minWidth: 0, width: 40, height: 40, p: 0 }}
                    >
                      {isRefreshingApps ? <CircularProgress size={16} /> : <RefreshIcon fontSize="small" />}
                    </Button>
                  </span>
                </Tooltip>
              </Box>
            </Box>

            {/* UI Elements Section */}
            <Box sx={{ mb: 0.5 }}>
              <Typography variant="subtitle2" gutterBottom>
                UI Elements ({androidElements.length})
              </Typography>

              <Box sx={{ display: 'flex', gap: 0.5, mb: 0.5 }}>
                <Button
                  variant="contained"
                  size="small"
                  onClick={handleDumpUIWithModal}
                  disabled={!session.connected || isDumpingUI}
                  sx={{ flex: 1 }}
                >
                  {isDumpingUI ? (
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <CircularProgress size={16} />
                      <Typography variant="caption">Capturing...</Typography>
                    </Box>
                  ) : (
                    'Dump UI'
                  )}
                </Button>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={clearElements}
                  disabled={androidElements.length === 0}
                  sx={{ flex: 1 }}
                >
                  Clear
                </Button>
              </Box>

              {/* Element selection dropdown */}
              <FormControl
                fullWidth
                size="small"
                sx={{
                  '& .MuiOutlinedInput-root': {
                    fontSize: '0.75rem',
                  },
                  '& .MuiInputLabel-root': {
                    fontSize: '0.75rem',
                    transform: 'translate(14px, 9px) scale(1)',
                    '&.MuiInputLabel-shrink': {
                      transform: 'translate(14px, -6px) scale(0.75)',
                    },
                  },
                  maxWidth: '100%',
                  mb: 0,
                }}
              >
                <InputLabel>Select element...</InputLabel>
                <Select
                  value={selectedElement}
                  label="Select element..."
                  disabled={!session.connected || androidElements.length === 0}
                  sx={{
                    '& .MuiSelect-select': {
                      py: 0.75,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    },
                  }}
                  onChange={(e) => {
                    const elementId = e.target.value as string;
                    const element = androidElements.find((el) => el.id === elementId);
                    if (element) {
                      setSelectedElement(element.id);
                      handleOverlayElementClick(element);
                    }
                  }}
                  MenuProps={{
                    PaperProps: {
                      style: {
                        maxHeight: 200,
                        width: 'auto',
                        maxWidth: '100%',
                      },
                    },
                    // Prevent dropdown from affecting page scrollbar
                    disableScrollLock: true,
                    keepMounted: false,
                  }}
                >
                  {androidElements
                    .filter((element) => element && element.id) // Filter out invalid elements
                    .map((element) => {
                      return (
                        <MenuItem
                          key={element.id}
                          value={element.id}
                          sx={{
                            fontSize: '0.75rem',
                            py: 0.5,
                            px: 1,
                            minHeight: 'auto',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                          }}
                        >
                          {getElementDisplayName(element)}
                        </MenuItem>
                      );
                    })}
                </Select>
              </FormControl>
            </Box>

            {/* Device Controls */}
            <Box sx={{ mb: 0.5 }}>
              <Typography variant="subtitle2" gutterBottom>
                Device Controls
              </Typography>

              {/* D-pad (OK in the middle) with Back / Home / Menu beside it */}
              <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mb: 1 }}>
                <Box
                  sx={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(3, 36px)',
                    gridTemplateRows: 'repeat(3, 36px)',
                    gap: '5px',
                    flexShrink: 0,
                  }}
                >
                <Box />
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => handleRemoteCommand('DPAD_UP')}
                  disabled={!session.connected}
                  sx={{ minWidth: 0, p: 0, height: 36 }}
                >
                  ↑
                </Button>
                <Box />
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => handleRemoteCommand('DPAD_LEFT')}
                  disabled={!session.connected}
                  sx={{ minWidth: 0, p: 0, height: 36 }}
                >
                  ←
                </Button>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => handleRemoteCommand('DPAD_CENTER')}
                  disabled={!session.connected}
                  sx={{ minWidth: 0, p: 0, height: 36, borderRadius: '50%' }}
                >
                  OK
                </Button>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => handleRemoteCommand('DPAD_RIGHT')}
                  disabled={!session.connected}
                  sx={{ minWidth: 0, p: 0, height: 36 }}
                >
                  →
                </Button>
                <Box />
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => handleRemoteCommand('DPAD_DOWN')}
                  disabled={!session.connected}
                  sx={{ minWidth: 0, p: 0, height: 36 }}
                >
                  ↓
                </Button>
                <Box />
                </Box>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, flex: 1, minWidth: 0 }}>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => handleRemoteCommand('BACK')}
                  disabled={!session.connected}
                  sx={{  }}
                >
                  Back
                </Button>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => handleRemoteCommand('HOME')}
                  disabled={!session.connected}
                  sx={{  }}
                >
                  Home
                </Button>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => handleRemoteCommand('MENU')}
                  disabled={!session.connected}
                  sx={{  }}
                >
                  Menu
                </Button>
                </Box>
              </Box>

              {/* Scroll buttons: Scr↓ shows what is below, so the finger swipes up (BUG-0489) */}
              <Box sx={{ display: 'flex', gap: 0.25, mb: 0.5 }}>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => handleRemoteCommand('SWIPE_DOWN')}
                  disabled={!session.connected}
                  sx={{ flex: 1, fontSize: '0.65rem', padding: '1px 2px', minWidth: '40px', maxWidth: '55px' }}
                >
                  Scr↑
                </Button>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => handleRemoteCommand('SWIPE_UP')}
                  disabled={!session.connected}
                  sx={{ flex: 1, fontSize: '0.65rem', padding: '1px 2px', minWidth: '40px', maxWidth: '55px' }}
                >
                  Scr↓
                </Button>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => handleRemoteCommand('SWIPE_RIGHT')}
                  disabled={!session.connected}
                  sx={{ flex: 1, fontSize: '0.65rem', padding: '1px 2px', minWidth: '40px', maxWidth: '55px' }}
                >
                  Scr←
                </Button>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => handleRemoteCommand('SWIPE_LEFT')}
                  disabled={!session.connected}
                  sx={{ flex: 1, fontSize: '0.65rem', padding: '1px 2px', minWidth: '40px', maxWidth: '55px' }}
                >
                  Scr→
                </Button>
              </Box>

              {/* Volume controls */}
              <Box sx={{ display: 'flex', gap: 0.5 }}>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => handleRemoteCommand('VOLUME_UP')}
                  disabled={!session.connected}
                  sx={{ flex: 1 }}
                >
                  Vol+
                </Button>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => handleRemoteCommand('VOLUME_DOWN')}
                  disabled={!session.connected}
                  sx={{ flex: 1 }}
                >
                  Vol-
                </Button>
              </Box>
            </Box>

            {/* Type Text: Enter types the field's text then presses Enter; empty field = Enter only */}
            <Box sx={{ mb: 0.5 }}>
              <Typography variant="subtitle2" gutterBottom>
                Type Text
              </Typography>
              <Box sx={{ display: 'flex', gap: 0.5 }}>
                <TextField
                  value={typeTextInput}
                  onChange={(e) => setTypeTextInput(e.target.value)}
                  placeholder="Type text"
                  variant="outlined"
                  size="small"
                  disabled={!session.connected || isTyping}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      handleTypeEnter();
                    }
                  }}
                  sx={{
                    flex: 1,
                    minWidth: 0,
                    '& .MuiOutlinedInput-root': {
                      fontSize: '0.75rem',
                      '& input': { py: 0.5 },
                    },
                  }}
                />
                <Button
                  variant="outlined"
                  size="small"
                  onClick={handleTypeEnter}
                  disabled={!session.connected || isTyping}
                  sx={{ minWidth: '64px' }}
                >
                  {isTyping ? <CircularProgress size={16} /> : 'Enter'}
                </Button>
              </Box>
            </Box>

            {/* Element Interaction Section - Compact version with dropdown */}
            <Box sx={{ mb: 1 }}>
              <Typography variant="subtitle2" gutterBottom>
                Element Interaction
              </Typography>

              {/* Action Type Selector */}
              <FormControl fullWidth size="small" sx={{ mb: 0.5 }}>
                <Select
                  value={elementActionType}
                  onChange={(e) => {
                    setElementActionType(e.target.value as 'click_id' | 'click_text' | 'find');
                    setActionStatus('idle');
                  }}
                  disabled={!session.connected}
                  sx={{
                    fontSize: '0.75rem',
                    '& .MuiSelect-select': { py: 0.5 },
                  }}
                >
                  <MenuItem value="click_id" sx={{ fontSize: '0.75rem' }}>
                    Click by ID
                  </MenuItem>
                  <MenuItem value="click_text" sx={{ fontSize: '0.75rem' }}>
                    Click by Text
                  </MenuItem>
                  <MenuItem value="find" sx={{ fontSize: '0.75rem' }}>
                    Find Element
                  </MenuItem>
                </Select>
              </FormControl>

              {/* Input and Action Button */}
              <Box sx={{ display: 'flex', gap: 0.5 }}>
                <TextField
                  value={elementActionInput}
                  onChange={(e) => {
                    // For click_id, only allow integers
                    if (elementActionType === 'click_id') {
                      const value = e.target.value;
                      // Allow empty string or valid integers (including negative)
                      if (value === '' || /^-?\d+$/.test(value)) {
                        setElementActionInput(value);
                      }
                    } else {
                      setElementActionInput(e.target.value);
                    }
                  }}
                  placeholder={
                    elementActionType === 'click_id'
                      ? 'Element ID (number)'
                      : elementActionType === 'click_text'
                      ? 'Element text'
                      : 'Search term'
                  }
                  variant="outlined"
                  size="small"
                  type={elementActionType === 'click_id' ? 'number' : 'text'}
                  disabled={!session.connected || isExecutingAction}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && elementActionInput.trim()) {
                      e.preventDefault();
                      handleElementAction();
                    }
                  }}
                  sx={{
                    flex: 1,
                    '& .MuiOutlinedInput-root': {
                      fontSize: '0.75rem',
                      '& input': { py: 0.5 },
                    },
                  }}
                />
                <Button
                  variant="contained"
                  size="small"
                  onClick={handleElementAction}
                  disabled={!session.connected || !elementActionInput.trim() || isExecutingAction || isDumpingUI}
                  color={
                    actionStatus === 'success' ? 'success' : 
                    actionStatus === 'error' ? 'error' : 
                    'primary'
                  }
                  sx={{ 
                    minWidth: '60px',
                    position: 'relative'
                  }}
                >
                  {isExecutingAction ? (
                    <CircularProgress size={16} sx={{ color: 'white' }} />
                  ) : (
                    <>
                      {actionStatus === 'success' && '✓ '}
                      {actionStatus === 'error' && '✗ '}
                      {elementActionType === 'find' ? 'Find' : 'Click'}
                    </>
                  )}
                </Button>
              </Box>
            </Box>

            {/* Disconnect Button - REMOVED: Users can close panel or release control */}
          </Box>
        </Box>

        {/* Results Modal */}
        <StyledDialog
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          maxWidth="lg"
          fullWidth
        >
          <DialogTitle>{modalTitle}</DialogTitle>
          <DialogContent>
            <Box sx={{ maxHeight: '400px', overflowY: 'auto', overflowX: 'hidden' }}>
              {modalContent && Array.isArray(modalContent) && modalContent.map((item: any, index: number) => (
                <Box key={index} sx={{ mb: 1, p: 1, backgroundColor: 'rgba(0,0,0,0.05)', borderRadius: 1 }}>
                  <Typography variant="caption" sx={{ display: 'block', fontWeight: 'bold', wordBreak: 'break-word' }}>
                    {index + 1}. Element
                  </Typography>
                  {(item.id || item.element_id) && (
                    <Typography variant="caption" sx={{ display: 'block', color: 'text.primary', fontSize: '0.7rem', wordBreak: 'break-word' }}>
                      ID: {item.id || item.element_id}
                    </Typography>
                  )}
                  {item.text && item.text !== '<no text>' && (
                    <Typography variant="caption" sx={{ display: 'block', color: 'text.primary', fontSize: '0.7rem', wordBreak: 'break-word' }}>
                      Text: {item.text}
                    </Typography>
                  )}
                  {item.contentDesc && item.contentDesc !== '<no content-desc>' && (
                    <Typography variant="caption" sx={{ display: 'block', color: 'text.primary', fontSize: '0.7rem', wordBreak: 'break-word' }}>
                      Content-Desc: {item.contentDesc}
                    </Typography>
                  )}
                  {item.match_reason && (
                    <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', fontSize: '0.7rem', wordBreak: 'break-word', fontStyle: 'italic' }}>
                      Match: {item.match_reason}
                    </Typography>
                  )}
                  {item.bounds && (
                    <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', fontSize: '0.7rem', wordBreak: 'break-word' }}>
                      Bounds: {typeof item.bounds === 'string' ? item.bounds : JSON.stringify(item.bounds)}
                    </Typography>
                  )}
                  {item.xpath && (
                    <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', fontSize: '0.7rem', wordBreak: 'break-all' }}>
                      XPath: {item.xpath}
                    </Typography>
                  )}
                </Box>
              ))}
            </Box>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setModalOpen(false)} variant="outlined">Close</Button>
          </DialogActions>
        </StyledDialog>

        {/* Toast Notification */}
        <Snackbar
          open={toastOpen}
          autoHideDuration={3000}
          onClose={() => setToastOpen(false)}
          anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
        >
          <Alert onClose={() => setToastOpen(false)} severity={toastSeverity} sx={{ width: '100%' }}>
            {toastMessage}
          </Alert>
        </Snackbar>

        {/* AndroidMobileOverlay - Only visible when in stream mode (not during screenshot/video capture or verification editor), not minimized, not hidden, and showOverlay is true */}
        {panelInfo &&
        typeof document !== 'undefined' &&
        captureMode === 'stream' &&
        !streamMinimized &&
        !streamHidden &&
        !isVerificationVisible &&
        showOverlay
          ? createPortal(
              <AndroidMobileOverlay
                key={`overlay-${isLandscape}`} // Force re-render on orientation change
                elements={androidElements}
                // Real device screen size (falls back to the layout default until the
                // first orientation read answers); swapped for landscape
                deviceWidth={isLandscape ? overlayScreen.height : overlayScreen.width}
                deviceHeight={isLandscape ? overlayScreen.width : overlayScreen.height}
                isVisible={captureMode === 'stream' && !streamMinimized && !streamHidden && !isVerificationVisible && showOverlay}
                onElementClick={handleOverlayElementClick}
                panelInfo={panelInfo}
                host={host}
                deviceId={deviceId}
                isLandscape={isLandscape}
                // Modal context renders EnhancedHLSPlayer (always objectFit 'contain');
                // the floating panel renders HDMIStream, which uses 'cover' for mobile.
                streamObjectFit={streamContainerDimensions ? 'contain' : 'cover'}
                onAfterTap={checkOrientation}
              />,
              document.body,
            )
          : null}

      {/* Debug logging for overlay visibility */}
      {(() => {
        console.log('[@AndroidMobileRemote] Component render - showOverlay:', showOverlay);
        return null;
      })()}
      </>
    );
  },
  (prevProps, nextProps) => {
    // Custom comparison function to prevent unnecessary re-renders
    const hostChanged = JSON.stringify(prevProps.host) !== JSON.stringify(nextProps.host);
    const sxChanged = JSON.stringify(prevProps.sx) !== JSON.stringify(nextProps.sx);
    const isCollapsedChanged = prevProps.isCollapsed !== nextProps.isCollapsed;
    const panelWidthChanged = prevProps.panelWidth !== nextProps.panelWidth;
    const panelHeightChanged = prevProps.panelHeight !== nextProps.panelHeight;
    const deviceResolutionChanged =
      JSON.stringify(prevProps.deviceResolution) !== JSON.stringify(nextProps.deviceResolution);
    const streamCollapsedChanged = prevProps.streamCollapsed !== nextProps.streamCollapsed;
    const streamMinimizedChanged = prevProps.streamMinimized !== nextProps.streamMinimized;
    const captureModeChanged = prevProps.captureMode !== nextProps.captureMode;
    const isVerificationVisibleChanged = prevProps.isVerificationVisible !== nextProps.isVerificationVisible;
    const onDisconnectCompleteChanged =
      prevProps.onDisconnectComplete !== nextProps.onDisconnectComplete;
    const streamContainerDimensionsChanged =
      JSON.stringify(prevProps.streamContainerDimensions) !==
      JSON.stringify(nextProps.streamContainerDimensions);
    const streamPositionLeftChanged = prevProps.streamPositionLeft !== nextProps.streamPositionLeft;
    const streamPositionBottomChanged = prevProps.streamPositionBottom !== nextProps.streamPositionBottom;
    const onOrientationChangeChanged = prevProps.onOrientationChange !== nextProps.onOrientationChange;

    // Return true if props are equal (don't re-render), false if they changed (re-render)
    const shouldSkipRender =
      !hostChanged &&
      !sxChanged &&
      !isCollapsedChanged &&
      !panelWidthChanged &&
      !panelHeightChanged &&
      !deviceResolutionChanged &&
      !streamCollapsedChanged &&
      !streamMinimizedChanged &&
      !captureModeChanged &&
      !isVerificationVisibleChanged &&
      !onDisconnectCompleteChanged &&
      !streamContainerDimensionsChanged &&
      !streamPositionLeftChanged &&
      !streamPositionBottomChanged &&
      !onOrientationChangeChanged;

    // Log only significant re-renders for debugging
    // if (!shouldSkipRender) {
    //   console.log(`[@component:AndroidMobileRemote] Re-rendering due to prop changes`);
    // }

    return shouldSkipRender;
  },
);
