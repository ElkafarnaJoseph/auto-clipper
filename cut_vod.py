import argparse
import json
import subprocess
from pathlib import Path

CUT_DIR = Path("cut_videos")
CUT_DIR.mkdir(exist_ok=True)


def to_seconds(t: str) -> float:
    parts = [float(x) for x in t.split(":")]
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, (m, s) = 0, parts
    else:
        raise SystemExit(f"Bad time '{t}'. Use HH:MM:SS, for example 01:30:00")
    return h * 3600 + m * 60 + s


def fmt(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02}:{sec % 3600 // 60:02}:{sec % 60:02}"


def get_duration(video: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(video),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"ffprobe failed:\n{r.stderr[-600:]}")
    value = json.loads(r.stdout).get("format", {}).get("duration")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SystemExit("Could not read the video length. Is the file a complete, valid video?")


def main():
    p = argparse.ArgumentParser(description="Cut a part out of a full VOD.")
    p.add_argument("video", help="path to the full VOD, e.g. vods\\stream.mp4")
    p.add_argument("start", nargs="?", help="start time, e.g. 00:00:00")
    p.add_argument("end", nargs="?", help="end time, e.g. 01:00:00")
    p.add_argument("--precise", action="store_true",
                   help="re-encode for frame-exact cuts (slower, default is a fast copy)")
    args = p.parse_args()

    video = Path(args.video)
    if not video.exists():
        raise SystemExit(f"Video not found: {video}")

    total = get_duration(video)
    print(f"{video.name} is {fmt(total)} long.")

    if not args.start or not args.end:
        print('Now pick a part, for example:\n  python cut_vod.py "' + str(video) + '" 00:00:00 01:00:00')
        return

    start, end = to_seconds(args.start), to_seconds(args.end)
    if start >= total:
        raise SystemExit(f"Start {fmt(start)} is past the end of the video ({fmt(total)}).")
    if end > total:
        print(f"End is past the video, using {fmt(total)} instead.")
        end = total
    if end <= start:
        raise SystemExit("End time must be after start time.")

    tag = f"{fmt(start).replace(':', 'h', 1).replace(':', 'm', 1)}s"
    tag_end = f"{fmt(end).replace(':', 'h', 1).replace(':', 'm', 1)}s"
    out = CUT_DIR / f"{video.stem}_{tag}-{tag_end}.mp4"

    cmd = ["ffmpeg", "-y", "-ss", str(start), "-t", str(end - start), "-i", str(video)]
    if args.precise:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac"]
    else:
        cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
    cmd.append(str(out))

    print(f"Cutting {fmt(start)} to {fmt(end)} ...")
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()