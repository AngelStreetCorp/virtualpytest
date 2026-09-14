import { Box, Typography, Paper, Grid, Switch, FormControlLabel } from '@mui/material';
import { useState, useMemo } from 'react';

import { RemotePanel } from '../components/controller/remote/RemotePanel';
import { DEFAULT_DEVICE_RESOLUTION } from '../config/deviceResolutions';
import { Host } from '../types/common/Host_Types';

// Extended Host type to include controller_configs used in the components
interface TestHost extends Host {
  controller_configs?: {
    remote?: {
      implementation: string;
      type: string;
      parameters: any;
    };
    av?: {
      implementation: string;
      type: string;
      parameters: any;
    };
    [key: string]: any; // Allow indexing with string keys
  };
}

// Mock host data for testing different device types
const mockHosts: TestHost[] = [
  {
    host_name: 'Test Android Mobile',
    description: 'Android Mobile Test Device',
    host_url: 'http://localhost:6109',
    host_port: 6109,
    devices: [
      {
        device_id: 'device1',
        device_name: 'Android Mobile',
        device_model: 'android_mobile',
        device_capabilities: {
          av: 'hdmi_stream',
          remote: 'android_mobile',
        },
      },
    ],
    device_count: 1,
    status: 'online',
    last_seen: Date.now(),
    registered_at: new Date().toISOString(),
    system_stats: {
      cpu_percent: 10,
      memory_percent: 30,
      disk_percent: 50,
      platform: 'linux',
      architecture: 'x64',
      python_version: '3.9.0',
    },
    isLocked: false,
    controller_configs: {
      remote: {
        implementation: 'android_mobile',
        type: 'android_mobile',
        parameters: {},
      },
      av: {
        implementation: 'hdmi_stream',
        type: 'hdmi_stream',
        parameters: {},
      },
    },
  },
  {
    host_name: 'Test Android TV',
    description: 'Android TV Test Device',
    host_url: 'http://localhost:6109',
    host_port: 6109,
    devices: [
      {
        device_id: 'device1',
        device_name: 'Android TV',
        device_model: 'android_tv',
        device_capabilities: {
          av: 'hdmi_stream',
          remote: 'android_tv',
        },
      },
    ],
    device_count: 1,
    status: 'online',
    last_seen: Date.now(),
    registered_at: new Date().toISOString(),
    system_stats: {
      cpu_percent: 10,
      memory_percent: 30,
      disk_percent: 50,
      platform: 'linux',
      architecture: 'x64',
      python_version: '3.9.0',
    },
    isLocked: false,
    controller_configs: {
      remote: {
        implementation: 'android_tv',
        type: 'android_tv',
        parameters: {},
      },
      av: {
        implementation: 'hdmi_stream',
        type: 'hdmi_stream',
        parameters: {},
      },
    },
  },
  {
    host_name: 'Test iOS Mobile',
    description: 'iOS Mobile Test Device',
    host_url: 'http://localhost:6109',
    host_port: 6109,
    devices: [
      {
        device_id: 'device1',
        device_name: 'iOS Mobile',
        device_model: 'ios_mobile',
        device_capabilities: {
          av: 'hdmi_stream',
          remote: 'appium_remote',
        },
      },
    ],
    device_count: 1,
    status: 'online',
    last_seen: Date.now(),
    registered_at: new Date().toISOString(),
    system_stats: {
      cpu_percent: 10,
      memory_percent: 30,
      disk_percent: 50,
      platform: 'darwin',
      architecture: 'x64',
      python_version: '3.9.0',
    },
    isLocked: false,
    controller_configs: {
      remote: {
        implementation: 'appium_remote',
        type: 'appium_remote',
        parameters: {
          device_ip: '192.168.8.1',
          device_port: '5555',
          platform_name: 'iOS',
          automation_name: 'XCUITest',
          appium_url: 'http://localhost:4723',
        },
      },
      av: {
        implementation: 'hdmi_stream',
        type: 'hdmi_stream',
        parameters: {},
      },
    },
  },
  {
    host_name: 'Test Bluetooth Remote',
    description: 'Bluetooth Remote Test Device',
    host_url: 'http://localhost:6109',
    host_port: 6109,
    devices: [
      {
        device_id: 'device1',
        device_name: 'Bluetooth Remote',
        device_model: 'bluetooth_remote',
        device_capabilities: {
          av: 'hdmi_stream',
          remote: 'bluetooth_remote',
        },
      },
    ],
    device_count: 1,
    status: 'online',
    last_seen: Date.now(),
    registered_at: new Date().toISOString(),
    system_stats: {
      cpu_percent: 10,
      memory_percent: 30,
      disk_percent: 50,
      platform: 'linux',
      architecture: 'x64',
      python_version: '3.9.0',
    },
    isLocked: false,
    controller_configs: {
      remote: {
        implementation: 'bluetooth_remote',
        type: 'bluetooth_remote',
        parameters: {},
      },
      av: {
        implementation: 'hdmi_stream',
        type: 'hdmi_stream',
        parameters: {},
      },
    },
  },

  {
    host_name: 'Test STB Remote',
    description: 'STB IR Remote Test Device',
    host_url: 'http://localhost:6109',
    host_port: 6109,
    devices: [
      {
        device_id: 'device1',
        device_name: 'STB Remote',
        device_model: 'ir_remote',
        device_capabilities: {
          av: 'hdmi_stream',
          remote: 'ir_remote',
        },
        ir_type: 'stb',
      },
    ],
    device_count: 1,
    status: 'online',
    last_seen: Date.now(),
    registered_at: new Date().toISOString(),
    system_stats: {
      cpu_percent: 10,
      memory_percent: 30,
      disk_percent: 50,
      platform: 'linux',
      architecture: 'x64',
      python_version: '3.9.0',
    },
    isLocked: false,
    controller_configs: {
      remote: {
        implementation: 'ir_remote',
        type: 'ir_remote',
        parameters: {
          ir_type: 'stb',
        },
      },
      av: {
        implementation: 'hdmi_stream',
        type: 'hdmi_stream',
        parameters: {},
      },
    },
  },
  {
    host_name: 'Test Samsung Remote',
    description: 'Samsung IR Remote Test Device',
    host_url: 'http://localhost:6109',
    host_port: 6109,
    devices: [
      {
        device_id: 'device1',
        device_name: 'Samsung Remote',
        device_model: 'ir_remote',
        device_capabilities: {
          av: 'hdmi_stream',
          remote: 'ir_remote',
        },
        ir_type: 'samsung',
      },
    ],
    device_count: 1,
    status: 'online',
    last_seen: Date.now(),
    registered_at: new Date().toISOString(),
    system_stats: {
      cpu_percent: 10,
      memory_percent: 30,
      disk_percent: 50,
      platform: 'linux',
      architecture: 'x64',
      python_version: '3.9.0',
    },
    isLocked: false,
    controller_configs: {
      remote: {
        implementation: 'ir_remote',
        type: 'ir_remote',
        parameters: {
          ir_type: 'samsung',
        },
      },
      av: {
        implementation: 'hdmi_stream',
        type: 'hdmi_stream',
        parameters: {},
      },
    },
  },
  {
    host_name: 'Test FireTV Remote',
    description: 'FireTV IR Remote Test Device',
    host_url: 'http://localhost:6109',
    host_port: 6109,
    devices: [
      {
        device_id: 'device1',
        device_name: 'FireTV Remote',
        device_model: 'ir_remote',
        device_capabilities: {
          av: 'hdmi_stream',
          remote: 'ir_remote',
        },
        ir_type: 'firetv',
      },
    ],
    device_count: 1,
    status: 'online',
    last_seen: Date.now(),
    registered_at: new Date().toISOString(),
    system_stats: {
      cpu_percent: 10,
      memory_percent: 30,
      disk_percent: 50,
      platform: 'linux',
      architecture: 'x64',
      python_version: '3.9.0',
    },
    isLocked: false,
    controller_configs: {
      remote: {
        implementation: 'ir_remote',
        type: 'ir_remote',
        parameters: {
          ir_type: 'firetv',
        },
      },
      av: {
        implementation: 'hdmi_stream',
        type: 'hdmi_stream',
        parameters: {},
      },
    },
  },
  {
    host_name: 'Test Apple TV Remote',
    description: 'Apple TV IR Remote Test Device',
    host_url: 'http://localhost:6109',
    host_port: 6109,
    devices: [
      {
        device_id: 'device1',
        device_name: 'Apple TV Remote',
        device_model: 'ir_remote',
        device_capabilities: {
          av: 'hdmi_stream',
          remote: 'ir_remote',
        },
        ir_type: 'apple_tv',
      },
    ],
    device_count: 1,
    status: 'online',
    last_seen: Date.now(),
    registered_at: new Date().toISOString(),
    system_stats: {
      cpu_percent: 10,
      memory_percent: 30,
      disk_percent: 50,
      platform: 'linux',
      architecture: 'x64',
      python_version: '3.9.0',
    },
    isLocked: false,
    controller_configs: {
      remote: {
        implementation: 'ir_remote',
        type: 'ir_remote',
        parameters: {
          ir_type: 'apple_tv',
        },
      },
      av: {
        implementation: 'hdmi_stream',
        type: 'hdmi_stream',
        parameters: {},
      },
    },
  },
];

export default function RemoteTestPage() {
  const [selectedHost, setSelectedHost] = useState<TestHost>(mockHosts[0]);
  const [useModalLayout, setUseModalLayout] = useState<boolean>(false);
  const [showRemote, setShowRemote] = useState<boolean>(true);
  const [showStackedTest, setShowStackedTest] = useState<boolean>(false);

  // State to coordinate between HDMIStream and RemotePanel
  const [captureMode] = useState<'stream' | 'screenshot' | 'video'>('stream');
  const [streamCollapsed] = useState<boolean>(true);
  const [streamMinimized] = useState<boolean>(false);

  // Stable stream container dimensions to prevent re-renders - copied from RecHostStreamModal
  const streamContainerDimensions = useMemo(() => {
    if (!useModalLayout && !showStackedTest) return undefined;

    const windowWidth = typeof window !== 'undefined' ? window.innerWidth : DEFAULT_DEVICE_RESOLUTION.width;
    const windowHeight = typeof window !== 'undefined' ? window.innerHeight : DEFAULT_DEVICE_RESOLUTION.height;

    // Modal dimensions (95vw x 90vh)
    const modalWidth = windowWidth * 0.95;
    const modalHeight = windowHeight * 0.9;

    // Header height
    const headerHeight = 48;

    // Use fixed stream area (assume remote might be shown)
    const streamAreaWidth = modalWidth * 0.75;
    const streamAreaHeight = modalHeight - headerHeight;

    // Modal position (centered)
    const modalX = (windowWidth - modalWidth) / 2;
    const modalY = (windowHeight - modalHeight) / 2;

    // Stream container position
    const streamX = modalX;
    const streamY = modalY + headerHeight;

    return {
      width: Math.round(streamAreaWidth),
      height: Math.round(streamAreaHeight),
      x: Math.round(streamX),
      y: Math.round(streamY),
    };
  }, [useModalLayout, showStackedTest]);

  // Stable device resolution to prevent re-renders
  const stableDeviceResolution = useMemo(() => DEFAULT_DEVICE_RESOLUTION, []);

  console.log('[@page:RemoteTestPage] Rendering test page with host:', selectedHost.host_name);

  return (
    <Box sx={{ p: 3, minHeight: '100vh', backgroundColor: 'background.default' }}>
      <Typography variant="h4" gutterBottom>
        Remote & AV Stream Testing
      </Typography>

      <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
        Test different remote configurations and panel layouts without device control
      </Typography>

      {/* Device Selector */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Select Device Type to Test:
        </Typography>
        <Grid container spacing={2}>
          {mockHosts.map((host) => (
            <Grid item key={host.host_name}>
              <Box
                component="button"
                onClick={() => setSelectedHost(host)}
                sx={{
                  p: 2,
                  border: '2px solid',
                  borderColor:
                    selectedHost.host_name === host.host_name ? 'primary.main' : 'divider',
                  borderRadius: 1,
                  backgroundColor:
                    selectedHost.host_name === host.host_name
                      ? 'primary.light'
                      : 'background.paper',
                  color:
                    selectedHost.host_name === host.host_name
                      ? 'primary.contrastText'
                      : 'text.primary',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                  '&:hover': {
                    borderColor: 'primary.main',
                    backgroundColor: 'primary.light',
                  },
                }}
              >
                <Typography variant="body2" fontWeight="bold">
                  {host.host_name}
                </Typography>
                <Typography variant="caption" display="block">
                  {host.devices[0].device_model}
                </Typography>
              </Box>
            </Grid>
          ))}
        </Grid>
      </Paper>

      {/* Modal Layout Toggle */}
      <Paper sx={{ p: 2, mb: 3, backgroundColor: 'warning.light' }}>
        <FormControlLabel
          control={
            <Switch
              checked={useModalLayout}
              onChange={(e) => setUseModalLayout(e.target.checked)}
              color="primary"
            />
          }
          label={
            <Typography variant="body2" fontWeight="bold">
              Use RecHostStreamModal Layout (button_layout_recmodal)
            </Typography>
          }
        />
        <Typography variant="caption" display="block" sx={{ mt: 1 }}>
          When enabled, this will simulate the remote layout as it appears in RecHostStreamModal
          using button_layout_recmodal
        </Typography>
      </Paper>

      {/* Remote Toggle */}
      <Paper sx={{ p: 2, mb: 3, backgroundColor: 'info.light' }}>
        <FormControlLabel
          control={
            <Switch
              checked={showRemote}
              onChange={(e) => setShowRemote(e.target.checked)}
              color="primary"
            />
          }
          label={
            <Typography variant="body2" fontWeight="bold">
              Show Remote Panel
            </Typography>
          }
        />
      </Paper>

      {/* Fire TV + Android TV Stacked Test */}
      <Paper sx={{ p: 2, mb: 3, backgroundColor: 'secondary.light' }}>
        <FormControlLabel
          control={
            <Switch
              checked={showStackedTest}
              onChange={(e) => setShowStackedTest(e.target.checked)}
              color="primary"
            />
          }
          label={
            <Typography variant="body2" fontWeight="bold">
              Fire TV + Android TV Stacked Modal Test
            </Typography>
          }
        />
        <Typography variant="caption" display="block" sx={{ mt: 1 }}>
          Shows both Fire TV and Android TV remotes stacked in modal layout for comparison
        </Typography>
      </Paper>

      {/* Current Selection Info */}
      <Paper sx={{ p: 2, mb: 3, backgroundColor: 'info.light' }}>
        <Typography variant="h6" gutterBottom>
          Currently Testing: {selectedHost.host_name}
        </Typography>
        <Typography variant="body2">
          Device Model: <strong>{selectedHost.devices[0].device_model}</strong>
        </Typography>
        <Typography variant="body2">
          Remote Type:{' '}
          <strong>
            {(() => {
              if (!selectedHost.controller_configs) return 'None';
              const remoteKey = Object.keys(selectedHost.controller_configs).find((key) =>
                key.startsWith('remote_'),
              );
              return remoteKey
                ? selectedHost.controller_configs[remoteKey]?.implementation || 'Unknown'
                : selectedHost.controller_configs.remote?.implementation || 'None';
            })()}
          </strong>
        </Typography>
        <Typography variant="body2">
          AV Type: <strong>{selectedHost.controller_configs?.av?.type || 'None'}</strong>
        </Typography>
        <Typography variant="body2">
          Layout Mode:{' '}
          <strong>
            {useModalLayout
              ? 'RecHostStreamModal (button_layout_recmodal)'
              : 'Standard (button_layout)'}
          </strong>
        </Typography>
      </Paper>

      {/* Instructions */}
      <Paper sx={{ p: 2, mb: 3, backgroundColor: 'success.light' }}>
        <Typography variant="body2" gutterBottom>
          <strong>Testing Instructions:</strong>
        </Typography>
        <Typography variant="body2" component="ul" sx={{ pl: 2 }}>
          <li>Remote panels should appear at bottom-right with device-specific sizing</li>
          <li>AV stream is mocked (bottom-left) - no real streaming for faster testing</li>
          <li>Toggle panels between collapsed/expanded states</li>
          <li>Verify button overlay positioning and sizing from config files</li>
          <li>
            Toggle "Use RecHostStreamModal Layout" to test button_layout_recmodal configuration
          </li>
          <li>Focus on button alignment testing - no actual device control</li>
        </Typography>
      </Paper>

      {/* Test Components */}
      {showStackedTest ? (
        // Fire TV + Android TV Stacked Modal Test
        <Box
          sx={{
            position: 'relative',
            width: '95vw',
            height: '90vh',
            backgroundColor: 'background.paper',
            borderRadius: 2,
            boxShadow: 24,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            margin: '0 auto',
          }}
        >
          {/* Header */}
          <Box
            sx={{
              px: 2,
              py: 1,
              backgroundColor: 'grey.800',
              color: 'white',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              borderRadius: '8px 8px 0 0',
              minHeight: 48,
            }}
          >
            <Typography variant="h6" component="h2">
              Fire TV + Android TV Stacked Modal Test
            </Typography>
          </Box>

          {/* Main Content */}
          <Box
            sx={{
              flex: 1,
              display: 'flex',
              overflow: 'hidden',
              backgroundColor: 'black',
              position: 'relative',
            }}
          >
            {/* Stream Viewer */}
            <Box
              sx={{
                width: '75%',
                position: 'relative',
                overflow: 'hidden',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                backgroundColor: 'black',
              }}
            >
              <Typography sx={{ color: 'white' }}>Fire TV + Android TV Modal Test</Typography>
            </Box>

            {/* Stacked Remote Panels */}
            <Box
              sx={{
                width: '25%',
                backgroundColor: 'background.default',
                borderLeft: '1px solid',
                borderColor: 'divider',
                overflow: 'auto',
                display: 'flex',
                flexDirection: 'column',
                height: '100%',
              }}
            >
              {/* Android TV Remote */}
              <RemotePanel
                host={mockHosts.find(h => h.host_name === 'Test Android TV') as any}
                deviceId="device1"
                deviceModel="android_tv"
                remoteType="android_tv"
                isConnected={true}
                onReleaseControl={() => console.log('Release Android TV control')}
                initialCollapsed={false}
                deviceResolution={stableDeviceResolution}
                streamCollapsed={false}
                streamMinimized={false}
                streamContainerDimensions={streamContainerDimensions ? {
                  ...streamContainerDimensions,
                  height: Math.round((streamContainerDimensions.height - 60) / 2) + 30
                } : undefined}
                disableResize={true}
              />
              
              {/* Fire TV Remote */}
              <RemotePanel
                host={mockHosts.find(h => h.host_name === 'Test FireTV Remote') as any}
                deviceId="device1"
                deviceModel="ir_remote"
                remoteType="ir_remote"
                isConnected={true}
                onReleaseControl={() => console.log('Release Fire TV control')}
                initialCollapsed={false}
                deviceResolution={stableDeviceResolution}
                streamCollapsed={false}
                streamMinimized={false}
                streamContainerDimensions={streamContainerDimensions ? {
                  ...streamContainerDimensions,
                  height: Math.round((streamContainerDimensions.height - 60) / 2) + 30
                } : undefined}
                disableResize={true}
              />
            </Box>
          </Box>
        </Box>
      ) : useModalLayout ? (
        // Modal layout - mimic RecHostStreamModal layout
        <Box
          sx={{
            position: 'relative',
            width: '95vw',
            height: '90vh',
            backgroundColor: 'background.paper',
            borderRadius: 2,
            boxShadow: 24,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            margin: '0 auto',
          }}
        >
          {/* Header */}
          <Box
            sx={{
              px: 2,
              py: 1,
              backgroundColor: 'grey.800',
              color: 'white',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              borderRadius: '8px 8px 0 0',
              minHeight: 48,
            }}
          >
            <Typography variant="h6" component="h2">
              {selectedHost.devices[0].device_name || selectedHost.host_name} - Modal Test
            </Typography>
          </Box>

          {/* Main Content */}
          <Box
            sx={{
              flex: 1,
              display: 'flex',
              overflow: 'hidden',
              backgroundColor: 'black',
              position: 'relative',
            }}
          >
            {/* Stream Viewer */}
            <Box
              sx={{
                width: showRemote ? '75%' : '100%',
                position: 'relative',
                overflow: 'hidden',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                backgroundColor: 'black',
              }}
            >
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  height: '100%',
                  color: 'white',
                }}
              >
                <Typography>Stream area (mock)</Typography>
              </Box>
            </Box>

            {/* Remote Control Panel */}
            {showRemote && (
              <Box
                sx={{
                  width: '25%',
                  backgroundColor: 'background.default',
                  borderLeft: '1px solid',
                  borderColor: 'divider',
                  overflow: 'auto',
                  display: 'flex',
                  flexDirection: 'column',
                  height: '100%',
                }}
              >
                <RemotePanel
                  host={selectedHost as any}
                  deviceId={selectedHost.devices[0].device_id}
                  deviceModel={selectedHost.devices[0].device_model}
                  isConnected={true}
                  onReleaseControl={() => console.log('Release control')}
                  initialCollapsed={false}
                  deviceResolution={stableDeviceResolution}
                  streamCollapsed={false}
                  streamMinimized={false}
                  streamContainerDimensions={streamContainerDimensions}
                />
              </Box>
            )}
          </Box>
        </Box>
      ) : (
        // Standard layout
        <Box sx={{ position: 'relative', minHeight: '600px' }}>
          {/* Remote Panel */}
          {showRemote &&
            (() => {
              if (!selectedHost.controller_configs) return false;
              return (
                Object.keys(selectedHost.controller_configs).some((key) =>
                  key.startsWith('remote_'),
                ) || selectedHost.controller_configs.remote !== undefined
              );
            })() && (
              <RemotePanel
                host={selectedHost as any}
                deviceId={selectedHost.devices[0].device_id}
                deviceModel={selectedHost.devices[0].device_model}
                isConnected={true}
                initialCollapsed={true}
                deviceResolution={DEFAULT_DEVICE_RESOLUTION}
                streamCollapsed={streamCollapsed}
                streamMinimized={streamMinimized}
                streamHidden={!selectedHost.controller_configs?.av} // Stream is hidden when no AV config
                captureMode={captureMode}
              />
            )}

          {/* AV Stream - Optional for testing */}
          {selectedHost.controller_configs?.av && (
            <Box
              sx={{
                position: 'fixed',
                bottom: '20px',
                left: '20px',
                width: '300px',
                height: '200px',
                backgroundColor: 'background.paper',
                border: '2px dashed',
                borderColor: 'divider',
                borderRadius: 2,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: 1000,
              }}
            >
              <Typography variant="body2" color="text.secondary" textAlign="center">
                Mock AV Stream<br />
                (Stream testing disabled)<br />
                {streamCollapsed ? 'Collapsed' : 'Expanded'} | {captureMode}
              </Typography>
            </Box>
          )}

          {/* Center message */}
          <Box
            sx={{
              position: 'absolute',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              textAlign: 'center',
              p: 3,
              backgroundColor: 'background.paper',
              border: '2px dashed',
              borderColor: 'divider',
              borderRadius: 2,
            }}
          >
            <Typography variant="h6" gutterBottom>
              Testing Area
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Remote and AV panels should appear at screen edges
            </Typography>
            <Typography variant="body2" color="text.secondary">
              This center area represents your main workspace
            </Typography>
          </Box>
        </Box>
      )}
    </Box>
  );
}
