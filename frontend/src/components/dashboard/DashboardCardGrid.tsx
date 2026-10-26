import { Box, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';

import { DASH_CARD_HEADER, DASH_GRID_GAP, DashCard, KpiTile } from './DashCard';
import { LAYOUT_COLUMNS, type CardDefinition, type ResolvedCard } from './dashboardLayout';
import { PAGED_LIST_ROW_HEIGHT } from './PagedList';
import type { DashboardData, DashRange } from './dashboardTypes';

interface Props {
  cards: ResolvedCard[];
  data: DashboardData;
  range: DashRange;
  now: number;
}

const TABLE_HEADER_ROWS = 1;
/** Card chrome around a table: header, padding and the card's own border. */
const TABLE_CHROME = DASH_CARD_HEADER + 16 + 2;

interface SlotProps {
  def: CardDefinition;
  data: DashboardData;
  range: DashRange;
  now: number;
}

/** One grid cell. A card with `useVisible` that says no renders nothing at all, not even its cell. */
const CardSlot: React.FC<SlotProps> = ({ def, data, range, now }) => {
  const { t } = useI18n();
  const visible = def.useVisible ? def.useVisible() : true;
  if (!visible) return null;
  const block = def.source === 'summary' ? data.summary : data.system;
  const failed = def.source === 'summary' ? data.summaryError : data.systemError;
  const state = block ? 'ready' : failed ? 'error' : 'loading';
  const isTile = def.layout === 'tile';
  const span = { xs: `span ${isTile ? 6 : 12}`, md: `span ${LAYOUT_COLUMNS[def.layout]}` };
  const tableHeight = def.layout === 'table' && state === 'ready' && def.tableRows
    ? TABLE_CHROME + (def.tableRows(data) + TABLE_HEADER_ROWS) * PAGED_LIST_ROW_HEIGHT
    : undefined;
  return (
    <Box sx={{ gridColumn: span, minWidth: 0 }}>
      {isTile ? (
        state === 'ready' ? (
          <def.Component data={data} range={range} now={now} />
        ) : (
          <KpiTile to={def.href} label={t(def.titleKey)} icon={def.icon ?? 'info'} value="—" testId={`dash-card-${def.id}`} />
        )
      ) : (
        <DashCard
          title={t(def.titleKey)}
          href={def.href}
          state={state}
          testId={`dash-card-${def.id}`}
          slim={def.layout === 'band'}
          height={tableHeight}
          bodyHeight={def.bodyHeight}
          errorText={def.source === 'system' ? t('No data') : undefined}
        >
          <def.Component data={data} range={range} now={now} />
        </DashCard>
      )}
    </Box>
  );
};

/** 12-column grid: tiles (quarter), half and full cards; below `md` a tile takes half a row and every other card the full row. */
export const DashboardCardGrid: React.FC<Props> = ({ cards, data, range, now }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  const shown = cards.filter((c) => c.on);

  if (shown.length === 0) {
    return (
      <Typography sx={{ color: P.textMuted, py: 6, textAlign: 'center' }}>{t('All cards are off for this tab')}</Typography>
    );
  }

  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(12, minmax(0, 1fr))', gap: DASH_GRID_GAP }}>
      {shown.map(({ def }) => (
        <CardSlot key={def.id} def={def} data={data} range={range} now={now} />
      ))}
    </Box>
  );
};
