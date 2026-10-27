/**
 * The report pages' first-load state (UI_STYLE §10 S6 — a loading state is the size of the
 * content it replaces, and it is gated on `loading`, never on "the data is empty").
 *
 * The regression these lock: both pages greeted the user with the stat tiles already drawn and
 * reading `N/A%` / `N/A` in the ERROR colour, because `Number('N/A')` is `NaN` and `NaN >= 80`
 * is false so the rate chain fell through to its last branch. A value that is not known yet
 * looked like a failure. CI/CD additionally showed a lone `<CircularProgress>` in an empty page
 * that then popped into place.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

/** A fetch that never settles — the first-load window, held open on purpose. */
const neverResolves = () => new Promise<Response>(() => {});

// A holder object, not destructured consts — each test swaps the implementation it sees.
const results = vi.hoisted(() => ({
  scripts: async (): Promise<unknown[]> => [],
  campaigns: async (): Promise<unknown[]> => [],
  executionResults: async (): Promise<unknown[]> => [],
  userInterfaces: async (): Promise<unknown[]> => [],
  metrics: async (): Promise<void> => {},
}));

vi.mock('../../frontend/src/hooks/pages/useScriptResults', () => ({
  useScriptResults: () => ({
    getAllScriptResults: (...a: unknown[]) => results.scripts(...a),
    updateCheckedStatus: async () => {},
    updateDiscardStatus: async () => {},
  }),
}));

vi.mock('../../frontend/src/hooks/pages/useCampaignResults', () => ({
  useCampaignResults: () => ({
    getAllCampaignResults: (...a: unknown[]) => results.campaigns(...a),
  }),
}));

vi.mock('../../frontend/src/hooks/useHostManager', () => ({
  useHostData: () => ({ getAllHosts: () => [] }),
}));

vi.mock('../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({
    selectedServer: 'server-1',
    availableServers: ['server-1'],
    setSelectedServer: () => {},
    serverHostsData: [],
    isLoading: false,
    error: null,
    pendingServers: new Set(),
    failedServers: new Set(),
    isServerChanging: false,
    refreshServerData: async () => {},
  }),
}));

vi.mock('../../frontend/src/contexts/workspace/WorkspaceContext', () => ({
  WorkspaceProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useWorkspaceContext: () => ({
    userWorkspaces: [],
    activeWorkspace: null,
    setActiveWorkspace: () => {},
    isLoadingWorkspaces: false,
    isDeviceAllowed: () => true,
    isScriptAllowed: () => true,
    isPathHidden: () => false,
  }),
}));

vi.mock('../../frontend/src/contexts/auth/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuthContext: () => ({
    user: null,
    profile: null,
    session: null,
    isLoading: false,
    isAuthenticated: true,
    signInWithGoogle: async () => {},
    signInWithGithub: async () => {},
    signInWithEmail: async () => {},
    signUpWithEmail: async () => {},
    resetPassword: async () => {},
    signOut: async () => {},
    refreshProfile: async () => {},
  }),
}));

vi.mock('../../frontend/src/contexts/ToastContext', () => ({
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useToastContext: () => ({
    showSuccess: () => {},
    showError: () => {},
    showWarning: () => {},
    showInfo: () => {},
  }),
  __esModule: true,
}));

const { emptyQuery, idleMutation } = vi.hoisted(() => ({
  emptyQuery: { data: { items: [], rows: [] }, isLoading: false, error: null },
  idleMutation: { mutateAsync: async () => ({}), isPending: false },
}));
vi.mock('../../frontend/src/hooks/reports/useRunManagement', () => ({
  useMilestones: () => emptyQuery,
  useRunGroups: () => emptyQuery,
  useLabels: () => emptyQuery,
  useQualityQuery: () => emptyQuery,
  useReportPermissions: () => ({ canEdit: false }),
  useGovernanceMutations: () => ({
    setResultMilestone: idleMutation,
    setResultRunGroup: idleMutation,
    setResultLabels: idleMutation,
    batchAssign: idleMutation,
  }),
}));

// STABLE references, hoisted outside the factory. ModelReports' interface load depends on
// `getAllUserInterfaces` in its effect deps, so a fresh arrow per mock call makes the dep look
// changed on every render and the list never settles. Same trap as DependencyReport.test.tsx.
const getAllUserInterfaces = async () => results.userInterfaces();
const getAllExecutionResults = async () => results.executionResults();
vi.mock('../../frontend/src/hooks/pages/useExecutionResults', () => ({
  useExecutionResults: () => ({ getAllExecutionResults: getAllExecutionResults }),
}));
vi.mock('../../frontend/src/hooks/pages/useUserInterface', () => ({
  useUserInterface: () => ({ getAllUserInterfaces: getAllUserInterfaces }),
}));

vi.mock('../../frontend/src/hooks/navigation/useMetrics', () => ({
  useMetrics: () => ({
    getNodeMetrics: () => null,
    getEdgeMetrics: () => null,
    getEdgeDirectionMetrics: () => null,
    fetchMetrics: (...a: unknown[]) => results.metrics(...a),
  }),
}));

import TestReports from '../../frontend/src/pages/TestReports';
import ModelReports from '../../frontend/src/pages/ModelReports';
import CICDReports from '../../features/cicd/frontend/CICDReportsPage';
import {
  BAR_HEIGHT,
  StatTileSkeleton,
  TableRowsSkeleton,
  rowPaddingY,
} from '../../frontend/src/components/common/ReportSkeleton';

/** MUI renders a Skeleton as this; counting them proves the placeholder actually mounted. */
const skeletonCount = (container: HTMLElement) =>
  container.querySelectorAll('.MuiSkeleton-root').length;

beforeEach(() => {
  results.scripts = async (): Promise<unknown[]> => [];
  results.campaigns = async (): Promise<unknown[]> => [];
  results.executionResults = async (): Promise<unknown[]> => [];
  results.userInterfaces = async (): Promise<unknown[]> => [];
  results.metrics = async (): Promise<void> => {};
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ runs: [], runners: [] }) }));
});

/**
 * True when nothing in the tree reads N/A, or a stand-in dash, in the error colour. This is the
 * user-visible defect: `rateColor(NaN, P)` fell through to `P.error`, so "nothing loaded yet"
 * was painted exactly like "this failed".
 */
const noRateIsRed = (container: HTMLElement): boolean => {
  const dist = (c: number[], t: number[]) =>
    Math.abs(c[0] - t[0]) + Math.abs(c[1] - t[1]) + Math.abs(c[2] - t[2]);
  for (const el of Array.from(container.querySelectorAll('body *, *'))) {
    if (el.children.length) continue;
    const t = (el.textContent || '').trim();
    if (!t || t.length > 24) continue;
    if (!/N\/A|^(—|-)$/.test(t)) continue;
    const c = (getComputedStyle(el).color.match(/\d+/g) || []).slice(0, 3).map(Number);
    if (c.length < 3) continue;
    if (dist(c, [211, 47, 47]) < 90 || dist(c, [220, 60, 50]) < 90) return false;
  }
  return true;
};

/**
 * How long an `await` on rendered output may take. Testing Library's async queries default to
 * 1000 ms, which is independent of vitest's `testTimeout: 10000` in vitest.config.ts — the test
 * had the budget, the query did not. Keep the two budgets aligned.
 */
const SETTLE_MS = 8000;

/**
 * Open the interface Select, once it is actually openable.
 *
 * The page draws its heading before `userInterfaces` resolves, and the Select carries
 * `disabled={userInterfaces.length === 0}` (ModelReports.tsx). Firing mouseDown as soon as the
 * heading appears therefore races the data. Lose that race and MUI swallows the event, because a
 * disabled input ignores it: the menu never opens, and the options only exist once the menu IS
 * open — so no amount of waiting inside `selectOption` recovers, it just burns the full budget
 * and fails with `Unable to find role="option"`. That is exactly what happened to both tests
 * below on run 3938 (2026-10-21: 2 failures, ~8 s each) while this file passed on an idle box;
 * raising SETTLE_MS had never addressed the cause, only the deadline. Wait for the Select to
 * leave `Mui-disabled` before opening it, so the open cannot be lost.
 */
const openInterfaceSelect = async (container: HTMLElement) => {
  const select = await waitFor(
    () => {
      const el = container.querySelector<HTMLElement>('.MuiSelect-select');
      if (!el) throw new Error('the interface Select is not rendered yet');
      if (el.classList.contains('Mui-disabled')) throw new Error('the interface Select is still disabled');
      return el;
    },
    { timeout: SETTLE_MS },
  );
  fireEvent.mouseDown(select);
};

/** Pick a real option by name — the listbox opens with a placeholder entry. */
const selectOption = async (name: string) => {
  const options = await screen.findAllByRole('option', undefined, { timeout: SETTLE_MS });
  const match = options.find((o) => (o.textContent || '').trim() === name);
  if (!match) throw new Error(`no option named ${name}; got ${options.map((o) => o.textContent).join(', ')}`);
  return match;
};

describe('report pages — first-load state', () => {
  describe('Test Reports', () => {
    it('skeletons the stat values instead of showing a red N/A while the first load is in flight', async () => {
      results.scripts = neverResolves as never;
      results.campaigns = neverResolves as never;

      const { container } = render(
        <BrowserRouter>
          <TestReports />
        </BrowserRouter>,
      );

      // The tile labels are static, so they stay readable — only the values are unknown.
      expect(screen.getByText('Success rate')).toBeInTheDocument();
      expect(screen.getByText('Avg duration')).toBeInTheDocument();
      expect(screen.queryByText(/N\/A/)).not.toBeInTheDocument();
      // Two value bars plus the placeholder table rows.
      expect(skeletonCount(container)).toBeGreaterThan(4);
    });

    it('skeletons the table body rather than showing a centred spinner', () => {
      results.scripts = neverResolves as never;
      results.campaigns = neverResolves as never;

      const { container } = render(
        <BrowserRouter>
          <TestReports />
        </BrowserRouter>,
      );

      expect(container.querySelectorAll('.MuiCircularProgress-root')).toHaveLength(0);
      // The header row stays mounted (static text), so the columns never shift.
      expect(screen.getByRole('columnheader', { name: /Test/i })).toBeInTheDocument();
      expect(container.querySelectorAll('tbody tr').length).toBeGreaterThan(1);
    });

    it('shows a muted dash, not a red N/A, when the load lands with no results', async () => {
      render(
        <BrowserRouter>
          <TestReports />
        </BrowserRouter>,
      );

      await waitFor(() => {
        expect(screen.getAllByText(/No .*results available yet|No test results/i).length).toBeGreaterThan(0);
      });
      // "unknown value" must never be dressed as a failed rate. Both tiles fall back to the
      // muted em dash, so there are two.
      expect(screen.queryByText(/N\/A%/)).not.toBeInTheDocument();
      expect(screen.getAllByText('—')).toHaveLength(2);
    });
  });

  describe('CI/CD Reports', () => {
    it('draws the KPI row and a skeleton table instead of a lone spinner', async () => {
      vi.stubGlobal('fetch', vi.fn().mockImplementation(neverResolves));

      const { container } = render(<CICDReports />);

      expect(await screen.findByRole('heading', { name: 'CI/CD Reports' })).toBeInTheDocument();
      // No centred spinner, and no empty page waiting to pop.
      expect(container.querySelectorAll('.MuiCircularProgress-root')).toHaveLength(0);
      // The real header stays, so the arriving table lines up with it.
      expect(screen.getByRole('columnheader', { name: 'Project' })).toBeInTheDocument();
      expect(screen.getByRole('columnheader', { name: 'Status' })).toBeInTheDocument();
      // KPI tiles + table rows.
      expect(skeletonCount(container)).toBeGreaterThan(20);
      expect(screen.queryByText(/Total Runs/)).not.toBeInTheDocument();
    });

    it('gives every KPI tile the three lines the live card draws', async () => {
      vi.stubGlobal('fetch', vi.fn().mockImplementation(neverResolves));

      const { container } = render(<CICDReports />);
      await screen.findByRole('heading', { name: 'CI/CD Reports' });

      // The live KpiCard draws caption / h5 / caption. The placeholder must reserve exactly
      // those three lines, or the row shrinks by the missing line when the numbers arrive.
      // Skip the Paper that wraps the runs table — it holds row skeletons, not tile lines.
      const tiles = [...container.querySelectorAll('.MuiPaper-root')].filter(
        (p) => p.querySelectorAll('.MuiSkeleton-root').length > 0 && !p.querySelector('table'),
      );
      expect(tiles).toHaveLength(7);
      tiles.forEach((t) => expect(t.querySelectorAll('.MuiSkeleton-root')).toHaveLength(3));
    });
  });

  /**
   * The other two pages of the same Report dropdown. ModelReports carried the identical
   * `rateColor(Number('N/A'), P)` defect — `NaN` fails every threshold, so "no executions yet"
   * painted the success rate red — and both pages replaced their whole table body with one
   * centred spinner.
   */
  describe('Model Reports and Dependency Report', () => {
    it('ModelReports never renders an N/A% success rate while the executions are pending', async () => {
      // One interface is available; the executions behind it never arrive.
      results.userInterfaces = async (): Promise<unknown[]> => [{ id: 'stb-testop', name: 'STB TV' }];
      results.executionResults = neverResolves as never;
      results.metrics = neverResolves as never;

      const { container } = render(
        <BrowserRouter>
          <ModelReports />
        </BrowserRouter>,
      );
      await screen.findByRole('heading', { name: 'Model Analysis Reports' });
      await openInterfaceSelect(container);
      fireEvent.click(await selectOption('STB TV'));

      // The tile row is reached and nothing in it is dressed as a failed rate.
      await waitFor(() => expect(screen.getByText('Success rate')).toBeInTheDocument(), { timeout: SETTLE_MS });
      expect(screen.queryByText(/N\/A%/)).not.toBeInTheDocument();
      expect(noRateIsRed(container)).toBe(true);
    });

    it('ModelReports shows a muted dash, not a red rate, when the load lands empty', async () => {
      results.userInterfaces = async (): Promise<unknown[]> => [{ id: 'stb-testop', name: 'STB TV' }];
      results.executionResults = async (): Promise<unknown[]> => [];

      const { container } = render(
        <BrowserRouter>
          <ModelReports />
        </BrowserRouter>,
      );
      await screen.findByRole('heading', { name: 'Model Analysis Reports' });
      await openInterfaceSelect(container);
      fireEvent.click(await selectOption('STB TV'));

      await waitFor(() => expect(screen.getByText('Success rate')).toBeInTheDocument(), { timeout: SETTLE_MS });
      expect(screen.queryByText(/N\/A%/)).not.toBeInTheDocument();
      // Success rate and Avg duration both fall back to the dash; neither is red.
      expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2);
      expect(noRateIsRed(container)).toBe(true);
    });
  });

  describe('ReportSkeleton geometry', () => {
    /**
     * MUI's `sx` runs bare numbers in padding through the theme's `spacing` (8 by default), so
     * `py: 6.5` became 52 px and every skeleton row on /test-results/cicd-reports rendered
     * 125 px tall instead of 42. `rowPaddingY` must keep returning a unit-suffixed string.
     */
    it('returns cell padding as an Npx string, which sx will not scale', () => {
      expect(rowPaddingY(42)).toBe('12px'); // the CI/CD run row
      expect(rowPaddingY(34)).toBe('8px'); // the Test Reports row
      expect(rowPaddingY(16)).toBe('0px'); // never negative
      for (const v of [16, 34, 42, 60]) {
        expect(rowPaddingY(v)).toMatch(/^\d+px$/);
        // A bare number here is the bug: sx would multiply it by spacing.
        expect(rowPaddingY(v)).not.toMatch(/^\d+(\.\d+)?$/);
      }
    });

    it('renders one cell per width and one BAR_HEIGHT bar per text cell', () => {
      const { container } = render(
        <table>
          <tbody>
            <TableRowsSkeleton rows={3} widths={['50%', null, 80]} rowHeight={42} />
          </tbody>
        </table>,
      );

      expect(container.querySelectorAll('tr')).toHaveLength(3);
      expect(container.querySelectorAll('td')).toHaveLength(9);
      // Every block, icon cells included, is BAR_HEIGHT — a taller one would outgrow the
      // pinned row height.
      const bars = [...container.querySelectorAll('td .MuiSkeleton-root')];
      expect(bars).toHaveLength(9);
      expect(bars.every((b) => b.style.height === `${BAR_HEIGHT}px`)).toBe(true);
      expect(bars.filter((b) => b.style.width === '52px')).toHaveLength(3);
    });
  });
});