import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const testState = vi.hoisted(() => ({
  selectedServer: 'https://server-a.example',
  isAuthenticated: true,
  apiGet: vi.fn(),
}));

vi.mock('../../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({
    selectedServer: testState.selectedServer,
  }),
}));

vi.mock('../../../frontend/src/hooks/auth/useAuth', () => ({
  useAuth: () => ({
    isAuthenticated: testState.isAuthenticated,
  }),
}));

vi.mock('../../../frontend/src/lib/supabase', () => ({
  isAuthEnabled: false,
}));

vi.mock('../../../frontend/src/utils/buildUrlUtils', () => ({
  buildSelectedServerUrl: (path: string) => path,
}));

vi.mock('../../../frontend/src/utils/apiClient', () => ({
  api: {
    get: testState.apiGet,
  },
}));

import { useDashboard } from '../../../frontend/src/hooks/pages/useDashboard';

describe('useDashboard hook', () => {
  beforeEach(() => {
    testState.apiGet.mockReset();
    testState.isAuthenticated = true;
  });

  it('returns expected structure for populated API responses', async () => {
    testState.selectedServer = 'https://server-a.example';
    testState.apiGet
      .mockResolvedValueOnce({ success: true, campaigns: [{ campaign_id: 'c1', campaign_name: 'Campaign 1' }] })
      .mockResolvedValueOnce({ success: true, testcases: [{ test_id: 't1', name: 'Test 1' }, { test_id: 't2', name: 'Test 2' }] })
      .mockResolvedValueOnce({ success: true, trees: [{ id: 'n1' }, { id: 'n2' }, { id: 'n3' }] });

    const { result } = renderHook(() => useDashboard());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toBeNull();
    expect(result.current.stats.testCases).toBe(2);
    expect(result.current.stats.campaigns).toBe(1);
    expect(result.current.stats.trees).toBe(3);
    expect(Array.isArray(result.current.stats.recentActivity)).toBe(true);
  });

  it('handles empty API responses', async () => {
    testState.selectedServer = 'https://server-b.example';
    testState.apiGet
      .mockResolvedValueOnce({ success: true, campaigns: [] })
      .mockResolvedValueOnce({ success: true, testcases: [] })
      .mockResolvedValueOnce({ success: true, trees: [] });

    const { result } = renderHook(() => useDashboard());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toBeNull();
    expect(result.current.stats.testCases).toBe(0);
    expect(result.current.stats.campaigns).toBe(0);
    expect(result.current.stats.trees).toBe(0);
  });
});
