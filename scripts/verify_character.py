"""Generation-time character-consistency verification + bounded corrective retry.

Plugs into gen_images_ref.py: after each successful image generation for a scene
that involves a character_bible-tracked character, checks the result two ways:

  1. Discrete claims (checklist.claims) -- "does it have the fruit, not a hat" type
     yes/no questions, resolved from the character bible's critical_invariants +
     default_rules for that scene's costume variant.
  2. Face-closeup comparison (checklist.face_closeup_images) -- an OPEN-ENDED
     comparison against clean close-up reference photos, specifically to catch
     continuous/similarity-type drift (facial proportions, mouth-line weight,
     nose-mouth shading) that a discrete checklist cannot detect at all even
     when every discrete claim passes. This is the failure mode confirmed by
     direct user feedback on a real batch ("哪有这么重的鼻子跟嘴巴的那条线啊") --
     see the approved plan and character_bible.schema.md for the full story.

On failure, amends the ORIGINAL prompt (never a previously-amended one, to avoid
unbounded growth) with the specific failure reason(s) and regenerates, bounded by
correction_loop.decide() (vendored from img2threejs, unmodified pure-logic state
machine -- see that module's own docstring for the termination guarantee).

Public entry point: verify_and_maybe_retry(scene, out_path, checklist, generate_fn).
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.request

import config
import correction_loop
import per_feature
import image_hash

try:
    from PIL import Image
except ImportError:  # pragma: no cover - PIL is expected to be present; fail loud at call time instead
    Image = None

VERIFIER_MODEL = config.VERIFIER_MODEL
MAX_GEN_ATTEMPTS = config.MAX_GEN_ATTEMPTS
VERIFY_MODE = config.VERIFY_MODE

# Cross-scene circuit breaker: if the SAME (character_id, claim_id) fails on the
# FIRST attempt for this many distinct scenes within one process run, stop
# retrying that claim for the rest of the run -- a single scene's max_attempts
# doesn't protect against a systemically-wrong bible rule burning the whole
# batch's generation budget on doomed retries. Reset per-process (module-level
# state is fine: gen_images_ref.py runs one batch per process invocation).
SYSTEMIC_FAILURE_THRESHOLD = int(os.environ.get("SYSTEMIC_FAILURE_THRESHOLD", "3"))
_systemic_first_attempt_failures = {}  # (character_id, claim_id) -> set of scene numbers
_systemic_breaker_tripped = set()  # (character_id, claim_id) already circuit-broken


# ---------------------------------------------------------------------------
# Tier 1: cheap, deterministic, zero-token sanity + echo-detection + a coarse
# whole-frame style-drift proxy. See character_bible.schema.md for why this
# tier deliberately does NOT attempt to judge "right accessory in right
# place" -- that needs spatial localization pHash/CIEDE2000 don't have.
# ---------------------------------------------------------------------------

def _load_pixels(path):
    if Image is None:
        raise RuntimeError("Pillow (PIL) is required for verify_character's Tier-1 checks")
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    return w, h, list(im.getdata())


def _flatness(w, h, pixels, sample_stride=4, luma_threshold=6.0):
    """Fraction of horizontally-adjacent sampled pixel pairs with near-zero
    luma delta. Higher = flatter/more cartoon-like; lower = more continuous-
    gradient/photoreal-like. A coarse whole-frame statistic, not a localizer."""
    if w < 2 or h < 1:
        return 1.0
    flat = total = 0
    for y in range(0, h, sample_stride):
        row = y * w
        for x in range(0, w - 1, sample_stride):
            r1, g1, b1, _ = pixels[row + x]
            r2, g2, b2, _ = pixels[row + x + 1]
            l1 = 0.2126 * r1 + 0.7152 * g1 + 0.0722 * b1
            l2 = 0.2126 * r2 + 0.7152 * g2 + 0.0722 * b2
            total += 1
            if abs(l1 - l2) < luma_threshold:
                flat += 1
    return flat / total if total else 1.0


def tier1_check(candidate_path, reference_paths):
    """Returns a dict, never raises for a 'soft' finding -- only an unreadable/
    too-small file sets hard_fail."""
    result = {"hard_fail": None, "dims": None, "phash_vs_ref_max_sim": None,
              "flat_fraction": None, "style_drift_proxy": "none"}
    try:
        w, h, pixels = _load_pixels(candidate_path)
    except Exception as e:
        result["hard_fail"] = f"unreadable candidate image: {e}"
        return result
    result["dims"] = [w, h]
    if w < 64 or h < 64:
        result["hard_fail"] = f"suspiciously small image ({w}x{h})"
        return result

    cand_hash = image_hash.phash_from_image(w, h, pixels)
    sims = []
    for ref_path in reference_paths:
        try:
            rw, rh, rpixels = _load_pixels(ref_path)
            sims.append(image_hash.normalized_similarity(cand_hash, image_hash.phash_from_image(rw, rh, rpixels)))
        except Exception:
            continue
    if sims:
        result["phash_vs_ref_max_sim"] = round(max(sims), 4)
        if result["phash_vs_ref_max_sim"] > 0.97:
            result["hard_fail"] = ("candidate is a near-exact copy of a reference image "
                                    "(model likely echoed the input instead of generating a new scene)")

    flat_fraction = _flatness(w, h, pixels)
    result["flat_fraction"] = round(flat_fraction, 4)
    if flat_fraction < 0.25:
        result["style_drift_proxy"] = "possible-photoreal-drift"
    return result


# ---------------------------------------------------------------------------
# Tier 2: vision-model judge. Two distinct calls -- discrete claims (closed
# checklist) and face-closeup comparison (open-ended, produces a corrective
# description rather than a fixed verdict).
# ---------------------------------------------------------------------------

CLAIMS_SYSTEM_PROMPT = """You are a strict visual QA judge for an AI character-consistency pipeline. You are shown
reference images of a character's canonical design, then ONE candidate image freshly
generated for a specific video scene. The candidate is EXPECTED to differ from the
references in pose, camera angle, background, lighting, and action -- that is not a
defect. Judge ONLY the identity/costume/style traits named in the checklist.

For each claim, decide independently:
- "pass": clearly true in the candidate image.
- "fail": clearly false / contradicted in the candidate image.
- "uncertain": can't tell from this view (occluded, cropped, too small, ambiguous angle)
  -- do NOT guess pass or fail when the relevant region isn't clearly visible.

Respond with ONLY a JSON object, no prose, no markdown fences, exactly:
{"claims": [{"id": "<id>", "verdict": "pass"|"fail"|"uncertain", "reason": "<=25 words"}]}
One entry per input claim id, same order, no omissions, no extra ids."""

FACE_SYSTEM_PROMPT = """You are a strict visual QA judge comparing a character's face in a freshly-generated
image against reference close-up photos of that character's canonical face design. The
candidate's POSE, EXPRESSION, and CAMERA ANGLE are expected to differ from the
references -- judge only proportions, line weight, and shading style, not pose/expression.

Specifically compare: mouth line thickness/shape/color, the shading/contour at the
nose-to-mouth junction, eye shape and spacing, and overall facial proportions. If the
candidate's face is not clearly visible (too small, angled away, obscured), say so --
do not guess.

Respond with ONLY a JSON object, no prose, no markdown fences, exactly:
{"face_visible": bool, "deviates": bool, "deviation_description": "<=40 words"}
"deviates" is true only for a real, describable difference in proportion/line-weight/
shading -- NOT for pose/expression/lighting differences, which are expected and fine.
"deviation_description" must be empty when deviates is false; when true it must name
specifically what differs and in which direction (e.g. "the mouth line is noticeably
thicker and darker than the reference, which shows a thin soft curve") so it can be
used verbatim as a corrective instruction for regeneration."""


def _b64_image(path):
    with open(path, "rb") as f:
        data = f.read()
    ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
    if ext == "jpg":
        ext = "jpeg"
    return f"data:image/{ext};base64,{base64.b64encode(data).decode()}"


def _call_verifier(system_prompt, user_content, temperature=0.2, retries=2):
    body = {
        "model": VERIFIER_MODEL,
        "temperature": temperature,
        "max_tokens": 2000,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    req_data = json.dumps(body).encode()
    last_exc = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                f"{config.NEWAPI_URL}/v1/chat/completions",
                data=req_data,
                headers={"Authorization": f"Bearer {config.NEWAPI_KEY}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.loads(r.read().decode())
            content = resp["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(content)
        except Exception as e:
            last_exc = e
            if attempt < retries:
                time.sleep(3)
    raise RuntimeError(f"verifier call failed after {retries + 1} attempts: {last_exc}")


def _claims_call(candidate_path, ref_paths, claims, scene_num, prompt_excerpt, temperature=0.2):
    content = []
    for i, ref in enumerate(ref_paths):
        content.append({"type": "text", "text": f"Reference photo {i + 1} of {len(ref_paths)} (canonical design):"})
        content.append({"type": "image_url", "image_url": {"url": _b64_image(ref)}})
    content.append({"type": "text", "text": f"Candidate image for scene {scene_num}, generated from this "
                                              f"prompt: \"{prompt_excerpt[:400]}\""})
    content.append({"type": "image_url", "image_url": {"url": _b64_image(candidate_path)}})
    claims_json = json.dumps([{"id": c["id"], "text": c["text"], "tier": c["tier"]} for c in claims])
    content.append({"type": "text", "text": f"Claims to check (respond in this exact order, one verdict "
                                              f"per id):\n{claims_json}\n\nRespond with ONLY the JSON object "
                                              f"described in the system prompt."})
    return _call_verifier(CLAIMS_SYSTEM_PROMPT, content, temperature=temperature)


def _face_call(candidate_path, face_ref_paths, scene_num, temperature=0.2):
    content = []
    for i, ref in enumerate(face_ref_paths):
        content.append({"type": "text", "text": f"Canonical face reference {i + 1} of {len(face_ref_paths)}:"})
        content.append({"type": "image_url", "image_url": {"url": _b64_image(ref)}})
    content.append({"type": "text", "text": f"Candidate image, scene {scene_num} -- compare this character's "
                                              f"face against the references above:"})
    content.append({"type": "image_url", "image_url": {"url": _b64_image(candidate_path)}})
    return _call_verifier(FACE_SYSTEM_PROMPT, content, temperature=temperature)


def _claims_disagree_on_critical(a, b, critical_ids):
    va = {c["id"]: c["verdict"] for c in a["claims"]}
    vb = {c["id"]: c["verdict"] for c in b["claims"]}
    return any(va.get(cid) != vb.get(cid) for cid in critical_ids)


def tier2_verify_claims(candidate_path, ref_paths, claims, scene_num, prompt_excerpt):
    """Self-consistency sampling: 1 call in the common (clean pass) case, up to
    3 only when the first sample already looks like trouble on a critical claim."""
    if not claims:
        return {"claims": []}
    sample1 = _claims_call(candidate_path, ref_paths, claims, scene_num, prompt_excerpt, temperature=0.2)
    critical_ids = {c["id"] for c in claims if c["tier"] == "critical"}
    ambiguous = any(v["verdict"] in ("fail", "uncertain") for v in sample1["claims"] if v["id"] in critical_ids)
    if not ambiguous:
        return sample1
    sample2 = _claims_call(candidate_path, ref_paths, claims, scene_num, prompt_excerpt, temperature=0.6)
    votes = [sample1, sample2]
    if _claims_disagree_on_critical(sample1, sample2, critical_ids):
        votes.append(_claims_call(candidate_path, ref_paths, claims, scene_num, prompt_excerpt, temperature=0.6))
    return _majority_vote_claims(votes, claims)


def _majority_vote_claims(votes, claims):
    merged = []
    for c in claims:
        cid = c["id"]
        verdicts = [next((v["verdict"] for v in vote["claims"] if v["id"] == cid), "uncertain") for vote in votes]
        reasons = [next((v.get("reason", "") for v in vote["claims"] if v["id"] == cid), "") for vote in votes]
        counts = {"pass": verdicts.count("pass"), "fail": verdicts.count("fail"), "uncertain": verdicts.count("uncertain")}
        # ties break toward "uncertain" -- never toward a false pass.
        best = max(counts, key=lambda k: (counts[k], k != "pass"))
        if counts["pass"] == counts["fail"] and counts["pass"] > 0:
            best = "uncertain"
        reason = next((r for v, r in zip(verdicts, reasons) if v == best and r), reasons[0] if reasons else "")
        merged.append({"id": cid, "verdict": best, "reason": reason})
    return {"claims": merged}


# ---------------------------------------------------------------------------
# Retry driver
# ---------------------------------------------------------------------------

def amend_prompt(original_prompt, failed_items):
    """failed_items: [{"id","text","reason","tier"}, ...]. Always derives from
    the PRISTINE original prompt, never a previously-amended one, so repeated
    retries don't make the prompt grow unbounded."""
    if not failed_items:
        return original_prompt
    lines = ["CRITICAL CORRECTIONS -- the previous attempt failed these; fix explicitly:"]
    for item in failed_items:
        reason = f" (previous attempt: {item['reason']})" if item.get("reason") else ""
        lines.append(f"- REQUIRED: \"{item['text']}\"{reason}. Make this unambiguously true in the new image.")
    return original_prompt + "\n\n" + "\n".join(lines)


def _breaker_key(character_id, claim_id):
    return (character_id or "", claim_id)


def _record_first_attempt_failure(character_id, claim_id, scene_num):
    key = _breaker_key(character_id, claim_id)
    if key in _systemic_breaker_tripped:
        return True
    seen = _systemic_first_attempt_failures.setdefault(key, set())
    seen.add(scene_num)
    if len(seen) >= SYSTEMIC_FAILURE_THRESHOLD:
        _systemic_breaker_tripped.add(key)
        return True
    return False


def verify_and_maybe_retry(scene, out_path, checklist, generate_fn, max_attempts=None, log=print):
    """checklist: the dict returned by character_bible.critical_checklist_for(...)
    -- {"character_id","variant_id","claims","reference_images","face_closeup_images"}.
    generate_fn(prompt: str) -> bytes: caller's closure over its own generate();
    this module never duplicates the image-generation HTTP call.

    Mutates `scene` in place with verification_status/attempts/failed_claims/
    verification_history/verification_tier1, and returns it. VERIFY_MODE="off"
    short-circuits to verification_status="skipped" without any network calls.
    """
    if VERIFY_MODE == "off":
        scene["verification_status"] = "skipped"
        return scene

    max_attempts = max_attempts or MAX_GEN_ATTEMPTS
    claims = checklist.get("claims", [])
    face_images = checklist.get("face_closeup_images", [])
    reference_images = checklist.get("reference_images", [])
    character_id = checklist.get("character_id")
    scene_num = scene.get("scene")
    original_prompt = scene["image_prompt"]

    if VERIFY_MODE == "critical-only" and not any(c["tier"] == "critical" for c in claims) and not face_images:
        scene["verification_status"] = "skipped"
        return scene

    history = []
    attempt = 0
    try:
        while True:
            attempt += 1
            tier1 = tier1_check(out_path, reference_images)
            scene["verification_tier1"] = tier1

            failed_items = []
            uncertain_items = []
            claims_result = {"claims": []}
            if tier1["hard_fail"] is None and claims:
                claims_result = tier2_verify_claims(out_path, reference_images, claims, scene_num, original_prompt)
                for c in claims_result["claims"]:
                    orig = next((x for x in claims if x["id"] == c["id"]), {"text": c["id"], "tier": "important"})
                    if c["verdict"] == "fail":
                        if orig.get("tier") == "critical" and attempt == 1:
                            if _record_first_attempt_failure(character_id, c["id"], scene_num):
                                log(f"scene{scene_num}: systemic failure -- ({character_id}, {c['id']}) failed "
                                    f"first-attempt on >= {SYSTEMIC_FAILURE_THRESHOLD} scenes this run, "
                                    f"check the character bible's rule for this claim")
                        failed_items.append({"id": c["id"], "text": orig["text"], "reason": c.get("reason", ""),
                                              "tier": orig.get("tier", "important")})
                    elif c["verdict"] == "uncertain":
                        # An "uncertain" verdict means the judge genuinely can't see the
                        # relevant region this shot (too small/distant/occluded/angled
                        # away) -- confirmed on real production data (a wide/distant
                        # snow-battle video) that this is common and, critically, NOT
                        # something a corrective prompt amendment can fix: the amendment
                        # can't change the shot's camera distance/framing, which is what
                        # made the claim unjudgeable in the first place. Forcing a retry
                        # here previously burned generations on scenes that could never
                        # resolve to "verified" no matter how many attempts ran. Record
                        # for human visibility (uncertain_items) instead of gating on it.
                        uncertain_items.append({"id": c["id"], "text": orig["text"], "reason": c.get("reason", ""),
                                                 "tier": orig.get("tier", "important")})

            face_result = None
            if tier1["hard_fail"] is None and face_images:
                face_result = _face_call(out_path, face_images, scene_num)
                if face_result.get("face_visible") and face_result.get("deviates"):
                    failed_items.append({"id": "face_closeup_fidelity",
                                          "text": "face proportions/line-weight/shading must match the canonical face reference",
                                          "reason": face_result.get("deviation_description", ""), "tier": "critical"})

            feature_targets = [{"id": c["id"], "tier": c["tier"]} for c in claims]
            feature_scores = {}
            for c in claims_result["claims"]:
                # "uncertain" scores as a pass (1.0), not missing (None): see the
                # uncertain_items branch above -- per_feature.py treats a None/missing
                # score on a critical target as a gating failure, which would force the
                # exact same can't-possibly-succeed retry this whole branch exists to
                # avoid. An unconfirmable claim is reported (uncertain_items), not gated.
                feature_scores[c["id"]] = {"pass": 1.0, "fail": 0.0, "uncertain": 1.0}[c["verdict"]]
            if face_images:
                # Distinct id from any bible claim named "face_fidelity" (lulu/grass_cow/
                # daodun/bibilabu's critical_invariants all use that id for the prompt-text
                # reminder) -- sharing an id would make this dedicated check silently
                # overwrite that claim's own verdict in feature_scores (last-write-wins)
                # and double-count as two "missing"/"below" entries for the same defect.
                feature_targets.append({"id": "face_closeup_fidelity", "tier": "critical"})
                if face_result is None:
                    feature_scores["face_closeup_fidelity"] = 1.0  # tier1 hard_fail short-circuited; don't fail on this alone
                elif not face_result.get("face_visible"):
                    # The face genuinely isn't in frame this shot (back view, obscured,
                    # too small/distant, angled away) -- FACE_SYSTEM_PROMPT explicitly
                    # tells the judge to report this rather than guess. This is a normal,
                    # common outcome for action/wide shots, NOT a defect: scoring it as
                    # None (missing) would mark a CRITICAL feature missing and force a
                    # corrective retry that can't possibly succeed (the fix would require
                    # changing the shot's camera framing entirely, which a text amendment
                    # to the prompt cannot reliably do) -- confirmed on real production
                    # data, where a pure back-view shot got flagged_for_review and burned
                    # an extra generation for exactly this reason before this fix.
                    feature_scores["face_closeup_fidelity"] = 1.0
                else:
                    feature_scores["face_closeup_fidelity"] = 0.0 if face_result.get("deviates") else 1.0

            if tier1["hard_fail"]:
                gate = {"passed": False, "features": [], "defects": [f"tier1:{tier1['hard_fail']}"]}
                gating_defects = gate["defects"]
            else:
                gate = per_feature.evaluate_features(feature_targets, feature_scores)
                # Only GATING (critical/mustPass) misses should drive the retry
                # loop -- per_feature.py's own contract is "non-gating below-
                # threshold features are reported but do not fail the pass".
                # correction_loop.decide()'s SUCCESS condition requires an empty
                # defectTags list, so feeding it gate["defects"] (which includes
                # non-gating misses too, e.g. an "important"-tier no_stray_text
                # claim) would force a retry even when gate["passed"] is True --
                # silently contradicting per_feature's gating semantics and
                # burning an extra generation on a claim the design says
                # shouldn't gate at all.
                gating_defects = [f"{f['status']}:{f['id']}" for f in gate["features"]
                                   if f["gating"] and f["status"] != "ok"]

            ok_count = sum(1 for f in gate["features"] if f["status"] == "ok")
            fidelity = 1.0 if gate["passed"] else (ok_count / max(1, len(gate["features"])) if gate["features"] else 0.0)
            history.append({"fidelity": fidelity, "defectTags": sorted(gating_defects), "reverted": False})

            scene["verification_attempts"] = attempt
            scene["verification_model"] = VERIFIER_MODEL
            scene.setdefault("verification_history", []).append({
                "attempt": attempt, "fidelity": round(fidelity, 4),
                "defect_tags": sorted(gate.get("defects", [])),
                "prompt_used": scene["image_prompt"],
            })

            decision = correction_loop.decide(history, target_fidelity=1.0, max_iter=max_attempts, min_delta=0.0)
            if decision["stop"]:
                scene["verification_status"] = "verified" if gate["passed"] else "flagged_for_review"
                scene["verification_action"] = decision["action"]
                scene["failed_claims"] = failed_items
                scene["uncertain_claims"] = uncertain_items
                log(f"scene{scene_num}: verification {scene['verification_status']} "
                    f"({attempt} attempt(s), action={decision['action']})")
                return scene

            log(f"scene{scene_num}: attempt {attempt} failed ({[i['id'] for i in failed_items]}), "
                f"regenerating with corrections")
            scene["image_prompt"] = amend_prompt(original_prompt, failed_items)
            data = generate_fn(scene["image_prompt"])
            with open(out_path, "wb") as f:
                f.write(data)
    except Exception as e:
        scene["verification_status"] = "error"
        scene["verification_error"] = str(e)
        log(f"scene{scene_num}: verification errored, leaving image as-is: {e}")
        return scene
