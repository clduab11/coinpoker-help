#!/usr/bin/env python3
"""Loopback Laya Vision server for coinpoker-help (the sole live perception backend).

Subcommands:
  serve  (default)  serve the dashboard, then verify/load the pinned model asynchronously
  fetch             download the pinned base checkpoint (HF revision) into HF_HOME, then verify
  verify            check runtime package versions, laya commit and every pinned file's SHA-256

API (loopback only, concurrent HTTP with one GPU admission slot):
  GET  /                 read-only local dashboard
  GET  /api/state        bounded sanitized Rust-feed/model status snapshot
  GET  /api/reference    locally bundled researched study reference, not live recommendations
  GET  /v1/models        -> {"object":"list","data":[{"id": alias, "object":"model", "meta":{...}}]}
  POST /v1/laya/predict  -> body {model, pass, note, layout, glyph_style?, images_png_b64:[...],
                                  questions:{qid:{type, instructions, criteria?}}}
       layout "full"/"slots": every image goes into one Laya state (one 64-token tile each).
       layout "glyphs": exactly one amount crop; scripts/laya_prep.segment_glyphs splits it into
       n <= 8 glyph images; only g1..gn are answered; the response carries segments {n, overflow}.
       response {model, pass, answers:{qid:{type, choice?, probabilities?, noul?, confidence,
                 truncated}}, segments?, timing_ms:{decode, prep, predict}}

Hygiene: never logs or echoes request content; errors are {"error": "<code>"}; bounded body,
image and question limits; images are never written to disk. torch / laya / PIL / numpy are
imported lazily so the request validation stays stdlib-only and testable.
"""

import argparse
import base64
import binascii
import datetime as dt
import hashlib
import json
import math
import os
import re
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import laya_dashboard as dashboard

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS)
ROOT = Path(REPO)
PINS_PATH = os.path.join(SCRIPTS, "laya-pins.json")

HOST = "127.0.0.1"
MAX_BODY = 8 * 1024 * 1024
MAX_QUESTIONS = 64
MAX_OPTIONS = 64
MAX_IMAGES = 8
MAX_INSTRUCTIONS = 2000
MAX_OPTION_TEXT = 200
MAX_NOTE = 500
MAX_IMAGE_PIXELS = 4096 * 4096
MAX_REFERENCE_EDGE = 16384
MAX_GLYPHS = 8
MAX_GLYPH_BATCH = 6
ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")
LAYOUTS = ("full", "slots", "glyphs")
GLYPH_STYLES = ("white", "gold")
PNG_SIG = b"\x89PNG\r\n\x1a\n"
SOCKET_TIMEOUT = 10
PORT = 18090
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
ACCEPTANCE_PASSES = frozenset({"p0_full", "p2_board", "p3_pot",
                              *("p5_seat_" + str(n) + "_stack" for n in range(1, 7))})
STACK_PASSES = frozenset("p5_seat_%d_stack" % n for n in range(1, 7))
WAGER_PASSES = frozenset("p6_seat_%d_wager" % n for n in range(1, 7))
SCENE_PASSES = frozenset("p7_seat_%d_scene" % n for n in range(1, 7))
WAGER_NOTE = "Observed per-seat visible wager glyphs; not stack, street contribution or call cost."
SCENE_NOTE = "Observed per-seat visible scene only; not names, hidden cards, hand roster or actions."
SCENE_QUESTIONS = {
    "occupied": ("Is this physical seat visibly occupied or open?", ["occupied", "open", "unknown"]),
    "status": ("Read only the visible participation status of this seat.", ["active", "folded", "all_in", "sitting_out", "unknown"]),
    "badge": ("Read only this seat's visible badge, or none if visibly absent.", ["none", "fold", "check", "call", "bet", "raise", "all_in", "small_blind", "big_blind", "unknown"]),
    "dealer": ("Is the dealer button visibly at this seat?", ["dealer_here", "not_dealer", "unknown"]),
    "small_blind": ("Is the small-blind marker visibly at this seat?", ["small_blind_here", "not_small_blind", "unknown"]),
    "big_blind": ("Is the big-blind marker visibly at this seat?", ["big_blind_here", "not_big_blind", "unknown"]),
    "acting": ("Does visible acting evidence identify this seat as the current actor?", ["yes", "no", "unknown"]),
}
MAX_ACCEPTANCE_REPORT = 64 * 1024


class RequestError(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status = status
        self.code = code


def load_pins(path=PINS_PATH):
    with open(path, encoding="utf-8") as f:
        pins = json.load(f)
    if pins.get("format") != 1:
        raise ValueError("unsupported laya-pins format")
    return pins


def png_size(data):
    """(width, height) from a PNG header without decoding; raises RequestError for anything else."""
    if len(data) < 24 or data[:8] != PNG_SIG or data[12:16] != b"IHDR":
        raise RequestError(400, "invalid-image")
    w, h = struct.unpack(">II", data[16:24])
    if w == 0 or h == 0 or w * h > MAX_IMAGE_PIXELS:
        raise RequestError(400, "image-too-large" if w * h > MAX_IMAGE_PIXELS else "invalid-image")
    return w, h


def validate_request(body, alias):
    """Validate a decoded JSON body. Returns (pass_id, note, layout, style, [png bytes], questions)."""
    if not isinstance(body, dict):
        raise RequestError(400, "malformed")
    if body.get("model") != alias:
        raise RequestError(404, "unknown-model")
    pid = body.get("pass")
    if not isinstance(pid, str) or not ID_RE.match(pid):
        raise RequestError(400, "malformed")
    note = body.get("note", "")
    if not isinstance(note, str) or len(note) > MAX_NOTE:
        raise RequestError(400, "malformed")
    layout = body.get("layout")
    if layout not in LAYOUTS:
        raise RequestError(400, "malformed")
    style = body.get("glyph_style")
    if layout == "glyphs" and style not in GLYPH_STYLES:
        raise RequestError(400, "malformed")
    imgs = body.get("images_png_b64")
    if not isinstance(imgs, list) or not 1 <= len(imgs) <= MAX_IMAGES:
        raise RequestError(400, "malformed")
    if layout in ("full", "glyphs") and len(imgs) != 1:
        raise RequestError(400, "malformed")
    raw = []
    for s in imgs:
        if not isinstance(s, str):
            raise RequestError(400, "malformed")
        try:
            data = base64.b64decode(s.encode("ascii"), validate=True)
        except (binascii.Error, UnicodeEncodeError, ValueError):
            raise RequestError(400, "invalid-image")
        png_size(data)
        raw.append(data)
    qs = body.get("questions")
    if not isinstance(qs, dict) or not 1 <= len(qs) <= MAX_QUESTIONS:
        raise RequestError(400, "malformed")
    out = {}
    for qid, q in qs.items():
        if not isinstance(qid, str) or not ID_RE.match(qid) or not isinstance(q, dict):
            raise RequestError(400, "malformed")
        typ = q.get("type")
        ins = q.get("instructions")
        if typ not in ("choice", "noul") or not isinstance(ins, str) or not 0 < len(ins) <= MAX_INSTRUCTIONS:
            raise RequestError(400, "malformed")
        d = {"type": typ, "instructions": ins}
        if typ == "choice":
            crit = q.get("criteria")
            if (isinstance(crit, list) and crit and all(isinstance(x, list) and len(x) == 2 for x in crit)):
                # ordered [label, description] pairs: the option order is part of Laya's input
                labels = [x[0] for x in crit]
                if len(set(map(str, labels))) != len(labels):
                    raise RequestError(400, "malformed")
                crit = {x[0]: x[1] for x in crit}
            if isinstance(crit, dict):
                items = list(crit.items())
                ok = all(isinstance(k, str) and isinstance(v, str) and 0 < len(k) <= MAX_OPTION_TEXT
                         and len(v) <= MAX_OPTION_TEXT for k, v in items)
            elif isinstance(crit, list):
                items = crit
                ok = all(isinstance(k, str) and 0 < len(k) <= MAX_OPTION_TEXT for k in items)
            else:
                ok, items = False, []
            if not ok or not 2 <= len(items) <= MAX_OPTIONS:
                raise RequestError(400, "malformed")
            d["criteria"] = crit
        out[qid] = d
    if layout == "glyphs" and set(out) - {"g%d" % k for k in range(1, MAX_GLYPHS + 1)}:
        raise RequestError(400, "malformed")
    return pid, note, layout, style, raw, out


def shape_answers(result, questions):
    """Reduce laya answers to the wire format (no provenance, no action block)."""
    out = {}
    for qid in questions:
        a = result["answers"][qid]
        r = {"type": a["type"], "confidence": a.get("confidence"), "truncated": bool(a.get("truncated"))}
        if a["type"] == "choice":
            r["choice"] = a["choice"]
            r["probabilities"] = a["probabilities"]
        else:
            r["noul"] = a["noul"]
        out[qid] = r
    return out


def load_acceptance_floors(pins):
    """Read the separately pinned fitted report; this is not quality approval."""
    model = pins.get("model") if isinstance(pins, dict) else None
    ft = model.get("finetuned") if isinstance(model, dict) else None
    if not isinstance(ft, dict) or not isinstance(ft.get("files"), list):
        raise ValueError("acceptance-report-unpinned")
    filename = ft.get("acceptance_file")
    entries = [item for item in ft["files"] if isinstance(item, dict) and item.get("path") == filename]
    if filename != "calibration.json" or len(entries) != 1:
        raise ValueError("acceptance-report-unpinned")
    expected = entries[0]
    size, digest = expected.get("size"), expected.get("sha256")
    checkpoint = ft.get("path")
    if (type(size) is not int or not 0 < size <= MAX_ACCEPTANCE_REPORT
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not isinstance(checkpoint, str) or not checkpoint
            or Path(checkpoint).is_absolute() or ".." in Path(checkpoint).parts):
        raise ValueError("acceptance-report-invalid")
    root = Path(REPO).resolve()
    base = (root / checkpoint).resolve()
    path = (base / filename).resolve()
    if (base != root / checkpoint or not base.is_relative_to(root) or path != base / filename
            or path.stat().st_size != size):
        raise ValueError("acceptance-report-invalid")
    with path.open("rb") as stream:
        data = stream.read(MAX_ACCEPTANCE_REPORT + 1)
    if len(data) != size:
        raise ValueError("acceptance-report-invalid")
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("acceptance-report-digest-mismatch")

    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("acceptance-report-invalid")
            result[key] = value
        return result

    def finite(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("acceptance-report-invalid")
        return value

    report = json.loads(data, parse_constant=dashboard._reject_constant, parse_float=finite, object_pairs_hook=unique)
    floors = report.get("thresholds_per_pass") if isinstance(report, dict) else None
    if (not isinstance(report, dict) or report.get("ckpt") != checkpoint
            or not isinstance(floors, dict) or set(floors) != ACCEPTANCE_PASSES
            or any(type(value) not in (int, float) or not 0 <= value <= 1 or not math.isfinite(value)
                    for value in floors.values())):
        raise ValueError("acceptance-report-invalid")
    return {key: float(value) for key, value in floors.items()}


def load_seat_registry(pins, kind):
    """Optional per-seat evidence, absent for it1. Never caller or global approval."""
    ft = pins["model"].get("finetuned") or {}
    if kind not in ("wager", "scene"):
        raise ValueError("invalid registry kind")
    prefix = "p6" if kind == "wager" else "p7"
    name = ft.get(kind + "_registry")
    if name is None:
        return {}
    files = ft.get("files", {})
    if not isinstance(name, str) or name not in files:
        raise ValueError("wager-registry-not-pinned")
    base = (ROOT / ft["path"]).resolve()
    if not base.is_relative_to(ROOT.resolve()):
        raise ValueError("wager-registry-path")

    def read_pinned(filename):
        path = (base / filename).resolve()
        if not path.is_relative_to(base) or path.stat().st_size > MAX_BODY:
            raise ValueError("wager-evidence-path")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != files[filename]:
            raise ValueError("wager-evidence-hash")
        return json.loads(raw.decode("utf-8"), parse_constant=dashboard._reject_constant)

    registry = read_pinned(name)
    alias = pins["server"]["alias"]
    if (not isinstance(registry, dict) or type(registry.get("version")) is not int
        or registry["version"] != 1 or registry.get("model_alias") != alias
        or not isinstance(registry.get("passes"), list) or len(registry["passes"]) > 6):
        raise ValueError("wager-registry-schema")
    model_hash = files.get("model.safetensors")
    if not isinstance(model_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", model_hash) or set(model_hash) == {"0"}:
        raise ValueError("wager-model-not-pinned")
    candidate_hash = hashlib.sha256(json.dumps(
        {key: value for key, value in files.items()
         if key not in (ft.get("wager_registry"), ft.get("scene_registry"))},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    qualified, seen = {}, set()
    for entry in registry["passes"]:
        if not isinstance(entry, dict) or type(entry.get("seat")) is not int:
            raise ValueError("wager-registry-seat")
        seat, pid = entry["seat"], entry.get("pass")
        if not 1 <= seat <= 6 or pid != "%s_seat_%d_%s" % (prefix, seat, kind) or seat in seen:
            raise ValueError("wager-registry-seat")
        seen.add(seat)
        floor, region = entry.get("fitted_floor"), entry.get("region")
        valid = (entry.get("trained_candidate") is True and entry.get("held_out_approved") is True
                 and entry.get("human_verified") is True
                 and entry.get("provenance") == "observation-only-calibrated-pass"
                 and type(floor) in (int, float) and 0 < floor <= 1 and math.isfinite(floor)
                 and entry.get("candidate_sha256") == candidate_hash
                 and entry.get("model_sha256") == model_hash
                 and isinstance(region, dict) and region.get("id") == "seat_%d_%s" % (seat, kind))
        if not valid:
            continue
        dimensions, bounds = region.get("reference_dimensions"), region.get("bounds")
        if (not isinstance(dimensions, list) or len(dimensions) != 2
            or any(type(n) is not int or not 2 <= n <= MAX_REFERENCE_EDGE for n in dimensions)
            or not isinstance(bounds, list) or len(bounds) != 4 or any(type(n) is not int for n in bounds)
            or not 0 <= bounds[0] < bounds[2] <= dimensions[0]
            or not 0 <= bounds[1] < bounds[3] <= dimensions[1]):
            continue
        proof_names = [key for key, digest in files.items()
                       if key != name and digest == entry.get("capability_evidence_sha256")]
        if len(proof_names) != 1:
            continue
        proof = read_pinned(proof_names[0])
        if (not isinstance(proof, dict) or type(proof.get("schema_version")) is not int or proof.get("schema_version") != 1
            or proof.get("human_verification") != "VERIFIED" or proof.get("model_sha256") != model_hash
            or not isinstance(proof.get("passes"), dict)):
            continue
        metrics = proof["passes"].get(pid, {})
        if (not isinstance(metrics, dict) or type(metrics.get("fitted_floor")) not in (int, float)
            or metrics.get("fitted_floor") != floor
            or metrics.get("session_grouped") is not True
            or metrics.get("calibration_separate_from_held_out") is not True):
            continue
        def passes_target(m, coverage, recall=False):
            return (isinstance(m, dict) and type(m.get("precision")) in (int, float) and .99 <= m["precision"] <= 1
                    and type(m.get("coverage")) in (int, float) and coverage <= m["coverage"] <= 1
                    and type(m.get("confident_items")) is int and m["confident_items"] > 0
                    and type(m.get("positive_opportunities")) is int and m["positive_opportunities"] >= 20
                    and (not recall or type(m.get("recall")) in (int, float) and .95 <= m["recall"] <= 1))
        if kind == "wager":
            if not passes_target(metrics, .85):
                continue
        else:
            fields = metrics.get("fields", {})
            if not isinstance(fields, dict) or not all(passes_target(fields.get(field),
                .85 if field in ("status", "badge") else .95, field == "acting") for field in SCENE_QUESTIONS):
                continue
        safe = {key: entry[key] for key in ("seat", "pass", "region", "fitted_floor", "trained_candidate",
            "candidate_sha256", "model_sha256", "capability_evidence_sha256", "held_out_approved",
            "human_verified", "provenance")}
        safe["fitted_floor"] = float(floor)
        qualified[pid] = {**safe, "registry_version": 1, "model_alias": alias}
    return qualified


def load_wager_registry(pins):
    return load_seat_registry(pins, "wager")


def load_scene_registry(pins):
    return load_seat_registry(pins, "scene")


class Engine:
    """Lazy GPU side: decode, prepare, predict. Replaced by a fake in tests."""

    def __init__(self, pins, batch_size=32):
        self.pins = pins
        self.batch_size = batch_size
        self.acceptance_floors = load_acceptance_floors(pins)
        self.wager_registry = load_wager_registry(pins)
        self.scene_registry = load_scene_registry(pins)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
        import warnings

        warnings.filterwarnings("ignore")
        sys.path.insert(0, SCRIPTS)
        import laya  # noqa: F401
        from laya.calibration import Calibration
        import laya_prep

        self.prep = laya_prep
        ft = pins["model"]["finetuned"]
        path = os.path.join(REPO, ft["path"])
        self.agent = laya.load_vlm(path, device="cuda", dtype=pins["server"].get("dtype", "bf16"))
        cal = ft.get("calibration_file")
        self.calibration = Calibration.load(os.path.join(path, cal)) if cal else None

    def decode(self, raw):
        import io
        from PIL import Image

        out = []
        for data in raw:
            im = Image.open(io.BytesIO(data))
            im.load()
            out.append(im.convert("RGB"))
        return out

    def predict(self, images, note, questions):
        import torch

        res = self.agent.predict({"images": images, "note": note}, questions, n_permutations=1,
                                 batch_size=self.batch_size, calibration=self.calibration)
        torch.cuda.synchronize()
        return res

    def predict_batch(self, samples):
        """Collate compatible question rows, without changing their original states."""
        import numpy as np
        import torch
        from laya import vlm

        agent = self.agent
        if self.calibration is not None:
            self.calibration.check(vlm.checkpoint_identity(agent))
        temperatures = vlm.resolve_temperature(None, self.calibration)
        rows, definitions, prefixes, pixels, masks = [], [], [], [], []
        with torch.no_grad():
            for sample_index, (images, note, questions) in enumerate(samples):
                state = {"images": images, "note": note}
                prefix = vlm.vlm_prefix(agent.processor, images, agent.prep)
                if prefix["raw_images"] is not None:
                    pv, pam = agent.prep.pixel_values(prefix["raw_images"], device=agent.device,
                                                      dtype=agent._torch_dtype())
                else:
                    pv = prefix["pixel_values"].to(agent.device, agent._torch_dtype())
                    pam = prefix["pixel_attention_mask"].to(agent.device)
                pixels.append(pv)
                masks.append(pam)
                prefixes.append(prefix["n_images"])
                for qid, question in questions.items():
                    internal = agent._to_internal(question)
                    item = vlm.build_vlm_inputs(agent.processor, state, internal,
                        agent.cfg.get("max_len", 1024), agent.cfg.get("head_max_len", 256), prefix=prefix)
                    options = len(vlm.render_options(internal))
                    if len(item["markers"]) != options:
                        raise ValueError("batch-question-invalid")
                    item["qtype"] = vlm.QTYPES[internal["t"]]
                    item["sample_index"] = sample_index
                    rows.append(item)
                    definitions.append((sample_index, qid, internal,
                                        vlm.truncation_answer(item["truncation"], internal)))
            # One bounded image-encoder battery; no concatenated multi-seat prompt.
            all_pixels, all_masks = torch.cat(pixels), torch.cat(masks)
            encoded = []
            for offset in range(0, len(all_pixels), self.batch_size):
                encoded.append(agent.model.encode_images(all_pixels[offset:offset+self.batch_size],
                                                        all_masks[offset:offset+self.batch_size]))
            image_features = torch.cat(encoded)
            starts = [0]
            for count in prefixes:
                starts.append(starts[-1] + count)
            logits = []
            for offset in range(0, len(rows), self.batch_size):
                chunk = rows[offset:offset+self.batch_size]
                batch = vlm.collate_vlm(chunk, agent.processor.tokenizer.pad_token_id, with_pixels=False)
                features = torch.cat([image_features[starts[r["sample_index"]]:starts[r["sample_index"]+1]]
                                      for r in chunk])
                args = [batch[k].to(agent.device) for k in
                        ("input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype")]
                scored, _ = agent.model(*args, image_hidden_states=features,
                                       option_span=batch["option_span"].to(agent.device))
                logits.extend(scored.float().cpu().numpy())
            torch.cuda.synchronize()
        output = [{"answers": {}} for _ in samples]
        for (sample_index, qid, question, truncated), scored in zip(definitions, logits):
            options = list(question["crit"])
            scale = temperatures.get(vlm.QTYPES[question["t"]],
                                     agent._checkpoint_temperature(vlm.QTYPES[question["t"]], len(options)))
            z = np.asarray(scored[:len(options)], dtype=np.float64) / max(1e-3, float(scale))
            probabilities = np.exp(z-z.max())
            probabilities /= probabilities.sum()
            answer = {"type": "choice", "choice": options[int(probabilities.argmax())],
                      "probabilities": {key: round(float(p), 4) for key, p in zip(options, probabilities)},
                      "confidence": round(vlm.confidence_from_probs(probabilities, len(options)), 4)}
            if truncated:
                answer["truncated"] = truncated
            output[sample_index]["answers"][qid] = answer
        return output


def answer_diagnostics(pid, answers, floor):
    """Private closed-vocabulary score decisions; never raw caller prose or admission."""
    allowed_ids = {"screen_kind", "hero_seat_index", "game_phase", "action_on_hero", "n_seats",
                   "ev_table_layout", "ev_readable", "ev_board_area", "ev_pot", "ev_seat_controls",
                   "ev_hero_cards", "ev_action_controls", "ev_consistent"}
    if pid in SCENE_PASSES:
        allowed_ids.update(SCENE_QUESTIONS)
    labels = {"poker_table", "lobby", "unknown", "unreadable", "not_seated", "preflop", "flop",
              "turn", "river", "showdown", "no_card", "not_a_character", "clubs", "diamonds",
              "hearts", "spades", ".", ",", "10", "J", "Q", "K", "A", "T",
              *(str(n) for n in range(10)), *("seat_%d" % n for n in range(1, 7))}
    if pid in SCENE_PASSES:
        labels.update(label for _, choices in SCENE_QUESTIONS.values() for label in choices)
    safe = {}
    for qid, answer in answers.items():
        if (qid not in allowed_ids and not re.fullmatch(r"g[1-8]|board_[1-5]_(rank|suit)", qid)):
            continue
        value = answer.get("choice")
        if answer["type"] == "choice":
            if value not in labels:
                continue
            score = answer["probabilities"][value]
        else:
            value = answer["noul"] >= 0.5
            score = answer["noul"] if value else 1-answer["noul"]
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            continue
        reason = ("truncated" if answer["truncated"] else "floor-unavailable" if floor is None else
                  "below-fitted-floor" if score < floor else
                  "unknown-answer" if value in ("unknown", "unreadable", "not_a_character") else None)
        safe[qid] = {"v": value, "p": score, "truncated": answer["truncated"],
                     "effective_fitted_floor": floor, "status": "rejected" if reason else "accepted",
                     "reason": reason, "score_only_not_admission": True}
    return safe


@lru_cache(maxsize=1)
def wager_questions():
    path = ROOT / "crates/ingest/assets/laya/question-set.json"
    manifest = json.loads(path.read_text(encoding="utf-8"), parse_constant=dashboard._reject_constant)
    source = next(p for p in manifest["passes"] if p["id"] == "p5_seat_1_stack")
    return {q["id"]: {"type": q["type"], "instructions": q["instructions"],
                      "criteria": {label: q["criteria"][label] for label in q["option_order"]}}
            for q in source["questions"]}


def handle_predict(engine, alias, body_bytes, log_fn=None):
    """Pure request handling (testable with a fake engine). Returns (status, payload dict)."""
    try:
        body = json.loads(body_bytes.decode("utf-8"), parse_constant=dashboard._reject_constant)
    except (ValueError, UnicodeDecodeError):
        return 400, {"error": "malformed"}
    try:
        pid, note, layout, style, raw, questions = validate_request(body, alias)
    except RequestError as e:
        return e.status, {"error": e.code}
    floors = getattr(engine, "acceptance_floors", None)
    floor = floors.get(pid) if pid != "doctor_probe" and isinstance(floors, dict) else None
    wager_capability = None
    scene_capability = None
    if pid in WAGER_PASSES:
        registry = getattr(engine, "wager_registry", {})
        wager_capability = registry.get(pid) if isinstance(registry, dict) else None
        if wager_capability is None:
            return 503, {"error": "wager-capability-unavailable"}
        if (json.dumps(body.get("wager_capability"), sort_keys=True, separators=(",", ":"))
            != json.dumps(wager_capability, sort_keys=True, separators=(",", ":"))
            or layout != "glyphs" or style != "white"):
            return 400, {"error": "wager-capability-mismatch"}
        try:
            correct_questions = wager_questions()
        except (OSError, ValueError, KeyError, StopIteration):
            return 503, {"error": "wager-template-unavailable"}
        if note != WAGER_NOTE or questions != correct_questions:
            return 400, {"error": "wager-template-mismatch"}
        floor = wager_capability["fitted_floor"]
    if pid in SCENE_PASSES:
        registry = getattr(engine, "scene_registry", {})
        scene_capability = registry.get(pid) if isinstance(registry, dict) else None
        if scene_capability is None:
            return 503, {"error": "scene-capability-unavailable"}
        if (json.dumps(body.get("scene_capability"), sort_keys=True, separators=(",", ":"))
            != json.dumps(scene_capability, sort_keys=True, separators=(",", ":"))
            or layout != "slots" or len(raw) != 1):
            return 400, {"error": "scene-capability-mismatch"}
        expected = {qid: {"type": "choice", "instructions": instructions, "criteria": labels}
                    for qid, (instructions, labels) in SCENE_QUESTIONS.items()}
        if note != SCENE_NOTE or questions != expected:
            return 400, {"error": "scene-template-mismatch"}
        floor = scene_capability["fitted_floor"]
    if pid != "doctor_probe" and (pid not in ACCEPTANCE_PASSES and wager_capability is None and scene_capability is None
                                 or type(floor) not in (int, float)
                                 or not 0 <= floor <= 1 or not math.isfinite(floor)):
        return 503, {"error": "acceptance-floor-unavailable"}
    t0 = time.perf_counter()
    try:
        images = engine.decode(raw)
    except Exception:
        return 400, {"error": "invalid-image"}
    t1 = time.perf_counter()
    segments = None
    if layout == "glyphs":
        glyphs, info = engine.prep.segment_glyphs(images[0], style, MAX_GLYPHS)
        segments = {"n": int(info["n"]), "overflow": bool(info["overflow"])}
        images = glyphs
        questions = {q: d for q, d in questions.items() if int(q[1:]) <= len(glyphs)}
    t2 = time.perf_counter()
    answers = {}
    if images and questions:
        try:
            result = engine.predict(images, note, questions)
        except Exception:
            return 500, {"error": "predict-failed"}
        answers = shape_answers(result, questions)
    t3 = time.perf_counter()
    timing = {"decode": round((t1 - t0) * 1000, 1), "prep": round((t2 - t1) * 1000, 1),
              "predict": round((t3 - t2) * 1000, 1)}
    payload = {"model": alias, "pass": pid, "answers": answers, "timing_ms": timing,
               "acceptance_floor": floor}
    if segments is not None:
        payload["segments"] = segments
    if wager_capability is not None:
        payload["wager_capability"] = wager_capability
    if scene_capability is not None:
        payload["scene_capability"] = scene_capability
    if log_fn:
        log_fn({"utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"), "pass": pid,
                "timing_ms": timing, "segments": segments,
                "answers": answer_diagnostics(pid, answers, floor)})
    return 200, payload


def handle_predict_batch(engine, alias, body_bytes, log_fn=None):
    """Bounded six-stack batching only; validates every fitted floor before decoding."""
    try:
        body = json.loads(body_bytes.decode("utf-8"), parse_constant=dashboard._reject_constant)
        if not isinstance(body, dict) or body.get("model") != alias:
            return 400, {"error": "malformed"}
        requests = body.get("batch")
        if not isinstance(requests, list) or not 1 <= len(requests) <= MAX_GLYPH_BATCH:
            return 400, {"error": "malformed"}
        validated = [validate_request(request, alias) for request in requests]
    except (ValueError, UnicodeDecodeError):
        return 400, {"error": "malformed"}
    except RequestError as error:
        return error.status, {"error": error.code}
    ids = [row[0] for row in validated]
    if (len(set(ids)) != len(ids) or any(pid not in STACK_PASSES or layout != "glyphs" or style != "gold"
        or any(q["type"] != "choice" for q in questions.values())
        for pid, _, layout, style, _, questions in validated)):
        return 400, {"error": "incompatible-batch"}
    floors = getattr(engine, "acceptance_floors", {})
    if (not isinstance(floors, dict) or any(type(floors.get(pid)) not in (int, float)
        or not math.isfinite(floors[pid]) or not 0 <= floors[pid] <= 1 for pid in ids)):
        return 503, {"error": "acceptance-floor-unavailable"}
    if sum(png_size(raw[0])[0]*png_size(raw[0])[1] for _, _, _, _, raw, _ in validated) > MAX_IMAGE_PIXELS:
        return 400, {"error": "image-too-large"}
    if not callable(getattr(engine, "predict_batch", None)):
        return 503, {"error": "batch-unavailable"}
    samples, active, payloads = [], [], []
    decode_ms, prep_ms = 0.0, 0.0
    for pid, note, _, style, raw, questions in validated:
        start = time.perf_counter()
        try:
            image = engine.decode(raw)[0]
        except Exception:
            return 400, {"error": "invalid-image"}
        decoded = time.perf_counter()
        try:
            glyphs, info = engine.prep.segment_glyphs(image, style, MAX_GLYPHS)
            segments = {"n": int(info["n"]), "overflow": bool(info["overflow"])}
        except Exception:
            return 400, {"error": "invalid-image"}
        prepared = time.perf_counter()
        decode_ms += (decoded-start)*1000
        prep_ms += (prepared-decoded)*1000
        questions = {qid: q for qid, q in questions.items() if int(qid[1:]) <= len(glyphs)}
        payloads.append({"model": alias, "pass": pid, "acceptance_floor": floors[pid],
                         "segments": segments, "answers": {}})
        if glyphs and questions and not segments["overflow"]:
            active.append(len(payloads)-1)
            samples.append((glyphs, note, questions))
    start = time.perf_counter()
    if samples:
        try:
            results = engine.predict_batch(samples)
            if len(results) != len(samples):
                raise ValueError("batch-result-count")
            for index, (_, _, questions), result in zip(active, samples, results):
                payloads[index]["answers"] = shape_answers(result, questions)
        except Exception:
            return 500, {"error": "predict-failed"}
    timing = {"decode": round(decode_ms, 1), "prep": round(prep_ms, 1),
              "predict": round((time.perf_counter()-start)*1000, 1)}
    for payload in payloads:
        # Shared battery timings are not a falsely attributed per-seat latency.
        payload["timing_ms"] = timing
        payload["timing_shared_batch"] = True
        if log_fn:
            log_fn({"utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
                    "pass": payload["pass"], "timing_ms": timing, "timing_shared_batch": True,
                    "segments": payload["segments"], "answers": answer_diagnostics(
                        payload["pass"], payload["answers"], payload["acceptance_floor"])})
    return 200, {"model": alias, "results": payloads, "timing_ms": timing}


class Service:
    def __init__(self, alias, meta=None, engine=None, log_fn=None):
        self.alias, self.meta, self.engine, self.log_fn = alias, meta or {}, engine, log_fn
        self.inference = threading.Lock()
        self.state = dashboard.DashboardState(alias, self.meta.get("checkpoint"))
        if engine is not None:
            self.state.set_model("ready", calibrated=self.meta.get("temperature_calibration_loaded", False),
                                 floors_loaded=self.meta.get("acceptance_floors_loaded", False))

    def predict(self, body, batch=False):
        if self.engine is None:
            return 503, {"error": "model-not-ready"}
        if not self.inference.acquire(blocking=False):
            return 503, {"error": "inference-busy"}
        self.state.set_busy(True)
        try:
            handler = handle_predict_batch if batch else handle_predict
            return handler(self.engine, self.alias, body, self.log_fn)
        except Exception:
            return 500, {"error": "predict-failed"}
        finally:
            self.state.set_busy(False)
            self.inference.release()


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True

    def __init__(self, address, handler, max_requests=16):
        self.requests = threading.BoundedSemaphore(max_requests)
        super().__init__(address, handler)

    def process_request(self, request, address):
        if not self.requests.acquire(blocking=False):
            try:
                request.settimeout(SOCKET_TIMEOUT)
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.requests.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.requests.release()

    def handle_error(self, request, client_address):
        # Client disconnects must not dump request details or backend exceptions.
        return


def make_handler(engine, alias, meta, log_fn, service=None):
    service = service or Service(alias, meta, engine, log_fn)

    class Handler(BaseHTTPRequestHandler):
        server_version = "laya-server"
        sys_version = ""
        timeout = SOCKET_TIMEOUT

        def log_message(self, *args):  # never log requests
            return

        def _send_bytes(self, status, data, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            try:
                self.wfile.write(data)
            except OSError:
                pass

        def _send(self, status, payload):
            self._send_bytes(status, json.dumps(payload, allow_nan=False).encode("utf-8"), "application/json")

        def _discard_body(self):
            if self.headers.get("Transfer-Encoding"):
                return
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return
            if 0 < n <= MAX_BODY:
                self.rfile.read(n)

        def _local_request(self):
            port = self.server.server_address[1]
            hosts = {"127.0.0.1:%d" % port, "localhost:%d" % port}
            supplied = self.headers.get_all("Host", [])
            origins = self.headers.get_all("Origin", [])
            if (len(supplied) != 1 or supplied[0].lower() not in hosts or len(origins) > 1
                    or origins and origins[0].lower() not in {"http://" + h for h in hosts}):
                if self.command == "POST":
                    self._discard_body()
                self._send(403, {"error": "local-origin-required"})
                return False
            return True

        def do_GET(self):
            if not self._local_request():
                return
            if self.path == "/v1/models":
                if service.engine is None:
                    self._send(503, {"error": "model-not-ready"})
                else:
                    self._send(200, {"object": "list", "data": [{"id": alias, "object": "model", "meta": service.meta}]})
            elif self.path == "/api/state":
                self._send(200, service.state.snapshot())
            elif self.path == "/api/reference":
                try:
                    reference = dashboard.references()
                except (OSError, ValueError):
                    self._send(503, {"error": "reference-unavailable"})
                    return
                self._send(200, reference)
            elif self.path == "/favicon.ico":
                self._send_bytes(204, b"", "image/x-icon")
            elif self.path in ASSETS:
                filename, content_type = ASSETS[self.path]
                try:
                    data = (Path(SCRIPTS) / "dashboard" / filename).read_bytes()
                except OSError:
                    self._send(503, {"error": "dashboard-assets-unavailable"})
                    return
                self._send_bytes(200, data, content_type)
            else:
                self._send(404, {"error": "not-found"})

        def do_POST(self):
            if not self._local_request():
                return
            if self.path not in ("/v1/laya/predict", "/v1/laya/predict-batch"):
                self._discard_body()
                self._send(404, {"error": "not-found"})
                return
            try:
                n = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                n = -1
            if n < 0:
                self._send(411, {"error": "length-required"})
                return
            if n > MAX_BODY:
                self._send(413, {"error": "body-too-large"})
                return
            if self.headers.get("Transfer-Encoding"):
                self._send(400, {"error": "malformed"})
                return
            body = self.rfile.read(n)
            if len(body) != n:
                self._send(400, {"error": "malformed"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
                self._send(415, {"error": "json-required"})
                return
            status, payload = service.predict(body, batch=self.path.endswith("predict-batch"))
            self._send(status, payload)

    return Handler


# ------------------------------------------------------------------------------------------------
# verify / fetch
# ------------------------------------------------------------------------------------------------


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_dir(pins):
    m = pins["model"]
    hf_home = os.environ.get("HF_HOME") or os.path.join(REPO, m["hf_home"])
    return os.path.join(hf_home, "hub", "models--" + m["repository"].replace("/", "--"), "snapshots", m["revision"])


def verify(pins, check_runtime=True):
    problems = []
    if check_runtime:
        from importlib import metadata

        for pkg, ver in pins["runtime"]["packages"].items():
            try:
                got = metadata.version(pkg)
            except metadata.PackageNotFoundError:
                got = None
            if got != ver:
                problems.append("package %s: %s != %s" % (pkg, got, ver))
        try:
            durl = json.loads(metadata.distribution("laya").read_text("direct_url.json") or "{}")
            commit = (durl.get("vcs_info") or {}).get("commit_id")
        except Exception:
            commit = None
        if commit != pins["runtime"]["laya"]["commit"]:
            problems.append("laya commit %s != %s" % (commit, pins["runtime"]["laya"]["commit"]))
    snap = snapshot_dir(pins)
    for f in pins["model"]["files"]:
        p = os.path.join(snap, f["path"])
        if not os.path.exists(p):
            problems.append("missing base file %s" % f["path"])
        elif os.path.getsize(p) != f["size"] or sha256_file(p) != f["sha256"]:
            problems.append("hash mismatch base %s" % f["path"])
    ft = pins["model"].get("finetuned")
    if not ft:
        problems.append("no fine-tuned checkpoint pinned")
    else:
        d = os.path.join(REPO, ft["path"])
        for f in ft["files"]:
            p = os.path.join(d, f["path"])
            if not os.path.exists(p):
                problems.append("missing fine-tuned file %s" % f["path"])
            elif os.path.getsize(p) != f["size"] or sha256_file(p) != f["sha256"]:
                problems.append("hash mismatch fine-tuned %s" % f["path"])
    return problems


def cmd_fetch(pins):
    from huggingface_hub import snapshot_download

    m = pins["model"]
    os.environ.setdefault("HF_HOME", os.path.join(REPO, m["hf_home"]))
    snapshot_download(m["repository"], revision=m["revision"])
    return cmd_verify(pins)


def cmd_verify(pins):
    problems = verify(pins)
    print(json.dumps({"event": "laya-verify", "ok": not problems, "problems": problems}))
    return 0 if not problems else 2


def cmd_serve(pins, answers_log, batch_size, dashboard_only=False, live_config=None,
              auto_attach=False, practice_config=dashboard.DEFAULT_PROFILE):
    if live_config and (auto_attach or practice_config != dashboard.DEFAULT_PROFILE):
        raise ValueError("choose one attachment selector")
    srv = pins["server"]
    if int(srv["port"]) != PORT:
        raise ValueError("Laya dashboard/model service requires port 18090; no alternate-port fallback")
    log_fn = None
    fh = None
    if answers_log:
        path = dashboard.local_path(answers_log)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = path.open("a", encoding="utf-8")
        log_lock = threading.Lock()

        def log_fn(rec):
            with log_lock:
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
    ft = pins["model"].get("finetuned") or {}
    meta = {"checkpoint": ft.get("path"), "base_revision": pins["model"]["revision"],
            "calibrated": False, "temperature_calibration_loaded": False,
            "acceptance_floors_loaded": False,
            "quality_gate": "failed", "seated_advice_supported": False}
    service = Service(srv["alias"], meta, log_fn=log_fn)
    httpd = BoundedHTTPServer((HOST, PORT), make_handler(None, srv["alias"], meta, log_fn, service))
    feed = None

    def initialize():
        service.state.set_model("loading")
        try:
            problems = verify(pins)
            if problems:
                service.state.set_model("failed", "verification-failed")
                print(json.dumps({"event": "laya-verify", "ok": False, "problems": problems}), flush=True)
                return
            engine = Engine(pins, batch_size=batch_size or srv.get("batch_size", 32))
            from PIL import Image

            warm = Image.new("RGB", (64, 64), (200, 30, 30))
            t0 = time.perf_counter()
            engine.predict([warm], "warm-up", {"c": {"type": "choice", "instructions": "What colour is the image?",
                                                      "criteria": ["red", "blue", "green"]}})
            warm_ms = round((time.perf_counter() - t0) * 1000, 1)
            meta.update(temperature_calibration_loaded=engine.calibration is not None,
                        acceptance_floors_loaded=True,
                        glyph_batching=callable(getattr(engine, "predict_batch", None)))
            service.engine = engine
            service.state.set_model("ready", calibrated=meta["temperature_calibration_loaded"], floors_loaded=True)
            print(json.dumps({"event": "model-ready", "alias": srv["alias"], "warmup_ms": warm_ms,
                              "quality_gate": "failed", "advice_ready": False}), flush=True)
        except Exception:
            service.engine = None
            service.state.set_model("failed", "model-initialization-failed")
            print(json.dumps({"event": "model-failed", "error": "model-initialization-failed"}), flush=True)

    print(json.dumps({"event": "ready", "host": HOST, "port": PORT, "alias": srv["alias"],
                      "dashboard": True, "advice_ready": False}), flush=True)
    if not dashboard_only:
        threading.Thread(target=initialize, daemon=True).start()
    if auto_attach or live_config:
        try:
            feed = dashboard.AutoAttachFeed(live_config or practice_config, service.state)
            feed.start()
        except (OSError, ValueError):
            service.state.attach_blocked("invalid-attachment-config")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if feed is not None:
            feed.stop()
        httpd.server_close()
        if fh is not None:
            fh.close()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", nargs="?", default="serve", choices=["serve", "fetch", "verify"])
    ap.add_argument("--answers-log", default=None, help="JSONL of answers and timings (no image data)")
    ap.add_argument("--batch-size", type=int, default=None)
    ap.add_argument("--dashboard-only", action="store_true", help="serve read-only Monitor/Reference without loading a model")
    attachment = ap.add_mutually_exclusive_group()
    attachment.add_argument("--live-config", help="internal strict selector profile under .local, never raw capture argv")
    attachment.add_argument("--auto-attach", action="store_true", help="automatically retain one uniquely selected passive feed")
    ap.add_argument("--practice-config", default=dashboard.DEFAULT_PROFILE, help="optional private selector profile under .local")
    a = ap.parse_args(argv)
    if a.live_config and a.practice_config != dashboard.DEFAULT_PROFILE:
        ap.error("choose --live-config or --practice-config, not both")
    pins = load_pins()
    if a.command == "verify":
        return cmd_verify(pins)
    if a.command == "fetch":
        return cmd_fetch(pins)
    return cmd_serve(pins, a.answers_log, a.batch_size, a.dashboard_only, a.live_config,
                     a.auto_attach, a.practice_config)


if __name__ == "__main__":
    sys.exit(main())
