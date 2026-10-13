export const MOD_ID = 'blast-radius';

/** Device commands that need a click to confirm. `power_on` is harmless and passes. */
export const DANGEROUS_COMMANDS: ReadonlySet<string> = new Set(['power_off', 'reboot']);
