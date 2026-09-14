/**
 * Heatmap Timeline Hook
 * 
 * Manages 24h circular buffer timeline for heatmap display.
 * Uses predictable HHMM file naming to generate timeline without API calls.
 */

import { useState, useEffect } from 'react';
import { useHostData } from './useHostManager';
import { buildServerUrl, buildServerUrlForServer } from '../utils/buildUrlUtils';
import { api } from '../utils/apiClient';
import { getR2Url, openR2Url } from '../utils/infrastructure/cloudflareUtils';

export interface TimelineItem {
  timeKey: string;        // "1425" (2:25 PM)
  displayTime: Date;      // Full date for display
  isToday: boolean;       // Whether this time is from today
  mosaicUrl: string;      // Direct R2 URL to mosaic image
  mosaicOkUrl: string;    // Direct R2 URL to OK-only mosaic
  mosaicKoUrl: string;    // Direct R2 URL to KO-only mosaic
  analysisUrl: string;    // Direct R2 URL to analysis JSON
}

export interface AnalysisData {
  time_key: string;
  timestamp: string;
  devices: Array<{
    host_name: string;
    device_id: string;
    image_url: string;
    analysis_json: {
      audio?: boolean;
      blackscreen?: boolean;
      freeze?: boolean;
      volume_percentage?: number;
      mean_volume_db?: number;
      freeze_diffs?: number[];
      last_3_thumbnails?: string[];  // Local paths (deprecated, use r2_images)
      r2_images?: {
        original_urls: string[];
        thumbnail_urls: string[];
        original_r2_paths: string[];
        thumbnail_r2_paths: string[];
        timestamp: string;
      };
    };
  }>;
  incidents_count: number;
  hosts_count: number;
}

export const useHeatmap = () => {
  const { selectedServer } = useHostData();
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(1438); // Start at current-1 minute
  const [analysisData, setAnalysisData] = useState<AnalysisData | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [hasDataError, setHasDataError] = useState(false);
  const [corsBlocked, setCorsBlocked] = useState(false);
  const [retryAttempts, setRetryAttempts] = useState(0);
  const [lastSuccessfulIndex, setLastSuccessfulIndex] = useState<number | null>(null);
  const [serverName, setServerName] = useState<string>('default'); // Server name from backend
  
  // Get storage base URL from environment (Cloudflare R2 or MinIO)
  const R2_BASE_URL = (import.meta as any).env?.VITE_CLOUDFLARE_R2_PUBLIC_URL ||
                      (import.meta as any).env?.VITE_MINIO_PUBLIC_URL || '';
  
  /**
   * Fetch server name from backend
   */
  const fetchServerName = async (): Promise<string> => {
    try {
      const data = await api.get<{ server_info?: { server_name?: string } }>(
        buildServerUrlForServer(selectedServer, '/server/system/getAllHosts?include_system_stats=false')
      );
      const name = data?.server_info?.server_name || 'default';
      console.log(`[@useHeatmap] Fetched SERVER_NAME from backend: ${name}`);
      return name;
    } catch (error) {
      console.warn(`[@useHeatmap] Failed to fetch server name, using 'default':`, error);
    }
    return 'default';
  };
  
  
  /**
   * Generate 24-hour timeline with predictable file names
   * Uses UTC time to match backend heatmap processor
   */
  const generateTimeline = (serverPath: string): TimelineItem[] => {
    if (!selectedServer || !serverPath) return [];
    
    // Use UTC time to match backend
    const now = new Date();
    const items: TimelineItem[] = [];
    
    // Use server name directly (no URL conversion)
    console.log(`[@useHeatmap] Generating timeline for server: ${serverPath} (UTC time)`);
    
    // Construct base URL - ensure no double slashes
    // If R2_BASE_URL is empty (private mode), paths will be like "heatmaps/..." for signed URL requests
    // If R2_BASE_URL is set (public mode), paths will be like "https://r2.dev/heatmaps/..."
    const baseUrl = R2_BASE_URL ? R2_BASE_URL.replace(/\/$/, '') : ''; // Remove trailing slash
    
    // Generate 1440 minutes (24 hours) using UTC time
    for (let i = 0; i < 1440; i++) {
      const time = new Date(now.getTime() - (i * 60000)); // Go back i minutes
      
      // CRITICAL: Use UTC hours/minutes to match backend
      const timeKey = `${time.getUTCHours().toString().padStart(2, '0')}${time.getUTCMinutes().toString().padStart(2, '0')}`;
      
      // Construct paths without leading slashes (for both public and private bucket modes)
      const heatmapPath = `heatmaps/${serverPath}/${timeKey}`;
      
      items.push({
        timeKey,
        displayTime: time,
        isToday: time.toDateString() === now.toDateString(),
        mosaicUrl: baseUrl ? `${baseUrl}/${heatmapPath}.jpg` : `${heatmapPath}.jpg`,
        mosaicOkUrl: baseUrl ? `${baseUrl}/${heatmapPath}_ok.jpg` : `${heatmapPath}_ok.jpg`,
        mosaicKoUrl: baseUrl ? `${baseUrl}/${heatmapPath}_ko.jpg` : `${heatmapPath}_ko.jpg`,
        analysisUrl: baseUrl ? `${baseUrl}/${heatmapPath}.json` : `${heatmapPath}.json`
      });
    }
    
    return items.reverse(); // Return oldest to newest for timeline scrubber
  };
  
  /**
   * Load analysis data with retry logic (max 10 attempts)
   * Includes CORS error detection to prevent cascade failures
   */
  const loadAnalysisData = async (item: TimelineItem, retryCount: number = 0) => {
    if (!item) return;
    
    setAnalysisLoading(true);
    try {
      // Resolve URL based on mode: direct when public, signed when private
      const analysisUrl = R2_BASE_URL
        ? item.analysisUrl
        : await getR2Url(item.analysisUrl);
      
      const response = await fetch(analysisUrl, {
        mode: 'cors',
        credentials: 'omit', // Don't send credentials to prevent CORS issues
        cache: 'no-cache' // Prevent caching of failed requests
      });
      
      if (response.ok) {
        const contentType = response.headers.get('content-type') || '';
        if (!contentType.includes('application/json')) {
          throw new Error(`Non-JSON response (content-type: ${contentType || 'unknown'})`);
        }

        const data = await response.json();
        console.log(`[useHeatmap] Successfully loaded analysis data for ${item.timeKey}:`, data);
        
        // Validate data freshness - check if timestamp is recent (within 24 hours)
        if (data.timestamp) {
          const dataTimestamp = new Date(data.timestamp);
          const now = new Date();
          const ageInHours = (now.getTime() - dataTimestamp.getTime()) / (1000 * 60 * 60);
          
          if (ageInHours > 24) {
            console.warn(`[@useHeatmap] ⚠️ STALE DATA: ${item.timeKey} is ${ageInHours.toFixed(1)}h old (timestamp: ${data.timestamp})`);
            setHasDataError(true); // Mark as error to show warning
          } else {
            console.log(`[@useHeatmap] ✓ Fresh data: ${item.timeKey} age: ${ageInHours.toFixed(1)}h`);
            setHasDataError(false);
          }
        }
        
        setAnalysisData(data);
        // Success - reset flags and track success
        setCorsBlocked(false);
        setRetryAttempts(0);
        setLastSuccessfulIndex(timeline.findIndex(t => t.timeKey === item.timeKey));
      } else if (response.status === 404 && retryCount < 10) {
        // File not generated yet, try previous minute
        const itemIndex = timeline.findIndex(t => t.timeKey === item.timeKey);
        const prevIndex = itemIndex - 1;
        if (prevIndex >= 0 && timeline[prevIndex]) {
          console.log(`File ${item.timeKey} not found, trying previous minute (attempt ${retryCount + 1})`);
          await loadAnalysisData(timeline[prevIndex], retryCount + 1);
          return;
        }
      }
      if (response.status === 404) {
        setAnalysisData(null); // Stop retrying after 10 attempts
        setHasDataError(true); // Mark as having data error
      }
    } catch (error: any) {
      // Detect CORS errors specifically
      const isCorsError = error.message?.includes('CORS') || 
                         error.message?.includes('Access-Control-Allow-Origin') ||
                         error.name === 'TypeError' && error.message?.includes('fetch');
      
      if (isCorsError) {
        console.warn(`CORS error detected for ${item.timeKey}. This may affect subsequent requests.`);
        setCorsBlocked(true);
        setRetryAttempts(prev => prev + 1);
        
        // Auto-fallback to last successful timeframe if available
        if (lastSuccessfulIndex !== null && retryAttempts < 3) {
          console.log(`Attempting fallback to last successful timeframe (index ${lastSuccessfulIndex})`);
          setTimeout(() => {
            if (timeline[lastSuccessfulIndex]) {
              loadAnalysisData(timeline[lastSuccessfulIndex], 0);
            }
          }, 1000 * Math.pow(2, retryAttempts)); // Exponential backoff
        } else {
          setAnalysisData(null);
          setHasDataError(true);
        }
      } else {
        console.log(`No analysis data available for ${item.timeKey}:`, error.message);
        setAnalysisData(null);
        setHasDataError(true);
      }
    } finally {
      setAnalysisLoading(false);
    }
  };
  
  /**
   * Initialize timeline on mount and when server changes
   */
  useEffect(() => {
    const initTimeline = async () => {
      // Fetch server name first
      const name = await fetchServerName();
      setServerName(name);
      
      // Generate timeline with server name (pass directly, don't read state)
      const newTimeline = generateTimeline(name);
      setTimeline(newTimeline);
      
      // Load analysis for initial item
      if (newTimeline[currentIndex]) {
        loadAnalysisData(newTimeline[currentIndex]);
      }
    };
    
    initTimeline();
  }, [selectedServer]);
  
  /**
   * Refresh timeline every minute to get latest data
   */
  useEffect(() => {
    const interval = setInterval(() => {
      if (document.visibilityState === 'hidden') {
        return;
      }
      // Use current serverName state for refresh
      const newTimeline = generateTimeline(serverName);
      setTimeline(newTimeline);
      
      // If we're at the latest position, stay there with new data
      if (currentIndex === 1438 && newTimeline[1438]) {
        loadAnalysisData(newTimeline[1438]);
      }
    }, 60000); // Refresh every minute
    
    return () => clearInterval(interval);
  }, [currentIndex, selectedServer, serverName]);
  
  /**
   * Load analysis when timeline position changes (but NOT when timeline regenerates)
   * Only trigger when currentIndex changes, to avoid duplicate loads
   */
  useEffect(() => {
    if (timeline.length > 0 && timeline[currentIndex]) {
      loadAnalysisData(timeline[currentIndex]);
    }
  }, [currentIndex]);
  
  /**
   * Force refresh analysis data
   */
  const refreshCurrentData = () => {
    if (timeline[currentIndex]) {
      setAnalysisData(null); // Clear current data first
      setHasDataError(false); // Reset error flag
      setCorsBlocked(false); // Reset CORS blocked flag
      loadAnalysisData(timeline[currentIndex]);
    }
  };

  /**
   * Recovery method for CORS cascade issues
   * Call this when CORS errors block subsequent requests
   */
  const recoverFromCorsBlock = () => {
    setCorsBlocked(false);
    setHasDataError(false);
    setAnalysisData(null);
    setRetryAttempts(0);
    
    // Try to find a working timeframe by going back in time
    const findWorkingTimeframe = async () => {
      for (let i = currentIndex - 1; i >= Math.max(0, currentIndex - 60); i--) {
        if (timeline[i]) {
          try {
            const response = await fetch(timeline[i].analysisUrl, {
              mode: 'cors',
              credentials: 'omit',
              cache: 'no-cache'
            });
            if (response.ok) {
              console.log(`Found working timeframe at index ${i} (${timeline[i].timeKey})`);
              setLastSuccessfulIndex(i);
              loadAnalysisData(timeline[i], 0);
              return;
            }
          } catch (error) {
            // Continue searching
            continue;
          }
        }
      }
      console.warn('No working timeframes found. Consider refreshing the page.');
    };
    
    if (corsBlocked) {
      console.warn('CORS cascade detected. Searching for working timeframes...');
      findWorkingTimeframe();
    }
  };
  
  /**
   * Navigate to specific time
   */
  const goToTime = (hours: number, minutes: number) => {
    const targetTimeKey = `${hours.toString().padStart(2, '0')}${minutes.toString().padStart(2, '0')}`;
    const targetIndex = timeline.findIndex(item => item.timeKey === targetTimeKey);
    if (targetIndex !== -1) {
      setCurrentIndex(targetIndex);
    }
  };
  
  /**
   * Navigate to latest available data (current-1 minute)
   */
  const goToLatest = () => {
    setCurrentIndex(1438); // Go to current-1 minute
    setRetryAttempts(0); // Reset retry count when manually navigating
  };

  /**
   * Smart navigation that avoids problematic timeframes
   */
  const navigateToIndex = (index: number) => {
    // If CORS is blocked and we have a last successful index, suggest alternative
    if (corsBlocked && lastSuccessfulIndex !== null && Math.abs(index - lastSuccessfulIndex) > 10) {
      console.warn(`CORS issues detected. Consider using timeframe near ${timeline[lastSuccessfulIndex]?.timeKey} instead.`);
    }
    
    setCurrentIndex(index);
    setRetryAttempts(0); // Reset retry count when manually navigating
  };
  
  /**
   * Check if current frame has incidents
   */
  const hasIncidents = (): boolean => {
    if (!analysisData) return false;
    return analysisData.incidents_count > 0;
  };

  /**
   * Get mosaic URL based on filter
   */
  const getMosaicUrl = (item: TimelineItem | null, filter: 'ALL' | 'OK' | 'KO'): string => {
    if (!item) return '';
    
    switch (filter) {
      case 'OK': return item.mosaicOkUrl;
      case 'KO': return item.mosaicKoUrl;
      default: return item.mosaicUrl;
    }
  };

  /**
   * Filter devices based on filter type
   */
  const getFilteredDevices = (devices: any[], filter: 'ALL' | 'OK' | 'KO') => {
    if (filter === 'ALL') return devices;
    
    return devices.filter(device => {
      const analysis = device.analysis_json || {};
      // audio === false is a real audio loss; audio undefined/null means the
      // device has no audio capability (e.g. host VNC capture) → not an incident.
      const hasIncident = analysis.blackscreen || analysis.freeze || analysis.audio === false;
      return filter === 'OK' ? !hasIncident : hasIncident;
    });
  };

  /**
   * Generate HTML report for current frame
   */
  const generateReport = async (): Promise<void> => {
    if (!timeline[currentIndex] || !analysisData) return;
    
    const currentItem = timeline[currentIndex];
    
    try {
      // Call backend to generate HTML report
      const result = await api.post<{ success?: boolean; html_url?: string; error?: string }>(
        buildServerUrl('/server/heatmap/generateReport'),
        {
          time_key: currentItem.timeKey,
          mosaic_url: currentItem.mosaicUrl,
          analysis_data: analysisData,
          analysis_url: currentItem.analysisUrl,
          include_timeline: true,
        }
      );
      
      if (result.success && result.html_url) {
        await openR2Url(result.html_url);
        console.log(`Generated HTML report for ${currentItem.timeKey}: ${result.html_url}`);
      } else {
        throw new Error(result.error || 'Failed to generate report');
      }
    } catch (error) {
      console.error('Error generating HTML report:', error);
      throw error;
    }
  };
  
  return {
    // Timeline data
    timeline,
    currentIndex,
    setCurrentIndex: navigateToIndex, // Use smart navigation
    currentItem: timeline[currentIndex] || null,
    
    // Analysis data
    analysisData,
    analysisLoading,
    hasDataError,
    corsBlocked,
    retryAttempts,
    lastSuccessfulIndex,
    
    // Navigation helpers
    goToTime,
    goToLatest,
    hasIncidents,
    refreshCurrentData,
    recoverFromCorsBlock,
    navigateToIndex,
    generateReport,
    getMosaicUrl,
    getFilteredDevices,
    
    // Timeline info
    totalMinutes: timeline.length,
    isAtLatest: currentIndex === 1438,
    
    // Recovery status
    canRecover: lastSuccessfulIndex !== null && corsBlocked
  };
};
