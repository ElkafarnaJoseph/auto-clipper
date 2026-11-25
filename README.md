# Auto Clipper

Turn long videos and stream VODs into vertical Shorts, TikToks and Reels, automatically. Runs on your own computer, only costs money if you choose the Claude mode.

**Status:** v0.1.0, early release, tested on Windows. Linux and macOS should work but are untested.

## What it does

1. Cuts the part of a long VOD you choose (for example, the first hour).
2. Transcribes it locally with Whisper and measures loud moments.
3. Picks the best 10-60 second moments (free demo scoring, or Claude Haiku for smarter picks).
4. Edits each moment into a 9:16 clip with captions, in one of three layouts.
5. Writes a title, credit line and hashtags for each clip, then logs everything to a local database.

You review the clips and post them yourself.

## How it works

```mermaid
flowchart LR
  A[Full VOD] --> B[cut_vod.py]
  B --> C[transcribe.py]
  C --> D[pick_clips.py]
  D --> E[edit_clips.py]
  E --> F[Clips, titles, hashtags]
  F --> G[(pipeline.db)]
```

| Step | File | What happens |
|---|---|---|
| Cut | `cut_vod.py` | Cuts a time range out of a full VOD with FFmpeg |
| Transcribe | `transcribe.py` | faster-whisper with word timestamps, plus audio loudness (librosa) |
| Pick | `pick_clips.py` | Demo mode (loud audio and excited words) or Claude Haiku, 10-60 s clips |
| Edit | `edit_clips.py` | FFmpeg: layout, captions, optional spoiler warning and note |
| Run all | `clip.py` | Runs the three steps and logs each run to SQLite |

If nothing scores high enough, it says "No clips found" instead of making weak clips.

## Install

Requirements: Python 3.11+, [FFmpeg](https://ffmpeg.org/download.html) (on Windows: `winget install Gyan.FFmpeg`), Git.

```
git clone https://github.com/ElkafarnaJoseph/auto-clipper.git
cd auto-clipper
python -m venv .venv
.venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Optional, for NVIDIA GPU transcription: `pip install -r requirements-gpu.txt`. Without a working GPU it falls back to CPU automatically (slower).

## Use it

1. Put your video in a `vods` folder. Only use videos you own, that are licensed for reuse, or that you have permission to clip.
2. Cut an hour:
   ```
   python cut_vod.py "vods/stream.mp4" 00:00:00 01:00:00
   ```
3. Make clips, free demo mode:
   ```
   python clip.py "cut_videos/stream_00h00m00s-01h00m00s.mp4" --demo
   ```
4. Find them in `output/clips/<video name>/`.

Notes: run all commands from the project folder (the scripts use relative paths like `output/`). The tool is built for landscape 16:9 videos, and vertical videos are untested.

### Using Claude (optional, paid, a few cents or less per hour of video, estimate)

Copy `.env.example` to `.env`, put your API key in it, and run the same command without `--demo`. Check Anthropic's pricing page for current rates. Never commit your `.env`.

### Options

| Flag | What it does |
|---|---|
| `--demo` | Free test mode, no API |
| `--layout fit / mid / crop` | Zoomed out (blurred background), in between, zoomed in |
| `--zoom 1.4` | How far `mid` zooms in |
| `--focus left / center / right` | Which side to keep when zooming (for facecams) |
| `--spoiler` / `--spoiler-text "..."` | Spoiler warning for the first 3 seconds |
| `--note "..."` / `--note-from-title` | Text above the video |
| `--credit "Name"` | Credit line in the post text and hashtags |
| `--tags "gaming,funny"` | Extra topic hashtags |
| `-n 8`, `--min-score 5` | Max clips and quality bar |
| `--reuse-transcript` | Skip the slow transcription step on re-runs |
| `--no-captions`, `--device`, `--language` | Captions off, CPU/GPU choice, force a language |

To remake one clip with its own note: `python edit_clips.py output/NAME_clips.json video.mp4 --only 3 --note "text"`

### Output per clip

`clip_01.mp4`, `clip_01_post.txt` (title and credit), `clip_01_hashtags.txt` (YouTube Shorts, TikTok, Instagram Reels). Every run is logged in `pipeline.db`, including empty columns for views and likes.

## Versions

- **v0.1.0**: first release. Cut, transcribe, pick (demo and Claude), edit with three layouts, spoiler warning, note text, credit, hashtag files, SQLite logging.

## Known limitations (v0.1.0)

- Built and tested on Windows with 16:9 landscape videos. Vertical videos are untested.
- Claude mode is implemented but not yet tested end to end.
- Run commands from the project folder (scripts use relative paths).
- Demo mode only scores loudness and keywords, so it can't judge humor or hooks.
- Older clip files can remain in an output folder if a later run makes fewer clips.
- GPU setup is written for Windows; on Linux, CUDA libraries may need manual setup.


## Roadmap

Plans, not promises:

- **Near term:** facecam-aware stacked layout, config file, tests, pinned dependencies, Linux/macOS testing.
- **Local app:** a simple interface (for example Streamlit) to upload a video, preview clips, adjust start and end, edit titles and notes, and export.
- **Easy install:** downloadable packages on the Releases page so non-programmers can run it.
- **Hosted version:** GitHub Pages can only host static pages, so processing would need a server (or in-browser tools like ffmpeg.wasm) with real hosting costs.
- **Taste learning:** log which clips a user keeps, edits and posts. First feed good and bad examples into the Claude prompt, later train a small ranking model on that data to match each user's taste and edit style. Needs a few hundred labeled clips to be useful.

## Responsible use

Clipping someone else's content usually needs their permission, and platform terms apply. This tool doesn't grant any rights to the videos you process. You are responsible for what you download and post.

## License

MIT, see [LICENSE](LICENSE).