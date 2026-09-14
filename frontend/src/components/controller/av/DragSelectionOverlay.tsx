import { Box } from '@mui/material';
import React, { useState, useCallback, useRef, useEffect } from 'react';

import { getZIndex } from '../../../utils/zIndexUtils';
import { AGENT_CHAT_PALETTE } from '../../../constants/agentChatTheme';

interface DragArea {
  x: number;
  y: number;
  width: number;
  height: number;
  // Fuzzy search area (optional)
  fx?: number;
  fy?: number;
  fwidth?: number;
  fheight?: number;
}

/**
 * Round area coordinates to 2 decimal places
 * Prevents excessive precision in database and cleaner UX
 */
const roundAreaCoordinates = (area: DragArea, maxDecimals: number = 2): DragArea => {
  const rounded: DragArea = {
    x: Number(area.x.toFixed(maxDecimals)),
    y: Number(area.y.toFixed(maxDecimals)),
    width: Number(area.width.toFixed(maxDecimals)),
    height: Number(area.height.toFixed(maxDecimals)),
  };

  // Round fuzzy area if present
  if (area.fx !== undefined) rounded.fx = Number(area.fx.toFixed(maxDecimals));
  if (area.fy !== undefined) rounded.fy = Number(area.fy.toFixed(maxDecimals));
  if (area.fwidth !== undefined) rounded.fwidth = Number(area.fwidth.toFixed(maxDecimals));
  if (area.fheight !== undefined) rounded.fheight = Number(area.fheight.toFixed(maxDecimals));

  return rounded;
};

interface DragSelectionOverlayProps {
  imageRef: React.RefObject<HTMLImageElement>;
  onAreaSelected: (area: DragArea) => void;
  selectedArea: DragArea | null;
  // When false, Shift+drag fuzzy-area selection is disabled (e.g. text verification
  // does not use a fuzzy search area). Defaults to true.
  allowFuzzy?: boolean;
  // Fired whenever an area drag starts/stops so the parent can hide any on-top
  // widgets (e.g. video playback controls) that would otherwise block dragging
  // across the whole image.
  onDraggingChange?: (dragging: boolean) => void;
  sx?: any;
}

export const DragSelectionOverlay: React.FC<DragSelectionOverlayProps> = ({
  imageRef,
  onAreaSelected,
  selectedArea,
  allowFuzzy = true,
  onDraggingChange,
  sx = {},
}) => {
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [currentDrag, setCurrentDrag] = useState<DragArea | null>(null);
  const [isHoveringImage, setIsHoveringImage] = useState(false);
  const [isFuzzyMode, setIsFuzzyMode] = useState(false); // Track if Shift key is held
  const overlayRef = useRef<HTMLDivElement>(null);

  // Notify parent when a drag begins/ends (kept in a ref so the effect never
  // re-subscribes on a new callback identity).
  const onDraggingChangeRef = useRef(onDraggingChange);
  useEffect(() => {
    onDraggingChangeRef.current = onDraggingChange;
  }, [onDraggingChange]);
  useEffect(() => {
    onDraggingChangeRef.current?.(isDragging);
  }, [isDragging]);

  // ESC key handler to cancel drag in progress
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (isDragging && e.key === 'Escape') {
        console.log('[DragSelectionOverlay] ESC pressed - canceling drag');
        setIsDragging(false);
        setDragStart(null);
        setCurrentDrag(null);
        setIsFuzzyMode(false);
        e.preventDefault();
        e.stopPropagation();
      }
    };

    if (isDragging) {
      document.addEventListener('keydown', handleKeyDown);
    }

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isDragging]);

  const getImageBounds = useCallback(() => {
    if (!imageRef.current || !overlayRef.current) {
      return null;
    }

    const image = imageRef.current;
    const overlay = overlayRef.current;

    const imageRect = image.getBoundingClientRect();
    const overlayRect = overlay.getBoundingClientRect();

    // Calculate the actual displayed image dimensions (accounting for object-fit: contain)
    const imageAspectRatio = image.naturalWidth / image.naturalHeight;
    const containerAspectRatio = imageRect.width / imageRect.height;

    let displayedWidth, displayedHeight, offsetX, offsetY;

    if (imageAspectRatio > containerAspectRatio) {
      // Image is wider than container - limited by width
      displayedWidth = imageRect.width;
      displayedHeight = imageRect.width / imageAspectRatio;
      offsetX = 0;
      offsetY = (imageRect.height - displayedHeight) / 2;
    } else {
      // Image is taller than container - limited by height
      displayedWidth = imageRect.height * imageAspectRatio;
      displayedHeight = imageRect.height;
      offsetX = (imageRect.width - displayedWidth) / 2;
      offsetY = 0;
    }

    return {
      left: imageRect.left - overlayRect.left + offsetX,
      top: imageRect.top - overlayRect.top + offsetY,
      width: displayedWidth,
      height: displayedHeight,
      scaleX: image.naturalWidth / displayedWidth,
      scaleY: image.naturalHeight / displayedHeight,
    };
  }, [imageRef]);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (!imageRef.current) return;

      const bounds = getImageBounds();
      if (!bounds) return;

      const rect = e.currentTarget.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      // Detect if Shift key is pressed for fuzzy mode (only when fuzzy is allowed)
      const isFuzzy = allowFuzzy && e.shiftKey;
      setIsFuzzyMode(isFuzzy);

      // Check if click is within image bounds
      if (
        x >= bounds.left &&
        x <= bounds.left + bounds.width &&
        y >= bounds.top &&
        y <= bounds.top + bounds.height
      ) {
        setIsDragging(true);
        setDragStart({ x, y });
        setCurrentDrag(null);
        e.preventDefault();
        e.stopPropagation();
      }
    },
    [imageRef, getImageBounds, allowFuzzy],
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!imageRef.current) return;

      const bounds = getImageBounds();
      if (!bounds) return;

      const rect = e.currentTarget.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      // Check if hovering over image area
      const isOverImage =
        x >= bounds.left &&
        x <= bounds.left + bounds.width &&
        y >= bounds.top &&
        y <= bounds.top + bounds.height;
      setIsHoveringImage(isOverImage);

      // Handle dragging logic only if currently dragging
      if (!isDragging || !dragStart) return;

      // Constrain mouse to image bounds during drag
      const constrainedX = Math.max(bounds.left, Math.min(bounds.left + bounds.width, x));
      const constrainedY = Math.max(bounds.top, Math.min(bounds.top + bounds.height, y));

      const startX = Math.max(bounds.left, Math.min(bounds.left + bounds.width, dragStart.x));
      const startY = Math.max(bounds.top, Math.min(bounds.top + bounds.height, dragStart.y));

      const left = Math.min(startX, constrainedX) - bounds.left;
      const top = Math.min(startY, constrainedY) - bounds.top;
      const width = Math.abs(constrainedX - startX);
      const height = Math.abs(constrainedY - startY);

      // Minimum size constraint
      if (width >= 10 && height >= 10) {
        setCurrentDrag({ x: left, y: top, width, height });
      }
    },
    [isDragging, dragStart, imageRef, getImageBounds],
  );

  const handleMouseUp = useCallback(() => {
    if (!isDragging || !currentDrag || !imageRef.current) {
      setIsDragging(false);
      setDragStart(null);
      setCurrentDrag(null);
      setIsFuzzyMode(false);
      return;
    }

    const bounds = getImageBounds();
    if (!bounds || !onAreaSelected) {
      setIsDragging(false);
      setDragStart(null);
      setCurrentDrag(null);
      setIsFuzzyMode(false);
      return;
    }

    // Convert to original image coordinates
    const draggedArea = {
      x: currentDrag.x * bounds.scaleX,
      y: currentDrag.y * bounds.scaleY,
      width: currentDrag.width * bounds.scaleX,
      height: currentDrag.height * bounds.scaleY,
    };

    // Round coordinates to integers (no decimals) for clean data
    const roundedDraggedArea = roundAreaCoordinates(draggedArea, 0);

    // If fuzzy mode, save to fuzzy area fields; otherwise save to exact area fields
    let updatedArea: DragArea;
    if (isFuzzyMode) {
      // Save as fuzzy area, preserve existing exact area
      updatedArea = {
        ...(selectedArea || { x: 0, y: 0, width: 0, height: 0 }),
        fx: roundedDraggedArea.x,
        fy: roundedDraggedArea.y,
        fwidth: roundedDraggedArea.width,
        fheight: roundedDraggedArea.height,
      };
      console.log('[@DragSelectionOverlay] Saved fuzzy area (rounded to integers):', {
        fx: roundedDraggedArea.x,
        fy: roundedDraggedArea.y,
        fwidth: roundedDraggedArea.width,
        fheight: roundedDraggedArea.height,
      });
    } else {
      // Save as exact area, preserve existing fuzzy area
      updatedArea = {
        ...roundedDraggedArea,
        ...(selectedArea?.fx !== undefined && {
          fx: selectedArea.fx,
          fy: selectedArea.fy,
          fwidth: selectedArea.fwidth,
          fheight: selectedArea.fheight,
        }),
      };
      console.log('[@DragSelectionOverlay] Saved exact area (rounded to integers):', roundedDraggedArea);
    }

    onAreaSelected(updatedArea);
    setIsDragging(false);
    setDragStart(null);
    setCurrentDrag(null);
    setIsFuzzyMode(false);
  }, [isDragging, currentDrag, imageRef, getImageBounds, onAreaSelected, isFuzzyMode, selectedArea]);

  // Finalize the drag even when the mouse is released OUTSIDE the overlay. Without
  // a document-level listener, releasing off the image never fires the overlay's
  // onMouseUp and the drag stays stuck on. The currentDrag is already constrained
  // to the image bounds, so this just commits whatever selection is shown.
  useEffect(() => {
    if (!isDragging) return;
    document.addEventListener('mouseup', handleMouseUp);
    return () => document.removeEventListener('mouseup', handleMouseUp);
  }, [isDragging, handleMouseUp]);

  // Display area for exact selection (white box)
  const displayExactArea =
    (!isDragging || !isFuzzyMode) && currentDrag
      ? currentDrag
      : selectedArea && getImageBounds()
      ? {
          x: selectedArea.x / getImageBounds()!.scaleX,
          y: selectedArea.y / getImageBounds()!.scaleY,
          width: selectedArea.width / getImageBounds()!.scaleX,
          height: selectedArea.height / getImageBounds()!.scaleY,
        }
      : null;

  // Display area for fuzzy selection (yellow box)
  const displayFuzzyArea =
    (isDragging && isFuzzyMode && currentDrag)
      ? currentDrag
      : selectedArea?.fx !== undefined && getImageBounds()
      ? {
          x: selectedArea.fx / getImageBounds()!.scaleX,
          y: selectedArea.fy! / getImageBounds()!.scaleY,
          width: selectedArea.fwidth! / getImageBounds()!.scaleX,
          height: selectedArea.fheight! / getImageBounds()!.scaleY,
        }
      : null;

  return (
    <Box
      ref={overlayRef}
      sx={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        cursor: isDragging ? 'crosshair' : isHoveringImage ? 'crosshair' : 'default',
        userSelect: 'none',
        pointerEvents: 'auto', // Always allow pointer events
        zIndex: getZIndex('SCREENSHOT_CAPTURE_OVERLAY'), // Above all overlays including AndroidMobileOverlay
        ...sx,
      }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
    >
      {/* Fuzzy area rectangle (yellow) - render first so exact area is on top */}
      {displayFuzzyArea && getImageBounds() && (
        <Box
          sx={{
            position: 'absolute',
            left: getImageBounds()!.left + displayFuzzyArea.x,
            top: getImageBounds()!.top + displayFuzzyArea.y,
            width: displayFuzzyArea.width,
            height: displayFuzzyArea.height,
            border: `2px solid ${AGENT_CHAT_PALETTE.gold}`,
            backgroundColor: 'rgba(200, 200, 200, 0.2)',
            pointerEvents: 'none',
            boxSizing: 'border-box',
            zIndex: 1,
          }}
        />
      )}

      {/* Exact area rectangle (black) */}
      {displayExactArea && getImageBounds() && (
        <Box
          sx={{
            position: 'absolute',
            left: getImageBounds()!.left + displayExactArea.x,
            top: getImageBounds()!.top + displayExactArea.y,
            width: displayExactArea.width,
            height: displayExactArea.height,
            border: '2px solid black',
            backgroundColor: 'rgba(200, 200, 200, 0.2)',
            pointerEvents: 'none',
            boxSizing: 'border-box',
            zIndex: 2,
          }}
        />
      )}
    </Box>
  );
};

export default DragSelectionOverlay;
