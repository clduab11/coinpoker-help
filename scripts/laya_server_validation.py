"""Stdlib-only protocol constants, request validation, and pinned-registry helpers for laya-server.py."""

import base64
import binascii
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import time

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
MAX_READOUT_PASSES = 8
MAX_READOUT_QUESTIONS = 64
MAX_READOUT_IMAGES = 64
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
# Provisional seated passes: defined and cropped by the client, absent from the
# it1 fitted floor table, so the wire floor is null and the client's own pass
# threshold is operative while thresholds.calibrated is false.
SEATED_PASSES = frozenset({"p1_hero_cards", "p3_to_call", "p3_hero_chips",
                           "p4_min_raise_to", "p4_max_raise_to"})
WAGER_PASSES = frozenset("p6_seat_%d_wager" % n for n in range(1, 7))
SCENE_PASSES = frozenset("p7_seat_%d_scene" % n for n in range(1, 7))
WAGER_NOTE = "Observed per-seat visible wager glyphs; not stack, street contribution or call cost."
SCENE_NOTE = "Observed per-seat visible scene only; not names, hidden cards, hand roster or actions."
EXPERIMENTAL_WAGER_NOTE = "Characters of one chip amount, in reading order."
EXPERIMENTAL_CHECKPOINT = "models/laya-vision/finetuned/20261009T190322Z-it1"
EXPERIMENTAL_MODEL_SHA256 = "84c008b976e72445ae07c58678af542b63f79548ad0a314f836f210bda3195a1"
# Measured F001 review geometry, still DRAFT/PENDING, not an approved registry.
EXPERIMENTAL_BOUNDS = {
    "wager": ((315, 172, 387, 232), (567, 199, 734, 311), (576, 376, 743, 496),
              (409, 422, 594, 506), (157, 376, 333, 496), (157, 199, 333, 311)),
    "scene": ((360, 44, 558, 200), (666, 93, 882, 272), (684, 350, 891, 555),
              (342, 478, 558, 680), (9, 350, 225, 555), (18, 93, 234, 272)),
}
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
POPUP_BINDING_SCOPE_KEYS = ("service_instance_id", "session_id", "capture_session_id", "source_id",
                            "native_source_id", "epoch", "generation", "source_process_created_at_100ns")


def project_browser_snapshot(snapshot):
    """Deep-copy a state DTO, replacing private popup identities with scoped opaque bindings."""
    projected = copy.deepcopy(snapshot)

    def visit(value):
        if isinstance(value, dict):
            scope = {key: value.get(key) for key in POPUP_BINDING_SCOPE_KEYS}
            for key, child in value.items():
                if key == "popup_window":
                    identity = json.dumps({"scope": scope, "popup_window": child}, sort_keys=True,
                        ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
                    value[key] = {"binding_id": hashlib.sha256(identity).hexdigest()}
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(projected)
    return projected


class RequestError(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status = status
        self.code = code


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


def pinned_file_entries(ft):
    """Normalize the shipped list manifest without changing its evidence hashes."""
    entries = ft.get("files")
    if not isinstance(entries, list):
        raise ValueError("fine-tuned-files-invalid")
    files = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("fine-tuned-files-invalid")
        name, size, digest = entry.get("path"), entry.get("size"), entry.get("sha256")
        if (not isinstance(name, str) or not name or Path(name).is_absolute()
                or "\\" in name or ":" in name or ".." in Path(name).parts or name in files
                or type(size) is not int or size <= 0
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("fine-tuned-files-invalid")
        files[name] = entry
    return files


def _canonical(value):
    # Case-normalized real form via os.path.realpath (unpatched by tests that
    # patch Path.resolve); raw and resolved strings can differ without any
    # redirection (8.3 short names on CI, junctions).
    import os
    return Path(os.path.normcase(os.path.realpath(os.fspath(value))))


def load_acceptance_floors_from_repo(pins, repo, reject_constant):
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
    root = Path(repo)
    expected = _canonical(root) / checkpoint
    base = root / checkpoint
    path = base / filename
    if (base.resolve() != expected or not _canonical(path).is_relative_to(_canonical(root))
            or path.resolve() != expected / filename or path.stat().st_size != size):
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

    report = json.loads(data, parse_constant=reject_constant, parse_float=finite, object_pairs_hook=unique)
    floors = report.get("thresholds_per_pass") if isinstance(report, dict) else None
    if (not isinstance(report, dict) or report.get("ckpt") != checkpoint
            or not isinstance(floors, dict) or set(floors) != ACCEPTANCE_PASSES
            or any(type(value) not in (int, float) or not 0 <= value <= 1 or not math.isfinite(value)
                    for value in floors.values())):
        raise ValueError("acceptance-report-invalid")
    return {key: float(value) for key, value in floors.items()}


def load_seat_registry_from_root(pins, kind, root, reject_constant):
    """Optional per-seat evidence, absent for it1. Never caller or global approval."""
    ft = pins["model"].get("finetuned") or {}
    if kind not in ("wager", "scene"):
        raise ValueError("invalid registry kind")
    prefix = "p6" if kind == "wager" else "p7"
    name = ft.get(kind + "_registry")
    if name is None:
        return {}
    entries = pinned_file_entries(ft)
    files = {name: entry["sha256"] for name, entry in entries.items()}
    if not isinstance(name, str) or name not in files:
        raise ValueError("wager-registry-not-pinned")
    base = (Path(root) / ft["path"]).resolve()
    if not base.is_relative_to(Path(root).resolve()):
        raise ValueError("wager-registry-path")

    def read_pinned(filename):
        path = (base / filename).resolve()
        size = entries[filename]["size"]
        if not path.is_relative_to(base) or size > MAX_BODY or path.stat().st_size != size:
            raise ValueError("wager-evidence-path")
        with path.open("rb") as stream:
            raw = stream.read(size + 1)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != files[filename]:
            raise ValueError("wager-evidence-hash")
        return json.loads(raw.decode("utf-8"), parse_constant=reject_constant)

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


def experimental_descriptor(pid):
    if pid not in WAGER_PASSES | SCENE_PASSES:
        raise ValueError("experimental-descriptor-invalid")
    seat = int(pid.split("_")[2])
    kind = "wager" if pid in WAGER_PASSES else "scene"
    return {"version": 1, "pass": pid, "seat": seat,
            "region": {"id": "seat_%d_%s" % (seat, kind), "reference_dimensions": [900, 686],
                       "bounds": list(EXPERIMENTAL_BOUNDS[kind][seat-1])},
            "diagnostic_only": True, "training": "unvalidated",
            "geometry_status": "DRAFT", "human_review": "PENDING"}


def load_experimental_metadata_from_root(pins, floors, root, repo, reject_constant):
    """Bind transfer diagnostics to it1's pinned donor calibration, not target proof."""
    ft = pins["model"]["finetuned"]
    entries = pinned_file_entries(ft)
    if (ft.get("path") != EXPERIMENTAL_CHECKPOINT
            or entries.get("model.safetensors", {}).get("sha256") != EXPERIMENTAL_MODEL_SHA256
            or ft.get("calibration_file") != "laya-calibration.json"
            or ft.get("acceptance_file") != "calibration.json"
            or floors != load_acceptance_floors_from_repo(pins, repo, reject_constant)):
        raise ValueError("experimental-candidate-unavailable")
    donor = floors.get("p5_seat_1_stack")
    if type(donor) not in (int, float) or not 0 <= donor <= 1 or not math.isfinite(donor):
        raise ValueError("experimental-donor-floor-unavailable")
    entry = entries.get(ft["calibration_file"], {})
    size = entry.get("size")
    resolved_root = Path(root).resolve()
    base = resolved_root / ft["path"]
    path = (base / ft["calibration_file"]).resolve()
    if (type(size) is not int or not 0 < size <= MAX_ACCEPTANCE_REPORT
            or base.resolve() != base or path != base / ft["calibration_file"]
            or path.stat().st_size != size):
        raise ValueError("experimental-temperature-unavailable")
    with path.open("rb") as stream:
        raw = stream.read(MAX_ACCEPTANCE_REPORT + 1)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
        raise ValueError("experimental-temperature-unavailable")
    calibration = json.loads(raw, parse_constant=reject_constant)
    temperatures = calibration.get("temperatures") if isinstance(calibration, dict) else None
    checkpoint = calibration.get("checkpoint") if isinstance(calibration, dict) else None
    if (not isinstance(temperatures, dict) or not isinstance(checkpoint, dict)
            or checkpoint.get("ckpt") != ft["path"]
            or type(temperatures.get("choice")) not in (int, float)
            or not 0 < temperatures["choice"] < 1000 or not math.isfinite(temperatures["choice"])):
        raise ValueError("experimental-temperature-unavailable")
    return {"model_sha256": EXPERIMENTAL_MODEL_SHA256,
            "temperature_calibration_sha256": entry["sha256"],
            "donor_pass": "p5_seat_1_stack", "inherited_cutoff": max(0.8, float(donor))}


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
        if (qid not in allowed_ids and not re.fullmatch(r"g[1-8]|board_[1-5]_(rank|suit)|hero_[12]_(rank|suit)", qid)):
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


def decode_and_prepare_pass(engine, layout, style, raw, questions, *, catch_prep_errors=False):
    """Decode raw PNGs and optionally segment glyphs, returning (images, questions, segments, decode_ms, prep_ms)."""
    t0 = time.perf_counter()
    try:
        images = engine.decode(raw)
    except Exception as exc:
        raise RequestError(400, "invalid-image") from exc
    t1 = time.perf_counter()
    segments = None
    if layout == "glyphs":
        try:
            images, info = engine.prep.segment_glyphs(images[0], style, MAX_GLYPHS)
            segments = {"n": int(info["n"]), "overflow": bool(info["overflow"])}
        except Exception as exc:
            if catch_prep_errors:
                raise RequestError(400, "invalid-image") from exc
            raise
        questions = {qid: q for qid, q in questions.items() if int(qid[1:]) <= len(images)}
    t2 = time.perf_counter()
    return images, questions, segments, (t1 - t0) * 1000.0, (t2 - t1) * 1000.0
