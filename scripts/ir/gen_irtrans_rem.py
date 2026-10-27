#!/usr/bin/env python3
"""
Build an IRTrans .rem remote file from an ir_conf/<type>.json keymap.

ir_conf holds raw ir-ctl pulse strings. Each one is decoded to its protocol and 32
data bits, then written back with the protocol's nominal timings, so the box plays
a clean code instead of a capture with receiver skew. Upload the result in the
IRTrans web UI (Upload IRTrans .rem file); its keys are the panel key names, which
is what the identity maps in irtrans_conf/<type>.json expect.

Usage: gen_irtrans_rem.py <type> [--name <remote>]   (writes irtrans_rem/<type>.rem)
Format and protocols: docs/agent/devices/IRTRANS_REM.md
"""

import argparse
import json
import os

REMOTE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend_host', 'src', 'controllers', 'remote'))

# name -> (header mark, header space, nominal timing line). Digit 0 = header,
# 1 = bit 0, 2 = bit 1; a trailing 1 is the stop pulse.
PROTOCOLS = {
    'nec':       '[N]3[1]9000 4500[2]560 560[3]560 1690[RC]1[FL]108[FREQ]38',
    'samsung32': '[N]3[1]4500 4500[2]560 560[3]560 1690[RC]1[FL]108[FREQ]38',
}


def decode(raw: str):
    """Raw '+9000 -4500 +560 ...' -> (protocol, '0101...' 32 bits in air order)."""
    t = [abs(int(x)) for x in raw.split()]
    if len(t) < 67:
        raise ValueError(f'{len(t)} pulses, not a 32-bit NEC-family code')
    protocol = 'nec' if t[0] > 6500 else 'samsung32'
    bits = ''.join('1' if space > 1100 else '0' for space in t[3:67:2])
    return protocol, bits


def build(ir_type: str, name: str) -> str:
    with open(os.path.join(REMOTE_DIR, 'ir_conf', f'{ir_type}.json')) as f:
        keymap = json.load(f)

    commands, used = [], []
    for key, raw in keymap.items():
        if not raw:
            continue
        protocol, bits = decode(raw)
        if protocol not in used:
            used.append(protocol)
        data = '0' + bits.replace('1', '2').replace('0', '1') + '1'
        commands.append(f'  [{key}][T]{used.index(protocol)}[D]{data}')

    timing = [f'  [{i}]{PROTOCOLS[p]}' for i, p in enumerate(used)]
    return '\n'.join(['[REMOTE]', f'  [NAME]{name}', '', '[TIMING]', *timing, '', '[COMMANDS]', *commands, ''])


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    parser.add_argument('ir_type')
    parser.add_argument('--name', help='remote name in the box (default: ir_type)')
    args = parser.parse_args()

    out = os.path.join(REMOTE_DIR, 'irtrans_rem', f'{args.ir_type}.rem')
    with open(out, 'w') as f:
        f.write(build(args.ir_type, args.name or args.ir_type))
    print(out)


if __name__ == '__main__':
    main()
