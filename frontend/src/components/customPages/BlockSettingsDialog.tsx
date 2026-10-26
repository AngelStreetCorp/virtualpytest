import { Button, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Select, Switch, TextField, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import React, { useEffect, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useCatalogue } from '../../hooks/customPages/useCustomPages';
import { fetchCustomReports } from '../../hooks/reports/runManagementApi';
import { useI18n } from '../../i18n/useI18n';
import type { PageBlock, SettingSpec } from '../../types/customPages';
import { StyledDialog } from '../common/StyledDialog';
import { neutralButtonSx, primaryButtonSx } from '../common/PageChrome';

type Value = string | number | boolean;

interface Props {
  block: PageBlock | null;
  /** The other blocks of the page, for settings that point at one (device_from). */
  blocks: PageBlock[];
  onClose: () => void;
  onSave: (blockId: string, changes: Record<string, Value>) => void;
}

const LABELS: Record<string, string> = {
  model_filter: 'Show devices',
  device_from: 'Device from',
  userinterface: 'User interface (empty: the device default)',
  limit: 'Rows',
  report_id: 'Saved report',
  text: 'Text',
  heading: 'Show as heading',
};

/** Edit the settings of one block; the fields come from the catalogue, the server re-validates on save. */
export const BlockSettingsDialog: React.FC<Props> = ({ block, blocks, onClose, onSave }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { data: catalogue } = useCatalogue();
  const [values, setValues] = useState<Record<string, Value>>({});
  const spec = catalogue ? [...catalogue.available, ...catalogue.unavailable].find((b) => b.type === block?.type) : undefined;
  const reports = useQuery({ queryKey: ['custom-page', 'reports-list'], queryFn: fetchCustomReports, enabled: block?.type === 'report' });

  useEffect(() => {
    setValues(block ? { ...block.settings } : {});
  }, [block]);

  if (!block || !spec) return null;
  const set = (name: string, value: Value) => setValues((prev) => ({ ...prev, [name]: value }));

  const field = (name: string, s: SettingSpec) => {
    const label = t(LABELS[name] ?? name);
    const value = values[name];
    switch (s.type) {
      case 'enum':
        return (
          <Select key={name} size="small" fullWidth value={String(value ?? s.default ?? '')} onChange={(e) => set(name, String(e.target.value))} inputProps={{ 'aria-label': label }}>
            {s.values.map((v) => (
              <MenuItem key={v} value={v}>
                {v}
              </MenuItem>
            ))}
          </Select>
        );
      case 'ref': {
        const options = blocks.filter((b) => b.type === s.ref_type && b.id !== block.id);
        return (
          <Select key={name} size="small" fullWidth displayEmpty value={String(value ?? '')} onChange={(e) => set(name, String(e.target.value))} inputProps={{ 'aria-label': label }}>
            {s.optional && <MenuItem value="">{t('Any device')}</MenuItem>}
            {options.map((b) => (
              <MenuItem key={b.id} value={b.id}>
                {t('Device picker')} ({b.id})
              </MenuItem>
            ))}
          </Select>
        );
      }
      case 'int':
        return <TextField key={name} size="small" fullWidth type="number" inputProps={{ min: s.min, max: s.max, 'aria-label': label }} value={value ?? s.default ?? ''} onChange={(e) => set(name, Number(e.target.value))} />;
      case 'bool':
        return <FormControlLabel key={name} control={<Switch checked={value === true} onChange={(e) => set(name, e.target.checked)} />} label={label} />;
      case 'uuid':
        return (
          <Select key={name} size="small" fullWidth displayEmpty value={String(value ?? '')} onChange={(e) => set(name, String(e.target.value))} inputProps={{ 'aria-label': label }}>
            {(reports.data?.items ?? []).map((r) => (
              <MenuItem key={r.id} value={r.id}>
                {r.name}
              </MenuItem>
            ))}
          </Select>
        );
      default:
        return (
          <TextField key={name} size="small" fullWidth multiline={name === 'text'} minRows={name === 'text' ? 3 : 1} inputProps={{ maxLength: s.max, 'aria-label': label }} value={String(value ?? '')} onChange={(e) => set(name, e.target.value)} />
        );
    }
  };

  const names = Object.keys(spec.settings);
  return (
    <StyledDialog open onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{t(spec.title)}</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, pt: 1 }}>
        {names.length === 0 && <Typography sx={{ color: P.textMuted }}>{t('This block has no settings.')}</Typography>}
        {names.map((name) => (
          <div key={name}>
            {spec.settings[name].type !== 'bool' && (
              <Typography sx={{ color: P.textSecondary, fontSize: TYPOGRAPHY.caption.size, mb: 0.5 }}>{t(LABELS[name] ?? name)}</Typography>
            )}
            {field(name, spec.settings[name])}
          </div>
        ))}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} sx={neutralButtonSx(P)}>
          {t('Cancel')}
        </Button>
        <Button variant="contained" onClick={() => onSave(block.id, values)} sx={primaryButtonSx(P)}>
          {t('Save')}
        </Button>
      </DialogActions>
    </StyledDialog>
  );
};
