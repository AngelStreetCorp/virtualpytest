#!/usr/bin/env python3
"""ABSTAIN-DOOR HISTOGRAM — TASK-68 row 7, the measurement EXPERIMENT-01 waits on.

`identify_screen` abstains on ~61.6% of `stb_tv` frames. That one number hides six different
exits, and only THREE of them (doors 2, 5, 6) are addressable by a local decision model:
door 1 is already named by `classify_special_state`, doors 3 and 4 are calibration/OCR fixes.
So the question this answers is not "how much does it abstain" but "which door does the
abstain come out of, per userinterface" — the stop condition is "if doors 2+5+6 are under
~30% of abstains, do not build Tier 3".

It replays frames that ALREADY EXIST (no capture, no device, no write) through the REAL
`identify_screen` with the REAL node set for a UI, and tallies the outcome per frame:

    matched                      — at least one candidate survived every door
    abstain / door N              — empty, and the reason names door N
    abstain / capture-state       — empty and `classify_special_state` named it (blackscreen / no_signal)
    abstain / unattributed        — empty, no door in the reason (reported verbatim, never folded in)

Doors are numbered as in docs/agent/navigation/FINGERPRINT.md. Because `identify_screen`
chains its notes with `' +'` (never overwriting), the LAST note of a chain is the door that
emptied the list; the tally records BOTH — `doors` (terminal, the headline number) and
`door_seen` (every door that dropped anything, including fail-safe narrowing that could not
abstain on its own).

READ-ONLY: frames are opened and never written, moved or deleted; the only file written is
its own report. `--limit` caps the frames read so a replay can never hammer a host.

Node fingerprints come from the DB for a named userinterface (`--ui`, the production
`_load_node_fps` rule, via MonitorLocalizer) or from a local screenshot corpus (`--corpus`,
the offline-test convention, no DB). Nothing else about the environment is touched.

Usage on a host:
    /opt/virtualpytest/venv/bin/python features/avq/backend_host/localize/abstain_histogram.py \
        --capture /var/www/html/stream/capture1 --ui stb_tv --limit 3000 \
        --out /tmp/abstain_histogram.md
Locally (no DB):
    python3 features/avq/backend_host/localize/abstain_histogram.py \
        --corpus screenshot/example_tv --capture /tmp/my_frames --ui local-corpus
"""
import argparse
import glob
import importlib.util
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# VIRTUALPYTEST_REPO lets the script run from /tmp on a host (where the checkout lives
# elsewhere and must not be written to); unset, it is the repo it sits in.
_REPO = os.environ.get('VIRTUALPYTEST_REPO') or os.path.abspath(
    os.path.join(_HERE, '..', '..', '..', '..'))
# Import image_helpers DIRECTLY (as the sibling offline harnesses do) so the tally itself
# stays importable without cv2 or a DB — that is what the unit tests exercise.
sys.path.insert(0, os.path.join(_REPO, 'backend_host', 'src', 'controllers', 'verification'))


# ── the six doors ────────────────────────────────────────────────────────────────────
# (number, label, fix, [reason fragments that identify the door])
# A fragment matches anywhere in the reason chain, so a chain like
# "… +confidence floor: 1 candidate(s) …" is attributed to door 6 as the terminal door.
DOORS = (
    (1, 'low-content frame', 'none — classify_special_state already names it',
     ('low-content frame',)),
    (2, 'nav underline matched no node', 'semantic model',
     ('nav underline matched no node',)),
    (3, 'nav underline far from chrome, no title match', 'calibration fix',
     ('nav underline far from chrome',)),
    (4, 'title disambiguation (title_score < 0.5)', 'OCR work',
     ('title disambiguation:',)),
    (5, 'dHash fallback narrowing / no qualifying screen', 'semantic model',
     ('dHash fallback narrowing:', 'no qualifying screen')),
    (6, 'confidence floor (FP_MIN_CONFIDENCE)', 'semantic model',
     ('confidence floor:',)),
)
# Reasons that are NOT one of the six doors. They are counted and printed verbatim rather
# than folded into a door, so nothing is silently misattributed.
OTHER_REASONS = ('no v5 region fingerprints', 'low-confidence answer not confirmed by Jev')
MODEL_ADDRESSABLE = (2, 5, 6)          # the doors EXPERIMENT-01's stop condition is about


def split_chain(reason):
    """A `reason` string -> its individual notes, in execution order (' +' is the separator)."""
    if not reason:
        return []
    return [p.strip() for p in str(reason).split(' +') if p.strip()]


def door_of_note(note):
    """The door number a single reason note names, or None."""
    for number, _label, _fix, fragments in DOORS:
        if any(frag in note for frag in fragments):
            return number
    return None


def classify(result):
    """One `identify_screen` result -> (bucket, door, reason, state).

    bucket is one of: 'matched', 'abstain', 'unattributed'. door is the TERMINAL door (the
    last note of the chain), None when the reason names no door.
    """
    cands = result.get('candidates') or []
    reason = (result.get('reason') or '').strip()
    state = result.get('state')
    if cands:
        return 'matched', None, reason, state
    doors = [d for d in (door_of_note(n) for n in split_chain(reason)) if d is not None]
    if doors:
        return 'abstain', doors[-1], reason, state
    return 'unattributed', None, reason, state


def doors_seen(result):
    """Every door that dropped candidates for this frame, in execution order (may be empty)."""
    reason = (result.get('reason') or '')
    return [d for d in (door_of_note(n) for n in split_chain(reason)) if d is not None]


class Tally:
    """Per-group frame tally: matched / abstained / named capture state / per-door counts.

    Two populations are kept apart. `all_*` is every frame. `content_*` drops the frames
    `classify_special_state` NAMED (`no_signal` = the capture card's test pattern,
    `blackscreen`) — those are a capture-side fault, not an unidentified screen, and on a host
    whose STB is powered down they are most of the archive. The door percentages that decide
    EXPERIMENT-01 are the content ones; the all-frames ones are reported too so the mix is
    visible rather than hidden.
    """

    def __init__(self, label):
        self.label = label
        self.frames = 0
        self.matched = 0
        self.abstained = 0
        self.unattributed = 0
        self.door_frames = {}        # terminal door -> frames that abstained there
        self.door_seen = {}          # any door that dropped candidates -> frames
        self.states = {}             # named capture state -> frames
        self.other_reasons = {}      # verbatim reason -> frames (never folded into a door)
        self.nodes = {}              # winning node label -> frames (matched only)
        self.content_frames = 0
        self.content_matched = 0
        self.content_abstained = 0
        self.content_door_frames = {}

    def add(self, result):
        self.frames += 1
        bucket, door, reason, state = classify(result)
        for d in doors_seen(result):
            self.door_seen[d] = self.door_seen.get(d, 0) + 1
        if not state:                                     # not a named capture-side state
            self.content_frames += 1
            if bucket == 'matched':
                self.content_matched += 1
            else:
                self.content_abstained += 1
                if door is not None:
                    self.content_door_frames[door] = self.content_door_frames.get(door, 0) + 1
        if bucket == 'matched':
            self.matched += 1
            label = (result.get('candidates') or [{}])[0].get('label') or '?'
            self.nodes[label] = self.nodes.get(label, 0) + 1
            return
        self.abstained += 1
        if door is not None:
            self.door_frames[door] = self.door_frames.get(door, 0) + 1
        else:
            self.unattributed += 1
            if reason:
                self.other_reasons[reason] = self.other_reasons.get(reason, 0) + 1
        if state:
            self.states[state] = self.states.get(state, 0) + 1

    _COUNTERS = ('frames', 'matched', 'abstained', 'unattributed',
                 'content_frames', 'content_matched', 'content_abstained')
    _MAPS = ('door_frames', 'door_seen', 'states', 'other_reasons', 'nodes', 'content_door_frames')

    def merge(self, other):
        for name in self._COUNTERS:
            setattr(self, name, getattr(self, name) + getattr(other, name))
        for name in self._MAPS:
            dst = getattr(self, name)
            for k, v in getattr(other, name).items():
                dst[k] = dst.get(k, 0) + v

    def rows(self, content_only=False):
        """(door, label, fix, terminal_frames, pct_of_that_population, seen_frames), sorted by
        terminal_frames desc — the table the task asks to be frequency-ordered."""
        counts = self.content_door_frames if content_only else self.door_frames
        whole = self.content_abstained if content_only else self.abstained
        out = []
        for number, label, fix, _frag in DOORS:
            n = counts.get(number, 0)
            if not n and not self.door_seen.get(number, 0):
                continue
            pct = (100.0 * n / whole) if whole else 0.0
            out.append((number, label, fix, n, pct, self.door_seen.get(number, 0)))
        out.sort(key=lambda r: (-r[3], r[0]))
        return out

    def model_addressable_share(self, content_only=False):
        """% of abstains that came out of doors 2, 5 or 6 — the stop condition's number."""
        counts = self.content_door_frames if content_only else self.door_frames
        whole = self.content_abstained if content_only else self.abstained
        n = sum(counts.get(d, 0) for d in MODEL_ADDRESSABLE)
        return (100.0 * n / whole) if whole else 0.0


# ── frames ───────────────────────────────────────────────────────────────────────────

def find_frames(base, source='cold'):
    """Every capture jpg under a capture base dir, oldest-first, deduplicated.

    Accepts a base dir (`/var/www/html/stream/capture1`), the `hot/captures` dir itself or
    the cold `captures` dir. Cold is archived as `captures/<hour>/capture_*.jpg` and hot as
    `hot/captures/capture_*.jpg`; the two overlap (the archiver copies hot -> cold), so the
    caller picks one. Pure reads (listdir/stat) — nothing is opened here.
    """
    base = os.path.abspath(base)
    roots = []
    if source in ('cold', 'both'):
        roots += [os.path.join(base, 'captures'), os.path.join(base, 'cold', 'captures')]
    if source in ('hot', 'both'):
        roots.append(os.path.join(base, 'hot', 'captures'))
    roots = [r for r in roots if os.path.isdir(r)]
    if not roots:
        roots = [base]                     # the caller handed us the captures dir itself
    seen, paths = set(), []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort(key=lambda d: (0, int(d), '') if d.isdigit() else (1, 0, d))
            for name in sorted(filenames):
                if not name.lower().endswith(('.jpg', '.jpeg', '.png')):
                    continue
                p = os.path.join(dirpath, name)
                key = os.path.realpath(p)
                if key in seen:
                    continue
                seen.add(key)
                paths.append(p)
    return paths


def sample(paths, limit):
    """Even stride over the sorted frame list, INCLUDING both endpoints, so the sample spans
    the whole archive instead of only its oldest hour. `limit <= 0` means "no cap"."""
    if not limit or limit <= 0 or limit >= len(paths):
        return list(paths)
    stride = (len(paths) - 1) / float(limit - 1) if limit > 1 else 0.0
    return [paths[int(round(i * stride))] for i in range(limit)]


# ── node fingerprints ────────────────────────────────────────────────────────────────

def load_node_fps_from_corpus(ih, corpus_dir):
    """node_fps from a directory of node screenshots — the offline-test convention
    (localize_regression_test.py): one screenshot per node, fingerprint computed in-process."""
    import cv2
    node_fps = []
    for p in sorted(glob.glob(os.path.join(corpus_dir, '*.jpg')) +
                    glob.glob(os.path.join(corpus_dir, '*.png'))):
        img = cv2.imread(p)
        if img is None:
            continue
        fp = ih.compute_fingerprint(img)
        if fp and fp.get('dhash'):
            name = os.path.splitext(os.path.basename(p))[0]
            node_fps.append({'node_id': name, 'label': name, 'fingerprint': fp})
    return node_fps


def load_node_fps_from_db(ui_name, team_id=None):
    """node_fps for a userinterface through the PRODUCTION loader, so the replay matches what
    the host itself matches against (base variant resolve, dedup by node_id, dHash required)."""
    if _REPO not in sys.path:
        sys.path.insert(0, _REPO)
    # Import the path utils FIRST: they are what loads the host .env, and the DB client is a
    # silent no-op without it — so the import order must not depend on which modules happened
    # to be imported earlier.
    import shared.src.lib.utils.storage_path_utils          # noqa: F401
    from backend_host.scripts.monitor_localize import MonitorLocalizer
    loc = MonitorLocalizer(team_id=team_id)
    node_fps = loc._load_node_fps(ui_name)          # read-only DB queries
    loc._fps_by_ui.clear()                          # nothing is written; drop the cache anyway
    return node_fps


# ── run + render ─────────────────────────────────────────────────────────────────────

def replay(helpers, node_fps, frames, dump=None):
    """Run the real identify_screen over `frames`; return (Tally, [(frame, result, error)]).

    No OCR/tesseract call is forced and no second opinion is run: the doors under test live
    in identify_screen itself. `confirm_low_confidence` is deliberately NOT called — it
    OVERWRITES `reason` when it turns a low-confidence match into an abstain, which would
    hide exactly the door attribution being measured (see identify_screen's docstring).
    `dump`, when a file handle, receives one TSV line per frame (the abstain set
    EXPERIMENT-01 §7.1 needs).
    """
    import cv2
    tally = Tally('frames')
    samples = []
    for path in frames:
        img = cv2.imread(path)
        if img is None:
            continue
        try:
            result = helpers.identify_screen(img, node_fps)
        except Exception as e:                                    # noqa: BLE001
            samples.append((path, None, f'{type(e).__name__}: {e}'))
            continue
        tally.add(result)
        samples.append((path, result, None))
        if dump is not None:
            bucket, door, reason, state = classify(result)
            dump.write(f'{path}\t{bucket}\t{door or "-"}\t{state or "-"}\t{reason}\n')
    return tally, samples


def render(tallies, notes=()):
    """Markdown: one table per group, then a frequency-ordered per-door table + the
    stop-condition number."""
    lines = ['# Abstain-door histogram (TASK-68 row 7)', '']
    for note in notes:
        lines += [f'> {n}' for n in ([note] if isinstance(note, str) else note)]
    if notes:
        lines.append('')

    lines += ['## Per group', '',
              '| group | frames | matched | abstained | abstain % | named capture state | unattributed |',
              '|---|--:|--:|--:|--:|--:|--:|']
    for t in tallies:
        states = ', '.join(f'{k}={v}' for k, v in sorted(t.states.items(), key=lambda kv: -kv[1])) or '-'
        lines.append(f'| {t.label} | {t.frames} | {t.matched} | {t.abstained} | '
                     f'{_pct(t.matched, t.frames)} | {states} | {t.unattributed} |')

    for content_only in (False, True):
        title = ('## Doors among frames with NO named capture state — the population the '
                 'EXPERIMENT-01 question is about'
                 if content_only else
                 '## Doors — all frames, terminal door (the one that emptied the list)')
        lines += ['', title, '',
                  '| door | meaning | fix | frames | % of abstains | frames where the door fired at all |',
                  '|---|---|---|--:|--:|--:|']
        for t in tallies:
            rows = t.rows(content_only=content_only)
            if not rows:
                continue
            lines += [f'**{t.label}**', '']
            for number, label, fix, n, pct, seen in rows:
                lines.append(f'| {number} | {label} | {fix} | {n} | {pct:.1f}% | {seen} |')
            lines.append('')

    total = Tally('ALL')
    for t in tallies:
        total.merge(t)
    if total.frames:
        lines += ['## All groups', '',
                  f'- frames read: **{total.frames}**, matched **{total.matched}** '
                  f'({_pct(total.matched, total.frames)}), abstained **{total.abstained}** '
                  f'({_pct(total.abstained, total.frames)})',
                  f'- of those, **{total.content_frames}** frames carry no named capture state '
                  f'(matched {total.content_matched}, abstained {total.content_abstained}); the rest '
                  f'are `no_signal` / `blackscreen`, i.e. a capture-side fault',
                  f'- **doors 2+5+6 = {total.model_addressable_share():.1f}% of all abstains**, '
                  f'**{total.model_addressable_share(content_only=True):.1f}% of the no-state '
                  f'abstains** (the EXPERIMENT-01 stop condition is ~30%)', '']
    if total.other_reasons:
        lines += ['Reasons that name no door (counted, never folded into one):', '']
        lines += [f'- `{r}` — {n} frames' for r, n in
                  sorted(total.other_reasons.items(), key=lambda kv: -kv[1])]
        lines.append('')
    if total.states:
        lines += ['Named capture states (classify_special_state, runs on empty results):', '']
        lines += [f'- `{s}` — {n} frames' for s, n in sorted(total.states.items(), key=lambda kv: -kv[1])]
        lines.append('')
    return '\n'.join(lines)


def _pct(part, whole):
    return f'{(100.0 * part / whole):.1f}%' if whole else '-'


# ── main ─────────────────────────────────────────────────────────────────────────────

def load_image_helpers():
    """The matcher class to replay with, and the file it came from (recorded in the report).

    `VIRTUALPYTEST_IMAGE_HELPERS=<path>` loads a CANDIDATE copy of image_helpers.py by path
    instead of the checkout's, so a change under test can be replayed on a host that has not
    been deployed to — the host's own tree is never written to. Unset, it is the checkout's.
    """
    override = os.environ.get('VIRTUALPYTEST_IMAGE_HELPERS')
    if override:
        spec = importlib.util.spec_from_file_location('image_helpers_candidate', override)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.ImageHelpers, os.path.abspath(override)
    from backend_host.src.controllers.verification.image_helpers import ImageHelpers
    return ImageHelpers, os.path.join(_REPO, 'backend_host', 'src', 'controllers',
                                      'verification', 'image_helpers.py')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--ui', action='append', default=[],
                    help='userinterface to load node fingerprints for (repeatable; needs the DB)')
    ap.add_argument('--corpus', action='append', default=[],
                    help='directory of node screenshots to fingerprint instead of the DB')
    ap.add_argument('--capture', action='append', default=[],
                    help='capture base dir (e.g. /var/www/html/stream/capture1), repeatable')
    ap.add_argument('--source', choices=('cold', 'hot', 'both'), default='cold',
                    help="which store to walk (default cold: hot is the ~60 s live buffer "
                         "and overlaps it)")
    ap.add_argument('--limit', type=int, default=3000,
                    help='max frames read PER capture dir (default 3000; <=0 means no cap)')
    ap.add_argument('--out', default='/tmp/abstain_histogram.md',
                    help='report file — the ONLY file this script writes')
    ap.add_argument('--dump-frames', default='',
                    help='optional TSV of every frame, its bucket, door and reason')
    args = ap.parse_args(argv)

    if not args.capture:
        ap.error('at least one --capture is required')
    if not args.ui and not args.corpus:
        ap.error('at least one --ui or --corpus is required')

    sys.path.insert(0, _REPO)
    Helpers, matcher_path = load_image_helpers()
    helpers = Helpers(None, None)

    groups = []          # (label, ui, device_model, tally)
    dump_fh = None
    try:
        if args.dump_frames:
            dump_fh = open(args.dump_frames, 'w')
            dump_fh.write('# frame\tbucket\tdoor\tstate\treason\n')

        def run(node_fps, ui, corpus, capture, model):
            frames = sample(find_frames(capture, args.source), args.limit)
            if not frames:
                print(f'WARN: no frames under {capture} ({args.source})')
                return
            tally, _ = replay(helpers, node_fps, frames, dump=dump_fh)
            base = os.path.basename(capture.rstrip('/'))
            tally.label = f'{base} / {ui}'
            groups.append((tally.label, ui, model, tally))

        for corpus in args.corpus:
            node_fps = load_node_fps_from_corpus(helpers, corpus)
            if not node_fps:
                print(f'WARN: no fingerprints in corpus {corpus}')
                continue
            name = os.path.basename(corpus.rstrip('/'))
            for capture in args.capture:
                run(node_fps, name, corpus, capture, '-')

        for ui in args.ui:
            node_fps = load_node_fps_from_db(ui)
            if not node_fps:
                print(f'WARN: no fingerprinted nodes for userinterface {ui}')
                continue
            for capture in args.capture:
                run(node_fps, ui, None, capture, device_model_for(capture))
    finally:
        if dump_fh is not None:
            dump_fh.close()

    if not groups:
        print('ERROR: nothing replayed (no fingerprints or no frames)')
        return 2

    notes = [f'frames per capture dir capped at --limit {args.limit}; store={args.source}',
             f'matcher replayed: `{matcher_path}`',
             'read-only: frames opened, never written; only this report file is created']
    tallies = [t for _l, _u, _m, t in groups]
    report = render(tallies, notes)

    print(report)
    written = [args.out] + ([args.dump_frames] if args.dump_frames else [])
    try:
        with open(args.out, 'w') as fh:
            fh.write(report + '\n')
    except OSError as e:
        print(f'\nERROR: could not write {args.out}: {e}')
        return 2
    print('\nreport written to ' + ', '.join(written))

    print('\n--- per device_model ---')
    by_model = {}
    for label, ui, model, tally in groups:
        merged = by_model.setdefault(model, Tally(f'{model} / {ui}'))
        merged.merge(tally)
    for model, t in sorted(by_model.items(), key=lambda kv: -kv[1].frames):
        print(f'{model:24s} frames={t.frames:5d} matched={t.matched:5d} abstained={t.abstained:5d} '
              f'doors2+5+6={t.model_addressable_share():5.1f}% of all / '
              f'{t.model_addressable_share(content_only=True):5.1f}% of no-state')
    return 0


def device_model_for(capture_dir):
    """DEVICE{N}_MODEL out of the host .env, by matching the capture path. Pure read; returns
    '-' when the env has no entry (so the per-model breakdown is skipped rather than guessed)."""
    env = {}
    for rel in (os.path.join('backend_host', 'src', '.env'), os.path.join('backend_host', '.env')):
        try:
            with open(os.path.join(_REPO, rel)) as fh:
                for key, value in re.findall(r'^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$', fh.read(), re.M):
                    env[key] = value.split('#', 1)[0].strip()      # inline comments are legal in .env
            break
        except OSError:
            continue
    if not env:
        return '-'
    base = os.path.abspath(capture_dir).rstrip('/')
    for key, value in env.items():
        if key.endswith('_VIDEO_CAPTURE_PATH') and value and os.path.abspath(value).rstrip('/') == base:
            num = re.match(r'DEVICE(\d+)_', key)
            return env.get(f'DEVICE{num.group(1)}_MODEL', '-') if num else env.get('HOST_MODEL', '-')
    host = env.get('HOST_VIDEO_CAPTURE_PATH')
    if host and os.path.abspath(host).rstrip('/') == base:
        return env.get('HOST_MODEL', '-')
    return '-'


if __name__ == '__main__':
    sys.exit(main())