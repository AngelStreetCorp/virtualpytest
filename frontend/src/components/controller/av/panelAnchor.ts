/**
 * How the panel inside an anchored stream box grows.
 *
 * The outer box of a stream (`VNCStream`, `HDMIStream`) is only the **anchor point**: it
 * carries the offsets (`right: 20px`, `bottom: 56px`, …) and has no size of its own. The
 * visible panel is a child of that box and grows from the anchor.
 *
 * A left-anchored stream grows to the *right* of its anchor; a right-anchored one has to
 * grow to the *left* of it, so that its right edge sits on the anchor. Growing to the
 * right instead pushes the panel past the right edge of the page — which is what the
 * picture-in-picture overlay did until BUG-0777.
 */
export const panelAnchorEdges = (
  anchoredRight: boolean,
): { left: number | 'auto'; right: number | 'auto' } =>
  anchoredRight ? { left: 'auto', right: 0 } : { left: 0, right: 'auto' };
