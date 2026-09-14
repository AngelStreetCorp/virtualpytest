#!/usr/bin/env python3
"""Send one or more keys into the running hid_remote.py via FIFO.

Usage:
  sendkey.py OK
  sendkey.py VOLUP VOLUP MUTE
  sendkey.py 0x00E9
"""
import sys
import time

FIFO_PATH = '/tmp/hid_remote.fifo'


def main():
    if len(sys.argv) < 2:
        print('usage: sendkey.py KEY [KEY ...]', file=sys.stderr)
        sys.exit(1)
    with open(FIFO_PATH, 'w') as f:
        for key in sys.argv[1:]:
            f.write(key + '\n')
            f.flush()
            time.sleep(0.15)


if __name__ == '__main__':
    main()
