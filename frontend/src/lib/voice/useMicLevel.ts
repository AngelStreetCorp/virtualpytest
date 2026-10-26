import { useEffect, useState } from 'react';

/**
 * Live microphone level, 0..1, while `active` (drives the recording waveform and the level meter).
 * Opens its own echo-cancelled stream; returns 0 when the mic is unavailable.
 */
export const useMicLevel = (active: boolean): number => {
  const [level, setLevel] = useState(0);

  useEffect(() => {
    if (!active || !navigator.mediaDevices?.getUserMedia) { setLevel(0); return undefined; }
    let stream: MediaStream | null = null;
    let ctx: AudioContext | null = null;
    let raf = 0;
    let cancelled = false;

    navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
      .then((s) => {
        if (cancelled) { s.getTracks().forEach((t) => t.stop()); return; }
        stream = s;
        ctx = new AudioContext();
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        ctx.createMediaStreamSource(s).connect(analyser);
        const buf = new Uint8Array(analyser.fftSize);
        let last = 0;
        const tick = (now: number) => {
          raf = requestAnimationFrame(tick);
          if (now - last < 50) return;
          last = now;
          analyser.getByteTimeDomainData(buf);
          let sum = 0;
          for (let i = 0; i < buf.length; i += 1) { const v = (buf[i] - 128) / 128; sum += v * v; }
          setLevel(Math.min(1, Math.sqrt(sum / buf.length) * 4));
        };
        raf = requestAnimationFrame(tick);
      })
      .catch(() => setLevel(0));

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      stream?.getTracks().forEach((t) => t.stop());
      void ctx?.close();
      setLevel(0);
    };
  }, [active]);

  return level;
};
