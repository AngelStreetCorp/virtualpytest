#!/usr/bin/env python3
"""Word error rate of captions against a reference, pair by pair (TASK-90 goal 11, local measurements).

    python3 scripts/caption_wer.py pairs.json

pairs.json: [{"ref": "...", "hyp": "..."}, ...]. Both sides are normalised (lower case, ss for sharp s, punctuation and thousands
separators dropped, hyphens read as spaces) and compared word by word with a Levenshtein distance. Prints each pair and the
word-weighted total. The reference of the SRF 1 measurement is the broadcaster's own subtitle text read off the frames, so it is not
verbatim speech (subtitles condense); pairs with a reference that could not be read in full are left out by the person who made the file.
"""
import json
import re
import sys


def words(text):
    t = text.lower().replace('ß', 'ss').replace('-', ' ')
    t = re.sub(r"(?<=\d)['.](?=\d)", '', t)
    t = re.sub(r"[^\w\s]", ' ', t)
    return t.split()


def distance(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def main():
    pairs = json.load(open(sys.argv[1]))
    errors = total = 0
    for p in pairs:
        r, h = words(p['ref']), words(p['hyp'])
        d = distance(r, h)
        errors += d
        total += len(r)
        print(f'{d:2d}/{len(r):2d}  {d / max(1, len(r)):4.0%}  {p["hyp"][:70]}')
    print(f'WER {errors}/{total} = {errors / max(1, total):.1%} over {len(pairs)} pairs')


if __name__ == '__main__':
    main()
