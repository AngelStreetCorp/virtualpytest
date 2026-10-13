/**
 * The one filter bar of Monitoring → AI usage, the same on every tab: period · team · project · user · provider ·
 * model · result. Values live in the page URL (see `UsageQuery`); a dropdown lists what the period has, "All" clears it.
 * A click on an Overview row adds a category / caller chip below the bar.
 */
import { Box, Chip, FormControl, InputLabel, MenuItem, Select, ToggleButton, ToggleButtonGroup } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { segmentedSx } from '../common/PageChrome';

import type { FilterOption, ProviderView, RangeHours, UsageQuery, UsageReport } from './api';
import { callerLabel, categoryLabel } from './labels';

const RANGES: { hours: RangeHours; label: string }[] = [
  { hours: 1, label: '1 h' },
  { hours: 24, label: '24 h' },
  { hours: 168, label: '7 d' },
  { hours: 720, label: '30 d' },
];

interface Props {
  query: UsageQuery;
  report: UsageReport | null;
  onChange: (patch: Partial<UsageQuery>) => void;
}

export const FilterBar: React.FC<Props> = ({ query, report, onChange }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const options = report?.options ?? {};
  const detailed = (report?.source ?? (query.hours <= 168 ? 'calls' : 'rollup')) === 'calls';
  const providerNames = new Map<string, string>((report?.providers ?? []).map((p: ProviderView) => [p.endpoint, p.name]));

  const select = (
    field: 'team' | 'project' | 'user' | 'provider' | 'model' | 'result',
    label: string,
    items: FilterOption[],
    opts?: { disabled?: boolean; width?: number; tip?: string },
  ) => {
    const value = query[field];
    const list = items.some((o) => o.key === value) || !value ? items : [...items, { key: value, label: value }];
    return (
      <FormControl key={field} size="small" disabled={opts?.disabled} sx={{ width: opts?.width ?? 135, flexShrink: 0 }} title={opts?.disabled ? opts.tip : undefined}>
        <InputLabel id={`ai-filter-${field}`} shrink>{label}</InputLabel>
        <Select
          labelId={`ai-filter-${field}`}
          label={label}
          notched
          displayEmpty
          value={value}
          onChange={(e) => onChange({ [field]: e.target.value } as Partial<UsageQuery>)}
          renderValue={(v) => {
            const hit = list.find((o) => o.key === v);
            return <Box component="span" sx={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{v ? hit?.label ?? v : t('All')}</Box>;
          }}
          MenuProps={{ transitionDuration: 0 }}
        >
          <MenuItem value="">{t('All')}</MenuItem>
          {list.map((o) => (
            <MenuItem key={o.key} value={o.key}>{o.label ?? o.key}</MenuItem>
          ))}
        </Select>
      </FormControl>
    );
  };

  const needsCalls = t('Needs a period of 7 days or less');
  const chips: [string, string, () => void][] = [];
  if (query.category) chips.push([t('Category'), categoryLabel(query.category, t), () => onChange({ category: '' })]);
  if (query.caller) chips.push([t('Caller'), callerLabel(query.caller, t), () => onChange({ caller: '' })]);

  return (
    <Box sx={{ mb: 1.5 }}>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
        <ToggleButtonGroup
          exclusive
          size="small"
          value={query.hours}
          onChange={(_, v) => v && onChange({ hours: v as RangeHours })}
          sx={[segmentedSx(P, 'sm'), { flexShrink: 0, '& .MuiToggleButton-root': { transition: 'none' } }] as never}
        >
          {RANGES.map((r) => (
            <ToggleButton key={r.hours} value={r.hours} disableRipple>{r.label}</ToggleButton>
          ))}
        </ToggleButtonGroup>
        {select('team', t('Team'), options.team ?? [])}
        {select('project', t('Project'), options.project ?? [], { disabled: !detailed, tip: needsCalls })}
        {select('user', t('User'), options.user ?? [], { disabled: !detailed, tip: needsCalls })}
        {select('provider', t('Provider'), (options.provider ?? []).map((o) => ({ ...o, label: providerNames.get(o.key) ?? o.key })))}
        {select('model', t('Model'), options.model ?? [], { width: 150 })}
        {select('result', t('Result'), [{ key: 'success', label: t('Success') }, { key: 'failed', label: t('Failed') }], { disabled: !detailed, tip: needsCalls, width: 115 })}
      </Box>
      {chips.length > 0 && (
        <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', mt: 1 }}>
          {chips.map(([kind, label, remove]) => (
            <Chip key={kind} size="small" label={`${kind}: ${label}`} onDelete={remove} sx={{ bgcolor: P.hoverBg, transition: 'none' }} />
          ))}
        </Box>
      )}
    </Box>
  );
};
