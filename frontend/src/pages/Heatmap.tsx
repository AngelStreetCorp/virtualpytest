import { GridView, SkipNext } from '@mui/icons-material';
import {
  Box,
  Typography,
  Button,
  Card,
  CardContent,
  Alert as MuiAlert,
  MenuItem,
  Select,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { PageTitle, StatTiles, goldButtonSx, pageSurfaceSx, segmentedSx } from '../components/common/PageChrome';
import React, { useState, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';

import { HeatMapAnalysisSection } from '../components/heatmap/HeatMapAnalysisSection';
import { HeatMapHistory, HeatMapHistoryRef } from '../components/heatmap/HeatMapHistory';
import { MosaicPlayer } from '../components/MosaicPlayer';
import { RecHostStreamModal } from '../components/rec/RecHostStreamModal';
import { HostManagerProvider } from '../contexts/HostManagerProvider';
import { DeviceDataProvider } from '../contexts/device/DeviceDataContext';
import { useResponsiveMode } from '../hooks/useResponsiveMode';
import { useHeatmap } from '../hooks/useHeatmap';
import { useHostData } from '../hooks/useHostManager';
import { useServerManager } from '../hooks/useServerManager';
import { isAllServersSentinel } from '../lib/allServer/scope';
import { Host, Device } from '../types/common/Host_Types';

interface HeatmapContentProps {
  serverUrl?: string; // defaults to the picked server
  serverPicker?: React.ReactNode; // the server dropdown, in "All servers" mode
}

const HeatmapContent: React.FC<HeatmapContentProps> = ({ serverUrl, serverPicker }) => {
  const P = useAgentChatPalette();
  const { isMobile, isTablet } = useResponsiveMode();
  const historyRef = useRef<HeatMapHistoryRef>(null);
  const {
    timeline,
    currentIndex,
    setCurrentIndex,
    analysisData,
    loadedItem,
    hasIncidents,
    hasDiscards,
    goToLatest,
    hasDataError,
    generateReport,
    getMosaicUrl,
    getFilteredDevices,
    isWorkspaceMode
  } = useHeatmap({ serverUrl });

  // Access to real host/device data
  const { getHostByName, getDevicesFromHost } = useHostData();

  // UI state
  const [error, setError] = useState<string | null>(null);
  const [analysisExpanded, setAnalysisExpanded] = useState(!(isMobile || isTablet));
  const [isGeneratingReport, setIsGeneratingReport] = useState(false);
  const [selectedFilter, setSelectedFilter] = useState<'ALL' | 'OK' | 'KO'>('ALL');
  // A workspace has no OK/KO mosaics (only ALL), so the filter is forced to ALL there
  const filter = isWorkspaceMode ? 'ALL' : selectedFilter;
  
  // Stream modal state
  const [streamModalOpen, setStreamModalOpen] = useState(false);
  const [streamModalHost, setStreamModalHost] = useState<Host | null>(null);
  const [streamModalDevice, setStreamModalDevice] = useState<Device | null>(null);
  // The loader can fall back a few minutes, so the header names the frame on screen.
  const displayedItem = loadedItem || (hasDataError ? null : timeline[currentIndex]);
  const [searchParams] = useSearchParams();
  const hostParam = searchParams.get('host');
  const deviceParam = searchParams.get('device');
  const filteredDevices = getFilteredDevices(analysisData?.devices || [], filter).filter(
    (d: any) => (!hostParam || d.host_name === hostParam) && (!deviceParam || d.device_id === deviceParam),
  );
  const allDevices: any[] = analysisData?.devices || [];
  const activeDevices = allDevices.filter((d: any) => d.image_url).length;
  const missingDevices = allDevices.length - activeDevices;
  const hasAnalysisRows = filteredDevices.some((device: any) => device.analysis_json && typeof device.analysis_json === 'object');

  // Handle overlay click to open stream modal
  const handleOverlayClick = (deviceData: any) => {
    console.log('[@Heatmap] Opening stream modal for device:', deviceData);
    
    // Get real host and device data from HostManagerProvider
    const realHost = getHostByName(deviceData.host_name);
    
    if (!realHost) {
      console.error('[@Heatmap] Host not found:', deviceData.host_name);
      setError(`Host "${deviceData.host_name}" not found`);
      return;
    }
    
    // Look for the specific device in the host's devices
    const hostDevices = getDevicesFromHost(deviceData.host_name);
    const realDevice = hostDevices.find(d => d.device_id === deviceData.device_id);
    
    if (!realDevice) {
      console.error('[@Heatmap] Device not found:', deviceData.device_id, 'in host:', deviceData.host_name);
      setError(`Device "${deviceData.device_id}" not found in host "${deviceData.host_name}"`);
      return;
    }
    
    console.log('[@Heatmap] Found real host:', realHost);
    console.log('[@Heatmap] Found real device:', realDevice);
    
    // Use real data
    setStreamModalHost(realHost);
    setStreamModalDevice(realDevice);
    setStreamModalOpen(true);
  };


  // Generate report for current frame
  const handleGenerateReport = async () => {
    if (!timeline[currentIndex] || !analysisData || isGeneratingReport) return;
    
    setIsGeneratingReport(true);
    try {
      await generateReport();
      console.log('HTML report generated for frame:', timeline[currentIndex].timeKey);
      
      // Refresh history to show the new report
      if (historyRef.current) {
        await historyRef.current.refreshReports();
      }
    } catch (error) {
      console.error('Error generating report:', error);
      setError('Failed to generate report');
    } finally {
      setIsGeneratingReport(false);
    }
  };

  return (
    <Box sx={pageSurfaceSx(P)}>
      {error && (
        <MuiAlert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>
          {error}
        </MuiAlert>
      )}

      {/* Missing frame notice. Files are keyed by HHMM in a 24h circular buffer, so a
          minute the processor skipped still holds the previous day's frame; the hook
          rejects it rather than passing yesterday's mosaic off as this minute's. */}
      {hasDataError && (
        <MuiAlert severity="warning" sx={{ mb: 1 }}>
          No heatmap was generated for{' '}
          {timeline[currentIndex]
            ? timeline[currentIndex].displayTime.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })
            : 'this minute'}
          . Check the Heatmap service on the Dashboard if this covers more than a minute or two.
        </MuiAlert>
      )}

      {/* Header: title + filter + actions, then stat tiles */}
      <PageTitle
        title="24h Heatmap"
        subtitle={
          displayedItem
            ? `One frame per minute for the last 24 hours · showing ${displayedItem.isToday ? 'Today' : 'Yesterday'} ${displayedItem.displayTime.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })}`
            : 'One frame per minute for the last 24 hours'
        }
        right={
          <>
            {serverPicker}
            {!isWorkspaceMode && (
              <ToggleButtonGroup
                size="small"
                exclusive
                value={filter}
                onChange={(_e, v) => v && setSelectedFilter(v as 'ALL' | 'OK' | 'KO')}
                sx={segmentedSx(P, 'sm')}
              >
                <ToggleButton value="ALL">All</ToggleButton>
                <ToggleButton value="OK">OK</ToggleButton>
                <ToggleButton value="KO">KO</ToggleButton>
              </ToggleButtonGroup>
            )}
            <Button variant="outlined" size="small" startIcon={<SkipNext />} onClick={goToLatest} sx={{ whiteSpace: 'nowrap', flexShrink: 0 }}>
              Latest
            </Button>
            <Button
              variant="contained"
              size="small"
              startIcon={<GridView />}
              onClick={handleGenerateReport}
              disabled={isGeneratingReport || !analysisData || !timeline[currentIndex]}
              sx={{ ...goldButtonSx(P), whiteSpace: 'nowrap', flexShrink: 0 }}
            >
              Generate report
            </Button>
          </>
        }
      />
      <StatTiles
        tiles={[
          { label: 'Devices', value: allDevices.length || analysisData?.hosts_count || 0 },
          { label: 'Active', value: activeDevices, color: P.success },
          { label: 'Missing', value: missingDevices, color: missingDevices ? P.warning : undefined },
          {
            label: 'Incidents',
            value: analysisData?.incidents_count || 0,
            color: analysisData?.incidents_count ? P.error : P.success,
            onClick: isWorkspaceMode || !hasIncidents() ? undefined : () => setSelectedFilter(filter === 'KO' ? 'ALL' : 'KO'),
            active: filter === 'KO',
            title: isWorkspaceMode ? undefined : filter === 'KO' ? 'Show all devices' : 'Show only KO devices',
          },
        ]}
      />

      {/* Mosaic Player */}
      <Box sx={{ mb: 3 }}>
        <MosaicPlayer
          timeline={timeline}
          currentIndex={currentIndex}
          onIndexChange={setCurrentIndex}
          onCellClick={handleOverlayClick}
          hasIncidents={hasIncidents()}
          hasDiscards={hasDiscards}
          hasDataError={hasDataError}
          displayItem={loadedItem}
          analysisData={analysisData}
          filter={filter}
          getMosaicUrl={getMosaicUrl}
          isCompactLayout={isMobile || isTablet}
        />
      </Box>

      {/* Analysis + History sections are dense, desktop-oriented panels — hidden on
          mobile for now rather than squeezed in, until they get a mobile design. */}
      {!isMobile && (
        <>
          {hasAnalysisRows ? (
            <Box sx={{ mb: 3 }}>
              <HeatMapAnalysisSection
                images={filteredDevices}
                analysisExpanded={analysisExpanded}
                onToggleExpanded={() => setAnalysisExpanded(!analysisExpanded)}
                frameTimestamp={analysisData?.timestamp || timeline[currentIndex]?.displayTime?.toISOString()}
              />
            </Box>
          ) : (
            <Card sx={{ mb: 3 }}>
              <CardContent sx={{ py: 1.5 }}>
                <Typography variant="body2" color="text.secondary">
                  No device analysis available for this frame.
                </Typography>
              </CardContent>
            </Card>
          )}

          {/* History Section */}
          <HeatMapHistory ref={historyRef} serverUrl={serverUrl} />
        </>
      )}

      {/* Freeze Modal */}
      {/* Freeze modal removed (freeze click disabled) */}

      {/* Stream Modal */}
      {streamModalHost && streamModalDevice && (
        <RecHostStreamModal
          host={streamModalHost}
          device={streamModalDevice}
          isOpen={streamModalOpen}
          onClose={() => {
            setStreamModalOpen(false);
            setStreamModalHost(null);
            setStreamModalDevice(null);
          }}
          showRemoteByDefault={false}
        />
      )}
    </Box>
  );
};

const HEATMAP_SERVER_KEY = 'virtualpytest:heatmap-all-servers-pick';

const readPickedServer = (): string | null => {
  try {
    return localStorage.getItem(HEATMAP_SERVER_KEY);
  } catch {
    return null;
  }
};

const writePickedServer = (serverUrl: string) => {
  try {
    localStorage.setItem(HEATMAP_SERVER_KEY, serverUrl);
  } catch {
    /* storage unavailable */
  }
};

// "All servers" mode: every server writes its own mosaic, so the page shows one server's heatmap
// at a time and a dropdown in the header picks which.
const AllServersHeatmapContent: React.FC = () => {
  const P = useAgentChatPalette();
  const { availableServers, serverHostsData } = useServerManager();
  const [picked, setPicked] = useState<string>(() => readPickedServer() || '');
  const serverUrl = availableServers.includes(picked) ? picked : availableServers[0] || '';

  const serverLabel = (url: string) => {
    const name = serverHostsData.find(sd => sd.server_info.server_url === url)?.server_info.server_name;
    if (name) return name;
    try {
      return new URL(url).host;
    } catch {
      return url;
    }
  };

  if (!serverUrl) {
    return (
      <Box sx={pageSurfaceSx(P)}>
        <Typography variant="body2" color="text.secondary">
          No servers configured.
        </Typography>
      </Box>
    );
  }

  const picker = (
    <Select
      size="small"
      value={serverUrl}
      onChange={e => {
        setPicked(e.target.value);
        writePickedServer(e.target.value);
      }}
      inputProps={{ 'aria-label': 'Server' }}
      sx={{ minWidth: 180, flexShrink: 0 }}
    >
      {availableServers.map(url => (
        <MenuItem key={url} value={url}>
          {serverLabel(url)}
        </MenuItem>
      ))}
    </Select>
  );

  // key: a new server is a new timeline, never the previous server's frame
  return <HeatmapContent key={serverUrl} serverUrl={serverUrl} serverPicker={picker} />;
};

const HeatmapScope: React.FC = () => {
  const { selectedServer } = useHostData();
  return isAllServersSentinel(selectedServer || '') ? <AllServersHeatmapContent /> : <HeatmapContent />;
};

const Heatmap: React.FC = () => {
  return (
    <HostManagerProvider>
      <DeviceDataProvider>
        <HeatmapScope />
      </DeviceDataProvider>
    </HostManagerProvider>
  );
};

export default Heatmap;
