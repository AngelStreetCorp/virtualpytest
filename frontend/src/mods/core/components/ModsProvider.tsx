import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { ConfirmDialog } from '../../../components/common/ConfirmDialog';
import { useAuth } from '../../../hooks/auth/useAuth';
import { useToast } from '../../../hooks/useToast';
import { useI18n } from '../../../i18n/useI18n';
import { isAuthEnabled } from '../../../lib/supabase';
import { isEmbedded } from '../../../utils/embeddedMode';
import { ALLOW, EVENT_NAMES, FRAME_EVENT_MESSAGE } from '../constants';
import { useEnabledMods } from '../hooks/useEnabledMods';
import { useModConfirm } from '../hooks/useModConfirm';
import { useModPreferencesSync } from '../hooks/useModPreferencesSync';
import { useModSystemEvents } from '../hooks/useModSystemEvents';
import { useWidgetLayoutSync } from '../hooks/useWidgetLayoutSync';
import { createModRegistry } from '../registry';
import type { GateName, GateResult, ModApi, ModEventEnvelope, ModEventName, ModEvents, ModGates, ModRegistry } from '../types';

interface ModsContextValue {
  registry: ModRegistry;
  api: ModApi;
  openPaneId: string | null;
}

const ModsContext = createContext<ModsContextValue | null>(null);

export const useMods = (): ModsContextValue => {
  const ctx = useContext(ModsContext);
  if (!ctx) throw new Error('useMods must be used within ModsProvider');
  return ctx;
};

/**
 * Ask the mods before the app acts (`device.command`, …). Outside the provider, or with no
 * mod hooked, everything is allowed.
 */
export const useModGate = () => {
  const ctx = useContext(ModsContext);
  return useCallback(
    <K extends GateName>(gate: K, e: ModGates[K]): Promise<GateResult> =>
      ctx ? ctx.registry.gate(ctx.api, gate, e) : Promise.resolve(ALLOW),
    [ctx],
  );
};

/**
 * Send an app-side event to the mods (`control.change`, …). Inside split view's frame the
 * mods live in the main window, so the event is handed up to it. Outside the provider it
 * does nothing.
 */
export const useModEmit = () => {
  const ctx = useContext(ModsContext);
  return useCallback(
    <K extends ModEventName>(event: K, e: ModEvents[K]) => {
      if (isEmbedded) {
        window.parent.postMessage({ type: FRAME_EVENT_MESSAGE, name: event, e }, window.location.origin);
        return;
      }
      if (ctx) ctx.registry.emit(ctx.api, event, e);
    },
    [ctx],
  );
};

export const ModsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { t } = useI18n();
  const { showSuccess, showError, showWarning, showInfo } = useToast();
  const [openPaneId, setOpenPaneId] = useState<string | null>(null);
  const { pending, confirm, answer } = useModConfirm();
  const { enabled: chosen, installed } = useEnabledMods();
  // No mods inside split view's frame: the main window already draws them.
  const enabled = useMemo(() => (isEmbedded ? [] : chosen), [chosen]);
  const { isAuthenticated } = useAuth();
  // The server refuses a signed-out page; start (again) once signed in.
  const signedIn = !isAuthEnabled || isAuthenticated;
  // Only a deployment that ships mods asks the server for saved choices.
  useModPreferencesSync(!isEmbedded && signedIn && installed.length > 0);
  useWidgetLayoutSync(!isEmbedded && signedIn && installed.length > 0);
  // A switch on the Mods page rebuilds the chains; mod state lives in stores and survives it.
  const registry = useMemo(() => createModRegistry(enabled), [enabled]);

  const api = useMemo<ModApi>(() => {
    const toasts = { success: showSuccess, error: showError, warning: showWarning, info: showInfo };
    return {
      ui: {
        toast: (text, severity = 'info') => toasts[severity](text),
        openPane: (paneId) => setOpenPaneId(paneId),
        closePane: () => setOpenPaneId(null),
        confirm,
      },
      clock: { now: () => Date.now() },
    };
  }, [showSuccess, showError, showWarning, showInfo, confirm]);

  const onEvent = useCallback((envelope: ModEventEnvelope) => registry.dispatch(api, envelope), [registry, api]);
  useModSystemEvents(onEvent, signedIn && enabled.length > 0);

  // App events handed up by split view's frame (same origin only).
  useEffect(() => {
    if (isEmbedded) return undefined;
    const onMessage = (msg: MessageEvent) => {
      const data = msg.data as { type?: string; name?: string; e?: unknown } | null;
      if (msg.origin !== window.location.origin || data?.type !== FRAME_EVENT_MESSAGE) return;
      if (!(EVENT_NAMES as readonly string[]).includes(data.name ?? '')) return;
      registry.emit(api, data.name as ModEventName, data.e as never);
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [registry, api]);

  const value = useMemo(() => ({ registry, api, openPaneId }), [registry, api, openPaneId]);
  return (
    <ModsContext.Provider value={value}>
      {children}
      <ConfirmDialog
        open={pending !== null}
        title={pending?.title}
        message={pending?.message ?? ''}
        confirmText={pending?.confirmText}
        cancelText={t('Cancel')}
        confirmColor={pending?.danger ? 'error' : 'primary'}
        onConfirm={() => answer(true)}
        onCancel={() => answer(false)}
      />
    </ModsContext.Provider>
  );
};
