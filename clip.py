import argparse
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path("output")
DB_PATH = Path("pipeline.db")


def run_step(label, cmd):
    print(f"\n=== {label} ===")
    start = time.time()
    if subprocess.run(cmd).returncode != 0:
        raise SystemExit(f"Step failed: {label}")
    return round(time.time() - start, 1)


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, video TEXT, video_seconds REAL,
        mode TEXT, input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL,
        transcribe_sec REAL, pick_sec REAL, edit_sec REAL, clips_made INTEGER, credit TEXT
    );
    CREATE TABLE IF NOT EXISTS clips (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, file TEXT, start REAL, end REAL,
        score REAL, title TEXT, reason TEXT, credit TEXT,
        posted_platform TEXT, views INTEGER, likes INTEGER, watch_time_pct REAL
    );
    """)
    return con


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("--demo", action="store_true", help="free test mode, no Claude")
    p.add_argument("--credit", default=None, help='creator/streamer to credit (optional)')
    p.add_argument("-n", type=int, default=8)
    p.add_argument("--min-score", type=float, default=5)
    p.add_argument("--no-captions", action="store_true")
    p.add_argument("--reuse-transcript", action="store_true")
    p.add_argument("--device", default="auto")
    p.add_argument("--language", default=None)
    p.add_argument("--layout", choices=["fit", "mid", "crop"], default="fit")
    p.add_argument("--zoom", type=float, default=1.4)
    p.add_argument("--focus", choices=["left", "center", "right"], default="center")
    p.add_argument("--spoiler", action="store_true")
    p.add_argument("--spoiler-text", default="SPOILER WARNING")
    p.add_argument("--note", default=None)
    p.add_argument("--note-from-title", action="store_true")
    p.add_argument("--tags", default="")
    args = p.parse_args()

    video = Path(args.video)
    if not video.exists():
        raise SystemExit(f"Video not found: {video}")

    py, stem = sys.executable, video.stem
    transcript = OUTPUT_DIR / f"{stem}_transcript.json"
    clips_json = OUTPUT_DIR / f"{stem}_clips.json"
    manifest = OUTPUT_DIR / "clips" / stem / "clips_manifest.json"

    if args.reuse_transcript and transcript.exists():
        print("Reusing existing transcript.")
        t_sec = 0.0
    else:
        cmd = [py, "transcribe.py", str(video), "--device", args.device]
        if args.language:
            cmd += ["--language", args.language]
        t_sec = run_step("1/3 Transcribe", cmd)

    pick = [py, "pick_clips.py", str(transcript), "-n", str(args.n), "--min-score", str(args.min_score)]
    if args.demo:
        pick.append("--demo")
    p_sec = run_step("2/3 Pick clips", pick)

    edit = [py, "edit_clips.py", str(clips_json), str(video)]
    edit += ["--layout", args.layout, "--zoom", str(args.zoom),
             "--focus", args.focus, "--spoiler-text", args.spoiler_text]
    if args.spoiler:
        edit.append("--spoiler")
    if args.note:
        edit += ["--note", args.note]
    if args.note_from_title:
        edit.append("--note-from-title")
    if args.tags:
        edit += ["--tags", args.tags]
    if args.credit:
        edit += ["--credit", args.credit]
    if args.no_captions:
        edit.append("--no-captions")
    manifest.unlink(missing_ok=True)  # don't log clips from an earlier run
    e_sec = run_step("3/3 Edit clips", edit)


    picked = json.loads(clips_json.read_text(encoding="utf-8"))
    made = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else []
    segs = json.loads(transcript.read_text(encoding="utf-8"))["segments"]
    usage = picked["usage"]

    con = init_db()
    cur = con.execute(
        """INSERT INTO runs (created_at, video, video_seconds, mode, input_tokens, output_tokens,
           cost_usd, transcribe_sec, pick_sec, edit_sec, clips_made, credit)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (datetime.now().isoformat(timespec="seconds"), video.name, segs[-1]["end"] if segs else 0,
         picked["mode"], usage["input_tokens"], usage["output_tokens"], usage["cost_usd"],
         t_sec, p_sec, e_sec, len(made), args.credit),
    )
    for c in made:
        con.execute(
            "INSERT INTO clips (run_id, file, start, end, score, title, reason, credit) VALUES (?,?,?,?,?,?,?,?)",
            (cur.lastrowid, c["file"], c["start"], c["end"], c["score"], c["title"], c.get("reason", ""), c.get("credit")),
        )
    con.commit()
    con.close()

    print("\n=== DONE ===")
    if made:
        print(f"{len(made)} clips in {OUTPUT_DIR / 'clips' / stem}")
    else:
        print("No clips found in this video.")
    print(f"Mode: {picked['mode']} | Cost: ${usage['cost_usd']} | Logged to {DB_PATH}")


if __name__ == "__main__":
    main()