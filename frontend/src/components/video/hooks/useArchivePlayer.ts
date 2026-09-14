import { useState, useCallback, useMemo, useEffect } from 'react';
import { ArchiveMetadata } from '../EnhancedHLSPlayer.types';
import { Host } from '../../../types/common/Host_Types';
import { buildStreamUrl } from '../../../utils/buildUrlUtils';

interface UseArchivePlayerProps {
  isLiveMode: boolean;
  providedStreamUrl?: string;
  hookStreamUrl?: string;
  host?: Host;
  deviceId: string;
  isTransitioning: boolean;
  videoRef: React.RefObject<HTMLVideoElement>;
  onVideoTimeUpdate?: (time: number) => void;
}

export const useArchivePlayer = ({
  isLiveMode,
  providedStreamUrl,
  hookStreamUrl,
  host,
  deviceId,
  isTransitioning,
  videoRef,
  onVideoTimeUpdate,
}: UseArchivePlayerProps) => {
  const [archiveMetadata, setArchiveMetadata] = useState<ArchiveMetadata | null>(null);
  const [currentManifestIndex, setCurrentManifestIndex] = useState(0);
  const [globalCurrentTime, setGlobalCurrentTime] = useState(0);
  const [preloadedNextManifest, setPreloadedNextManifest] = useState(false);
  const [isDraggingSlider, setIsDraggingSlider] = useState(false);
  const [dragSliderValue, setDragSliderValue] = useState(0);
  const [availableHours, setAvailableHours] = useState<number[]>([]);
  const [isCheckingAvailability, setIsCheckingAvailability] = useState(false);
  const [continuousStartTime, setContinuousStartTime] = useState<number>(0);
  const [continuousEndTime, setContinuousEndTime] = useState<number>(0);
  const [hasAttemptedLoad, setHasAttemptedLoad] = useState(false);
  const [isManualSeeking, setIsManualSeeking] = useState(false);
  const [lastErrorTime, setLastErrorTime] = useState<number>(0);
  const [errorChunkIndices, setErrorChunkIndices] = useState<Set<number>>(new Set());

  const loadArchiveManifest = useCallback(async (baseUrl: string): Promise<ArchiveMetadata | null> => {
    setIsCheckingAvailability(true);
    
    try {
      const manifestUrl = baseUrl.replace(/\/(segments\/)?(output|archive.*?)\.m3u8$/, '/segments/archive_manifest.json');
      const response = await fetch(manifestUrl);
      
      if (!response.ok) {
        console.warn('[@EnhancedHLSPlayer] No archive manifest found');
        return null;
      }
      
      const manifest = await response.json();
      console.log(`[@EnhancedHLSPlayer] Loaded manifest: ${manifest.total_chunks} chunks across ${manifest.available_hours.length} hours`);
      console.log(`[@EnhancedHLSPlayer] Continuous range: ${manifest.continuous_from ? `hour ${manifest.continuous_from.hour}, chunk ${manifest.continuous_from.chunk_index}` : 'unknown'} to ${manifest.chunks.length > 0 ? `hour ${manifest.chunks[manifest.chunks.length - 1].hour}, chunk ${manifest.chunks[manifest.chunks.length - 1].chunk_index}` : 'unknown'}`);
      
      setAvailableHours(manifest.available_hours);
      
      // Sort chunks chronologically by creation timestamp (oldest first)
      // This handles rolling 24h archives where clock time wraps around
      const sortedChunks = [...manifest.chunks].sort((a: any, b: any) => {
        return a.created - b.created;
      });
      
      const metadata: ArchiveMetadata = {
        total_segments: manifest.total_chunks,
        total_duration_seconds: manifest.total_chunks * 600,
        window_hours: 1,
        segments_per_window: 6,
        manifests: sortedChunks.map((chunk: any, index: number) => ({
          name: `${chunk.hour}/chunk_10min_${chunk.chunk_index}.mp4`,
          window_index: chunk.hour,
          chunk_index: chunk.chunk_index,
          start_segment: index,
          end_segment: index,
          // Use sequential playback time (index * 600) for archive navigation
          // But keep clock time for reference
          start_time_seconds: chunk.hour * 3600 + chunk.chunk_index * 600,
          end_time_seconds: chunk.hour * 3600 + (chunk.chunk_index + 1) * 600,
          duration_seconds: 600,
          created: chunk.created  // Preserve creation timestamp
        }))
      };
      
      // Calculate continuous time range
      if (metadata.manifests.length > 0) {
        const firstChunk = metadata.manifests[0];
        const lastChunk = metadata.manifests[metadata.manifests.length - 1];
        setContinuousStartTime(firstChunk.start_time_seconds);
        setContinuousEndTime(lastChunk.end_time_seconds);
      }
      
      return metadata;
    } catch (error) {
      console.error('[@EnhancedHLSPlayer] Failed to load archive manifest:', error);
      return null;
    } finally {
      setIsCheckingAvailability(false);
    }
  }, []);

  useEffect(() => {
    if (!isLiveMode && !archiveMetadata && !isTransitioning && !isCheckingAvailability && !hasAttemptedLoad) {
      const initializeArchiveMode = async () => {
        const baseUrl = providedStreamUrl || hookStreamUrl || buildStreamUrl(host, deviceId, 'archive');
        const metadata = await loadArchiveManifest(baseUrl);
        
        setHasAttemptedLoad(true);
        
        if (!metadata || metadata.manifests.length === 0) {
          console.warn('[@EnhancedHLSPlayer] No archive data available');
          return;
        }
        
        // Start from the most recent chunk in the archive (last chunk in sorted array)
        // This ensures we always start from available content, not theoretical "current" time
        const closestIndex = metadata.manifests.length - 1;
        const newestChunk = metadata.manifests[closestIndex];
        
        console.log(`[@EnhancedHLSPlayer] Archive initialized: ${metadata.manifests.length} chunks`);
        console.log(`[@EnhancedHLSPlayer] Starting from most recent chunk: hour ${newestChunk.window_index}, chunk ${newestChunk.chunk_index} (${newestChunk.start_time_seconds}s)`);
        
        setArchiveMetadata(metadata);
        setCurrentManifestIndex(closestIndex);
        setGlobalCurrentTime(newestChunk.start_time_seconds);
      };
      
      initializeArchiveMode();
    }
  }, [isLiveMode, archiveMetadata, isTransitioning, isCheckingAvailability, hasAttemptedLoad, providedStreamUrl, hookStreamUrl, deviceId, host, loadArchiveManifest]);

  const hourMarks = useMemo(() => {
    if (!archiveMetadata) return [];
    
    const marks = [];
    const now = new Date();
    const currentHour = now.getHours();
    const currentMinute = now.getMinutes();
    const currentSecond = now.getSeconds();
    const currentTimeInSeconds = currentMinute * 60 + currentSecond;
    
    // Simple: Generate 25 marks from 24h ago (left) to now (right)
    // Each mark represents an hour boundary in the rolling 24h window
    for (let hoursAgo = 0; hoursAgo <= 24; hoursAgo++) {
      const actualHour = (currentHour - hoursAgo + 24) % 24;
      const positionSeconds = 86400 - (hoursAgo * 3600) + currentTimeInSeconds;
      
      // Skip if too close to "Now" (within 30 minutes to prevent overlap)
      const distanceFromNow = 86400 - positionSeconds;
      if (distanceFromNow < 1800 && hoursAgo > 0) {
        continue;
      }
      
      const isAvailable = availableHours.includes(actualHour);
      const label = hoursAgo === 0 ? 'Now' : `${actualHour}h`;
      
      marks.push({
        value: positionSeconds,
        label: label,
        style: isAvailable ? {} : {
          color: 'rgba(255, 255, 255, 0.3)',
          opacity: 0.5
        }
      });
    }
    
    // Sort marks by position (left to right)
    marks.sort((a, b) => a.value - b.value);
    
    return marks;
  }, [archiveMetadata, availableHours]);

  const handleVideoError = useCallback(() => {
    if (!videoRef.current || isLiveMode) return;
    
    const video = videoRef.current;
    const error = video.error;
    
    if (error && archiveMetadata && archiveMetadata.manifests.length > 0) {
      const now = Date.now();
      const timeSinceLastError = now - lastErrorTime;
      
      // Mark current chunk as having errors
      setErrorChunkIndices(prev => new Set(prev).add(currentManifestIndex));
      
      console.warn(`[@EnhancedHLSPlayer] Video error (${error.code}): ${error.message}`);
      console.warn(`[@EnhancedHLSPlayer] Problematic chunk marked: ${currentManifestIndex + 1}/${archiveMetadata.manifests.length}`);
      
      // ANTI-CASCADE: If errors happening too frequently (< 2 seconds apart), stop auto-skipping
      if (timeSinceLastError < 2000) {
        console.error(`[@EnhancedHLSPlayer] ⚠️ Error cascade detected! Stopping auto-skip. Please seek to a different position.`);
        return;
      }
      
      // DON'T auto-skip during manual seeking - let user choose where to go
      if (isManualSeeking) {
        console.warn(`[@EnhancedHLSPlayer] Error during manual seek - NOT auto-skipping. User controls navigation.`);
        return;
      }
      
      // Only auto-skip during normal playback
      setLastErrorTime(now);
      const nextIndex = currentManifestIndex + 1;
      
      if (nextIndex < archiveMetadata.manifests.length) {
        console.log(`[@EnhancedHLSPlayer] Auto-skipping to next chunk during playback (${nextIndex + 1}/${archiveMetadata.manifests.length})`);
        setCurrentManifestIndex(nextIndex);
        setPreloadedNextManifest(false);
      } else {
        console.warn('[@EnhancedHLSPlayer] No more chunks available');
      }
    }
  }, [isLiveMode, archiveMetadata, currentManifestIndex, videoRef, lastErrorTime, isManualSeeking]);

  const handleSliderChange = useCallback((_event: Event | React.SyntheticEvent, newValue: number | number[]) => {
    const sliderValue = Array.isArray(newValue) ? newValue[0] : newValue;
    if (!isFinite(sliderValue) || sliderValue < 0) return;
    
    // Store the inverted slider value for display (timeline shows inverted positions)
    setIsDraggingSlider(true);
    setDragSliderValue(sliderValue);
  }, []);

  const handleSeek = useCallback((_event: Event | React.SyntheticEvent, newValue: number | number[]) => {
    if (!videoRef.current) return;
    
    setIsDraggingSlider(false);
    const video = videoRef.current;
    // newValue is already the actual time (converted from inverted in TimelineOverlay)
    const seekTime = Array.isArray(newValue) ? newValue[0] : newValue;
    if (!isFinite(seekTime) || seekTime < 0) return;
    
    if (archiveMetadata && archiveMetadata.manifests.length > 0) {
      let targetManifestIndex = -1;
      let targetLocalTime = 0;
      
      // Find the manifest that contains this seek time
      for (let i = 0; i < archiveMetadata.manifests.length; i++) {
        const manifest = archiveMetadata.manifests[i];
        const isAtEnd = seekTime >= manifest.end_time_seconds && i === archiveMetadata.manifests.length - 1;
        const isInRange = seekTime >= manifest.start_time_seconds && seekTime < manifest.end_time_seconds;
        
        if (isInRange || isAtEnd) {
          targetManifestIndex = i;
          targetLocalTime = seekTime - manifest.start_time_seconds;
          
          const manifestDuration = manifest.duration_seconds;
          targetLocalTime = Math.min(targetLocalTime, manifestDuration - 0.1);
          
          console.log(`[@EnhancedHLSPlayer] User seek: global ${seekTime.toFixed(1)}s -> manifest ${manifest.window_index} at ${targetLocalTime.toFixed(1)}s`);
          break;
        }
      }
      
      if (targetManifestIndex === -1) {
        console.warn(`[@EnhancedHLSPlayer] Seek time ${seekTime}s is in a gap (no chunk available) - finding nearest available chunk`);
        
        // Find nearest available chunk (forward first, then backward)
        let nearestIndex = -1;
        let minDistance = Infinity;
        
        for (let i = 0; i < archiveMetadata.manifests.length; i++) {
          const manifest = archiveMetadata.manifests[i];
          const distance = Math.abs(seekTime - manifest.start_time_seconds);
          if (distance < minDistance) {
            minDistance = distance;
            nearestIndex = i;
          }
        }
        
        if (nearestIndex !== -1) {
          targetManifestIndex = nearestIndex;
          const nearestManifest = archiveMetadata.manifests[nearestIndex];
          targetLocalTime = 0; // Start of nearest chunk
          console.log(`[@EnhancedHLSPlayer] Jumping to nearest chunk: manifest ${nearestManifest.window_index}`);
        } else {
          console.error('[@EnhancedHLSPlayer] No available chunks found');
          return;
        }
      }
      
      if (targetManifestIndex !== currentManifestIndex) {
        console.log(`[@EnhancedHLSPlayer] Switching from manifest ${currentManifestIndex + 1} to ${targetManifestIndex + 1}`);
        
        // Don't pause - just switch the chunk and the player will handle it
        setIsManualSeeking(true);
        setCurrentManifestIndex(targetManifestIndex);
        setPreloadedNextManifest(false);
        
        // Wait for new chunk to load, then seek to position
        setTimeout(() => {
          if (videoRef.current) {
            videoRef.current.currentTime = targetLocalTime;
            
            // Clear the manual seeking flag after seek completes
            setTimeout(() => {
              setIsManualSeeking(false);
            }, 100);
          }
        }, 1000);
      } else {
        video.currentTime = targetLocalTime;
      }
    } else {
      video.currentTime = seekTime;
    }
  }, [archiveMetadata, currentManifestIndex, videoRef]);

  const updateTimeTracking = useCallback((video: HTMLVideoElement) => {
    if (archiveMetadata && archiveMetadata.manifests.length > 0) {
      const currentManifest = archiveMetadata.manifests[currentManifestIndex];
      if (currentManifest) {
        const globalTime = currentManifest.start_time_seconds + video.currentTime;
        setGlobalCurrentTime(globalTime);
        
        if (onVideoTimeUpdate) {
          // Pass global clock time (seconds in day) to consumers for consistent archive lookups
          onVideoTimeUpdate(globalTime);
        }
        
        // Skip automatic chunk switching during manual seeks to prevent multiple jumps
        if (!isManualSeeking) {
          const progressRatio = video.currentTime / video.duration;
          if (progressRatio > 0.9 && !preloadedNextManifest) {
            const nextIndex = currentManifestIndex + 1;
            if (nextIndex < archiveMetadata.manifests.length) {
              console.log(`[@EnhancedHLSPlayer] Pre-loading next manifest (${nextIndex + 1}/${archiveMetadata.manifests.length})`);
              setPreloadedNextManifest(true);
            }
          }
          
          if (video.currentTime >= video.duration - 1) {
            const nextIndex = currentManifestIndex + 1;
            
            // If we've reached the last manifest (closest to "now"), pause instead of looping
            if (nextIndex >= archiveMetadata.manifests.length) {
              console.log(`[@EnhancedHLSPlayer] Reached the end of archive (now) - pausing playback`);
              video.pause();
            } else {
              console.log(`[@EnhancedHLSPlayer] Switching to manifest ${nextIndex + 1}`);
              setCurrentManifestIndex(nextIndex);
              setPreloadedNextManifest(false);
            }
          }
        }
      }
    } else {
      setGlobalCurrentTime(video.currentTime);
    }
  }, [archiveMetadata, currentManifestIndex, preloadedNextManifest, onVideoTimeUpdate, isManualSeeking]);

  const clearArchiveData = useCallback(() => {
    console.log('[@EnhancedHLSPlayer] Clearing archive metadata (switching to live)');
    setArchiveMetadata(null);
    setCurrentManifestIndex(0);
    setAvailableHours([]);
    setIsCheckingAvailability(false);
    setContinuousStartTime(0);
    setContinuousEndTime(0);
    setHasAttemptedLoad(false);
    setIsManualSeeking(false);
    setLastErrorTime(0);
    setErrorChunkIndices(new Set());
  }, []);

  return useMemo(() => ({
    archiveMetadata,
    currentManifestIndex,
    globalCurrentTime,
    preloadedNextManifest,
    isDraggingSlider,
    dragSliderValue,
    availableHours,
    isCheckingAvailability,
    continuousStartTime,
    continuousEndTime,
    hourMarks,
    errorChunkIndices,
    handleVideoError,
    handleSliderChange,
    handleSeek,
    updateTimeTracking,
    clearArchiveData,
    setCurrentManifestIndex,
    setPreloadedNextManifest,
  }), [
    archiveMetadata,
    currentManifestIndex,
    globalCurrentTime,
    preloadedNextManifest,
    isDraggingSlider,
    dragSliderValue,
    availableHours,
    isCheckingAvailability,
    continuousStartTime,
    continuousEndTime,
    hourMarks,
    errorChunkIndices,
    handleVideoError,
    handleSliderChange,
    handleSeek,
    updateTimeTracking,
    clearArchiveData,
  ]);
};
