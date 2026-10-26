/**
 * useDeviceVoice — continuous voice control of the device the user HOLDS under Take Control (TASK-160).
 *
 * Same engines as Atlas voice (browser speech-to-text, browser text-to-speech, the stop words). One utterance:
 *   heard -> POST /server/agent/voice/plan (matched to one of the device's own listed actions, lock checked)
 *         -> beep, read the command back -> POST /server/agent/voice/run -> beep, "Done".
 * "abort" (word or button) cancels what is being processed and keeps listening; "stop" (word or button) closes the
 * microphone and stops the device. Both act at once, before the server answers: the readback is cut and the plan is
 * never run. The client never sends a command to a device, only a plan id the server made.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { BrowserSpeechToText, BrowserTextToSpeech, isStopCommand, speechLang } from '../../lib/voice/engines';
import { api } from '../../utils/apiClient';
import { buildServerUrl, buildServerUrlForServer } from '../../utils/buildUrlUtils';
import { Host } from '../../types/common/Host_Types';
import { getBrowserSessionId } from '../useUserSession';

export type VoicePhase = 'off' | 'listening' | 'working' | 'speaking';

export interface VoiceHistoryItem {
  at: number;
  heard: string;
  /** What was understood (the readback), or the refusal. */
  sent: string;
  ok: boolean;
}

interface PlanReply {
  decision: string;
  reply?: string;
  label?: string;
  plan_id?: string;
  listening?: boolean;
}

const PREFS_KEY = 'virtualpytest:device-voice';
const HISTORY = 3;
const QUEUE_MAX = 3;

interface Prefs { beep: boolean; speak: boolean }
const loadPrefs = (): Prefs => {
  try {
    return { beep: true, speak: true, ...(JSON.parse(window.localStorage.getItem(PREFS_KEY) || '{}') as Partial<Prefs>) };
  } catch {
    return { beep: true, speak: true };
  }
};

const appLang = (): string => {
  try {
    const l = window.localStorage.getItem('virtualpytest:language');
    return l === 'fr' || l === 'de' ? l : 'en';
  } catch {
    return 'en';
  }
};

let audioCtx: AudioContext | null = null;
/** A short tone: one for "understood", two for "done". Silent where audio is not available. */
function beep(times: number): void {
  try {
    audioCtx = audioCtx ?? new AudioContext();
    const ctx = audioCtx;
    for (let i = 0; i < times; i += 1) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = i === 0 ? 880 : 1175;
      gain.gain.value = 0.08;
      osc.connect(gain).connect(ctx.destination);
      const t0 = ctx.currentTime + i * 0.16;
      osc.start(t0);
      osc.stop(t0 + 0.1);
    }
  } catch {
    // no audio: the readback and the screen still tell the user
  }
}

export function useDeviceVoice(host: Host | null | undefined, deviceId: string | null | undefined) {
  const [phase, setPhase] = useState<VoicePhase>('off');
  const [interim, setInterim] = useState('');
  const [history, setHistory] = useState<VoiceHistoryItem[]>([]);
  const [current, setCurrent] = useState<{ heard: string; sent: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const supported = typeof window !== 'undefined' && new BrowserSpeechToText().isSupported();

  const stt = useRef(new BrowserSpeechToText());
  const tts = useRef(new BrowserTextToSpeech());
  const token = useRef(0);               // bumped by abort / stop: whatever runs under an older token stops
  const queue = useRef<string[]>([]);
  const busy = useRef(false);
  const lastStop = useRef({ word: '', at: 0 });
  const listening = useRef(false);
  const prefsRef = useRef(prefs);
  prefsRef.current = prefs;

  const post = useCallback(
    async <T,>(path: string, body: Record<string, unknown>): Promise<T> => {
      const url = host?.server_url ? buildServerUrlForServer(host.server_url, path) : buildServerUrl(path);
      return api.post<T>(url, { host_name: host?.host_name, device_id: deviceId, session_id: getBrowserSessionId(), lang: appLang(), ...body });
    },
    [host, deviceId],
  );

  const addHistory = useCallback((item: Omit<VoiceHistoryItem, 'at'>) => {
    setHistory((h) => [{ ...item, at: Date.now() }, ...h].slice(0, HISTORY));
  }, []);

  const speak = useCallback((text: string, mine: number): Promise<void> => new Promise((resolve) => {
    if (!prefsRef.current.speak || !tts.current.isSupported() || mine !== token.current) { resolve(); return; }
    setPhase('speaking');
    // A speech engine that never reports its end (no voice, blocked audio) must not hold the command forever.
    const guard = window.setTimeout(resolve, Math.max(2500, text.length * 120));
    tts.current.speak(text, speechLang(appLang()), 1, () => { window.clearTimeout(guard); resolve(); });
  }), []);

  const process = useCallback(async (text: string) => {
    const mine = token.current;
    setPhase('working');
    setCurrent({ heard: text, sent: '…' });
    try {
      const plan = await post<PlanReply>('/server/agent/voice/plan', { text });
      if (mine !== token.current) return;
      if (plan.decision !== 'plan') {
        const ok = ['sent', 'answered', 'stop', 'abort'].includes(plan.decision);
        addHistory({ heard: text, sent: plan.reply || plan.decision, ok });
        setCurrent({ heard: text, sent: plan.reply || '' });
        if (prefsRef.current.beep) beep(ok ? 2 : 1);
        await speak(plan.reply || '', mine);
        return;
      }
      const label = plan.label || text;
      setCurrent({ heard: text, sent: label });
      if (prefsRef.current.beep) beep(1);
      await speak(label, mine);                       // read back; an abort in the meantime cancels the run
      if (mine !== token.current) return;
      setPhase('working');
      const res = await post<PlanReply>('/server/agent/voice/run', { plan_id: plan.plan_id });
      if (mine !== token.current) return;
      const ok = res.decision === 'sent';
      addHistory({ heard: text, sent: ok ? label : res.reply || label, ok });
      setCurrent({ heard: text, sent: ok ? `${label} ✓` : res.reply || '' });
      if (prefsRef.current.beep) beep(ok ? 2 : 1);
      await speak(res.reply || '', mine);
    } catch (e) {
      if (mine === token.current) setError(e instanceof Error ? e.message : 'Voice command failed');
    }
  }, [post, addHistory, speak]);

  const drain = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      while (queue.current.length) await process(queue.current.shift() as string);
    } finally {
      busy.current = false;
      setPhase(listening.current ? 'listening' : 'off');
    }
  }, [process]);

  const stopListening = useCallback(() => {
    listening.current = false;
    stt.current.cancel();
    setInterim('');
    setPhase((p) => (p === 'working' || p === 'speaking' ? p : 'off'));
  }, []);

  /** Abort: cancel what is processed or read back and what is queued; the microphone stays as it is. */
  const abort = useCallback(async (words = 'abort') => {
    token.current += 1;
    queue.current = [];
    tts.current.cancel();
    setPhase(listening.current ? 'listening' : 'off');
    try {
      const out = await post<PlanReply>('/server/agent/voice/plan', { text: words });
      addHistory({ heard: words, sent: out.reply || 'Aborted', ok: out.decision !== 'refused' });
      setCurrent({ heard: words, sent: out.reply || '' });
      if (out.listening === false) stopListening();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Abort failed');
    }
  }, [post, addHistory, stopListening]);

  /** Stop: the microphone closes at once and the device is told to stop. */
  const stop = useCallback(async () => {
    stopListening();
    token.current += 1;
    queue.current = [];
    tts.current.cancel();
    setPhase('off');
    try {
      const out = await post<PlanReply>('/server/agent/voice/plan', { text: 'stop' });
      addHistory({ heard: 'stop', sent: out.reply || 'Stopped', ok: out.decision !== 'refused' });
      setCurrent({ heard: 'stop', sent: out.reply || '' });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Stop failed');
    }
  }, [post, addHistory, stopListening]);

  const onFinal = useCallback((text: string) => {
    const said = text.trim();
    if (!said) return;
    setInterim('');
    if (isStopCommand(said)) {                        // never waits behind a running command
      const isAbort = /\b(abort|cancel|annule|annuler|abbrechen)\b/i.test(said);
      const word = isAbort ? 'abort' : 'stop';
      if (lastStop.current.word === word && Date.now() - lastStop.current.at < 1500) return;   // interim and final of one word
      lastStop.current = { word, at: Date.now() };
      void (isAbort ? abort(said) : stop());
      return;
    }
    if (queue.current.length >= QUEUE_MAX) return;
    queue.current.push(said);
    void drain();
  }, [abort, stop, drain]);

  const start = useCallback(() => {
    if (!host || !deviceId || listening.current) return;
    setError(null);
    listening.current = true;
    setPhase('listening');
    stt.current.start({
      lang: speechLang(appLang()),
      continuous: true,
      onInterim: (t) => {
        setInterim(t);
        if (isStopCommand(t)) onFinal(t);             // a stop / abort word acts as soon as it is heard
      },
      onFinal,
      onEnd: (err) => {
        if (!listening.current) return;
        listening.current = false;
        setPhase(busy.current ? 'working' : 'off');
        if (err && err !== 'no-speech' && err !== 'aborted') setError(err === 'not-allowed' ? 'Microphone blocked' : `Microphone: ${err}`);
      },
    });
  }, [host, deviceId, onFinal]);

  const setPref = useCallback((key: keyof Prefs, value: boolean) => {
    setPrefs((p) => {
      const next = { ...p, [key]: value };
      try { window.localStorage.setItem(PREFS_KEY, JSON.stringify(next)); } catch { /* the choice just is not remembered */ }
      return next;
    });
  }, []);

  useEffect(() => () => {
    listening.current = false;
    token.current += 1;
    stt.current.cancel();
    tts.current.cancel();
  }, []);

  return { supported, phase, interim, current, history, error, prefs, setPref, start, stop, abort: () => abort('abort'), listening: phase !== 'off' || listening.current };
}
