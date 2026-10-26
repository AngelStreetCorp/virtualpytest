"""Command line for the LoL dataset tool.

    python3 -m lol_dataset extract --video V.mkv --log L.jsonl --events E.json --roster R.json \
        --detections turns.jsonl --subject <ChampionName> --out OUT_DIR [--t0 60 --t1 480]
    python3 -m lol_dataset view --dataset OUT_DIR --video V.mkv --html OUT_DIR/dataset.html
"""
import argparse
import json
import os

from .build import build_tables
from .schema import SCHEMA_VERSION, TABLES
from .privacy import pseudonym, scrub
from . import viewer


def extract(a):
    gid = a.gid or os.path.basename(os.path.normpath(a.out))
    tables, meta, coverage = build_tables(a.video, a.log, a.events, a.roster, a.detections, a.subject, a.t0, a.t1, gid,
                                          frame0=a.frame0, minion_detections=a.minion_detections,
                                          minion_gate_min=a.minion_gate_min, enemy_names=a.enemy_names)
    roster = json.load(open(a.roster, encoding="utf-8"))
    if a.anonymize:
        # Riot IDs replaced by salted hashes everywhere (opt-in: the in-game names are public by default)
        salt = open(a.salt_file, encoding="utf-8").read().strip()
        if not salt:
            raise SystemExit("salt file is empty")
        names = [p.get("riotIdGameName") for p in roster]
        tables = scrub(tables, names, salt)
        meta = scrub(meta, names, salt)
        players = [{"player_id": pseudonym(p["riotIdGameName"], salt), "champion": p.get("championName"),
                    "team": p.get("team")} for p in roster if p.get("riotIdGameName")]
    else:
        players = [{"player_id": p["riotIdGameName"], "champion": p.get("championName"), "team": p.get("team")}
                   for p in roster if p.get("riotIdGameName")]
    os.makedirs(a.out, exist_ok=True)
    for name in TABLES:
        with open(os.path.join(a.out, f"{name}.jsonl"), "w", encoding="utf-8") as f:
            for row in tables.get(name, []):
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(os.path.join(a.out, "decisions.jsonl"), "w", encoding="utf-8") as f:  # Jev shape: turn, t, state, options, chosen, outcome
        for row in tables.get("decisions", []):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(os.path.join(a.out, "players.jsonl"), "w", encoding="utf-8") as f:   # player IDs (Riot IDs, or hashes with --anonymize), champion, team
        for row in players:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    meta["rows"] = {name: len(tables.get(name, [])) for name in TABLES}
    meta["rows"]["decisions"] = len(tables.get("decisions", []))
    meta["format"] = "jsonl (pyarrow not loadable with this NumPy; one file per table)"
    with open(os.path.join(a.out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    with open(os.path.join(a.out, "coverage.json"), "w", encoding="utf-8") as f:
        json.dump(coverage, f, indent=1)
    print(f"schema {SCHEMA_VERSION}: {meta['rows']} -> {a.out}")


def view(a):
    out, rows, thumbs = viewer.build(a.dataset, a.video, a.html)
    print(f"{out}: {rows} ticks, {thumbs} thumbnails, {os.path.getsize(out) / 1e6:.1f} MB")


def main(argv=None):
    p = argparse.ArgumentParser(prog="lol_dataset", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract", help="build the dataset tables for one capture")
    e.add_argument("--video", required=True, help="replay capture (.mkv), for the clock alignment and thumbnails")
    e.add_argument("--log", required=True, help="Replay API / Live Client log (.jsonl), camera per sample")
    e.add_argument("--events", required=True, help="Live Client events (.json with an Events list)")
    e.add_argument("--roster", required=True, help="roster at game start (.json list of players)")
    e.add_argument("--detections", required=True, help="per-frame detection rows at 5 Hz (format in README.md)")
    e.add_argument("--subject", required=True, help="champion the dataset is about, e.g. Garen (must be in the roster)")
    e.add_argument("--out", required=True, help="output folder")
    e.add_argument("--anonymize", action="store_true",
                   help="replace Riot IDs with salted hashes (default: keep the public in-game names)")
    e.add_argument("--salt-file", help="secret salt for --anonymize (keep it outside the repository)")
    e.add_argument("--gid", help="game id stored in every row (default: the output folder name)")
    e.add_argument("--t0", type=float, default=60.0, help="first game second (default 60)")
    e.add_argument("--t1", type=float, default=480.0, help="last game second (default 480)")
    e.add_argument("--frame0", type=float, help="game time of video frame 0 (default: HUD clock alignment)")
    e.add_argument("--minion-detections", help="optional: per-frame minion bars at 15 fps (detect_bars_15fps.py); replaces the 5 Hz minion units")
    e.add_argument("--minion-gate-min", type=float, help="tracker minimum match radius for the 15 fps input (px)")
    e.add_argument("--enemy-names", help="optional: enemy champion names from name tags (enemy_names_30fps.py), by frame")
    e.set_defaults(fn=extract)
    v = sub.add_parser("view", help="write the HTML viewer for a built dataset")
    v.add_argument("--dataset", required=True)
    v.add_argument("--video", help="same capture, for the per-second thumbnails (needs ffmpeg)")
    v.add_argument("--html", required=True)
    v.set_defaults(fn=view)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
