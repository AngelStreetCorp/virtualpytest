import { useCallback, useRef, useState } from 'react';

export interface ResizableColumnDef {
  key: string;
  initialWidth: number;
  minWidth?: number;
}

export const useResizableColumns = (columns: ResizableColumnDef[]) => {
  const [widths, setWidths] = useState<Record<string, number>>(() => {
    const initial: Record<string, number> = {};
    for (const col of columns) initial[col.key] = col.initialWidth;
    return initial;
  });

  const dragState = useRef<{ key: string; startX: number; startWidth: number } | null>(null);

  const onMouseDown = useCallback(
    (key: string) => (e: React.MouseEvent) => {
      e.preventDefault();
      const col = columns.find((c) => c.key === key);
      if (!col) return;

      dragState.current = { key, startX: e.clientX, startWidth: widths[key] };

      const onMouseMove = (ev: MouseEvent) => {
        if (!dragState.current) return;
        const delta = ev.clientX - dragState.current.startX;
        const minW = col.minWidth ?? 40;
        const newWidth = Math.max(minW, dragState.current.startWidth + delta);
        setWidths((prev) => ({ ...prev, [key]: newWidth }));
      };

      const onMouseUp = () => {
        dragState.current = null;
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
      };

      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
    },
    [columns, widths],
  );

  const headerCellSx = (key: string) => ({
    width: widths[key],
    minWidth: widths[key],
    maxWidth: widths[key],
    position: 'relative' as const,
    userSelect: 'none' as const,
    whiteSpace: 'nowrap' as const,
    overflow: 'hidden',
  });

  const bodyCellSx = (key: string) => ({
    width: widths[key],
    minWidth: widths[key],
    maxWidth: widths[key],
    whiteSpace: 'nowrap' as const,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  });

  const resizeHandleSx = {
    position: 'absolute' as const,
    right: 0,
    top: 0,
    bottom: 0,
    width: 4,
    cursor: 'col-resize',
    backgroundColor: 'divider',
    '&:hover': { backgroundColor: 'primary.main' },
  };

  return { widths, onMouseDown, headerCellSx, bodyCellSx, resizeHandleSx };
};
