import { Box, Chip, Stack, Tooltip } from '@mui/material';
import React from 'react';

export type LifecycleEnv = 'dev' | 'test' | 'prod';

const ENV_ORDER: LifecycleEnv[] = ['dev', 'test', 'prod'];

const ENV_COLOR: Record<LifecycleEnv, 'default' | 'warning' | 'success'> = {
  dev: 'default',
  test: 'warning',
  prod: 'success',
};

export interface LifecycleChipsProps {
  /** Which environment rows exist. A missing env renders greyed out rather than hidden,
   *  so the three slots stay in the same place on every row and the eye can scan them. */
  environments?: Partial<Record<LifecycleEnv, boolean>>;
  /** Version to show on the prod chip ("prod v7"). */
  prodVersion?: number | null;
  /** Version shown after the chips ("v3") — the current version of the edited row. */
  currentVersion?: number | null;
  /** Called when the prod chip is clicked; omit to render it non-interactive. */
  onProdClick?: (event: React.MouseEvent<HTMLElement>) => void;
  /** Tooltip for the prod chip when it is clickable. */
  prodTooltip?: string;
  size?: 'small' | 'tiny';
}

/**
 * dev / test / prod lifecycle chips.
 *
 * Extracted from the virtual-scripts editor so the Test Cases list and the Virtual Scripts
 * page render the same thing — a testcase and a virtual script both carry a dev/test/prod
 * lifecycle, and two separate renderers would drift.
 *
 * Lives in core, not in `features/virtual-scripts/`, because core pages cannot import from
 * an optional feature: a customer running with `DISABLED_FEATURES=virtual-scripts` would
 * otherwise get a broken Test Cases page. Features may import core (docs/technical/FEATURES.md).
 */
export const LifecycleChips: React.FC<LifecycleChipsProps> = ({
  environments,
  prodVersion,
  currentVersion,
  onProdClick,
  prodTooltip = 'Prod rollback history',
  size = 'small',
}) => {
  const height = size === 'tiny' ? 16 : 20;
  const fontSize = size === 'tiny' ? 10 : 11;

  return (
    <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
      {ENV_ORDER.map((env) => {
        const on = !!environments?.[env];
        const label = env === 'prod' && on && prodVersion ? `prod v${prodVersion}` : env;
        const clickable = env === 'prod' && on && !!onProdClick;

        return (
          <Tooltip key={env} title={clickable ? prodTooltip : ''} disableHoverListener={!clickable}>
            <Chip
              size="small"
              label={label}
              variant={on ? 'filled' : 'outlined'}
              color={on ? ENV_COLOR[env] : 'default'}
              clickable={clickable}
              onClick={clickable ? onProdClick : undefined}
              sx={{
                height,
                opacity: on ? 1 : 0.5,
                '& .MuiChip-label': { px: 0.75, fontSize },
              }}
            />
          </Tooltip>
        );
      })}
      {currentVersion != null && (
        <Box component="span" sx={{ fontSize, color: 'text.disabled', ml: 0.25 }}>
          v{currentVersion}
        </Box>
      )}
    </Stack>
  );
};
