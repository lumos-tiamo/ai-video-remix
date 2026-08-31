#!/usr/bin/env python3
"""Drive the full Stage-1 chain (Mode A, hardcoded-subtitle source) for one
老胡说说 remix folder: extract burned-in subs -> write_scenes.py -> gen_tts.py
(edge backend) -> gen_srt.py. Wraps the individual scripts so callers don't
have to hand-quote folder names full of Chinese punctuation.

Usage: run_stage1.py <folder_glob_prefix> <target_seconds> <style_notes_path> [style_prefix_path]
  folder_glob_prefix: e.g. "2" to match 老胡说说/2.* (must resolve to exactly one dir)
  target_seconds: measured source video duration (ffprobe), not guessed
  style_notes_path: path to a .txt file with the style_notes content
  style_prefix_path: optional -- path to a .txt file with a shared style-lock
    string. When given, the writer model is NOT asked to retype this string
    into every image_prompt (that was blowing up output length on dense
    transcripts and truncating the JSON response); instead it's prepended to
    every scene's image_prompt in code after generation, via
    prepend_style_prefix.py.

Skips extraction if <folder>/transcript.txt already exists (so this is
re-runnable after a manual transcript fix without re-paying for OCR).
"""
import glob, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))  # project root
sys.path.insert(0, HERE)


def resolve_folder(prefix):
    matches = glob.glob(os.path.join(ROOT, "老胡说说", f"{prefix}.*"))
    matches = [m for m in matches if os.path.isdir(m)]
    if len(matches) != 1:
        raise SystemExit(f"expected exactly 1 folder matching '{prefix}.*', found {matches}")
    return matches[0]


def find_source_mp4(folder):
    mp4s = [f for f in glob.glob(os.path.join(folder, "*.mp4"))]
    if len(mp4s) != 1:
        raise SystemExit(f"expected exactly 1 source mp4 in {folder}, found {mp4s}")
    return mp4s[0]


def run_module(script_name, argv):
    path = os.path.join(HERE, script_name)
    sys.argv = [script_name] + argv
    g = {"__name__": "__main__", "__file__": path}
    exec(compile(open(path).read(), path, "exec"), g)


if __name__ == "__main__":
    prefix, target_seconds, style_notes_path = sys.argv[1], sys.argv[2], sys.argv[3]
    style_prefix_path = sys.argv[4] if len(sys.argv) > 4 else None
    folder = resolve_folder(prefix)
    print(f"folder: {folder}")
    mp4 = find_source_mp4(folder)
    print(f"source video: {mp4}")

    transcript_path = os.path.join(folder, "transcript.txt")
    if os.path.exists(transcript_path):
        print(f"transcript.txt already exists, skipping extraction: {transcript_path}")
    else:
        run_module("extract_hardcoded_subs.py", [mp4, folder])

    style_notes = open(style_notes_path, encoding="utf-8").read()
    scenes_path = os.path.join(folder, "scenes.json")
    run_module("write_scenes.py", [scenes_path, target_seconds, transcript_path, style_notes])

    if style_prefix_path:
        run_module("prepend_style_prefix.py", [scenes_path, style_prefix_path])

    audio_dir = os.path.join(folder, "audio")
    run_module("gen_tts.py", [scenes_path, audio_dir])

    srt_path = os.path.join(folder, "captions.srt")
    run_module("gen_srt.py", [scenes_path, srt_path])

    scenes = json.load(open(scenes_path))
    total = sum(s["tts_duration"] for s in scenes)
    print(f"\nDONE: {folder}\nscenes={len(scenes)} target={target_seconds}s actual_tts_total={total:.1f}s")
