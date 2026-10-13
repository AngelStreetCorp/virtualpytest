/**
 * Label picker: chooses team labels BY ID (never by typed name) and stops at the
 * per-entity maximum. The server enforces the same cap atomically; this only keeps the
 * user from building a selection that would be refused.
 */

import { Autocomplete, Box, Chip, TextField } from '@mui/material';
import React, { useMemo } from 'react';

import { useLabels } from '../../hooks/reports/useRunManagement';
import { LABELS_PER_ENTITY_MAX, validateLabelSelection, type RunLabel } from '../../types/reports';

export interface LabelPickerProps {
  value: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
  label?: string;
}

export const LabelPicker: React.FC<LabelPickerProps> = ({ value, onChange, disabled, label = 'Labels' }) => {
  const labelsQuery = useLabels();
  const options = useMemo(() => labelsQuery.data?.items ?? [], [labelsQuery.data]);
  const byId = useMemo(() => new Map(options.map((option) => [option.id, option])), [options]);
  const selected = value.map((id) => byId.get(id)).filter((option): option is RunLabel => Boolean(option));
  const atLimit = value.length >= LABELS_PER_ENTITY_MAX;
  const selectionError = validateLabelSelection(value);

  return (
    <Autocomplete
      multiple
      size="small"
      options={options}
      value={selected}
      disabled={disabled}
      loading={labelsQuery.isLoading}
      getOptionLabel={(option) => option.name}
      isOptionEqualToValue={(option, current) => option.id === current.id}
      getOptionDisabled={(option) => atLimit && !value.includes(option.id)}
      onChange={(_event, next) => {
        const ids = Array.from(new Set(next.map((option) => option.id)));
        if (ids.length > LABELS_PER_ENTITY_MAX) return;
        onChange(ids);
      }}
      renderTags={(tags, getTagProps) =>
        tags.map((option, index) => {
          const { key, ...tagProps } = getTagProps({ index });
          return (
            <Chip
              key={key}
              {...tagProps}
              size="small"
              label={option.name}
              sx={option.color ? { borderColor: option.color, borderWidth: 1, borderStyle: 'solid' } : undefined}
            />
          );
        })
      }
      renderOption={(props, option) => {
        const { key, ...optionProps } = props as React.HTMLAttributes<HTMLLIElement> & { key: string };
        return (
          <Box component="li" key={key} {...optionProps} sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            <Box
              component="span"
              sx={{ width: 10, height: 10, borderRadius: '2px', bgcolor: option.color || 'action.disabled' }}
            />
            {option.name}
          </Box>
        );
      }}
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          error={Boolean(selectionError)}
          helperText={
            selectionError ??
            (atLimit
              ? `Maximum of ${LABELS_PER_ENTITY_MAX} labels reached`
              : `${value.length}/${LABELS_PER_ENTITY_MAX} labels`)
          }
        />
      )}
    />
  );
};

export default LabelPicker;
