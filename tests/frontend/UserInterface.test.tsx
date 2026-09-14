import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../../frontend/src/hooks/pages/useUserInterface', () => ({
  useUserInterface: () => ({
    getAllUserInterfaces: async () => [],
    updateUserInterfaceWithValidation: async () => ({}),
    deleteUserInterface: async () => {},
    createUserInterfaceWithValidation: async () => ({}),
    duplicateUserInterface: async () => ({}),
    publishUserInterface: async () => ({}),
    exportUserInterface: async () => {},
    importUserInterface: async () => ({}),
  }),
}));

vi.mock('../../frontend/src/hooks/pages/useDeviceModels', () => ({
  useDeviceModels: () => ({
    models: [],
    isLoading: false,
    error: null,
    refetch: () => {},
    createModel: async () => {},
    updateModel: async () => {},
    deleteModel: async () => {},
    isCreating: false,
    isUpdating: false,
    isDeleting: false,
    createError: null,
    updateError: null,
    deleteError: null,
  }),
}));

vi.mock('../../frontend/src/hooks/userinterface/useUserInterfaceVariants', () => ({
  primeAllVariants: async () => {},
  useUserInterfaceVariants: () => ({
    variants: [],
    loading: false,
    error: null,
    refresh: async () => {},
    refetch: async () => {},
    addVariant: async () => ({ variant: { name: '', description: '', node_overrides: {}, edge_overrides: {} } }),
    updateVariant: async () => {},
    updateVariantOverrides: async () => ({ name: '', description: '', node_overrides: {}, edge_overrides: {} }),
    deleteVariant: async () => ({ nodes: 0, edges: 0 }),
    renameVariant: async () => ({ nodes: 0, edges: 0 }),
  }),
}));

import UserInterface from '../../frontend/src/pages/UserInterface';

describe('UserInterface page', () => {
  it('renders the Interface heading', async () => {
    render(
      <BrowserRouter>
        <UserInterface />
      </BrowserRouter>,
    );

    expect(await screen.findByRole('heading', { name: 'Interface' })).toBeInTheDocument();
  });
});
