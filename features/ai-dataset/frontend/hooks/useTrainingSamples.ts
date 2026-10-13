/**
 * Training sample review hook (TASK-27 step 4).
 *
 * Wraps the admin-only /server/training-samples routes: list (filtered, signed
 * image URLs, `proposed_label` already in the family's label shape), label, freeze.
 * Step 4d: the "Confusable pairs" filter (`label_conflict=true`) and `conflict_partner`.
 * Step 4f: `total` is the count matching the filters at the last (re)load only, and
 * `loadOfftreeLabels` gives the "Screen not in the tree" suggestions.
 * Step 4h: `loadCoverage` reads the canonical-app coverage report.
 * Step 4i: AI triage. Show "Needs you" (`triage=needs_human`), each row's `triage` record,
 * AI-verified (agreed) counts next to the human ones, and `eval-vN-ai` freezes with a minimum.
 * Step 4k: `useScreenGroups(userinterface)` reads an app's screen groups (Home with any tab
 * focused is one screen): the screen answers of a screen-id sample. Coverage counts groups.
 * `countSamples(filters)`: the match count alone (the "Needs you" empty state counts the other sets).
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from '../../../../frontend/src/utils/apiClient';
import { buildServerUrl } from '../../../../frontend/src/utils/buildUrlUtils';

export type TrainingFamily = 'screen-id' | 'focus' | 'banner' | 'menu' | 'av-fault' | 'content-type' | 'other';

export const TRAINING_FAMILIES: TrainingFamily[] = ['screen-id', 'focus', 'banner', 'menu', 'av-fault', 'content-type', 'other'];

export interface ConflictPartner {
  id: string;
  ground_truth: unknown;
}

/** Step 4i: what the AI teacher said about a row (null = never triaged). */
export type TriageStatus = 'agreed' | 'needs_human' | 'teacher_only' | 'resolved' | 'excluded';
export type TriageReason = 'disagrees_with_run' | 'conflict' | 'low_confidence' | 'spot_check' | 'no_independent_label'
  | 'focus_low_confidence';

export interface TriageRecord {
  status: TriageStatus;
  reason: TriageReason | null;
  teacher_model?: string;
  teacher_answer?: unknown;
  teacher_label?: unknown;
  teacher_confidence?: 'high' | 'low';
  teacher_note?: string | null;
  batch_id?: string;
  triaged_at?: string;
  spot_check_of?: TriageStatus;
  prior_status?: TriageStatus | null;
  prior_reason?: TriageReason | null;
  resolved_at?: string;
  human_agreed_with_teacher?: boolean | null;
}

export interface TrainingSample {
  id: string;
  family: TrainingFamily;
  object_key: string;
  device_model: string;
  userinterface: string | null;
  node_id: string | null;
  focus_label: string | null;
  prompt: string | null;
  model_answer: unknown;
  ground_truth: unknown;
  proposed_label: unknown;
  /** Where proposed_label came from; null = no guess. */
  guess_source: 'run' | 'human' | 'teacher' | 'model' | null;
  label_source: 'run' | 'human' | 'teacher' | 'none';
  is_failure: boolean;
  label_conflict: boolean;
  /** One near-identical sample with a different label (set on label_conflict rows). */
  conflict_partner?: ConflictPartner | null;
  split: 'train' | 'eval' | 'holdout';
  eval_version: string | null;
  source_ref: Record<string, unknown> | null;
  created_at: string;
  image_url: string | null;
  /** Step 4i triage record; absent when the feature migration is not applied. */
  triage?: TriageRecord | null;
}

/** Review status view: what the AI triage sent to a human, not yet human-checked,
 * human-checked, or everything. */
export type ReviewShow = 'needs_you' | 'unchecked' | 'checked' | 'all';

/** The label_source list each view asks the list route for ('' = no filter). */
const SHOW_LABEL_SOURCES: Record<ReviewShow, string> = {
  needs_you: '',
  unchecked: 'none,run,teacher',
  checked: 'human',
  all: '',
};

/** Views that remove a sample from the list once a human answered it. */
export const SHOW_REMOVES_ON_LABEL: Record<ReviewShow, boolean> = {
  needs_you: true,
  unchecked: true,
  checked: false,
  all: false,
};

/** Step 4i freeze options: eval-vN takes human-verified rows only (threshold 200);
 * eval-vN-ai is a pilot of human + AI-verified (agreed) rows, with its own minimum. */
export const AI_VERSION_SUFFIX = '-ai';
export const isAiVersion = (version: string) => version.trim().endsWith(AI_VERSION_SUFFIX);

export interface TrainingFilters {
  family: TrainingFamily | '';
  split: '' | 'train' | 'eval' | 'holdout';
  show: ReviewShow;
  isFailure: '' | 'true' | 'false';
  deviceModel: string;
  balance: boolean;
  /** "Confusable pairs": only samples flagged label_conflict. */
  confusable: boolean;
}

interface ListResponse {
  success: boolean;
  samples: TrainingSample[];
  total: number;
}

interface LabelResponse {
  success: boolean;
  ground_truth: unknown;
  is_failure: boolean;
  label_conflict: boolean;
  triage: TriageRecord | null;
}

interface EvalCountsResponse {
  success: boolean;
  /** Human-verified eval rows not frozen. */
  counts: Record<TrainingFamily, number>;
  /** Step 4i: AI-verified eval rows (the teacher agreed with the run label), not frozen. */
  agreed_counts: Record<TrainingFamily, number>;
  threshold: number;
  ai_threshold: number;
}

interface OfftreeLabelsResponse {
  success: boolean;
  labels: string[];
}

/** Step 4k: one node of a screen group, with what is focused on it (null: the group itself). */
export interface ScreenGroupMember {
  node_id: string;
  label: string;
  focus: string | null;
}

/** Step 4k: a screen group; `node_id`/`label` are the screen-id answer. */
export interface ScreenGroup {
  node_id: string;
  label: string;
  members: ScreenGroupMember[];
}

interface ScreenGroupsResponse {
  success: boolean;
  found: boolean;
  groups: ScreenGroup[];
}

export interface CoverageState {
  node_id: string;
  label: string;
  focus: string | null;
  samples: number;
}

/** A screen of the coverage report: since step 4k a screen group, with its focus states. */
export interface CoverageScreen {
  node_id: string;
  label: string;
  samples: number;
  states?: CoverageState[];
  states_total?: number;
  states_covered?: number;
}

export interface CoverageApp {
  name: string;
  platform: string;
  models: string[];
  screens: number;
  node_rows: number;
  screens_ge1: number;
  screens_gek: number;
  pct_gek: number;
  screen_id_labelled: number;
  seeded_rows: number;
  eval_verified: number;
  offtree_labels: string[];
  stale_labels: string[];
  missing_screens: CoverageScreen[];
  thin_screens: CoverageScreen[];
  /** Step 4k: every screen group of the app (group -> member nodes), and the node count. */
  groups?: CoverageScreen[];
  node_screens?: number;
  grouped?: boolean;
  focus: { rows: number; labelled: number; eval_verified: number };
}

export interface CoveragePlatform {
  platform: string;
  apps: string[];
  screens: number;
  screens_ge1: number;
  screens_gek: number;
  pct_gek: number;
  eval_verified: number;
  banner: { rows?: number; labelled?: number; eval_verified?: number };
}

export interface CoverageReport {
  k: number;
  global: { screens: number; screens_ge1: number; screens_gek: number; eval_verified: number; exhaustiveness_pct: number };
  platforms: CoveragePlatform[];
  apps: CoverageApp[];
  not_in_scope: { name: string; platform: string; screens: number; reason: string }[];
  canonical_missing: string[];
}

interface FreezeResponse {
  success: boolean;
  frozen: number;
}

export const PAGE_SIZE = 50;

const buildListQuery = (filters: TrainingFilters, offset: number, limit = PAGE_SIZE): string => {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (filters.family) params.set('family', filters.family);
  if (filters.split) params.set('split', filters.split);
  if (SHOW_LABEL_SOURCES[filters.show]) params.set('label_source', SHOW_LABEL_SOURCES[filters.show]);
  if (filters.show === 'needs_you') params.set('triage', 'needs_human');
  if (filters.isFailure) params.set('is_failure', filters.isFailure);
  if (filters.deviceModel.trim()) params.set('device_model', filters.deviceModel.trim());
  if (filters.balance && filters.show !== 'needs_you') params.set('balance', 'device_model');
  if (filters.confusable) params.set('label_conflict', 'true');
  return params.toString();
};

export function useTrainingSamples() {
  const [samples, setSamplesState] = useState<TrainingSample[]>([]);
  // Mirror of `samples` so load() can tell synchronously how many rows were new.
  const samplesRef = useRef<TrainingSample[]>([]);
  const setSamples = useCallback((next: TrainingSample[]) => {
    samplesRef.current = next;
    setSamplesState(next);
  }, []);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [evalCounts, setEvalCounts] = useState<Partial<Record<TrainingFamily, number>>>({});
  const [evalThreshold, setEvalThreshold] = useState(200);
  const [agreedCounts, setAgreedCounts] = useState<Partial<Record<TrainingFamily, number>>>({});
  const [aiThreshold, setAiThreshold] = useState(50);

  /** Per family: verified eval rows the next freeze would take. */
  const loadEvalCounts = useCallback(async () => {
    try {
      const data = await api.get<EvalCountsResponse>(buildServerUrl('/server/training-samples/eval-counts'));
      setEvalCounts(data.counts);
      setEvalThreshold(data.threshold);
      setAgreedCounts(data.agreed_counts ?? {});
      setAiThreshold(data.ai_threshold ?? 50);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  /**
   * Load one page. `append` keeps what is already loaded (paging forward) and skips
   * rows already in the list. Returns how many rows the server returned and how many
   * were new. `total` is only taken from a fresh load (not `append`): it is what was
   * left to check when the page was (re)loaded, and stays fixed while paging.
   */
  const load = useCallback(async (filters: TrainingFilters, offset = 0, append = false) => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.get<ListResponse>(
        buildServerUrl(`/server/training-samples/list?${buildListQuery(filters, offset)}`),
      );
      const prev = append ? samplesRef.current : [];
      const seen = new Set(prev.map((s) => s.id));
      const fresh = data.samples.filter((s) => !seen.has(s.id));
      setSamples([...prev, ...fresh]);
      if (!append) setTotal(data.total);
      return { returned: data.samples.length, added: fresh.length };
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return { returned: 0, added: 0 };
    } finally {
      setIsLoading(false);
    }
  }, [setSamples]);

  /**
   * Write a human label. `remove` drops the row from the list (the "not checked yet"
   * view); otherwise it is updated in place. Throws on refusal (400/409).
   */
  /**
   * Save a human answer. With `remove` (a view the answer takes the row out of), the row leaves
   * the list at once, so the page can show the next sample without waiting for the server; if
   * the save fails it is put back where it was and the error is thrown.
   */
  const label = useCallback(async (sample: TrainingSample, groundTruth: unknown, remove = false) => {
    const sampleId = sample.id;
    const position = samplesRef.current.findIndex((s) => s.id === sampleId);
    if (remove) setSamples(samplesRef.current.filter((s) => s.id !== sampleId));
    let data: LabelResponse;
    try {
      data = await api.post<LabelResponse>(
        buildServerUrl(`/server/training-samples/${encodeURIComponent(sampleId)}/label`),
        { ground_truth: groundTruth, label_source: 'human' },
      );
    } catch (e) {
      const now = samplesRef.current;
      if (remove && position >= 0 && !now.some((s) => s.id === sampleId)) {
        setSamples([...now.slice(0, position), sample, ...now.slice(position)]);
      }
      throw e;
    }
    // A newly human-verified eval row counts towards the next freeze; an AI-agreed row
    // it replaces no longer counts as AI-verified.
    if (sample.split === 'eval' && sample.label_source !== 'human' && !sample.eval_version) {
      setEvalCounts((prev) => ({ ...prev, [sample.family]: (prev[sample.family] ?? 0) + 1 }));
      if (sample.triage?.status === 'agreed') {
        setAgreedCounts((prev) => ({ ...prev, [sample.family]: Math.max(0, (prev[sample.family] ?? 0) - 1) }));
      }
    }
    if (!remove) {
      setSamples(samplesRef.current.map((s) =>
        s.id === sampleId
          ? {
              ...s,
              ground_truth: data.ground_truth,
              proposed_label: data.ground_truth,
              guess_source: 'human',
              label_source: 'human',
              is_failure: data.is_failure,
              label_conflict: data.label_conflict,
              triage: data.triage ?? s.triage ?? null,
            }
          : s,
      ));
    }
    return data;
  }, [setSamples]);

  /**
   * Freeze an eval version for one family. `minRows` only applies to an `eval-vN-ai` pilot.
   * Throws on refusal (400 below threshold, 409 exists).
   */
  const freeze = useCallback(async (family: TrainingFamily, version: string, minRows?: number) => {
    const body: Record<string, unknown> = { family, version };
    if (isAiVersion(version) && minRows !== undefined) body.min_rows = minRows;
    return api.post<FreezeResponse>(buildServerUrl('/server/training-samples/freeze'), body);
  }, []);

  /** Suggestions for a screen-id frame showing a screen not in the tree: starters + saved ones. */
  const loadOfftreeLabels = useCallback(async (): Promise<string[]> => {
    try {
      const data = await api.get<OfftreeLabelsResponse>(buildServerUrl('/server/training-samples/offtree-labels'));
      return data.labels;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return [];
    }
  }, []);

  /** Step 4h: coverage of the canonical apps (screens with >= k labelled screen-id samples). */
  const loadCoverage = useCallback(async (k = 3): Promise<CoverageReport | null> => {
    try {
      return await api.get<CoverageReport>(buildServerUrl(`/server/training-samples/coverage?k=${k}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }, []);

  /**
   * How many samples match `filters`, without touching the list (one-row page, `total`).
   * null when the count failed: the caller then says nothing rather than a wrong number.
   */
  const countSamples = useCallback(async (filters: TrainingFilters): Promise<number | null> => {
    try {
      const data = await api.get<ListResponse>(
        buildServerUrl(`/server/training-samples/list?${buildListQuery(filters, 0, 1)}`),
      );
      return data.total;
    } catch {
      return null;
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return {
    samples, total, isLoading, error, evalCounts, evalThreshold, agreedCounts, aiThreshold,
    load, countSamples, loadEvalCounts, loadOfftreeLabels, loadCoverage, label, freeze, clearError,
  };
}

// ─── Step 4k: screen groups ──────────────────────────────────────────────────

const groupCache = new Map<string, Promise<ScreenGroup[]>>();

const fetchScreenGroups = (userinterface: string): Promise<ScreenGroup[]> => {
  const cached = groupCache.get(userinterface);
  if (cached) return cached;
  const request = api
    .get<ScreenGroupsResponse>(buildServerUrl(
      `/server/training-samples/screen-groups?userinterface=${encodeURIComponent(userinterface)}`))
    .then((data) => data.groups ?? [])
    .catch(() => {
      groupCache.delete(userinterface);
      return [] as ScreenGroup[];
    });
  groupCache.set(userinterface, request);
  return request;
};

/** The screen groups of one app (cached per page load). Empty while loading or without a tree. */
export function useScreenGroups(userinterface: string | null | undefined) {
  const [groups, setGroups] = useState<ScreenGroup[]>([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let alive = true;
    if (!userinterface) {
      setGroups([]);
      return undefined;
    }
    setLoading(true);
    void fetchScreenGroups(userinterface).then((g) => {
      if (alive) {
        setGroups(g);
        setLoading(false);
      }
    });
    return () => {
      alive = false;
    };
  }, [userinterface]);
  return { groups, loading };
}
