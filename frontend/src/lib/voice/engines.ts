/**
 * Voice engines for Atlas voice (TASK-140).
 *
 * The UI only talks to these two interfaces, so the audio stack can change (browser recognition, Whisper on a
 * host, a cloud speech model, a voice-to-command model) without touching a component. The browser engines below
 * are the zero-cost default; MiniMax is the main voice, with the browser voice as its fallback.
 */

import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

export interface SpeechToTextHandlers {
  /** Words heard so far for the current utterance (replaced, not appended). */
  onInterim: (text: string) => void;
  /** One finished utterance. */
  onFinal: (text: string) => void;
  /** The engine stopped on its own or failed; `error` is a short code ('not-allowed', 'no-speech', …). */
  onEnd: (error?: string) => void;
}

export interface SpeechToTextEngine {
  readonly name: string;
  isSupported(): boolean;
  /** `continuous` keeps listening across utterances (conversation); otherwise one message. */
  start(opts: { lang: string; continuous: boolean } & SpeechToTextHandlers): void;
  /** Finish: the current words are delivered through onFinal, then onEnd. */
  stop(): void;
  /** Drop everything: no onFinal. */
  cancel(): void;
}

export interface TextToSpeechEngine {
  readonly name: string;
  isSupported(): boolean;
  /** `rate` 1 = normal speed. */
  speak(text: string, lang: string, rate: number, onEnd: () => void): void;
  /** Stops speech at once (abort, barge-in). */
  cancel(): void;
}

// --- Browser speech recognition (Chrome, Edge, Safari, Android WebView) ---------------------------------------

interface RecognitionAlternative { transcript: string }
interface RecognitionResult { isFinal: boolean; 0: RecognitionAlternative }
interface RecognitionEvent { resultIndex: number; results: ArrayLike<RecognitionResult> }
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: RecognitionEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => Recognition;

const recognitionCtor = (): RecognitionCtor | undefined => {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition;
};

export class BrowserSpeechToText implements SpeechToTextEngine {
  readonly name = 'browser';
  private rec: Recognition | null = null;
  private cancelled = false;
  private wantContinuous = false;
  private lastError: string | undefined;
  private pending = '';

  isSupported(): boolean {
    return typeof window !== 'undefined' && !!recognitionCtor();
  }

  start(opts: { lang: string; continuous: boolean } & SpeechToTextHandlers): void {
    const Ctor = recognitionCtor();
    if (!Ctor) { opts.onEnd('unsupported'); return; }
    this.cancel();
    this.cancelled = false;
    this.wantContinuous = opts.continuous;
    this.lastError = undefined;
    this.pending = '';
    const rec = new Ctor();
    rec.lang = opts.lang;
    rec.continuous = true;
    rec.interimResults = true;
    rec.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i += 1) {
        const r = e.results[i];
        const text = r[0].transcript;
        if (r.isFinal) {
          if (opts.continuous) {
            const done = text.trim();
            if (done) opts.onFinal(done);
          } else {
            this.pending = `${this.pending} ${text}`.trim();
          }
        } else {
          interim += text;
        }
      }
      opts.onInterim(opts.continuous ? interim.trim() : `${this.pending} ${interim}`.trim());
    };
    rec.onerror = (e) => { this.lastError = e.error; };
    rec.onend = () => {
      // Chrome ends a "continuous" session after a pause; a conversation restarts it until stop/cancel.
      if (this.rec === rec && this.wantContinuous && !this.cancelled && this.lastError !== 'not-allowed') {
        try { rec.start(); return; } catch { /* fall through to end */ }
      }
      if (this.rec === rec) this.rec = null;
      if (!this.cancelled && !opts.continuous && this.pending) opts.onFinal(this.pending);
      opts.onEnd(this.cancelled ? undefined : this.lastError);
    };
    this.rec = rec;
    rec.start();
  }

  stop(): void {
    this.wantContinuous = false;
    this.rec?.stop();
  }

  cancel(): void {
    this.cancelled = true;
    this.wantContinuous = false;
    const rec = this.rec;
    this.rec = null;
    rec?.abort();
  }
}

// --- Browser voice ---------------------------------------------------------------------------------------------

export class BrowserTextToSpeech implements TextToSpeechEngine {
  readonly name = 'browser';

  isSupported(): boolean {
    return typeof window !== 'undefined' && 'speechSynthesis' in window;
  }

  speak(text: string, lang: string, rate: number, onEnd: () => void): void {
    if (!this.isSupported() || !text.trim()) { onEnd(); return; }
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = lang;
    u.rate = rate;
    const voice = window.speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().startsWith(lang.slice(0, 2).toLowerCase()));
    if (voice) u.voice = voice;
    u.onend = onEnd;
    u.onerror = onEnd;
    window.speechSynthesis.speak(u);
  }

  cancel(): void {
    if (this.isSupported()) window.speechSynthesis.cancel();
  }
}

// --- MiniMax voice (owner's pick: speech-2.6-turbo, Trustworth Man), browser voice as fallback ---------------

/** Atlas's main voice: the server's MiniMax text-to-speech; any failure falls back to `fallback` (browser voice). */
export class MiniMaxTextToSpeech implements TextToSpeechEngine {
  readonly name = 'minimax';
  private audio: HTMLAudioElement | null = null;
  private ctrl: AbortController | null = null;
  private url: string | null = null;

  constructor(private readonly fallback: TextToSpeechEngine) {}

  isSupported(): boolean {
    return typeof window !== 'undefined' && typeof Audio !== 'undefined';
  }

  speak(text: string, lang: string, rate: number, onEnd: () => void): void {
    this.cancel();
    if (!text.trim()) { onEnd(); return; }
    const ctrl = new AbortController();
    this.ctrl = ctrl;
    apiClient(buildServerUrl('/server/agent/voice/speak'), {
      method: 'POST', body: JSON.stringify({ text, lang: lang.slice(0, 2), speed: rate }), signal: ctrl.signal,
    })
      .then((resp) => (resp.ok ? resp.blob() : Promise.reject(new Error(`HTTP ${resp.status}`))))
      .then((blob) => {
        if (ctrl.signal.aborted) return;
        this.url = URL.createObjectURL(blob);
        const audio = new Audio(this.url);
        this.audio = audio;
        const done = () => { if (this.audio === audio) { this.release(); onEnd(); } };
        audio.onended = done;
        audio.onerror = done;
        return audio.play();
      })
      .catch(() => {
        if (ctrl.signal.aborted) return;
        this.release();
        this.fallback.speak(text, lang, rate, onEnd);
      });
  }

  private release(): void {
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = null;
    this.audio = null;
    this.ctrl = null;
  }

  cancel(): void {
    this.ctrl?.abort();
    this.audio?.pause();
    this.release();
    this.fallback.cancel();
  }
}

/** App language code → BCP-47 tag for the engines. */
export const speechLang = (lang: string): string => ({ fr: 'fr-FR', de: 'de-DE' } as Record<string, string>)[lang] ?? 'en-US';

/** A spoken abort: the whole utterance is a stop word (EN / FR / DE), so it never waits for the model. */
const STOP_WORDS = new Set(['stop', 'stopp', 'halt', 'cancel', 'abort', 'arrête', 'arrete', 'arrêtez', 'annule', 'annuler', 'stoppe', 'abbrechen']);
export const isStopCommand = (text: string): boolean => {
  const words = text.toLowerCase().replace(/[.,!?;:]/g, ' ').split(/\s+/).filter(Boolean);
  return words.length > 0 && words.length <= 3 && words.some((w) => STOP_WORDS.has(w));
};
