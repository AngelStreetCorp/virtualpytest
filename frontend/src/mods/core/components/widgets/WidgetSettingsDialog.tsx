import { Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, Switch, TextField } from '@mui/material';
import React, { useEffect, useState } from 'react';

import { useI18n } from '../../../../i18n/useI18n';
import type { WidgetDefinition, WidgetSettings } from '../../types';

interface Props {
  def: WidgetDefinition | null;
  settings: WidgetSettings;
  onSave: (settings: WidgetSettings) => void;
  onClose: () => void;
}

/** Edits one placed widget's settings, field by field as the widget declares them. */
export const WidgetSettingsDialog: React.FC<Props> = ({ def, settings, onSave, onClose }) => {
  const { t } = useI18n();
  const [draft, setDraft] = useState<WidgetSettings>(settings);
  useEffect(() => setDraft(settings), [settings]);

  return (
    <Dialog open={!!def} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{def ? t(def.name) : ''}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {(def?.settings ?? []).map((field) =>
            field.type === 'boolean' ? (
              <FormControlLabel
                key={field.key}
                control={
                  <Switch checked={Boolean(draft[field.key])} onChange={(e) => setDraft({ ...draft, [field.key]: e.target.checked })} />
                }
                label={t(field.label)}
              />
            ) : (
              <TextField
                key={field.key}
                select
                size="small"
                label={t(field.label)}
                value={String(draft[field.key] ?? field.default)}
                onChange={(e) => setDraft({ ...draft, [field.key]: e.target.value })}
              >
                {(field.options ?? []).map((o) => (
                  <MenuItem key={o.value} value={o.value}>
                    {t(o.label)}
                  </MenuItem>
                ))}
              </TextField>
            ),
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('Cancel')}</Button>
        <Button
          variant="contained"
          onClick={() => {
            onSave(draft);
            onClose();
          }}
        >
          {t('Save')}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
