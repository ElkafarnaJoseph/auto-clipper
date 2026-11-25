import argparse
import json
import re
import subprocess
from pathlib import Path

WORDS_PER_CAPTION = 4
SPOILER_SECONDS = 3  # how long the spoiler warning stays on screen
PX_PER_UNIT = 1920 / 288  # subtitle sizes use a 288-high scale

FOCUS_X = {"left": "0", "center": "(iw-ow)/2", "right": "iw-ow"}

BASE_TAGS = {
    "YouTube Shorts": ["#shorts", "#youtubeshorts", "#viral"],
    "TikTok": ["#fyp", "#foryou", "#viral"],
    "Instagram Reels": ["#reels", "#instagramreels", "#explore"],
}


def srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def build_srt(words, clip_start, clip_end, srt_path: Path) -> bool:
    clip_words = [w for w in words if clip_start <= w["start"] < clip_end]
    if not clip_words:
        return False
    lines = []
    for i in range(0, len(clip_words), WORDS_PER_CAPTION):
        chunk = clip_words[i:i + WORDS_PER_CAPTION]
        start = chunk[0]["start"] - clip_start
        end = min(chunk[-1]["end"], clip_end) - clip_start
        text = " ".join(w["word"] for w in chunk)
        lines.append(f"{len(lines) + 1}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n")
    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return True


def write_text_srt(text: str, seconds: float, srt_path: Path):
    srt_path.write_text(f"1\n{srt_time(0)} --> {srt_time(seconds)}\n{text}\n", encoding="utf-8")


def style(size, margin_v, alignment=2, color="&H00FFFFFF"):
    return (
        f"FontName=Arial,FontSize={size},Bold=1,PrimaryColour={color},"
        f"OutlineColour=&H00000000,Outline=3,Alignment={alignment},MarginV={margin_v}"
    )


def sub_filter(srt_name: str, st: str) -> str:
    return f"subtitles={srt_name}:force_style='{st}'"


def caption_margin(layout: str, zoom: float) -> int:
    """Put captions just below the video (assumes a 16:9 source)."""
    if layout == "crop":
        return 40
    z = 1.0 if layout == "fit" else zoom
    video_h = 1080 * z * 9 / 16
    bottom_of_video = (1920 + video_h) / 2
    px_from_bottom = 1920 - (bottom_of_video + 110)
    return max(40, round(px_from_bottom / PX_PER_UNIT))


def cut_clip(video: Path, clip, index: int, words, out_dir: Path, o):
    name = f"clip_{index:02d}"
    mp4 = f"{name}.mp4"
    duration = clip["end"] - clip["start"]
    subs = []

    cap_srt = out_dir / f"{name}.srt"
    if o.captions and build_srt(words, clip["start"], clip["end"], cap_srt):
        subs.append(sub_filter(cap_srt.name, style(12, caption_margin(o.layout, o.zoom))))

    if o.spoiler:
        sp = out_dir / f"{name}_spoiler.srt"
        write_text_srt(o.spoiler_text, min(SPOILER_SECONDS, duration), sp)
        subs.append(sub_filter(sp.name, style(14, 20, alignment=8, color="&H0000FFFF")))

    note = clip["title"] if o.note_from_title else o.note
    if note:
        nt = out_dir / f"{name}_note.srt"
        write_text_srt(note, duration, nt)
        subs.append(sub_filter(nt.name, style(11, 45, alignment=8)))

    sub_chain = ",".join(subs)

    if o.layout == "crop":
        vf = (f"crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)':x={FOCUS_X[o.focus]}:y=(ih-oh)/2,"
              "scale=1080:1920")
        if sub_chain:
            vf += "," + sub_chain
        video_args = ["-vf", vf]
    else:
        if o.layout == "fit":
            fg = "[fg]scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2[f];"
        else:  # mid: zoom in, keep the blurred bars
            fg = f"[fg]scale=trunc(1080*{o.zoom}/2)*2:-2,crop=1080:ih:{FOCUS_X[o.focus]}:0[f];"
        graph = (
            "[0:v]split=2[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[b];"
            + fg
            + "[b][f]overlay=(W-w)/2:(H-h)/2"
        )
        if sub_chain:
            graph += "," + sub_chain
        graph += "[v]"
        video_args = ["-filter_complex", graph, "-map", "[v]", "-map", "0:a?"]

    cmd = [
        "ffmpeg", "-y", "-ss", str(clip["start"]), "-t", str(duration),
        "-i", str(video), *video_args,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", mp4,
    ]
    result = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  FFmpeg error on clip {index}:\n{result.stderr[-600:]}")
        return None
    return mp4


def write_post_text(out_dir: Path, index: int, clip, credit):
    lines = [clip["title"]]
    if credit:
        lines += ["", f"Credit: {credit}"]
    name = f"clip_{index:02d}_post.txt"
    (out_dir / name).write_text("\n".join(lines), encoding="utf-8")
    return name


def clean_tag(t: str):
    t = re.sub(r"[^\w]", "", str(t))
    return f"#{t}" if t else None


def write_hashtags(out_dir: Path, index: int, clip, credit, extra_tags):
    topic = []
    for t in list(clip.get("hashtags") or []) + extra_tags + ([credit] if credit else []):
        tag = clean_tag(t)
        if tag and tag.lower() not in [x.lower() for x in topic]:
            topic.append(tag)
    topic = topic[:6]

    blocks = []
    for platform, base in BASE_TAGS.items():
        base_lower = [b.lower() for b in base]
        tags = base + [t for t in topic if t.lower() not in base_lower]
        blocks.append(f"{platform.upper()}\n{' '.join(tags)}")
    name = f"clip_{index:02d}_hashtags.txt"
    (out_dir / name).write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return name


def main():
    p = argparse.ArgumentParser()
    p.add_argument("clips_json")
    p.add_argument("video")
    p.add_argument("--credit", default=None, help='creator/streamer to credit, e.g. "xQc"')
    p.add_argument("--no-captions", action="store_true")
    p.add_argument("--layout", choices=["fit", "mid", "crop"], default="fit",
                   help="fit = zoomed out, mid = in between, crop = zoomed in")
    p.add_argument("--zoom", type=float, default=1.4, help="zoom for --layout mid (1.2 to 2.0)")
    p.add_argument("--focus", choices=["left", "center", "right"], default="center",
                   help="which side to keep when zooming (use left if the facecam is on the left)")
    p.add_argument("--spoiler", action="store_true", help="show a spoiler warning at the start")
    p.add_argument("--spoiler-text", default="SPOILER WARNING")
    p.add_argument("--note", default=None, help="text shown above the video (your reaction / what is happening)")
    p.add_argument("--note-from-title", action="store_true", help="use each clip's title as the note")
    p.add_argument("--tags", default="", help='extra topic hashtags, e.g. "gaming,streamer,funny"')
    p.add_argument("--only", default=None, help='only (re)make these clip numbers, e.g. "3" or "1,4"')
    args = p.parse_args()

    args.captions = not args.no_captions
    args.zoom = max(1.0, args.zoom)
    extra_tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    only = {int(x) for x in args.only.split(",")} if args.only else None

    clips_path = Path(args.clips_json)
    data = json.loads(clips_path.read_text(encoding="utf-8"))
    clips = data["clips"]

    if not clips:
        print("No clips found. Nothing to edit.")
        return

    transcript_path = clips_path.with_name(clips_path.name.replace("_clips.json", "_transcript.json"))
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    words = [w for seg in transcript["segments"] for w in seg["words"]]

    video = Path(args.video).resolve()
    out_dir = clips_path.parent / "clips" / Path(data["video"]).stem
    out_dir.mkdir(parents=True, exist_ok=True)

    made = []
    for i, clip in enumerate(clips, 1):
        if only and i not in only:
            continue
        print(f"{i}/{len(clips)}  {clip['start']:.0f}s-{clip['end']:.0f}s  {clip['title']}")
        mp4 = cut_clip(video, clip, i, words, out_dir, args)
        if mp4:
            post = write_post_text(out_dir, i, clip, args.credit)
            tags = write_hashtags(out_dir, i, clip, args.credit, extra_tags)
            made.append({"file": mp4, "post_text": post, "hashtags_file": tags,
                         "credit": args.credit, **clip})

    if not only:
        (out_dir / "clips_manifest.json").write_text(
            json.dumps(made, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"Done: {len(made)} clips in {out_dir}")


if __name__ == "__main__":
    main()