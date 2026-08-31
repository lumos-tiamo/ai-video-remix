#!/usr/bin/env python3
"""Multi-character variant of gen_tts.py -- casts a distinct voice per line
instead of one narrator voice for the whole scenes.json. Requires each scene
to carry its own "voice" field (edge-tts voice name); scenes with no
narration (silent beats, null voice) are skipped, matching gen_tts.py's
measure-don't-guess-duration discipline for every voiced scene.

Usage: gen_tts_multivoice.py <scenes.json> <audio_dir>
"""
import json, subprocess, sys
import gen_tts

if __name__ == "__main__":
    scenes_path, audio_dir = sys.argv[1], sys.argv[2]

    import os
    os.makedirs(audio_dir, exist_ok=True)
    scenes = json.load(open(scenes_path))
    for sc in scenes:
        n = sc["scene"]
        if not sc.get("narration") or not sc.get("voice"):
            print(f"scene{n}: no narration/voice, skipping (silent beat)")
            continue
        out_path = f"{audio_dir}/scene{n:02d}.mp3"
        word_timestamps = gen_tts.synthesize_edge(sc["narration"], sc["voice"], out_path)
        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out_path],
                              capture_output=True, text=True).stdout.strip()
        sc["tts_duration"] = float(dur)
        sc["audio_path"] = out_path
        if word_timestamps:
            sc["word_timestamps"] = word_timestamps
        print(f"scene{n} ({sc.get('speaker', '?')}/{sc['voice']}): {dur}s -- \"{sc['narration']}\"")
        json.dump(scenes, open(scenes_path, "w"), indent=2, ensure_ascii=False)
    voiced_total = sum(s["tts_duration"] for s in scenes if s.get("tts_duration"))
    print(f"TOTAL (voiced scenes only): {voiced_total:.2f}s")
