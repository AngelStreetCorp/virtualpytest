/** The remote desktop's fixed size. calculateVncScaling keeps the iframe's layout box at
 *  this and shrinks only the render, which is why anything centring the iframe itself has to
 *  reason about a 1440x847 box (see BUG-0104). */
const VNC_RESOLUTION = { width: 1440, height: 847 };

/**
 * The size the scaled render actually occupies — i.e. what you must size a wrapper to if you
 * want to centre it. Centre THAT wrapper, never the iframe: the iframe's own box is the full
 * remote desktop, so as a flex item it gets shrunk and its top-left lands off the card, which
 * is how the previews turned into black rectangles the first time this was attempted.
 */
export const vncScaledSize = (targetSize: { width: number; height: number }) => {
  const scale = Math.min(
    targetSize.width / VNC_RESOLUTION.width,
    targetSize.height / VNC_RESOLUTION.height,
  );
  return {
    width: Math.round(VNC_RESOLUTION.width * scale),
    height: Math.round(VNC_RESOLUTION.height * scale),
  };
};

export const calculateVncScaling = (targetSize: { width: number; height: number }) => {
  const vncResolution = { width: 1440, height: 847 };
  const scaleX = targetSize.width / vncResolution.width;
  const scaleY = targetSize.height / vncResolution.height;
  
  // Use minimum scale to maintain aspect ratio and fit within container
  const scale = Math.min(scaleX, scaleY);
  
  const result = {
    transform: `scale(${scale})`,
    transformOrigin: 'top left',
    width: `${vncResolution.width}px`,
    height: `${vncResolution.height}px`
  };

  // Opt-in debug logging to avoid noisy console spam during normal rerenders.
  if (typeof window !== 'undefined' && (window as any).__VPT_DEBUG_VNC_SCALE__ === true) {
    console.log(`[@utils:vncUtils] VNC scaling calculation:`, {
      targetSize,
      vncResolution,
      scaleX: scaleX.toFixed(3),
      scaleY: scaleY.toFixed(3),
      selectedScale: scale.toFixed(3),
      scaledDimensions: `${Math.round(vncResolution.width * scale)}x${Math.round(vncResolution.height * scale)}`,
      targetDimensions: `${targetSize.width}x${targetSize.height}`,
      transform: result.transform
    });
  }
  
  return result;
};
