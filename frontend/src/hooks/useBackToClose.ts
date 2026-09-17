import { useEffect, useRef } from 'react';

/**
 * Let the system Back button close an overlay instead of navigating away from it.
 *
 * A dialog is not a route, so it leaves no trace in history: pressing Back with one open used
 * to act on whatever was underneath — in the mobile app, where MainActivity now walks the
 * WebView's history, that means leaving the page you were looking at (and before that fix,
 * leaving the app outright). Pushing one entry while the overlay is open gives Back something
 * of its own to pop, and popping it is the signal to close.
 *
 * On the web this makes browser Back close the dialog too, which is what people expect there.
 */
export const useBackToClose = (open: boolean, onClose: () => void) => {
  // Kept in a ref so a caller passing a fresh closure each render does not re-run the effect
  // and push an entry per render.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return undefined;

    window.history.pushState({ vptOverlay: true }, '');
    let closedByBack = false;
    const handlePop = () => {
      closedByBack = true;
      onCloseRef.current();
    };
    window.addEventListener('popstate', handlePop);

    return () => {
      window.removeEventListener('popstate', handlePop);
      // Closed some other way (its own X, a click outside, Escape): drop the entry again, or
      // Back would have to be pressed twice to leave the page it was opened from.
      if (!closedByBack) window.history.back();
    };
  }, [open]);
};
