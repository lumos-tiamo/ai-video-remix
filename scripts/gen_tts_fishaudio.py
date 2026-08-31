#!/usr/bin/env python3
"""Fish Audio variant of gen_tts_multivoice.py -- casts a real community/
official character-voice clone (via Fish Audio's /v1/tts, reference_id =
a voice model ID from https://api.fish.audio/model) instead of a generic
edge-tts voice, for whichever speakers have a confirmed matching model.

Fish Audio's /v1/tts does not return word-level timestamps (unlike
edge-tts's WordBoundary events) -- any stale word_timestamps from a prior
edge-tts pass are dropped for scenes regenerated here, since they'd no
longer line up with the new audio. Stage 4 caption placement only needs
tts_duration (see SKILL.md), not word timestamps, so this is not a blocker.

Usage: gen_tts_fishaudio.py <scenes.json> <audio_dir> <speaker=model_id,...>
  e.g. gen_tts_fishaudio.py scenes.json audio "噜噜=046ae7e902234533880097310601ef3e,噜妹=6e11bc618a194622a80f2cd42f565761"
Only scenes whose "speaker" field matches one of the given names are
regenerated; everything else (silent beats, speakers not in the map) is
left untouched.
"""
import json, subprocess, sys, urllib.request
import config

def synthesize(text, reference_id, out_path):
    body = json.dumps({"text": text, "reference_id": reference_id, "format": "mp3"}).encode()
    req = urllib.request.Request(
        "https://api.fish.audio/v1/tts", data=body,
        headers={"Authorization": f"Bearer {config.FISHAUDIO_KEY}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} from /v1/tts: {e.read().decode()}") from None
    with open(out_path, "wb") as f:
        f.write(data)

if __name__ == "__main__":
    scenes_path, audio_dir, speaker_map_arg = sys.argv[1], sys.argv[2], sys.argv[3]
    speaker_map = dict(pair.split("=", 1) for pair in speaker_map_arg.split(","))

    import os
    os.makedirs(audio_dir, exist_ok=True)
    scenes = json.load(open(scenes_path))
    for sc in scenes:
        n = sc["scene"]
        speaker = sc.get("speaker")
        if speaker not in speaker_map:
            continue
        reference_id = speaker_map[speaker]
        out_path = f"{audio_dir}/scene{n:02d}.mp3"
        synthesize(sc["narration"], reference_id, out_path)
        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out_path],
                              capture_output=True, text=True).stdout.strip()
        sc["tts_duration"] = float(dur)
        sc["audio_path"] = out_path
        sc["tts_backend"] = f"fishaudio:{reference_id}"
        sc.pop("word_timestamps", None)
        print(f"scene{n} ({speaker}, fishaudio/{reference_id}): {dur}s -- \"{sc['narration']}\"")
        json.dump(scenes, open(scenes_path, "w"), indent=2, ensure_ascii=False)
    print("done")
