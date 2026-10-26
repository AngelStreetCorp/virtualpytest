/**
 * VoiceContext — Atlas voice (TASK-140), shared by the Atlas page and Ask AI.
 *
 * Two ways in:
 *  - voice message: record → stop (text lands in the field to edit) or send (straight to Atlas), or cancel;
 *  - voice conversation: keeps listening; each utterance is an Atlas turn; Atlas's answer can be read out.
 * Abort (button or a spoken "stop") cancels the turn and cuts speech at once. Engines are swappable
 * (lib/voice/engines.ts) until the audio stack is chosen.
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

import { useAgentChatContext } from './AgentChatContext';
import { useAIContext } from './AIContext';
import { useI18n } from '../i18n/useI18n';
import { useHostData } from '../hooks/useHostManager';
import { getBrowserSessionId } from '../hooks/useUserSession';
import { api } from '../utils/apiClient';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { UtteranceRecorder } from '../lib/voice/recorder';
import {
  BrowserSpeechToText,
  BrowserTextToSpeech,
  MiniMaxTextToSpeech,
  SpeechToTextEngine,
  TextToSpeechEngine,
  isStopCommand,
  speechLang,
} from '../lib/voice/engines';

export type VoicePhase = 'off' | 'recording' | 'listening' | 'working' | 'speaking' | 'stopped';
export type VoiceMode = 'silent' | 'interactive';
export type VoiceSurface = 'atlas' | 'askai';
/** How a spoken command reaches Atlas: its words (Atlas's quick step does the rest), or the audio, where a speech
 *  model picks the command and Atlas checks and runs it in the session. */
export type VoicePipeline = 'atlas' | 'audio';
export type VoiceCmdModel = 'voxtral' | 'gemini-lite';
export type VoiceSpeed = 1.2 | 1.5 | 2;

export interface VoicePrefs {
  mode: VoiceMode;
  speak: { answer: boolean; thinking: boolean; questions: boolean };
  pipeline: VoicePipeline;
  cmdModel: VoiceCmdModel;
  speed: VoiceSpeed;
}

/** The last fast-path command, shown in the strip so the two models can be compared. */
export interface VoiceCommandInfo {
  heard: string;
  pipeline: VoicePipeline;
  model: string;
  tool?: string;
  args?: Record<string, unknown>;
  latencyMs?: number;
  costUsd?: number;
  result: 'hint' | 'abort' | 'atlas' | 'drone' | 'error';
  detail?: string;
}

export interface VoiceTarget { host_name: string; device_id: string; userinterface_name: string }

const PREFS_KEY = 'virtualpytest:atlas-voice';
const DEFAULT_PREFS: VoicePrefs = {
  mode: 'interactive', speak: { answer: true, thinking: false, questions: true },
  pipeline: 'atlas', cmdModel: 'voxtral', speed: 1.2,
};
const STOPPED_MS = 2000;

const loadPrefs = (): VoicePrefs => {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (!raw) return DEFAULT_PREFS;
    const p = JSON.parse(raw) as Partial<VoicePrefs>;
    return {
      mode: p.mode === 'silent' ? 'silent' : 'interactive',
      speak: { ...DEFAULT_PREFS.speak, ...(p.speak ?? {}) },
      pipeline: p.pipeline === 'audio' ? 'audio' : 'atlas',
      cmdModel: p.cmdModel === 'gemini-lite' ? 'gemini-lite' : 'voxtral',
      speed: p.speed === 1.5 || p.speed === 2 ? p.speed : 1.2,
    };
  } catch {
    return DEFAULT_PREFS;
  }
};

/** Markdown and code out, so the voice reads words, not symbols. */
const speakable = (text: string): string =>
  text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/[*_#>|]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 600);

const firstSentence = (text: string): string => (speakable(text).match(/^.*?[.!?](\s|$)/)?.[0] ?? speakable(text).slice(0, 160)).trim();

interface VoiceContextType {
  supported: boolean;
  phase: VoicePhase;
  surface: VoiceSurface | null;
  conversation: boolean;
  interim: string;
  lastReply: string;
  error: string | null;
  prefs: VoicePrefs;
  lastCommand: VoiceCommandInfo | null;
  setMode: (mode: VoiceMode) => void;
  setPref: <K extends 'pipeline' | 'cmdModel' | 'speed'>(key: K, value: VoicePrefs[K]) => void;
  /** The device Atlas works on (Atlas page selection); voice commands without a device name use it. */
  setTarget: (target: VoiceTarget) => void;
  /** Route a finished voice message to Atlas through `send`; on the audio path with a command hint first. */
  dispatch: (text: string, send: (text: string) => void) => Promise<void>;
  toggleSpeak: (key: keyof VoicePrefs['speak']) => void;
  startMessage: (surface: VoiceSurface) => void;
  /** Stop recording; resolves with the words heard ('' when nothing). */
  stopMessage: () => Promise<string>;
  cancelMessage: () => void;
  startConversation: (surface: VoiceSurface) => void;
  endConversation: () => void;
  abort: () => void;
}

const VoiceContext = createContext<VoiceContextType | null>(null);

export const VoiceProvider: React.FC<{ children: React.ReactNode; stt?: SpeechToTextEngine; tts?: TextToSpeechEngine }> = ({
  children,
  stt: sttProp,
  tts: ttsProp,
}) => {
  const agentChat = useAgentChatContext();
  const ai = useAIContext();
  const { lang } = useI18n();
  const stt = useMemo(() => sttProp ?? new BrowserSpeechToText(), [sttProp]);
  const tts = useMemo(() => ttsProp ?? new MiniMaxTextToSpeech(new BrowserTextToSpeech()), [ttsProp]);

  const [phase, setPhase] = useState<VoicePhase>('off');
  const [surface, setSurface] = useState<VoiceSurface | null>(null);
  const [conversation, setConversation] = useState(false);
  const [interim, setInterim] = useState('');
  const [lastReply, setLastReply] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<VoicePrefs>(loadPrefs);
  const [lastCommand, setLastCommand] = useState<VoiceCommandInfo | null>(null);
  const { getAllHosts } = useHostData();
  const target = useRef<VoiceTarget>({ host_name: '', device_id: '', userinterface_name: '' });
  const recorder = useRef<UtteranceRecorder | null>(null);
  const pendingAudio = useRef<Promise<string> | null>(null);

  // Refs so engine callbacks (created once per start) always see current values.
  const live = useRef({ conversation: false, surface: null as VoiceSurface | null, processing: false, speaking: false, prefs, lang });
  live.current.prefs = prefs;
  live.current.lang = lang;
  const messageText = useRef('');
  const messageResolve = useRef<((text: string) => void) | null>(null);
  const queued = useRef<string | null>(null);
  const stoppedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sendRef = useRef<(text: string) => void>(() => undefined);
  const abortRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch { /* per-viewer convenience only */ }
  }, [prefs]);

  const send = useCallback((text: string) => {
    if (live.current.surface === 'askai') ai.sendMessage(text);
    else agentChat.sendMessage(text);
  }, [ai, agentChat]);
  sendRef.current = send;

  const stopSpeaking = useCallback(() => {
    live.current.speaking = false;
    tts.cancel();
  }, [tts]);

  const speak = useCallback((text: string, after: () => void) => {
    const words = speakable(text);
    if (!words) { after(); return; }
    live.current.speaking = true;
    setPhase('speaking');
    tts.speak(words, speechLang(live.current.lang), live.current.prefs.speed, () => {
      if (!live.current.speaking) return;
      live.current.speaking = false;
      after();
    });
  }, [tts]);

  const backToListening = useCallback(() => {
    if (!live.current.conversation) { setPhase('off'); return; }
    setPhase(live.current.processing ? 'working' : 'listening');
    const next = queued.current;
    if (next && !live.current.processing) {
      queued.current = null;
      sendRef.current(next);
    }
  }, []);

  const startRecorder = useCallback(() => {
    if (live.current.prefs.pipeline !== 'audio' || recorder.current) return;
    const r = new UtteranceRecorder();
    recorder.current = r;
    r.start().catch(() => { recorder.current = null; });
  }, []);
  const stopRecorder = useCallback(() => {
    recorder.current?.stop();
    recorder.current = null;
  }, []);

  const dispatch = useCallback(async (text: string, send: (text: string) => void) => {
    const p = live.current.prefs;
    const audio = pendingAudio.current;
    pendingAudio.current = null;
    if (p.pipeline === 'atlas') { if (text.trim()) send(text); return; }
    const audioB64 = (await audio) ?? '';
    if (!audioB64) { if (text.trim()) send(text); return; }
    setPhase('working');
    const devices = getAllHosts().flatMap((h) => (h.devices || []).map((d) => ({
      device_name: d.device_name || d.device_id, host_name: h.host_name, device_id: d.device_id,
    })));
    const info: VoiceCommandInfo = { heard: text, pipeline: p.pipeline, model: p.cmdModel, result: 'error' };
    try {
      const data = await api.post(buildServerUrl('/server/agent/voice/command'), {
        mode: 'audio', model: p.cmdModel, text, audio_b64: audioB64, lang: live.current.lang, devices,
        session_id: getBrowserSessionId(),
        ...target.current,
      }) as {
        success: boolean; error?: string;
        command?: { tool?: string; args?: Record<string, unknown>; latency_ms?: number; cost_usd?: number };
        outcome?: { action: string; reason?: string; text?: string; hint?: { tool: string; args: Record<string, unknown> }; drone?: { decision: string; reply: string } };
      };
      const c = data.command ?? {};
      const o = data.outcome;
      const base = { ...info, tool: c.tool, args: c.args, latencyMs: c.latency_ms, costUsd: c.cost_usd };
      if (!data.success || !o) {
        setLastCommand({ ...info, detail: data.error });
      } else if (o.action === 'abort') {
        setLastCommand({ ...base, result: 'abort' });
        abortRef.current();
        return;
      } else if (o.action === 'drone') {
        // TASK-160: a Tello command was answered by the drone executor (lock, limits, battery, confirmation).
        setLastCommand({ ...base, result: 'drone', detail: o.drone?.reply });
        if (!live.current.conversation) setPhase('off');
        return;
      } else if (o.action === 'hint' && o.hint) {
        // Atlas's quick step checks the pick and runs it in the session: it shows in the chat, Atlas remembers it.
        setLastCommand({ ...base, result: 'hint' });
        agentChat.setQuickHint(o.hint);
        const words = text.trim() || `${c.tool ?? o.hint.tool} ${Object.values(c.args ?? {}).map(String).join(' ')}`.trim();
        send(words);
        return;
      } else {
        setLastCommand({ ...base, result: 'atlas', detail: o.reason });
      }
    } catch (e) {
      setLastCommand({ ...info, detail: e instanceof Error ? e.message : String(e) });
    }
    if (text.trim()) send(text);
    else if (!live.current.conversation) setPhase('off');
  }, [getAllHosts, agentChat]);

  const onUtterance = useCallback((text: string) => {
    setInterim('');
    if (isStopCommand(text)) {
      abortRef.current();
      // A Tello in control also gets its safe stop (hover); any other device: the server answers "abort", no model call.
      const t = target.current;
      if (t?.host_name && t?.device_id) {
        void api.post(buildServerUrl('/server/agent/voice/command'), {
          mode: 'transcript', text, abort_only: true, lang: live.current.lang, session_id: getBrowserSessionId(), ...t,
        }).catch(() => undefined);
      }
      return;
    }
    if (live.current.speaking) stopSpeaking();
    if (live.current.processing) { queued.current = text; return; }
    if (recorder.current) pendingAudio.current = recorder.current.cut();
    void dispatch(text, (words) => sendRef.current(words));
  }, [stopSpeaking, dispatch]);

  const onEngineEnd = useCallback((err?: string) => {
    if (err === 'not-allowed' || err === 'service-not-allowed' || err === 'unsupported' || err === 'audio-capture') {
      setError(err === 'unsupported' ? 'unsupported' : 'blocked');
      live.current.conversation = false;
      setConversation(false);
      setPhase('off');
    }
    if (messageResolve.current) {
      messageResolve.current(messageText.current.trim());
      messageResolve.current = null;
    }
    if (!live.current.conversation) setPhase((p) => (p === 'stopped' ? p : 'off'));
  }, []);

  // --- voice message ---------------------------------------------------------------------------------------
  const startMessage = useCallback((s: VoiceSurface) => {
    if (!stt.isSupported()) { setError('unsupported'); return; }
    setError(null);
    stopSpeaking();
    live.current.surface = s;
    setSurface(s);
    messageText.current = '';
    setInterim('');
    setPhase('recording');
    startRecorder();
    stt.start({
      lang: speechLang(live.current.lang),
      continuous: false,
      onInterim: (t) => { messageText.current = t; setInterim(t); },
      onFinal: (t) => { messageText.current = t; },
      onEnd: onEngineEnd,
    });
  }, [stt, stopSpeaking, onEngineEnd, startRecorder]);

  const stopMessage = useCallback(() => new Promise<string>((resolve) => {
    const r = recorder.current;
    if (r) {
      const clip = r.cut();
      pendingAudio.current = clip;
      void clip.finally(() => { if (recorder.current === r) stopRecorder(); });
    }
    messageResolve.current = (text) => { setInterim(''); setPhase('off'); resolve(text); };
    stt.stop();
  }), [stt, stopRecorder]);

  const cancelMessage = useCallback(() => {
    messageResolve.current = null;
    pendingAudio.current = null;
    stopRecorder();
    stt.cancel();
    setInterim('');
    setPhase('off');
  }, [stt, stopRecorder]);

  // --- conversation ----------------------------------------------------------------------------------------
  const startConversation = useCallback((s: VoiceSurface) => {
    if (!stt.isSupported()) { setError('unsupported'); return; }
    setError(null);
    live.current.surface = s;
    live.current.conversation = true;
    setSurface(s);
    setConversation(true);
    setInterim('');
    setLastReply('');
    setPhase(live.current.processing ? 'working' : 'listening');
    startRecorder();
    stt.start({
      lang: speechLang(live.current.lang),
      continuous: true,
      onInterim: (t) => {
        setInterim(t);
        // Barge-in: the user talks over Atlas → stop speaking at once.
        if (t.length > 2 && live.current.speaking) { stopSpeaking(); backToListening(); }
      },
      onFinal: onUtterance,
      onEnd: onEngineEnd,
    });
  }, [stt, stopSpeaking, backToListening, onUtterance, onEngineEnd, startRecorder]);

  const endConversation = useCallback(() => {
    live.current.conversation = false;
    queued.current = null;
    setConversation(false);
    stt.cancel();
    stopRecorder();
    stopSpeaking();
    setInterim('');
    setPhase('off');
  }, [stt, stopSpeaking, stopRecorder]);

  const abort = useCallback(() => {
    stopSpeaking();
    queued.current = null;
    if (live.current.processing) agentChat.stopGeneration();
    if (phase === 'recording') { messageResolve.current = null; stt.cancel(); }
    setInterim('');
    setPhase('stopped');
    if (stoppedTimer.current) clearTimeout(stoppedTimer.current);
    stoppedTimer.current = setTimeout(() => setPhase(live.current.conversation ? 'listening' : 'off'), STOPPED_MS);
  }, [stopSpeaking, agentChat, phase, stt]);
  abortRef.current = abort;

  // --- follow the Atlas turn ---------------------------------------------------------------------------------
  const { isProcessing, messages, currentEvents } = agentChat;
  useEffect(() => {
    const was = live.current.processing;
    live.current.processing = isProcessing;
    if (!live.current.conversation) return;
    if (isProcessing && !was) {
      stopSpeaking();
      setPhase((p) => (p === 'stopped' ? p : 'working'));
      return;
    }
    if (!isProcessing && was) {
      const reply = [...messages].reverse().find((m) => m.role === 'agent');
      const text = reply?.content ?? '';
      setLastReply(text);
      const p = live.current.prefs;
      const isQuestion = /\?\s*$/.test(text.trim());
      const wanted = p.mode === 'interactive' && (isQuestion ? p.speak.questions || p.speak.answer : p.speak.answer);
      if (text && wanted) speak(text, backToListening);
      else backToListening();
    }
  }, [isProcessing, messages, speak, stopSpeaking, backToListening]);

  const lastThinking = useRef(0);
  useEffect(() => {
    if (!live.current.conversation || !isProcessing) return;
    const p = live.current.prefs;
    if (p.mode !== 'interactive' || !p.speak.thinking || live.current.speaking) return;
    const idx = currentEvents.map((e) => e.type).lastIndexOf('thinking');
    if (idx < 0 || idx < lastThinking.current) return;
    lastThinking.current = idx + 1;
    const sentence = firstSentence(currentEvents[idx].content || '');
    if (sentence) speak(sentence, () => setPhase(live.current.processing ? 'working' : 'listening'));
  }, [currentEvents, isProcessing, speak]);

  useEffect(() => () => {
    recorder.current?.stop();
    stt.cancel();
    tts.cancel();
    if (stoppedTimer.current) clearTimeout(stoppedTimer.current);
  }, [stt, tts]);

  const setMode = useCallback((mode: VoiceMode) => {
    setPrefs((p) => ({ ...p, mode }));
    if (mode === 'silent') stopSpeaking();
  }, [stopSpeaking]);
  const setPref = useCallback(<K extends 'pipeline' | 'cmdModel' | 'speed'>(key: K, value: VoicePrefs[K]) => {
    setPrefs((p) => ({ ...p, [key]: value }));
  }, []);
  const setTarget = useCallback((t: VoiceTarget) => { target.current = t; }, []);
  const toggleSpeak = useCallback((key: keyof VoicePrefs['speak']) => {
    setPrefs((p) => ({ ...p, speak: { ...p.speak, [key]: !p.speak[key] } }));
  }, []);

  const value = useMemo<VoiceContextType>(() => ({
    supported: stt.isSupported(),
    phase, surface, conversation, interim, lastReply, error, prefs, lastCommand,
    setMode, setPref, setTarget, dispatch, toggleSpeak, startMessage, stopMessage, cancelMessage, startConversation,
    endConversation, abort,
  }), [stt, phase, surface, conversation, interim, lastReply, error, prefs, lastCommand, setMode, setPref, setTarget,
    dispatch, toggleSpeak, startMessage, stopMessage, cancelMessage, startConversation, endConversation, abort]);

  return <VoiceContext.Provider value={value}>{children}</VoiceContext.Provider>;
};

export const useVoice = (): VoiceContextType => {
  const ctx = useContext(VoiceContext);
  if (!ctx) throw new Error('useVoice must be used within VoiceProvider');
  return ctx;
};
