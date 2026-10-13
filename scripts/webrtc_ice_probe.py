#!/usr/bin/env python3
"""Check that a host's WebRTC media port answers, without a browser.

Posts a minimal WHEP offer, reads the ICE candidates and credentials from the answer,
then sends each IPv4 candidate a STUN Binding Request signed with those credentials.
"REPLY 0x0101" (Binding Success) means UDP reaches MediaMTX on that address. Public
and Tailnet candidates go first: MediaMTX drops a session that has not connected
within 10 s and stops answering for it.

    python3 scripts/webrtc_ice_probe.py vpt-pi1 capture4
    WHEP_URL=http://127.0.0.1:8889/capture1/whep python3 scripts/webrtc_ice_probe.py   # on the host

Run it from outside the hosts' LAN to test the gateway port forward.
Doc: docs/agent/devices/WEBRTC.md §5.
"""
import hashlib
import hmac
import os
import re
import socket
import ssl
import struct
import sys
import urllib.request
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _server_url import server_public_url  # noqa: E402

BASE = server_public_url()
UFRAG, PWD = 'probe', 'probeprobeprobeprobe12'


def offer_sdp() -> str:
    fingerprint = ':'.join(f'{b:02X}' for b in os.urandom(32))
    lines = [
        'v=0', 'o=- 1 2 IN IP4 127.0.0.1', 's=-', 't=0 0', 'a=group:BUNDLE 0',
        'm=video 9 UDP/TLS/RTP/SAVPF 96', 'c=IN IP4 0.0.0.0', 'a=mid:0', 'a=recvonly', 'a=rtcp-mux',
        f'a=ice-ufrag:{UFRAG}', f'a=ice-pwd:{PWD}', f'a=fingerprint:sha-256 {fingerprint}', 'a=setup:actpass',
        'a=rtpmap:96 H264/90000',
        'a=fmtp:96 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f',
    ]
    return '\r\n'.join(lines) + '\r\n'


def binding_request(server_ufrag: str, server_pwd: str) -> bytes:
    """RFC 8445 connectivity check: USERNAME, ICE-CONTROLLING, PRIORITY, MESSAGE-INTEGRITY, FINGERPRINT."""
    tid = os.urandom(12)
    user = f'{server_ufrag}:{UFRAG}'.encode()
    attrs = struct.pack('!HH', 0x0006, len(user)) + user + b'\0' * (-len(user) % 4)
    attrs += struct.pack('!HHQ', 0x802A, 8, int.from_bytes(os.urandom(8), 'big'))
    attrs += struct.pack('!HHI', 0x0024, 4, 0x6E7F00FF)

    def header(length: int) -> bytes:
        return struct.pack('!HHI', 0x0001, length, 0x2112A442) + tid

    mac = hmac.new(server_pwd.encode(), header(len(attrs) + 24) + attrs, hashlib.sha1).digest()
    attrs += struct.pack('!HH', 0x0008, 20) + mac
    crc = (zlib.crc32(header(len(attrs) + 8) + attrs) ^ 0x5354554E) & 0xFFFFFFFF
    attrs += struct.pack('!HHI', 0x8028, 4, crc)
    return header(len(attrs)) + attrs


def main() -> int:
    host, capture = (sys.argv[1:3] + ['vpt-pi3', 'capture1'][len(sys.argv[1:3]):])[:2]
    url = os.environ.get('WHEP_URL') or f'{BASE}/host/{host}/whep/{capture}/whep'
    req = urllib.request.Request(url, data=offer_sdp().encode(), method='POST', headers={
        'Content-Type': 'application/sdp', 'User-Agent': 'Mozilla/5.0'})  # Cloudflare blocks Python's UA
    try:
        res = urllib.request.urlopen(req, timeout=10, context=ssl._create_unverified_context())
    except Exception as e:  # noqa: BLE001 — print whatever the proxy or MediaMTX said
        body = e.read()[:300].decode(errors='replace') if hasattr(e, 'read') else ''
        print(f'POST {url} failed: {e} {body}')
        return 1
    answer = res.read().decode()
    print(f'POST {url} -> {res.status}')
    server_ufrag = re.search(r'a=ice-ufrag:(\S+)', answer).group(1)
    server_pwd = re.search(r'a=ice-pwd:(\S+)', answer).group(1)
    ips = {}
    for ip, port in re.findall(r'a=candidate:\S+ \d+ udp \d+ (\S+) (\d+) typ', answer, re.I):
        if ':' not in ip:
            ips[ip] = int(port)

    def order(ip: str) -> int:
        if re.match(r'^(127\.|10\.|192\.168\.|172\.)', ip):
            return 2
        return 1 if ip.startswith('100.') else 0

    ok = False
    for ip in sorted(ips, key=order):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0)
        reply = None
        for _ in range(2):
            try:
                sock.sendto(binding_request(server_ufrag, server_pwd), (ip, ips[ip]))
                reply = struct.unpack('!H', sock.recvfrom(2048)[0][:2])[0]
                break
            except OSError:
                pass
        ok |= reply == 0x0101
        print(f'  {ip}:{ips[ip]:<6} ' + (f'REPLY 0x{reply:04x}' if reply is not None else 'no reply'))
    return 0 if ok else 2


if __name__ == '__main__':
    sys.exit(main())
