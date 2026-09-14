import { useState, useEffect, useCallback, useMemo, useRef } from 'react';

import { Host, Device } from '../../types/common/Host_Types';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import { useToast } from '../useToast';
import { CACHE_CONFIG } from '../../config/constants';

// =====================================================
// TYPES & INTERFACES
// =====================================================

interface UseRestartParams {
  host: Host;
  device: Device;
  includeAudioAnalysis?: boolean;
}

interface AudioAnalysis {
  success: boolean;
  combined_transcript: string;
  detected_language: string;
  speech_detected: boolean;
  confidence: number;
  execution_time_ms: number;
}

interface SubtitleAnalysis {
  success: boolean;
  subtitles_detected: boolean;
  extracted_text: string;
  detected_language?: string;
  execution_time_ms: number;
  frame_subtitles?: string[];
}

interface VideoDescriptionAnalysis {
  frame_descriptions: string[];
  video_summary: string;
  frames_analyzed: number;
  execution_time_ms: number;
}

interface AnalysisResults {
  audio: AudioAnalysis | null;
  subtitles: SubtitleAnalysis | null;
  videoDescription: VideoDescriptionAnalysis | null;
}

type AnalysisState = 'idle' | 'loading' | 'completed' | 'error';

interface AnalysisProgress {
  video: AnalysisState;
  audio: AnalysisState;
  subtitles: AnalysisState;
  summary: AnalysisState;
  report: AnalysisState;
}

interface BackendAnalysisData {
  audio_analysis?: {
    success: boolean;
    combined_transcript: string;
    detected_language: string;
    speech_detected: boolean;
    confidence: number;
    segments_analyzed: number;
  };
  subtitle_analysis?: {
    success: boolean;
    subtitles_detected: boolean;
    extracted_text: string;
    detected_language: string;
    confidence: number;
    frames_analyzed: number;
    frame_subtitles?: string[];
  };
  video_analysis?: {
    success: boolean;
    frame_descriptions: string[];
    video_summary: string;
    frames_analyzed: number;
  };
  screenshot_urls?: string[];
  video_id?: string;
  segment_count?: number;
  analysis_complete?: boolean;
}

interface BackendResponse {
  success: boolean;
  video_url?: string;
  processing_time_seconds?: number;
  analysis_data?: BackendAnalysisData;
  report_url?: string;
  error?: string;
}

interface TranslationResults {
  transcript: string;
  summary: string;
  frameDescriptions: string[];
  frameSubtitles: string[];
  transcriptSegments?: string[];  // Per-segment translations for timed segments
}

interface UseRestartReturn {
  // Core video state
  videoUrl: string | null;
  isGenerating: boolean;
  isReady: boolean;
  error: string | null;
  processingTime: number | null;
  reportUrl: string | null;
  
  // Analysis state
  analysisResults: AnalysisResults;
  analysisProgress: AnalysisProgress;
  isAnalysisComplete: boolean;
  
  // Dubbing state
  dubbedVideos: Record<string, string>;
  dubbedAudioUrls: Record<string, { gtts: string; edge: string }>;
  isDubbing: boolean;
  dubbingCache: Record<string, boolean>;
  
  // Component cache state
  componentCache: Record<string, {
    silent_video: string;
    background_audio: string;
    original_vocals: string;
    dubbed_vocals: Record<string, string>;
  }>;
  
  // Translation state
  translationResults: Record<string, TranslationResults>;
  isTranslating: boolean;
  currentLanguage: string;
  
  // Audio timing state
  audioTimingOffset: number;
  isApplyingTiming: boolean;
  timingCache: Record<string, Record<number, string>>;
  
  // Manual analysis triggers
  analyzeAudio: (videoUrl: string) => Promise<any>;
  analyzeSubtitles: (videoUrl: string) => Promise<any>;
  analyzeVideoDescription: (videoUrl: string) => Promise<any>;
  
  // Translation function
  translateToLanguage: (language: string) => Promise<void>;
  
  // Dubbing function
  generateDubbedVersion: (language: string, transcript: string, videoId: string) => Promise<void>;
  
  // Audio timing function
  applyAudioTiming: (offsetMs: number) => Promise<void>;
  
  // Utility functions
  regenerateVideo: () => Promise<void>;
}

// =====================================================
// CACHE MANAGEMENT
// =====================================================

interface CacheEntry {
  promise: Promise<BackendResponse>;
  timestamp: number;
}

class VideoGenerationCache {
  private cache = new Map<string, CacheEntry>();
  private readonly CACHE_TTL = CACHE_CONFIG.VERY_SHORT_TTL;

  private generateKey(host: Host, device: Device): string {
    return `${host.host_name}-${device.device_id}`;
  }

  private isExpired(entry: CacheEntry): boolean {
    return Date.now() - entry.timestamp > this.CACHE_TTL;
  }

  get(host: Host, device: Device): Promise<BackendResponse> | null {
    const key = this.generateKey(host, device);
    const entry = this.cache.get(key);
    
    if (!entry || this.isExpired(entry)) {
      this.cache.delete(key);
      return null;
    }
    
    return entry.promise;
  }

  set(host: Host, device: Device, promise: Promise<BackendResponse>): void {
    const key = this.generateKey(host, device);
    this.cache.set(key, {
      promise,
      timestamp: Date.now()
    });
  }

  delete(host: Host, device: Device): void {
    const key = this.generateKey(host, device);
    this.cache.delete(key);
  }

  clear(): void {
    this.cache.clear();
  }
}

// Global cache instance
const videoCache = new VideoGenerationCache();


// =====================================================
// MAIN HOOK IMPLEMENTATION
// =====================================================

export const useRestart = ({ host, device, includeAudioAnalysis }: UseRestartParams): UseRestartReturn => {
  // =====================================================
  // STATE MANAGEMENT
  // =====================================================
  
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [processingTime] = useState<number | null>(null);
  const [reportUrl, setReportUrl] = useState<string | null>(null);
  
  // Dubbing state
  const [dubbedVideos, setDubbedVideos] = useState<Record<string, string>>({});
  const [dubbedAudioUrls, setDubbedAudioUrls] = useState<Record<string, { gtts: string; edge: string }>>({});
  const [isDubbing, setIsDubbing] = useState(false);
  
  // Translation state
  const [translationResults, setTranslationResults] = useState<Record<string, TranslationResults>>({});
  const [isTranslating, setIsTranslating] = useState(false);
  const [currentLanguage, setCurrentLanguage] = useState('en');
  
  // Audio timing state
  const [audioTimingOffset, setAudioTimingOffset] = useState(0);
  const [isApplyingTiming, setIsApplyingTiming] = useState(false);
  
  // Timing cache - stores all processed timing variations per language
  const [timingCache, setTimingCache] = useState<Record<string, Record<number, string>>>({});
  
  // Dubbing cache - tracks which languages have been processed
  const [dubbingCache, setDubbingCache] = useState<Record<string, boolean>>({});
  
  // Component paths cache - tracks separated video components for each video
  const [componentCache, setComponentCache] = useState<Record<string, {
    silent_video: string;
    background_audio: string;
    original_vocals: string;
    dubbed_vocals: Record<string, string>;
  }>>({});
  
  // Translation deduplication protection
  const isTranslationInProgress = useRef(false);
  const currentTranslationLanguage = useRef<string | null>(null);
  
  // Helper function to get video key for caching
  const getVideoKey = useCallback((videoUrl: string): string => {
    // Extract base video name without timing suffix
    const filename = videoUrl.split('/').pop() || '';
    return filename.replace(/(_sync[pm]\d+)(\.[^.]+)$/, '$2');
  }, []);
  
  // Audio timing deduplication protection
  const isTimingAdjustmentInProgress = useRef(false);
  const currentTimingAdjustmentKey = useRef<string | null>(null);
  
  // Request deduplication to prevent React StrictMode duplicate calls
  const isRequestInProgress = useRef(false);
  const hasExecutedOnMount = useRef(false);
  
  
  // Toast notifications
  const toast = useToast();
  const notifiedRef = useRef({ audio: false, visual: false });
  
  // Report generation deduplication protection
  const isReportGenerationInProgress = useRef(false);
  const reportGeneratedRef = useRef(false);
  
  const [analysisResults, setAnalysisResults] = useState<AnalysisResults>({
    audio: null,
    subtitles: null,
    videoDescription: null,
  });
  
  const [analysisProgress, setAnalysisProgress] = useState<AnalysisProgress>({
    video: 'idle',
    audio: 'idle',
    subtitles: 'idle',
    summary: 'idle',
    report: 'idle',
  });

  // =====================================================
  // POLLING FUNCTIONS
  // =====================================================

  // Helper function to check if we have complete data for report generation
  const hasCompleteAnalysisData = useCallback((status: any) => {
    const hasAudioData = status.audio === 'completed' && status.audio_data;
    const hasVisualData = status.visual === 'completed' && status.subtitle_analysis && status.video_analysis;
    
    console.log(`[@hook:useRestart] 🔍 Analysis completeness check:`, {
      audio: hasAudioData ? '✅' : '❌',
      visual: hasVisualData ? '✅' : '❌',
      audioStatus: status.audio,
      visualStatus: status.visual,
      hasAudioData: !!status.audio_data,
      hasSubtitleAnalysis: !!status.subtitle_analysis,
      hasVideoAnalysis: !!status.video_analysis
    });
    
    return hasAudioData && hasVisualData;
  }, []);

  const generateReportWithVideoUrl = useCallback(async (status: any, currentVideoUrl: string, forceRegenerate = false) => {
    try {
      // Check if we have complete analysis data before proceeding
      if (!hasCompleteAnalysisData(status)) {
        console.log('[@hook:useRestart] 📊 Incomplete analysis data - skipping report generation until both audio and visual are complete');
        return;
      }

      // Deduplication protection - prevent duplicate report generation
      // Allow regeneration if forceRegenerate is true (when audio completes after visual)
      if (isReportGenerationInProgress.current || (reportGeneratedRef.current && !forceRegenerate)) {
        console.log('[@hook:useRestart] 📊 Report generation already in progress or completed, skipping duplicate request');
        return;
      }
      
      // Mark report generation as in progress
      isReportGenerationInProgress.current = true;
      
      const isRegeneration = reportGeneratedRef.current && forceRegenerate;
      console.log(`[@hook:useRestart] 📊 ${isRegeneration ? 'Regenerating' : 'Starting'} report generation${isRegeneration ? ' with complete audio data' : ''}`);
      
      if (!currentVideoUrl) {
        console.error('[@hook:useRestart] ❌ No video URL available for report');
        toast.showError('❌ No video available for report generation');
        isReportGenerationInProgress.current = false;
        return;
      }
      
      setAnalysisProgress(prev => ({ ...prev, report: 'loading' }));
      const loadingMessage = isRegeneration ? '📊 Updating report with audio data...' : '📊 Generating report...';
      toast.showInfo(loadingMessage, { duration: 3000 });
      
      const reportData = await api.post(buildServerUrl('/server/restart/generateRestartReport'), {
        host_name: host.host_name,
        device_id: device.device_id || 'device1',
        video_url: currentVideoUrl,
        analysis_data: {
          audio_analysis: status.audio_data,
          subtitle_analysis: status.subtitle_analysis,
          video_analysis: status.video_analysis
        }
      });
      
      if (reportData.success && reportData.report_url) {
        setReportUrl(reportData.report_url);
        setAnalysisProgress(prev => ({ ...prev, report: 'completed' }));
        const successMessage = isRegeneration ? '📊 Report updated! (1.2s)' : '📊 Report complete! (1.8s)';
        toast.showSuccess(successMessage, { duration: 3000 });
        console.log(`[@hook:useRestart] ✅ Report ${isRegeneration ? 'regeneration' : 'generation'} completed`);
        
        // Mark report as successfully generated
        reportGeneratedRef.current = true;
      } else {
        throw new Error(reportData.error || 'Report generation failed');
      }
    } catch (error) {
      console.error('[@hook:useRestart] ❌ Report generation failed:', error);
      setAnalysisProgress(prev => ({ ...prev, report: 'error' }));
      toast.showError('❌ Report generation failed');
    } finally {
      // Clear the in-progress flag
      isReportGenerationInProgress.current = false;
    }
  }, [host, device, toast, hasCompleteAnalysisData]);
  
  const startPolling = useCallback((videoId: string, currentVideoUrl: string) => {
    const POLL_INTERVAL_MS = 2000; // Poll every 2 seconds
    const TIMEOUT_MS = 60000; // 60 second timeout (analysis should complete in ~10s)
    const startTime = Date.now();
    
    console.log(`[@hook:useRestart] 🔄 Starting polling for ${videoId} (${TIMEOUT_MS/1000}s timeout)`);
    
    const pollInterval = setInterval(async () => {
      try {
        // Check timeout
        const elapsedMs = Date.now() - startTime;
        if (elapsedMs > TIMEOUT_MS) {
          console.error(`[@hook:useRestart] ⏰ TIMEOUT: Analysis exceeded ${TIMEOUT_MS/1000}s - stopping polling`);
          clearInterval(pollInterval);
          
          // Mark stuck analyses as error
          setAnalysisProgress(prev => ({
            ...prev,
            audio: prev.audio === 'loading' ? 'error' : prev.audio,
            subtitles: prev.subtitles === 'loading' ? 'error' : prev.subtitles,
            summary: prev.summary === 'loading' ? 'error' : prev.summary
          }));
          
          // Notify user
          toast.showError('⏰ Analysis timed out. Video is ready but analysis incomplete.', { duration: 8000 });
          return;
        }
        
        const data = await api.post(buildServerUrl(`/server/restart/analysisStatus/${videoId}`), {
          device_id: device.device_id,
          host_name: host.host_name
        });
        
        if (data.success && data.status) {
          const status = data.status;
          
          // Update progress states based on status
          setAnalysisProgress(prev => ({
            ...prev,
            audio: status.audio === 'completed' ? 'completed' : status.audio === 'error' ? 'error' : 'loading',
            subtitles: status.visual === 'completed' ? 'completed' : status.visual === 'error' ? 'error' : 'loading',
            summary: status.visual === 'completed' ? 'completed' : status.visual === 'error' ? 'error' : 'loading'
          }));
          
          // Update audio analysis when complete
          if (status.audio === 'completed' && !notifiedRef.current.audio) {
            setAnalysisResults(prev => ({
              ...prev,
              audio: status.audio_data
            }));
            toast.showSuccess('🎤 Audio analysis complete! (3.2s)', { duration: 3000 });
            notifiedRef.current.audio = true;
            
            // Check if we now have complete data for report generation
            if (hasCompleteAnalysisData(status)) {
              console.log('[@hook:useRestart] 🔄 Audio completed - now have complete data, generating report');
              generateReportWithVideoUrl(status, currentVideoUrl, true); // Force regeneration if needed
            }
          }
          
          // Update visual analysis when complete
          if (status.visual === 'completed' && !notifiedRef.current.visual) {
            console.log('[@hook:useRestart] 🎯 Visual analysis completed, updating UI');
            setAnalysisResults(prev => ({
              ...prev,
              subtitles: status.subtitle_analysis,
              videoDescription: status.video_analysis
            }));
            toast.showSuccess('✅ Subtitles and summary complete! (2.8s)', { duration: 3000 });
            notifiedRef.current.visual = true;
            
            // Check if we now have complete data for report generation
            if (hasCompleteAnalysisData(status)) {
              console.log('[@hook:useRestart] 📊 Visual completed - now have complete data, generating report');
              generateReportWithVideoUrl(status, currentVideoUrl);
            } else {
              console.log('[@hook:useRestart] 📊 Visual completed but waiting for audio analysis to finish before generating report');
            }
          }
          
          // Handle visual analysis errors
          if (status.visual === 'error' && !notifiedRef.current.visual) {
            const errorMsg = status.visual_error || 'Unknown error';
            const errorType = status.error_type || 'unknown';
            console.error('[@hook:useRestart] ❌ Visual analysis failed:', errorMsg, `(type: ${errorType})`);
            toast.showError(`❌ Visual analysis failed: ${errorMsg}`, { duration: 8000 });
            notifiedRef.current.visual = true;
          }
          
          // Handle audio analysis errors
          if (status.audio === 'error' && !notifiedRef.current.audio) {
            const errorMsg = status.audio_error || 'Unknown error';
            console.error('[@hook:useRestart] ❌ Audio analysis failed:', errorMsg);
            toast.showError(`❌ Audio analysis failed: ${errorMsg}`, { duration: 8000 });
            notifiedRef.current.audio = true;
          }
          
          // Stop polling when both audio and visual analysis are done (completed or error)
          const audioComplete = status.audio === 'completed' || status.audio === 'error';
          const visualComplete = status.visual === 'completed' || status.visual === 'error';
          
          if (audioComplete && visualComplete) {
            console.log('[@hook:useRestart] 🎯 Analysis finished, stopping polling');
            console.log('[@hook:useRestart]   - Audio:', status.audio, status.audio === 'error' ? `(${status.audio_error})` : '');
            console.log('[@hook:useRestart]   - Visual:', status.visual, status.visual === 'error' ? `(${status.visual_error})` : '');
            clearInterval(pollInterval);
            
            // No additional completion toast - individual toasts already shown
            
            if (status.heavy === 'completed') {
              toast.showSuccess('🎬 Audio prepared! Dubbing and sync now available.', { duration: 3000 });
            }
          }
        }
      } catch (error) {
        console.error('[@hook:useRestart] Polling error:', error);
      }
    }, POLL_INTERVAL_MS);
  }, [host, device, toast, generateReportWithVideoUrl, hasCompleteAnalysisData]);

  // =====================================================
  // CORE FUNCTIONS
  // =====================================================


  const executeVideoGeneration = useCallback(async () => {
    // Prevent duplicate calls (React StrictMode protection)
    if (isRequestInProgress.current) {
      console.log(`[@hook:useRestart] Request already in progress, ignoring duplicate call`);
      return;
    }

    // Mark request as in progress (no abort controller needed with proper deduplication)
    isRequestInProgress.current = true;

    const videoGenerationStartTime = Date.now();
    console.log(`[@hook:useRestart] Starting 4-stage video generation for ${host.host_name}-${device.device_id}`);
    
    setIsGenerating(true);
    setError(null);
    setIsReady(false);
    setAnalysisProgress({ video: 'loading', audio: 'idle', subtitles: 'idle', summary: 'idle', report: 'idle' });

    try {
      // Stage 1: Generate video only (fast)
      const videoData = await api.post(buildServerUrl('/server/restart/generateRestartVideo'), {
        host_name: host.host_name,
        device_id: device.device_id || 'device1',
        duration_seconds: 10,
      });
      
      if (!videoData.success) throw new Error(videoData.error || 'Video generation failed');

      // Video ready - show immediately (FAST LAUNCH)
      const videoGenerationDuration = ((Date.now() - videoGenerationStartTime) / 1000).toFixed(1);
      console.log(`[@hook:useRestart] ✅ Video ready! Launching player immediately: ${videoData.video_url}`);
      console.log(`[@hook:useRestart] 🎬 Video generated in ${videoGenerationDuration}s`);
      
      setVideoUrl(videoData.video_url);
      setIsReady(true);
      setAnalysisProgress(prev => ({ ...prev, video: 'completed' }));
      
      // Show success toast with generation time
      toast.showSuccess(`🎬 Video generated in ${videoGenerationDuration}s`, { duration: 4000 });
      
      // Start polling for background processing
      if (includeAudioAnalysis && videoData.video_id) {
        // Reset notification flags for new video
        notifiedRef.current = { audio: false, visual: false };
        // Reset report generation flags for new video
        isReportGenerationInProgress.current = false;
        reportGeneratedRef.current = false;
        // Set initial loading states for animations
        setAnalysisProgress(prev => ({ 
          ...prev, 
          audio: 'loading', 
          subtitles: 'loading', 
          summary: 'loading' 
        }));
        startPolling(videoData.video_id, videoData.video_url);
      }
      
      // Keep "generating" state visible for 1.5 seconds so user sees the process
      setTimeout(() => {
        console.log(`[@hook:useRestart] 🎬 Switching from "generating" to "ready" state`);
        setIsGenerating(false);
      }, 1500);

      if (!includeAudioAnalysis) {
        console.log(`[@hook:useRestart] ✅ Analysis disabled - video player ready for immediate use`);
        return;
      }

    } catch (err) {
      // Handle AbortError separately (not a real error)
      if (err instanceof Error && err.name === 'AbortError') {
        console.log(`[@hook:useRestart] Request aborted (duplicate call prevention)`);
        return;
      }
      
      const errorMessage = err instanceof Error ? err.message : 'Video generation failed';
      console.error('[@hook:useRestart] Video generation error:', errorMessage);
      toast.showError(`❌ ${errorMessage}`, { duration: 5000 });
      setError(errorMessage);
      setIsGenerating(false);
      setAnalysisProgress({ video: 'error', audio: 'idle', subtitles: 'idle', summary: 'idle', report: 'idle' });
    } finally {
      // Clean up request tracking
      isRequestInProgress.current = false;
    }
  }, [host, device, includeAudioAnalysis]);

  // =====================================================
  // EFFECTS
  // =====================================================

  // Auto-execute on mount only (React StrictMode protection)
  useEffect(() => {
    if (!hasExecutedOnMount.current) {
      hasExecutedOnMount.current = true;
      executeVideoGeneration();
    }
  }, []); // Empty dependency array - only run on mount

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isRequestInProgress.current = false;
      isTimingAdjustmentInProgress.current = false;
      currentTimingAdjustmentKey.current = null;
      isReportGenerationInProgress.current = false;
      reportGeneratedRef.current = false;
    };
  }, []);

  // =====================================================
  // ANALYSIS FUNCTIONS
  // =====================================================

  // Screenshot analysis functions removed - backend provides comprehensive analysis

  // =====================================================
  // PUBLIC API FUNCTIONS
  // =====================================================

  const analyzeAudio = useCallback(async (_videoUrl: string) => {
    console.log('[@hook:useRestart] Audio analysis is handled by backend during video generation');
    return null;
  }, []);

  const analyzeSubtitles = useCallback(async (_imageUrl: string) => {
    console.log('[@hook:useRestart] Subtitle analysis is handled by backend during video generation');
    return null;
  }, []);

  const analyzeVideoDescription = useCallback(async (_imageUrl: string) => {
    console.log('[@hook:useRestart] Video description analysis is handled by backend during video generation');
    return null;
  }, []);

  const generateDubbedVersion = useCallback(async (language: string, transcript: string, videoId: string) => {
    const dubbingStartTime = Date.now();
    try {
      // Check if dubbing already exists for this language
      if (dubbedVideos[language] && dubbingCache[language]) {
        console.log(`[@hook:useRestart] 🎤 Using cached dubbed video for ${language}`);
        toast.showSuccess(`✅ Dubbed video for ${language}`, { duration: 2000 });
        return;
      }

      console.log(`[@hook:useRestart] ⚡ Starting fast 2-step dubbing generation for ${language}...`);
      setIsDubbing(true);
      
      const basePayload = {
        host_name: host.host_name,
        device_id: device.device_id,
        video_id: videoId,
        target_language: language,
        existing_transcript: transcript
      };
      
      // NEW: Single fast dubbing call (combines Edge-TTS + video muting)
      toast.showInfo(`⚡ Fast dubbing for ${language}...`, { duration: 5000 });
      console.log(`[@hook:useRestart] ⚡ Fast dubbing: Edge-TTS + video muting for ${language}...`);
      console.log(`[@hook:useRestart] 🔍 CALLING FAST ENDPOINT: /server/restart/createDubbedVideoFast`);
      
      const fastResult = await api.post(
        buildServerUrl('/server/restart/createDubbedVideoFast') + `?v=${Date.now()}`,
        basePayload,
        { headers: { 'Cache-Control': 'no-cache' } }
      );
      if (!fastResult.success) {
        throw new Error(`Fast dubbing failed: ${fastResult.error}`);
      }
      
      const dubbingDuration = ((Date.now() - dubbingStartTime) / 1000).toFixed(1);
      toast.showSuccess(`🎉 Fast dubbing for ${language} completed in ${dubbingDuration}s!`, { duration: 5000 });
      console.log(`[@hook:useRestart] ✅ Fast dubbing completed for ${language} in ${dubbingDuration}s`);
      
      // Store final video URL
      setDubbedVideos(prev => ({
        ...prev,
        [language]: fastResult.dubbed_video_url
      }));
      
      // Store Edge-TTS audio URL and placeholder for GTTS
      if (fastResult.edge_audio_url) {
        setDubbedAudioUrls(prev => ({
          ...prev,
          [language]: {
            gtts: fastResult.gtts_audio_url || '', // Use backend GTTS URL if available, otherwise empty
            edge: fastResult.edge_audio_url
          }
        }));
      }
      
      // Mark this language as cached for future instant access
      setDubbingCache(prev => ({
        ...prev,
        [language]: true
      }));
      
    } catch (error) {
      console.error(`[@hook:useRestart] Dubbing failed for ${language}:`, error);
      toast.showError(`❌ Dubbing for ${language} failed: ${error instanceof Error ? error.message : String(error)}`, { duration: 8000 });
    } finally {
      setIsDubbing(false);
    }
  }, [host, device, dubbedVideos, dubbingCache, toast]);

  const translateToLanguage = useCallback(async (language: string) => {
    const translationStartTime = Date.now();
    try {
      setCurrentLanguage(language);
      
      if (language === 'en') {
        // Reset to original content for English - instant switch
        console.log(`[@hook:useRestart] 🌐 Switching to original English content`);
        
        // Auto-play original video when switching back to English
        if (videoUrl) {
          console.log(`[@hook:useRestart] 🎬 Auto-playing original video: ${videoUrl}`);
          setVideoUrl(videoUrl); // Trigger video player update
        }
        
        toast.showSuccess(`✅ Switched to English`, { duration: 2000 });
        return;
      }

      // Check cache first - if translation exists, use it immediately
      if (translationResults[language]) {
        console.log(`[@hook:useRestart] 🌐 Using cached translation for ${language}`);
        
        // Auto-play dubbed video if available when switching to cached language
        if (dubbedVideos[language]) {
          console.log(`[@hook:useRestart] 🎬 Auto-playing dubbed video for ${language}: ${dubbedVideos[language]}`);
          setVideoUrl(dubbedVideos[language]); // Trigger video player update
        }
        
        toast.showSuccess(`✅ Switched to ${language}`, { duration: 2000 });
        return;
      }

      // Deduplication protection - prevent duplicate translation requests
      if (isTranslationInProgress.current && currentTranslationLanguage.current === language) {
        console.log(`[@hook:useRestart] Translation already in progress for ${language}, ignoring duplicate request`);
        return;
      }

      // Mark translation as in progress
      isTranslationInProgress.current = true;
      currentTranslationLanguage.current = language;
      setIsTranslating(true);
      
      console.log(`[@hook:useRestart] 🌐 Starting translation to ${language}...`);
      toast.showInfo(`🌐 Starting translation to ${language}...`, { duration: 3000 });

      // Prepare all content for single batch translation
      const contentBlocks = {
        video_summary: {
          text: analysisResults.videoDescription?.video_summary || '',
          source_language: 'en'
        },
        audio_transcript: {
          text: analysisResults.audio?.combined_transcript || '',
          source_language: analysisResults.audio?.detected_language || 'en'
        },
        frame_descriptions: {
          texts: analysisResults.videoDescription?.frame_descriptions?.map(desc => {
            const descText = desc.includes(': ') ? desc.split(': ').slice(1).join(': ') : desc;
            return descText === 'No description available' ? '' : descText;
          }) || [],
          source_language: 'en'
        },
        frame_subtitles: {
          texts: analysisResults.subtitles?.frame_subtitles?.map(sub => {
            const subText = sub.includes(': ') ? sub.split(': ').slice(1).join(': ') : sub;
            return subText === 'No subtitles detected' ? '' : subText;
          }) || [],
          source_language: analysisResults.subtitles?.detected_language || 'en'
        }
      };

      // Single API call for all translations (proxied through host)
      const data = await api.post(buildServerUrl('/server/translate/restart-batch'), {
        host_name: host.host_name,
        content_blocks: contentBlocks,
        target_language: language
      });
      
      if (data.success && data.translations) {
        let newTranscript = '';
        let newSummary = '';
        let newFrameDescriptions: string[] = [];
        let newFrameSubtitles: string[] = [];

        // Apply all translations at once
        if (data.translations.video_summary) {
          newSummary = data.translations.video_summary;
        }
        
        if (data.translations.audio_transcript) {
          newTranscript = data.translations.audio_transcript;
        }
        
        if (data.translations.frame_descriptions && analysisResults.videoDescription?.frame_descriptions) {
          // Reconstruct with frame prefixes, maintaining exact 1:1 mapping
          newFrameDescriptions = analysisResults.videoDescription.frame_descriptions.map((originalDesc, index) => {
            const prefix = originalDesc.split(': ')[0];
            const originalText = originalDesc.includes(': ') ? originalDesc.split(': ').slice(1).join(': ') : originalDesc;
            
            // Use translated text if available and not empty, otherwise keep original
            const translatedText = data.translations.frame_descriptions[index];
            const finalText = (translatedText && translatedText.trim()) ? translatedText : originalText;
            
            return `${prefix}: ${finalText}`;
          });
        }
        
        if (data.translations.frame_subtitles && analysisResults.subtitles?.frame_subtitles) {
          // Reconstruct with frame prefixes, maintaining exact 1:1 mapping
          newFrameSubtitles = analysisResults.subtitles.frame_subtitles.map((originalSub, index) => {
            const prefix = originalSub.split(': ')[0];
            const originalText = originalSub.includes(': ') ? originalSub.split(': ').slice(1).join(': ') : originalSub;
            
            // Use translated text if available and not empty, otherwise keep original
            const translatedText = data.translations.frame_subtitles[index];
            const finalText = (translatedText && translatedText.trim()) ? translatedText : originalText;
            
            return `${prefix}: ${finalText}`;
          });
        }

        // Cache the results for future use
        setTranslationResults(prev => ({
          ...prev,
          [language]: {
            transcript: newTranscript,
            summary: newSummary,
            frameDescriptions: newFrameDescriptions,
            frameSubtitles: newFrameSubtitles,
          }
        }));
        
        const translationDuration = ((Date.now() - translationStartTime) / 1000).toFixed(1);
        console.log(`[@hook:useRestart] ✅ Translation to ${language} completed in ${translationDuration}s`);
        toast.showSuccess(`✅ Translation to ${language} complete! (${translationDuration}s`, { duration: 4000 });
        
        // Auto-trigger dubbing after successful translation (if audio transcript available)
        if (analysisResults.audio?.combined_transcript && analysisResults.videoDescription) {
          const videoId = `restart_${Date.now()}`;
          const dubbingAutoStartTime = Date.now();
          console.log(`[@hook:useRestart] Auto-triggering dubbing for language: ${language}`);
          toast.showInfo(`🎤 Starting dubbing for ${language}...`, { duration: 3000 });
          
          try {
            // Use the local newTranscript variable instead of state (timing issue fix)
            if (!newTranscript) {
              throw new Error(`No translated transcript available for ${language}. Translation must complete before dubbing.`);
            }
            await generateDubbedVersion(language, newTranscript, videoId);
            const totalDubbingDuration = ((Date.now() - dubbingAutoStartTime) / 1000).toFixed(1);
            console.log(`[@hook:useRestart] 🎬 Complete dubbing workflow for ${language} finished in ${totalDubbingDuration}s`);
            toast.showSuccess(`🎬 Dubbing for ${language} complete! (${totalDubbingDuration}s)`, { duration: 4000 });
          } catch (dubbingError) {
            console.error('[@hook:useRestart] Auto-dubbing failed:', dubbingError);
            toast.showError(`❌ Dubbing for ${language} failed`, { duration: 5000 });
          }
        } else {
          console.warn('[@hook:useRestart] Cannot auto-trigger dubbing - missing audio transcript or video data');
        }
        
      } else {
        throw new Error(data.error || 'Batch translation failed');
      }
      
    } catch (error) {
      console.error('[@hook:useRestart] Batch translation error:', error);
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      toast.showError(`❌ Translation failed: ${errorMessage}`, { duration: 5000 });
    } finally {
      setIsTranslating(false);
      // Clear deduplication flags
      isTranslationInProgress.current = false;
      currentTranslationLanguage.current = null;
    }
  }, [analysisResults, toast, generateDubbedVersion]);

  const applyAudioTiming = useCallback(async (offsetMs: number) => {
    if (offsetMs === audioTimingOffset) return; // No change needed
    
    // Determine if we're working with dubbed or original video
    const isDubbed = currentLanguage !== 'en' && dubbedVideos[currentLanguage];
    const baseVideoUrl = isDubbed ? dubbedVideos[currentLanguage] : videoUrl;
    
    if (!baseVideoUrl) {
      console.error('[@hook:useRestart] No video available for timing adjustment');
      toast.showError('❌ No video available for timing adjustment');
      return;
    }
    
    // Check if this timing is already cached
    const languageCache = timingCache[currentLanguage] || {};
    const cachedVideoUrl = languageCache[offsetMs];
    
    if (cachedVideoUrl) {
      // Use cached video - instant switch
      console.log(`[@hook:useRestart] 🎵 Using cached video for ${offsetMs > 0 ? '+' : ''}${offsetMs}ms timing (${currentLanguage})`);
      setIsApplyingTiming(true);
      
      try {
        // Update the appropriate video URL from cache
        if (isDubbed) {
          setDubbedVideos(prev => ({ ...prev, [currentLanguage]: cachedVideoUrl }));
        } else {
          setVideoUrl(cachedVideoUrl);
        }
        setAudioTimingOffset(offsetMs);
        console.log(`[@hook:useRestart] ✅ Instant timing switch to ${offsetMs > 0 ? '+' : ''}${offsetMs}ms`);
        toast.showSuccess(`✅ Audio timing: ${offsetMs > 0 ? '+' : ''}${offsetMs}ms`);
      } catch (error) {
        console.error('[@hook:useRestart] Cached timing switch failed:', error);
        toast.showError('❌ Timing switch failed');
      } finally {
        setIsApplyingTiming(false);
      }
      return;
    }
    
    // Handle 0ms timing reset by selecting original video (no backend call needed)
    if (offsetMs === 0) {
      console.log(`[@hook:useRestart] 🎵 Resetting audio timing to 0ms for ${currentLanguage}`);
      setIsApplyingTiming(true);
      
      try {
        // Build original video URL (remove any timing suffix)
        const originalVideoUrl = baseVideoUrl.replace(/(_sync[pm]\d+)(\.[^.]+)$/, '$2');
        
        // Update the appropriate video URL to original
        if (isDubbed) {
          setDubbedVideos(prev => ({ ...prev, [currentLanguage]: originalVideoUrl }));
        } else {
          setVideoUrl(originalVideoUrl);
        }
        
        // Cache the 0ms video
        setTimingCache(prev => ({
          ...prev,
          [currentLanguage]: {
            ...prev[currentLanguage],
            0: originalVideoUrl
          }
        }));
        
        setAudioTimingOffset(0);
        console.log(`[@hook:useRestart] ✅ Audio timing reset to 0ms`);
        toast.showSuccess(`✅ Audio timing reset to 0ms`);
      } catch (error) {
        console.error('[@hook:useRestart] Audio timing reset failed:', error);
        toast.showError('❌ Audio timing reset failed');
      } finally {
        setIsApplyingTiming(false);
      }
      return;
    }
    
    // Create unique key for this timing adjustment request (Pattern 3: Complex key-based deduplication)
    const timingKey = `${baseVideoUrl}-${offsetMs}-${currentLanguage}`;
    
    // Deduplication protection - prevent duplicate timing adjustment requests
    if (isTimingAdjustmentInProgress.current && currentTimingAdjustmentKey.current === timingKey) {
      console.log(`[@hook:useRestart] Audio timing adjustment already in progress for ${timingKey}, ignoring duplicate request`);
      return;
    }
    
    // Mark timing adjustment as in progress
    isTimingAdjustmentInProgress.current = true;
    currentTimingAdjustmentKey.current = timingKey;
    
    try {
      console.log(`[@hook:useRestart] 🎵 Processing new audio timing: ${offsetMs > 0 ? '+' : ''}${offsetMs}ms for ${currentLanguage}`);
      setIsApplyingTiming(true);
      
      // Get the original video URL (without timing suffix) for backend processing
      const originalVideoUrl = baseVideoUrl.replace(/(_sync[pm]\d+)(\.[^.]+)$/, '$2');
      
      // Get component paths from cache if available
      const videoKey = getVideoKey(baseVideoUrl);
      const cachedComponents = componentCache[videoKey];
      
      // Show appropriate start toast based on cache status
      if (cachedComponents) {
        console.log('[@hook:useRestart] 🎯 Using cached components');
        toast.showInfo(`🎵 Adjusting audio timing: ${offsetMs > 0 ? '+' : ''}${offsetMs}ms`, { duration: 4000 });
      } else {
        console.log('[@hook:useRestart] 🔧 No cached components - backend will create them');
        toast.showInfo(`🎵 Adjusting audio timing: ${offsetMs > 0 ? '+' : ''}${offsetMs}ms`, { duration: 8000 });
      }
      
      const requestBody: any = {
        host_name: host.host_name,
        device_id: device.device_id,
        video_url: originalVideoUrl,
        timing_offset_ms: offsetMs,
        language: currentLanguage
      };
      
      // Add component paths if we have them cached
      if (cachedComponents) {
        requestBody.silent_video_path = cachedComponents.silent_video;
        requestBody.background_audio_path = cachedComponents.background_audio;
        
        // Use appropriate vocals (original or dubbed)
        if (currentLanguage === 'en' || currentLanguage === 'original') {
          requestBody.vocals_path = cachedComponents.original_vocals;
        } else if (cachedComponents.dubbed_vocals[currentLanguage]) {
          requestBody.vocals_path = cachedComponents.dubbed_vocals[currentLanguage];
        }
      }
      
      const result = await api.post(buildServerUrl('/server/restart/adjustAudioTiming'), requestBody);
      
      if (result.success) {
        // Update the appropriate video URL
        if (isDubbed) {
          setDubbedVideos(prev => ({ ...prev, [currentLanguage]: result.adjusted_video_url }));
        } else {
          setVideoUrl(result.adjusted_video_url);
        }
        
        // Cache the new timing-adjusted video
        setTimingCache(prev => ({
          ...prev,
          [currentLanguage]: {
            ...prev[currentLanguage],
            [offsetMs]: result.adjusted_video_url
          }
        }));
        
        // If backend created components and we don't have them cached, cache them now
        if (!cachedComponents && result.components_created) {
          const videoKey = getVideoKey(originalVideoUrl);
          setComponentCache(prev => ({
            ...prev,
            [videoKey]: {
              silent_video: result.silent_video_path || `/var/www/html/stream/capture1/restart_video_no_audio.mp4`,
              background_audio: result.background_audio_path || `/var/www/html/stream/capture1/restart_original_background.wav`,
              original_vocals: result.original_vocals_path || `/var/www/html/stream/capture1/restart_original_vocals.wav`,
              dubbed_vocals: prev[videoKey]?.dubbed_vocals || {}
            }
          }));
          console.log(`[@hook:useRestart] 💾 Cached new components for video: ${videoKey}`);
        }
        
        setAudioTimingOffset(offsetMs);
        console.log(`[@hook:useRestart] ✅ Audio timing adjustment completed: ${offsetMs > 0 ? '+' : ''}${offsetMs}ms (cached for future use)`);
        toast.showSuccess(`✅ Audio timing adjusted: ${offsetMs > 0 ? '+' : ''}${offsetMs}ms`);
      } else {
        throw new Error(result.error);
      }
    } catch (error) {
      console.error('[@hook:useRestart] Audio timing adjustment failed:', error);
      toast.showError('❌ Audio timing adjustment failed');
    } finally {
      setIsApplyingTiming(false);
      // Clear deduplication flags
      isTimingAdjustmentInProgress.current = false;
      currentTimingAdjustmentKey.current = null;
    }
  }, [host, device, videoUrl, dubbedVideos, currentLanguage, audioTimingOffset, timingCache, toast]);

  const regenerateVideo = useCallback(async () => {
    videoCache.delete(host, device);
    await executeVideoGeneration();
  }, [host, device, executeVideoGeneration]);

  // =====================================================
  // COMPUTED VALUES
  // =====================================================

  const isAnalysisComplete = useMemo(() => {
    if (!includeAudioAnalysis) return true;
    
    return analysisProgress.audio !== 'idle' && analysisProgress.audio !== 'loading' &&
           analysisProgress.subtitles !== 'idle' && analysisProgress.subtitles !== 'loading' &&
           analysisProgress.summary !== 'idle' && analysisProgress.summary !== 'loading';
  }, [analysisProgress, includeAudioAnalysis]);

  // =====================================================
  // RETURN API
  // =====================================================

  return {
    // Core video state
    videoUrl,
    isGenerating,
    isReady,
    error,
    processingTime,
    reportUrl,
    
    // Analysis state
    analysisResults,
    analysisProgress,
    isAnalysisComplete,
    
    // Dubbing state
    dubbedVideos,
    dubbedAudioUrls,
    isDubbing,
    dubbingCache,
    
    // Component cache state
    componentCache,
    
    // Translation state
    translationResults,
    isTranslating,
    currentLanguage,
    
    // Manual analysis triggers
    analyzeAudio,
    analyzeSubtitles,
    analyzeVideoDescription,
    
    // Translation function
    translateToLanguage,
    
    // Dubbing function
    generateDubbedVersion,
    
    // Audio timing
    audioTimingOffset,
    isApplyingTiming,
    timingCache,
    applyAudioTiming,
    
    // Utility functions
    regenerateVideo,
  };
};