import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * A GitLab instance is configured PER SERVER: each VirtualPyTest server keeps its own
 * `gitlab_instances.json`, and it is normal for only some of them to have one. So the page has to
 * follow the server picker, not the main server.
 *
 * It did not, and the result was a page that contradicted the app around it: the picker said
 * `vpt-pi4` while the page showed the main server's GitLab — its projects, its files, its README.
 * The navbar shortcut already used the per-server builder and correctly hid itself on a server
 * with no instance, so the shortcut and the page it links to disagreed on the same screen.
 *
 * Source-level rather than behavioural, for two reasons. `buildPrimaryServerUrl` and
 * `buildServerUrl` both return a plain string from module-level server state, so a unit test would
 * have to fake the whole URL layer to tell them apart; and the GitLabPage listener is a side effect
 * of mounting a component that is not in the core test set. Both invariants are one token each and
 * cost nothing to assert directly.
 */
/**
 * Strip comments before asserting on an identifier.
 *
 * The point is which builder the CODE calls. A docstring is free to name the wrong one while
 * explaining why it was wrong — this file's own header does exactly that, and it must not make the
 * guard fail on the fix's own explanation.
 */
const stripComments = (src: string) =>
  src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');

const API = stripComments(
  readFileSync(resolve(__dirname, '../../features/gitlab/frontend/gitlabApi.ts'), 'utf-8'),
);
const PAGE = stripComments(
  readFileSync(resolve(__dirname, '../../features/gitlab/frontend/GitLabPage.tsx'), 'utf-8'),
);

describe('GitLab page follows the selected server', () => {
  it('builds its calls against the selected server, not the primary one', () => {
    // buildPrimaryServerUrl is documented as ignoring the server picker — right for CI reports
    // and runners, wrong for a per-server instance store.
    expect(API).not.toContain('buildPrimaryServerUrl');
    expect(API).toContain('buildServerUrl');
  });

  it('re-reads the instance when the picker moves to another server', () => {
    // Without this the page keeps the previous server's data under the new server's name. The
    // navbar shortcut has listened for this event since it was added. Check the SUBSCRIBE, not
    // just the string: an unsubscribed-only listener passes a naive contains-check, which is
    // exactly what the first version of this test did.
    expect(PAGE).toContain("addEventListener('vpt:server-changed'");
    expect(PAGE).toContain("removeEventListener('vpt:server-changed'");
  });

  it('clears what the previous server showed before loading the new one', () => {
    // Re-reading is not enough: a server with no GitLab must land on the empty state rather than
    // on the previous server's projects with an empty-state header.
    for (const setter of [
      'setProjects([])',
      'setEntries([])',
      'setReadme(null)',
      'setInstanceId(\'\')',
      'setError(null)',
    ]) {
      expect(PAGE).toContain(setter);
    }
  });
});
describe('GitLab is identified by its mark, not a generic glyph', () => {
  // Stripped, not raw: the component's doc comment explains WHY it no longer paints with
  // currentColor, and that explanation must not read as the code doing so.
  const ROUTES = stripComments(
    readFileSync(resolve(__dirname, '../../features/gitlab/frontend/routes.tsx'), 'utf-8'),
  );
  const MARK = stripComments(
    readFileSync(resolve(__dirname, '../../features/gitlab/frontend/GitLabMark.tsx'), 'utf-8'),
  );
  const TANUKI = readFileSync(
    resolve(__dirname, '../../features/gitlab/frontend/gitlab-tanuki.svg'),
    'utf-8',
  );

  it('uses the real GitLab mark in the nav row', () => {
    // It shipped with MUI's generic <Code />, which reads as "source code", not "GitLab".
    expect(ROUTES).toContain('GitLabMark');
    expect(ROUTES).not.toContain("Code as GitLabIcon");
  });

  it('keeps the brand colours in the asset, never in feature UI', () => {
    // UI_STYLE.md §10: no literal colours in feature UI. The logo's three fills are the one place a
    // literal colour is legitimate, and §11 puts them in an asset file — so the component stays free
    // of them and the asset carries them.
    expect(MARK).not.toMatch(/#[0-9a-fA-F]{3,6}\b/);
    expect(MARK).toContain('gitlab-tanuki.svg');
    expect(TANUKI).toMatch(/#e24329/i);
    expect(TANUKI).toMatch(/#fc6d26/i);
    expect(TANUKI).toMatch(/#fca326/i);
  });

  it('ships the logo in colour, not a monochrome silhouette', () => {
    // Kept because the monochrome version was measured and rejected. Rendered at the real 20px
    // navbar size, a single-currentColor tanuki loses every interior boundary (the muzzle is ~2px
    // there) and reads as a featureless blob with two horns — "GitLab" only because the label is
    // beside it. Separating the three regions by OPACITY instead of colour did not rescue it. So the
    // component renders the three-fill asset rather than drawing its own single-colour path; a flat
    // silhouette would look fine in review and be unreadable in the row.
    expect(MARK).not.toContain('<path');
    expect(MARK).not.toContain('currentColor');
  });
});
