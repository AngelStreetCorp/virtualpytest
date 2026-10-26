/**
 * Parser for docs/release_note/README.md and docs/bugs/README.md: a stack of `## ` lists
 * (Unreleased, then one per build), each with `### Features / Bug fixes / Security / Upgrade`.
 * Pure functions, no React, so the version mapping and the compare maths are unit-tested.
 */

export type SectionKind = 'features' | 'improvements' | 'fixes' | 'security' | 'internal' | 'upgrade' | 'list' | 'other';

/** The fixed list of areas a Feature or Improvement belongs to (docs/release_note/AUTHORING.md). */
export const AREAS = [
  { slug: 'device-control', name: 'Device control & streaming' },
  { slug: 'monitoring', name: 'Monitoring & alerts' },
  { slug: 'testing', name: 'Test automation' },
  { slug: 'ai', name: 'AI' },
  { slug: 'integrations', name: 'Integrations' },
  { slug: 'platform', name: 'Platform & admin' },
  { slug: 'entertainment', name: 'Games & entertainment' },
] as const;
export type AreaSlug = (typeof AREAS)[number]['slug'];

export interface Entry {
  bug?: string;
  commit?: string;
  task?: string;
  migration: boolean;
  /** The dated SQL file named by the "DB migration" marker, when there is one. */
  migrationFile?: string;
  /** Every migration file the entry names (a merged feature can carry several). */
  migrationFiles: string[];
  /** Area slug from the ` · area: <slug>` segment. */
  area?: string;
  summary: string;
  details: string;
  /** The "In plain words: …" sentence of the entry, when it has one. */
  plain?: string;
}

export interface Subsection {
  heading: string;
  body: string;
  kind: SectionKind;
  entries: Entry[];
}

export interface Build {
  title: string;
  slug: string;
  /** `Unreleased`, or `build 9369`. */
  name: string;
  /** The build number (the version tag's last segment); undefined for Unreleased. */
  number?: string;
  date?: string;
  unreleased: boolean;
  subsections: Subsection[];
}

const kindOf = (heading: string, body: string): SectionKind => {
  if (/bug fixes|fixes/i.test(heading)) return 'fixes';
  if (/security/i.test(heading)) return 'security';
  if (/^improvements/i.test(heading)) return 'improvements';
  if (/^internal/i.test(heading)) return 'internal';
  if (/features/i.test(heading)) return 'features';
  if (/^upgrade/i.test(heading)) return 'upgrade';
  if (!heading && /^\s*-\s/m.test(body)) return 'list';
  return 'other';
};

/** Pulls top-level `- ` list items out of a body, joining wrapped continuation lines. */
export const extractBullets = (body: string): string[] => {
  const bullets: string[] = [];
  let current: string[] | null = null;
  for (const raw of body.split('\n')) {
    const m = raw.match(/^- (.*)$/);
    if (m) {
      if (current) bullets.push(current.join(' ').trim());
      current = [m[1]];
    } else if (raw.trim() !== '') {
      if (current) current.push(raw.trim());
    } else if (current) {
      bullets.push(current.join(' ').trim());
      current = null;
    }
  }
  if (current) bullets.push(current.join(' ').trim());
  return bullets.filter(Boolean);
};

/** First sentence-ending period outside a `[...]`/`(...)` link or a `code` span. */
const splitAtFirstSentence = (text: string): { summary: string; details: string } => {
  let depth = 0;
  let inCode = false;
  for (let i = 0; i < text.length - 1; i++) {
    const ch = text[i];
    if (ch === '`') {
      inCode = !inCode;
      continue;
    }
    if (inCode) continue;
    if (ch === '[' || ch === '(') depth++;
    else if (ch === ']' || ch === ')') depth = Math.max(0, depth - 1);
    else if (depth === 0 && ch === '.' && text[i + 1] === ' ') {
      return { summary: text.slice(0, i + 1), details: text.slice(i + 1).trim() };
    }
  }
  return { summary: text, details: '' };
};

/** A bullet is `**Title** — body · [BUG-nnnn](…) · `sha` · TASK-nn · 🗄 DB migration `x.sql``. */
export const parseBullet = (text: string): Entry => {
  const titled = text.match(/^\*\*(.+?)\*\*\s*[—-]?\s*([\s\S]*)$/);
  const title = titled ? titled[1].trim() : '';
  const rest = titled ? titled[2] : text;

  let bug: string | undefined;
  let commit: string | undefined;
  let task: string | undefined;
  let area: string | undefined;
  const kept: string[] = [];
  for (const seg of rest.split(' · ')) {
    const t = seg.trim();
    const b = t.match(/^\[(BUG-\d+)\]\([^)]*\)$/);
    if (b) {
      bug = bug ?? b[1];
      continue;
    }
    if (/^`[0-9a-f]{7,40}`$/.test(t) || t === '`this commit`') {
      if (t !== '`this commit`') commit = commit ?? t.replace(/`/g, '');
      continue;
    }
    const a = t.match(/^area:\s*([\w-]+)$/);
    if (a) {
      area = a[1];
      continue;
    }
    const k = t.match(/^(TASK-\d+)$/);
    if (k) {
      task = task ?? k[1];
      continue;
    }
    kept.push(seg);
  }
  const body = kept.join(' · ').trim();
  const migration = /DB migration/.test(body);
  const migrationFiles = migration ? [...body.matchAll(/`([^`]*\.sql)`/g)].map((m) => m[1]) : [];
  const migrationFile = body.match(/DB migration\s+`([^`]+)`/)?.[1] ?? migrationFiles[0];
  const plain = body.match(/In plain words:\s*([\s\S]*?)(?=\s*(?:·|$))/)?.[1]?.trim();
  const base = { bug, commit, task, migration, migrationFile, migrationFiles, plain, area };

  if (title) return { ...base, summary: title, details: body };
  return { ...base, ...splitAtFirstSentence(body) };
};

/** `build 9369 — 2026-09-26` → slug `build-9369`: short, stable, survives a corrected date. */
const listSlug = (title: string): string =>
  title.split('—')[0].trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');

/** Splits the markdown into one Build per `## ` list; the intro before the first one is dropped. */
export const parseReleaseNotes = (md: string): Build[] => {
  type Raw = { title: string; subs: { heading: string; body: string }[] };
  const raws: Raw[] = [];
  let cur: Raw | null = null;
  let sub: { heading: string; body: string } | null = null;
  const closeSub = () => {
    if (cur && sub) cur.subs.push(sub);
    sub = null;
  };
  for (const line of md.split('\n')) {
    const h2 = line.match(/^##\s+(.*)$/);
    const h3 = line.match(/^###\s+(.*)$/);
    if (h2) {
      closeSub();
      cur = { title: h2[1].trim(), subs: [] };
      raws.push(cur);
      continue;
    }
    if (h3) {
      closeSub();
      if (cur) sub = { heading: h3[1].trim(), body: '' };
      continue;
    }
    if (line.trim() === '---' || !cur || (!sub && !line.trim())) continue;
    if (!sub) sub = { heading: '', body: '' };
    sub.body += line + '\n';
  }
  closeSub();

  const taken = new Set<string>();
  return raws.map((r, idx) => {
    let slug = listSlug(r.title);
    while (taken.has(slug)) slug = `${slug}-${idx}`;
    taken.add(slug);
    const name = r.title.split('—')[0].trim();
    const num = name.match(/^build\s+(\S+)/i)?.[1];
    return {
      title: r.title,
      slug,
      name,
      number: num,
      date: r.title.split('—')[1]?.trim(),
      unreleased: /^unreleased$/i.test(name),
      subsections: r.subs.map((s) => {
        const kind = kindOf(s.heading, s.body);
        const listy = ['features', 'improvements', 'fixes', 'security', 'internal', 'list'].includes(kind);
        return { ...s, kind, entries: listy ? extractBullets(s.body).map(parseBullet) : [] };
      }),
    };
  });
};

export const entriesOf = (b: Build, kind: SectionKind): Entry[] =>
  b.subsections.filter((s) => s.kind === kind).flatMap((s) => s.entries);

export interface Counts {
  features: number;
  improvements: number;
  fixes: number;
  security: number;
  migrations: number;
}

const isRollback = (f: string) => /rollback/i.test(f);

/** Distinct migration files an entry names, rollbacks left out. */
const migrationsOf = (e: Entry): string[] => (e.migrationFiles ?? []).filter((f) => !isRollback(f));

export const countsOf = (b: Build): Counts => {
  const all = b.subsections.flatMap((s) => s.entries);
  const files = new Set<string>();
  let anon = 0;
  for (const e of all) {
    if (!e.migration) continue;
    const fs = migrationsOf(e);
    if (fs.length) fs.forEach((f) => files.add(f));
    else anon++;
  }
  return {
    features: entriesOf(b, 'features').length,
    improvements: entriesOf(b, 'improvements').length,
    fixes: entriesOf(b, 'fixes').length + entriesOf(b, 'list').length,
    security: entriesOf(b, 'security').length,
    migrations: files.size + anon,
  };
};

/** Entries grouped by area in the fixed order; entries with no known area go last under `other`. */
export const groupByArea = (entries: Entry[]): { slug: string; name: string; entries: Entry[] }[] => {
  const groups = AREAS.map((a) => ({ slug: a.slug as string, name: a.name as string, entries: [] as Entry[] }));
  const other: Entry[] = [];
  for (const e of entries) {
    const g = groups.find((x) => x.slug === e.area);
    (g ? g.entries : other).push(e);
  }
  const out = groups.filter((g) => g.entries.length > 0);
  if (other.length) out.push({ slug: 'other', name: 'Other', entries: other });
  return out;
};

/** The build number of a deployed version tag: its last `-` segment (`main-2026.10.14-87931` → `87931`). */
export const buildNumberOfVersion = (version: string): string | undefined => {
  const last = version.trim().split('-').pop();
  return last && /^\d+$/.test(last) ? last : undefined;
};

/**
 * Which build a deployed version belongs to: the section numbered like its tag, else the newest
 * section numbered at or below it (`builds` is newest first). Undefined when nothing fits.
 */
export const resolveVersionToBuild = (version: string | null | undefined, builds: Build[]): Build | undefined => {
  if (!version) return undefined;
  const n = buildNumberOfVersion(version);
  if (!n) return undefined;
  const exact = builds.find((b) => b.number === n);
  if (exact) return exact;
  const target = Number(n);
  return builds.find((b) => b.number !== undefined && /^\d+$/.test(b.number) && Number(b.number) <= target);
};

export interface FeatureRow {
  entry: Entry;
  /** Name of the build that introduced it. */
  addedIn: string;
  inFrom: boolean;
  inTo: boolean;
}

/**
 * Feature table between two builds (`builds` newest first). A feature is "in" a build when it was
 * added in that build or an older one; a row differs when exactly one of the two has it, so
 * picking an older To flips the ticks (what a rollback would lose).
 */
export const featureRows = (builds: Build[], fromSlug: string, toSlug: string): FeatureRow[] => {
  const fi = builds.findIndex((b) => b.slug === fromSlug);
  const ti = builds.findIndex((b) => b.slug === toSlug);
  if (fi < 0 || ti < 0) return [];
  const rows: FeatureRow[] = [];
  builds.forEach((b, i) => {
    for (const entry of entriesOf(b, 'features')) {
      rows.push({ entry, addedIn: b.name, inFrom: i >= fi, inTo: i >= ti });
    }
  });
  return rows;
};

/** The builds a move between two picks passes through, oldest first (the From build itself excluded). */
export const buildsBetween = (builds: Build[], fromSlug: string, toSlug: string): Build[] => {
  const fi = builds.findIndex((b) => b.slug === fromSlug);
  const ti = builds.findIndex((b) => b.slug === toSlug);
  if (fi < 0 || ti < 0 || fi === ti) return [];
  const [newer, older] = fi < ti ? [fi, ti] : [ti, fi];
  // Going forward: builds newer than From up to To. Going back: the same span, listed as lost.
  return builds.slice(newer, older).reverse();
};

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

/**
 * "What you gain" is only worth a card when it says more than the table: true when at least one
 * plain-words sentence differs from its row's title.
 */
export const gainText = (e: Entry): string =>
  e.plain ||
  e.details
    .split(' · ')
    .map((seg) => seg.trim())
    .filter((seg) => seg && !/^\[[^\]]+\]\([^)]*\)$/.test(seg) && !/DB migration/.test(seg))
    .join(' · ')
    .replace(/[*`]/g, '')
    .trim();

export const plainAddsInfo = (entries: Entry[]): boolean =>
  entries.some((e) => {
    const g = gainText(e);
    return g !== '' && norm(g) !== norm(e.summary);
  });

/** Case-insensitive match on title, BUG-, TASK- and migration file. */
export const entryMatches = (e: Entry, q: string): boolean => {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  return [e.summary, e.bug, e.task, e.commit, ...(e.migrationFiles ?? [])].some((v) => v?.toLowerCase().includes(needle));
};

export interface MergedUpgrade {
  migrations: string[];
  envKeys: string[];
  services: string[];
  /** Other manual steps (proxy, Grafana, sudoers, …): label + first words of the line. */
  other: string[];
}

/**
 * The upgrade checklist of several builds as one list, in build order (oldest first): migration
 * files (from the Upgrade blocks and the entries' DB-migration markers), new `.env` keys, and
 * the services to restart by hand. Rollback files are not part of the way forward.
 */
export const mergeUpgrade = (builds: Build[]): MergedUpgrade => {
  const migrations = new Set<string>();
  const envKeys = new Set<string>();
  const services = new Set<string>();
  const other: string[] = [];
  const ROUTINE = /^(database|settings|services|dependencies|deploy command|compared with|audit read|rollback)/i;
  const NOOP = /\b(no (new|migration|package|service|nginx|change)|nothing|none|unchanged)\b/i;
  const base = (p: string) => p.split('/').pop() ?? p;
  for (const b of builds) {
    for (const s of b.subsections) {
      for (const e of s.entries) for (const f of migrationsOf(e)) migrations.add(base(f));
      if (s.kind !== 'upgrade') continue;
      for (const line of s.body.split('\n')) {
        if (/^\*\*Database\*\*/.test(line) || /^- `setup\/db\/migrations\//.test(line) || /^- `[^`]*\.sql`/.test(line)) {
          for (const m of line.matchAll(/`([^`]*\.sql)`/g)) if (!/rollback/i.test(m[1])) migrations.add(base(m[1]));
        }
        if (/^\*\*Settings\*\*/.test(line) || /^- `[A-Z][A-Z0-9_]{3,}/.test(line)) {
          if (/no new key/i.test(line)) continue;
          for (const m of line.matchAll(/`([A-Z][A-Z0-9_]{3,})(?:=[^`]*)?`/g)) envKeys.add(m[1]);
        }
        const lab = line.match(/^\*\*([^*]+?):?\*\*:?\s*[—:-]?\s*(.*)$/);
        if (lab && /^manual$/i.test(lab[1].trim()) && lab[2].trim()) {
          other.push(lab[2].replace(/[*`]/g, '').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').trim());
        } else if (lab && !ROUTINE.test(lab[1].trim()) && !NOOP.test(lab[2].slice(0, 80)) && lab[2].trim() !== '') {
          const text = lab[2].replace(/[*`]/g, '').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').trim();
          other.push(`${lab[1].trim()}${text ? ': ' + (text.length > 110 ? text.slice(0, 107) + '…' : text) : ''}`);
        }
        if (/^\*\*Services\*\*/.test(line)) {
          for (const m of line.matchAll(/`(vpt-[\w-]+)`/g)) services.add(m[1]);
        }
      }
    }
  }
  return { migrations: [...migrations], envKeys: [...envKeys], services: [...services], other: [...new Set(other)] };
};
