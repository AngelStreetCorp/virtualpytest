/**
 * Records the microphone for the "audio → command" voice test (TASK-140): the model hears the
 * utterance itself. `cut()` returns what was recorded since the last cut as a 16 kHz mono WAV
 * (base64) and keeps recording, so a conversation sends one clip per utterance.
 */

const TARGET_RATE = 16000;

const encodeWav = (samples: Float32Array, rate: number): ArrayBuffer => {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o: number, s: string) => { for (let i = 0; i < s.length; i += 1) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); str(8, 'WAVE'); str(12, 'fmt ');
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, 'data');
  v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i += 1) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buf;
};

const toBase64 = (buf: ArrayBuffer): string => {
  const bytes = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
};

/** Any browser recording (webm/ogg/mp4) → 16 kHz mono WAV, base64. */
export const blobToWavBase64 = async (blob: Blob): Promise<string> => {
  const raw = await blob.arrayBuffer();
  const ctx = new AudioContext();
  try {
    const decoded = await ctx.decodeAudioData(raw);
    const frames = Math.ceil(decoded.duration * TARGET_RATE);
    const offline = new OfflineAudioContext(1, Math.max(frames, 1), TARGET_RATE);
    const src = offline.createBufferSource();
    src.buffer = decoded;
    src.connect(offline.destination);
    src.start();
    const rendered = await offline.startRendering();
    return toBase64(encodeWav(rendered.getChannelData(0), TARGET_RATE));
  } finally {
    void ctx.close();
  }
};

export class UtteranceRecorder {
  private stream: MediaStream | null = null;
  private rec: MediaRecorder | null = null;
  private chunks: Blob[] = [];

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    this.begin();
  }

  private begin(): void {
    if (!this.stream) return;
    this.chunks = [];
    this.rec = new MediaRecorder(this.stream);
    this.rec.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
    this.rec.start();
  }

  /** The audio since the last cut, as WAV base64; recording goes on. */
  cut(): Promise<string> {
    const rec = this.rec;
    if (!rec || rec.state === 'inactive') return Promise.resolve('');
    return new Promise((resolve) => {
      rec.onstop = () => {
        const blob = new Blob(this.chunks, { type: rec.mimeType });
        this.begin();
        blobToWavBase64(blob).then(resolve, () => resolve(''));
      };
      rec.stop();
    });
  }

  stop(): void {
    if (this.rec && this.rec.state !== 'inactive') { this.rec.onstop = null; this.rec.stop(); }
    this.stream?.getTracks().forEach((t) => t.stop());
    this.rec = null;
    this.stream = null;
    this.chunks = [];
  }
}
