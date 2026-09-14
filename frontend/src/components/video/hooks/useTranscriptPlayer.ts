import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { TranscriptData, TranscriptDataLegacy, TranscriptData10Min, TranscriptSegment, ArchiveMetadata, TimedSegment } from '../EnhancedHLSPlayer.types';
import { Host } from '../../../types/common/Host_Types';
import { 
  buildHostUrl, 
  buildAudioMp3Url,
  buildDubbedAudioUrl,
  buildTranscriptChunkUrl,
  buildTranscriptManifestUrl
} from '../../../utils/buildUrlUtils';

interface UseTranscriptPlayerProps {
  isLiveMode: boolean;
  archiveMetadata: ArchiveMetadata | null;
  currentManifestIndex: number;
  globalCurrentTime: number;
  providedStreamUrl?: string;
  hookStreamUrl?: string;
  host?: Host;
  deviceId: string;
}

// Type guard to check if transcript is new 10-minute format
const isTranscriptData10Min = (data: TranscriptData): data is TranscriptData10Min => {
  return 'chunk_duration_minutes' in data && 'mp3_file' in data;
};

// Helper to normalize transcript data to legacy format for backward compatibility
const normalizeTranscriptData = (data: TranscriptData): TranscriptDataLegacy => {
  if (isTranscriptData10Min(data)) {
    // Convert new 10-min format to legacy segments format
    // Create a single segment representing the entire 10-minute chunk
    const chunkStartSeconds = (data.hour * 3600) + (data.chunk_index * 600);
    
    const segment: TranscriptSegment = {
      segment_num: data.chunk_index,
      relative_seconds: chunkStartSeconds,
      language: data.language,
      transcript: data.transcript,
      confidence: data.confidence,
      manifest_window: data.hour,
      translations: data.translations,
    };
    
    return {
      capture_folder: data.capture_folder,
      sample_interval_seconds: 600, // 10 minutes
      total_duration_seconds: 600,
      segments: [segment],
      last_update: data.timestamp,
      total_samples: 1,
    };
  }
  
  // Already in legacy format
  return data as TranscriptDataLegacy;
};

export const useTranscriptPlayer = ({
  isLiveMode,
  archiveMetadata,
  currentManifestIndex,
  globalCurrentTime,
  providedStreamUrl,
  hookStreamUrl,
  host,
  deviceId,
}: UseTranscriptPlayerProps) => {
  const [transcriptData, setTranscriptData] = useState<TranscriptDataLegacy | null>(null);
  const [rawTranscriptData, setRawTranscriptData] = useState<TranscriptData10Min | null>(null);  // Keep raw 10-min data
  const [currentTranscript, setCurrentTranscript] = useState<TranscriptSegment | null>(null);
  const [currentTimedSegment, setCurrentTimedSegment] = useState<TimedSegment | null>(null);
  const [selectedTranscriptLanguage, setSelectedTranscriptLanguage] = useState<string>('original');
  
  const [availableLanguages, setAvailableLanguages] = useState<string[]>(['original']);
  const [availableDubbedLanguages, setAvailableDubbedLanguages] = useState<string[]>([]);
  const [isTranslating, setIsTranslating] = useState(false);
  const [hasMp3, setHasMp3] = useState(false);
  const [mp3Url, setMp3Url] = useState<string | null>(null);
  const [dubbedAudioUrl, setDubbedAudioUrl] = useState<string | null>(null);
  
  // Prevent duplicate language change requests
  const languageChangeInProgressRef = useRef<string | null>(null);
  
  const clearTranscriptState = useCallback(() => {
    setTranscriptData(null);
    setRawTranscriptData(null);
    setCurrentTranscript(null);
    setCurrentTimedSegment(null);
  }, []);

  // Clear transcript and dubbed audio when switching to live mode
  useEffect(() => {
    if (isLiveMode) {
      console.log(`[@useTranscriptPlayer] Live mode detected - clearing transcript and dubbed audio`);
      clearTranscriptState();
      setDubbedAudioUrl(null);
      setSelectedTranscriptLanguage('original');
      setAvailableLanguages(['original']);
      setAvailableDubbedLanguages([]);
      setHasMp3(false);
      setMp3Url(null);
    }
  }, [isLiveMode, clearTranscriptState]);

  // Check if device is VNC (no audio capture, so no transcripts)
  const isVncDevice = host?.devices?.some(
    (d: any) => d?.device_id === deviceId && d?.device_model === 'host_vnc'
  );

  useEffect(() => {
    if (!isLiveMode) {
      if (!archiveMetadata || archiveMetadata.manifests.length === 0) {
        clearTranscriptState();
        setHasMp3(false);
        setMp3Url(null);
        return;
      }
      // VNC devices have no audio - skip transcript fetching entirely
      if (isVncDevice) {
        clearTranscriptState();
        setHasMp3(false);
        setMp3Url(null);
        return;
      }

      const currentManifest = archiveMetadata.manifests[currentManifestIndex];
      if (currentManifest) {
        const hour = currentManifest.window_index;
        const chunkIndex = currentManifest.chunk_index;

        // Check transcript manifest first to avoid 404s
        const manifestUrl = buildTranscriptManifestUrl(host, deviceId);
        
        console.log(`[@useTranscriptPlayer] Checking transcript availability from manifest...`);
        
        fetch(manifestUrl)
          .then(res => {
            if (!res.ok) {
              console.log(`[@useTranscriptPlayer] No transcript manifest available`);
              clearTranscriptState();
              return null;
            }
            return res.json();
          })
          .then((manifest) => {
            if (!manifest || !manifest.chunks) {
              clearTranscriptState();
              return;
            }
            
            // Filter to chunks from last 24h only (prevents showing old transcripts)
            const now = Date.now();
            const chunks24h = manifest.chunks.filter((chunk: any) => {
              if (!chunk.timestamp) return false;
              const chunkTime = new Date(chunk.timestamp).getTime();
              return (now - chunkTime) < 24 * 60 * 60 * 1000; // 24h in ms
            });
            
            // Check if transcript exists for this hour/chunk
            const chunkInfo = chunks24h.find(
              (chunk: any) => chunk.hour === hour && chunk.chunk_index === chunkIndex
            );
            
            if (!chunkInfo || !chunkInfo.has_transcript) {
              console.log(`[@useTranscriptPlayer] No transcript available for hour ${hour}, chunk ${chunkIndex} (checked manifest)`);
              clearTranscriptState();
              setHasMp3(false);
              setMp3Url(null);
              return;
            }
            
            // If manifest explicitly indicates no timed segments, avoid loading transcript
            if (chunkInfo.has_timed_segments === false || chunkInfo.segment_count === 0) {
              console.log(`[@useTranscriptPlayer] Transcript has no timed segments for hour ${hour}, chunk ${chunkIndex} - skipping display`);
              clearTranscriptState();
              setHasMp3(false);
              setMp3Url(null);
              return;
            }
            
            // Extract has_mp3 and build mp3Url if available
            const hasMp3Flag = chunkInfo.has_mp3 === true;
            setHasMp3(hasMp3Flag);
            if (hasMp3Flag) {
              const mp3Path = buildAudioMp3Url(host, deviceId, hour, chunkIndex);
              setMp3Url(mp3Path);
            } else {
              setMp3Url(null);
            }
            
            // Extract available languages from manifest
            const languages = chunkInfo.available_languages || ['original'];
            const dubbedLanguages = chunkInfo.available_dubbed_languages || [];
            setAvailableLanguages(languages);
            setAvailableDubbedLanguages(dubbedLanguages);
            console.log(`[@useTranscriptPlayer] Available languages:`, languages);
            console.log(`[@useTranscriptPlayer] Available dubbed audio:`, dubbedLanguages);
            
            // Manifest has metadata only - load actual chunk JSON for segments
            console.log(`[@useTranscriptPlayer] Loading transcript chunk with segments (hour ${hour}, chunk ${chunkIndex})`);
            const transcriptUrl = buildTranscriptChunkUrl(host, deviceId, hour, chunkIndex, 'original');
            
            fetch(transcriptUrl)
              .then(res => {
                if (!res.ok) throw new Error(`Transcript chunk not found`);
                return res.json();
              })
              .then((data) => {
                const transcript: TranscriptData10Min = {
                  ...data,
                  hour: hour,
                  chunk_index: chunkIndex,
                };
                
                if (!transcript.transcript) {
                  console.log(`[@useTranscriptPlayer] No transcript text in chunk ${chunkIndex}`);
                  clearTranscriptState();
                  return;
                }
                
                // Store raw 10-min data for timed segment access
                setRawTranscriptData(transcript);
                
                // Show segment summary
                const segmentCount = transcript.segments?.length || 0;
                if (segmentCount > 0 && transcript.segments) {
                  const firstSeg = transcript.segments[0];
                  const lastSeg = transcript.segments[segmentCount - 1];
                  console.log(`📚 Loaded ${segmentCount} segments: ${firstSeg.start.toFixed(1)}s-${lastSeg.end.toFixed(1)}s | First: "${firstSeg.text.substring(0, 30)}..."`);
                } else {
                  console.log(`[@useTranscriptPlayer] ⚠️ Chunk has no timed segments`);
                }
                
                const normalizedData = normalizeTranscriptData(transcript);
                
                console.log(`[@useTranscriptPlayer] ✅ Transcript loaded:`, {
                  language: transcript.language,
                  confidence: transcript.confidence,
                  textLength: transcript.transcript.length,
                  segmentCount: segmentCount,
                  preview: transcript.transcript.substring(0, 100)
                });
                
                setTranscriptData(normalizedData);
              })
              .catch((error) => {
                console.error(`[@useTranscriptPlayer] Failed to load transcript:`, error.message);
                clearTranscriptState();
              });
          })
          .catch((error) => {
            console.log(`[@useTranscriptPlayer] Error loading transcript:`, error.message);
            clearTranscriptState();
          });
      }
    }
  }, [isLiveMode, archiveMetadata, currentManifestIndex, providedStreamUrl, hookStreamUrl, deviceId, host, isVncDevice, clearTranscriptState]);

  useEffect(() => {
    if (transcriptData && transcriptData.segments && transcriptData.segments.length > 0) {
      // For 10-minute chunks (1 segment), show transcript for entire chunk duration
      // For legacy 6-second segments, find closest segment
      const isLongChunk = (transcriptData.sample_interval_seconds ?? 0) >= 600; // 10 minutes
      
      if (isLongChunk && transcriptData.segments.length === 1) {
        // NEW format: Show transcript for entire 10-minute chunk
        // Since we're playing a single 10-min chunk, transcript is always visible during playback
        const segment = transcriptData.segments[0];
        const chunkStartTime = segment.relative_seconds;
        const chunkEndTime = chunkStartTime + 600; // 10 minutes
        
        // Check if current time is within this chunk
        if (globalCurrentTime >= chunkStartTime && globalCurrentTime < chunkEndTime) {
          setCurrentTranscript(segment);
        } else {
          console.log(`[@useTranscriptPlayer] Time mismatch: globalCurrentTime=${globalCurrentTime.toFixed(1)}s, chunk range=${chunkStartTime}-${chunkEndTime}`);
          setCurrentTranscript(null);
        }
      } else {
        // LEGACY format: Find closest 6-second segment
        const closestSegment = transcriptData.segments.reduce((closest: TranscriptSegment, segment: TranscriptSegment) => {
          const timeDiff = Math.abs(segment.relative_seconds - globalCurrentTime);
          const closestDiff = closest ? Math.abs(closest.relative_seconds - globalCurrentTime) : Infinity;
          return timeDiff < closestDiff ? segment : closest;
        }, transcriptData.segments[0]);
        
        if (Math.abs(closestSegment.relative_seconds - globalCurrentTime) < 6) {
          setCurrentTranscript(closestSegment);
        } else {
          setCurrentTranscript(null);
        }
      }
    } else {
      setCurrentTranscript(null);
    }
  }, [transcriptData, globalCurrentTime]);
  
  // Find current timed segment based on video playback time (per-minute granularity)
  useEffect(() => {
    if (!rawTranscriptData || !rawTranscriptData.segments || rawTranscriptData.segments.length === 0) {
      setCurrentTimedSegment(null);
      return;
    }
    
    if (!archiveMetadata || archiveMetadata.manifests.length === 0) {
      setCurrentTimedSegment(null);
      return;
    }
    
    const currentManifest = archiveMetadata.manifests[currentManifestIndex];
    if (!currentManifest) {
      setCurrentTimedSegment(null);
      return;
    }
    
    // Local time within the 10-minute chunk (0-600 seconds)
    const localTime = globalCurrentTime - currentManifest.start_time_seconds;
    
    // Find active segment at current time (no per-minute filtering for incomplete chunks)
    const activeSegment = rawTranscriptData.segments.find(
      seg => localTime >= seg.start && localTime < seg.end
    );
    
    if (activeSegment) {
      setCurrentTimedSegment(activeSegment);
      console.log(`📝 ${localTime.toFixed(1)}s | seg[${activeSegment.start.toFixed(1)}-${activeSegment.end.toFixed(1)}] | "${activeSegment.text.substring(0, 40)}..."`);
    } else {
      setCurrentTimedSegment(null);
      
      // Log if no segment found (useful for debugging incomplete chunks)
      const segmentRange = rawTranscriptData.segments.length > 0 
        ? `${rawTranscriptData.segments[0].start.toFixed(1)}-${rawTranscriptData.segments[rawTranscriptData.segments.length - 1].end.toFixed(1)}s`
        : 'none';
      if (rawTranscriptData.segments.length === 0 || localTime < rawTranscriptData.segments[0].start || localTime > rawTranscriptData.segments[rawTranscriptData.segments.length - 1].end) {
        console.log(`⏹️ ${localTime.toFixed(1)}s | Outside segment range: ${segmentRange} (${rawTranscriptData.segments.length} segments)`);
      }
    }
  }, [rawTranscriptData, globalCurrentTime, archiveMetadata, currentManifestIndex]);

  // Translation progress removed - we now translate the full transcript as ONE block (fast!)
  
  const loadTranscriptForLanguage = useCallback(async (hour: number, chunkIndex: number, language: string, retries = 3) => {
    const transcriptUrl = buildTranscriptChunkUrl(host, deviceId, hour, chunkIndex, language);
    
    for (let attempt = 1; attempt <= retries; attempt++) {
      try {
        const response = await fetch(transcriptUrl);
        if (!response.ok) {
          if (attempt < retries) {
            console.log(`[@useTranscriptPlayer] Transcript not ready yet (attempt ${attempt}/${retries}), retrying in 500ms...`);
            await new Promise(resolve => setTimeout(resolve, 500));
            continue;
          }
          throw new Error(`Failed to load ${language} transcript after ${retries} attempts`);
        }
        
        const data = await response.json();
        const transcript: TranscriptData10Min = { ...data, hour, chunk_index: chunkIndex };
        
        setRawTranscriptData(transcript);
        setTranscriptData(normalizeTranscriptData(transcript));
        console.log(`[@useTranscriptPlayer] ✅ Loaded ${language} transcript (attempt ${attempt})`);
        return;
      } catch (error) {
        if (attempt === retries) {
          console.error(`[@useTranscriptPlayer] Error loading ${language}:`, error);
          throw error;
        }
      }
    }
  }, [deviceId, host]);

  const handleLanguageChange = useCallback(async (language: string) => {
    // GUARD: Only allow language changes in archive mode (not live mode)
    if (isLiveMode) {
      console.log(`[@useTranscriptPlayer] 🛑 Language change blocked - only available in Last 24h mode`);
      return;
    }
    
    // Prevent duplicate requests for the same language
    if (languageChangeInProgressRef.current === language) {
      console.log(`[@useTranscriptPlayer] 🛑 Language change already in progress for ${language}, skipping duplicate request`);
      return;
    }
    
    setSelectedTranscriptLanguage(language);
    
    if (!archiveMetadata?.manifests.length) return;
    const currentManifest = archiveMetadata.manifests[currentManifestIndex];
    if (!currentManifest) return;

    const hour = currentManifest.window_index;
    const chunkIndex = currentManifest.chunk_index;

    // Mark language change as in progress
    languageChangeInProgressRef.current = language;
    setIsTranslating(true);
    
    try {
      if (language === 'original') {
        // Load original transcript directly
        await loadTranscriptForLanguage(hour, chunkIndex, language);
      } else {
        // For translations, trigger translation API first
        if (!host) {
          console.error(`[@useTranscriptPlayer] Host required for translation`);
          return;
        }
        
        console.log(`[@useTranscriptPlayer] Starting translation to ${language}...`);
        const originalUrl = buildTranscriptChunkUrl(host, deviceId, hour, chunkIndex, 'original');
        const apiUrl = buildHostUrl(host, 'host/transcript/translate-chunk');
        const response = await fetch(apiUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chunk_url: originalUrl, language })
        });
        
        const result = await response.json();
        
        if (result.success) {
          console.log(`[@useTranscriptPlayer] Translation completed in ${result.processing_time?.toFixed(1)}s, loading transcript...`);
          // NOW load the translated transcript
          await loadTranscriptForLanguage(hour, chunkIndex, language);
        } else {
          console.error(`[@useTranscriptPlayer] Translation failed:`, result.error);
          return;
        }
      }

      console.log(`[@useTranscriptPlayer] ✅ Transcript loaded successfully, proceeding to audio...`);

      if (language === 'original') {
        setDubbedAudioUrl(null);
      } else {
        const url10min = buildDubbedAudioUrl(host, deviceId, hour, chunkIndex, language);
        console.log(`[@useTranscriptPlayer] Checking dubbed audio:`, url10min);
        
        const audioCheck = await fetch(url10min, { method: 'HEAD' }).catch(() => ({ ok: false }));
        
        if (audioCheck.ok) {
          console.log(`[@useTranscriptPlayer] ✅ Dubbed audio exists (cached)`);
          setDubbedAudioUrl(url10min);
        } else if (host) {
          const apiUrl = buildHostUrl(host, 'host/transcript/generate-dubbed-audio');
          console.log(`[@useTranscriptPlayer] 🎤 Generating dubbed audio via API (404 is expected - checking cache first)...`);
          
          const response = await fetch(apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_id: deviceId, hour, chunk_index: chunkIndex, language })
          }).catch(err => {
            console.error(`[@useTranscriptPlayer] API request failed:`, err);
            return null;
          });
          
          if (response && response.ok) {
            const result = await response.json();
            
            if (result.success && result.url) {
              const cleanUrl = result.url.startsWith('/') ? result.url.slice(1) : result.url;
              const finalUrl = buildHostUrl(host, cleanUrl);
              console.log(`[@useTranscriptPlayer] ✅ Dubbed audio generated, waiting for file to be ready...`);
              
              // Wait for the file to be fully written to disk before setting URL
              // This prevents the audio element from trying to load before the file is ready
              await new Promise(resolve => setTimeout(resolve, 500));
              
              // Verify the file is now accessible with retry
              let fileReady = false;
              for (let i = 0; i < 3; i++) {
                const verifyCheck = await fetch(finalUrl, { method: 'HEAD' }).catch(() => ({ ok: false }));
                if (verifyCheck.ok) {
                  fileReady = true;
                  console.log(`[@useTranscriptPlayer] ✅ Audio file verified and ready to play`);
                  break;
                }
                console.log(`[@useTranscriptPlayer] Audio file not ready yet, retrying... (${i + 1}/3)`);
                await new Promise(resolve => setTimeout(resolve, 300));
              }
              
              if (fileReady) {
                setDubbedAudioUrl(finalUrl);
              } else {
                console.error(`[@useTranscriptPlayer] Audio file not accessible after retries`);
                setDubbedAudioUrl(null);
              }
            } else {
              console.error(`[@useTranscriptPlayer] API returned error:`, result);
              setDubbedAudioUrl(null);
            }
          } else {
            console.error(`[@useTranscriptPlayer] API request failed with status:`, response?.status);
            setDubbedAudioUrl(null);
          }
        } else {
          setDubbedAudioUrl(null);
        }
      }
    } catch (error) {
      console.error(`[@useTranscriptPlayer] Error:`, error);
    } finally {
      setIsTranslating(false);
      languageChangeInProgressRef.current = null; // Clear the guard
    }
  }, [isLiveMode, archiveMetadata, currentManifestIndex, loadTranscriptForLanguage, host, deviceId]);

  const getCurrentTranscriptText = useCallback(() => {
    // New 10-minute format: only show text when a timed segment is active
    if (rawTranscriptData) {
      if (rawTranscriptData.segments && rawTranscriptData.segments.length > 0) {
        return currentTimedSegment?.text || '';
      }
      // If no timed segments in 10-min data, show nothing (avoid stale full-chunk text)
      return '';
    }
    // Legacy format fallback
    if (currentTranscript) {
      return currentTranscript.enhanced_transcript || currentTranscript.transcript;
    }
    return '';
  }, [rawTranscriptData, currentTranscript, currentTimedSegment]);

  const clearTranscriptData = useCallback(() => {
    clearTranscriptState();
  }, [clearTranscriptState]);

  return useMemo(() => ({
    transcriptData,
    currentTranscript,
    selectedLanguage: selectedTranscriptLanguage, // Unified language (same for both transcript and audio)
    availableLanguages,
    availableDubbedLanguages,
    isTranslating,
    handleLanguageChange, // Unified handler for both transcript and audio
    getCurrentTranscriptText,
    clearTranscriptData,
    hasMp3,
    mp3Url,
    dubbedAudioUrl,
  }), [
    transcriptData,
    currentTranscript,
    selectedTranscriptLanguage,
    availableLanguages,
    availableDubbedLanguages,
    isTranslating,
    handleLanguageChange,
    getCurrentTranscriptText,
    clearTranscriptData,
    hasMp3,
    mp3Url,
    dubbedAudioUrl,
  ]);
};
