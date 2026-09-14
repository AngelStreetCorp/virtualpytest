import React, { useEffect } from 'react';
import { createPortal } from 'react-dom';

import { getZIndex } from '../../utils/zIndexUtils';

interface ScreenshotModalProps {
  open: boolean;
  screenshotUrl?: string | null;
  alt?: string;
  onClose: () => void;
}

/**
 * Full-screen screenshot viewer shared by navigation + action nodes (and any
 * other place that double-clicks a preview). Closes on: backdrop click (clicking
 * anywhere around the image), the visible close cross, and the Escape key.
 *
 * Rendered via a portal to document.body so it escapes React Flow's transformed
 * canvas. The image has pointer-events: none so a click on it bubbles to the
 * backdrop and still closes.
 */
export const ScreenshotModal: React.FC<ScreenshotModalProps> = ({
  open,
  screenshotUrl,
  alt = 'Screenshot',
  onClose,
}) => {
  // Close on Escape while open.
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  if (!open || !screenshotUrl) return null;

  const close = (e?: React.MouseEvent) => {
    e?.stopPropagation();
    e?.preventDefault();
    onClose();
  };

  const modal = (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.95)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: getZIndex('SCREENSHOT_MODAL'),
        cursor: 'pointer',
        padding: '20px',
      }}
      onClick={close}
      onDoubleClick={(e) => {
        e.stopPropagation();
        e.preventDefault();
      }}
      title="Click anywhere or press Esc to close"
    >
      {/* Visible close button (Esc and click-anywhere also close) */}
      <button
        type="button"
        onClick={close}
        aria-label="Close"
        style={{
          position: 'fixed',
          top: '16px',
          right: '16px',
          width: '40px',
          height: '40px',
          borderRadius: '50%',
          border: 'none',
          background: 'rgba(0, 0, 0, 0.6)',
          color: '#fff',
          fontSize: '24px',
          lineHeight: '40px',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: getZIndex('SCREENSHOT_MODAL') + 1,
        }}
      >
        ✕
      </button>
      {/* Full-size screenshot */}
      <img
        src={screenshotUrl}
        alt={alt}
        style={{
          width: 'auto',
          height: 'auto',
          maxWidth: '95vw',
          maxHeight: '95vh',
          objectFit: 'contain',
          borderRadius: '8px',
          boxShadow: '0 4px 20px rgba(0, 0, 0, 0.5)',
          display: 'block',
          pointerEvents: 'none',
        }}
      />
    </div>
  );

  return createPortal(modal, document.body);
};
