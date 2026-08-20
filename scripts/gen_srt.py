#!/usr/bin/env python3
"""Write an SRT file from scenes.json's narration + measured tts_duration.

Splits each scene's narration into short phrase-level cues at Chinese/English
punctuation (,.!?;:，。！？；：) instead of one long cue per scene -- a whole
sentence as a single caption reliably wraps to 2-3 lines on a 1088px-wide
vertical canvas and looks cluttered/hard to read. Each phrase gets a
duration proportional to its character count within the scene's measured
tts_duration, which is a good enough approximation (real speech doesn't
pause exactly proportionally, but it's close and correct-by-construction --
the phrase cues always sum to exactly the scene's real audio duration, so
they can't drift out of sync with the narration track over a multi-scene
video the way a fixed reading-speed guess would).
"""
import json, re, sys

SPLIT_RE = re.compile(r"([,.!?;:，。！？；：、])")

def split_phrases(text):
    parts = SPLIT_RE.split(text)
    phrases = []
    buf = ""
    for part in parts:
        buf += part
        if SPLIT_RE.fullmatch(part):
            phrases.append(buf)
            buf = ""
    if buf.strip():
        phrases.append(buf)
    return [p for p in phrases if p.strip()]

def fmt(seconds):
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

if __name__ == "__main__":
    scenes_path, out_path = sys.argv[1], sys.argv[2]
    scenes = json.load(open(scenes_path))
    cursor = 0.0
    lines = []
    idx = 1
    for sc in scenes:
        phrases = split_phrases(sc["narration"]) or [sc["narration"]]
        total_chars = sum(len(p) for p in phrases)
        scene_start = cursor
        scene_end = cursor + sc["tts_duration"]
        for p in phrases:
            share = len(p) / total_chars if total_chars else 1 / len(phrases)
            dur = sc["tts_duration"] * share
            start, end = cursor, min(cursor + dur, scene_end)
            lines.append(str(idx))
            lines.append(f"{fmt(start)} --> {fmt(end)}")
            lines.append(p.strip())
            lines.append("")
            idx += 1
            cursor = end
        cursor = scene_end  # avoid drift from rounding across phrases
    open(out_path, "w").write("\n".join(lines))
    print(f"wrote {out_path}, {idx - 1} caption cues, total {cursor:.2f}s")
