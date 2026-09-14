import { useCallback, useEffect, useState } from 'react';

import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

export interface UserInterfaceReferenceArea {
  x: number;
  y: number;
  width: number;
  height: number;
  text?: string;
  font_size?: number;
  confidence?: number;
  fx?: number;
  fy?: number;
  fwidth?: number;
  fheight?: number;
}

export interface UserInterfaceReference {
  id: string;
  name: string;
  type: 'image' | 'text';
  url: string;
  text?: string;
  area: UserInterfaceReferenceArea;
  shared: boolean;
  created_at: string;
  updated_at: string;
}

interface UseUserInterfaceReferencesResult {
  references: UserInterfaceReference[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export const useUserInterfaceReferences = (
  userInterfaceName: string | undefined,
): UseUserInterfaceReferencesResult => {
  const [references, setReferences] = useState<UserInterfaceReference[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const refetch = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    if (!userInterfaceName) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const url = buildServerUrl(
          `/server/verification/getAllReferences?userinterface_name=${encodeURIComponent(userInterfaceName)}`,
        );
        const response = await apiClient(url, { method: 'POST' });
        if (!response.ok) {
          throw new Error(`Failed to load references (HTTP ${response.status})`);
        }
        const result = await response.json();
        if (cancelled) return;
        if (!result?.success || !Array.isArray(result.references)) {
          setReferences([]);
          return;
        }

        const normalised: UserInterfaceReference[] = result.references.map((ref: any) => {
          const type: 'image' | 'text' = ref.reference_type === 'reference_text' ? 'text' : 'image';
          const area = ref.area || { x: 0, y: 0, width: 0, height: 0 };
          return {
            id: ref.id,
            name: ref.name || '',
            type,
            url: ref.r2_url || '',
            text: type === 'text' ? area.text : undefined,
            area,
            shared: Boolean(ref.shared),
            created_at: ref.created_at,
            updated_at: ref.updated_at,
          };
        });

        setReferences(normalised);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load references');
        setReferences([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [userInterfaceName, reloadKey]);

  return { references, loading, error, refetch };
};
