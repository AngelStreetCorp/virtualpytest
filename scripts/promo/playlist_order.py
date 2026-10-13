"""Put the "VirtualPyTest in action" playlist in chronological (production) order: video 1 first.
Needs the playlist's sort set to Manual in YouTube Studio (else the API answers 400 manualSortRequired).
Usage: python3 playlist_order.py [--check]
"""
import sys
import youtube_upload as y

ORDER = [   # video number: YouTube id (voiced versions where they exist)
    ("01 VirtualPyTest in 60 seconds", "RBgS376Blvo"), ("02 navigation trees", "_CP29LQe0xQ"),
    ("03 evidence", "bBheQqaRIQM"), ("04 AI agent", "prG2eqnbjfs"), ("05 KPI", "rFkZxSoK0zM"),
    ("06 comparison", "TcRkqETFlco"), ("07 zap", "9cjzYpDVROs"), ("09 monitoring", "DR8IX3Y_rCs"),
    ("10 QuickTest", "xWZyBp7Npck"), ("11 campaign", "RdMTfT4MjAM"), ("12 2048", "hHnKrb9vIc0"),
    ("13 A/V quality", "YlOJau8WPqE"), ("14 map an app", "sDkJ3U14mlE"), ("15 24 streams", "hdcoyhftNEs"),
    ("16 Atlas charts", "HF2Kuiw8zaE"), ("17 test prompting", "ehsC4x7_5KQ"), ("18 virtual script", "x0ghHYXUFeI"),
    ("19 MCP", "pSYvpoRfTIM"), ("20 Atlas Grafana", "ujmCqAn-RvE"), ("21 subtitles", "03jh3MMb6PM"),
    ("22 what's new", "IP7rehiSBo4"), ("23 fingerprint", "qAm6YmmvU5g"), ("24 Switch Fire TV", "Dvd5CpA2SwU"),
]


def items():
    r, _ = y.http("GET", f"{y.API}/playlistItems?part=snippet&maxResults=50&playlistId={y.PLAYLIST}", headers=y.auth_h())
    return r["items"]


def main():
    cur = {p["snippet"]["resourceId"]["videoId"]: p for p in items()}
    missing = [n for n, v in ORDER if v not in cur]
    extra = [p["snippet"]["title"] for v, p in cur.items() if v not in dict((v, n) for n, v in ORDER)]
    if missing or extra:
        sys.exit(f"playlist differs from ORDER: missing {missing}, extra {extra}")
    if "--check" in sys.argv:
        for p in sorted(cur.values(), key=lambda p: p["snippet"]["position"]):
            print(p["snippet"]["position"], p["snippet"]["title"][:70]); return
    for pos, (name, vid) in enumerate(ORDER):
        p = cur[vid]; sn = p["snippet"]
        y.http("PUT", f"{y.API}/playlistItems?part=snippet", headers=y.auth_h(),
               body={"id": p["id"], "snippet": {"playlistId": sn["playlistId"], "resourceId": sn["resourceId"], "position": pos}})
        print(pos, name)


if __name__ == "__main__":
    main()
