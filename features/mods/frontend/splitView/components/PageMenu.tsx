import { Check, ExpandMore } from '@mui/icons-material';
import { Box, ListItemIcon, ListItemText, Menu, MenuItem } from '@mui/material';
import React, { useEffect, useMemo, useRef, useState } from 'react';

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

/** Every menu page grouped by its section. Compact rows; every section is collapsible. */
export const PageMenu: React.FC<Props> = ({ anchor, onClose, onPick, current, recent: _recent, header }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const options = usePageOptions();
  // Ref on the currently selected item: when the menu reopens, focus and scroll
  // it into view so users land on their last selection rather than at the top
  // of the first section.
  const selectedRef = useRef<HTMLLIElement | null>(null);
  // Collapsed sections — every section from the page list. Default all expanded
  // so the first-time UX matches the prior menu; state is local, so a closed
  // and reopened menu keeps the user's current collapse (useful when they
  // reopen to compare two pages without the picker blowing up to its full
  // height again).
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const sections = useMemo(() => {
    const grouped = new Map<string, PageOption[]>();
    options.forEach((o) => grouped.set(o.section, [...(grouped.get(o.section) ?? []), o]));
    return [...grouped];
  }, [options]);

  useEffect(() => {
    if (!anchor) return;
    // Anchor flips on the next frame (after MUI mounts the Menu). Defer so the
    // selected MenuItem is in the DOM when we scroll.
    const id = window.setTimeout(() => {
      const el = selectedRef.current;
      if (!el) return;
      el.scrollIntoView({ block: 'center' });
      // scrollIntoView also moves the menu inside its paper; that does not loop because
      // we run this once per open.
      el.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(id);
  }, [anchor, current, options.length]);

  const toggleSection = (key: string) =>
    setCollapsed((c) => ({ ...c, [key]: !c[key] }));

  // Compact row: tighter padding + smaller label, kept clickable so a future
  // toggle (long press, modifier) can repurpose it without a UI swap.
  const item = (o: PageOption) => {
    const isCurrent = o.path === current;
    return (
      <MenuItem
        key={o.path}
        ref={isCurrent ? selectedRef : undefined}
        selected={isCurrent}
        onClick={() => {
          onPick(o.path);
          onClose();
        }}
        dense
        sx={{ minHeight: 28, py: 0.25 }}
      >
        <ListItemIcon sx={{ minWidth: 28 }}>
          {isCurrent ? (
            <Check fontSize="small" sx={{ color: P.accentText }} />
          ) : (
            <Box sx={{ width: 18, height: 18 }} aria-hidden />
          )}
        </ListItemIcon>
        <ListItemText primary={t(o.label)} primaryTypographyProps={{ fontSize: '0.8125rem' }} />
      </MenuItem>
    );
  };

  const headerSx = {
    minHeight: 26,
    py: 0.25,
    px: 1.5,
    backgroundColor: P.hoverBg,
    borderBottom: `1px solid ${P.borderColor}`,
    color: P.textSecondary,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
    fontSize: '0.6875rem',
    fontWeight: 700,
    '&:hover': { backgroundColor: P.hoverBg },
  };

  const sectionHeader = (key: string, label: string) => {
    const isCollapsed = !!collapsed[key];
    return (
      <MenuItem
        key={`s-${key}`}
        onClick={() => toggleSection(key)}
        disableRipple
        sx={headerSx}
        aria-expanded={!isCollapsed}
      >
        <ListItemIcon sx={{ minWidth: 28, color: P.textSecondary }}>
          <ExpandMore
            fontSize="small"
            sx={{
              transform: isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
              transition: 'transform 120ms ease',
            }}
          />
        </ListItemIcon>
        <ListItemText
          primary={t(label)}
          primaryTypographyProps={{ fontSize: '0.6875rem', fontWeight: 700, letterSpacing: '0.5px' }}
        />
      </MenuItem>
    );
  };

  return (
    <Menu
      anchorEl={anchor}
      open={!!anchor}
      onClose={onClose}
      // Right-align the menu to the trigger: in the split pane the trigger sits
      // at the top-left of the pane and the menu should hang off its right
      // edge instead of bleeding off the left of the screen.
      anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      // Skip MUI's default first-item focus — we focus the user's current page below.
      MenuListProps={{ autoFocusItem: false, dense: true, sx: { py: 0.5, paddingTop: 0, paddingBottom: 0 } }}
      slotProps={{
        paper: { sx: { minWidth: 240, maxHeight: 480, borderRadius: 1.5 } },
      }}
    >
      {header}
      {sections.map(([section, pages]) => [
        sectionHeader(section, section),
        ...(collapsed[section] ? [] : pages.map((o) => item(o))),
      ])}
    </Menu>
  );
};
