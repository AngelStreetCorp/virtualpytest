import { useRef, useEffect, useState, useCallback } from 'react';
import { Box, Typography, Button, TextField, Paper, Grid, Chip } from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import RefreshIcon from '@mui/icons-material/Refresh';

/**
 * HLS Debug Page
 * 
 * Dedicated page for testing and debugging HLS streaming with improved configuration
 * and comprehensive logging.
 */
const HLSDebugPage: React.FC = () => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<any>(null);
  const [streamUrl, setStreamUrl] = useState('https://dev.virtualpytest.com/host/stream/capture1/segments/output.m3u8');
  const [streamError, setStreamError] = useState<string | null>(null);
  const [streamLoaded, setStreamLoaded] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [debugLogs, setDebugLogs] = useState<string[]>([]);
  const [hlsStats, setHlsStats] = useState<any>({});
  const [ffmpegStuck, setFfmpegStuck] = useState(false);
  const [segmentFailureCount, setSegmentFailureCount] = useState(0);
  const maxSegmentFailures = 10;

  const addDebugLog = useCallback((message: string) => {
    const timestamp = new Date().toLocaleTimeString();
    const logMessage = `[${timestamp}] ${message}`;
    console.log(logMessage);
    setDebugLogs(prev => [...prev.slice(-50), logMessage]); // Keep last 50 logs
  }, []);

  const cleanupStream = useCallback(() => {
    if (hlsRef.current) {
      try {
        hlsRef.current.destroy();
        addDebugLog('HLS instance destroyed');
      } catch (error) {
        addDebugLog(`Error destroying HLS instance: ${error}`);
      }
      hlsRef.current = null;
    }

    if (videoRef.current) {
      videoRef.current.pause();
      videoRef.current.src = '';
      videoRef.current.load();
    }

    setStreamLoaded(false);
    setStreamError(null);
    setIsPlaying(false);
    setHlsStats({});
    setSegmentFailureCount(0);
    setFfmpegStuck(false);
  }, [addDebugLog]);

  const tryNativePlayback = useCallback(async () => {
    if (!streamUrl || !videoRef.current) return false;

    addDebugLog('Trying native HTML5 playback');
    
    try {
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }

      const video = videoRef.current;

      const handleLoadedMetadata = () => {
        addDebugLog('Native playback loaded successfully');
        setStreamLoaded(true);
        setStreamError(null);
      };

      const handleError = (e: any) => {
        addDebugLog(`Native playback error: ${e}`);
        setStreamError('Native playback failed');
      };

      video.addEventListener('loadedmetadata', handleLoadedMetadata);
      video.addEventListener('error', handleError);

      video.src = streamUrl + (streamUrl.includes('?') ? '&' : '?') + 't=' + Date.now();
      video.load();

      return true;
    } catch (error) {
      addDebugLog(`Native playback setup failed: ${error}`);
      return false;
    }
  }, [streamUrl, addDebugLog]);

  const initializeStream = useCallback(async () => {
    if (ffmpegStuck) {
      addDebugLog('FFmpeg is stuck, refusing to initialize stream');
      return;
    }
    
    if (!streamUrl || !videoRef.current) {
      setStreamError('Stream URL or video element not available');
      return;
    }
    
    cleanupStream();
    addDebugLog(`Initializing HLS stream: ${streamUrl}`);
    
    try {
      const HLSModule = await import('hls.js');
      const HLS = HLSModule.default;
      
      if (!HLS.isSupported()) {
        addDebugLog('HLS.js not supported, trying native playback');
        await tryNativePlayback();
        return;
      }

      // Improved HLS configuration
      const hls = new HLS({
        enableWorker: false,
        lowLatencyMode: true,
        liveSyncDuration: 2,           // Stay 2 segments behind live edge
        liveMaxLatencyDuration: 5,     // Max 5 seconds latency before correction
        maxBufferLength: 3,            // 3 seconds of buffer
        maxMaxBufferLength: 6,         // Max 6 seconds buffer
        backBufferLength: 0,           // No back buffer
        maxBufferSize: 2 * 1000 * 1000, // 2MB buffer size
        maxBufferHole: 0.1,            // Fill gaps faster
        fragLoadingTimeOut: 5000,      // 5 second timeout for segments
        manifestLoadingTimeOut: 1000,  // 1 second timeout for manifest
        levelLoadingTimeOut: 3000,     // 3 second timeout for levels
        liveBackBufferLength: 0,       // No live back buffer
        liveDurationInfinity: true,    // Allow infinite live duration
        startFragPrefetch: true,       // Prefetch fragments
      });

      hlsRef.current = hls;
      addDebugLog('HLS instance created with improved configuration');

      // Event handlers with detailed logging
      hls.on(HLS.Events.MANIFEST_PARSED, (_, data) => {
        addDebugLog(`Manifest parsed - Levels: ${data.levels.length}, Audio tracks: ${data.audioTracks.length}`);
        setStreamLoaded(true);
        setStreamError(null);
        setSegmentFailureCount(0);
        setFfmpegStuck(false);
      });

      hls.on(HLS.Events.LEVEL_LOADED, (_, data) => {
        addDebugLog(`Level loaded - Level: ${data.level}, Segments: ${data.details.fragments.length}, Live: ${data.details.live}`);
      });

      hls.on(HLS.Events.FRAG_LOADED, (_, data) => {
        addDebugLog(`Fragment loaded - URL: ${data.frag.url}, Duration: ${data.frag.duration}s`);
        setSegmentFailureCount(0); // Reset on successful load
        
        // Update stats
        setHlsStats((prev: any) => ({
          ...prev,
          lastFragmentUrl: data.frag.url,
          lastFragmentDuration: data.frag.duration,
          totalFragmentsLoaded: (prev.totalFragmentsLoaded || 0) + 1
        }));
      });

      hls.on(HLS.Events.FRAG_PARSING_USERDATA, (_, data: any) => {
        addDebugLog(`Fragment parsing - Type: ${data.type}, Start: ${data.startPTS}, End: ${data.endPTS}`);
      });

      hls.on(HLS.Events.ERROR, (_, data) => {
        const errorMsg = `HLS Error - Type: ${data.type}, Details: ${data.details}, Fatal: ${data.fatal}`;
        addDebugLog(errorMsg);

        // Ignore buffer stall errors - they are temporary
        if (data.details === 'bufferStalledError') {
          addDebugLog('Buffer stall detected, ignoring (will self-recover)');
          return;
        }

        // Detailed fragment load error handling
        if (data.details === 'fragLoadError') {
          const responseCode = data.response?.code;
          const segmentUrl = data.frag?.url;
          const networkDetails = data.response ? `Code: ${responseCode}, Text: ${data.response.text}` : 'No response data';
          
          addDebugLog(`Fragment load error - URL: ${segmentUrl}, ${networkDetails}`);
          
          // Only count confirmed 404s as segment failures
          if (responseCode === 404) {
            setSegmentFailureCount(prev => {
              if (prev >= maxSegmentFailures) {
                return prev;
              }
              
              const newCount = prev + 1;
              addDebugLog(`Confirmed 404 error (${newCount}/${maxSegmentFailures}): ${segmentUrl}`);
              
              if (newCount >= maxSegmentFailures) {
                addDebugLog('FFmpeg appears stuck - too many consecutive segment failures');
                setFfmpegStuck(true);
                setStreamError('FFmpeg appears stuck. Stream restart required.');
                
                // Cleanup HLS instance
                setTimeout(() => {
                  if (hlsRef.current) {
                    try {
                      hlsRef.current.destroy();
                      hlsRef.current = null;
                      addDebugLog('HLS instance destroyed due to FFmpeg stuck');
                    } catch (error) {
                      addDebugLog(`Error destroying HLS on FFmpeg stuck: ${error}`);
                    }
                  }
                }, 100);
              }
              
              return newCount;
            });
          } else {
            addDebugLog(`Fragment load error but not 404 (code: ${responseCode}) - ignoring for segment failure count`);
          }
          
          return;
        }

        if (data.fatal) {
          addDebugLog('Fatal HLS error, trying native playback');
          setTimeout(() => tryNativePlayback(), 500);
        } else {
          if (data.details === 'fragParsingError') {
            addDebugLog('Fragment parsing error, attempting HLS recovery');
            try {
              hls.startLoad();
            } catch (recoveryError) {
              addDebugLog(`HLS recovery failed: ${recoveryError}`);
              setStreamError('Stream connection issues. Retrying...');
            }
          }
        }
      });

      // Load source with cache-busting
      const sourceUrl = `${streamUrl}?t=${Date.now()}`;
      addDebugLog(`Loading source: ${sourceUrl}`);
      hls.loadSource(sourceUrl);
      hls.attachMedia(videoRef.current);

    } catch (error: any) {
      addDebugLog(`Stream initialization failed: ${error.message}`);
      setStreamError(`Stream initialization failed: ${error.message}`);
    }
  }, [streamUrl, cleanupStream, tryNativePlayback, ffmpegStuck, addDebugLog]);

  const handlePlay = useCallback(() => {
    if (videoRef.current) {
      videoRef.current.play().then(() => {
        setIsPlaying(true);
        addDebugLog('Video playback started');
      }).catch(err => {
        addDebugLog(`Play failed: ${err.message}`);
      });
    }
  }, [addDebugLog]);

  const handleStop = useCallback(() => {
    if (videoRef.current) {
      videoRef.current.pause();
      setIsPlaying(false);
      addDebugLog('Video playback stopped');
    }
  }, [addDebugLog]);

  const handleRefresh = useCallback(() => {
    addDebugLog('Refreshing stream...');
    setDebugLogs([]);
    initializeStream();
  }, [initializeStream, addDebugLog]);

  const clearLogs = useCallback(() => {
    setDebugLogs([]);
  }, []);

  // Update stats periodically
  useEffect(() => {
    const interval = setInterval(() => {
      if (hlsRef.current && videoRef.current) {
        const hls = hlsRef.current;
        const video = videoRef.current;
        
        setHlsStats((prev: any) => ({
          ...prev,
          currentTime: video.currentTime,
          duration: video.duration,
          buffered: video.buffered.length > 0 ? video.buffered.end(0) : 0,
          liveSyncPosition: hls.liveSyncPosition,
          latency: hls.liveSyncPosition ? hls.liveSyncPosition - video.currentTime : null,
          loadLevel: hls.loadLevel,
          currentLevel: hls.currentLevel,
        }));
      }
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  return (
    <Box sx={{ p: 3, maxWidth: 1400, margin: '0 auto' }}>
      <Typography variant="h4" gutterBottom>
        HLS Debug Page
      </Typography>
      
      <Grid container spacing={3}>
        {/* Video Player */}
        <Grid item xs={12} md={8}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Video Player
            </Typography>
            
            <Box sx={{ mb: 2 }}>
              <TextField
                fullWidth
                label="Stream URL"
                value={streamUrl}
                onChange={(e) => setStreamUrl(e.target.value)}
                variant="outlined"
                size="small"
              />
            </Box>

            <Box sx={{ mb: 2, display: 'flex', gap: 1 }}>
              <Button
                variant="contained"
                startIcon={<PlayArrowIcon />}
                onClick={handlePlay}
                disabled={!streamLoaded || isPlaying}
              >
                Play
              </Button>
              <Button
                variant="outlined"
                startIcon={<StopIcon />}
                onClick={handleStop}
                disabled={!isPlaying}
              >
                Stop
              </Button>
              <Button
                variant="outlined"
                startIcon={<RefreshIcon />}
                onClick={handleRefresh}
              >
                Refresh
              </Button>
            </Box>

            <Box
              sx={{
                position: 'relative',
                width: '100%',
                height: 400,
                backgroundColor: '#000',
                borderRadius: 1,
                overflow: 'hidden',
              }}
            >
              <video
                ref={videoRef}
                style={{
                  width: '100%',
                  height: '100%',
                  objectFit: 'contain',
                }}
                controls
                muted
                playsInline
              />
              
              {streamError && (
                <Box
                  sx={{
                    position: 'absolute',
                    top: '50%',
                    left: '50%',
                    transform: 'translate(-50%, -50%)',
                    textAlign: 'center',
                    color: 'white',
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    p: 2,
                    borderRadius: 1,
                  }}
                >
                  <Typography variant="body2">{streamError}</Typography>
                  {ffmpegStuck && (
                    <Chip 
                      label={`Segment failures: ${segmentFailureCount}/${maxSegmentFailures}`}
                      color="error"
                      size="small"
                      sx={{ mt: 1 }}
                    />
                  )}
                </Box>
              )}
            </Box>
          </Paper>
        </Grid>

        {/* Stats Panel */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2, mb: 2 }}>
            <Typography variant="h6" gutterBottom>
              Stream Stats
            </Typography>
            
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2 }}>
              <Chip 
                label={streamLoaded ? 'Loaded' : 'Not Loaded'} 
                color={streamLoaded ? 'success' : 'default'}
                size="small"
              />
              <Chip 
                label={isPlaying ? 'Playing' : 'Paused'} 
                color={isPlaying ? 'primary' : 'default'}
                size="small"
              />
              {ffmpegStuck && (
                <Chip 
                  label="FFmpeg Stuck" 
                  color="error"
                  size="small"
                />
              )}
            </Box>

            <Typography variant="body2" component="div" sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>
              <div>Current Time: {hlsStats.currentTime?.toFixed(2) || 'N/A'}s</div>
              <div>Duration: {hlsStats.duration?.toFixed(2) || 'N/A'}s</div>
              <div>Buffered: {hlsStats.buffered?.toFixed(2) || 'N/A'}s</div>
              <div>Live Position: {hlsStats.liveSyncPosition?.toFixed(2) || 'N/A'}s</div>
              <div>Latency: {hlsStats.latency?.toFixed(2) || 'N/A'}s</div>
              <div>Load Level: {hlsStats.loadLevel ?? 'N/A'}</div>
              <div>Current Level: {hlsStats.currentLevel ?? 'N/A'}</div>
              <div>Fragments Loaded: {hlsStats.totalFragmentsLoaded || 0}</div>
              <div>Segment Failures: {segmentFailureCount}/{maxSegmentFailures}</div>
            </Typography>
          </Paper>

          {/* Debug Logs */}
          <Paper sx={{ p: 2 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
              <Typography variant="h6">
                Debug Logs ({debugLogs.length})
              </Typography>
              <Button size="small" onClick={clearLogs}>
                Clear
              </Button>
            </Box>
            
            <Box
              sx={{
                height: 300,
                overflow: 'auto',
                backgroundColor: '#f5f5f5',
                p: 1,
                borderRadius: 1,
                fontFamily: 'monospace',
                fontSize: '0.75rem',
              }}
            >
              {debugLogs.map((log, index) => (
                <div key={index} style={{ marginBottom: 2 }}>
                  {log}
                </div>
              ))}
              {debugLogs.length === 0 && (
                <Typography variant="body2" color="text.secondary">
                  No logs yet. Click Refresh to start streaming.
                </Typography>
              )}
            </Box>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
};

export default HLSDebugPage;
