/**
 * Nintendo Switch Pro Controller remote (switch controller `bluetooth_procon`).
 *
 * The panel shows a front photo of a Pro Controller with clickable hotspots.
 * The photo is a separate swappable file (only `image_url` references it); a
 * replacement must keep the same framing or the hotspot coordinates below
 * must be re-measured.
 *
 * Coordinates are in image pixels of `image_size` (hotspot CENTER + size).
 * Negative y = the strip drawn above the photo (`top_strip_height`): the
 * triggers ZL / ZR are not visible from the front, so they sit in that strip
 * right above their bumpers L / R, which overlay the top corners of the photo.
 * Each hotspot sends `command` to /server/av/switch/command.
 */

export interface SwitchHotspot {
  label: string;
  command: string;
  x: number;
  y: number;
  width: number;
  height: number;
  shape: 'circle' | 'rectangle';
  comment: string;
}

const STICK_OFFSET = 44; // tap-direction hotspots sit on the stick's outer ring
const STICK_ZONE = 26;

const stick = (side: 'left' | 'right', cx: number, cy: number, click: string) => ({
  [`${side}_stick_click`]: {
    label: click,
    command: `press:${click.toLowerCase()}`,
    x: cx,
    y: cy,
    width: 46,
    height: 46,
    shape: 'circle' as const,
    comment: `${side} stick click (${click})`,
  },
  [`${side}_stick_up`]: {
    label: '▲',
    command: `stick:${side},up`,
    x: cx,
    y: cy - STICK_OFFSET,
    width: STICK_ZONE,
    height: STICK_ZONE,
    shape: 'circle' as const,
    comment: `${side} stick up`,
  },
  [`${side}_stick_down`]: {
    label: '▼',
    command: `stick:${side},down`,
    x: cx,
    y: cy + STICK_OFFSET,
    width: STICK_ZONE,
    height: STICK_ZONE,
    shape: 'circle' as const,
    comment: `${side} stick down`,
  },
  [`${side}_stick_left`]: {
    label: '◀',
    command: `stick:${side},left`,
    x: cx - STICK_OFFSET,
    y: cy,
    width: STICK_ZONE,
    height: STICK_ZONE,
    shape: 'circle' as const,
    comment: `${side} stick left`,
  },
  [`${side}_stick_right`]: {
    label: '▶',
    command: `stick:${side},right`,
    x: cx + STICK_OFFSET,
    y: cy,
    width: STICK_ZONE,
    height: STICK_ZONE,
    shape: 'circle' as const,
    comment: `${side} stick right`,
  },
});

const button = (
  label: string,
  name: string,
  x: number,
  y: number,
  size: number,
  shape: 'circle' | 'rectangle' = 'circle',
  height: number = size,
): SwitchHotspot => ({
  label,
  command: `press:${name}`,
  x,
  y,
  width: size,
  height,
  shape,
  comment: name,
});

export const nintendoSwitchRemoteConfig = {
  remote_info: {
    name: 'Nintendo Switch',
    type: 'switch_procon' as const,
    image_url: '/procon_remote.png',
    image_size: { width: 791, height: 550 },
    top_strip_height: 64,
    text_style: {
      fontSize: '20px', // ui-ok: no-literal-font-size - remote overlay text scales with the screenshot (remoteScale)
      fontWeight: 'bold',
      color: 'white',
      textShadow: '1px 1px 3px rgba(0,0,0,0.9)',
    },
  },
  panel_layout: {
    collapsed: {
      width: '300px',
      height: '330px',
      position: {
        bottom: '20px',
        right: '20px',
      },
    },
    expanded: {
      width: '440px',
      height: '480px',
      position: {
        top: '100px',
        right: '20px',
      },
    },
    showScreenshotInCollapsed: false,
    showScreenshotInExpanded: true,
    header: {
      height: '40px',
      fontSize: '0.875rem', // ui-ok: no-literal-font-size - layout data, read by the remote/AV panel renderer
      fontWeight: 'bold',
      iconSize: 'small',
      padding: '8px',
      backgroundColor: '#1E1E1E',
      borderColor: '#333',
      textColor: '#ffffff',
    },
  },
  hotspots: {
    // Shoulders: ZL / ZR in the strip above the photo, L / R on the bumpers.
    zl: button('ZL', 'zl', 175, -32, 120, 'rectangle', 48),
    l: button('L', 'l', 175, 22, 120, 'rectangle', 34),
    zr: button('ZR', 'zr', 616, -32, 120, 'rectangle', 48),
    r: button('R', 'r', 616, 22, 120, 'rectangle', 34),
    // Centre buttons
    minus: button('−', 'minus', 297, 104, 34),
    plus: button('+', 'plus', 493, 104, 34),
    capture: button('', 'capture', 339, 165, 34, 'rectangle'),
    home: button('', 'home', 452, 165, 40),
    // Face buttons
    x: button('X', 'x', 604, 110, 54),
    y: button('Y', 'y', 543, 165, 54),
    a: button('A', 'a', 665, 165, 54),
    b: button('B', 'b', 604, 219, 54),
    // D-pad
    dpad_up: button('', 'up', 273, 237, 34, 'rectangle'),
    dpad_down: button('', 'down', 273, 309, 34, 'rectangle'),
    dpad_left: button('', 'left', 234, 273, 34, 'rectangle'),
    dpad_right: button('', 'right', 312, 273, 34, 'rectangle'),
    // Sticks: centre = click, ring = 4 tap directions
    ...stick('left', 177, 162, 'L3'),
    ...stick('right', 497, 269, 'R3'),
  } as Record<string, SwitchHotspot>,
};
