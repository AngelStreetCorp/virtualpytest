import React, { useState } from 'react';
import {
  Box,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  FormControlLabel,
  Switch,
  TextField,
  InputAdornment,
  IconButton,
} from '@mui/material';
import { Visibility, VisibilityOff } from '@mui/icons-material';

import { UserinterfaceSelector } from '../UserinterfaceSelector';
import { VariantSelector } from '../VariantSelector';
import { EdgeKpiSelector } from '../EdgeKpiSelector';
import { NavigationNodeSelector } from '../NavigationNodeSelector';

export interface ScriptParameterRowParam {
  name: string;
  dataType?: string;
  default?: string;
  choices?: string[];
  required?: boolean;
}

interface ScriptParameterRowProps {
  param: ScriptParameterRowParam;
  value: string;
  onChange: (value: string) => void;
  // Sibling parameter values, so cascading selectors (variant reads
  // userinterface, edge/node read userinterface+variant) stay self-consistent
  // regardless of where the bag lives (per-device map in RunTests vs flat
  // script.parameters in BuildCampaigns).
  allValues: Record<string, string>;
  // Script identifier (basename, no .py) — used to gate kpi_measurement/edge
  // and goto/node special renderers.
  scriptName: string;
  // Only needed for UserinterfaceSelector compatibility filtering.
  deviceModel?: string;
  // Dev/prod userinterface targeting. When onUiModeChange is provided the
  // userinterface dropdown also lists published prod versions (gold chip) and
  // reports the selected entry's mode; uiMode is the current selection's mode.
  uiMode?: 'dev' | 'prod';
  onUiModeChange?: (mode: 'dev' | 'prod') => void;
}

const getInlineParamWidth = (
  param: ScriptParameterRowParam,
  value: string,
  hasChoices: boolean,
  isBool: boolean,
): string => {
  // Free-text run name (e.g. zap_digit) — give it room; names are descriptive.
  if (param.name === 'display_name') {
    return '28ch';
  }
  // OCR char whitelist (device_get_info) prefills the full default character set
  // — give it room so the user can read/edit it instead of a 14ch peephole.
  if (param.name === 'ocr_whitelist') {
    return '36ch';
  }
  if (isBool) {
    return 'auto';
  }

  if (hasChoices) {
    const longestChoice = Math.max(0, ...(param.choices || []).map((choice) => choice.length));
    const basis = Math.max(param.name.length, value.length, longestChoice);
    return `${Math.min(Math.max(basis + 4, 10), 18)}ch`;
  }

  const isNumericLike =
    param.dataType === 'int' ||
    param.dataType === 'float' ||
    /(^|[_-])(port|max|count|sec|timeout|retry|attempt|delay|minute|hour|day)([_-]|$)/i.test(param.name);
  const isSensitive =
    /password|secret|token|key|username|email|mailbox|address|server|domain|path|url/i.test(param.name);

  const basis = Math.max(param.name.length, value.length, (param.default || '').length);
  const minCh = isNumericLike ? 8 : isSensitive ? 12 : 9;
  const maxCh = isNumericLike ? 12 : isSensitive ? 18 : 14;
  return `${Math.min(Math.max(basis + 2, minCh), maxCh)}ch`;
};

const pickUserinterface = (allValues: Record<string, string>): string => (
  (allValues['userinterface'] || allValues['userinterface_name'] || '').trim()
);

// standby_measurement.py's --edge dropdown offers only the edge whose TARGET
// node is standby (any source — "live → standby", "home → standby", …), never
// the reverse. The script derives both nodes and measures the standby → live
// wake internally, so all it needs is the into-standby direction. Filter on the
// destination node label rather than a whole-label substring so a variant that
// re-wires the source (e.g. home → standby) still surfaces the edge.
const STANDBY_EDGE_TO_LABEL = 'standby';

// standby_measurement.py's standby-mode node picker only offers the mode nodes
// (label contains one of these). Module-level for stable identity.
const STANDBY_MODE_NODE_FILTER = ['standby_eco', 'standby_fast', 'standby_active'];

// Per-script display-label overrides for the generic text field, where the
// argparse name can't carry the unit. standby_measurement's --wait is minutes.
const paramDisplayLabel = (scriptName: string, paramName: string): string => {
  if (scriptName === 'standby_measurement' && paramName === 'wait') return 'wait (min)';
  // Any script exposing a free-text run name reads as "Display name" in RunTests.
  if (paramName === 'display_name') return 'Display name';
  return paramName;
};

export const ScriptParameterRow: React.FC<ScriptParameterRowProps> = ({
  param,
  value,
  onChange,
  allValues,
  scriptName,
  deviceModel,
  uiMode = 'dev',
  onUiModeChange,
}) => {
  const [showPassword, setShowPassword] = useState(false);

  const isUserinterfaceParam = param.name === 'userinterface' || param.name === 'userinterface_name';
  if (isUserinterfaceParam) {
    return (
      <Box key={param.name} sx={{ flexShrink: 0, width: '22ch' }}>
        <UserinterfaceSelector
          deviceModel={deviceModel}
          value={value || param.default || ''}
          mode={uiMode}
          includeProd={Boolean(onUiModeChange)}
          onChange={(v, m) => {
            onChange(v);
            onUiModeChange?.(m ?? 'dev');
          }}
          label={param.name}
          size="small"
          fullWidth
        />
      </Box>
    );
  }

  // Named-variant dropdown (see docs/agent/ENHANCE_VARIANT.md §7.3). Default
  // option is "(none — use base)"; reads the current userinterface from the
  // same parameter bag the caller passed in.
  if (param.name === 'variant') {
    const uiName = pickUserinterface(allValues);
    return (
      <Box key={param.name} sx={{ flexShrink: 0, width: '22ch' }}>
        <VariantSelector
          userinterfaceName={uiName || undefined}
          value={value || ''}
          onChange={onChange}
          label={param.name}
          size="small"
          fullWidth
        />
      </Box>
    );
  }

  // kpi_measurement.py's --edge takes an action_set LABEL. Render a dropdown
  // of action_sets with KPI measurement configured for the selected
  // userinterface, scoped to the active variant.
  if (scriptName === 'kpi_measurement' && param.name === 'edge') {
    const uiName = pickUserinterface(allValues);
    const variantName = (allValues['variant'] || '').trim() || null;
    return (
      <Box key={param.name} sx={{ flexShrink: 0, width: '32ch' }}>
        <EdgeKpiSelector
          userinterfaceName={uiName || undefined}
          variant={variantName}
          value={value || ''}
          onChange={onChange}
          label={param.name}
          size="small"
          fullWidth
        />
      </Box>
    );
  }

  // kpi_measurement.py's --closing_edge takes an OPTIONAL action_set LABEL: the
  // edge executed once measurement finishes (e.g. to fully close an app), instead
  // of the old always-goto-home closure. Same dropdown as --edge, but allowNone
  // so it can be left blank (blank = no closure; the script leaves the device
  // where the run ended).
  if (scriptName === 'kpi_measurement' && param.name === 'closing_edge') {
    const uiName = pickUserinterface(allValues);
    const variantName = (allValues['variant'] || '').trim() || null;
    return (
      <Box key={param.name} sx={{ flexShrink: 0, width: '32ch' }}>
        <EdgeKpiSelector
          userinterfaceName={uiName || undefined}
          variant={variantName}
          value={value || ''}
          onChange={onChange}
          label={param.name}
          allowNone
          size="small"
          fullWidth
        />
      </Box>
    );
  }

  // standby_measurement.py's --edge takes an into-standby action_set LABEL.
  // Reuse the same KPI edge selector but filtered to edges whose target node
  // is the standby node (any source — see STANDBY_EDGE_TO_LABEL).
  if (scriptName === 'standby_measurement' && param.name === 'edge') {
    const uiName = pickUserinterface(allValues);
    const variantName = (allValues['variant'] || '').trim() || null;
    return (
      <Box key={param.name} sx={{ flexShrink: 0, width: '32ch' }}>
        <EdgeKpiSelector
          userinterfaceName={uiName || undefined}
          variant={variantName}
          value={value || ''}
          onChange={onChange}
          label={param.name}
          toLabelEquals={STANDBY_EDGE_TO_LABEL}
          size="small"
          fullWidth
        />
      </Box>
    );
  }

  // standby_measurement.py's --standby_mode_node selects the standby mode by
  // navigating to its node. The picker is filtered to the standby mode nodes
  // (labelIncludesAny) and shows each node's friendly display name
  // (data.display_name, e.g. "[TC266] Eco (ColdStandby)") when set. No "(none)"
  // option — a mode is always selected; the first matching node is preselected.
  if (scriptName === 'standby_measurement' && param.name === 'standby_mode_node') {
    const uiName = pickUserinterface(allValues);
    const variantName = (allValues['variant'] || '').trim() || null;
    return (
      <Box key={param.name} sx={{ flexShrink: 0, width: '32ch' }}>
        <NavigationNodeSelector
          userinterfaceName={uiName || undefined}
          variant={variantName}
          value={value || ''}
          onChange={onChange}
          label={param.name}
          labelIncludesAny={STANDBY_MODE_NODE_FILTER}
          size="small"
          fullWidth
        />
      </Box>
    );
  }

  // goto.py's --node takes a node LABEL. Render a dropdown of nodes
  // available in the selected userinterface's tree hierarchy under the
  // active variant — same pattern as kpi_measurement/edge.
  if (scriptName === 'goto' && param.name === 'node') {
    const uiName = pickUserinterface(allValues);
    const variantName = (allValues['variant'] || '').trim() || null;
    return (
      <Box key={param.name} sx={{ flexShrink: 0, width: '22ch' }}>
        <NavigationNodeSelector
          userinterfaceName={uiName || undefined}
          variant={variantName}
          value={value || ''}
          onChange={onChange}
          label={param.name}
          size="small"
          fullWidth
        />
      </Box>
    );
  }

  const hasChoices = Boolean(param.choices && param.choices.length > 0);
  const isBool = !hasChoices && (
    param.dataType === 'bool' ||
    param.name === 'goto-live' ||
    param.name === 'audio-analysis' ||
    param.default === 'true' ||
    param.default === 'false'
  );
  const fieldWidth = getInlineParamWidth(param, value || param.default || '', hasChoices, isBool);

  if (hasChoices) {
    return (
      <Box key={param.name} sx={{ flexShrink: 0, width: fieldWidth, minWidth: fieldWidth }}>
        <FormControl size="small" fullWidth>
          <InputLabel sx={{ fontSize: '0.75rem' }}>{param.name}</InputLabel>
          <Select
            value={value || param.default || ''}
            label={param.name}
            onChange={(e) => onChange(e.target.value as string)}
            sx={{ fontSize: '0.75rem' }}
          >
            {param.choices!.map((choice) => (
              <MenuItem key={choice} value={choice}>{choice}</MenuItem>
            ))}
          </Select>
        </FormControl>
      </Box>
    );
  }

  if (isBool) {
    return (
      <Box key={param.name} sx={{ flexShrink: 0, width: fieldWidth, minWidth: 'auto' }}>
        <FormControlLabel
          control={
            <Switch
              size="small"
              checked={(value || param.default || 'false') === 'true'}
              onChange={(e) => onChange(e.target.checked ? 'true' : 'false')}
            />
          }
          label={param.name}
          slotProps={{ typography: { variant: 'caption', sx: { fontSize: '0.7rem' } } }}
          sx={{ mx: 0, gap: 0.25 }}
        />
      </Box>
    );
  }

  const isPasswordField = /password|secret|token/i.test(param.name);

  return (
    <Box key={param.name} sx={{ flexShrink: 0, width: fieldWidth, minWidth: fieldWidth }}>
      <TextField
        size="small"
        label={paramDisplayLabel(scriptName, param.name)}
        type={isPasswordField && !showPassword ? 'password' : (param.dataType === 'int' || param.dataType === 'float') ? 'number' : 'text'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        error={!!param.required && !value.trim()}
        fullWidth
        inputProps={{ style: { fontSize: '0.75rem' }, ...(param.dataType === 'int' ? { step: 1 } : param.dataType === 'float' ? { step: 0.1 } : {}) }}
        InputLabelProps={{ style: { fontSize: '0.75rem' } }}
        InputProps={isPasswordField ? {
          endAdornment: (
            <InputAdornment position="end">
              <IconButton
                size="small"
                onClick={() => setShowPassword((prev) => !prev)}
                edge="end"
                sx={{ p: 0.25 }}
              >
                {showPassword ? <VisibilityOff sx={{ fontSize: '0.9rem' }} /> : <Visibility sx={{ fontSize: '0.9rem' }} />}
              </IconButton>
            </InputAdornment>
          ),
        } : undefined}
      />
    </Box>
  );
};
