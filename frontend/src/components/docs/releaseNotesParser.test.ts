import { describe, expect, it } from 'vitest';
import {
  buildNumberOfVersion,
  buildsBetween,
  countsOf,
  entryMatches,
  featureRows,
  parseReleaseNotes,
  plainAddsInfo,
  resolveVersionToBuild,
} from './releaseNotesParser';

const MD = `# Release Notes

## Unreleased

### Features
- **Alpha** — does alpha. In plain words: you can alpha · TASK-5 · \u{1F5C4} DB migration \`setup/db/migrations/1.sql\`
- **Beta** — does beta. In plain words: Beta · \`abcdef1\`

### Bug fixes
- **Gamma broke** — fixed · [BUG-0001](x.md)

## build 9369 — 2026-09-26

### Features
- **Old thing** — it is old

### Security
- **Lock** — locked

## build 9300 — 2026-09-20

### Features
- **Older thing** — older
`;

describe('releaseNotesParser', () => {
  const builds = parseReleaseNotes(MD);

  it('splits builds and drops the intro', () => {
    expect(builds.map((b) => b.name)).toEqual(['Unreleased', 'build 9369', 'build 9300']);
    expect(builds[1].number).toBe('9369');
    expect(builds[1].date).toBe('2026-09-26');
    expect(builds[0].unreleased).toBe(true);
  });

  it('counts entries and migrations', () => {
    expect(countsOf(builds[0])).toEqual({ features: 2, improvements: 0, fixes: 1, security: 0, migrations: 1 });
    expect(countsOf(builds[1]).security).toBe(1);
  });

  it('parses bullet metadata', () => {
    const [alpha] = builds[0].subsections[0].entries;
    expect(alpha.task).toBe('TASK-5');
    expect(alpha.migrationFile).toBe('setup/db/migrations/1.sql');
    expect(alpha.plain).toBe('you can alpha');
    expect(builds[0].subsections[1].entries[0].bug).toBe('BUG-0001');
  });

  it('maps a version tag to its build (D1)', () => {
    expect(buildNumberOfVersion('main-2026.10.14-87931')).toBe('87931');
    expect(resolveVersionToBuild('main-2026.09.26-9369', builds)?.name).toBe('build 9369');
    // no section of its own: newest section at or below its number
    expect(resolveVersionToBuild('main-2026.09.22-9330', builds)?.name).toBe('build 9300');
    expect(resolveVersionToBuild('main-2026.01.01-12', builds)).toBeUndefined();
    expect(resolveVersionToBuild(null, builds)).toBeUndefined();
  });

  it('ticks flip with direction', () => {
    const fwd = featureRows(builds, 'build-9300', 'unreleased').filter((r) => r.inFrom !== r.inTo);
    expect(fwd.map((r) => r.entry.summary)).toEqual(['Alpha', 'Beta', 'Old thing']);
    expect(fwd.every((r) => !r.inFrom && r.inTo)).toBe(true);
    const back = featureRows(builds, 'unreleased', 'build-9300').filter((r) => r.inFrom !== r.inTo);
    expect(back.every((r) => r.inFrom && !r.inTo)).toBe(true);
  });

  it('lists builds passed through, oldest first', () => {
    expect(buildsBetween(builds, 'build-9300', 'unreleased').map((b) => b.name)).toEqual(['build 9369', 'Unreleased']);
    expect(buildsBetween(builds, 'build-9300', 'build-9300')).toEqual([]);
  });

  it('shows What you gain only when it adds information', () => {
    expect(plainAddsInfo(builds[0].subsections[0].entries)).toBe(true);
    expect(plainAddsInfo([builds[0].subsections[0].entries[1]])).toBe(false);
  });

  it('filters by title, bug, task and migration', () => {
    const [alpha] = builds[0].subsections[0].entries;
    expect(entryMatches(alpha, 'task-5')).toBe(true);
    expect(entryMatches(alpha, 'migrations/1')).toBe(true);
    expect(entryMatches(alpha, 'zzz')).toBe(false);
  });
});

describe('mergeUpgrade', () => {
  it('collects migrations, env keys and services in order', async () => {
    const { mergeUpgrade } = await import('./releaseNotesParser');
    const bs = parseReleaseNotes(`## build 2

### Upgrade

**Database** — apply once:
- \`setup/db/migrations/20261009a_x.sql\`
Rollback: \`setup/db/migrations/20261009a_x_rollback.sql\`.

**Settings** — new: \`FOO_KEY\`, \`BAR_KEY=1\`
**Services** — restart \`vpt-server\`.

## build 1

### Upgrade

**Settings** — no new key.
**Services** — restart \`vpt-server\` and \`vpt-kpi\`.
`);
    expect(mergeUpgrade([...bs].reverse())).toEqual({
      migrations: ['20261009a_x.sql'],
      envKeys: ['FOO_KEY', 'BAR_KEY'],
      services: ['vpt-server', 'vpt-kpi'],
      other: [],
    });
  });
});

describe('kinds and areas (TASK-108)', () => {
  const md = `## Unreleased

### Features
- **GitLab** — Connect your own GitLab. · [Docs](../x.md) · TASK-9 · \u{1F5C4} DB migration \`a.sql\`, \`b.sql\` · area: integrations

### Improvements
- **Empty state** — nicer · area: monitoring
- **Glow** — pulse · area: ai

### Internal
- **numpy 2** — libs

### Bug fixes
- **Fixed** — q · [BUG-0001](x.md)
`;
  const [b] = parseReleaseNotes(md);

  it('reads kinds, area and several migration files', async () => {
    const { entriesOf, groupByArea, countsOf: counts } = await import('./releaseNotesParser');
    const f = entriesOf(b, 'features')[0];
    expect(f.area).toBe('integrations');
    expect(f.migrationFiles).toEqual(['a.sql', 'b.sql']);
    expect(entriesOf(b, 'internal')).toHaveLength(1);
    expect(counts(b)).toEqual({ features: 1, improvements: 2, fixes: 1, security: 0, migrations: 2 });
    expect(groupByArea(entriesOf(b, 'improvements')).map((g) => g.slug)).toEqual(['monitoring', 'ai']);
  });

  it('what you gain uses the feature sentence when there is no plain-words line', async () => {
    const { gainText, entriesOf } = await import('./releaseNotesParser');
    expect(gainText(entriesOf(b, 'features')[0])).toBe('Connect your own GitLab.');
  });
});

describe('manual upgrade steps', () => {
  it('reads **Manual:** lines and skips bare section labels', async () => {
    const { mergeUpgrade } = await import('./releaseNotesParser');
    const bs = parseReleaseNotes(`## build 3

### Upgrade

**platform update prerequisites (TASK-101)**

**Manual:** hand-deploy \`dash.json\` to Grafana.
**Settings** — no new key.
`);
    expect(mergeUpgrade(bs).other).toEqual(['hand-deploy dash.json to Grafana.']);
  });
});
