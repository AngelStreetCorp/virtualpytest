/** What the confirm dialog says, as English keys plus their values. */
export interface CommandWarning {
  title: string;
  message: string;
  confirmText: string;
  vars: Record<string, string>;
}
