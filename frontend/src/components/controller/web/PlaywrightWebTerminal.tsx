import {
  PlayArrow as PlayIcon,
  Stop as StopIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
  ArrowUpward as ArrowUpwardIcon,
  ArrowDownward as ArrowDownwardIcon,
} from '@mui/icons-material';
import {
  Box,
  Button,
  TextField,
  Paper,
  Typography,
  CircularProgress,
  IconButton,
  Collapse,
  Divider,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material';
import React, { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';

import { useVNCState } from '../../../contexts/VNCStateContext';
import { usePlaywrightWeb } from '../../../hooks/controller/usePlaywrightWeb';
import { Host } from '../../../types/common/Host_Types';
import { WebElement } from '../../../types/controller/Web_Types';
import { PlaywrightWebOverlay } from './PlaywrightWebOverlay';


interface PlaywrightWebTerminalProps {
  host: Host;
  isMinimized?: boolean;
}

export const PlaywrightWebTerminal = React.memo(function PlaywrightWebTerminal({
  host,
  isMinimized = false,
}: PlaywrightWebTerminalProps) {
  // Get VNC state from context
  const { isVNCExpanded } = useVNCState();
  const {
    executeCommand,
    // Removed unused destructured properties to fix linter errors
    session,
    currentUrl,
    pageTitle,
    terminalOutput,
    isExecuting,
    isBrowserUseExecuting,
    clearTerminal,
  } = usePlaywrightWeb(host); // Web automation operates directly on the host

  // Local state for individual action inputs
  const [navigateUrl, setNavigateUrl] = useState('');
  const [clickSelector, setClickSelector] = useState('');
  const [tapX, setTapX] = useState('');
  const [tapY, setTapY] = useState('');
  const [findSelector, setFindSelector] = useState('');
  const [taskInput, setTaskInput] = useState('');

  // Web overlay state
  const [webElements, setWebElements] = useState<WebElement[]>([]);
  const [isElementsVisible, setIsElementsVisible] = useState(false);
  const [selectedElement, setSelectedElement] = useState<string>('');
  const [browserViewport, setBrowserViewport] = useState({ width: 1024, height: 618 });
  const [isResponseExpanded, setIsResponseExpanded] = useState(false);
  const [isBrowserUseExpanded, setIsBrowserUseExpanded] = useState(true);
  const [isPlaywrightExpanded, setIsPlaywrightExpanded] = useState(true);
  const [isBrowserOpen, setIsBrowserOpen] = useState(false);
  const [isOpening, setIsOpening] = useState(false);
  const [isClosing, setIsClosing] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);

  // Execution states for individual actions
  const [isNavigating, setIsNavigating] = useState(false);
  const [isClicking, setIsClicking] = useState(false);
  const [isTapping, setIsTapping] = useState(false);
  const [isFinding, setIsFinding] = useState(false);
  const [isDumping, setIsDumping] = useState(false);
  const [isActivatingSemantic, setIsActivatingSemantic] = useState(false);

  // Key press execution states
  const [isPressBackKey, setIsPressBackKey] = useState(false);
  const [isPressOkKey, setIsPressOkKey] = useState(false);
  const [isPressEscKey, setIsPressEscKey] = useState(false);

  // Scroll execution states
  const [isScrollingUp, setIsScrollingUp] = useState(false);
  const [isScrollingDown, setIsScrollingDown] = useState(false);

  // Success/failure states for visual feedback
  const [navigateStatus, setNavigateStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [clickStatus, setClickStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [tapStatus, setTapStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [findStatus, setFindStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [dumpStatus, setDumpStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [taskStatus, setTaskStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [semanticStatus, setSemanticStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [backKeyStatus, setBackKeyStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [okKeyStatus, setOkKeyStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [escKeyStatus, setEscKeyStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [scrollUpStatus, setScrollUpStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [scrollDownStatus, setScrollDownStatus] = useState<'idle' | 'success' | 'error'>('idle');

  // Tap animation state
  const [tapAnimation, setTapAnimation] = useState<{ x: number; y: number; show: boolean }>({
    x: 0,
    y: 0,
    show: false,
  });

  // Element highlight state
  const [elementHighlight, setElementHighlight] = useState<{
    x: number;
    y: number;
    width: number;
    height: number;
    show: boolean;
  }>({
    x: 0,
    y: 0,
    width: 0,
    height: 0,
    show: false,
  });

  const responseRef = useRef<HTMLDivElement>(null);

  // Helper function to extract element coordinates from response
  const showElementHighlight = (result: any) => {
    if (result.success && result.result) {
      const { x, y, width, height } = result.result;
      if (
        typeof x === 'number' &&
        typeof y === 'number' &&
        typeof width === 'number' &&
        typeof height === 'number'
      ) {
        setElementHighlight({ x, y, width, height, show: true });
        setTimeout(() => setElementHighlight((prev) => ({ ...prev, show: false })), 2000);
      }
    }
  };

  // Auto-scroll response area when new output arrives
  useEffect(() => {
    if (responseRef.current && terminalOutput) {
      responseRef.current.scrollTop = responseRef.current.scrollHeight;
    }
  }, [terminalOutput]);

  // Update browser open state based on session and page info
  useEffect(() => {
    // Browser is only considered open if we have an active page with content
    // Since we don't auto-open anymore, we need explicit browser open confirmation
    const browserOpen = session.connected && Boolean(currentUrl && pageTitle);
    setIsBrowserOpen(browserOpen);
  }, [session.connected, currentUrl, pageTitle]);

  // Reset status after 3 seconds
  useEffect(() => {
    const timers: NodeJS.Timeout[] = [];

    if (navigateStatus !== 'idle') {
      timers.push(setTimeout(() => setNavigateStatus('idle'), 3000));
    }
    if (clickStatus !== 'idle') {
      timers.push(setTimeout(() => setClickStatus('idle'), 3000));
    }
    if (tapStatus !== 'idle') {
      timers.push(setTimeout(() => setTapStatus('idle'), 3000));
    }
    if (findStatus !== 'idle') {
      timers.push(setTimeout(() => setFindStatus('idle'), 3000));
    }
    if (dumpStatus !== 'idle') {
      timers.push(setTimeout(() => setDumpStatus('idle'), 3000));
    }
    if (taskStatus !== 'idle') {
      timers.push(setTimeout(() => setTaskStatus('idle'), 3000));
    }
    if (semanticStatus !== 'idle') {
      timers.push(setTimeout(() => setSemanticStatus('idle'), 3000));
    }
    if (backKeyStatus !== 'idle') {
      timers.push(setTimeout(() => setBackKeyStatus('idle'), 3000));
    }
    if (okKeyStatus !== 'idle') {
      timers.push(setTimeout(() => setOkKeyStatus('idle'), 3000));
    }
    if (escKeyStatus !== 'idle') {
      timers.push(setTimeout(() => setEscKeyStatus('idle'), 3000));
    }
    if (scrollUpStatus !== 'idle') {
      timers.push(setTimeout(() => setScrollUpStatus('idle'), 3000));
    }
    if (scrollDownStatus !== 'idle') {
      timers.push(setTimeout(() => setScrollDownStatus('idle'), 3000));
    }

    return () => {
      timers.forEach((timer) => clearTimeout(timer));
    };
  }, [navigateStatus, clickStatus, tapStatus, findStatus, dumpStatus, taskStatus, semanticStatus, backKeyStatus, okKeyStatus, escKeyStatus, scrollUpStatus, scrollDownStatus]);

  // Handle task execution (placeholder)
  const handleTaskExecution = async () => {
    if (!taskInput.trim() || isBrowserUseExecuting) return;

    setTaskStatus('idle');

    try {
      // Clear response area before new task
      clearTerminal();

      const commandJson = JSON.stringify({
        command: 'browser_use_task',
        params: { task: taskInput.trim() },
      });
      const result = await executeCommand(commandJson);

      setTaskInput(''); // Clear input after execution

      // Set visual feedback based on result
      setTaskStatus(result.success ? 'success' : 'error');

      // Show response area
      setIsResponseExpanded(true);

      return result;
    } catch (error) {
      setTaskStatus('error');
      console.error('Task error:', error);
      return { success: false, error: 'Task failed' };
    }
  };

  // Check if any action is executing
  const isAnyActionExecuting =
    isExecuting ||
    isNavigating ||
    isClicking ||
    isTapping ||
    isFinding ||
    isDumping ||
    isActivatingSemantic ||
    isOpening ||
    isClosing ||
    isConnecting ||
    isBrowserUseExecuting ||
    isPressBackKey ||
    isPressOkKey ||
    isPressEscKey ||
    isScrollingUp ||
    isScrollingDown;

  // Handle browser open
  const handleOpenBrowser = async () => {
    setIsOpening(true);
    try {
      console.log('Starting browser open process...');
      const result = await executeCommand(
        JSON.stringify({
          command: 'open_browser',
          params: {},
        }),
      );
      if (result.success) {
        setIsBrowserOpen(true);
        console.log('Browser opened successfully');
      } else {
        console.error('Failed to open browser:', result.error);
      }
    } catch (error) {
      console.error('Failed to open browser:', error);
    } finally {
      setIsOpening(false);
    }
  };

  // Handle browser connect
  const handleConnectBrowser = async () => {
    setIsConnecting(true);
    try {
      console.log('Starting browser connect process...');
      const result = await executeCommand(
        JSON.stringify({
          command: 'connect_browser',
          params: {},
        }),
      );
      if (result.success) {
        setIsBrowserOpen(true);
        console.log('Browser connected successfully');
      } else {
        console.error('Failed to connect to browser:', result.error);
      }
    } catch (error) {
      console.error('Failed to connect to browser:', error);
    } finally {
      setIsConnecting(false);
    }
  };

  // Handle browser close
  const handleCloseBrowser = async () => {
    setIsClosing(true);
    try {
      console.log('Starting browser close process...');
      const result = await executeCommand(
        JSON.stringify({
          command: 'close_browser',
          params: {},
        }),
      );
      if (result.success) {
        // Reset local component state when browser is closed
        setIsBrowserOpen(false);
        setNavigateUrl('');
        setClickSelector('');
        setTapX('');
        setTapY('');
        setFindSelector('');
        setIsResponseExpanded(false);

        // Reset all action states and status
        setIsNavigating(false);
        setIsClicking(false);
        setIsTapping(false);
        setIsFinding(false);
        setNavigateStatus('idle');
        setClickStatus('idle');
        setTapStatus('idle');
        setFindStatus('idle');

        console.log('Browser closed successfully');
      } else {
        console.error('Failed to close browser:', result.error);
      }
    } catch (error) {
      console.error('Failed to close browser:', error);
    } finally {
      setIsClosing(false);
    }
    // Don't call onDisconnectComplete here - that's for closing the entire panel, not just the browser
  };

  // Handle navigate action
  const handleNavigate = async () => {
    if (!navigateUrl.trim() || isAnyActionExecuting) return;

    setIsNavigating(true);
    setNavigateStatus('idle');

    try {
      // Clear response area before new command
      clearTerminal();

      // Use proper JSON format for the command
      const commandJson = JSON.stringify({
        command: 'navigate_to_url',
        params: {
          url: navigateUrl.trim(),
          follow_redirects: true, // Always follow redirects for navigation
        },
      });
      const result = await executeCommand(commandJson);
      // Don't reset navigateUrl to allow reuse
      // setNavigateUrl('');

      // Set visual feedback based on result
      setNavigateStatus(result.success ? 'success' : 'error');

      // Show response area
      setIsResponseExpanded(true);
    } catch (error) {
      setNavigateStatus('error');
      console.error('Navigate error:', error);
    } finally {
      setIsNavigating(false);
    }
  };

  // Handle click element action
  const handleClickElement = async () => {
    if (!clickSelector.trim() || isAnyActionExecuting) return;

    setIsClicking(true);
    setClickStatus('idle');

    try {
      // Clear response area before new command
      clearTerminal();

      // Use proper JSON format for the command (now using element_id like Android)
      const commandJson = JSON.stringify({
        command: 'click_element',
        params: { element_id: clickSelector.trim() },
      });
      const result = await executeCommand(commandJson);
      // Don't reset clickSelector to allow reuse
      // setClickSelector('');

      // Show element highlight if coordinates are available
      showElementHighlight(result);

      // Set visual feedback based on result
      setClickStatus(result.success ? 'success' : 'error');

      // Show response area
      setIsResponseExpanded(true);
    } catch (error) {
      setClickStatus('error');
      console.error('Click error:', error);
    } finally {
      setIsClicking(false);
    }
  };

  // Handle tap coordinates action
  const handleTapXY = async () => {
    const x = parseInt(tapX);
    const y = parseInt(tapY);

    if (isNaN(x) || isNaN(y) || isAnyActionExecuting) return;

    setIsTapping(true);
    setTapStatus('idle');

    // Show tap animation at coordinates
    setTapAnimation({ x, y, show: true });
    setTimeout(() => setTapAnimation((prev) => ({ ...prev, show: false })), 1000);

    try {
      // Clear response area before new command
      clearTerminal();

      // Use proper JSON format for the command
      const commandJson = JSON.stringify({
        command: 'tap_x_y',
        params: { x, y },
      });
      const result = await executeCommand(commandJson);
      // Don't reset tap coordinates to allow reuse
      // setTapX('');
      // setTapY('');

      // Set visual feedback based on result
      setTapStatus(result.success ? 'success' : 'error');

      // Show response area
      setIsResponseExpanded(true);
    } catch (error) {
      setTapStatus('error');
      console.error('Tap error:', error);
    } finally {
      setIsTapping(false);
    }
  };

  // Handle find element action
  const handleFindElement = async () => {
    if (!findSelector.trim() || isAnyActionExecuting) return;

    setIsFinding(true);
    setFindStatus('idle');

    try {
      // Clear response area before new find
      clearTerminal();

      // Use proper JSON format for the command - find specific element
      const commandJson = JSON.stringify({
        command: 'find_element',
        params: { selector: findSelector.trim() },
      });

      const result = await executeCommand(commandJson);
      // Don't reset findSelector to allow reuse
      // setFindSelector('');

      // Show element highlight if coordinates are available
      showElementHighlight(result);

      // Set visual feedback based on result
      setFindStatus(result.success ? 'success' : 'error');

      // Show response area
      setIsResponseExpanded(true);
    } catch (error) {
      setFindStatus('error');
      console.error('Find error:', error);
    } finally {
      setIsFinding(false);
    }
  };

  const handleDumpElements = async () => {
    if (isAnyActionExecuting) return;

    setIsDumping(true);
    setDumpStatus('idle');

    try {
      // Clear response area before new dump
      clearTerminal();

      // Use proper JSON format for the command
      const commandJson = JSON.stringify({
        command: 'dump_elements',
        params: {
          element_types: 'all',
        },
      });
      const result = await executeCommand(commandJson);

      // Set visual feedback based on result
      setDumpStatus(result.success ? 'success' : 'error');

      // Copy raw dump to clipboard
      if (result.success && result.elements) {
        try {
          const rawDump = JSON.stringify(result, null, 2);
          await navigator.clipboard.writeText(rawDump);
          console.log('✅ Raw dump copied to clipboard');
        } catch (clipboardError) {
          console.error('Failed to copy to clipboard:', clipboardError);
        }
      }

      // Store elements for overlay
      if (result.success && result.elements) {
        // Filter elements to only include those within browser viewport
        const viewport = result.summary?.viewport || browserViewport;
        const filteredElements = result.elements.filter((element: any) => {
          const { x, y, width, height } = element.position;
          // Keep elements that are at least partially within viewport
          return (
            x < viewport.width && 
            y < viewport.height && 
            x + width > 0 && 
            y + height > 0
          );
        });
        
        setWebElements(filteredElements);
        setIsElementsVisible(true);
        
        // Update browser viewport from dump_elements response
        if (result.summary && result.summary.viewport) {
          setBrowserViewport(result.summary.viewport);
        }
      } else {
        setWebElements([]);
        setIsElementsVisible(false);
      }

      // Show response area
      setIsResponseExpanded(true);
    } catch (error) {
      setDumpStatus('error');
      setWebElements([]);
      setIsElementsVisible(false);
      console.error('Dump elements error:', error);
    } finally {
      setIsDumping(false);
    }
  };

  const handleActivateSemantic = async () => {
    if (isAnyActionExecuting) return;

    setIsActivatingSemantic(true);

    try {
      // Clear response area before new command
      clearTerminal();

      // Use proper JSON format for the command
      const commandJson = JSON.stringify({
        command: 'activate_semantic',
        params: {},
      });
      const result = await executeCommand(commandJson);

      // Set visual feedback based on result
      setSemanticStatus(result.success ? 'success' : 'error');

      // Show response area
      setIsResponseExpanded(true);
    } catch (error) {
      setSemanticStatus('error');
      console.error('Activate semantic error:', error);
    } finally {
      setIsActivatingSemantic(false);
    }
  };

  // Handle key press actions
  const handlePressKey = async (key: string, setExecuting: React.Dispatch<React.SetStateAction<boolean>>, setStatus: React.Dispatch<React.SetStateAction<'idle' | 'success' | 'error'>>) => {
    if (isAnyActionExecuting) return;

    setExecuting(true);
    setStatus('idle');

    try {
      // Clear response area before new command
      clearTerminal();

      // Use proper JSON format for the command
      const commandJson = JSON.stringify({
        command: 'press_key',
        params: { key },
      });
      const result = await executeCommand(commandJson);

      // Set visual feedback based on result
      setStatus(result.success ? 'success' : 'error');

      // Show response area
      setIsResponseExpanded(true);
    } catch (error) {
      setStatus('error');
      console.error(`Press ${key} key error:`, error);
    } finally {
      setExecuting(false);
    }
  };

  const handlePressBackKey = () => handlePressKey('BACK', setIsPressBackKey, setBackKeyStatus);
  const handlePressOkKey = () => handlePressKey('OK', setIsPressOkKey, setOkKeyStatus);
  const handlePressEscKey = () => handlePressKey('ESCAPE', setIsPressEscKey, setEscKeyStatus);

  // Handle scroll actions
  const handleScroll = async (direction: string, setExecuting: React.Dispatch<React.SetStateAction<boolean>>, setStatus: React.Dispatch<React.SetStateAction<'idle' | 'success' | 'error'>>) => {
    if (isAnyActionExecuting) return;

    setExecuting(true);
    setStatus('idle');

    try {
      // Clear response area before new command
      clearTerminal();

      // Use proper JSON format for the command
      const commandJson = JSON.stringify({
        command: 'scroll',
        params: { direction, amount: 300 },
      });
      const result = await executeCommand(commandJson);

      // Set visual feedback based on result
      setStatus(result.success ? 'success' : 'error');

      // Show response area
      setIsResponseExpanded(true);
    } catch (error) {
      setStatus('error');
      console.error(`Scroll ${direction} error:`, error);
    } finally {
      setExecuting(false);
    }
  };

  const handleScrollUp = () => handleScroll('up', setIsScrollingUp, setScrollUpStatus);
  const handleScrollDown = () => handleScroll('down', setIsScrollingDown, setScrollDownStatus);

  const handleClearElements = () => {
    setWebElements([]);
    setIsElementsVisible(false);
    setSelectedElement('');
    setDumpStatus('idle');
  };

  const handleElementClick = async (element: WebElement) => {
    setSelectedElement(element.selector);
    setClickSelector(element.selector);
    await handleClickElement();
  };

  const handleDropdownElementSelect = async (elementSelector: string) => {
    const element = webElements.find(el => el.selector === elementSelector);
    if (element) {
      setSelectedElement(elementSelector);
      await handleElementClick(element);
    }
  };

  // Dynamic VNC panel info using same approach as AndroidMobileRemote
  const getVNCPanelInfo = () => {
    // Use VNC state from context
    const actualVncExpanded = isVNCExpanded;
    
    // VNC desktop resolution (what the VNC stream shows)
    const vncResolution = { width: 1440, height: 847 };
    
    // VNC panel size from config/state
    const vncPanelWidth = actualVncExpanded ? 520 : 370;
    const vncPanelHeight = actualVncExpanded ? 360 : 240;
    
    // Header height (varies by expansion state)
    const headerHeight = actualVncExpanded ? 35 : 30;
    
    // Calculate VNC CONTENT size (subtract header, maintain aspect ratio)
    const vncContentHeight = vncPanelHeight - headerHeight;
    const vncAspectRatio = vncResolution.width / vncResolution.height; // 1440:847 = 1.7
    const vncContentWidth = vncContentHeight * vncAspectRatio;
    
    // Calculate VNC panel position (bottom-left)
    const panelX = 20;  // Fixed left: 20px
    const panelY = window.innerHeight - 20 - vncPanelHeight;  // Bottom: 20px
    
    // Calculate VNC CONTENT position (panel position + centering + header offset)
    const vncContentPosition = {
      x: panelX + (vncPanelWidth - vncContentWidth) / 2, // Center horizontally in panel
      y: panelY + headerHeight  // Below header
    };
    
    const vncContentSize = {
      width: Math.round(vncContentWidth),
      height: Math.round(vncContentHeight)
    };
    
    const panelInfo = {
      position: vncContentPosition,  // VNC content position (not panel position!)
      size: vncContentSize,           // VNC content size (not panel size!)
      deviceResolution: vncResolution, // VNC desktop resolution
      isCollapsed: !actualVncExpanded
    };
    
    console.log('[PlaywrightWebTerminal] Dynamic VNC Panel Info (Content Area):', {
      vncExpanded: actualVncExpanded,
      vncResolution,
      vncPanelSize: { width: vncPanelWidth, height: vncPanelHeight },
      vncContentSize,
      headerHeight,
      vncAspectRatio: vncAspectRatio.toFixed(3),
      panelPosition: { panelX, panelY },
      contentPosition: vncContentPosition,
      browserViewport,
      panelInfo
    });
    
    return panelInfo;
  };

  // Helper function to get button color based on status
  const getButtonColor = (status: 'idle' | 'success' | 'error') => {
    switch (status) {
      case 'success':
        return 'success';
      case 'error':
        return 'error';
      default:
        return 'primary';
    }
  };

  return (
    <Box
      sx={{
        p: 1,
        flex: 1,
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        width: '100%',
        height: '100%',
      }}
    >
      {/* Browser Control */}
      <Box sx={{ mb: 2 }}>
        <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 'bold' }}>
          Browser Control
        </Typography>
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          <Button
            variant={isBrowserOpen ? 'outlined' : 'contained'}
            size="small"
            onClick={handleOpenBrowser}
            disabled={isBrowserOpen || isAnyActionExecuting || isOpening}
            startIcon={isOpening ? <CircularProgress size={16} /> : <PlayIcon />}
            color="success"
            sx={{ flex: 1, minWidth: '80px' }}
          >
            {isOpening ? 'Opening...' : 'Open'}
          </Button>
          <Button
            variant={isBrowserOpen ? 'outlined' : 'contained'}
            size="small"
            onClick={handleConnectBrowser}
            disabled={isBrowserOpen || isAnyActionExecuting || isConnecting}
            startIcon={isConnecting ? <CircularProgress size={16} /> : <PlayIcon />}
            color="primary"
            sx={{ flex: 1, minWidth: '80px' }}
          >
            {isConnecting ? 'Connecting...' : 'Connect'}
          </Button>
          <Button
            variant={isBrowserOpen ? 'contained' : 'outlined'}
            size="small"
            onClick={handleCloseBrowser}
            disabled={!isBrowserOpen || isClosing || isAnyActionExecuting}
            startIcon={isClosing ? <CircularProgress size={16} /> : <StopIcon />}
            color="error"
            sx={{ flex: 1, minWidth: '80px' }}
          >
            {isClosing ? 'Closing...' : 'Close'}
          </Button>
        </Box>
      </Box>

      {/* Action Sections */}
      {isBrowserOpen && (
        <Box sx={{ flex: 1, overflow: 'auto' }}>
          {/* Browser-Use Section */}
          <Box sx={{ mb: 1 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 'bold', flex: 1 }}>
                Browser-Use
              </Typography>
              <IconButton
                size="small"
                onClick={() => setIsBrowserUseExpanded(!isBrowserUseExpanded)}
              >
                {isBrowserUseExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
              </IconButton>
            </Box>
            <Collapse in={isBrowserUseExpanded}>
              <Box sx={{ mb: 2 }}>
                <Typography
                  variant="caption"
                  sx={{ display: 'block', mb: 0.5, fontWeight: 'bold' }}
                >
                  Task Execution
                </Typography>
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <TextField
                    value={taskInput}
                    onChange={(e) => setTaskInput(e.target.value)}
                    placeholder="Enter task description (e.g., 'Search for cats on Google')"
                    variant="outlined"
                    size="small"
                    disabled={isExecuting}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        handleTaskExecution();
                      }
                    }}
                    sx={{
                      flex: 1,
                      '& .MuiOutlinedInput-root': {
                        fontSize: '0.875rem',
                      },
                    }}
                  />
                  <Button
                    variant="contained"
                    size="small"
                    onClick={handleTaskExecution}
                    disabled={!taskInput.trim() || isBrowserUseExecuting}
                    color={getButtonColor(taskStatus)}
                    startIcon={isBrowserUseExecuting ? <CircularProgress size={16} /> : undefined}
                    sx={{ minWidth: '80px' }}
                  >
                    {isBrowserUseExecuting ? 'Running...' : 'Run'}
                  </Button>
                </Box>
              </Box>
            </Collapse>
          </Box>

          <Divider sx={{ my: 1 }} />

          {/* Keyboard Controls Section */}
          <Box sx={{ mb: 1 }}>
            <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 'bold' }}>
              Keyboard Controls
            </Typography>
            <Box sx={{ display: 'flex', gap: 0.5, mb: 1 }}>
              <Button
                variant="outlined"
                size="small"
                onClick={handlePressBackKey}
                disabled={isAnyActionExecuting}
                color={getButtonColor(backKeyStatus)}
                startIcon={isPressBackKey ? <CircularProgress size={16} /> : undefined}
                sx={{ flex: 1 }}
              >
                {isPressBackKey ? 'Pressing...' : 'Back'}
              </Button>
              <Button
                variant="outlined"
                size="small"
                onClick={handlePressOkKey}
                disabled={isAnyActionExecuting}
                color={getButtonColor(okKeyStatus)}
                startIcon={isPressOkKey ? <CircularProgress size={16} /> : undefined}
                sx={{ flex: 1 }}
              >
                {isPressOkKey ? 'Pressing...' : 'OK'}
              </Button>
              <Button
                variant="outlined"
                size="small"
                onClick={handlePressEscKey}
                disabled={isAnyActionExecuting}
                color={getButtonColor(escKeyStatus)}
                startIcon={isPressEscKey ? <CircularProgress size={16} /> : undefined}
                sx={{ flex: 1 }}
              >
                {isPressEscKey ? 'Pressing...' : 'Esc'}
              </Button>
            </Box>
            <Box sx={{ display: 'flex', gap: 0.5 }}>
              <Button
                variant="outlined"
                size="small"
                onClick={handleScrollUp}
                disabled={isAnyActionExecuting}
                color={getButtonColor(scrollUpStatus)}
                startIcon={isScrollingUp ? <CircularProgress size={16} /> : <ArrowUpwardIcon />}
                sx={{ flex: 1 }}
              >
                {isScrollingUp ? 'Scrolling...' : 'Scroll Up'}
              </Button>
              <Button
                variant="outlined"
                size="small"
                onClick={handleScrollDown}
                disabled={isAnyActionExecuting}
                color={getButtonColor(scrollDownStatus)}
                startIcon={isScrollingDown ? <CircularProgress size={16} /> : <ArrowDownwardIcon />}
                sx={{ flex: 1 }}
              >
                {isScrollingDown ? 'Scrolling...' : 'Scroll Down'}
              </Button>
            </Box>
          </Box>

          <Divider sx={{ my: 1 }} />

          {/* Playwright Section */}
          <Box sx={{ mb: 1 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 'bold', flex: 1 }}>
                Playwright
              </Typography>
              <IconButton
                size="small"
                onClick={() => setIsPlaywrightExpanded(!isPlaywrightExpanded)}
              >
                {isPlaywrightExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
              </IconButton>
            </Box>
            <Collapse in={isPlaywrightExpanded}>
              <Box>
                {/* Navigate Action */}
                <Box sx={{ mb: 1 }}>
                  <Typography
                    variant="caption"
                    sx={{ display: 'block', mb: 0.5, fontWeight: 'bold' }}
                  >
                    Navigate to URL
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <TextField
                      value={navigateUrl}
                      onChange={(e) => setNavigateUrl(e.target.value)}
                      placeholder="https://example.com"
                      variant="outlined"
                      size="small"
                      disabled={isExecuting}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          handleNavigate();
                        }
                      }}
                      sx={{
                        flex: 1,
                        '& .MuiOutlinedInput-root': {
                          fontSize: '0.875rem',
                        },
                      }}
                    />
                    <Button
                      variant="contained"
                      size="small"
                      onClick={handleNavigate}
                      disabled={!navigateUrl.trim() || isAnyActionExecuting}
                      color={getButtonColor(navigateStatus)}
                      startIcon={isNavigating ? <CircularProgress size={16} /> : undefined}
                      sx={{ minWidth: '60px' }}
                    >
                      {isNavigating ? 'Going...' : 'Go'}
                    </Button>
                  </Box>
                </Box>

                <Divider sx={{ my: 1 }} />

                {/* Click Element Action */}
                <Box sx={{ mb: 1 }}>
                  <Typography
                    variant="caption"
                    sx={{ display: 'block', mb: 0.5, fontWeight: 'bold' }}
                  >
                    Click Element
                  </Typography>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      <TextField
                        value={clickSelector}
                        onChange={(e) => setClickSelector(e.target.value)}
                        placeholder="CSS selector or text content (e.g., 'Google', button, #id, .class)"
                        variant="outlined"
                        size="small"
                        disabled={isExecuting}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            handleClickElement();
                          }
                        }}
                        sx={{
                          flex: 1,
                          '& .MuiOutlinedInput-root': {
                            fontSize: '0.875rem',
                          },
                        }}
                      />
                      <Button
                        variant="contained"
                        size="small"
                        onClick={handleClickElement}
                        disabled={!clickSelector.trim() || isAnyActionExecuting}
                        color={getButtonColor(clickStatus)}
                        startIcon={isClicking ? <CircularProgress size={16} /> : undefined}
                        sx={{ minWidth: '60px' }}
                      >
                        {isClicking ? 'Clicking...' : 'Click'}
                      </Button>
                    </Box>
                  </Box>
                </Box>

                <Divider sx={{ my: 1 }} />

                {/* Tap X,Y Action */}
                <Box sx={{ mb: 1 }}>
                  <Typography
                    variant="caption"
                    sx={{ display: 'block', mb: 0.5, fontWeight: 'bold' }}
                  >
                    Tap Coordinates
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <TextField
                      value={tapX}
                      onChange={(e) => setTapX(e.target.value)}
                      placeholder="X"
                      variant="outlined"
                      size="small"
                      type="number"
                      disabled={isExecuting}
                      sx={{
                        width: '80px',
                        '& .MuiOutlinedInput-root': {
                          fontSize: '0.875rem',
                        },
                      }}
                    />
                    <TextField
                      value={tapY}
                      onChange={(e) => setTapY(e.target.value)}
                      placeholder="Y"
                      variant="outlined"
                      size="small"
                      type="number"
                      disabled={isExecuting}
                      sx={{
                        width: '80px',
                        '& .MuiOutlinedInput-root': {
                          fontSize: '0.875rem',
                        },
                      }}
                    />
                    <Button
                      variant="contained"
                      size="small"
                      onClick={handleTapXY}
                      disabled={!tapX.trim() || !tapY.trim() || isAnyActionExecuting}
                      color={getButtonColor(tapStatus)}
                      startIcon={isTapping ? <CircularProgress size={16} /> : undefined}
                      sx={{ minWidth: '60px' }}
                    >
                      {isTapping ? 'Tapping...' : 'Tap'}
                    </Button>
                  </Box>
                </Box>

                <Divider sx={{ my: 1 }} />

                {/* Find Element Action */}
                <Box sx={{ mb: 1 }}>
                  <Typography
                    variant="caption"
                    sx={{ display: 'block', mb: 0.5, fontWeight: 'bold' }}
                  >
                    Find Element
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <TextField
                      value={findSelector}
                      onChange={(e) => setFindSelector(e.target.value)}
                      placeholder="CSS selector to find"
                      variant="outlined"
                      size="small"
                      disabled={isExecuting}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          handleFindElement();
                        }
                      }}
                      sx={{
                        flex: 1,
                        '& .MuiOutlinedInput-root': {
                          fontSize: '0.875rem',
                        },
                      }}
                    />
                    <Button
                      variant="contained"
                      size="small"
                      onClick={handleFindElement}
                      disabled={!findSelector.trim() || isAnyActionExecuting}
                      color={getButtonColor(findStatus)}
                      startIcon={isFinding ? <CircularProgress size={16} /> : undefined}
                      sx={{ minWidth: '60px' }}
                    >
                      {isFinding ? 'Finding...' : 'Find'}
                    </Button>
                  </Box>
                </Box>

                <Divider sx={{ my: 1 }} />

                {/* Dump Elements Action */}
                <Box sx={{ mb: 1 }}>
                  <Typography
                    variant="caption"
                    sx={{ display: 'block', mb: 0.5, fontWeight: 'bold' }}
                  >
                    Dump Elements
                  </Typography>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      <Button
                        variant="contained"
                        size="small"
                        onClick={handleDumpElements}
                        disabled={isAnyActionExecuting}
                        color={getButtonColor(dumpStatus)}
                        startIcon={isDumping ? <CircularProgress size={16} /> : undefined}
                        sx={{ minWidth: '80px', flex: 1 }}
                      >
                        {isDumping ? 'Dumping...' : 'Dump'}
                      </Button>
                      <Button
                        variant="outlined"
                        size="small"
                        onClick={handleClearElements}
                        disabled={webElements.length === 0}
                        sx={{ minWidth: '80px', flex: 1 }}
                      >
                        Clear
                      </Button>
                      <Button
                        variant="contained"
                        size="small"
                        onClick={handleActivateSemantic}
                        disabled={isAnyActionExecuting}
                        color={getButtonColor(semanticStatus)}
                        startIcon={isActivatingSemantic ? <CircularProgress size={16} /> : undefined}
                        sx={{ minWidth: '100px' }}
                      >
                        {isActivatingSemantic ? 'Activating...' : 'Activate Semantic'}
                      </Button>
                    </Box>
                    
                    {/* Element Selection Dropdown */}
                    {webElements.length > 0 && (
                      <FormControl fullWidth size="small">
                        <InputLabel>Select element to click...</InputLabel>
                        <Select
                          value={selectedElement}
                          label="Select element to click..."
                          onChange={(e) => handleDropdownElementSelect(e.target.value)}
                          MenuProps={{
                            PaperProps: {
                              style: {
                                maxHeight: 200,
                                width: 'auto',
                                maxWidth: '100%',
                              },
                            },
                          }}
                        >
                          {webElements.map((element, index) => {
                            // Generate display name
                            const getElementDisplayName = (el: WebElement): string => {
                              let displayName = '';
                              
                              // Priority: aria-label → textContent → tagName + selector
                              if (el.attributes['aria-label']) {
                                displayName = el.attributes['aria-label'];
                              } else if (el.textContent && el.textContent.trim()) {
                                displayName = `"${el.textContent.trim()}"`;
                              } else {
                                displayName = `${el.tagName}${el.id ? '#' + el.id : ''}`;
                              }
                              
                              // Prepend element index for identification
                              const fullDisplayName = `${index + 1}. ${displayName}`;
                              
                              // Limit length
                              return fullDisplayName.length > 40 
                                ? fullDisplayName.substring(0, 37) + '...'
                                : fullDisplayName;
                            };
                            
                            return (
                              <MenuItem
                                key={element.selector}
                                value={element.selector}
                                sx={{
                                  fontSize: '0.875rem',
                                  py: 1,
                                  px: 2,
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
                    )}
                  </Box>
                </Box>


              </Box>
            </Collapse>
          </Box>
        </Box>
      )}

      {/* Response Area - Collapsible */}
      {terminalOutput && (
        <Box>
          <Divider sx={{ my: 1 }} />
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
            <Typography variant="caption" sx={{ fontWeight: 'bold', flex: 1 }}>
              Response
            </Typography>
            <IconButton size="small" onClick={() => setIsResponseExpanded(!isResponseExpanded)}>
              {isResponseExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
            </IconButton>
          </Box>
          <Collapse in={isResponseExpanded}>
            <Paper
              ref={responseRef}
              sx={{
                p: 1,
                backgroundColor: '#1e1e1e',
                color: '#00ff00',
                fontFamily: 'monospace',
                fontSize: '0.75rem',
                overflow: 'auto',
                border: '1px solid #333',
                maxHeight: '200px',
              }}
            >
              <Box
                component="pre"
                sx={{
                  margin: 0,
                  fontFamily: 'monospace',
                  fontSize: '0.75rem',
                  lineHeight: 1.2,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                {terminalOutput}
              </Box>
            </Paper>
          </Collapse>
        </Box>
      )}

      {/* Show instructions when browser is closed */}
      {!isBrowserOpen && (
        <Box
          sx={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            textAlign: 'center',
            color: 'text.secondary',
          }}
        >
          <Typography variant="body2">Click "Open Browser" to start web automation</Typography>
        </Box>
      )}

      {/* Tap Animation Overlay */}
      {tapAnimation.show && (
        <Box
          sx={{
            position: 'fixed',
            left: tapAnimation.x - 20,
            top: tapAnimation.y - 20,
            width: 40,
            height: 40,
            borderRadius: '50%',
            backgroundColor: 'rgba(33, 150, 243, 0.6)',
            border: '2px solid #2196f3',
            pointerEvents: 'none',
            zIndex: 9999,
            animation: 'ripple 1s ease-out',
            '@keyframes ripple': {
              '0%': {
                transform: 'scale(0)',
                opacity: 1,
              },
              '100%': {
                transform: 'scale(2)',
                opacity: 0,
              },
            },
          }}
        />
      )}

      {/* Element Highlight Overlay */}
      {elementHighlight.show && (
        <Box
          sx={{
            position: 'fixed',
            left: elementHighlight.x,
            top: elementHighlight.y,
            width: elementHighlight.width,
            height: elementHighlight.height,
            backgroundColor: 'rgba(255, 193, 7, 0.3)',
            border: '2px solid #ffc107',
            pointerEvents: 'none',
            zIndex: 9998,
            animation: 'highlight 2s ease-out',
            '@keyframes highlight': {
              '0%': {
                opacity: 0,
                transform: 'scale(1.1)',
              },
              '20%': {
                opacity: 1,
                transform: 'scale(1)',
              },
              '100%': {
                opacity: 0,
                transform: 'scale(1)',
              },
            },
          }}
        />
      )}

      {/* Web Element Overlay */}
      {isElementsVisible && webElements.length > 0 && !isMinimized && typeof document !== 'undefined' && 
        createPortal(
          <PlaywrightWebOverlay
            elements={webElements}
            isVisible={isElementsVisible && !isMinimized}
            onElementClick={handleElementClick}
            panelInfo={getVNCPanelInfo()}
          />,
          document.body
        )
      }
    </Box>
  );
});
