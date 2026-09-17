/**
 * What clicking a phone slot's REC preview card does while no phone is on it.
 *
 * A `phone_agent` slot always has a stream — the host writes a placeholder frame into it so
 * ffmpeg has a valid source (TASK-17 §1.1) — so the card looks alive and opening the stream
 * modal gets you a full-screen "phone offline" picture and nothing to do. When the slot has no
 * phone, the useful thing to offer is the pairing code, so this takes the click and opens the
 * same dialog the "Mobile app & phones" page uses.
 *
 * Core cannot decide this on its own: "is a phone on this slot?" lives behind
 * /server/mobile-app, which is this feature's. So core asks the feature registry whether anyone
 * wants a given device model's preview click and renders what it gets back; this component
 * answers by reporting `canHandle` up to the card. A slot with a connected phone reports false
 * and the card opens the stream modal exactly as before.
 */
import { useEffect } from 'react';

import PairQrDialog from './PairQrDialog';
import { useMobileApp, type PhoneSlotState } from './hooks/useMobileApp';

/** States in which the slot has no phone streaming, so pairing is the useful offer. */
const PAIRABLE_STATES: PhoneSlotState[] = ['free', 'pending', 'offline', 'unknown'];

export interface PhoneSlotPreviewActionProps {
  hostName: string;
  deviceId: string;
  open: boolean;
  onClose: () => void;
  /** Told whether this component wants the card's click. */
  onCanHandleChange: (canHandle: boolean) => void;
}

export default function PhoneSlotPreviewAction({
  hostName,
  deviceId,
  open,
  onClose,
  onCanHandleChange,
}: PhoneSlotPreviewActionProps) {
  const { hosts, refresh, createPairing } = useMobileApp();

  const slot = hosts
    .find((h) => h.host_name === hostName)
    ?.slots.find((s) => s.device_id === deviceId);
  const canHandle = slot ? PAIRABLE_STATES.includes(slot.state) : false;

  useEffect(() => {
    onCanHandleChange(canHandle);
  }, [canHandle, onCanHandleChange]);

  // Only while the code is up: that is the one moment a scan can land, and the phone
  // connecting is what closes the dialog.
  useEffect(() => {
    if (!open) return;
    const timer = setInterval(() => refresh(), 1000);
    return () => clearInterval(timer);
  }, [open, refresh]);

  // The phone is on the slot now — the code on screen is spent. Close rather than leave a
  // dead QR up; the card goes back to opening the stream, which by then has a picture in it.
  useEffect(() => {
    if (open && !canHandle) onClose();
  }, [open, canHandle, onClose]);

  if (!open || !canHandle) return null;

  return (
    <PairQrDialog
      hostName={hostName}
      deviceId={deviceId}
      createPairing={createPairing}
      onClose={onClose}
    />
  );
}
