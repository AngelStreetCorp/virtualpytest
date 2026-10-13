import { useCallback, useRef, useState } from 'react';

import type { ConfirmOptions } from '../types';

interface Pending {
  options: ConfirmOptions;
  resolve: (ok: boolean) => void;
}

/** `$.ui.confirm`: one question at a time; a newer one cancels the one still open. */
export const useModConfirm = () => {
  const [pending, setPending] = useState<Pending | null>(null);
  const pendingRef = useRef<Pending | null>(null);

  const confirm = useCallback(
    (options: ConfirmOptions) =>
      new Promise<boolean>((resolve) => {
        pendingRef.current?.resolve(false);
        pendingRef.current = { options, resolve };
        setPending(pendingRef.current);
      }),
    [],
  );

  const answer = useCallback((ok: boolean) => {
    pendingRef.current?.resolve(ok);
    pendingRef.current = null;
    setPending(null);
  }, []);

  return { pending: pending?.options ?? null, confirm, answer };
};
