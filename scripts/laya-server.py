#!/usr/bin/env python3
"""Loopback Laya Vision server for coinpoker-help (the sole live perception backend).

Subcommands:
  serve  (default)  local dashboard; model loading is selected with --enable-inference
  fetch             download the pinned base checkpoint (HF revision) into HF_HOME, then verify
  verify            check runtime package versions, laya commit and every pinned file's SHA-256

API (loopback only, concurrent HTTP with one GPU admission slot):
  GET  /                 local dashboard
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
  POST /v1/laya/predict-batch -> {model, batch:[predict bodies]} for up to six stack passes.
       With batch_kind "readout": exactly [p0, Pot, seat1, seat2] (or 3/4, 5/6),
       [p0, Pot, seat1..seat6], or [p0, Board].
       Readout p0 requires exactly the original numeric (4) or board (5) gate questions.
       At most 64 question rows and 64 prepared images; independent results, shared timing only.

Hygiene: never logs or echoes request content; errors are {"error": "<code>"}; bounded body,
image and question limits; images are never written to disk. torch / laya / PIL / numpy are
imported lazily so the request validation stays stdlib-only and testable.
"""

import argparse
import base64
import binascii
import contextlib
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
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import laya_dashboard as dashboard
import laya_capture as manual_capture
import laya_provenance as provenance
from laya_server_validation import (
    ACCEPTANCE_PASSES,
    ASSETS,
    CSP,
    EXPERIMENTAL_BOUNDS,
    EXPERIMENTAL_CHECKPOINT,
    EXPERIMENTAL_MODEL_SHA256,
    EXPERIMENTAL_WAGER_NOTE,
    GLYPH_STYLES,
    HOST,
    ID_RE,
    LAYOUTS,
    MAX_ACCEPTANCE_REPORT,
    MAX_BODY,
    MAX_GLYPHS,
    MAX_GLYPH_BATCH,
    MAX_IMAGES,
    MAX_IMAGE_PIXELS,
    MAX_INSTRUCTIONS,
    MAX_NOTE,
    MAX_OPTIONS,
    MAX_OPTION_TEXT,
    MAX_QUESTIONS,
    MAX_READOUT_IMAGES,
    MAX_READOUT_PASSES,
    MAX_READOUT_QUESTIONS,
    MAX_REFERENCE_EDGE,
    PNG_SIG,
    PORT,
    RequestError,
    SCENE_NOTE,
    SCENE_PASSES,
    SCENE_QUESTIONS,
    SOCKET_TIMEOUT,
    STACK_PASSES,
    SEATED_PASSES,
    WAGER_NOTE,
    WAGER_PASSES,
    answer_diagnostics,
    decode_and_prepare_pass,
    experimental_descriptor,
    load_acceptance_floors_from_repo,
    load_experimental_metadata_from_root,
    load_seat_registry_from_root,
    pinned_file_entries,
    png_size,
    project_browser_snapshot,
    shape_answers,
    validate_request,
)

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS)
ROOT = Path(REPO)
PINS_PATH = os.path.join(SCRIPTS, "laya-pins.json")


def load_pins(path=PINS_PATH):
    with open(path, encoding="utf-8") as f:
        pins = json.load(f)
    if pins.get("format") != 1:
        raise ValueError("unsupported laya-pins format")
    return pins


def load_acceptance_floors(pins):
    """Read the separately pinned fitted report; this is not quality approval."""
    return load_acceptance_floors_from_repo(pins, REPO, dashboard._reject_constant)


def load_seat_registry(pins, kind):
    """Optional per-seat evidence, absent for it1. Never caller or global approval."""
    return load_seat_registry_from_root(pins, kind, ROOT, dashboard._reject_constant)


def load_wager_registry(pins):
    return load_seat_registry(pins, "wager")


def load_scene_registry(pins):
    return load_seat_registry(pins, "scene")


def load_experimental_metadata(pins, floors):
    """Bind transfer diagnostics to it1's pinned donor calibration, not target proof."""
    return load_experimental_metadata_from_root(pins, floors, ROOT, REPO, dashboard._reject_constant)


class Engine:
    """Lazy GPU side: decode, prepare, predict. Replaced by a fake in tests."""

    def __init__(self, pins, batch_size=32, *, experimental_bet_action=False):
        if type(experimental_bet_action) is not bool:
            raise ValueError("experimental-bet-action-approval-required")
        self.pins = pins
        self.batch_size = batch_size
        self.acceptance_floors = load_acceptance_floors(pins)
        self.wager_registry = load_wager_registry(pins)
        self.scene_registry = load_scene_registry(pins)
        self.experimental_metadata = load_experimental_metadata(pins, self.acceptance_floors) if experimental_bet_action else None
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
        self._prefix_processors = None
        self._image_feature_cache = {}
        self._image_feature_cache_bytes = 0
        self._image_feature_cache_limit = 16 * 1024 * 1024
        self._image_feature_cache_context = None
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

        if len(questions) <= self.batch_size:
            return self.predict_many([(images, note, questions)])[0]
        # Keep upstream's shared-prefix policy for unusually large single requests.
        with torch.inference_mode():
            res = self.agent.predict({"images": images, "note": note}, questions, n_permutations=1,
                                     batch_size=self.batch_size, calibration=self.calibration)
            torch.cuda.synchronize()
            return res

    def predict_batch(self, samples):
        return self.predict_many(samples)

    def _prefix(self, images):
        """Use the original processor, including its tensor conversion and resampling."""
        from laya import vlm

        return vlm.vlm_prefix(self.agent.processor, images, self.agent.prep)

    def _prefixes(self, samples):
        """Bounded CPU-only preprocessing; GPU inference stays ordered and scalar-shaped."""
        from laya import vlm

        processor, prep = self.agent.processor, self.agent.prep
        if (len(samples) < 2 or getattr(prep, "on_gpu", False) or getattr(prep, "split_edge", 0)
                or type(getattr(processor, "image_processor", None)).__name__ != "Idefics3ImageProcessorPil"
                or vlm.processor_readout(processor) != "terminator"):
            return [self._prefix(images) for images, _, _ in samples]
        import copy
        from concurrent.futures import ThreadPoolExecutor

        # Tokenizers may mutate padding/truncation settings. Never share one between
        # concurrent workers, and never retain request images in this processor cache.
        if self._prefix_processors is None:
            self._prefix_processors = tuple(copy.deepcopy(processor) for _ in range(4))
        processors = iter(self._prefix_processors)
        local = threading.local()

        def initialize():
            local.processor = next(processors)

        def prepare(images):
            return vlm.vlm_prefix(local.processor, images, prep)

        # The context joins all running work even on failure, before the inference
        # admission lock can be released. HTTP batches already cap queued states at six.
        with ThreadPoolExecutor(max_workers=min(4, len(samples)), initializer=initialize) as pool:
            return list(pool.map(prepare, (images for images, _, _ in samples)))

    def _image_cache_key(self, images):
        """Exact small RGB states only; never mix features from different encoder batches."""
        cache = getattr(self, "_image_feature_cache", None)
        if cache is None:
            return None
        agent = self.agent
        context = (agent.model, agent.processor, agent.prep, str(agent.device), agent._torch_dtype())
        old = self._image_feature_cache_context
        if (old is None or any(a is not b for a, b in zip(context[:3], old[:3]))
                or context[3:] != old[3:] or agent.model.training):
            cache.clear()
            self._image_feature_cache_bytes = 0
            self._image_feature_cache_context = context
        if (agent.model.training or self._image_feature_cache_limit <= 0 or not images
                or getattr(agent.prep, "on_gpu", False) or getattr(agent.prep, "split_edge", 0)
                or any(getattr(image, "mode", None) != "RGB" for image in images)):
            return None
        # Full windows change continuously. Do not let them evict repeated glyph/slot states.
        if sum(image.width * image.height * 3 for image in images) > 128 * 1024:
            return None
        return tuple((image.size, image.tobytes()) for image in images)

    def _remember_image_features(self, key, prefix, features):
        """Bound retained pixels, prefix ids and owned feature storage; callers hold GPU admission."""
        if key is None or features is None:
            return
        prefix = {**prefix, "ids": list(prefix["ids"]), "pixel_values": None,
                  "pixel_attention_mask": None, "raw_images": None}
        size = (features.numel() * features.element_size() + sys.getsizeof(key)
                + sum(sys.getsizeof(pair) + sys.getsizeof(pair[0]) + sys.getsizeof(pair[1]) for pair in key)
                + sys.getsizeof(prefix) + sys.getsizeof(prefix["ids"])
                + sum(sys.getsizeof(token) for token in prefix["ids"]))
        if size > self._image_feature_cache_limit:
            return
        cache = self._image_feature_cache
        while cache and (len(cache) >= 64 or self._image_feature_cache_bytes + size > self._image_feature_cache_limit):
            _, _, evicted_size = cache.pop(next(iter(cache)))
            self._image_feature_cache_bytes -= evicted_size
        # Own a compact tensor, not a view that could retain a larger allocation or be mutated.
        cache[key] = (prefix, features.detach().clone(), size)
        self._image_feature_cache_bytes += size

    def predict_many(self, samples):
        """Coalesce requests without changing scalar vision/text batch shapes or order."""
        if not samples:
            return []
        if any(len(questions) > self.batch_size for _, _, questions in samples):
            # Upstream may enable a shared-prefix cache for large states. Preserve it.
            return [self.predict(images, note, questions) for images, note, questions in samples]
        import numpy as np
        import torch
        from laya import vlm

        agent = self.agent
        if self.calibration is not None:
            self.calibration.check(vlm.checkpoint_identity(agent))
        temperatures = vlm.resolve_temperature(None, self.calibration)
        definitions, scored_batches = [], []
        text_rows = {}
        # Thread-local: loading the model under this guard would not cover HTTP workers.
        with torch.inference_mode():
            keys = [self._image_cache_key(images) for images, _, _ in samples]
            cache = getattr(self, "_image_feature_cache", {})
            cached = [cache.get(key) if key is not None else None for key in keys]
            prepared = iter(self._prefixes([sample for sample, entry in zip(samples, cached) if entry is None]))
            prefixes = [entry[0] if entry is not None else next(prepared) for entry in cached]
            for sample_index, ((images, note, questions), prefix) in enumerate(zip(samples, prefixes)):
                rows = []
                for qid, question in questions.items():
                    if question["type"] not in ("choice", "noul"):
                        raise ValueError("batch-question-invalid")
                    internal = agent._to_internal(question)
                    options = len(vlm.render_options(internal))
                    key = (note, tuple(prefix["ids"]), prefix["n_images"],
                           json.dumps(internal, ensure_ascii=True, separators=(",", ":")))
                    if key not in text_rows:
                        # build_vlm_inputs ignores state images with a supplied prefix, but
                        # split_state still copies them. Pass the identical serialized note only.
                        text_prefix = {**prefix, "pixel_values": None,
                                       "pixel_attention_mask": None, "raw_images": None}
                        item = vlm.build_vlm_inputs(agent.processor, {"note": note}, internal,
                            agent.cfg.get("max_len", 1024), agent.cfg.get("head_max_len", 256), prefix=text_prefix)
                        if len(item["markers"]) != options:
                            raise ValueError("batch-question-invalid")
                        item["qtype"] = vlm.QTYPES[internal["t"]]
                        text_rows[key] = item
                    item = text_rows[key]
                    rows.append({**item, "sample_index": sample_index})
                    definitions.append((sample_index, qid, internal,
                                         vlm.truncation_answer(item["truncation"], internal)))
                key = keys[sample_index]
                entry = cached[sample_index]
                if key is not None and key in cache:
                    entry = cache.pop(key)
                    cache[key] = entry
                image_features = entry[1] if entry is not None else None
                if entry is None and images and prefix["raw_images"] is not None:
                    image_features = agent.model.encode_raw_images(prefix["raw_images"])
                elif entry is None and images:
                    image_features = agent.model.encode_images(
                        prefix["pixel_values"].to(agent.device, agent._torch_dtype()),
                        prefix["pixel_attention_mask"].to(agent.device))
                if entry is None:
                    self._remember_image_features(key, prefix, image_features)
                # Cross-state batches changed calibrated probabilities on original captures.
                # Match upstream's per-state encoder batch, padding and feature repetition.
                for offset in range(0, len(rows), self.batch_size):
                    chunk = rows[offset:offset+self.batch_size]
                    batch = vlm.collate_vlm(chunk, agent.processor.tokenizer.pad_token_id, with_pixels=False)
                    features = image_features.repeat(len(chunk), 1, 1) if image_features is not None else None
                    args = [batch[k].to(agent.device) for k in
                            ("input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype")]
                    scored, _ = agent.model(*args, image_hidden_states=features,
                                           option_span=batch["option_span"].to(agent.device))
                    scored_batches.append(scored)
            # Queue all forwards before the first blocking device-to-host copy.
            logits = [row for scored in scored_batches for row in scored.float().cpu().numpy()]
            torch.cuda.synchronize()
        output = [{"answers": {}} for _ in samples]
        for (sample_index, qid, question, truncated), scored in zip(definitions, logits):
            count = len(vlm.render_options(question))
            scale = temperatures.get(vlm.QTYPES[question["t"]],
                                     agent._checkpoint_temperature(vlm.QTYPES[question["t"]], count))
            z = np.asarray(scored[:count], dtype=np.float64) / max(1e-3, float(scale))
            probabilities = np.exp(z-z.max())
            probabilities /= probabilities.sum()
            if question["t"] == "choice":
                options = list(question["crit"])
                answer = {"type": "choice", "choice": options[int(probabilities.argmax())],
                          "probabilities": {key: round(float(p), 4) for key, p in zip(options, probabilities)},
                          "confidence": round(vlm.confidence_from_probs(probabilities, count), 4)}
            else:
                value = float(probabilities[1])
                answer = {"type": "noul", "noul": round(value, 4),
                          "confidence": round(max(value, 1.0-value), 4)}
            if truncated:
                answer["truncated"] = truncated
            output[sample_index]["answers"][qid] = answer
        return output


@lru_cache(maxsize=1)
def wager_questions():
    path = ROOT / "crates/ingest/assets/laya/question-set.json"
    manifest = json.loads(path.read_text(encoding="utf-8"), parse_constant=dashboard._reject_constant)
    source = next(p for p in manifest["passes"] if p["id"] == "p5_seat_1_stack")
    return {q["id"]: {"type": q["type"], "instructions": q["instructions"],
                      "criteria": {label: q["criteria"][label] for label in q["option_order"]}}
            for q in source["questions"]}


@lru_cache(maxsize=2)
def readout_core_template(board):
    path = ROOT / "crates/ingest/assets/laya/question-set.json"
    manifest = json.loads(path.read_text(encoding="utf-8"), parse_constant=dashboard._reject_constant)
    source = next(p for p in manifest["passes"] if p["id"] == "p0_full")
    original = {q["id"]: q for q in source["questions"]}
    ids = ("screen_kind", "ev_table_layout", "ev_readable") + (
        ("ev_board_area", "game_phase") if board else ("ev_pot",))
    questions = {}
    for qid in ids:
        q = original[qid]
        definition = {"type": q["type"], "instructions": q["instructions"]}
        if q["type"] == "choice":
            criteria = q["criteria"]
            definition["criteria"] = ({label: criteria[label] for label in q["option_order"]}
                                      if isinstance(criteria, dict) else criteria)
        questions[qid] = definition
    return source["note"], questions


def handle_predict(engine, alias, body_bytes, log_fn=None, *, experimental_authorized=None):
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
    descriptor = None
    experiment = "experimental_descriptor" in body
    diagnostic_metadata = None
    if experiment:
        if not callable(experimental_authorized) or not experimental_authorized():
            return 403, {"error": "experimental-session-required"}
        if pid not in WAGER_PASSES | SCENE_PASSES:
            return 400, {"error": "experimental-descriptor-mismatch"}
        descriptor = experimental_descriptor(pid)
        if (json.dumps(body["experimental_descriptor"], sort_keys=True, separators=(",", ":"))
                != json.dumps(descriptor, sort_keys=True, separators=(",", ":"))
                or "wager_capability" in body or "scene_capability" in body):
            return 400, {"error": "experimental-descriptor-mismatch"}
        metadata = getattr(engine, "experimental_metadata", None)
        if (not isinstance(floors, dict) or set(floors) != ACCEPTANCE_PASSES
                or any(type(value) not in (int, float) or not 0 <= value <= 1 or not math.isfinite(value)
                       for value in floors.values())
                or not isinstance(metadata, dict) or metadata.get("model_sha256") != EXPERIMENTAL_MODEL_SHA256
                or not re.fullmatch(r"[0-9a-f]{64}", str(metadata.get("temperature_calibration_sha256", "")))
                or metadata.get("donor_pass") != "p5_seat_1_stack"
                or type(metadata.get("inherited_cutoff")) not in (int, float)
                or not max(0.8, floors["p5_seat_1_stack"]) <= metadata["inherited_cutoff"] <= 1):
            return 503, {"error": "experimental-candidate-unavailable"}
        try:
            expected = wager_questions() if pid in WAGER_PASSES else {
                qid: {"type": "choice", "instructions": instructions, "criteria": labels}
                for qid, (instructions, labels) in SCENE_QUESTIONS.items()}
        except (OSError, ValueError, KeyError, StopIteration):
            return 503, {"error": "experimental-template-unavailable"}
        expected_note = EXPERIMENTAL_WAGER_NOTE if pid in WAGER_PASSES else SCENE_NOTE
        if (questions != expected or note != expected_note
                or pid in WAGER_PASSES and (layout != "glyphs" or style != "white")
                or pid in SCENE_PASSES and (layout != "slots" or len(raw) != 1 or style is not None)
                or any(isinstance(q["criteria"], dict)
                       and list(q["criteria"].items()) != list(expected[qid]["criteria"].items())
                       for qid, q in questions.items())):
            return 400, {"error": "experimental-template-mismatch"}
        floor = None
        diagnostic_metadata = {"diagnostic_only": True, "training": "unvalidated",
                               "geometry_status": "DRAFT", "human_review": "PENDING",
                               "donor_pass": metadata["donor_pass"] if pid in WAGER_PASSES else None,
                               "inherited_cutoff": metadata["inherited_cutoff"] if pid in WAGER_PASSES else None}
    if pid in WAGER_PASSES and not experiment:
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
    if pid in SCENE_PASSES and not experiment:
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
    if not experiment and pid != "doctor_probe":
        seated = pid in SEATED_PASSES
        if (pid not in ACCEPTANCE_PASSES and not seated
                and wager_capability is None and scene_capability is None):
            return 503, {"error": "acceptance-floor-unavailable"}
        # The fitted table never covered the seated passes: a null floor is the
        # contract there. Everywhere else a missing floor still fails closed.
        if floor is None and not seated:
            return 503, {"error": "acceptance-floor-unavailable"}
        if floor is not None and (type(floor) not in (int, float)
                                  or not 0 <= floor <= 1 or not math.isfinite(floor)):
            return 503, {"error": "acceptance-floor-unavailable"}
    try:
        images, questions, segments, decode_ms, prep_ms = decode_and_prepare_pass(
            engine, layout, style, raw, questions
        )
    except RequestError as error:
        return error.status, {"error": error.code}
    t2 = time.perf_counter()
    answers = {}
    if experiment and not experimental_authorized():
        return 409, {"error": "manual-session-ended"}
    if images and questions:
        try:
            result = engine.predict(images, note, questions)
        except Exception:
            return 500, {"error": "predict-failed"}
        answers = shape_answers(result, questions)
        if experiment:
            # A transfer score is neither recognition approval nor arbitrary OCR.
            answers = {qid: answer for qid, answer in answers.items()
                       if answer["type"] == "choice" and answer.get("choice") in questions[qid]["criteria"]
                       and isinstance(answer.get("probabilities"), dict)
                       and set(answer["probabilities"]) == set(questions[qid]["criteria"])
                       and all(type(p) in (int, float) and 0 <= p <= 1 and math.isfinite(p)
                               for p in answer["probabilities"].values())
                       and (answer["confidence"] is None or type(answer["confidence"]) in (int, float)
                            and 0 <= answer["confidence"] <= 1 and math.isfinite(answer["confidence"]))}
    t3 = time.perf_counter()
    timing = {"decode": round(decode_ms, 1), "prep": round(prep_ms, 1),
              "predict": round((t3 - t2) * 1000, 1)}
    payload = {"model": alias, "pass": pid, "answers": answers, "timing_ms": timing,
               "acceptance_floor": floor}
    if segments is not None:
        payload["segments"] = segments
    if wager_capability is not None:
        payload["wager_capability"] = wager_capability
    if scene_capability is not None:
        payload["scene_capability"] = scene_capability
    if experiment:
        if not experimental_authorized():
            return 409, {"error": "manual-session-ended"}
        payload.update(experimental_descriptor=descriptor, experimental_diagnostics=diagnostic_metadata)
    if log_fn:
        log_fn({"utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"), "pass": pid,
                "timing_ms": timing, "segments": segments,
                "answers": answer_diagnostics(pid, answers, floor),
                **({"experimental_diagnostics": diagnostic_metadata} if experiment else {})})
    return 200, payload


def handle_predict_batch(engine, alias, body_bytes, log_fn=None):
    """Legacy stack batches or opt-in paired readouts; validate all floors before decode."""
    try:
        body = json.loads(body_bytes.decode("utf-8"), parse_constant=dashboard._reject_constant)
        if not isinstance(body, dict) or body.get("model") != alias:
            return 400, {"error": "malformed"}
        readout = body.get("batch_kind") == "readout"
        if "batch_kind" in body and not readout:
            return 400, {"error": "incompatible-batch"}
        requests = body.get("batch")
        limit = MAX_READOUT_PASSES if readout else MAX_GLYPH_BATCH
        if not isinstance(requests, list) or not 1 <= len(requests) <= limit:
            return 400, {"error": "malformed"}
        validated = [validate_request(request, alias) for request in requests]
    except (ValueError, UnicodeDecodeError):
        return 400, {"error": "malformed"}
    except RequestError as error:
        return error.status, {"error": error.code}
    ids = [row[0] for row in validated]
    if readout:
        groups = [("p0_full", "p2_board")] + [
            ("p0_full", "p3_pot", "p5_seat_%d_stack" % seat, "p5_seat_%d_stack" % (seat+1))
            for seat in (1, 3, 5)] + [
            tuple(["p0_full", "p3_pot"] + ["p5_seat_%d_stack" % seat for seat in range(1, 7)])]
        if (tuple(ids) not in groups or any(
                any(key in request for key in ("experimental_descriptor", "wager_capability", "scene_capability"))
                for request in requests)):
            return 400, {"error": "incompatible-batch"}
        for pid, _, layout, style, raw, questions in validated:
            expected = (("full", None, 1) if pid == "p0_full" else ("slots", None, 5) if pid == "p2_board"
                        else ("glyphs", "white" if pid == "p3_pot" else "gold", 1))
            if ((layout, style, len(raw)) != expected
                    or pid != "p0_full" and any(q["type"] != "choice" for q in questions.values())):
                return 400, {"error": "incompatible-batch"}
        if sum(len(row[5]) for row in validated) > MAX_READOUT_QUESTIONS:
            return 400, {"error": "batch-too-large"}
        try:
            expected_note, expected_core = readout_core_template(ids[1] == "p2_board")
        except (OSError, ValueError, KeyError, StopIteration, TypeError):
            return 503, {"error": "readout-core-template-unavailable"}
        core = validated[0][5]
        if (validated[0][1] != expected_note or core != expected_core
                or any(set(requests[0]["questions"][qid]) != set(expected_core[qid]) for qid in core)
                or any(isinstance(q.get("criteria"), dict)
                       and list(q["criteria"].items()) != list(expected_core[qid]["criteria"].items())
                       for qid, q in core.items())):
            return 400, {"error": "readout-core-template-mismatch"}
    elif (len(set(ids)) != len(ids) or any(pid not in STACK_PASSES or layout != "glyphs" or style != "gold"
        or any(q["type"] != "choice" for q in questions.values())
        for pid, _, layout, style, _, questions in validated)):
        return 400, {"error": "incompatible-batch"}
    floors = getattr(engine, "acceptance_floors", {})
    if (not isinstance(floors, dict) or any(type(floors.get(pid)) not in (int, float)
        or not math.isfinite(floors[pid]) or not 0 <= floors[pid] <= 1 for pid in ids)):
        return 503, {"error": "acceptance-floor-unavailable"}
    if sum(png_size(data)[0]*png_size(data)[1] for _, _, _, _, raw, _ in validated for data in raw) > MAX_IMAGE_PIXELS:
        return 400, {"error": "image-too-large"}
    if not callable(getattr(engine, "predict_batch", None)):
        return 503, {"error": "batch-unavailable"}
    samples, active, payloads = [], [], []
    decode_ms, prep_ms = 0.0, 0.0
    prepared_images, prepared_questions = 0, 0
    for pid, note, layout, style, raw, questions in validated:
        try:
            images, questions, segments, step_decode_ms, step_prep_ms = decode_and_prepare_pass(
                engine, layout, style, raw, questions, catch_prep_errors=True
            )
        except RequestError as error:
            return error.status, {"error": error.code}
        decode_ms += step_decode_ms
        prep_ms += step_prep_ms
        prepared_images += len(images)
        prepared_questions += len(questions)
        if readout and (prepared_images > MAX_READOUT_IMAGES or prepared_questions > MAX_READOUT_QUESTIONS):
            return 400, {"error": "batch-too-large"}
        payload = {"model": alias, "pass": pid, "acceptance_floor": floors[pid], "answers": {}}
        if segments is not None:
            payload["segments"] = segments
        payloads.append(payload)
        if images and questions and (segments is None or not segments["overflow"]):
            active.append(len(payloads)-1)
            samples.append((images, note, questions))
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
                    "segments": payload.get("segments"), "answers": answer_diagnostics(
                        payload["pass"], payload["answers"], payload["acceptance_floor"])})
    return 200, {"model": alias, "results": payloads, "timing_ms": timing}


class Service:
    def __init__(self, alias, meta=None, engine=None, log_fn=None, *, experimental_bet_action=False):
        if type(experimental_bet_action) is not bool:
            raise ValueError("experimental-bet-action-approval-required")
        self.alias, self.meta, self.engine, self.log_fn = alias, meta or {}, engine, log_fn
        self.experimental_bet_action = experimental_bet_action
        self.inference_enabled = engine is not None
        self.instance_id = uuid.uuid4().hex
        self.provenance = None
        self.manual_feed = None
        self.automatic_startup = None
        self.capture_control_lock = threading.RLock()
        self.capture_control_id = uuid.uuid4().hex
        self.shutting_down = threading.Event()
        self.inference = threading.Lock()
        self.state = dashboard.DashboardState(alias, self.meta.get("checkpoint"),
                                              experimental_bet_action=self.experimental_bet_action,
                                              service_instance_id=self.instance_id)
        if engine is not None:
            self.state.set_model("ready", calibrated=self.meta.get("temperature_calibration_loaded", False),
                                  floors_loaded=self.meta.get("acceptance_floors_loaded", False))

    def capture_controls(self, current):
        with self.capture_control_lock:
            startup = self.automatic_startup
            alive = startup is not None and startup.thread is not None and startup.thread.is_alive()
            stopping = alive and startup.closed.is_set()
            configured = startup is not None and self.manual_feed is not None and self.inference_enabled
            with self.state.lock:
                ready = self.state.model["model_state"] == "ready"
            active = current.get("status") == "capturing"
            available = configured and ready and self.engine is not None and not alive and not active and not self.shutting_down.is_set()
            status = "stopping" if stopping else "running" if active else "starting" if alive else "available" if available else "unavailable"
            return {"enabled": configured or active or alive, "control_id": self.capture_control_id, "status": status,
                    "can_start": available, "can_stop": not self.shutting_down.is_set() and not stopping and (active or alive)}

    def start_capture(self, body):
        try:
            value = manual_capture.attach._json(body, "window-list-invalid")
            if (not isinstance(value, dict) or set(value) != {"service_instance_id", "control_id"}
                    or any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{32}", item) for item in value.values())):
                raise ValueError("invalid-request")
        except (ValueError, TypeError, UnicodeDecodeError):
            return 400, {"error": "invalid-request"}
        with self.capture_control_lock:
            if (self.shutting_down.is_set() or value["service_instance_id"] != self.instance_id
                    or value["control_id"] != self.capture_control_id):
                return 409, {"error": "capture-control-unavailable"}
            root = self.manual_feed.root if self.manual_feed is not None else manual_capture.ROOT
            current = manual_capture.public_snapshot(root=root)
            if not self.capture_controls(current)["can_start"]:
                return 409, {"error": "capture-control-unavailable"}
            previous = self.automatic_startup
            startup = manual_capture.AutomaticStart(self, profile=previous.profile, root=previous.root,
                                                    continuous_observation=previous.continuous_observation)
            self.capture_control_id = uuid.uuid4().hex
            self.automatic_startup = startup
            try:
                startup.start()
            except (OSError, RuntimeError):
                startup.closed.set()
                startup.status, startup.reason = "failed", "automatic-startup-failed"
                return 500, {"error": "capture-start-failed"}
            return 202, {"ok": True, "control_id": self.capture_control_id}

    def stop_capture(self, body):
        def unique_fields(pairs):
            value = dict(pairs)
            if len(value) != len(pairs):
                raise ValueError("invalid-request")
            return value
        try:
            value = json.loads(body, object_pairs_hook=unique_fields, parse_constant=dashboard._reject_constant)
            controlled = isinstance(value, dict) and "control_id" in value
            expected = {"session_id", "service_instance_id"} | ({"control_id"} if controlled else set())
            if (not isinstance(value, dict) or set(value) != expected
                    or any(not isinstance(value.get(key), str) or not re.fullmatch(r"[0-9a-f]{32}", value[key])
                           for key in expected - {"session_id"})
                    or not (isinstance(value.get("session_id"), str) and re.fullmatch(r"[0-9a-f]{32}", value["session_id"])
                            or controlled and value.get("session_id") is None)):
                raise ValueError("invalid-request")
        except (ValueError, TypeError, UnicodeDecodeError):
            return 400, {"error": "invalid-request"}
        if self.shutting_down.is_set() or value["service_instance_id"] != self.instance_id:
            return 409, {"error": "capture-session-unavailable"}
        if controlled:
            with self.capture_control_lock:
                if value["control_id"] != self.capture_control_id:
                    return 409, {"error": "capture-session-unavailable"}
                startup = self.automatic_startup
                if value["session_id"] is None:
                    if startup is None or startup.thread is None or not startup.thread.is_alive():
                        return 409, {"error": "capture-session-unavailable"}
                    # Cancel this exact arm, including a source bind racing the request.
                    startup.closed.set()
                    if startup.session_id is not None:
                        try:
                            root = self.manual_feed.root if self.manual_feed is not None else manual_capture.ROOT
                            manual_capture.stop_session(startup.session_id, root=root)
                        except (OSError, ValueError, TypeError):
                            return 409, {"error": "capture-session-unavailable"}
                    with self.state.lock:
                        self.state.capture.update(state="unavailable", fresh_capture=False, epoch=None)
                        self.state._invalidate("operator-stop")
                    return 200, {"ok": True}
        root = self.manual_feed.root if self.manual_feed is not None else manual_capture.ROOT
        snapshot = manual_capture.public_snapshot(root=root)
        if snapshot.get("status") != "capturing" or snapshot.get("session_id") != value["session_id"]:
            return 409, {"error": "capture-session-unavailable"}
        try:
            approval = manual_capture.read_json(manual_capture.session_path(value["session_id"], root=root) / "approval.json")
            if (approval.get("mode") not in manual_capture.MODES
                    or approval["mode"] == "inference-enabled" and approval.get("service_instance_id") != self.instance_id):
                return 409, {"error": "capture-session-unavailable"}
            manual_capture.stop_session(value["session_id"], root=root)
        except (OSError, ValueError, TypeError):
            return 409, {"error": "capture-session-unavailable"}
        with self.state.lock:
            self.state.capture.update(state="unavailable", fresh_capture=False, epoch=None)
            self.state._invalidate("operator-stop")
        if (self.automatic_startup is not None
                and self.automatic_startup.session_id == value["session_id"]):
            self.automatic_startup.closed.set()
        return 200, {"ok": True}

    def predict(self, body, batch=False, session_binding=None):
        def authorized():
            return (not self.shutting_down.is_set() and (session_binding is None or self.manual_feed is not None
                     and self.manual_feed.authorizes(*session_binding)))
        def experimental_authorized():
            return (self.experimental_bet_action is True and self.inference_enabled
                    and not self.shutting_down.is_set() and session_binding is not None
                    and authorized() and manual_capture.experimental_session_approved(
                        *session_binding, root=self.manual_feed.root))
        if not authorized():
            return 409, {"error": "manual-session-ended"}
        if self.engine is None:
            return 503, {"error": "model-not-ready"}
        if not self.inference.acquire(blocking=False):
            return 503, {"error": "inference-busy"}
        self.state.set_busy(True)
        try:
            if not authorized():
                return 409, {"error": "manual-session-ended"}
            if batch:
                result = handle_predict_batch(self.engine, self.alias, body, self.log_fn)
            elif self.experimental_bet_action:
                result = handle_predict(self.engine, self.alias, body, self.log_fn,
                                        experimental_authorized=experimental_authorized)
            else:
                result = handle_predict(self.engine, self.alias, body, self.log_fn)
            return result if authorized() else (409, {"error": "manual-session-ended"})
        except Exception:
            return 500, {"error": "predict-failed"}
        finally:
            self.state.set_busy(False)
            self.inference.release()


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True

    def __init__(self, address, handler, max_requests=64):
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
                if service.manual_feed is not None:
                    snapshot = service.manual_feed.snapshot()
                else:
                    snapshot = service.state.snapshot()
                    snapshot["capture_session"] = manual_capture.public_snapshot()
                snapshot["server"]["inference_enabled"] = service.inference_enabled
                snapshot["server"]["experimental_bet_action"] = service.experimental_bet_action
                snapshot["server"]["instance_id"] = service.instance_id
                snapshot["server"]["manual_feed_version"] = 1 if service.manual_feed is not None else None
                snapshot["automatic_startup"] = service.automatic_startup.snapshot(snapshot["capture_session"]) if service.automatic_startup is not None else None
                snapshot["capture_control"] = service.capture_controls(snapshot["capture_session"])
                self._send(200, project_browser_snapshot(snapshot))
            elif self.path.startswith("/api/evidence/"):
                evidence_id = self.path.removeprefix("/api/evidence/")
                png = (service.manual_feed.visual.archive.read(evidence_id)
                       if service.manual_feed is not None else None)
                if png is None:
                    self._send(404, {"error": "evidence-unavailable"})
                else:
                    self._send_bytes(200, png, "image/png")
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
            if self.path not in ("/v1/laya/predict", "/v1/laya/predict-batch", "/api/capture/start", "/api/capture/stop"):
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
            if n > (512 if self.path in ("/api/capture/start", "/api/capture/stop") else MAX_BODY):
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
            if self.path == "/api/capture/stop":
                status, payload = service.stop_capture(body)
                self._send(status, payload)
                return
            if self.path == "/api/capture/start":
                status, payload = service.start_capture(body)
                self._send(status, payload)
                return
            sessions = self.headers.get_all("X-Coinpoker-Session", [])
            instances = self.headers.get_all("X-Coinpoker-Service", [])
            binding = None
            if sessions or instances:
                if (len(sessions) != 1 or len(instances) != 1
                        or any(not re.fullmatch(r"[0-9a-f]{32}", value) for value in sessions + instances)):
                    self._send(409, {"error": "manual-session-ended"})
                    return
                binding = (sessions[0], instances[0])
            status, payload = service.predict(body, batch=self.path.endswith("predict-batch"), session_binding=binding)
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


def verify(pins, check_runtime=True, *, verified_files=None):
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
    def check_file(path, entry):
        before = os.stat(path)
        actual = sha256_file(path) if before.st_size == entry["size"] else None
        after = os.stat(path)
        stable = (before.st_size, before.st_mtime_ns, before.st_ino) == (after.st_size, after.st_mtime_ns, after.st_ino)
        matches = stable and before.st_size == entry["size"] and actual == entry["sha256"]
        if verified_files is not None:
            verified_files.append({"path": str(Path(path).absolute()), "sha256": actual, "size_bytes": after.st_size,
                                   "state": "verified" if matches else "unknown",
                                   "verified_at_unix_ms": time.time_ns() // 1_000_000})
        return matches

    for f in pins["model"]["files"]:
        p = os.path.join(snap, f["path"])
        if not os.path.exists(p):
            problems.append("missing base file %s" % f["path"])
        elif not check_file(p, f):
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
            elif not check_file(p, f):
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


def cmd_serve(pins, answers_log, batch_size, dashboard_only=True, live_config=None,
               auto_attach=False, practice_config=dashboard.DEFAULT_PROFILE, enable_inference=False,
                automatic_inference=False, *, experimental_bet_action=False, continuous_observation=False,
                manual_start=False, provenance_directory=None, diagnostic_streams=None):
    if live_config or auto_attach or practice_config != dashboard.DEFAULT_PROFILE and not automatic_inference:
        raise ValueError("use --automatic-inference with --practice-config; legacy attachment arguments are unsupported")
    if automatic_inference and (not enable_inference or dashboard_only):
        raise ValueError("automatic observation requires inference enabled and dashboard-only disabled")
    if enable_inference and dashboard_only:
        raise ValueError("choose dashboard-only or enable-inference, not both")
    if type(experimental_bet_action) is not bool or experimental_bet_action and not automatic_inference:
        raise ValueError("experimental bet/action diagnostics require bounded automatic inference approval")
    if type(manual_start) is not bool or manual_start and not automatic_inference:
        raise ValueError("manual start requires the configured automatic source selector")
    if (type(continuous_observation) is not bool or continuous_observation and
            (not automatic_inference or not enable_inference or dashboard_only or experimental_bet_action)):
        raise ValueError("continuous observation requires inference and automatic opt-ins without experimental diagnostics")
    srv = pins["server"]
    if int(srv["port"]) != PORT:
        raise ValueError("Laya dashboard/model service requires port 18090; no alternate-port fallback")
    log_fn = None
    fh = None
    diagnostics = dict(diagnostic_streams or {})
    if answers_log:
        path = dashboard.local_path(answers_log)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = path.open("a", encoding="utf-8", newline="\n")
        log_lock = threading.Lock()
        logged_bytes = path.stat().st_size
        answer_counter = provenance.DiagnosticCounter()
        answer_counter.value.update(preexisting_bytes=logged_bytes, cap_bytes=manual_capture.MAX_LOG)
        diagnostics["answers"] = answer_counter.value

        def log_fn(rec):
            nonlocal logged_bytes
            with log_lock:
                line = json.dumps(rec) + "\n"
                size = len(line.encode("utf-8"))
                if continuous_observation and logged_bytes + size > manual_capture.MAX_LOG:
                    answer_counter.account(size, 0)
                    return
                try:
                    if fh.write(line) != len(line):
                        raise OSError("short-diagnostic-write")
                    fh.flush()
                except (OSError, ValueError):
                    answer_counter.fail_write(size)
                    raise
                logged_bytes += size
                answer_counter.account(size, size)
    ft = pins["model"].get("finetuned") or {}
    meta = {"checkpoint": ft.get("path"), "base_revision": pins["model"]["revision"],
            "calibrated": False, "temperature_calibration_loaded": False,
            "acceptance_floors_loaded": False,
            "quality_gate": "failed", "seated_advice_supported": False}
    service = Service(srv["alias"], meta, log_fn=log_fn, experimental_bet_action=experimental_bet_action)
    model = pins.get("model", {})
    model_snapshot = (snapshot_dir(pins) if model.get("repository") and model.get("hf_home")
                      else str(ROOT / "models/unknown"))
    try:
        service.provenance = provenance.service_identity(ROOT, service.instance_id, pins, model_snapshot,
            argv=[sys.executable, str(Path(SCRIPTS) / "laya-server.py"), *sys.argv[1:]],
            options={"enable_inference": enable_inference, "automatic_inference": automatic_inference,
                     "continuous_observation": continuous_observation, "manual_start": manual_start,
                     "experimental_bet_action": experimental_bet_action,
                     "batch_size": batch_size or srv.get("batch_size", 32), "practice_config": practice_config,
                     "answers_log": answers_log})
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        service.provenance = {"version": 1, "instance_id": service.instance_id, "complete": False,
                              "state": "unknown", "build": {"complete": False, "state": "unknown"}}
    service.provenance["diagnostic_streams"] = diagnostics

    def publish_provenance():
        streams = {name: dict(row) for name, row in diagnostics.items()}
        service.provenance["diagnostics_complete"] = all(not row["truncated"] and row["accounting_complete"]
                                                        for row in streams.values())
        if provenance_directory is not None:
            try:
                directory = manual_capture.private_path(Path(provenance_directory), root=ROOT)
                directory.mkdir(parents=True, exist_ok=True)
                service.provenance["publication_state"] = "known"
                manual_capture.write_json(directory / (service.instance_id + ".json"),
                                          {**service.provenance, "diagnostic_streams": streams})
            except (OSError, ValueError):
                # Missing private publication is incomplete evidence, not a new startup gate.
                service.provenance["complete"] = False
                service.provenance["publication_state"] = "unknown"

    publish_provenance()
    service.inference_enabled = enable_inference
    httpd = BoundedHTTPServer((HOST, PORT), make_handler(None, srv["alias"], meta, log_fn, service))

    def initialize():
        service.state.set_model("loading")
        try:
            verified_files = []
            problems = verify(pins, verified_files=verified_files)
            service.provenance["model"] = provenance.model_identity(pins, ROOT, model_snapshot, verified_files)
            service.provenance["complete"] = bool(not problems and service.provenance["build"]["complete"]
                                                   and service.provenance["build"]["runtime"]["complete"]
                                                   and service.provenance["model"]["complete"])
            publish_provenance()
            if problems:
                service.state.set_model("failed", "verification-failed")
                print(json.dumps({"event": "laya-verify", "ok": False, "problems": problems}), flush=True)
                return
            if service.shutting_down.is_set():
                return
            engine = Engine(pins, batch_size=batch_size or srv.get("batch_size", 32),
                            experimental_bet_action=experimental_bet_action)
            if service.shutting_down.is_set():
                return
            from PIL import Image

            warm = Image.new("RGB", (64, 64), (200, 30, 30))
            t0 = time.perf_counter()
            engine.predict([warm], "warm-up", {"c": {"type": "choice", "instructions": "What colour is the image?",
                                                      "criteria": ["red", "blue", "green"]}})
            warm_ms = round((time.perf_counter() - t0) * 1000, 1)
            if service.shutting_down.is_set():
                return
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
    if enable_inference:
        service.manual_feed = dashboard.ManualSessionFeed(service.state, service.instance_id)
        service.manual_feed.start()
        service.state.set_model("loading")
        threading.Thread(target=initialize, daemon=True).start()
        if automatic_inference:
            service.automatic_startup = manual_capture.AutomaticStart(service, profile=practice_config,
                                                                      continuous_observation=continuous_observation)
            if manual_start:
                service.automatic_startup.status, service.automatic_startup.reason = "stopped", "operator-start-required"
            else:
                service.automatic_startup.start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.shutting_down.set()
        try:
            if service.manual_feed is not None:
                service.manual_feed.stop()
        finally:
            try:
                if service.automatic_startup is not None:
                    service.automatic_startup.stop()
            finally:
                httpd.server_close()
                try:
                    if fh is not None:
                        try:
                            fh.close()
                        except (OSError, ValueError):
                            answer_counter.fail_write(0)
                            raise
                finally:
                    publish_provenance()
    return 0


class BoundedErrorLog:
    encoding = "utf-8"

    def __init__(self, stream):
        self.stream, self.lock = stream, threading.Lock()
        self.counter = provenance.DiagnosticCounter()
        self.counter.value["cap_bytes"] = manual_capture.MAX_LOG

    def write(self, text):
        with self.lock:
            manual_capture._write_capped(self.stream, text.encode(self.encoding, errors="backslashreplace"), self.counter)
        return len(text)

    def flush(self):
        with self.lock:
            if not self.stream.closed:
                try:
                    self.stream.flush()
                except (OSError, ValueError):
                    self.counter.fail_write(0)
                    raise

    def isatty(self):
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", nargs="?", default="serve", choices=["serve", "fetch", "verify"])
    ap.add_argument("--answers-log", default=None, help="JSONL of answers and timings (no image data)")
    ap.add_argument("--batch-size", type=int, default=None)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dashboard-only", action="store_true", help="default: Monitor/Reference and session controls without loading the model")
    mode.add_argument("--enable-inference", action="store_true", help="load the pinned model; capture is configured separately")
    ap.add_argument("--automatic-inference", action="store_true", help="explicit one-shot bounded automatic observation approval; requires --enable-inference")
    ap.add_argument("--continuous-observation", action="store_true", help="same-source sustained observation; requires both inference opt-ins; evidence remains bounded")
    ap.add_argument("--manual-start", action="store_true", help="keep capture stopped until Start monitor; requires the configured automatic source selector")
    ap.add_argument("--stderr-log", default=None, help="private capped launcher diagnostic file; continuous observation only")
    ap.add_argument("--experimental-bet-action", action="store_true", help="explicit unvalidated p6/p7 diagnostics; requires bounded automatic inference approval")
    attachment = ap.add_mutually_exclusive_group()
    attachment.add_argument("--live-config", help="removed: automatic feeds are refused")
    attachment.add_argument("--auto-attach", action="store_true", help="removed: refused without starting a feed")
    ap.add_argument("--practice-config", default=dashboard.DEFAULT_PROFILE, help="private source profile for explicitly authorized automatic observation")
    a = ap.parse_args(argv)
    if a.live_config or a.auto_attach or a.practice_config != dashboard.DEFAULT_PROFILE and not a.automatic_inference:
        ap.error("automatic attachment disabled; use scripts/laya_capture.py start for manual source approval")
    if a.automatic_inference and (not a.enable_inference or a.command != "serve"):
        ap.error("--automatic-inference requires --enable-inference and serve")
    if a.manual_start and not a.automatic_inference:
        ap.error("--manual-start requires --automatic-inference")
    if a.experimental_bet_action and not a.automatic_inference:
        ap.error("--experimental-bet-action requires --automatic-inference")
    if a.continuous_observation and (not a.automatic_inference or not a.enable_inference
                                    or a.command != "serve" or a.experimental_bet_action):
        ap.error("--continuous-observation requires --enable-inference and --automatic-inference, without --experimental-bet-action")
    error_log = None
    if a.stderr_log:
        error_log = Path(a.stderr_log).resolve()
        if (not a.continuous_observation or error_log.parent != ROOT / ".local/laya/train"
                or not re.fullmatch(r"server-[0-9]{8}T[0-9]{9}Z\.stderr\.txt", error_log.name)):
            ap.error("--stderr-log requires continuous observation and a private launcher diagnostic path")
    pins = load_pins()
    if a.command == "verify":
        return cmd_verify(pins)
    if a.command == "fetch":
        return cmd_fetch(pins)
    diagnostic_streams = {}
    def serve():
        return cmd_serve(pins, a.answers_log, a.batch_size, not a.enable_inference, a.live_config,
                         a.auto_attach, a.practice_config, a.enable_inference, a.automatic_inference,
                          experimental_bet_action=a.experimental_bet_action, continuous_observation=a.continuous_observation,
                          manual_start=a.manual_start, provenance_directory=".local/laya/service-provenance",
                          diagnostic_streams=diagnostic_streams)
    if error_log is not None:
        with manual_capture.private_path(error_log).open("xb") as stream:
            logger = BoundedErrorLog(stream)
            diagnostic_streams["stderr"] = logger.counter.value
            with contextlib.redirect_stderr(logger):
                return serve()
    return serve()


if __name__ == "__main__":
    sys.exit(main())
