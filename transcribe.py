import os
import sys
import argparse
import json
import subprocess
from pathlib import Path

import librosa
import numpy as np
from faster_whisper import WhisperModel

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# let Windows find the NVIDIA libraries installed inside the venv
_nvidia = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
for _sub in ("cublas", "cudnn"):
    _bin = _nvidia / _sub / "bin"
    if _bin.exists():
        os.add_dll_directory(str(_bin))
        os.environ["PATH"] = str(_bin) + os.pathsep + os.environ["PATH"]

def extract_audio(video: Path) -> Path:
    wav = OUTPUT_DIR / f"{video.stem}.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
        check=True, capture_output=True,
    )
    return wav


def transcribe(wav: Path, model_name: str, device: str, language):
    audio, _ = librosa.load(str(wav), sr=16000, mono=True)  # avoids the broken audio decoder

    def go(dev, compute):
        model = WhisperModel(model_name, device=dev, compute_type=compute)
        segments, info = model.transcribe(
            audio, word_timestamps=True, language=language, vad_filter=True
        )
        out = []
        for seg in segments:  # the real work happens while looping here
            print(f"\r  {seg.end / 60:.1f} min transcribed", end="", flush=True)
            out.append({
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": seg.text.strip(),
                "words": [
                    {"word": w.word.strip(), "start": round(w.start, 2), "end": round(w.end, 2)}
                    for w in (seg.words or [])
                ],
            })
        print()
        return out, info.language

    try:
        return go(device, "auto")
    except Exception as e:
        if device == "cpu":
            raise
        print(f"\n  GPU run failed ({e}). Retrying on CPU...")
        return go("cpu", "int8")


def audio_energy(wav: Path):
    y, sr = librosa.load(str(wav), sr=16000, mono=True)
    rms = librosa.feature.rms(y=y, frame_length=sr, hop_length=sr)[0]
    rms = rms / (rms.max() or 1)
    threshold = max(float(np.percentile(rms, 90)), 0.25)  # loud AND in the top 10%
    return {
        "per_second": [round(float(v), 3) for v in rms],
        "hype_seconds": [int(i) for i, v in enumerate(rms) if v >= threshold],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("--model", default="small", help="small, medium, large-v3")
    p.add_argument("--device", default="auto", help="auto, cuda, cpu")
    p.add_argument("--language", default=None, help="e.g. en, fr, ar (default: auto-detect)")
    args = p.parse_args()

    video = Path(args.video)
    print("1/3 Extracting audio...")
    wav = extract_audio(video)
    print("2/3 Transcribing (first run downloads the model)...")
    segments, language = transcribe(wav, args.model, args.device, args.language)
    print("3/3 Measuring audio energy...")
    energy = audio_energy(wav)

    out = {"video": video.name, "language": language, "segments": segments, "audio_energy": energy}
    out_path = OUTPUT_DIR / f"{video.stem}_transcript.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done: {out_path}")


if __name__ == "__main__":
    main()