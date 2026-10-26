import type { CardDefinition } from '../dashboardLayout';

import { deviceCards } from './deviceCards';
import { kpiTiles } from './kpiTiles';
import { overviewCards } from './overviewCards';
import { scriptCards } from './scriptCards';
import { systemCards } from './systemCards';

/** Every dashboard card, in default on-screen order. Add a card: write its definition, list it here. */
export const CARD_REGISTRY: CardDefinition[] = [...kpiTiles, ...scriptCards, ...overviewCards, ...deviceCards, ...systemCards];
