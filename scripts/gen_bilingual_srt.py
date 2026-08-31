#!/usr/bin/env python3
"""Write a bilingual SRT (English dialogue line on top, Chinese translation
below) from a dialogue-cast scenes.json produced by dialogueize_scenes.py +
translate_dialogue.py. One cue per voiced scene, spanning its measured
tts_duration -- dialogue lines are already short (one spoken line), unlike
narrator prose, so no further phrase-splitting is needed. Silent scenes
(no narration) contribute no cue and just advance the cursor by their
placeholder duration (passed in via scene_gap_seconds, matching how the
timeline will place them once retimed).

Usage: gen_bilingual_srt.py <scenes_dialogue.json> <out.srt>
"""
import json, sys

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
        dur = sc.get("tts_duration") or sc.get("silent_duration") or 0.0
        if sc.get("narration"):
            en = sc["narration"]
            zh = sc.get("narration_zh_translated", "")
            lines.append(str(idx))
            lines.append(f"{fmt(cursor)} --> {fmt(cursor + dur)}")
            lines.append(en)
            if zh:
                lines.append(zh)
            lines.append("")
            idx += 1
        cursor += dur
    open(out_path, "w").write("\n".join(lines))
    print(f"wrote {out_path}, {idx - 1} caption cues, total {cursor:.2f}s")
