export interface SplitState {
  open: boolean;
  /** Page shown in the second pane, router path (no proxy prefix). */
  path: string;
  widthPct: number;
  /** Last pages opened beside, newest first. */
  recent: string[];
}

/** A page offered in the picker. */
export interface PageOption {
  path: string;
  /** English nav label (an i18n key). */
  label: string;
  /** English nav section (Top, Monitoring, Test › Build…). */
  section: string;
}
