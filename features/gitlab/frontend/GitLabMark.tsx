/**
 * The GitLab tanuki, as the app's nav/page mark.
 *
 * The logo itself is `gitlab-tanuki.svg` next to this file — the official GitLab mark (Dashboard
 * Icons / homarr-labs, the library UI_STYLE.md §11 names; see that file for source + trademark).
 * This component is the sizing/accessibility wrapper, and it carries no geometry of its own, so the
 * two files cannot drift.
 *
 * It was an inline `currentColor` SVG, and that was wrong at navbar size. Measured at the real 20px
 * against the real rows: a single-colour tanuki loses every interior boundary (the muzzle is ~2px
 * there) and reads as a featureless blob with two horns — "GitLab" only because the label is beside
 * it. Splitting the three regions by OPACITY instead of colour did not rescue it; the separations are
 * too thin at 20px. Only the three brand fills read as GitLab, so this is an `<img>` of the asset,
 * which is also exactly how every other vendor mark in the navbar renders (Slack, Jira, Grafana,
 * Langfuse, Postman, TestRail all go through `vendorMark`).
 *
 * The brand hexes stay in the `.svg` rather than here: feature UI must not hold literal colours
 * (docs/agent/platform/UI_STYLE.md §10, guarded by tests/frontend/GitLabSelectedServer.test.ts), and
 * §11 puts every other vendor's colours in an asset file too. The one thing lost is inheritance —
 * the mark no longer tints with the row on hover — which is the trade for being recognisable at all.
 *
 * Without a real mark the navbar entry carried a generic MUI `Code` glyph, which reads as "source
 * code", not "GitLab".
 */
import tanuki from './gitlab-tanuki.svg';

export interface GitLabMarkProps {
  /** Rendered size in px (a square box; the tanuki is slightly taller than wide inside it). The navbar passes 20, the page hero 44. */
  fontSize?: number;
  className?: string;
}

/**
 * Decorative on purpose: both call sites render the word "GitLab" right next to it (the nav row's
 * label, the page's "Connect to GitLab" heading), so naming the image too would just read the name
 * twice. If a future call site has no adjacent label, pass `alt` there instead of un-decorating
 * this one.
 */
export function GitLabMark({ fontSize = 20, className }: GitLabMarkProps) {
  return (
    <img
      src={tanuki}
      alt=""
      aria-hidden="true"
      width={fontSize}
      height={fontSize}
      className={className}
      // flex: none so a long row cannot squash the mark; the nav row is a flex box with gap={1}.
      style={{ display: 'block', flex: 'none' }}
    />
  );
}

export default GitLabMark;