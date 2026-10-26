import { useCallback, useEffect, useRef, useState } from 'react';

import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

export type CoreSource = 'github' | 'zip';
export type OverlaySource = 'gitlab' | 'github' | 'zip' | 'none';
export type CheckStatus = 'ok' | 'ko' | 'na';

/** A root command an admin runs on one machine to fix a KO (TASK-128). The page shows it with a Copy button; the app never runs it. */
export interface CheckAction {
  machine: string;
  command: string;
  reason: string;
}

/** One prerequisite of a Platform update (TASK-101), as returned by GET /server/platform-update/prerequisites. */
export interface PrerequisiteCheck {
  id: string;
  title: string;
  required: boolean;
  status: CheckStatus;
  detail: string;
  log: string;
  fix: string;
  /** Section id in docs/user-guide/platform-update.md (inside step 0). */
  doc_anchor: string;
  /** Commands to run as root on the named machines; only on a KO row, and only for checks that can name one. */
  actions?: CheckAction[];
  /** Hosts the page can update once itself (TASK-128 G11); only on the host version row. */
  update_hosts?: string[];
}

export interface PrerequisitesResult {
  ok: boolean;
  passed: number;
  total: number;
  checks: PrerequisiteCheck[];
}

/** Runs the checks on mount and whenever the chosen sources change; `recheck()` runs them again. */
export const usePrerequisites = (core: CoreSource, overlay: OverlaySource) => {
  const [result, setResult] = useState<PrerequisitesResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  const recheck = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient(buildServerUrl(`/server/platform-update/prerequisites?core=${core}&overlay=${overlay}`));
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.success === false) throw new Error(data.error || data.message || `HTTP ${response.status}`);
      if (mine === seq.current) setResult(data as PrerequisitesResult);
    } catch (e) {
      if (mine === seq.current) setError(e instanceof Error ? e.message : 'Request failed');
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [core, overlay]);

  useEffect(() => {
    void recheck();
  }, [recheck]);

  const blocking = (result?.checks ?? []).filter((c) => c.required && c.status === 'ko');
  return { result, loading, error, recheck, blocking };
};
