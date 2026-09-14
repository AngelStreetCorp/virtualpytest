/**
 * Navigation form defaults and status clear helpers.
 * Centralizes repeated form reset values and timed status clearing.
 */

import type { NodeForm, EdgeForm } from '../../types/pages/Navigation_Types';

/** Default empty node form for reset/initial state */
export const DEFAULT_NODE_FORM: NodeForm = {
  label: '',
  type: 'screen',
  description: '',
  verifications: [],
};

/** Default empty edge form for reset/initial state */
export const DEFAULT_EDGE_FORM: EdgeForm = {
  edgeId: '',
  action_sets: [],
  default_action_set_id: '',
};

/** Success message auto-clear delay (ms) */
export const SUCCESS_CLEAR_MS = 3000;

/** Error message auto-clear delay (ms) */
export const ERROR_CLEAR_MS = 5000;

/** Schedule clearing success message after delay */
export function scheduleClearSuccess(
  setSuccess: (value: string | null) => void,
  delayMs: number = SUCCESS_CLEAR_MS
): void {
  setTimeout(() => setSuccess(null), delayMs);
}

/** Schedule clearing error message after delay */
export function scheduleClearError(
  setError: (value: string | null) => void,
  delayMs: number = ERROR_CLEAR_MS
): void {
  setTimeout(() => setError(null), delayMs);
}
