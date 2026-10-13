import {
  Alert,
  Box,
  Button,
  CircularProgress,
  MenuItem,
  TextField,
  Typography,
} from '@mui/material';
import React, { useCallback, useEffect, useState } from 'react';

import { useControllerApi } from '../../../hooks/controller/useControllerApi';
import { Host } from '../../../types/common/Host_Types';
import { api } from '../../../utils/apiClient';
import { buildServerUrlWithParams } from '../../../utils/buildUrlUtils';

// TASK-31: source switcher for the stream-only device models. rtsp_video takes any
// rtsp:// / https:// (HLS or video file) / YouTube link; local_video plays a file
// from the host's video folder or downloads one there. The host writes the override
// and vpt-stream restarts only this device's ffmpeg (same path as the SD/HD switch).

interface StreamSourceRemoteProps {
  host: Host;
  deviceId?: string;
  deviceModel: 'rtsp_video' | 'local_video';
  isCollapsed: boolean;
  sx?: any;
}

interface SourceStatus {
  source_url?: string | null;
  youtube_url?: string | null;
  // Video vpt-stream is on for a YouTube link: "<watch url>" or "<watch url> 3/9" (playlist).
  youtube_now_playing?: string | null;
  loop?: boolean;
}

interface VideoFile {
  name: string;
  path: string;
  size: number;
}

// A video (watch?v=, youtu.be/, shorts/) or a playlist (any link with list=): vpt-stream
// plays a playlist's videos in order and loops it.
const YOUTUBE_RE = /^https?:\/\/(www\.|m\.|music\.)?(youtube\.com|youtu\.be)\//i;

const formatSize = (bytes: number) =>
  bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.round(bytes / 1e6)} MB`;

export const StreamSourceRemote = React.memo(function StreamSourceRemote({
  host,
  deviceId,
  deviceModel,
  isCollapsed,
  sx = {},
}: StreamSourceRemoteProps) {
  const { postToHost } = useControllerApi(host, deviceId);
  const [status, setStatus] = useState<SourceStatus | null>(null);
  const [videos, setVideos] = useState<VideoFile[]>([]);
  const [url, setUrl] = useState('');
  const [selectedPath, setSelectedPath] = useState('');
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!deviceId) return;
    try {
      const statusResult = await api.get<{ status: SourceStatus }>(
        buildServerUrlWithParams('/server/av/status', { host_name: host.host_name, device_id: deviceId }),
      );
      setStatus(statusResult.status);
      if (deviceModel === 'local_video') {
        const listResult = await api.get<{ videos: VideoFile[] }>(
          buildServerUrlWithParams('/server/av/listVideos', { host_name: host.host_name, device_id: deviceId }),
        );
        setVideos(listResult.videos);
        setSelectedPath((current) => current || statusResult.status.source_url || '');
      }
    } catch (requestError: any) {
      setError(requestError?.message || 'Failed to read the current source');
    }
  }, [host.host_name, deviceId, deviceModel]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const run = useCallback(
    async (label: string, path: string, payload: Record<string, string | number>) => {
      setPending(label);
      setError(null);
      setMessage(null);
      try {
        await postToHost(path, payload, { includeDeviceId: true });
        setMessage('Switched. The stream restarts in a few seconds.');
        setUrl('');
        await refresh();
      } catch (requestError: any) {
        setError(requestError?.message || `${label} failed`);
      } finally {
        setPending(null);
      }
    },
    [postToHost, refresh],
  );

  const applyUrl = () => {
    const value = url.trim();
    if (!value) return;
    const payload: Record<string, string> = { url: value };
    if (YOUTUBE_RE.test(value)) payload.youtube_url = value;
    run('Apply', '/server/av/setUrl', payload);
  };

  const current = status?.youtube_url || status?.source_url || '—';
  const busy = pending !== null;

  return (
    <Box
      sx={{
        ...sx,
        display: 'flex',
        flexDirection: 'column',
        gap: 1.5,
        p: isCollapsed ? 1 : 1.5,
        overflow: 'auto',
      }}
    >
      {error && <Alert severity="error">{error}</Alert>}
      {message && <Alert severity="success">{message}</Alert>}

      <Box>
        <Typography variant="caption" color="textSecondary">
          Now playing
        </Typography>
        <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>
          {current}
        </Typography>
        {status?.youtube_now_playing && status.youtube_now_playing !== current && (
          <Typography variant="caption" color="textSecondary" sx={{ wordBreak: 'break-all' }}>
            Video: {status.youtube_now_playing}
          </Typography>
        )}
      </Box>

      {deviceModel === 'rtsp_video' ? (
        <>
          <TextField
            size="small"
            label="Source URL"
            placeholder="rtsp://…, https://….m3u8, YouTube video or playlist link"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && applyUrl()}
            disabled={busy}
            fullWidth
          />
          <Button variant="contained" size="small" onClick={applyUrl} disabled={busy || !url.trim()}>
            {pending === 'Apply' ? <CircularProgress size={18} /> : 'Apply'}
          </Button>
        </>
      ) : (
        <>
          <TextField
            select
            size="small"
            label="Play a file on the host"
            value={selectedPath}
            onChange={(event) => setSelectedPath(event.target.value)}
            disabled={busy || videos.length === 0}
            fullWidth
          >
            {videos.map((video) => (
              <MenuItem key={video.path} value={video.path}>
                {video.name} · {formatSize(video.size)}
              </MenuItem>
            ))}
          </TextField>
          <Button
            variant="contained"
            size="small"
            onClick={() => run('Play', '/server/av/loadVideo', { url_or_path: selectedPath })}
            disabled={busy || !selectedPath || selectedPath === status?.source_url}
          >
            {pending === 'Play' ? <CircularProgress size={18} /> : 'Play'}
          </Button>

          <TextField
            size="small"
            label="Download & play"
            placeholder="https://…/video.mp4"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            disabled={busy}
            fullWidth
          />
          <Button
            variant="outlined"
            size="small"
            onClick={() => run('Download', '/server/av/loadVideo', { url_or_path: url.trim(), timeout: 600 })}
            disabled={busy || !url.trim()}
          >
            {pending === 'Download' ? <CircularProgress size={18} /> : 'Download & play'}
          </Button>
        </>
      )}
    </Box>
  );
});
