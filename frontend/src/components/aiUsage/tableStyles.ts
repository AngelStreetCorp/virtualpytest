/** Shared cell styles of the AI usage tables: one line per row (ellipsis + tooltip), headers that wrap, never "…". */
export const cellSx = { whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontSize: '0.8rem', py: 0.5 } as const;
export const headSx = { whiteSpace: 'normal', overflow: 'visible', lineHeight: 1.2, py: 0.5, verticalAlign: 'bottom' } as const;
