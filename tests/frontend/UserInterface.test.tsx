import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

const rows = vi.hoisted(() => [] as unknown[]);
// Variants are keyed by interface id so a row can be given some. The "model chips only" test needs
// a real one: `OneLineChips` drives BOTH the Models and the Variants column, and only the Models
// column is a filter.
const variantNames = vi.hoisted(() => ({ byId: {} as Record<string, string[]> }));
afterEach(() => {
  rows.length = 0;
  variantNames.byId = {};
});

vi.mock('../../frontend/src/hooks/userinterface/useUserInterfaceVariants', () => ({
  primeAllVariants: async () => {},
  useUserInterfaceVariants: (id: string) => ({
    variants: (variantNames.byId[id] || []).map((name) => ({ name, description: '' })),
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

vi.mock('../../frontend/src/hooks/pages/useUserInterface', () => ({
  useUserInterface: () => ({
    getAllUserInterfaces: async () => rows,
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

import UserInterface from '../../frontend/src/pages/UserInterface';

describe('UserInterface page', () => {
  it('renders the Interface heading', async () => {
    render(
      <BrowserRouter>
        <UserInterface />
      </BrowserRouter>,
    );

    expect(await screen.findByRole('heading', { name: /^Interface \(\d+\)$/ })).toBeInTheDocument();
  });
});

/**
 * The row's name is the link to that interface — the navigation editor, the same destination the
 * Navigation column's icon button opens. It was the only way in before, which made a name that
 * reads like a link do nothing.
 *
 * Asserted as a real anchor with an `href`, because that is the part that cannot silently rot: an
 * `onClick` on a `div` could have satisfied "clicking the name navigates" in a test while still
 * being unreachable by keyboard, invisible to a screen reader as a link, and dead to
 * middle-click. The `?mode=prod` case is separate because the name is shared between the dev and
 * prod rows, so a deep link without it is ambiguous.
 */
describe('UserInterface page — the name opens the interface', () => {
  const renderWith = async (...uis: Record<string, unknown>[]) => {
    rows.push(...uis);
    render(
      <BrowserRouter>
        <UserInterface />
      </BrowserRouter>,
    );
    return screen.findAllByRole('link', { name: uis[0].name as string });
  };

  it('links a dev row’s name to its navigation editor', async () => {
    const [link] = await renderWith({
      id: 'u1',
      name: 'example_ui',
      models: ['example_tv'],
      mode: 'dev',
      min_version: null,
      max_version: null,
    });

    expect(link.tagName).toBe('A');
    expect(link).toHaveAttribute('href', expect.stringContaining('/navigation-editor/example_ui'));
  });

  it('keeps ?mode=prod on a prod row, since the name is shared with its dev row', async () => {
    // A prod row is listed only next to the dev row it was published from — the page pairs them
    // by `dev_userinterface_id` — so both have to be present for the prod link to render at all.
    const links = await renderWith(
      {
        id: 'u1',
        name: 'example_ui',
        models: ['example_tv'],
        mode: 'dev',
        min_version: null,
        max_version: null,
      },
      {
        id: 'u2',
        name: 'example_ui',
        models: ['example_tv'],
        mode: 'prod',
        dev_userinterface_id: 'u1',
        min_version: '1.0',
        max_version: '2.0',
      },
    );

    expect(links).toHaveLength(2);
    // The dev row opens the editor plain; the prod row's link must say so, or a name that appears
    // twice on the page opens the same editor twice and the read-only snapshot is unreachable.
    expect(links[0]).toHaveAttribute('href', expect.stringContaining('/navigation-editor/example_ui'));
    expect(links[0].getAttribute('href')).not.toContain('mode=prod');
    expect(links[1]).toHaveAttribute('href', expect.stringContaining('mode=prod'));
  });

  it('encodes the name, so a name with a slash still resolves', async () => {
    const [link] = await renderWith({
      id: 'u3',
      name: 'example/odd name',
      models: [],
      mode: 'dev',
      min_version: null,
      max_version: null,
    });

    // `/navigation-editor/example%2Fodd%20name`, not a path that would split into two segments.
    expect(link).toHaveAttribute(
      'href',
      expect.stringContaining('/navigation-editor/example%2Fodd%20name'),
    );
  });
});

/**
 * The model filter, reachable two ways over one piece of state: the dropdown in the toolbar, and
 * clicking a model chip in a row. Clicking the same chip again lifts that one filter.
 *
 * The AND semantics are asserted explicitly rather than left implicit, because "two models
 * selected" has exactly two plausible readings and only one of them narrows the list further each
 * time — which is what a chip you can turn back off implies. A regression to OR would still
 * "filter by model", so it has to be pinned by a test.
 */
describe('UserInterface page — filter by model', () => {
  const rowsShown = () => document.querySelectorAll('tbody tr');

  // `web` on three interfaces and `android_tv` on two, which is the point: a model repeated across
  // rows is the normal case, so every chip query below is scoped to its row instead of the page.
  const FACET_ROWS = [
    { id: 'a', name: 'alpha_ui', models: ['web'], mode: 'dev' },
    { id: 'b', name: 'beta_ui', models: ['web', 'android_tv'], mode: 'dev' },
    { id: 'c', name: 'gamma_ui', models: ['web'], mode: 'dev' },
    { id: 'd', name: 'delta_ui', models: ['android_tv'], mode: 'dev' },
    { id: 'e', name: 'epsilon_ui', models: [], mode: 'dev' },
  ];

  const renderList = async (...extra: Record<string, unknown>[]) => {
    rows.push(...FACET_ROWS, ...extra);
    render(
      <BrowserRouter>
        <UserInterface />
      </BrowserRouter>,
    );
    await screen.findByText('alpha_ui');
  };

  // `web` is on three of the five rows, so an unscoped getByRole would be ambiguous by design of
  // the fixture — and in production too. Everything is addressed through the row it belongs to.
  const row = (name: string) => screen.getByText(name).closest('tr') as HTMLElement;
  const modelChip = (name: string, rowName: string) =>
    within(row(rowName)).getByRole('button', { name });

  it('lists every model in use, with how many interfaces use it', async () => {
    await renderList();
    await userEvent.click(screen.getByRole('combobox', { name: 'Filter by model' }));

    // web on alpha + beta + gamma = 3; android_tv on beta + delta = 2. `epsilon_ui` has no model
    // at all, so it contributes to neither facet.
    expect(await screen.findByRole('option', { name: /web/ })).toHaveTextContent('web3');
    expect(screen.getByRole('option', { name: /android_tv/ })).toHaveTextContent('android_tv2');
  });

  it('filters the rows when a model is picked in the dropdown', async () => {
    await renderList();
    await userEvent.click(screen.getByRole('combobox', { name: 'Filter by model' }));
    await userEvent.click(await screen.findByRole('option', { name: /^web/ }));

    expect(rowsShown()).toHaveLength(3);
    expect(screen.getByText('gamma_ui')).toBeInTheDocument();
    expect(screen.queryByText('delta_ui')).not.toBeInTheDocument();
  });

  it('filters when a model chip in a row is clicked, and lifts the filter when clicked again', async () => {
    const user = userEvent.setup();
    await renderList();
    expect(rowsShown()).toHaveLength(5);

    await user.click(modelChip('web', 'alpha_ui'));
    expect(rowsShown()).toHaveLength(3);

    // alpha still passes the filter, so the chip it was clicked on is still on screen — clicking
    // it again is what lifts the filter.
    await user.click(modelChip('web', 'alpha_ui'));
    expect(rowsShown()).toHaveLength(5);
  });

  it('marks the chips that are filtering, and only those', async () => {
    const user = userEvent.setup();
    await renderList();

    // Nothing is filtering yet, so every chip says so — including on a row whose model no other row
    // shares, which would otherwise have no peer to be compared against.
    expect(modelChip('web', 'alpha_ui')).toHaveAttribute('aria-pressed', 'false');
    expect(modelChip('android_tv', 'delta_ui')).toHaveAttribute('aria-pressed', 'false');

    await user.click(modelChip('web', 'alpha_ui'));

    // aria-pressed is what makes the state announceable; MUI puts it on a clickable Chip given an
    // `onClick`, so this asserts the toggle is a real control and not a styled div.
    expect(modelChip('web', 'alpha_ui')).toHaveAttribute('aria-pressed', 'true');
    // Same model, other row: the filtering state belongs to the model, not to the row you clicked.
    expect(modelChip('web', 'gamma_ui')).toHaveAttribute('aria-pressed', 'true');
  });

  it('ANDs several models: both selected shows only the interface carrying both', async () => {
    const user = userEvent.setup();
    await renderList();
    await user.click(modelChip('web', 'alpha_ui'));
    expect(rowsShown()).toHaveLength(3);

    // beta_ui is the row with both models, and its second one sits behind its "+1" chip.
    await user.click(within(row('beta_ui')).getByRole('button', { name: /^Show all 2/ }));
    await user.click(await screen.findByRole('button', { name: 'android_tv' }));

    expect(rowsShown()).toHaveLength(1);
    expect(screen.getByText('beta_ui')).toBeInTheDocument();
  });

  it('combines with the dev/prod toggle rather than replacing it', async () => {
    const user = userEvent.setup();
    await renderList(
      { id: 'f', name: 'zeta_ui', models: ['web'], mode: 'dev' },
      { id: 'g', name: 'eta_ui', models: ['web'], mode: 'prod', dev_userinterface_id: 'f' },
    );

    await user.click(modelChip('web', 'alpha_ui'));
    // 4 dev rows use `web` (alpha, beta, gamma, zeta) plus the prod row paired with zeta = 5.
    expect(rowsShown()).toHaveLength(5);

    await user.click(screen.getByRole('button', { name: 'Prod' }));
    expect(rowsShown()).toHaveLength(1);

    await user.click(screen.getByRole('button', { name: 'All' }));
    expect(rowsShown()).toHaveLength(5);
  });

  it('leaves a variant name read-only — a variant is not something to filter by', async () => {
    variantNames.byId.b = ['example-variant'];
    await renderList();

    // beta_ui carries models ['web', 'android_tv'] AND a variant, and both render through the same
    // chip component. This pins the distinction: the model is a button that filters, the variant is
    // present text that filters nothing.
    expect(within(row('beta_ui')).getByRole('button', { name: 'web' })).toBeInTheDocument();
    expect(screen.getByText('example-variant')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'example-variant' })).not.toBeInTheDocument();
  });
});
