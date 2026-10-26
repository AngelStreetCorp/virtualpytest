import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  CAPTION_LANG_STORAGE_KEY, CaptionsResponse, DEFAULT_DELAY_S, ManifestChunk, findChunk, hostOffsetMs, languageCode, readyUntil, targetPosition,
} from '../utils/captionPlayback';
import {
  buildArchiveManifestUrl, buildServerUrl, ensureHostSession, fetchHostMedia,
} from '../utils/buildUrlUtils';
import { getLanguage, LANGUAGES, Language } from '../i18n';

const POLL_MS = 20_000; // the host merges a minute at a time; finished chunks do not change
const SESSION_REFRESH_MS = 4 * 60_000;

const readLang = (): Language => {
  try {
    const v = window.localStorage.getItem(CAPTION_LANG_STORAGE_KEY);
    if (v && LANGUAGES.some((l) => l.code === v)) return v as Language;
  } catch { /* storage blocked */ }
  return getLanguage();
};

/**
 * Data side of the delayed caption player (TASK-103): the archive manifest and the host's captions of the
 * chunk being watched (WebVTT plus per-minute readiness, §7.2). The host only returns the source language
 * for now; `shownLang` reports what it returned, so the picker can say when it differs from the choice.
 */
export const useCaptionPlayback = (host: any, deviceId: string, delayS: number = DEFAULT_DELAY_S) => {
  const [chunks, setChunks] = useState<ManifestChunk[]>([]);
  const [manifestError, setManifestError] = useState(false);
  const [lang, setLangState] = useState<Language>(readLang);
  const [captions, setCaptions] = useState<CaptionsResponse | null>(null);
  const [tick, setTick] = useState(0);

  const manifestUrl = useMemo(() => buildArchiveManifestUrl(host, deviceId), [host, deviceId]);
  const chunkUrl = useCallback(
    (hour: number, idx: number) => manifestUrl.replace('archive_manifest.json', `${hour}/chunk_10min_${idx}.mp4`),
    [manifestUrl],
  );

  const setLang = useCallback((l: Language) => {
    setLangState(l);
    try { window.localStorage.setItem(CAPTION_LANG_STORAGE_KEY, l); } catch { /* storage blocked */ }
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => setTick((n) => n + 1), POLL_MS);
    return () => window.clearInterval(id);
  }, []);
  useEffect(() => {
    const id = window.setInterval(() => { void ensureHostSession(manifestUrl); }, SESSION_REFRESH_MS);
    return () => window.clearInterval(id);
  }, [manifestUrl]);

  useEffect(() => {
    let alive = true;
    fetchHostMedia(manifestUrl)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((m) => { if (alive) { setChunks(m.chunks ?? []); setManifestError(false); } })
      .catch(() => { if (alive) setManifestError(true); });
    return () => { alive = false; };
  }, [manifestUrl, tick]);

  // The chunk being watched: re-evaluated on every poll, so a chunk change is noticed within 20 s.
  // On the HOST's clock: the archive names hours by it, whatever timezone this browser is in.
  const hostOffset = useMemo(() => hostOffsetMs(chunks), [chunks]);
  const target = useMemo(() => targetPosition(Date.now(), delayS, hostOffset ?? 0), [delayS, hostOffset, tick]);

  useEffect(() => {
    if (hostOffset == null) return undefined; // the hour is not known before the host's clock is
    let alive = true;
    const url = buildServerUrl(
      `/server/transcript/captions?host_name=${encodeURIComponent(host.host_name)}&device_id=${encodeURIComponent(deviceId)}` +
        `&hour=${target.hour}&chunk_index=${target.chunkIndex}&lang=${lang}`,
    );
    fetch(url, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((c: CaptionsResponse & { success?: boolean }) => {
        if (alive && c.success !== false) setCaptions(c);
      })
      .catch(() => { /* keep what we have; the next poll retries */ });
    return () => { alive = false; };
  }, [host.host_name, deviceId, hostOffset, target.hour, target.chunkIndex, lang, tick]);

  // A different chunk starts with no captions, not with the previous chunk's.
  useEffect(() => { setCaptions(null); }, [deviceId, target.hour, target.chunkIndex]);

  const limit = useMemo(() => readyUntil(captions?.minutes), [captions]);
  const vtt = captions?.vtt && captions.vtt.includes('-->') ? captions.vtt : null;
  const shownLang = languageCode(captions?.language);

  return {
    chunks, hostOffset, manifestError, lang, setLang, captions, shownLang, vtt, limit, target, chunkUrl,
    findChunk: (h: number, i: number) => findChunk(chunks, h, i),
  };
};
