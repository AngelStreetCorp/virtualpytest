import { useCallback, useState } from 'react';

import { api } from '../../../../frontend/src/utils/apiClient';
import { buildServerUrl } from '../../../../frontend/src/utils/buildUrlUtils';

export type VirtualScriptEnv = 'dev' | 'test' | 'prod';

export interface VirtualScriptFolder {
  folder_id: number;
  name: string;
}

export interface VirtualScriptMeta {
  id: string;
  name: string;
  description?: string | null;
  target_rules?: Record<string, any> | null;
  created_by?: string | null;
  created_at?: string;
  updated_at?: string;
  // Lifecycle: per-environment row ids (dev always present; test/prod created on
  // promote) and the current prod version counter.
  environments?: Record<VirtualScriptEnv, string | null>;
  prod_version?: number | null;
  // Shared folder taxonomy (same as testcases/disk scripts) — resolved name,
  // defaults to '(Root)' when unassigned.
  folder?: string | null;
}

export interface VirtualScriptFull extends VirtualScriptMeta {
  source: string;
  doc?: string | null;
}

export interface VirtualScriptParam {
  name: string;
  dataType?: string;
  default?: string;
  choices?: string[];
  required?: boolean;
  description?: string;
}

export interface VirtualScriptValidation {
  valid: boolean;
  error?: { line: number; offset: number; msg: string; text?: string } | null;
  warnings?: string[];
}

export interface VirtualScriptVersion {
  version_number: number | null;
  name?: string;
  description?: string | null;
  snapshot_timestamp?: string;
  change_description?: string;
  is_current?: boolean;
}

export const useVirtualScripts = () => {
  const [scripts, setScripts] = useState<VirtualScriptMeta[]>([]);
  const [folders, setFolders] = useState<VirtualScriptFolder[]>([]);
  const [loading, setLoading] = useState(false);

  const listScripts = useCallback(async (): Promise<VirtualScriptMeta[]> => {
    setLoading(true);
    try {
      const res = await api.get<{
        success: boolean;
        scripts: VirtualScriptMeta[];
        folders?: VirtualScriptFolder[];
      }>(buildServerUrl('/server/virtual-script/list'));
      const list = res?.scripts || [];
      setScripts(list);
      setFolders(res?.folders || []);
      return list;
    } finally {
      setLoading(false);
    }
  }, []);

  const getScript = useCallback(async (id: string) => {
    return api.get<{ success: boolean; script: VirtualScriptFull; parameters: VirtualScriptParam[] }>(
      buildServerUrl(`/server/virtual-script/${id}`),
    );
  }, []);

  const validateSource = useCallback(async (source: string) => {
    const res = await api.post<{ success: boolean; validation: VirtualScriptValidation }>(
      buildServerUrl('/server/virtual-script/validate'),
      { source },
    );
    return res?.validation;
  }, []);

  const analyzeSource = useCallback(async (source: string, name?: string) => {
    const res = await api.post<{ success: boolean; parameters: VirtualScriptParam[] }>(
      buildServerUrl('/server/virtual-script/analyze'),
      { source, name },
    );
    return res?.parameters || [];
  }, []);

  const saveScript = useCallback(
    async (payload: {
      id?: string;
      name: string;
      source: string;
      description?: string;
      doc?: string;
      folder?: string;
    }) => {
      return api.post<{
        success: boolean;
        id?: string;
        error?: string;
        validation?: VirtualScriptValidation;
        parameters?: VirtualScriptParam[];
        script?: Partial<VirtualScriptFull>;
      }>(buildServerUrl('/server/virtual-script/save'), payload);
    },
    [],
  );

  const deleteScript = useCallback(async (id: string) => {
    return api.delete<{ success: boolean }>(buildServerUrl(`/server/virtual-script/${id}`));
  }, []);

  const getVersions = useCallback(async (id: string) => {
    const res = await api.get<{ success: boolean; versions: VirtualScriptVersion[] }>(
      buildServerUrl(`/server/virtual-script/${id}/versions`),
    );
    return res?.versions || [];
  }, []);

  const restoreVersion = useCallback(async (id: string, versionNumber: number) => {
    return api.post<{ success: boolean; script?: VirtualScriptFull }>(
      buildServerUrl(`/server/virtual-script/${id}/restore/${versionNumber}`),
    );
  }, []);

  // Promote one lifecycle step: dev->test or test->prod. Copies source into the
  // target env row; on prod the previous prod is kept as N-1 for rollback.
  const promoteScript = useCallback(async (id: string, targetEnv: 'test' | 'prod') => {
    return api.post<{
      success: boolean;
      error?: string;
      target_env?: VirtualScriptEnv;
      prod_version?: number | null;
    }>(buildServerUrl(`/server/virtual-script/${id}/promote`), { target_env: targetEnv });
  }, []);

  // Convert an existing on-disk script into a virtual script (upserts the dev row).
  const convertScript = useCallback(async (scriptName: string) => {
    return api.post<{
      success: boolean;
      error?: string;
      action?: 'created' | 'updated';
      id?: string;
      name?: string;
    }>(buildServerUrl('/server/virtual-script/convert'), { script_name: scriptName });
  }, []);

  return {
    scripts,
    folders,
    loading,
    listScripts,
    getScript,
    validateSource,
    analyzeSource,
    saveScript,
    deleteScript,
    getVersions,
    restoreVersion,
    promoteScript,
    convertScript,
  };
};
