import { useCallback, useState } from 'react';

import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

// Sources the bundle can be built from (TASK-99), as listed by `customer_bundle.py candidates` on this server.

export interface CoreRef {
  ref: string;
  sha: string;
}

export interface BundleSources {
  core: { github: { usable: boolean; error: string; remote: string; refs: CoreRef[] } };
  overlay: {
    gitlab: { usable: boolean; reason: string; error: string; refs: string[] };
    github: { usable: boolean; token_set: boolean };
  };
  gitlab_instance: { configured: boolean; base_url: string };
}

/** The core release tag that is build `wanted` (a tag equal to it, or ending in `-<wanted>`), if the core remote has one. */
export const findCoreTag = (refs: CoreRef[], wanted: string | null): string | undefined =>
  wanted ? refs.find((r) => r.ref === wanted || r.ref.split('-').pop() === wanted)?.ref : undefined;

export interface UploadedZip {
  id: string;
  name: string;
}

export interface BundleInfo {
  name: string;
  path: string;
  size: number;
  sha256: string;
  delivery_note: string;
  dir: string;
}

/** Loads the source lists and uploads zips through the existing source-upload store (one store, one set of limits). */
export const useBundleSources = () => {
  const [sources, setSources] = useState<BundleSources | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (project = '') => {
    setLoading(true);
    setError(null);
    try {
      const query = project ? `?project=${encodeURIComponent(project)}` : '';
      const response = await apiClient(buildServerUrl(`/server/platform-update/bundle/sources${query}`));
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || `HTTP ${response.status}`);
      setSources(data as BundleSources);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed');
    } finally {
      setLoading(false);
    }
  }, []);

  const uploadZip = useCallback(async (file: File): Promise<UploadedZip> => {
    const form = new FormData();
    form.append('file', file);
    const response = await apiClient(buildServerUrl('/server/system/source/zip/upload'), { method: 'POST', body: form });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.success) throw new Error(data.error || `HTTP ${response.status}`);
    return { id: data.upload_id as string, name: file.name };
  }, []);

  const fetchDeliveryNote = useCallback(async (runId: string): Promise<string> => {
    const response = await apiClient(buildServerUrl(`/server/platform-update/runs/${runId}/bundle/delivery-note`));
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.text();
  }, []);

  return { sources, loading, error, load, uploadZip, fetchDeliveryNote };
};
