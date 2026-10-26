/**
 * A `<tbody>` must live inside the same `<table>` as the `<thead>` it belongs to.
 *
 * This is not a style preference — it is the whole mechanism a `<table>` uses to put a header
 * cell over the body cell below it. Break the nesting and the browser builds TWO independent
 * tables: the head keeps `tableLayout: fixed` and its % widths and fills the card, while the
 * orphaned body falls back to content-based auto layout and shrink-to-fit. Every column then
 * drifts further from its header the further right it sits, and the body loses the `py: 0.5`
 * override scoped to the head's `<Table>`, so rows render at the theme's default padding.
 *
 * BUG-0768: 57f6cdac9 hoisted the whole `<Table>` (header included) into a `…Shell` const in
 * three pages so the loading skeleton would share the live table's geometry. The `<TableBody>`
 * written below the shell was left as a SIBLING of the table, so it escaped it. Measured on the
 * deployed /configuration/interface before the fix: header table 1132px wide, body table 823px;
 * Models 12px off its header, Version 86px, Variants 172px, Actions 250px; rows 60px instead of
 * 29px.
 *
 * The assertion is DOM structure, not computed style — jsdom resolves it, so unlike an `sx`-class
 * check it is a real test here rather than one that silently passes on an empty stylesheet.
 */
import { render } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

const state = vi.hoisted(() => ({ loading: false, rows: [] as unknown[], models: [] as unknown[] }));
afterEach(() => {
  state.loading = false;
  state.rows = [];
  state.models = [];
});

vi.mock('../../frontend/src/hooks/pages/useUserInterface', () => ({
  useUserInterface: () => ({
    getAllUserInterfaces: async () => state.rows,
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
    models: state.models,
    supportedModels: [],
    isLoading: state.loading,
    error: null,
    refetch: () => {},
    createModel: async () => {},
    updateModel: async () => {},
    deleteModel: async () => {},
    isCreating: false,
    isDeleting: false,
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
    addVariant: async () => ({ variant: { name: '' } }),
    updateVariant: async () => {},
    updateVariantOverrides: async () => ({}),
    deleteVariant: async () => ({ nodes: 0, edges: 0 }),
    renameVariant: async () => ({ nodes: 0, edges: 0 }),
  }),
}));

vi.mock('../../frontend/src/hooks/pages/useUserInterfaceReferences', () => ({
  useUserInterfaceReferences: () => ({
    references: state.rows,
    loading: state.loading,
    error: null,
    refetch: () => {},
  }),
}));

vi.mock('../../frontend/src/components/verification/ReferenceHistoryModal', () => ({
  ReferenceHistoryModal: () => null,
}));

vi.mock('../../frontend/src/components/verification/ReferenceImagePreview', () => ({
  ReferenceImagePreview: () => null,
}));

import Models from '../../frontend/src/pages/Models';
import UserInterface from '../../frontend/src/pages/UserInterface';
import UserInterfaceReferencesPage from '../../frontend/src/pages/UserInterfaceReferences';

/**
 * The invariant, in one place so each page below only has to say "render me".
 * Fails loudly, naming the page, because the symptom — two tables — is invisible in a
 * snapshot diff and only shows up as drifted pixels.
 */
const expectBodiesInsideTables = (label: string, container: HTMLElement) => {
  const bodies = container.querySelectorAll('tbody');
  expect(bodies.length, `${label}: no <tbody> rendered — the assertion below would pass vacuously`).toBeGreaterThan(0);

  bodies.forEach((body, i) => {
    const table = body.closest('table');
    expect(table, `${label}: <tbody> #${i} has no <table> ancestor — it is a sibling of the table`).not.toBeNull();
    // Same table as the header, which is what makes the columns line up.
    expect(
      table?.querySelector('thead'),
      `${label}: <tbody> #${i} is in a different table from the <thead>`,
    ).not.toBeNull();

    const headCells = table?.querySelectorAll('thead th').length ?? 0;
    const bodyRow = body.querySelector('tr');
    if (bodyRow) {
      const bodyCells = bodyRow.querySelectorAll('td, th').length;
      expect(bodyCells, `${label}: <tbody> #${i} row has ${bodyCells} cells, header has ${headCells}`).toBe(
        headCells,
      );
    }
  });
};

const MODEL_ROWS = [
  { id: 'm1', name: 'example_tv', types: ['example'], version: '1.0', description: 'Example', is_default: true },
];

const UI_ROWS = [
  { id: 'u1', name: 'example_ui', models: ['example_tv'], mode: 'dev', min_version: null, max_version: null },
];

const REF_ROWS = [
  { id: 'r1', type: 'text', name: 'example_ref', text: 'hello', area: null, shared: false, created_at: '2026-01-01', updated_at: '2026-01-01' },
];

describe('BUG-0768 — the table body is inside the header’s table', () => {
  describe('/configuration/models', () => {
    it('holds while the placeholder rows are showing', () => {
      state.loading = true;
      const { container } = render(
        <BrowserRouter>
          <Models />
        </BrowserRouter>,
      );
      expectBodiesInsideTables('Models (loading)', container);
    });

    it('holds once the real rows are showing', () => {
      state.models = MODEL_ROWS;
      const { container } = render(
        <BrowserRouter>
          <Models />
        </BrowserRouter>,
      );
      expectBodiesInsideTables('Models (live)', container);
    });
  });

  describe('/configuration/interface', () => {
    it('holds while the placeholder rows are showing', () => {
      state.loading = true;
      const { container } = render(
        <BrowserRouter>
          <UserInterface />
        </BrowserRouter>,
      );
      expectBodiesInsideTables('Interface (loading)', container);
    });

    it('holds once the real rows are showing', async () => {
      state.rows = UI_ROWS;
      const { container, findByText } = render(
        <BrowserRouter>
          <UserInterface />
        </BrowserRouter>,
      );
      // The page fills its own state from getAllUserInterfaces, not from `state.rows` directly.
      await findByText('example_ui');
      expectBodiesInsideTables('Interface (live)', container);
    });
  });

  describe('/configuration/interface/:name/references', () => {
    it('holds while the placeholder rows are showing', () => {
      state.loading = true;
      const { container } = render(
        <BrowserRouter>
          <UserInterfaceReferencesPage />
        </BrowserRouter>,
      );
      expectBodiesInsideTables('References (loading)', container);
    });

    it('holds once the real rows are showing', () => {
      state.rows = REF_ROWS;
      const { container } = render(
        <BrowserRouter>
          <UserInterfaceReferencesPage />
        </BrowserRouter>,
      );
      expectBodiesInsideTables('References (live)', container);
    });
  });
});