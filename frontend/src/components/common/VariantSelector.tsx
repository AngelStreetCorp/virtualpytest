/**
 * Variant Selector
 *
 * Multi-select dropdown of registered variant names for a given userinterface,
 * used by the RunTests modal to drive the optional --variant CLI flag. The
 * value is the canonical composite string the backend already understands
 * (components sorted, '+'-joined — see shared navigation_graph.py
 * canonical_variant_name / parse_variant_list): '' = base run,
 * 'variant1' = single variant, 'variant1+variant2' = composition.
 *
 * Resolution flow:
 *   userinterface_name (string) → useUserInterface().getUserInterfaceByName
 *     → userinterface_id → useUserInterfaceVariants → list of names.
 *
 * See docs/agent/ENHANCE_VARIANT.md §7.3.
 */

import React, { useEffect, useState } from 'react';
import {
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Checkbox,
  useTheme,
} from '@mui/material';

import { useUserInterface } from '../../hooks/pages/useUserInterface';
import { useUserInterfaceVariants } from '../../hooks/userinterface/useUserInterfaceVariants';
import { AGENT_CHAT_PALETTE } from '../../constants/agentChatTheme';

interface VariantSelectorProps {
  userinterfaceName?: string;
  value?: string; // '' = base, 'a' or 'a+b' (canonical composite) otherwise
  onChange: (variant: string) => void;
  label?: string;
  disabled?: boolean;
  size?: 'small' | 'medium';
  fullWidth?: boolean;
}

const BASE_LABEL = 'base';

/** Split a stored variant value into its components ('+' or ',' separated). */
const parseComponents = (value: string | undefined | null): string[] =>
  (value || '')
    .split(/[+,]/)
    .map((s) => s.trim())
    .filter(Boolean);

/** Canonical composite string: components sorted, '+'-joined ('' for base). */
const toCanonical = (components: string[]): string => [...components].sort().join('+');

export const VariantSelector: React.FC<VariantSelectorProps> = ({
  userinterfaceName,
  value = '',
  onChange,
  label = 'variant',
  disabled = false,
  size = 'small',
  fullWidth = true,
}) => {
  const theme = useTheme();
  const isDarkMode = theme.palette.mode === 'dark';
  const PALETTE = AGENT_CHAT_PALETTE;

  const { getUserInterfaceByName } = useUserInterface();
  const [userinterfaceId, setUserinterfaceId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!userinterfaceName) {
      setUserinterfaceId(null);
      return;
    }
    (async () => {
      try {
        const ui = await getUserInterfaceByName(userinterfaceName);
        if (!cancelled) {
          setUserinterfaceId(ui?.id || null);
        }
      } catch (err) {
        console.warn(
          `[@VariantSelector] Could not resolve userinterface '${userinterfaceName}':`,
          err,
        );
        if (!cancelled) setUserinterfaceId(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userinterfaceName, getUserInterfaceByName]);

  const { variants, loading: variantsLoading } = useUserInterfaceVariants(userinterfaceId);

  const selectedComponents = parseComponents(value);

  // If a selected component disappears from the list (e.g. the user switched
  // userinterface), drop just that component — keep any that still exist.
  //
  // Critical: gate on `userinterfaceId` being resolved AND the variants
  // request having finished. The hook returns `variants=[]` synchronously
  // both while `userinterfaceId` is still being resolved by the parent
  // useEffect (getUserInterfaceByName) AND while the /variants fetch is in
  // flight. Resetting in those windows wipes a valid device-default variant
  // (DEVICE{i}_VARIANT, surfaced via RunTests' `device.preferred_variant`)
  // before the variants list ever arrives — the dropdown then collapses to
  // "base" on mount even though the configured variant exists. See
  // feedback_reset_effect_async_deps: reset-on-open effects must not depend
  // on async-loaded state.
  useEffect(() => {
    if (!userinterfaceId || variantsLoading) return;
    const components = parseComponents(value);
    if (components.length === 0) return;
    const valid = components.filter((c) => variants.some((v) => v.name === c));
    if (valid.length !== components.length) {
      onChange(toCanonical(valid));
    }
  }, [userinterfaceId, variantsLoading, variants, value, onChange]);

  const styles = {
    height: size === 'small' ? 32 : 40,
    fontSize: size === 'small' ? '0.85rem' : '0.875rem',
    bgcolor: isDarkMode ? PALETTE.inputBg : '#fff',
    borderRadius: 1.5,
    '& .MuiOutlinedInput-notchedOutline': {
      borderColor: isDarkMode ? PALETTE.borderColor : 'grey.300',
    },
  };

  return (
    <FormControl size={size} fullWidth={fullWidth} disabled={disabled}>
      <InputLabel shrink sx={{ fontSize: '0.75rem' }}>{label}</InputLabel>
      <Select
        multiple
        value={selectedComponents}
        label={label}
        notched
        onChange={(e) => {
          const next = e.target.value as unknown as string[];
          // Clicking "base" (empty value) clears the whole selection.
          if (next.includes('')) {
            onChange('');
            return;
          }
          onChange(toCanonical(next));
        }}
        sx={styles}
        renderValue={(selected) => {
          const arr = selected as string[];
          return arr.length ? toCanonical(arr) : BASE_LABEL;
        }}
        displayEmpty
      >
        <MenuItem value="">{BASE_LABEL}</MenuItem>
        {variants.map((variant) => (
          <MenuItem key={variant.name} value={variant.name} dense>
            <Checkbox
              size="small"
              checked={selectedComponents.includes(variant.name)}
              sx={{ p: 0.25, mr: 1 }}
            />
            {variant.name}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
};
