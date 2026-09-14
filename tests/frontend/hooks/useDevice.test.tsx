import { renderHook, waitFor } from '@testing-library/react';
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const testState = vi.hoisted(() => ({
  apiGet: vi.fn(),
}));

vi.mock('../../../frontend/src/utils/buildUrlUtils', () => ({
  buildServerUrl: (path: string) => path,
}));

vi.mock('../../../frontend/src/utils/apiClient', () => ({
  api: {
    get: testState.apiGet,
  },
}));

import { useDeviceModels } from '../../../frontend/src/hooks/pages/useDeviceModels';

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

describe('useDevice hook behavior', () => {
  beforeEach(() => {
    testState.apiGet.mockReset();
  });

  it('handles empty device-model response', async () => {
    testState.apiGet.mockResolvedValueOnce([]);

    const { result } = renderHook(() => useDeviceModels(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.error).toBeNull();
    expect(result.current.models).toEqual([]);
  });

  it('handles populated device-model response', async () => {
    testState.apiGet.mockResolvedValueOnce([
      {
        id: 'model-1',
        name: 'Android TV',
        types: ['remote'],
      },
    ]);

    const { result } = renderHook(() => useDeviceModels(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.error).toBeNull();
    expect(result.current.models).toHaveLength(1);
    expect(result.current.models[0]?.name).toBe('Android TV');
  });
});
