#!/usr/bin/env python3
"""Backfill scene-relative word_timestamps for scenes that don't have them
(i.e. generated with the "newapi" TTS backend, which has no native
word-boundary events) by running HyperFrames' own local Whisper transcription
on each scene's already-generated audio. Free, local, no API key.

Real CLI flags on hyperframes@0.8.4 (verified via `npx hyperframes transcribe
--help` -- don't trust older docs): the multilingual model is `large-v3`;
the small/base/tiny sizes are `.en`-suffixed and ENGLISH-ONLY, so `--model
small` (no suffix) is not a valid choice for Chinese audio and silently
doesn't exist as an option -- always pass `--model large-v3 --language zh`
explicitly for this project's narration, never rely on the CLI's own
default (which is `small.en`, an English-only model that would decode
Chinese speech as garbage or attempt to translate it).

`--dir` also must be passed explicitly and unique per scene -- multiple
scenes transcribed without their own --dir will overwrite each other's
transcript.json.

Usage: gen_word_timestamps_fallback.py <scenes.json> [--model large-v3] [--language zh]
"""
import json, os, subprocess, sys, tempfile

def clean_words(words):
    """Drop filler/junk entries per HyperFrames' transcript-guide.md: music
    note glyphs, mojibake placeholders, and near-zero-duration filler."""
    out = []
    for w in words:
        text = w.get("text", "").strip()
        if not text or text in ("♪", "�"):
            continue
        if w.get("end", 0) - w.get("start", 0) < 0.1:
            continue
        out.append(w)
    return out

def transcribe_scene(audio_path, model, language):
    with tempfile.TemporaryDirectory() as tmp_dir:
        result = subprocess.run(
            ["npx", "hyperframes", "transcribe", audio_path, "--dir", tmp_dir,
             "--model", model, "--language", language, "--json"],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(f"transcribe failed: {result.stderr[-2000:]}")
        info = json.loads(result.stdout.strip().splitlines()[-1])
        transcript_path = info.get("transcriptPath") or os.path.join(tmp_dir, "transcript.json")
        transcript = json.load(open(transcript_path))
        # transcript.json shape is [{id,text,start,end}, ...] per hyperframes-media's
        # documented normalized shape.
        return clean_words(transcript)

if __name__ == "__main__":
    scenes_path = sys.argv[1]
    args = sys.argv[2:]
    model = "large-v3"
    language = "zh"
    for i, a in enumerate(args):
        if a == "--model":
            model = args[i + 1]
        if a == "--language":
            language = args[i + 1]

    scenes = json.load(open(scenes_path))
    for sc in scenes:
        n = sc["scene"]
        if sc.get("word_timestamps"):
            print(f"scene{n}: already has word_timestamps, skipping")
            continue
        audio_path = sc.get("audio_path")
        if not audio_path or not os.path.exists(audio_path):
            print(f"scene{n}: FAILED: no audio_path -- run gen_tts.py first")
            continue
        try:
            words = transcribe_scene(audio_path, model, language)
            sc["word_timestamps"] = words
            print(f"scene{n}: {len(words)} word timestamps ({model}/{language})")
        except Exception as e:
            print(f"scene{n}: FAILED: {e}")
        json.dump(scenes, open(scenes_path, "w"), indent=2, ensure_ascii=False)
