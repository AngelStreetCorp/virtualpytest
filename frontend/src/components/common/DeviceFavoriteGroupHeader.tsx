import { ListSubheader } from '@mui/material';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { TYPOGRAPHY } from '../../constants/typography';

/**
 * Group header of a device or executable menu (TASK-99/100): "Favorites" above the starred devices, "All devices"
 * above the rest. A ListSubheader, so a MUI Select/Menu never treats it as a selectable option.
 */
export const DeviceFavoriteGroupHeader = ({ kind, inline = false }: { kind: 'favorites' | 'all' | 'allItems'; inline?: boolean }) => {
  const { t } = useI18n();
  const P = useAgentChatPalette();
  return (
    // disableSticky: a sticky header sticks at top:0 and slides over a pinned search box above the list.
    <ListSubheader
      disableSticky
      // inline: a label inside a plain-div rail (no list around it), on the rail's own background.
      component={inline ? 'div' : 'li'}
      sx={{ lineHeight: '1.75rem', fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, bgcolor: inline ? 'transparent' : P.surface, ...(inline ? { px: 0.5 } : {}) }}
    >
      {kind === 'favorites' ? t('Favorites') : kind === 'allItems' ? t('All items') : t('All devices')}
    </ListSubheader>
  );
};

// MenuList skips the header when it picks the item to focus, as it does for ListSubheader itself.
DeviceFavoriteGroupHeader.muiSkipListHighlight = true;
