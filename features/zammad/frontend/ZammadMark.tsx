/**
 * A Zammad mark, as inline SVG that paints with `currentColor` - it follows the nav row and the page
 * like every other icon (no literal colours, docs/agent/platform/UI_STYLE.md). A rounded plate with the
 * Zammad "Z"; an approximation of the brand glyph, not the official artwork.
 */
export interface ZammadMarkProps {
  fontSize?: number;
  className?: string;
  color?: string;
}

export function ZammadMark({ fontSize = 20, className, color }: ZammadMarkProps) {
  return (
    <svg
      className={className}
      width={fontSize}
      height={fontSize}
      viewBox="0 0 24 24"
      role="img"
      aria-label="Zammad"
      focusable="false"
      style={color ? { color } : undefined}
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M5 2h14a3 3 0 0 1 3 3v14a3 3 0 0 1-3 3H5a3 3 0 0 1-3-3V5a3 3 0 0 1 3-3Zm1.6 4.6v2.2h7.4l-7.6 8.5v2.1h10.9v-2.2H9.4l7.6-8.5V6.6H6.6Z"
      />
    </svg>
  );
}

export default ZammadMark;
