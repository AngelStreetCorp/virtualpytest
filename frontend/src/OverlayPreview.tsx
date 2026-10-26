/**
 * A bare harness that mounts the REAL ProfileOverlay over a real device frame, for a visual check of the
 * layout without a server, a login or a host. Not part of the app: overlay-preview.html loads it.
 *
 * The data is a real frame JSON pulled from `vpt-lenovo1` device3 (a `capture_*.json` the monitor wrote)
 * and the real capture jpg beside it, so what is on screen is the device's own state, rendered by the
 * component the app uses.
 */
import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Box, CssBaseline, ThemeProvider, createTheme } from '@mui/material';

import ProfileOverlay from './components/monitoring/ProfileOverlay';
import type { MonitoringAnalysis } from './types/pages/Monitoring_Types';

const Preview: React.FC = () => {
  const [analysis, setAnalysis] = useState<MonitoringAnalysis | null>(null);
  const [image, setImage] = useState('');
  const [locked, setLocked] = useState(false);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const frame = q.get('frame') ?? 'overlay-preview-data/live_eggs_frame.json';
    const jpg = q.get('image') ?? 'overlay-preview-data/live_eggs_frame.jpg';
    const ageMs = Number(q.get('age_ms') ?? '310');
    const locked = q.get('locked') === '1';
    fetch(frame)
      .then((r) => r.json())
      .then((d) => {
        // pretend the JSON arrived `ageMs` ago, which is what the app sees
        d.captured_at = new Date(Date.now() - ageMs).toISOString();
        setAnalysis(d as MonitoringAnalysis);
        setLocked(locked);
      });
    setImage(jpg);
  }, []);

  return (
    <ThemeProvider theme={createTheme({ palette: { mode: 'dark' } })}>
      <CssBaseline />
      <Box
        data-testid="preview-frame"
        sx={{
          position: 'relative',
          width: 1280,
          height: 720,
          backgroundImage: image ? `url(${image})` : 'none',
          backgroundSize: 'cover',
          overflow: 'hidden',
        }}
      >
        {analysis && (
          <ProfileOverlay analysis={analysis} fpsInConfigured={5} fpsIn={5} fpsOut={8} frameLocked={locked} />
        )}
      </Box>
    </ThemeProvider>
  );
};

createRoot(document.getElementById('preview-root')!).render(<Preview />);