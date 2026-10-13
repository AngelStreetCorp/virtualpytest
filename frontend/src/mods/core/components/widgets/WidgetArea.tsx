import { Add, Widgets } from '@mui/icons-material';
import { Box, Button, ListItemIcon, ListItemText, Menu, MenuItem } from '@mui/material';
import React, { useState } from 'react';

import { useAgentChatPalette } from '../../../../constants/agentChatTheme';
import { useI18n } from '../../../../i18n/useI18n';
import { WIDGET_COLUMNS } from '../../constants';
import { useWidgetArea } from '../../hooks/useWidgetArea';
import type { WidgetAreaName, WidgetDefinition, WidgetSettings } from '../../types';

import { WidgetFrame } from './WidgetFrame';
import { WidgetSettingsDialog } from './WidgetSettingsDialog';

/**
 * The "+ Add widget" button + the menu it opens (TASK-77). Lives in the page
 * header so it sits next to the page title, not below the placed widgets.
 * Returns null when no mod that is on offers a widget for this area.
 */
export const WidgetAddButton: React.FC<{ area: WidgetAreaName }> = ({ area }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { available, add } = useWidgetArea(area);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);

  if (available.length === 0) return null;

  return (
    <>
      <Button size="small" startIcon={<Add />} onClick={(e) => setAnchor(e.currentTarget)} sx={{ color: P.accentText }}>
        {t('Add widget')}
      </Button>
      <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
        {available.map((def) => (
          <MenuItem
            key={def.id}
            onClick={() => {
              add(def);
              setAnchor(null);
            }}
          >
            <ListItemIcon>
              <Widgets fontSize="small" sx={{ color: P.accentText }} />
            </ListItemIcon>
            <ListItemText primary={t(def.name)} secondary={t(def.description)} />
          </MenuItem>
        ))}
      </Menu>
    </>
  );
};

/**
 * The placed widgets grid (TASK-77). Nothing shows when no widget is placed;
 * the "+ Add widget" button that opens the picker is in `<WidgetAddButton>`
 * (rendered separately in the page header).
 */
export const WidgetArea: React.FC<{ area: WidgetAreaName }> = ({ area }) => {
  const { t } = useI18n();
  const { api, available, placed, remove, move, configure } = useWidgetArea(area);
  const [editing, setEditing] = useState<{ id: string; def: WidgetDefinition; settings: WidgetSettings } | null>(null);

  if (available.length === 0) return null;
  if (placed.length === 0) return null;

  return (
    <Box sx={{ mb: 1.5 }}>
      <Box sx={{ display: 'grid', gridTemplateColumns: `repeat(${WIDGET_COLUMNS}, 1fr)`, gap: 1.5, mb: 1 }}>
        {placed.map(({ instance, def, settings }, i) => (
          <WidgetFrame
            key={instance.id}
            title={t(def.name)}
            size={def.size}
            hasSettings={(def.settings ?? []).length > 0}
            isFirst={i === 0}
            isLast={i === placed.length - 1}
            onSettings={() => setEditing({ id: instance.id, def, settings })}
            onMove={(step) => move(instance.id, step)}
            onRemove={() => remove(instance.id)}
          >
            <def.Component settings={settings} $={api} />
          </WidgetFrame>
        ))}
      </Box>
      <WidgetSettingsDialog
        def={editing?.def ?? null}
        settings={editing?.settings ?? {}}
        onSave={(s) => editing && configure(editing.id, s)}
        onClose={() => setEditing(null)}
      />
    </Box>
  );
};
