/**
 * Content Viewer Component
 * 
 * Displays dynamic content in the AgentChat center area above the minimized chat.
 * Content types: navigation-tree, testcase-flow, device-preview, report-chart, data-table
 * 
 * Controlled by AI agent via show_content_panel tool.
 */

import React from 'react';
import {
  Box,
  Typography,
  IconButton,
  Chip,
  CircularProgress,
  Tabs,
  Tab,
} from '@mui/material';
import {
  Close as CloseIcon,
  AccountTree as TreeIcon,
  PlaylistPlay as TestCaseIcon,
  Tv as StreamIcon,
  BarChart as ChartIcon,
  TableChart as TableIcon,
  Fullscreen as FullscreenIcon,
  FullscreenExit as FullscreenExitIcon,
  Error as ErrorIcon,
  OpenInNew as OpenInNewIcon,
} from '@mui/icons-material';
import { useTheme } from '@mui/material/styles';
import { AGENT_CHAT_PALETTE as PALETTE } from '../../constants/agentChatTheme';

// Real viewer components
import { NavigationTreeViewer } from './NavigationTreeViewer';
import { TestCaseFlowViewer } from './TestCaseFlowViewer';
import { CampaignFlowViewer } from './CampaignFlowViewer';
import { HeatmapViewer } from './HeatmapViewer';
import { AlertsViewer } from './AlertsViewer';

// REC components
import { DeviceStreamGrid } from '../common/DeviceStreaming/DeviceStreamGrid';

// Hooks
import { useHostData, useHostControl } from '../../hooks/useHostManager';

// Content type definitions
export type ContentType =
  | 'navigation-tree'
  | 'testcase-flow'
  | 'campaign-flow'
  | 'heatmap'
  | 'alerts'
  | 'device-preview'
  | 'report-chart'
  | 'data-table'  
  | 'execution-log';

export interface ContentData {
  // Navigation tree
  tree_id?: string;
  node_id?: string;
  userinterface_name?: string;

  // Test case
  testcase_id?: string;
  editable?: boolean;

  // Campaign
  campaign_id?: string;

  // REC preview
  device_ids?: string[];
  stream_urls?: string[];

  // Report/Chart
  chart_type?: 'bar' | 'line' | 'pie' | 'area';
  chart_data?: any;

  // Data table
  columns?: { field: string; header: string }[];
  rows?: any[];

  // Execution log
  log_entries?: { timestamp: string; level: string; message: string }[];
}

export type ContentTab = 'navigation' | 'testcase' | 'campaign' | 'device-preview' | 'heatmap' | 'alerts';

interface ContentViewerProps {
  contentType: ContentType | null;
  contentData: ContentData | null;
  title?: string;
  onClose: () => void;
  isLoading?: boolean;
  // Tab support
  activeTab?: ContentTab;
  onTabChange?: (tab: ContentTab) => void;
  selectedUserInterface?: string;
  selectedTestCase?: string;
  selectedCampaign?: string;
  selectedDevices?: string[];
  // Fullscreen support
  isFullscreen?: boolean;
  onFullscreenChange?: (fullscreen: boolean) => void;
}

// Icon mapping for content types
const ContentTypeIcon: Record<ContentType, React.ElementType> = {
  'navigation-tree': TreeIcon,
  'testcase-flow': TestCaseIcon,
  'campaign-flow': TestCaseIcon, // Use same icon as testcase for now
  'heatmap': TreeIcon, // Use TreeIcon for heatmap grid
  'alerts': ErrorIcon, // Use ErrorIcon for alerts/incidents
  'device-preview': StreamIcon,
  'report-chart': ChartIcon,
  'data-table': TableIcon,
  'execution-log': TableIcon,
};

// Label mapping for content types
const ContentTypeLabel: Record<ContentType, string> = {
  'navigation-tree': 'Navigation Tree',
  'testcase-flow': 'Test Case',
  'campaign-flow': 'Campaign',
  'heatmap': 'Heatmap',
  'alerts': 'Alerts',
  'device-preview': 'Device Preview',
  'report-chart': 'Report',
  'data-table': 'Data',
  'execution-log': 'Execution Log',
};

export const ContentViewer: React.FC<ContentViewerProps> = ({
  contentType,
  contentData,
  title,
  onClose,
  isLoading = false,
  activeTab = 'device-preview',
  onTabChange,
  selectedUserInterface,
  selectedTestCase,
  selectedCampaign,
  selectedDevices,
  isFullscreen = false,
  onFullscreenChange,
}) => {
  const theme = useTheme();
  const isDarkMode = theme.palette.mode === 'dark';

  // Get hosts and devices for REC preview
  const { getAllHosts, getDevicesFromHost } = useHostData();
  const allHosts = getAllHosts();

  // Get control state for navigation tree viewer
  const { isControlActive, selectedHost, selectedDeviceId } = useHostControl();

  // Handle tab redirects
  const handleTabRedirect = (tab: ContentTab) => {
    switch (tab) {
      case 'navigation':
        if (selectedUserInterface) {
          window.open(`/navigation-editor/${selectedUserInterface}`, '_blank');
        }
        break;
      case 'testcase':
        if (selectedTestCase) {
          window.open(`/builder/test-builder?testcase=${selectedTestCase}`, '_blank');
        }
        break;
      case 'campaign':
        if (selectedCampaign) {
          window.open(`/builder/campaign-builder?campaign=${selectedCampaign}`, '_blank');
        }
        break;
      case 'device-preview':
        window.open('/device-control', '_blank');
        break;  
      case 'heatmap':
        window.open('/monitoring/heatmap', '_blank');
        break;
      case 'alerts':
        window.open('/monitoring/incidents', '_blank');
        break;
    }
  };

  // Determine if tabs should be shown (when we have manual selection mode)
  const showTabs = selectedUserInterface !== undefined || selectedTestCase !== undefined || selectedCampaign !== undefined || selectedDevices !== undefined;

  // Tab enabled states
  const navigationEnabled = !!selectedUserInterface;
  const testcaseEnabled = !!selectedTestCase;
  const campaignEnabled = !!selectedCampaign;

  // Don't render if no content type AND no tabs
  if (!contentType && !showTabs) return null;
  
  // If showing tabs but no content type, determine from active tab
  const effectiveContentType = contentType || (activeTab === 'testcase' ? 'testcase-flow' : 'navigation-tree');

  const Icon = ContentTypeIcon[effectiveContentType];
  const typeLabel = ContentTypeLabel[effectiveContentType];

  // Render content based on type
  const renderContent = () => {
    if (isLoading) {
      return (
        <Box sx={{ 
          flex: 1, 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center',
          flexDirection: 'column',
          gap: 2,
        }}>
          <CircularProgress size={40} sx={{ color: PALETTE.accent }} />
          <Typography variant="body2" color="text.secondary">
            Loading {typeLabel}...
          </Typography>
        </Box>
      );
    }

    switch (contentType) {
      case 'navigation-tree':
        return <NavigationTreeContent data={contentData} selectedHost={selectedHost} selectedDeviceId={selectedDeviceId} isControlActive={isControlActive} />;
      case 'testcase-flow':
        return <TestCaseFlowContent data={contentData} />;
      case 'campaign-flow':
        return <CampaignFlowContent data={contentData} selectedUserInterface={selectedUserInterface} />;
      case 'heatmap':
        return <HeatmapContent data={contentData} />;
      case 'alerts':
        return <AlertsContent data={contentData} />;
      case 'device-preview':
        return <RecPreviewContent data={contentData} allHosts={allHosts} getDevicesFromHost={getDevicesFromHost} />;
      case 'report-chart':
        return <ReportChartContent data={contentData} />;
      case 'data-table':
        return <DataTableContent data={contentData} />;
      case 'execution-log':
        return <ExecutionLogContent data={contentData} />;
      default:
        return (
          <Box sx={{ p: 4, textAlign: 'center' }}>
            <Typography color="text.secondary">
              Unknown content type: {contentType}
            </Typography>
          </Box>
        );
    }
  };

  // Render content based on effective type (handles both tab mode and direct mode)
  const renderTabContent = () => {
    if (isLoading) {
      return (
        <Box sx={{ 
          flex: 1, 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center',
          flexDirection: 'column',
          gap: 2,
        }}>
          <CircularProgress size={40} sx={{ color: PALETTE.accent }} />
          <Typography variant="body2" color="text.secondary">
            Loading...
          </Typography>
        </Box>
      );
    }
    
    // In tab mode, use activeTab to determine content
    if (showTabs) {
      if (activeTab === 'navigation' && selectedUserInterface) {
        return (
          <Box sx={{ flex: 1, display: 'flex', width: '100%', height: '100%' }}>
            <NavigationTreeViewer
              userInterfaceName={selectedUserInterface}
              readOnly={false}
              selectedHost={selectedHost}
              selectedDeviceId={selectedDeviceId || undefined}
              isControlActive={isControlActive}
            />
          </Box>
        );
      } else if (activeTab === 'testcase' && selectedTestCase) {
        return (
          <Box sx={{ flex: 1, display: 'flex', width: '100%', height: '100%' }}>
            <TestCaseFlowViewer
              testcaseId={selectedTestCase}
              readOnly={true}
            />
          </Box>
        );
      } else if (activeTab === 'campaign' && selectedCampaign) {
        return (
          <Box sx={{ flex: 1, display: 'flex', width: '100%', height: '100%' }}>
            <CampaignFlowViewer
              campaignId={selectedCampaign}
              readOnly={true}
              selectedUserInterface={selectedUserInterface}
            />
          </Box>
        );
      } else if (activeTab === 'device-preview') {
        // Convert device IDs to DeviceStreamGrid format
        const devices = (selectedDevices || []).map(deviceId => {
          const [hostName, deviceId_part] = deviceId.split(':');
          return { hostName, deviceId: deviceId_part };
        });

        return (
          <Box sx={{ flex: 1, display: 'flex', width: '100%', height: '100%', p: 2, overflow: 'auto' }}>
            <DeviceStreamGrid
              devices={devices}
              allHosts={allHosts}
              getDevicesFromHost={getDevicesFromHost}
              maxColumns={3}
              isActive={true}
            />
          </Box>
        );
      } else if (activeTab === 'heatmap') {
        return (
          <Box sx={{ flex: 1, display: 'flex', width: '100%', height: '100%' }}>
            <HeatmapViewer />
          </Box>
        );
      } else if (activeTab === 'alerts') {
        return (
          <Box sx={{ flex: 1, display: 'flex', width: '100%', height: '100%' }}>
            <AlertsViewer />
          </Box>
        );
      } else {
        // No valid selection for active tab
        return (
          <Box sx={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexDirection: 'column',
            gap: 2,
            p: 4,
          }}>
            {activeTab === 'navigation' ? (
              <>
                <TreeIcon sx={{ fontSize: 64, color: 'text.disabled', opacity: 0.3 }} />
                <Typography variant="body1" color="text.secondary">
                  Select an Interface to view navigation tree
                </Typography>
              </>
            ) : activeTab === 'testcase' ? (
              <>
                <TestCaseIcon sx={{ fontSize: 64, color: 'text.disabled', opacity: 0.3 }} />
                <Typography variant="body1" color="text.secondary">
                  Select a Test Case to view flow
                </Typography>
              </>
            ) : activeTab === 'campaign' ? (
              <>
                <TestCaseIcon sx={{ fontSize: 64, color: 'text.disabled', opacity: 0.3 }} />
                <Typography variant="body1" color="text.secondary">
                  Select a Campaign to view flow
                </Typography>
              </>
            ) : activeTab === 'device-preview' ? (
              <>
                <StreamIcon sx={{ fontSize: 64, color: 'text.disabled', opacity: 0.3 }} />
                <Typography variant="body1" color="text.secondary">
                  Device control page
                </Typography>
                <Typography variant="caption" color="text.disabled">
                  Click the icon to open device control
                </Typography>
              </>
            ) : activeTab === 'heatmap' ? (
              <>
                <TreeIcon sx={{ fontSize: 64, color: 'text.disabled', opacity: 0.3 }} />
                <Typography variant="body1" color="text.secondary">
                  Heatmap monitoring
                </Typography>
                <Typography variant="caption" color="text.disabled">
                  Click the icon to open heatmap
                </Typography>
              </>
            ) : activeTab === 'alerts' ? (
              <>
                <ErrorIcon sx={{ fontSize: 64, color: 'text.disabled', opacity: 0.3 }} />
                <Typography variant="body1" color="text.secondary">
                  Incident monitoring
                </Typography>
                <Typography variant="caption" color="text.disabled">
                  Click the icon to open alerts
                </Typography>
              </>
            ) : (
              <>
                <TreeIcon sx={{ fontSize: 64, color: 'text.disabled', opacity: 0.3 }} />
                <Typography variant="body1" color="text.secondary">
                  Unknown tab
                </Typography>
              </>
            )}
          </Box>
        );
      }
    }
    
    // Direct content mode (from AI agent)
    return renderContent();
  };

  return (
    <Box
      sx={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        bgcolor: isDarkMode ? PALETTE.sidebarBg : 'grey.50',
        borderBottom: '1px solid',
        borderColor: isDarkMode ? PALETTE.borderColor : 'grey.200',
        overflow: 'hidden',
      }}
    >
      {/* Header with Tabs */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 1,
          borderBottom: '1px solid',
          borderColor: isDarkMode ? PALETTE.borderColor : 'grey.200',
          bgcolor: isDarkMode ? PALETTE.surface : '#fff',
          minHeight: 44,
        }}
      >
        {/* Tabs (when in manual selection mode) */}
        {showTabs ? (
          <Tabs
            value={activeTab}
            onChange={(_, newValue) => onTabChange?.(newValue)}
            sx={{
              minHeight: 42,
              '& .MuiTabs-indicator': {
                backgroundColor: PALETTE.accent,
                height: 2,
              },
            }}
          >
            <Tab
              value="device-preview"
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <span>Device</span>
                  <OpenInNewIcon
                    sx={{ fontSize: 14, cursor: 'pointer' }}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleTabRedirect('device-preview');
                    }}
                  />
                </Box>
              }
              sx={{
                minHeight: 42,
                py: 1,
                px: 2,
                textTransform: 'none',
                fontSize: '0.85rem',
                fontWeight: activeTab === 'device-preview' ? 600 : 400,
                color: activeTab === 'device-preview' ? 'text.primary' : 'text.secondary',
                opacity: 1, // Always enabled - no selection required
                pointerEvents: 'auto',
              }}
            />
            <Tab
              value="navigation"
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <span>Userinterface</span>
                  {navigationEnabled && (
                    <OpenInNewIcon
                      sx={{ fontSize: 14, cursor: 'pointer' }}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleTabRedirect('navigation');
                      }}
                    />
                  )}
                </Box>
              }
              sx={{
                minHeight: 42,
                py: 1,
                px: 2,
                textTransform: 'none',
                fontSize: '0.85rem',
                fontWeight: activeTab === 'navigation' ? 600 : 400,
                color: activeTab === 'navigation' ? 'text.primary' : 'text.secondary',
                opacity: navigationEnabled ? 1 : 0.5,
                pointerEvents: navigationEnabled ? 'auto' : 'none',
              }}
            />
            <Tab
              value="testcase"
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <span>TestCase</span>
                  {testcaseEnabled && (
                    <OpenInNewIcon
                      sx={{ fontSize: 14, cursor: 'pointer' }}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleTabRedirect('testcase');
                      }}
                    />
                  )}
                </Box>
              }
              sx={{
                minHeight: 42,
                py: 1,
                px: 2,
                textTransform: 'none',
                fontSize: '0.85rem',
                fontWeight: activeTab === 'testcase' ? 600 : 400,
                color: activeTab === 'testcase' ? 'text.primary' : 'text.secondary',
                opacity: testcaseEnabled ? 1 : 0.5,
                pointerEvents: testcaseEnabled ? 'auto' : 'none',
              }}
            />
            <Tab
              value="campaign"
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <span>Campaign</span>
                  {campaignEnabled && (
                    <OpenInNewIcon
                      sx={{ fontSize: 14, cursor: 'pointer' }}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleTabRedirect('campaign');
                      }}
                    />
                  )}
                </Box>
              }
              sx={{
                minHeight: 42,
                py: 1,
                px: 2,
                textTransform: 'none',
                fontSize: '0.85rem',
                fontWeight: activeTab === 'campaign' ? 600 : 400,
                color: activeTab === 'campaign' ? 'text.primary' : 'text.secondary',
                opacity: campaignEnabled ? 1 : 0.5,
                pointerEvents: campaignEnabled ? 'auto' : 'none',
              }}
            />
            <Tab
              value="heatmap"
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <span>Heatmap</span>
                  <OpenInNewIcon
                    sx={{ fontSize: 14, cursor: 'pointer' }}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleTabRedirect('heatmap');
                    }}
                  />
                </Box>
              }
              sx={{
                minHeight: 42,
                py: 1,
                px: 2,
                textTransform: 'none',
                fontSize: '0.85rem',
                fontWeight: activeTab === 'heatmap' ? 600 : 400,
                color: activeTab === 'heatmap' ? 'text.primary' : 'text.secondary',
                opacity: 1, // Always enabled - no selection required
                pointerEvents: 'auto',
              }}
            />
            <Tab
              value="alerts"
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <span>Alerts</span>
                  <OpenInNewIcon
                    sx={{ fontSize: 14, cursor: 'pointer' }}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleTabRedirect('alerts');
                    }}
                  />
                </Box>
              }
              sx={{
                minHeight: 42,
                py: 1,
                px: 2,
                textTransform: 'none',
                fontSize: '0.85rem',
                fontWeight: activeTab === 'alerts' ? 600 : 400,
                color: activeTab === 'alerts' ? 'text.primary' : 'text.secondary',
                opacity: 1, // Always enabled - no selection required
                pointerEvents: 'auto',
              }}
            />
          </Tabs>
        ) : (
          /* Simple header when showing AI-triggered content */
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, px: 1 }}>
            <Icon sx={{ fontSize: 20, color: PALETTE.accent }} />
            <Typography variant="subtitle2" fontWeight={600}>
              {title || typeLabel}
            </Typography>
            <Chip
              label={typeLabel}
              size="small"
              sx={{
                height: 20,
                fontSize: '0.7rem',
                bgcolor: isDarkMode ? 'rgba(99, 102, 241, 0.2)' : 'rgba(99, 102, 241, 0.1)',
                color: PALETTE.accent,
              }}
            />
          </Box>
        )}
        
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <IconButton
            size="small"
            onClick={() => onFullscreenChange?.(!isFullscreen)}
            sx={{
              color: 'text.secondary',
              '&:hover': { color: PALETTE.accent },
            }}
          >
            {isFullscreen ? <FullscreenExitIcon fontSize="small" /> : <FullscreenIcon fontSize="small" />}
          </IconButton>
          <IconButton
            size="small"
            onClick={onClose}
            sx={{ 
              color: 'text.secondary',
              '&:hover': { color: 'error.main' },
            }}
          >
            <CloseIcon fontSize="small" />
          </IconButton>
        </Box>
      </Box>

      {/* Content Area */}
      <Box sx={{ flex: 1, overflow: 'auto', position: 'relative' }}>
        {renderTabContent()}
      </Box>
    </Box>
  );
};

// --- Content Type Components ---

// Navigation Tree Content - Uses real NavigationTreeViewer component
const NavigationTreeContent: React.FC<{ data: ContentData | null; selectedHost: any; selectedDeviceId: string | null; isControlActive: boolean }> = ({ data, selectedHost, selectedDeviceId, isControlActive }) => {
  // Require userinterface_name to show the navigation tree
  if (!data?.userinterface_name) {
    return (
      <Box sx={{ 
        flex: 1, 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'center',
        flexDirection: 'column',
        gap: 2,
        p: 4,
      }}>
        <TreeIcon sx={{ fontSize: 64, color: 'text.disabled', opacity: 0.3 }} />
        <Typography variant="body1" color="text.secondary">
          No user interface specified
        </Typography>
        <Typography variant="caption" color="text.disabled">
          Provide userinterface_name in content_data
        </Typography>
      </Box>
    );
  }

    return (
      <Box
        sx={{
          flex: 1,
          display: 'flex',
          width: 'calc(100% / 0.8)',
          height: 'calc(100% / 0.8)',
          transform: 'scale(0.8)',
          transformOrigin: 'top center',
        }}
      >
        <NavigationTreeViewer
          userInterfaceName={data.userinterface_name}
          readOnly={false}
          selectedHost={selectedHost}
          selectedDeviceId={selectedDeviceId || undefined}
          isControlActive={isControlActive}
        />
      </Box>
    );
};

// Test Case Flow Content - Uses real TestCaseFlowViewer component
const TestCaseFlowContent: React.FC<{ data: ContentData | null }> = ({ data }) => {
  // Can show empty state or load a specific test case
  return (
    <Box sx={{ flex: 1, display: 'flex', width: '100%', height: '100%' }}>
      <TestCaseFlowViewer
        testcaseId={data?.testcase_id}
        readOnly={!data?.editable}
      />
    </Box>
  );
};

// Campaign Flow Content - Uses real CampaignFlowViewer component
const CampaignFlowContent: React.FC<{ data: ContentData | null; selectedUserInterface?: string }> = ({ data, selectedUserInterface }) => {
  // Can show empty state or load a specific campaign
  return (
    <Box sx={{ flex: 1, display: 'flex', width: '100%', height: '100%' }}>
      <CampaignFlowViewer
        campaignId={data?.campaign_id}
        readOnly={true}
        selectedUserInterface={selectedUserInterface}
      />
    </Box>
  );
};

// Heatmap Content - Uses real HeatmapViewer component
const HeatmapContent: React.FC<{ data: ContentData | null }> = () => {
  // Heatmap viewer doesn't need specific data - it shows the current heatmap
  return (
    <Box sx={{ flex: 1, display: 'flex', width: '100%', height: '100%' }}>
      <HeatmapViewer />
    </Box>
  );
};

// Alerts Content - Uses real AlertsViewer component
const AlertsContent: React.FC<{ data: ContentData | null }> = () => {
  // Alerts viewer doesn't need specific data - it shows current active alerts
  return (
    <Box sx={{ flex: 1, display: 'flex', width: '100%', height: '100%' }}>
      <AlertsViewer />
    </Box>
  );
};

// REC Preview Content - Uses DeviceStreamGrid for actual stream display
const RecPreviewContent: React.FC<{ data: ContentData | null, allHosts: any[], getDevicesFromHost: (hostName: string) => any[] }> = ({ data, allHosts, getDevicesFromHost }) => {
  // Convert device_ids to DeviceStreamGrid format
  const devices = (data?.device_ids || []).map(deviceId => {
    const [hostName, deviceId_part] = deviceId.split(':');
    return { hostName, deviceId: deviceId_part };
  });

  if (devices.length === 0) {
    return (
      <Box sx={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'column',
        gap: 2,
        p: 4,
        bgcolor: '#000',
      }}>
        <StreamIcon sx={{ fontSize: 64, color: 'grey.600', opacity: 0.3 }} />
        <Typography variant="body1" color="grey.500">
          No devices specified
        </Typography>
        <Typography variant="caption" color="grey.600" sx={{ maxWidth: 400, textAlign: 'center' }}>
          Provide device_ids in content_data to display streams
        </Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ flex: 1, display: 'flex', width: '100%', height: '100%', p: 2, overflow: 'auto' }}>
      <DeviceStreamGrid
        devices={devices}
        allHosts={allHosts}
        getDevicesFromHost={getDevicesFromHost}
        maxColumns={3}
        isActive={true}
      />
    </Box>
  );
};

// Report Chart Content (placeholder - will integrate charting library)
const ReportChartContent: React.FC<{ data: ContentData | null }> = ({ data }) => {
  return (
    <Box sx={{ 
      flex: 1, 
      display: 'flex', 
      alignItems: 'center', 
      justifyContent: 'center',
      flexDirection: 'column',
      gap: 2,
      p: 4,
    }}>
      <ChartIcon sx={{ fontSize: 64, color: 'text.disabled', opacity: 0.3 }} />
      <Typography variant="body1" color="text.secondary">
        Report Chart Viewer
      </Typography>
      {data?.chart_type && (
        <Chip label={`Type: ${data.chart_type}`} size="small" variant="outlined" />
      )}
      <Typography variant="caption" color="text.disabled" sx={{ mt: 2, maxWidth: 400, textAlign: 'center' }}>
        Chart integration coming soon. This will display test results and metrics.
      </Typography>
    </Box>
  );
};

// Data Table Content (placeholder - will integrate DataGrid)
const DataTableContent: React.FC<{ data: ContentData | null }> = ({ data }) => {
  const theme = useTheme();
  const isDarkMode = theme.palette.mode === 'dark';
  
  // Simple table rendering if data is provided
  if (data?.columns && data?.rows && data.rows.length > 0) {
    return (
      <Box sx={{ p: 2, overflow: 'auto' }}>
        <table style={{ 
          width: '100%', 
          borderCollapse: 'collapse',
          fontSize: '0.85rem',
        }}>
          <thead>
            <tr style={{ 
              borderBottom: `2px solid ${isDarkMode ? PALETTE.borderColor : '#e0e0e0'}`,
            }}>
              {data.columns.map((col, i) => (
                <th key={i} style={{ 
                  padding: '8px 12px', 
                  textAlign: 'left',
                  fontWeight: 600,
                  color: isDarkMode ? '#fff' : '#333',
                }}>
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, rowIndex) => (
              <tr 
                key={rowIndex}
                style={{ 
                  borderBottom: `1px solid ${isDarkMode ? PALETTE.borderColor : '#e0e0e0'}`,
                }}
              >
                {data.columns!.map((col, colIndex) => (
                  <td key={colIndex} style={{ 
                    padding: '8px 12px',
                    color: isDarkMode ? '#ccc' : '#666',
                  }}>
                    {row[col.field] ?? '-'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </Box>
    );
  }
  
  return (
    <Box sx={{ 
      flex: 1, 
      display: 'flex', 
      alignItems: 'center', 
      justifyContent: 'center',
      flexDirection: 'column',
      gap: 2,
      p: 4,
    }}>
      <TableIcon sx={{ fontSize: 64, color: 'text.disabled', opacity: 0.3 }} />
      <Typography variant="body1" color="text.secondary">
        Data Table Viewer
      </Typography>
      <Typography variant="caption" color="text.disabled">
        No data to display
      </Typography>
    </Box>
  );
};

// Execution Log Content
const ExecutionLogContent: React.FC<{ data: ContentData | null }> = ({ data }) => {
  const theme = useTheme();
  const isDarkMode = theme.palette.mode === 'dark';
  
  if (data?.log_entries && data.log_entries.length > 0) {
    return (
      <Box sx={{ 
        p: 1, 
        fontFamily: 'monospace', 
        fontSize: '0.75rem',
        overflow: 'auto',
        bgcolor: isDarkMode ? '#1a1a1a' : '#f5f5f5',
      }}>
        {data.log_entries.map((entry, i) => (
          <Box 
            key={i}
            sx={{ 
              py: 0.5,
              px: 1,
              display: 'flex',
              gap: 1,
              borderBottom: '1px solid',
              borderColor: isDarkMode ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)',
            }}
          >
            <Typography 
              component="span" 
              sx={{ 
                color: 'text.disabled',
                fontSize: 'inherit',
                fontFamily: 'inherit',
                minWidth: 80,
              }}
            >
              {entry.timestamp}
            </Typography>
            <Typography 
              component="span" 
              sx={{ 
                color: entry.level === 'error' ? 'error.main' 
                  : entry.level === 'warn' ? 'warning.main' 
                  : entry.level === 'success' ? 'success.main'
                  : 'text.secondary',
                fontSize: 'inherit',
                fontFamily: 'inherit',
                minWidth: 50,
                textTransform: 'uppercase',
              }}
            >
              [{entry.level}]
            </Typography>
            <Typography 
              component="span" 
              sx={{ 
                color: isDarkMode ? '#e0e0e0' : '#333',
                fontSize: 'inherit',
                fontFamily: 'inherit',
                flex: 1,
              }}
            >
              {entry.message}
            </Typography>
          </Box>
        ))}
      </Box>
    );
  }
  
  return (
    <Box sx={{ 
      flex: 1, 
      display: 'flex', 
      alignItems: 'center', 
      justifyContent: 'center',
      flexDirection: 'column',
      gap: 2,
      p: 4,
    }}>
      <TableIcon sx={{ fontSize: 64, color: 'text.disabled', opacity: 0.3 }} />
      <Typography variant="body1" color="text.secondary">
        Execution Log
      </Typography>
      <Typography variant="caption" color="text.disabled">
        No log entries
      </Typography>
    </Box>
  );
};

export default ContentViewer;

