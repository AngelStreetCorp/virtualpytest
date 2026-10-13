import { Box } from '@mui/material';
import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { LAYOUT_VIEWS, fitLayout, layoutForCount } from '../../../constants/deviceLayouts';
import type { LayoutViewId } from '../../../types/pages/deviceLayout.types';
import type { GroupMember } from '../../../types/pages/groupControl.types';
import { DeviceLayout } from '../layout/DeviceLayout';
import { ViewMenu } from '../layout/ViewMenu';

import { GroupStreamCell } from './GroupStreamCell';

interface GroupStreamGridProps {
  members: GroupMember[];
  focusKey: string | null;
  onToggleFocus: (key: string) => void;
  onIncludedChange: (key: string, included: boolean) => void;
  onTap?: (key: string, point: { x_pct: number; y_pct: number }) => void;
  /** Where the View menu renders (the modal's Models row); inline above the grid without it. */
  viewMenuTarget?: HTMLElement | null;
  /** Members whose page tile already plays live; their cell borrows that player through `onStreamSlot`. */
  reusableStreamKeys?: ReadonlySet<string>;
  onStreamSlot?: (key: string, el: HTMLElement | null) => void;
}

/**
 * The group's streams in a TASK-75 layout: the smallest grid that holds them by default,
 * any layout from the View menu. Focusing a stream turns the focused cell into a hero
 * (its own large area on top) and keeps the rest in their original order as a small
 * thumbnail bar below — the cell never moves left/right, only its area resizes.
 * Unfocusing returns to the layout that was active before the focus.
 */
export const GroupStreamGrid: React.FC<GroupStreamGridProps> = ({
  members,
  focusKey,
  onToggleFocus,
  onIncludedChange,
  onTap,
  viewMenuTarget,
  reusableStreamKeys,
  onStreamSlot,
}) => {
  const P = useAgentChatPalette();
  const [viewId, setViewId] = useState<LayoutViewId>(() => layoutForCount(members.length).id);
  // The layout to return to when the user unfocuses (BUG-0440). Updated
  // every time the user picks a new non-focus layout from the View menu.
  // Stays at the auto-fit default if they never change the View menu.
  const lastNonFocusViewId = useRef<LayoutViewId>(viewId);
  const base = LAYOUT_VIEWS.find((v) => v.id === viewId) ?? layoutForCount(members.length);
  const view = fitLayout(base, members.length);

  // Track non-focus layout changes so we can restore them on unfocus.
  useEffect(() => {
    if (!view.focus) lastNonFocusViewId.current = viewId;
  }, [viewId, view.focus]);

  // When focusKey clears (user clicked Unfocus), drop back to the last
  // non-focus layout the user had selected.
  useEffect(() => {
    if (focusKey === null && view.focus) setViewId(lastNonFocusViewId.current);
    // We intentionally only react to focusKey changes here; reading view.focus
    // would cause the effect to also fire when the user picks a focus layout
    // manually, which would undo their pick.
     
  }, [focusKey]);

  const focused = focusKey ? members.find((m) => m.key === focusKey) : null;
  const showProfile = new Set(members.filter((m) => m.controlled).map((m) => m.chosenProfile)).size > 1;

  const viewMenu = (
    <ViewMenu
      view={base}
      onChange={(id) => setViewId(id as LayoutViewId)}
      layoutsOnly
      itemCount={members.length}
    />
  );

  const streamSlotFor = (key: string) => (reusableStreamKeys?.has(key) ? onStreamSlot : undefined);

  const handleToggleFocus = (key: string) => {
    onToggleFocus(key);
  };

  // Focused mode: a hero on top (the focused cell, full area) and a small
  // thumbnail bar below in the original members order so the user can see
  // the relative position of every cell. The focused cell itself is NOT in
  // the bar (it is the hero), and the original order is preserved — so
  // "left/right position" of every cell stays the same; only the focused
  // cell's area grows (BUG-0441).
  if (focused) {
    const others = members.filter((m) => m.key !== focusKey);
    return (
      <Box
        sx={{
          flex: 1,
          minWidth: 0,
          display: 'flex',
          flexDirection: 'column',
          p: 1.5,
          gap: 1,
          bgcolor: P.background,
        }}
      >
        <Box sx={{ flex: 1, minHeight: 0 }}>
          <GroupStreamCell
            member={focused}
            isFocused
            showProfile={showProfile}
            onToggleFocus={handleToggleFocus}
            onIncludedChange={onIncludedChange}
            onTap={onTap}
            onStreamSlot={streamSlotFor(focused.key)}
          />
        </Box>
        <Box
          sx={{
            display: 'flex',
            gap: 1,
            height: 96,
            overflowX: 'auto',
            flexShrink: 0,
          }}
        >
          {others.map((m) => (
            <Box key={m.key} sx={{ flex: '0 0 160px', height: '100%' }}>
              <GroupStreamCell
                member={m}
                isFocused={false}
                showProfile={showProfile}
                onToggleFocus={handleToggleFocus}
                onIncludedChange={onIncludedChange}
                onTap={onTap}
                onStreamSlot={streamSlotFor(m.key)}
              />
            </Box>
          ))}
        </Box>
      </Box>
    );
  }

  return (
    <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', p: 1.5, gap: 1, bgcolor: P.background }}>
      {viewMenuTarget
        ? createPortal(viewMenu, viewMenuTarget)
        : <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>{viewMenu}</Box>}
      <Box sx={{ flex: 1, minHeight: 0 }}>
        {/* A layout with fewer slots than members falls back to the smallest grid that holds them all. */}
        <DeviceLayout
          view={view.slots >= members.length ? view : fitLayout(layoutForCount(members.length), members.length)}
          height="100%"
          items={members.map((m) => ({
            key: m.key,
            node: (
              <GroupStreamCell
                member={m}
                isFocused={false}
                showProfile={showProfile}
                onToggleFocus={handleToggleFocus}
                onIncludedChange={onIncludedChange}
                onTap={onTap}
                onStreamSlot={streamSlotFor(m.key)}
              />
            ),
          }))}
        />
      </Box>
    </Box>
  );
};
