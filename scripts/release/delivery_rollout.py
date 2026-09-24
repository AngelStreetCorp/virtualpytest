#!/usr/bin/env python3
"""Roll-out section of a customer delivery note: only what THIS customer must do.

A delivery is always an update — the customer is on release N and moves to N+1. There is no
first-install path here on purpose; installing is a different document.

Everything is a delta between two platform refs, and every section is dropped when it is empty.
An operator who reads "no nginx change" still had to read a paragraph to learn nothing; a
section that is absent costs nothing. What is left is the list of things that break a rollout
when skipped: a migration, an .env key, a proxy config, a service nobody restarts.

Three filters make the difference between this and the raw upgrade block:
  - features in DISABLED_FEATURES: their migrations, units and dashboards are NOT this
    customer's, and running their migrations is wrong, not merely useless;
  - the platform's own lab/reference vhosts (proxmox*, local-*, docker.conf, example/*), which
    no customer deploys;
  - overlay overrides: a dashboard the overlay ships replaces the platform's at deploy, so a
    platform change to it never reaches this customer.

Usage:
  delivery_rollout.py --from <ref> --to <ref> [--disabled a,b] [--overlay <dir>] [--prev-tag <t>]
                      [--relnote <file>]      # release-note sections, for the 🗄 markers
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import upgrade_notes as un  # noqa: E402

# Lab and reference vhosts: our own proxmox proxy and the docker/local install samples.
NGINX_REF = re.compile(r'(^|/)(proxmox[^/]*|local-http|local|docker)\.conf$|/example/')
# .env files a fleet customer has. setup/docker/.env.example belongs to the standalone docker
# install; a customer running server + hosts never opens it, so its keys are noise here.
CUSTOMER_ENV = ('backend_server/src/.env.example', 'backend_host/src/.env.example',
                'frontend/.env.example')
VOCAB_FILE = os.path.join(HERE, 'feature_db_vocabulary.txt')
ENV_LABEL = {'backend_server/src/.env.example': 'the server VM',
             'backend_host/src/.env.example': 'every host',
             'frontend/.env.example': 'the frontend VM'}


def sh(*args: str, cwd: str | None = None) -> str:
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ''


def owning_feature(text: str, disabled: list[str]) -> str | None:
    """Which disabled feature a path/bullet belongs to — path evidence only.

    A feature name in prose ("(AVQ)") is a guess; telling someone to skip a migration they need
    is the dangerous direction, so only a features/<name>/ path decides.
    """
    for d in disabled:
        if f'features/{d}/' in text:
            return d
    return None


def load_vocab() -> dict:
    """{feature: [identifier fragments]} — see feature_db_vocabulary.txt for why."""
    vocab: dict = {}
    if not os.path.exists(VOCAB_FILE):
        return vocab
    for line in open(VOCAB_FILE, encoding='utf-8'):
        line = line.split('#')[0].strip()
        if not line or ':' not in line:
            continue
        feat, frags = line.split(':', 1)
        vocab[feat.strip()] = [f.strip() for f in frags.split(',') if f.strip()]
    return vocab


MODIFIES = [
    r'(?:create|alter|drop)\s+(?:table|materialized\s+view|view)\s+(?:if\s+(?:not\s+)?exists\s+)?([\w.]+)',
    r'(?:create|drop)\s+(?:or\s+replace\s+)?function\s+(?:if\s+exists\s+)?([\w.]+)',
    r'(?:create|drop)\s+(?:unique\s+)?(?:policy|index|trigger)\b[^;]{0,400}?\son\s+([\w.]+)',
    r'grant\s[^;]{0,400}?\son\s+(?:table\s+)?([\w.]+)',
    r'insert\s+into\s+([\w.]+)',
    r'update\s+([\w.]+)\s+set\b',
    r'delete\s+from\s+([\w.]+)',
]
REFERENCES = [r'references\s+([\w.]+)']
NOISE = {'if', 'not', 'exists', 'only', 'all', 'conflict', 'select', 'set', 'where', 'public',
         'schema', 'values', 'columns', 'tables', 'constraints', 'information_schema'}


def _objects(low: str, patterns: list) -> set:
    found = set()
    for pat in patterns:
        for m in re.finditer(pat, low, re.S):
            t = m.group(1).split('.')[-1].strip()
            if t and not t.startswith('pg_') and t not in NOISE:
                found.add(t)
    return found


def classify(body: str, disabled: list[str], vocab: dict) -> tuple[str, list[str]]:
    """CORE / SKIP / MIXED for one migration, decided per object it touches.

    The distinction that matters is between a table the migration MODIFIES and one it merely
    REFERENCES, because they fail differently. A migration that only modifies a disabled
    feature's tables is not this customer's at all. One that modifies a core table but points a
    foreign key at a feature table still fails on a database without it — that is the case a
    filename can never reveal (20260907d alters `deployments` and references `virtual_scripts`).
    """
    low = re.sub(r'--[^\n]*', ' ', body.lower()).replace('"', '')
    owner = lambda t: next((f for f, frags in vocab.items() if any(fr in t for fr in frags)), None)
    modified = _objects(low, MODIFIES)
    referenced = _objects(low, REFERENCES) - modified
    mod_disabled = {t for t in modified if owner(t) in disabled}
    mod_core = modified - mod_disabled
    ref_disabled = {t for t in referenced if owner(t) in disabled}
    hits = sorted({owner(t) for t in (mod_disabled | ref_disabled)} - {None})
    if not hits:
        return 'CORE', []
    if mod_core:
        return 'MIXED', hits
    return 'SKIP', hits


def relnote_markers(path: str | None) -> dict:
    """{migration filename: (change title, whole bullet)} from the 🗄 markers shipped."""
    if not path or not os.path.exists(path):
        return {}
    text = open(path, encoding='utf-8').read()
    out, cur = {}, None
    for line in text.splitlines():
        if re.match(r'^\s*-\s+\*\*', line):
            cur = line
        elif cur is not None and line.strip() and not line.startswith('#'):
            cur += ' ' + line.strip()
        else:
            cur = None if line.startswith('#') else cur
        if cur and 'DB migration' in cur:
            m = re.search(r'\*\*(.+?)\*\*', cur)
            title = m.group(1) if m else ''
            for seg in cur.split('DB migration')[1:]:
                f = re.search(r'`([^`]+)`', seg)
                if f:
                    # Keep the whole bullet: a core-path migration is attributed to a feature
                    # only by the text that names it — features/virtual-scripts/ appears in the
                    # bullet, never in setup/db/migrations/<file>.sql.
                    out.setdefault(os.path.basename(f.group(1).rstrip('/')), (title, cur))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='frm', required=True)
    ap.add_argument('--to', dest='to', required=True)
    ap.add_argument('--disabled', default='')
    ap.add_argument('--overlay', default='')
    ap.add_argument('--prev-tag', default='')
    ap.add_argument('--relnote', default='')
    args = ap.parse_args()
    disabled = [d.strip() for d in args.disabled.replace(',', ' ').split() if d.strip()]
    rng = f'{args.frm}..{args.to}'

    changed = un.git('diff', '--name-only', rng).split()
    added = un.git('diff', '--name-only', '--diff-filter=A', rng).split()
    a = un.analyse(changed, added)
    markers = relnote_markers(args.relnote or None)

    ov_changed = []
    if args.overlay and args.prev_tag:
        ov_changed = [p for p in sh('git', '-C', args.overlay, 'diff', '--name-only',
                                    f'{args.prev_tag}..HEAD', cwd=None).splitlines() if p.strip()]
    overlay_files = set()
    if args.overlay:
        overlay_files = {os.path.basename(p) for p in
                         sh('git', '-C', args.overlay, 'ls-files').splitlines() if p.strip()}

    vocab = load_vocab()
    # ---- database -------------------------------------------------------------------------
    migrations, skipped, mixed = [], [], []
    for p, owner in a['migrations']:
        title, bullet = markers.get(os.path.basename(p), ('', ''))
        feat = owner if owner != 'core' else owning_feature(p + ' ' + bullet, disabled)
        if feat in disabled:
            skipped.append((p, feat))
            continue
        # The decisive test: what the SQL actually touches.
        verdict, hits = classify(sh('git', 'show', f'{args.to}^{{commit}}:{p}') or '', disabled, vocab)
        if verdict == 'SKIP':
            skipped.append((p, ', '.join(hits)))
        elif verdict == 'MIXED':
            mixed.append((p, title, ', '.join(hits)))
        else:
            # A description taken from the release-note bullet can describe a feature this
            # customer does not have, on a migration they DO need: 20260907d alters core
            # `deployments` (the `environment` column every deployment uses) but its bullet is
            # about virtual scripts. Keep the file, drop the misleading sentence.
            if title and owning_feature(bullet, disabled):
                title = ''
            migrations.append((p, title))
    # A schema/ file added with no migration of the same name would never reach an existing
    # database — the customer is updating, and apply_schema.sh is for a new one only.
    mig_stems = ' '.join(p for p, _ in a['migrations'])
    orphan_schema = []
    for p in added:
        if not (p.startswith('setup/db/schema/') and p.endswith('.sql')):
            continue
        if re.sub(r'^\d+_', '', os.path.basename(p))[:-4] in mig_stems:
            continue
        if classify(sh('git', 'show', f'{args.to}^{{commit}}:{p}') or '', disabled, vocab)[0] == 'SKIP':
            continue
        orphan_schema.append(p)

    # ---- settings -------------------------------------------------------------------------
    env_rows = []
    for f, keys in un.env_keys_added(args.frm, args.to):
        if f not in CUSTOMER_ENV:
            continue
        for k in keys:
            why = sh('git', 'log', '-1', '--format=%s', f'-S{k}=', rng, '--', f)
            env_rows.append((f, k, why))

    # ---- proxy ----------------------------------------------------------------------------
    # With the reason: "1 nginx config changed" makes someone go and diff it. The commit subject
    # says whether it is a fix they need or a change to a block their vhost may not even have.
    nginx = [(p, sh('git', 'log', '-1', '--format=%s', rng, '--', p))
             for p in a['nginx'] if not NGINX_REF.search(p)]
    nginx += [(p, sh('git', '-C', args.overlay, 'log', '-1', '--format=%s',
                     f'{args.prev_tag}..HEAD', '--', p) if args.overlay else '')
              for p in ov_changed if p.endswith('.conf') and '/nginx/' in p]

    # ---- services -------------------------------------------------------------------------
    byhand, optin, templates = [], [], []
    for u in a['units']:
        if u.name in un.DEPLOY_RESTARTS:
            continue                       # the deploy script does it; not the operator's problem
        if getattr(u, 'feature', None) in disabled:
            continue
        (optin if u.name in un.OPT_IN_RESTARTS else byhand).append(u)
    for p in a['unit_templates']:
        if owning_feature(p, disabled):
            continue
        templates.append(p)

    # ---- grafana --------------------------------------------------------------------------
    # An overlay dashboard replaces the platform's at deploy, so a platform change to a file the
    # overlay also ships never reaches this customer.
    graf = [(p, 'platform') for p in a['grafana']
            if not owning_feature(p, disabled) and os.path.basename(p) not in overlay_files]
    graf += [(p, 'yours') for p in ov_changed if p.endswith('.json') and '/grafana/' in p]

    # ---- render ---------------------------------------------------------------------------
    L: list[str] = ['', '---', '', '## Roll it out', '']
    steps: list = []
    if migrations:
        L2 = ['STEP Database', '',
              'Apply once per database, **before** the services restart. No deploy script does this.', '']
        for p, title in migrations:
            L2.append(f'- `{p}`' + (f' — {title}' if title else ''))
        L2 += ['']
        # Only the migrations to apply. What this customer must NOT run is not their work:
        # the feature migrations, the rollback files and the mixed ones are decided here and
        # simply left out, rather than listed as things to read past.
    steps.append(('db', L2, len(migrations))) if migrations else None
    if env_rows:
        L2 = ['STEP Settings', '',
              'Keys that appeared in the `.env` examples. A deploy never writes a VM `.env`, so '
              'anything genuinely new has to be added by hand on the machines named.', '',
              '| Keys | Where | Why |', '|---|---|---|']
        grouped: dict = {}
        for f, k, why in env_rows:
            grouped.setdefault((ENV_LABEL.get(f, f), why), []).append(k)
        for (where, why), keys in grouped.items():
            L2.append(f'| {", ".join(f"`{k}`" for k in keys)} | {where} | {why or "—"} |')
        L2 += ['',
              '> A key can appear here because the **example** was completed, not because the '
              'setting is new — check the machine before adding one: a value that is already set '
              'is already correct.', '']

    steps.append(('env', L2, len(env_rows))) if env_rows else None
    if nginx:
        L2 = ['STEP Nginx', '',
              'Hand-deployed; the deploy script never touches the proxy. Check your own vhost '
              'carries the block each change touches — it may not.', '']
        L2 += [f'- `{p}`' + (f' — {why}' if why else '') for p, why in nginx]
        L2 += ['']

    steps.append(('nginx', L2, len(nginx))) if nginx else None
    if byhand:
        L2 = ['STEP Services', '']
        if env_rows:
            # Settings come after this step in the operator's order, but a restart is what reads
            # a .env -- restart first and the new keys sit there doing nothing until next time.
            L2 += ['> Set the `.env` keys from the **Settings** step below **before** restarting: '
                   'a service reads its `.env` at start-up, so a restart done first leaves them inactive.', '']
        # Only the ones the deploy will not restart itself. The opt-in units are covered by
        # passing --restart in the deploy step, so they are not the operator's list to keep.
        L2 += ['Restart these after the update:', '',
               ', '.join(f'`{u.name}`' for u in byhand), '']
    steps.append(('svc', L2, len(byhand))) if byhand else None
    if graf:
        L2 = ['STEP Grafana', '', 'Dashboards to update:', '']
        L2 += [f'- `{p}`' + ('  ← **your dashboard**' if src == 'yours' else '') for p, src in graf]
        L2.append('')

    steps.append(('graf', L2, len(graf))) if graf else None

    order = ['db', 'nginx', 'svc', 'env', 'graf']
    n = 0
    for key in order:
        for k, body, count in steps:
            if k != key:
                continue
            n += 1
            title = body[0].replace('STEP ', '')
            # The count rides on the heading: with every section collapsed, a summary line
            # repeating the same five numbers above them was the only thing to read.
            L += ['<details>', '<summary><h3>%d. %s (%d)</h3></summary>' % (n, title, count), '']
            L += list(body[1:])
            L += ['</details>', '']
    sys.stdout.write('\n'.join(L) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
