#!/usr/bin/env python3
"""Generate narration audio for every scene in a scenes.json and record each
scene's *actual measured* TTS duration back into the file -- never guess
duration from character count, measure it.

Two backends:
- "edge" (default): edge-tts, Microsoft Edge's free neural TTS. No API key,
  no cost. Good enough quality for drafts and most production use. Requires
  `pip install edge-tts`. Also captures real per-word timestamps for free
  (via edge-tts's WordBoundary events) -- written to
  sc["word_timestamps"] = [{"text","start","end"}, ...] (seconds, relative
  to that scene's own audio clip). This is what stage 6 (HyperFrames karaoke
  captions) needs; nothing else in the pipeline requires it.
- "newapi": qwen3-tts-base via the newapi gateway (paid, uses NEWAPI_KEY).
  Use when you specifically need this voice/model or edge-tts is blocked in
  your environment. Does not produce word_timestamps -- if you need stage 6
  for scenes generated this way, run gen_word_timestamps_fallback.py
  afterward (Whisper via `npx hyperframes transcribe`, local, free).

Usage: gen_tts.py <scenes.json> <audio_dir> [backend] [voice]
  backend: edge (default) | newapi
  voice:   edge default zh-CN-YunjianNeural (energetic male, good fit for
           explainer narration) | newapi default "zora" (only voice this
           gateway's key had enabled when checked)
"""
import asyncio, json, subprocess, sys
import config

def synthesize_edge(text, voice, out_path):
    """Returns word_timestamps: [{"text","start","end"}, ...] in seconds,
    relative to this clip's own start -- edge-tts's WordBoundary offsets are
    100-nanosecond ticks (1 tick = 1e-7s), hence the /1e7 conversion."""
    import edge_tts

    async def _run():
        communicate = edge_tts.Communicate(text, voice, boundary="WordBoundary")
        words = []
        with open(out_path, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    words.append({
                        "text": chunk["text"],
                        "start": chunk["offset"] / 1e7,
                        "end": (chunk["offset"] + chunk["duration"]) / 1e7,
                    })
        return words

    return asyncio.run(_run())

def synthesize_newapi(text, voice, out_path):
    import urllib.request
    req = urllib.request.Request(
        f"{config.NEWAPI_URL}/v1/audio/speech",
        data=json.dumps({"model": "qwen3-tts-base", "input": text, "voice": voice}).encode(),
        headers={"Authorization": f"Bearer {config.NEWAPI_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    with open(out_path, "wb") as f:
        f.write(data)
    return None  # no native word-level timestamps -- see gen_word_timestamps_fallback.py

BACKENDS = {
    "edge": (synthesize_edge, "zh-CN-YunjianNeural"),
    "newapi": (synthesize_newapi, "zora"),
}

if __name__ == "__main__":
    scenes_path, audio_dir = sys.argv[1], sys.argv[2]
    backend = sys.argv[3] if len(sys.argv) > 3 else "edge"
    fn, default_voice = BACKENDS[backend]
    voice = sys.argv[4] if len(sys.argv) > 4 else default_voice

    import os
    os.makedirs(audio_dir, exist_ok=True)
    scenes = json.load(open(scenes_path))
    for sc in scenes:
        n = sc["scene"]
        ext = "mp3" if backend == "edge" else "wav"
        out_path = f"{audio_dir}/scene{n:02d}.{ext}"
        word_timestamps = fn(sc["narration"], voice, out_path)
        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out_path],
                              capture_output=True, text=True).stdout.strip()
        sc["tts_duration"] = float(dur)
        sc["audio_path"] = out_path
        if word_timestamps:
            sc["word_timestamps"] = word_timestamps
        else:
            sc.pop("word_timestamps", None)
        print(f"scene{n}: {dur}s ({backend}/{voice}), {len(word_timestamps) if word_timestamps else 0} word timestamps")
        json.dump(scenes, open(scenes_path, "w"), indent=2, ensure_ascii=False)
    print(f"TOTAL: {sum(s['tts_duration'] for s in scenes):.2f}s")
