import { Check, History } from '@mui/icons-material';
import { ListItemIcon, ListItemText, ListSubheader, Menu, MenuItem } from '@mui/material';
import React, { useMemo } from 'react';

import { useAgentChatPalette } from '../../../../../frontend/src/constants/agentChatTheme';
import { useI18n } from '../../../../../frontend/src/i18n/useI18n';
import { usePageOptions } from '../hooks/usePageOptions';
import type { PageOption } from '../types';

interface Props {
  anchor: HTMLElement | null;
  onClose: () => void;
  onPick: (path: string) => void;
  current?: string;
  recent: string[];
  /** Extra items first (swap, close…). */
  header?: React.ReactNode;
}

/** Recent pages, then every menu page grouped by its section. */
export const PageMenu: React.FC<Props> = ({ anchor, onClose, onPick, current, recent, header }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const options = usePageOptions();

  const { recentOptions, sections } = useMemo(() => {
    const byPath = new Map(options.map((o) => [o.path, o]));
    const grouped = new Map<string, PageOption[]>();
    options.forEach((o) => grouped.set(o.section, [...(grouped.get(o.section) ?? []), o]));
    return { recentOptions: recent.map((p) => byPath.get(p)).filter((o): o is PageOption => !!o), sections: [...grouped] };
  }, [options, recent]);

  const item = (o: PageOption, icon?: React.ReactNode) => (
    <MenuItem
      key={`${icon ? 'r' : 'p'}-${o.path}`}
      selected={o.path === current}
      onClick={() => {
        onPick(o.path);
        onClose();
      }}
    >
      <ListItemIcon>{o.path === current ? <Check fontSize="small" sx={{ color: P.accentText }} /> : icon}</ListItemIcon>
      <ListItemText primary={t(o.label)} />
    </MenuItem>
  );

  return (
    <Menu anchorEl={anchor} open={!!anchor} onClose={onClose} slotProps={{ paper: { sx: { minWidth: 260, maxHeight: 520 } } }}>
      {header}
      {recentOptions.length > 0 && [
        <ListSubheader key="recent" sx={{ lineHeight: '32px', fontSize: '0.75rem' }}>
          {t('Recent')}
        </ListSubheader>,
        ...recentOptions.map((o) => item(o, <History fontSize="small" sx={{ color: P.textMuted }} />)),
      ]}
      {sections.map(([section, pages]) => [
        <ListSubheader key={`s-${section}`} sx={{ lineHeight: '32px', fontSize: '0.75rem' }}>
          {t(section)}
        </ListSubheader>,
        ...pages.map((o) => item(o)),
      ])}
    </Menu>
  );
};
