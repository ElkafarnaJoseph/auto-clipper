import argparse
import json
import math
import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-5-5"
MIN_LEN, TARGET_LEN, MAX_LEN = 10, 25, 60
PRICE_IN, PRICE_OUT = 0.10, 0.50  # USD per million tokens (prompts up to 100K)
CHUNK_SECONDS = 3600
EXCITED = ["haha", "lol", "funny", "crazy", "wow", "amazing", "incredible", "insane",
           "secret", "never", "no way", "omg", "incroyable", "dingue", "مستحيل"]


def overlaps(a, b):
    return not (a["end"] <= b["start"] or a["start"] >= b["end"])


def pick_top(cands, n):
    picked = []
    for c in sorted(cands, key=lambda c: c["score"], reverse=True):
        if all(not overlaps(c, p) for p in picked):
            picked.append(c)
        if len(picked) == n:
            break
    return picked


# ---------------- DEMO MODE (free) ----------------
def demo_pick(data, n, min_score):
    segs = data["segments"]
    per_sec = data["audio_energy"]["per_second"]
    hype = set(data["audio_energy"]["hype_seconds"])
    cands = []

    for i, s in enumerate(segs):
        start, j = s["start"], i
        while j < len(segs) - 1 and segs[j]["end"] - start < TARGET_LEN:
            j += 1
        while j > i and segs[j]["end"] - start > MAX_LEN:
            j -= 1
        end = segs[j]["end"]
        if not (MIN_LEN <= end - start <= MAX_LEN):
            continue

        text = " ".join(x["text"] for x in segs[i:j + 1])
        secs = range(int(start), int(end) + 1)
        hype_frac = sum(1 for t in secs if t in hype) / max(1, len(secs))
        window = [per_sec[t] for t in secs if t < len(per_sec)] or [0]
        loud = sum(window) / len(window)
        low = text.lower()
        text_bonus = 0.25 * sum(w in low for w in EXCITED) + 0.1 * (text.count("!") + text.count("?"))

        raw = 0.45 * min(1, hype_frac * 2.5) + 0.25 * loud + 0.30 * min(1, text_bonus)
        title = re.split(r"[.!?]", text)[0].strip()[:60] or text[:60]
        cands.append({
            "start": start, "end": end, "score": round(10 * raw, 1),
            "title": title, "hook": text[:80],
            "reason": "demo: loud audio and/or excited words",
        })

    good = [c for c in cands if c["score"] >= min_score]
    return pick_top(good, n), {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


# ---------------- REAL MODE (Claude) ----------------
SYSTEM_PROMPT = """You are an expert short-form video editor for TikTok and YouTube Shorts.
Find moments that keep viewers hooked: a strong opening line in the first 3 seconds, a funny
or surprising moment, a strong emotion, or a clear valuable insight. The clip must make sense
without extra context and end at a natural point.
Rules:
- Ideal length 10-30 seconds. Go up to 60 seconds only if the story needs it. Never exceed 60.
- Start and end on sentence boundaries. Clips must not overlap.
- Be strict and score honestly (1-10). Only include clips you would genuinely post.
- If nothing is good enough, return {"clips": []}. Never pad the list.
Respond with ONLY valid JSON, no extra text."""


def snap(start, end, segs):
    """Move times to segment boundaries and enforce 10-60s."""
    starts = [s["start"] for s in segs]
    ends = [s["end"] for s in segs]
    start = max([t for t in starts if t <= start + 0.5] or [starts[0]])
    later = [t for t in ends if t >= end - 0.5]
    end = min(later) if later else ends[-1]
    if end - start > MAX_LEN:
        ok = [t for t in ends if start < t <= start + MAX_LEN]
        if not ok:
            return None
        end = max(ok)
    if end - start < MIN_LEN:
        return None
    return start, end


def claude_pick(data, n, min_score):
    import anthropic

    client = anthropic.Anthropic()
    segs = data["segments"]
    total = segs[-1]["end"] if segs else 0
    n_chunks = max(1, math.ceil(total / CHUNK_SECONDS))
    per_chunk = max(3, math.ceil(n / n_chunks) + 1)
    hype_all = data["audio_energy"]["hype_seconds"]
    tok_in = tok_out = 0
    cands = []

    for k in range(n_chunks):
        lo, hi = k * CHUNK_SECONDS, (k + 1) * CHUNK_SECONDS
        chunk = [s for s in segs if lo <= s["start"] < hi]
        if not chunk:
            continue
        transcript = "\n".join(f"[{s['start']:.0f}-{s['end']:.0f}s] {s['text']}" for s in chunk)
        if len(transcript) / 3 > 90_000:
            raise SystemExit("A chunk is too long for one call. Lower CHUNK_SECONDS.")
        hype = [t for t in hype_all if lo <= t < hi]

        user_msg = f"""Find up to {per_chunk} of the best clips in this part of the video.
Loud/energetic seconds (may signal laughter or excitement): {hype}

Return JSON exactly like:
{{"clips": [{{"start": 12.0, "end": 38.0, "score": 8, "hook": "the opening line", "title": "catchy title", "reason": "why it works", "hashtags": ["topic1", "topic2", "topic3"]}}]}}
hashtags = 3 to 5 short topics specific to this clip, no # sign, no generic ones like fyp.
Transcript:
{transcript}"""

        try:
            reply = client.messages.create(
                model=MODEL, max_tokens=2000, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
        except anthropic.APIError as e:
            raise SystemExit(f"Claude API error: {e}")
        tok_in += reply.usage.input_tokens
        tok_out += reply.usage.output_tokens

        match = re.search(r"\{.*\}", reply.content[0].text, re.DOTALL)
        if not match:
            print("  Warning: Claude did not return JSON for one chunk, skipping it.")
            continue
        try:
            items = json.loads(match.group(0)).get("clips", [])
        except json.JSONDecodeError:
            print("  Warning: could not parse Claude's JSON for one chunk, skipping it.")
            continue

        for c in items:
            try:
                snapped = snap(float(c["start"]), float(c["end"]), segs)
                if snapped:
                    cands.append({
                        "start": snapped[0], "end": snapped[1],
                        "score": float(c.get("score", 0)),
                        "title": c.get("title", "Untitled"),
                        "hook": c.get("hook", ""), "reason": c.get("reason", ""),
                        "hashtags": list(c.get("hashtags") or []),
                    })
            except (KeyError, ValueError, TypeError):
                continue

    good = [c for c in cands if c["score"] >= min_score]
    cost = (tok_in * PRICE_IN + tok_out * PRICE_OUT) / 1_000_000
    return pick_top(good, n), {"input_tokens": tok_in, "output_tokens": tok_out, "cost_usd": round(cost, 6)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("transcript", help="output/<video>_transcript.json")
    p.add_argument("-n", type=int, default=8, help="max number of clips")
    p.add_argument("--min-score", type=float, default=5, help="quality bar, 1-10")
    p.add_argument("--demo", action="store_true", help="force demo mode (free)")
    args = p.parse_args()

    data = json.loads(Path(args.transcript).read_text(encoding="utf-8"))
    demo = args.demo or not os.getenv("ANTHROPIC_API_KEY")
    mode = "demo" if demo else "claude"
    print(f"Mode: {mode}")

    clips, usage = (demo_pick if demo else claude_pick)(data, args.n, args.min_score)

    out = {"video": data["video"], "mode": mode, "usage": usage, "clips": clips}
    out_path = Path(args.transcript).with_name(f"{Path(data['video']).stem}_clips.json")
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    if not clips:
        print(f"No clips found. Nothing scored {args.min_score} or higher (try --min-score 3 to lower the bar).")
    for i, c in enumerate(clips, 1):
        print(f"{i}. {c['start']:.0f}s-{c['end']:.0f}s  score {c['score']}  {c['title']}")
    print(f"Tokens: {usage['input_tokens']} in / {usage['output_tokens']} out, cost ${usage['cost_usd']}")


if __name__ == "__main__":
    main()