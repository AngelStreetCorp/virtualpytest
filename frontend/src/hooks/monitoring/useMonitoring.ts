import { useState, useEffect, useCallback, useRef } from 'react';

import {
  MonitoringAnalysis,
  SubtitleAnalysis,
  LanguageMenuAnalysis,
} from '../../types/pages/Monitoring_Types';

import { 
  buildServerUrl, 
  buildCaptureUrl, 
  buildMetadataChunkUrl 
} from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';

interface ErrorTrendData {
  blackscreenConsecutive: number;
  freezeConsecutive: number;
  audioLossConsecutive: number;
  macroblocksConsecutive: number;
  hasWarning: boolean;
  hasError: boolean;
}

interface AnalysisSnapshot {
  timestamp: string;
  analysis: MonitoringAnalysis | null;
  subtitleAnalysis?: SubtitleAnalysis | null;
  languageMenuAnalysis?: LanguageMenuAnalysis | null;
  aiDescription?: string | null;
}

interface UseMonitoringReturn {
  latestAnalysis: MonitoringAnalysis | null;
  latestSubtitleAnalysis: SubtitleAnalysis | null;
  latestLanguageMenuAnalysis: LanguageMenuAnalysis | null;
  latestAIDescription: string | null;
  errorTrendData: ErrorTrendData | null;
  isLoading: boolean;
  analysisTimestamp: string | null;
  requestAIAnalysisForFrame: (imageUrl: string, sequence: string) => void; // Fire-and-forget (non-blocking)
  isAIAnalyzing: boolean;
}

interface UseMonitoringProps {
  host: any; // Host object for API requests
  device: any; // Device object for API requests
  enabled: boolean; // Only poll when monitoring mode is active
  archiveMode?: boolean; // Archive mode (Last 24h)
  currentVideoTime?: number; // Video currentTime in seconds
}

export const useMonitoring = ({
  host,
  device,
  enabled,
  archiveMode = false,
  currentVideoTime,
}: UseMonitoringProps): UseMonitoringReturn => {
  // Store last 10 analysis snapshots for error trend tracking
  const [analysisHistory, setAnalysisHistory] = useState<AnalysisSnapshot[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [lastProcessedSequence, setLastProcessedSequence] = useState<string>('');
  // AI analysis disabled
  // const [isAIAnalyzing, setIsAIAnalyzing] = useState(false);
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const fetchTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isAudioSupported = device?.device_model !== 'host_vnc';
  
  // Use refs for values that should NOT trigger effect re-runs
  const isLoadingRef = useRef(isLoading);
  const lastProcessedSequenceRef = useRef(lastProcessedSequence);
  
  // Keep refs in sync
  isLoadingRef.current = isLoading;
  lastProcessedSequenceRef.current = lastProcessedSequence;

  // Helper: Parse JSON data to analysis objects
  const parseJsonData = useCallback((data: any): {
    analysis: MonitoringAnalysis | null;
    subtitleAnalysis: SubtitleAnalysis | null;
  } => {
    // DEBUG: Log zap data extraction
    if (data.zap_cache || data.zap) {
      console.log('[useMonitoring] Extracting zap data:', { 
        zap_cache: data.zap_cache, 
        zap: data.zap 
      });
    }
    
    const parsed: MonitoringAnalysis = {
      timestamp: data.timestamp || '',
      filename: data.filename || '',
      thumbnail: data.thumbnail || '',
      blackscreen: data.blackscreen ?? false,
      blackscreen_percentage: data.blackscreen_percentage ?? 0,
      freeze: data.freeze ?? false,
      freeze_diffs: data.freeze_diffs || [],
      last_3_filenames: data.last_3_filenames || [],
      last_3_thumbnails: data.last_3_thumbnails || [],
      audio: data.audio ?? false,
      volume_percentage: data.volume_percentage ?? 0,
      mean_volume_db: data.mean_volume_db ?? -100,
      macroblocks: data.macroblocks ?? false,
      quality_score: data.quality_score ?? 0,
      has_incidents: data.has_incidents ?? false,
      // Event duration metadata
      blackscreen_event_start: data.blackscreen_event_start,
      blackscreen_event_duration_ms: data.blackscreen_event_duration_ms,
      freeze_event_start: data.freeze_event_start,
      freeze_event_duration_ms: data.freeze_event_duration_ms,
      audio_event_start: data.audio_event_start,
      audio_event_duration_ms: data.audio_event_duration_ms,
      macroblocks_event_start: data.macroblocks_event_start,
      macroblocks_event_duration_ms: data.macroblocks_event_duration_ms,
      // Action metadata
      last_action_executed: data.last_action_executed,
      last_action_timestamp: data.last_action_timestamp,
      action_params: data.action_params,
      // Screen identification (Localize) - only present when enabled for the device
      localize: data.localize,
      // Motion classification (live / carousel / pip / static) - only present when classified
      motion: data.motion,
      // NEW: Nested zapping structures (primary data source)
      zap: data.zap,
      zap_cache: data.zap_cache,
      // @deprecated Old flat zapping fields (kept for backward compatibility)
      zapping_detected: data.zapping_detected,
      zapping_id: data.zapping_id,
      zapping_channel_name: data.zapping_channel_name,
      zapping_channel_number: data.zapping_channel_number,
      zapping_program_name: data.zapping_program_name,
      zapping_program_start_time: data.zapping_program_start_time,
      zapping_program_end_time: data.zapping_program_end_time,
      zapping_confidence: data.zapping_confidence,
      zapping_blackscreen_duration_ms: data.zapping_blackscreen_duration_ms,
      zapping_audio_silence_duration: data.zapping_audio_silence_duration,
      zapping_detection_type: data.zapping_detection_type,
      zapping_detected_at: data.zapping_detected_at,
    };
    
    // Extract subtitle data from metadata
    let subtitleAnalysis: SubtitleAnalysis | null = null;
    if (data.subtitle_analysis?.has_subtitles) {
      const sub = data.subtitle_analysis;
      subtitleAnalysis = {
        subtitles_detected: sub.has_subtitles,
        combined_extracted_text: sub.extracted_text || '',
        detected_language: sub.detected_language !== 'unknown' ? sub.detected_language : undefined,
        confidence: sub.confidence || 0.9,
        detection_message: sub.extracted_text ? `Detected: ${sub.extracted_text}` : 'Subtitles detected',
      };
    }
    
    return { analysis: parsed, subtitleAnalysis };
  }, []);

  // AI analysis disabled - all AI functionality commented out
  // const analyzeFrameAIAsync = useCallback(async (imageUrl: string, sequence: string): Promise<{
  //   subtitleAnalysis: SubtitleAnalysis | null;
  //   languageMenuAnalysis: LanguageMenuAnalysis | null;
  //   aiDescription: string | null;
  // }> => {
  //   console.log('[useMonitoring] 🤖 Background AI analysis for sequence:', sequence);
  //   const combinedResult = await fetch(buildServerUrl('/server/verification/video/analyzeImageComplete'), {
  //     method: 'POST',
  //     headers: { 'Content-Type': 'application/json' },
  //     body: JSON.stringify({
  //       host_name: host.host_name,
  //       device_id: device?.device_id,
  //       image_source_url: imageUrl,
  //       extract_text: true,
  //       include_description: true,
  //     }),
  //   }).then(r => r.ok ? r.json() : null).catch(() => null);
  //   let subtitleAnalysis: SubtitleAnalysis | null = null;
  //   let languageMenuAnalysis: LanguageMenuAnalysis | null = null;
  //   let aiDescription: string | null = null;
  //   if (combinedResult?.success && combinedResult.subtitle_analysis) {
  //     const data = combinedResult.subtitle_analysis;
  //     subtitleAnalysis = {
  //       subtitles_detected: data.subtitles_detected || false,
  //       combined_extracted_text: data.combined_extracted_text || '',
  //       detected_language: data.detected_language !== 'unknown' ? data.detected_language : undefined,
  //       confidence: data.confidence || (data.subtitles_detected ? 0.9 : 0.1),
  //       detection_message: data.detection_message || '',
  //     };
  //   }
  //   if (combinedResult?.success && combinedResult.description_analysis?.success) {
  //     aiDescription = combinedResult.description_analysis.response;
  //   }
  //   console.log(`[useMonitoring] ✅ Background AI completed for sequence:`, sequence);
  //   return { subtitleAnalysis, languageMenuAnalysis, aiDescription };
  // }, [host, device?.device_id]);

  // AI analysis disabled - no-op function
  const requestAIAnalysisForFrame = useCallback((_imageUrl: string, _sequence: string) => {
    console.log('[useMonitoring] AI analysis is disabled');
    // No-op
  }, []);

  // Fetch latest JSON content directly (no second HTTP request!)
  const fetchLatestMonitoringData = useCallback(async (): Promise<{
    jsonData: any;
    imageUrl: string;
    timestamp: string;
    sequence: string;
  } | null> => {
    try {
      const result = await api.post<{ success?: boolean; json_data?: any; filename?: string; timestamp?: string }>(
        buildServerUrl('/server/monitoring/latest-json'),
        {
          host_name: host.host_name,
          device_id: device?.device_id || 'device1',
        }
      );
      if (result.success && result.json_data && result.filename) {
        const sequenceMatch = result.filename.match(/capture_(\d+)/);
        const sequence = sequenceMatch ? sequenceMatch[1] : '';
        const imageUrl = buildCaptureUrl(host, sequence, device?.device_id);
        const timestamp = result.timestamp || new Date().toISOString();
        return { jsonData: result.json_data, imageUrl, sequence, timestamp };
      }
      return null;
    } catch (error) {
      console.error('[useMonitoring] Failed to fetch latest JSON:', error);
      return null;
    }
  }, [host, device?.device_id]);

  // Cache for metadata chunks (avoid re-fetching same 10min window)
  const chunkCacheRef = useRef<Map<string, any>>(new Map());
  
  // Fetch archive data by directly fetching chunk file (no backend endpoint!)
  const fetchArchiveData = useCallback(async (timestampSeconds: number) => {
    try {
      // Calculate chunk location from global timestamp (REUSE archive player logic!)
      // timestampSeconds is globalCurrentTime from useArchivePlayer (hour * 3600 + chunk_index * 600 + video.currentTime)
      const hour = Math.floor(timestampSeconds / 3600) % 24;  // Extract hour from global time
      const chunkIndex = Math.floor((timestampSeconds % 3600) / 600);  // Extract 10min chunk (0-5)
      const cacheKey = `${device?.device_id}_${hour}_${chunkIndex}`;
      
      console.log(`[useMonitoring] Archive lookup: ${timestampSeconds}s -> hour ${hour}, chunk ${chunkIndex}`);
      
      // Check cache first
      let chunkData = chunkCacheRef.current.get(cacheKey);
      
      if (!chunkData) {
        // Fetch chunk directly from host (no backend!)
        const chunkUrl = buildMetadataChunkUrl(host, device?.device_id || 'device1', hour, chunkIndex);
        console.log(`[useMonitoring] Fetching chunk directly: ${chunkUrl}`);
        
        const response = await fetch(chunkUrl);
        if (response.ok) {
          chunkData = await response.json();
          // Cache chunk for future requests in same 10min window
          chunkCacheRef.current.set(cacheKey, chunkData);
          console.log(`[useMonitoring] Chunk loaded: ${chunkData.frames?.length || 0} frames`);
        } else {
          console.warn(`[useMonitoring] Chunk not found: ${hour}/chunk_10min_${chunkIndex}.json`);
          return;
        }
      }
      
      // Find nearest frame in chunk by timestamp (1fps = one frame per second)
      if (chunkData?.frames && Array.isArray(chunkData.frames)) {
        // Round video time to nearest second since frames are 1fps
        const targetSecond = Math.round(timestampSeconds);
        let nearestFrame = null;
        let minDiff = Infinity;
        
        for (const frame of chunkData.frames) {
          if (!frame.timestamp) continue;
          
          const frameDate = new Date(frame.timestamp);
          const frameSeconds = frameDate.getHours() * 3600 
            + frameDate.getMinutes() * 60 
            + frameDate.getSeconds();
          const diff = Math.abs(frameSeconds - targetSecond);
          
          if (diff < minDiff) {
            minDiff = diff;
            nearestFrame = frame;
          }
        }
        
        if (nearestFrame) {
          console.log(`[useMonitoring] Nearest frame found:`, {
            timestamp: nearestFrame.timestamp,
            filename: nearestFrame.filename,
            blackscreen: nearestFrame.blackscreen,
            freeze: nearestFrame.freeze,
            audio: nearestFrame.audio
          });
          
          const parsedAnalysis: MonitoringAnalysis = {
            timestamp: nearestFrame.timestamp || new Date().toISOString(),
            filename: nearestFrame.filename || '',
            thumbnail: '',
            blackscreen: nearestFrame.blackscreen ?? false,
            blackscreen_percentage: nearestFrame.blackscreen_percentage ?? 0,
            freeze: nearestFrame.freeze ?? false,
            freeze_diffs: nearestFrame.freeze_diffs || [],
            last_3_filenames: [],
            last_3_thumbnails: [],
            audio: nearestFrame.audio ?? false,
            volume_percentage: nearestFrame.volume_percentage ?? 0,
            mean_volume_db: nearestFrame.mean_volume_db ?? -100,
            macroblocks: false,
            quality_score: 0,
            has_incidents: false,
            // Event duration metadata (from chunk JSON)
            blackscreen_event_start: nearestFrame.blackscreen_event_start,
            blackscreen_event_duration_ms: nearestFrame.blackscreen_event_duration_ms,
            freeze_event_start: nearestFrame.freeze_event_start,
            freeze_event_duration_ms: nearestFrame.freeze_event_duration_ms,
            audio_event_start: nearestFrame.audio_event_start,
            audio_event_duration_ms: nearestFrame.audio_event_duration_ms,
            macroblocks_event_start: nearestFrame.macroblocks_event_start,
            macroblocks_event_duration_ms: nearestFrame.macroblocks_event_duration_ms,
            // Action metadata (from chunk JSON)
            last_action_executed: nearestFrame.last_action_executed,
            last_action_timestamp: nearestFrame.last_action_timestamp,
            action_params: nearestFrame.action_params,
            // Zapping detection (nested structures)
            zap: nearestFrame.zap,
            zap_cache: nearestFrame.zap_cache,
          };
          
          const snapshot: AnalysisSnapshot = {
            timestamp: parsedAnalysis.timestamp,
            analysis: parsedAnalysis,
            subtitleAnalysis: null,
            languageMenuAnalysis: null,
            aiDescription: null,
          };
          setAnalysisHistory([snapshot]);
          if (isLoadingRef.current) setIsLoading(false);
          console.log(`[useMonitoring] Archive analysis updated for ${nearestFrame.timestamp}`);
        } else {
          console.warn(`[useMonitoring] No frames found in chunk`);
        }
      } else {
        console.warn(`[useMonitoring] Invalid chunk data structure:`, chunkData);
      }
    } catch (error) {
      console.error('[useMonitoring] Archive fetch error:', error);
    }
  }, [host, device?.device_id]);

  // Poll live data OR fetch archive data based on mode
  useEffect(() => {
    // Monitoring is disabled in archive mode (archive = pure playback, no monitoring)
    if (!enabled || archiveMode) {
      setAnalysisHistory([]);
      setIsLoading(true);
      setLastProcessedSequence('');
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
      if (fetchTimeoutRef.current) {
        clearTimeout(fetchTimeoutRef.current);
        fetchTimeoutRef.current = null;
      }
      return;
    }

    // Live mode only: 500ms polling
    let isMounted = true;
    
    const pollLatestData = async () => {
      if (document.visibilityState === 'hidden') {
        return;
      }
      try {
        const latestData = await fetchLatestMonitoringData();
        if (!isMounted || !latestData) return;
        if (latestData.sequence === lastProcessedSequenceRef.current) return;

        const { analysis, subtitleAnalysis } = parseJsonData(latestData.jsonData);
        if (!analysis) return;

        const snapshot: AnalysisSnapshot = {
          timestamp: latestData.timestamp,
          analysis,
          subtitleAnalysis,
          languageMenuAnalysis: null,
          aiDescription: null,
        };

        setAnalysisHistory(prev => [...prev, snapshot].slice(-10));
        setLastProcessedSequence(latestData.sequence);
        if (isLoadingRef.current) setIsLoading(false);

        // AI analysis disabled - no background AI calls
        // analyzeFrameAIAsync(latestData.imageUrl, latestData.sequence).then(aiResults => {
        //   if (!isMounted) return;
        //   setAnalysisHistory(prev => 
        //     prev.map(s => 
        //       s.timestamp === latestData.timestamp 
        //         ? { 
        //             ...s, 
        //             subtitleAnalysis: aiResults.subtitleAnalysis || s.subtitleAnalysis,
        //             languageMenuAnalysis: aiResults.languageMenuAnalysis,
        //             aiDescription: aiResults.aiDescription,
        //           }
        //         : s
        //     )
        //   );
        // }).catch(error => {
        //   console.warn('[useMonitoring] Background AI failed:', error);
        // });
      } catch (error) {
        console.error('[useMonitoring] Polling error:', error);
      }
    };

    pollLatestData();
    pollingIntervalRef.current = setInterval(pollLatestData, 500);

    return () => {
      isMounted = false;
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
    };
  }, [enabled, archiveMode, currentVideoTime, fetchLatestMonitoringData, parseJsonData, fetchArchiveData]);

  // Compute error trend data from analysis history
  const computeErrorTrends = useCallback((): ErrorTrendData | null => {
    if (analysisHistory.length === 0) return null;

    let blackscreenConsecutive = 0;
    let freezeConsecutive = 0;
    let audioLossConsecutive = 0;

    // Count consecutive errors from the end (most recent snapshots)
    for (let i = analysisHistory.length - 1; i >= 0; i--) {
      const analysis = analysisHistory[i].analysis;
      if (!analysis) break;

      const hasBlackscreen = analysis.blackscreen;
      const hasFreeze = analysis.freeze;
      const hasAudioLoss = isAudioSupported ? !analysis.audio : false;

      // Count consecutive errors
      if (hasBlackscreen) {
        blackscreenConsecutive++;
      } else if (blackscreenConsecutive > 0) {
        break;
      }

      if (hasFreeze) {
        freezeConsecutive++;
      } else if (freezeConsecutive > 0) {
        break;
      }

      if (hasAudioLoss) {
        audioLossConsecutive++;
      } else if (audioLossConsecutive > 0) {
        break;
      }

      // Stop if no errors
      if (!hasBlackscreen && !hasFreeze && !hasAudioLoss) {
        break;
      }
    }

    // Determine warning/error states
    const maxConsecutive = Math.max(
      blackscreenConsecutive,
      freezeConsecutive,
      audioLossConsecutive,
    );
    const hasWarning = maxConsecutive >= 1 && maxConsecutive < 3;
    const hasError = maxConsecutive >= 3;

    return {
      blackscreenConsecutive,
      freezeConsecutive,
      audioLossConsecutive,
      macroblocksConsecutive: 0,
      hasWarning,
      hasError,
    };
  }, [analysisHistory, isAudioSupported]);

  // ❌ REMOVED: Live events polling - redundant!
  // Frame JSON already contains zapping info + action info
  // No need for separate polling

  // Get latest snapshot (most recent)
  const latestSnapshot = analysisHistory.length > 0 ? analysisHistory[analysisHistory.length - 1] : null;

  return {
    latestAnalysis: latestSnapshot?.analysis || null,
    latestSubtitleAnalysis: latestSnapshot?.subtitleAnalysis || null,
    latestLanguageMenuAnalysis: latestSnapshot?.languageMenuAnalysis || null,
    latestAIDescription: latestSnapshot?.aiDescription || null,
    errorTrendData: computeErrorTrends(),
    isLoading,
    analysisTimestamp: latestSnapshot?.timestamp || null,
    requestAIAnalysisForFrame,
    isAIAnalyzing: false, // AI disabled
  };
};
