#!/usr/bin/env python3
"""Score an offline run of the egg profile against the synthetic conveyor's ground truth (TASK-90 goal 9).

    python3 scripts/egg_eval.py --run run.json --truth .local-data/eggs/conveyor/truth.json

Each verdict the monitor emitted (one per track) is matched to the egg whose left edge came into view up to 2.2 s before the
track's first sighting. Reports: count error, correct / wrong / unverified verdicts among the matched, eggs with no verdict (missed), eggs with
more than one verdict (double counts), verdicts that match no egg (false), and per-class precision/recall on the verified ones.
"""
import argparse
import json
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', required=True)
    ap.add_argument('--truth', required=True)
    ap.add_argument('--attr', default='condition')
    args = ap.parse_args()
    run, truth = json.load(open(args.run)), json.load(open(args.truth))
    eggs = truth['eggs']
    by_egg = defaultdict(list)
    false = []
    for v in run['verdicts']:
        # a track's first sighting is just after its egg's left edge comes into view; the belt brings an egg every `gap` s,
        # so these windows do not overlap and a verdict belongs to exactly one egg
        hit = [e for e in eggs if e['enters_t'] - 0.2 <= v['first'] <= e['enters_t'] + 2.2]
        if hit:
            by_egg[hit[0]['id']].append(v)
        else:
            false.append(v)
    classes = sorted({e['class'] for e in eggs})
    conf = defaultdict(int)
    correct = wrong = unverified = missed = doubles = 0
    for e in eggs:
        vs = by_egg.get(e['id'], [])
        if not vs:
            missed += 1
            continue
        if len(vs) > 1:
            doubles += len(vs) - 1
        label = vs[0]['attrs'].get(args.attr)
        if label == 'unverified':
            unverified += 1
        elif label == e['class']:
            correct += 1
        else:
            wrong += 1
        conf[(e['class'], label)] += 1
    n_verdicts = len(run['verdicts'])
    out = {
        'eggs_in_truth': len(eggs), 'verdicts': n_verdicts,
        'count_error_pct': round(100 * abs(n_verdicts - len(eggs)) / len(eggs), 1),
        'correct': correct, 'wrong': wrong, 'unverified': unverified, 'unverified_pct': round(100 * unverified / len(eggs), 1),
        'missed_no_verdict': missed, 'double_counts': doubles, 'false_verdicts_matching_no_egg': len(false),
        'accuracy_on_verified_pct': round(100 * correct / max(1, correct + wrong), 1), 'per_class': {},
    }
    for c in classes:
        tp = conf[(c, c)]
        fp = sum(conf[(o, c)] for o in classes if o != c)
        fn = sum(n for (t, p), n in conf.items() if t == c and p not in (c, 'unverified'))
        out['per_class'][c] = {'precision': round(tp / max(1, tp + fp), 3), 'recall_of_verified': round(tp / max(1, tp + fn), 3),
                               'support': sum(1 for e in eggs if e['class'] == c)}
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
