/** Shared cell styles of the AI usage tables: one line per row (ellipsis + tooltip), headers on one line too (short labels, ellipsis as a last resort). */
// ui-ok: no-literal-font-size - rem already (follows the Size picker); 12.8 px is between caption and body
export const cellSx = { whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontSize: '0.8rem', py: 0.5 } as const;
export const headSx = { whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', lineHeight: 1.2, py: 0.5, verticalAlign: 'bottom' } as const;
