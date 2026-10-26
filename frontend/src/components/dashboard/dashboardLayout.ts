/**
 * Dashboard tabs and card layout (TASK-123): the pure part. Which tabs a role sees, which tab opens
 * first, which cards a tab shows and in which shape. No React state here, so it is unit-tested.
 *
 * Defaults are COMPUTED from the card registry and the role, never copied into storage: a user's
 * saved layout holds only what they changed (`on` per card), so a changed default reaches
 * everyone who never customised that card. Width is not a user setting: a card has the shape it was designed for.
 */
import type { ComponentType } from 'react';

import type { AppIconName } from '../../constants/icons';
import type { Role } from '../../types/auth';

import type { DashboardData, DashRange } from './dashboardTypes';

export type TranslateFn = (key: string, vars?: Record<string, string | number>) => string;

export type DashTabId = 'hosts' | 'overview' | 'scripts' | 'devices' | 'system';
/**
 * The only card shapes (12-column grid): `tile` = a quarter-width KPI tile; `third`, `half`, `twoThirds` and `full` = a
 * list / chart card; `band` = a full-width slim row; `table` = a full-width table whose height follows its row count. Tiles and bands
 * share the KPI height, the rest the card height.
 */
export type CardLayout = 'tile' | 'third' | 'half' | 'twoThirds' | 'full' | 'band' | 'table';

export const ALL_ROLES: Role[] = ['admin', 'manager', 'developer', 'tester', 'viewer'];
const RUNNERS: Role[] = ['admin', 'manager', 'developer', 'tester'];

export interface DashTabDef {
  id: DashTabId;
  /** English text = i18n key. */
  titleKey: string;
  roles: Role[];
}

/** Order = order on screen. Overview opens first; "Hosts and devices" is the previous dashboard, second. */
export const DASH_TABS: DashTabDef[] = [
  { id: 'overview', titleKey: 'Overview', roles: ALL_ROLES },
  { id: 'hosts', titleKey: 'Hosts and devices', roles: ALL_ROLES },
  { id: 'scripts', titleKey: 'Scripts', roles: RUNNERS },
  { id: 'devices', titleKey: 'Devices', roles: ALL_ROLES },
  { id: 'system', titleKey: 'System', roles: ['admin'] },
];

export const FALLBACK_TAB: DashTabId = 'overview';

/** Props every card body receives. The shell has already handled "source block not loaded yet". */
export interface CardBodyProps {
  data: DashboardData;
  range: DashRange;
  now: number;
}

/**
 * One dashboard card. To add a card: write one of these in a `cards/*Cards.tsx` file and list it in
 * `cards/registry.ts` (docs/agent/platform/DASHBOARD_CARDS.md). `registry.test.ts` fails when a field is missing.
 */
export interface CardDefinition {
  id: string;
  titleKey: string;
  descriptionKey: string;
  /** Roles that may see the card at all (the endpoint is the real gate; this hides it). */
  roles: Role[];
  /** Tabs where the card is on by default. Any card the role may see can be switched on in any card tab. */
  tabs: DashTabId[];
  /** Grid shape: the only width decision, made by the card's author (see CardLayout). */
  layout: CardLayout;
  /** Icon chip of a `tile`; tiles draw their own shell, so the card body is a <KpiTile>. */
  icon?: AppIconName;
  /** Which endpoint feeds the card: drives the loading / error state of the shell. */
  source: 'summary' | 'system';
  /** Page the title (and the big numbers) lead to: the follow-up question's answer. */
  href: string;
  Component: ComponentType<CardBodyProps>;
  /** `table` layout only: how many body rows the card shows, so its height follows the data. */
  tableRows?: (data: DashboardData) => number;
  /** A chart card's fixed body height; other cards size their body to their content and are centred. */
  bodyHeight?: number;
  /** A card that exists only for some viewers (for example the user's favourites): a hook, called once per card. */
  useVisible?: () => boolean;
}

export type TabOverrides = Record<string, { on?: boolean }>;
export interface StoredLayout {
  favouriteTab?: DashTabId;
  tabs: Partial<Record<DashTabId, TabOverrides>>;
}

export const EMPTY_LAYOUT: StoredLayout = { tabs: {} };

/** A layout saved before widths were fixed may carry `size` (S / M / L) per card: drop it, the card's own shape applies. */
export const normaliseLayout = (stored: StoredLayout): StoredLayout => ({
  ...stored,
  tabs: Object.fromEntries(
    Object.entries(stored.tabs).map(([tab, ov]) => [tab, ov && Object.fromEntries(Object.entries(ov).map(([id, { on }]) => [id, { on }]))]),
  ),
});

/** Tabs the role may open, in screen order. */
export const allowedTabs = (role: Role): DashTabDef[] => DASH_TABS.filter((tab) => tab.roles.includes(role));

/** The tab that opens first: the user's favourite if they may still open it, else Overview. */
export const resolveFavouriteTab = (role: Role, favourite: DashTabId | undefined): DashTabId =>
  favourite && allowedTabs(role).some((tab) => tab.id === favourite) ? favourite : FALLBACK_TAB;

export interface ResolvedCard {
  def: CardDefinition;
  on: boolean;
}

/** Every card the role may use, with its resolved on/off for `tab` (default merged with overrides). */
export const resolveTabCards = (
  tab: DashTabId,
  role: Role,
  registry: CardDefinition[],
  overrides: TabOverrides | undefined,
): ResolvedCard[] =>
  registry
    .filter((def) => def.roles.includes(role))
    .map((def) => ({
      def,
      on: overrides?.[def.id]?.on ?? def.tabs.includes(tab),
    }));

/** Grid columns (of 12) a shape takes on a wide screen. */
export const LAYOUT_COLUMNS: Record<CardLayout, number> = { tile: 3, third: 4, half: 6, twoThirds: 8, full: 12, band: 12, table: 12 };

/** Fields a registry entry must have; the registry test uses it so a half-written card fails CI. */
export const REQUIRED_CARD_FIELDS: Array<keyof CardDefinition> = [
  'id',
  'titleKey',
  'descriptionKey',
  'roles',
  'tabs',
  'layout',
  'source',
  'href',
  'Component',
];
