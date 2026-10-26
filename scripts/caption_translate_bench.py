#!/usr/bin/env python3
"""Measure caption translation (TASK-103 goal 6): one chunk JSON, one pinned AI profile, one target language.

Runs where the provider keys are (the backend server): `python caption_translate_bench.py chunk.json <profile> <lang>`.
Prints one line per minute (segments, ms, tokens) and the totals with tokens per hour, and writes the translation to
stdout with --show. Pinned profile = no fallback (the model measured is the model that answered)."""
import json
import os
import sys
import time

sys.path.insert(0, os.environ.get('VPT_ROOT', '/opt/virtualpytest'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared.src.lib.ai import gateway, router  # noqa: E402

gateway.use_local_routing()


def main():
    path, profile, lang = sys.argv[1:4]
    import caption_translate as ct
    chunk = json.load(open(path))
    source = ct.lang_code(chunk['language'])
    by_minute = {}
    for s in chunk['segments']:
        by_minute.setdefault(ct.minute_of(s), []).append(s)

    def complete(prompt):
        res = router.resolve_profile(profile, os.environ.get('BENCH_USAGE', ct.USAGE))
        return gateway.execute(res, prompt, max_tokens=int(os.environ.get('BENCH_MAX_TOKENS', ct.MAX_TOKENS)), temperature=0.0)

    tin = tout = 0
    lat = []
    for m in sorted(by_minute):
        out = ct.translate_minute_segments(by_minute[m], source, lang, complete)
        if out is None:
            print(f'minute {m}: FAILED')
            continue
        tin += out['tokens_in']; tout += out['tokens_out']; lat.append(out['ms'])
        print(f'minute {m}: {len(by_minute[m])} segs, {out["ms"]} ms, tokens {out["tokens_in"]}/{out["tokens_out"]}')
        if '--show' in sys.argv:
            for src, dst in zip(by_minute[m], out['segments']):
                print(f'   {src["text"].strip()}  =>  {dst["text"]}')
    n = len(lat) or 1
    print(f'TOTAL {profile} {source}->{lang}: {len(lat)} minutes, latency mean {sum(lat)//n} ms max {max(lat or [0])} ms, '
          f'tokens in {tin} out {tout}, per hour (x{60/n:.1f}): in {int(tin*60/n)} out {int(tout*60/n)}')


main()
