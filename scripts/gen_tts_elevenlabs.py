#!/usr/bin/env python3
"""Multi-character TTS via ElevenLabs -- much more natural/human than
edge-tts, at the cost of needing a paid ElevenLabs API key (ELEVENLABS_KEY
in .env). Casts a distinct ElevenLabs voice per line, same contract as
gen_tts_multivoice.py: each scene needs "narration" and an "elevenlabs_voice_id"
(not the edge-tts "voice" field -- ElevenLabs voice IDs are different).

Usage: gen_tts_elevenlabs.py <scenes.json> <audio_dir>
"""
import json, subprocess, sys, urllib.request
import config

def synthesize(text, voice_id, out_path, model_id="eleven_multilingual_v2"):
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        data=json.dumps({
            "text": text,
            "model_id": model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }).encode(),
        headers={"xi-api-key": config.ELEVENLABS_KEY, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    with open(out_path, "wb") as f:
        f.write(data)

if __name__ == "__main__":
    scenes_path, audio_dir = sys.argv[1], sys.argv[2]
    import os
    os.makedirs(audio_dir, exist_ok=True)
    scenes = json.load(open(scenes_path))
    for sc in scenes:
        n = sc["scene"]
        if not sc.get("narration") or not sc.get("elevenlabs_voice_id"):
            print(f"scene{n}: no narration/voice, skipping (silent beat)")
            continue
        out_path = f"{audio_dir}/scene{n:02d}.mp3"
        try:
            synthesize(sc["narration"], sc["elevenlabs_voice_id"], out_path)
        except Exception as e:
            print(f"scene{n}: FAILED: {e}")
            continue
        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out_path],
                              capture_output=True, text=True).stdout.strip()
        sc["tts_duration"] = float(dur)
        sc["audio_path"] = out_path
        print(f"scene{n} ({sc.get('speaker', '?')}): {dur}s -- \"{sc['narration']}\"")
        json.dump(scenes, open(scenes_path, "w"), indent=2, ensure_ascii=False)
    voiced_total = sum(s["tts_duration"] for s in scenes if s.get("tts_duration"))
    print(f"TOTAL (voiced scenes only): {voiced_total:.2f}s")
