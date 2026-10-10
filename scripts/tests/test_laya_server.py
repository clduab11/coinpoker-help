"""Stdlib-only tests for scripts/laya-server.py (no torch, laya, PIL or numpy needed)."""

import base64
import copy
import hashlib
import builtins
import copy
from email.message import Message
import hashlib
import importlib.util
import io
import json
import struct
import threading
import tempfile
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.request
import zlib
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("laya_server", SCRIPTS / "laya-server.py")
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)

ALIAS = "coinpoker-laya-vision"
FLOORS = {"p0_full": 0.995, "p2_board": 1.0, "p3_pot": 0.8,
          **{"p5_seat_%d_stack" % n: 0.8 for n in range(1, 7)}}


def png(w=4, h=3):
    raw = b"".join(b"\x00" + b"\x10\x20\x30" * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (srv.PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def b64(data):
    return base64.b64encode(data).decode("ascii")


def body(**over):
    b = {"model": ALIAS, "pass": "p2_board", "note": "Card slot images, left to right.", "layout": "slots",
         "images_png_b64": [b64(png())] * 2,
         "questions": {"board_1_rank": {"type": "choice", "instructions": "Rank?", "criteria": {"A": "ace", "K": "king"}},
                       "ev_pot": {"type": "noul", "instructions": "Pot?"}}}
    b.update(over)
    return b


class FakePrep:
    def __init__(self, n, overflow=False):
        self.n, self.overflow = n, overflow

    def segment_glyphs(self, img, style, max_glyphs):
        if self.overflow:
            return [], {"n": 9, "overflow": True}
        return ["glyph"] * self.n, {"n": self.n, "overflow": False}


class FakeEngine:
    def __init__(self, n=3, overflow=False, fail=False):
        self.prep = FakePrep(n, overflow)
        self.acceptance_floors = dict(FLOORS)
        self.calls = []
        self.batch_calls = []
        self.wager_registry = {}
        self.scene_registry = {}
        self.fail = fail

    def decode(self, raw):
        return ["img"] * len(raw)

    def predict(self, images, note, questions):
        if self.fail:
            raise RuntimeError("boom with secret payload")
        self.calls.append((len(images), sorted(questions)))
        answers = {}
        for qid, q in questions.items():
            if q["type"] == "choice":
                keys = list(q["criteria"]) if not isinstance(q["criteria"], dict) else list(q["criteria"].keys())
                answers[qid] = {"type": "choice", "choice": keys[0], "probabilities": {k: 1.0 / len(keys) for k in keys},
                                "confidence": 0.5, "action": {}, "truncated": {"options": []} if qid == "x" else None}
            else:
                answers[qid] = {"type": "noul", "noul": 0.9, "confidence": 0.9, "action": {}}
        return {"answers": answers, "provenance": {"secret": True}}

    def predict_batch(self, samples):
        self.batch_calls.append(samples)
        return [self.predict(images, note, questions) for images, note, questions in samples]


class ValidateTests(unittest.TestCase):
    def test_accepts_valid_slots_request(self):
        pid, note, layout, style, raw, qs = srv.validate_request(body(), ALIAS)
        self.assertEqual((pid, layout, len(raw), sorted(qs)), ("p2_board", "slots", 2, ["board_1_rank", "ev_pot"]))

    def test_rejects(self):
        cases = [
            (body(model="other"), 404, "unknown-model"),
            (body(layout="tiles"), 400, "malformed"),
            (body(layout="full"), 400, "malformed"),  # full takes exactly one image
            (body(layout="glyphs", images_png_b64=[b64(png())]), 400, "malformed"),  # style missing
            (body(images_png_b64=[]), 400, "malformed"),
            (body(images_png_b64=[b64(png())] * 9), 400, "malformed"),
            (body(images_png_b64=["not base64!"]), 400, "invalid-image"),
            (body(images_png_b64=[b64(b"GIF89a....................")]), 400, "invalid-image"),
            (body(images_png_b64=[b64(srv.PNG_SIG + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 5000, 5000) + b"\x08\x02\x00\x00\x00")]), 400, "image-too-large"),
            (body(questions={}), 400, "malformed"),
            (body(questions={"Bad-Id": {"type": "noul", "instructions": "x"}}), 400, "malformed"),
            (body(questions={"q": {"type": "score", "instructions": "x"}}), 400, "malformed"),
            (body(questions={"q": {"type": "choice", "instructions": "x", "criteria": ["only"]}}), 400, "malformed"),
            (body(questions={"q": {"type": "noul", "instructions": "x" * 2001}}), 400, "malformed"),
            (body(**{"pass": "../etc"}), 400, "malformed"),
            (body(layout="glyphs", glyph_style="white", images_png_b64=[b64(png())],
                  questions={"g9": {"type": "noul", "instructions": "x"}}), 400, "malformed"),
            ([1, 2], 400, "malformed"),
        ]
        for b, status, code in cases:
            with self.subTest(code=code, b=str(b)[:60]):
                with self.assertRaises(srv.RequestError) as cm:
                    srv.validate_request(b, ALIAS)
                self.assertEqual((cm.exception.status, cm.exception.code), (status, code))

    def test_ordered_pairs_become_an_ordered_dict(self):
        qs = {"r": {"type": "choice", "instructions": "x", "criteria": [["2", "two"], ["A", "ace"], ["10", "ten"]]}}
        *_, out = srv.validate_request(body(questions=qs), ALIAS)
        self.assertEqual(list(out["r"]["criteria"].items()), [("2", "two"), ("A", "ace"), ("10", "ten")])
        for bad in ([["a", "x"], ["a", "y"]], [["a", 1], ["b", "y"]]):
            with self.assertRaises(srv.RequestError):
                srv.validate_request(body(questions={"r": {"type": "choice", "instructions": "x", "criteria": bad}}), ALIAS)

    def test_too_many_questions(self):
        qs = {"q%d" % i: {"type": "noul", "instructions": "x"} for i in range(65)}
        with self.assertRaises(srv.RequestError):
            srv.validate_request(body(questions=qs), ALIAS)


class HandleTests(unittest.TestCase):
    def test_slots_happy_path_shape(self):
        status, payload = srv.handle_predict(FakeEngine(), ALIAS, json.dumps(body()).encode())
        self.assertEqual(status, 200)
        self.assertEqual(set(payload), {"model", "pass", "answers", "timing_ms", "acceptance_floor"})
        self.assertEqual(payload["acceptance_floor"], 1.0)
        a = payload["answers"]["board_1_rank"]
        self.assertEqual(set(a), {"type", "confidence", "truncated", "choice", "probabilities"})
        self.assertNotIn("provenance", json.dumps(payload))
        self.assertEqual(payload["answers"]["ev_pot"]["noul"], 0.9)

    def test_glyphs_answers_only_segmented_glyphs(self):
        qs = {"g%d" % k: {"type": "choice", "instructions": "c", "criteria": {"0": "zero", "1": "one"}} for k in range(1, 9)}
        eng = FakeEngine(n=3)
        b = body(layout="glyphs", glyph_style="white", images_png_b64=[b64(png())], questions=qs, **{"pass": "p3_pot"})
        status, payload = srv.handle_predict(eng, ALIAS, json.dumps(b).encode())
        self.assertEqual(status, 200)
        self.assertEqual(payload["segments"], {"n": 3, "overflow": False})
        self.assertEqual(sorted(payload["answers"]), ["g1", "g2", "g3"])
        self.assertEqual(eng.calls, [(3, ["g1", "g2", "g3"])])

    def test_glyphs_overflow_and_empty_skip_predict(self):
        qs = {"g1": {"type": "noul", "instructions": "c"}}
        for eng, seg in ((FakeEngine(overflow=True), {"n": 9, "overflow": True}), (FakeEngine(n=0), {"n": 0, "overflow": False})):
            b = body(layout="glyphs", glyph_style="gold", images_png_b64=[b64(png())], questions=qs)
            status, payload = srv.handle_predict(eng, ALIAS, json.dumps(b).encode())
            self.assertEqual((status, payload["answers"], payload["segments"]), (200, {}, seg))
            self.assertEqual(eng.calls, [])

    def test_errors_never_echo_payload(self):
        b = body()
        status, payload = srv.handle_predict(FakeEngine(fail=True), ALIAS, json.dumps(b).encode())
        self.assertEqual((status, payload), (500, {"error": "predict-failed"}))
        status, payload = srv.handle_predict(FakeEngine(), ALIAS, b"{not json")
        self.assertEqual((status, payload), (400, {"error": "malformed"}))

    def test_answers_log_has_no_image_data(self):
        logged = []
        srv.handle_predict(FakeEngine(), ALIAS, json.dumps(body()).encode(), logged.append)
        self.assertEqual(len(logged), 1)
        text = json.dumps(logged[0])
        self.assertNotIn(b64(png()), text)
        self.assertEqual(set(logged[0]), {"utc", "pass", "timing_ms", "segments", "answers"})

    def test_every_trained_pass_returns_only_the_engine_floor_not_request_overrides(self):
        for pid, floor in FLOORS.items():
            with self.subTest(pid=pid):
                b = body(**{"pass": pid, "acceptance_floor": 0, "thresholds_per_pass": {pid: 0.1}})
                status, payload = srv.handle_predict(FakeEngine(), ALIAS, json.dumps(b).encode())
                self.assertEqual(status, 200)
                self.assertEqual(payload["acceptance_floor"], floor)

    def test_unknown_untrained_or_missing_floor_rejects_before_decode_or_predict(self):
        for pid in ("p1_hero", "p4_buttons", "p6_to_call", "p7_hero_stack", "p8_raise_bounds", "unknown"):
            engine = FakeEngine()
            engine.acceptance_floors[pid] = 0.8
            engine.decode = Mock(side_effect=AssertionError("must not decode"))
            engine.predict = Mock(side_effect=AssertionError("must not predict"))
            result = srv.handle_predict(engine, ALIAS, json.dumps(body(**{"pass": pid})).encode())
            self.assertEqual(result, (503, {"error": "acceptance-floor-unavailable"}))
            engine.decode.assert_not_called()
            engine.predict.assert_not_called()
        for floor in (None, True, "1", -0.1, 1.01, float("nan"), float("inf"), 10 ** 1000):
            with self.subTest(floor=str(floor)[:30]):
                engine = FakeEngine()
                engine.acceptance_floors["p2_board"] = floor
                engine.decode = Mock()
                self.assertEqual(srv.handle_predict(engine, ALIAS, json.dumps(body()).encode()),
                                 (503, {"error": "acceptance-floor-unavailable"}))
                engine.decode.assert_not_called()
        for floors in (None, {}, []):
            engine = FakeEngine()
            engine.acceptance_floors = floors
            self.assertEqual(srv.handle_predict(engine, ALIAS, json.dumps(body()).encode()),
                             (503, {"error": "acceptance-floor-unavailable"}))

    def test_doctor_probe_is_diagnostic_only_with_null_floor_even_if_spoofed(self):
        engine = FakeEngine()
        engine.acceptance_floors["doctor_probe"] = float("nan")
        b = body(**{"pass": "doctor_probe", "acceptance_floor": 0.8})
        status, payload = srv.handle_predict(engine, ALIAS, json.dumps(b).encode())
        self.assertEqual(status, 200)
        self.assertIsNone(payload["acceptance_floor"])
        self.assertNotIn("NaN", json.dumps(payload, allow_nan=False))
        state = srv.Service(ALIAS, {"acceptance_floors_loaded": True, "calibrated": True}, engine).state.snapshot()
        self.assertTrue(state["server"]["acceptance_floors_loaded"])
        self.assertFalse(state["server"]["temperature_calibration_loaded"])
        self.assertEqual(state["server"]["quality_gate"], "failed")
        self.assertFalse(state["server"]["advice_ready"])

    def test_nonfinite_request_is_malformed_without_engine_calls(self):
        engine = FakeEngine()
        engine.decode = Mock()
        self.assertEqual(srv.handle_predict(engine, ALIAS, json.dumps(body(extra=float("nan"))).encode()),
                         (400, {"error": "malformed"}))
        engine.decode.assert_not_called()


class BatchTests(unittest.TestCase):
    def batch(self, seats=(1, 2), **override):
        questions = {"g%d" % n: {"type": "choice", "instructions": "Which character is shown in image %d?" % n,
                                 "criteria": [["0", "zero"], ["1", "one"]]} for n in range(1, 9)}
        requests = [body(layout="glyphs", glyph_style="gold", note="Characters of one chip amount, in reading order.",
                         images_png_b64=[b64(png())], questions=questions,
                         **{"pass": "p5_seat_%d_stack" % seat}) for seat in seats]
        return {"model": ALIAS, "batch": requests, **override}

    def handle(self, engine, value):
        return srv.handle_predict_batch(engine, ALIAS, json.dumps(value).encode())

    def test_original_independent_states_and_floors_survive_one_batch_admission(self):
        engine = FakeEngine()
        engine.acceptance_floors["p5_seat_2_stack"] = 0.95
        value = self.batch()
        value["batch"][0]["acceptance_floor"] = 0
        value["batch"][1]["acceptance_floor"] = 0
        status, result = self.handle(engine, value)
        self.assertEqual(status, 200)
        self.assertEqual(len(engine.batch_calls), 1)
        self.assertEqual(len(engine.batch_calls[0]), 2)
        for images, note, questions in engine.batch_calls[0]:
            self.assertEqual(images, ["glyph"] * 3)
            self.assertEqual(note, value["batch"][0]["note"])
            self.assertEqual(list(questions), ["g1", "g2", "g3"])
            self.assertEqual(questions["g1"]["instructions"], "Which character is shown in image 1?")
        self.assertEqual([r["pass"] for r in result["results"]], ["p5_seat_1_stack", "p5_seat_2_stack"])
        self.assertEqual([r["acceptance_floor"] for r in result["results"]], [0.8, 0.95])
        self.assertTrue(all(r["timing_shared_batch"] for r in result["results"]))
        self.assertNotIn("provenance", json.dumps(result))

    def test_all_six_physical_stacks_are_distinct(self):
        status, result = self.handle(FakeEngine(), self.batch(seats=range(1, 7)))
        self.assertEqual(status, 200)
        self.assertEqual([r["pass"] for r in result["results"]],
                         ["p5_seat_%d_stack" % n for n in range(1, 7)])
        self.assertEqual(len(result["results"]), 6)

    def test_empty_or_overflow_is_not_zero_and_never_calls_model(self):
        for engine in (FakeEngine(n=0), FakeEngine(overflow=True)):
            status, result = self.handle(engine, self.batch())
            self.assertEqual(status, 200)
            self.assertTrue(all(r["answers"] == {} for r in result["results"]))
            self.assertEqual(engine.batch_calls, [])
            self.assertNotIn("amount", json.dumps(result))

    def test_unknown_wager_missing_floor_or_incompatible_batch_never_decodes(self):
        value = self.batch()
        missing = FakeEngine()
        missing.acceptance_floors.pop("p5_seat_2_stack")
        missing.decode = Mock()
        self.assertEqual(self.handle(missing, value), (503, {"error": "acceptance-floor-unavailable"}))
        missing.decode.assert_not_called()
        cases = [self.batch(seats=(1, 1)), self.batch(seats=()), self.batch(seats=range(1, 8))]
        wager = self.batch()
        wager["batch"][0]["pass"] = "p6_seat_1_wager"
        cases.append(wager)
        white = self.batch()
        white["batch"][0]["glyph_style"] = "white"
        cases.append(white)
        arbitrary = self.batch()
        arbitrary["batch"][0]["questions"] = {"g1": {"type": "noul", "instructions": "x"}}
        cases.append(arbitrary)
        for case in cases:
            engine = FakeEngine()
            engine.decode = Mock()
            status, _ = self.handle(engine, case)
            self.assertEqual(status, 400)
            engine.decode.assert_not_called()

    def test_batch_errors_do_not_echo_backend_or_input(self):
        self.assertEqual(self.handle(FakeEngine(fail=True), self.batch()),
                         (500, {"error": "predict-failed"}))
        engine = FakeEngine()
        engine.predict_batch = Mock(return_value=[])
        self.assertEqual(self.handle(engine, self.batch()), (500, {"error": "predict-failed"}))
        self.assertEqual(srv.handle_predict_batch(FakeEngine(), ALIAS, b'{"model":NaN}'),
                         (400, {"error": "malformed"}))

    def test_single_and_batch_share_same_nonblocking_gpu_lock(self):
        engine = FakeEngine()
        service = srv.Service(ALIAS, engine=engine)
        with service.inference:
            self.assertEqual(service.predict(json.dumps(self.batch()).encode(), batch=True),
                             (503, {"error": "inference-busy"}))
            self.assertEqual(service.predict(json.dumps(body()).encode()),
                             (503, {"error": "inference-busy"}))
        self.assertEqual(engine.batch_calls, [])

    def test_safe_diagnostics_show_negative_noul_score_and_omit_prose(self):
        answers = {"ev_pot": {"type": "noul", "noul": 0.01, "truncated": False},
                   "screen_kind": {"type": "choice", "choice": "PRIVATE-NAME",
                                   "probabilities": {"PRIVATE-NAME": 1}, "truncated": False},
                   "secret_identifier": {"type": "choice", "choice": "A",
                                         "probabilities": {"A": 1}, "truncated": False}}
        result = srv.answer_diagnostics("p0_full", answers, 0.995)
        self.assertEqual(list(result), ["ev_pot"])
        self.assertIs(result["ev_pot"]["v"], False)
        self.assertEqual(result["ev_pot"]["p"], 0.99)
        self.assertEqual(result["ev_pot"]["reason"], "below-fitted-floor")
        self.assertTrue(result["ev_pot"]["score_only_not_admission"])
        self.assertNotIn("PRIVATE", json.dumps(result))


class WagerTests(unittest.TestCase):
    def capability(self, seat=1):
        return {"registry_version": 1, "model_alias": ALIAS, "seat": seat, "pass": "p6_seat_%d_wager" % seat,
                "region": {"id": "seat_%d_wager" % seat, "reference_dimensions": [879, 670],
                           "bounds": [617, 218, 674, 250]}, "fitted_floor": .999,
                "trained_candidate": True, "candidate_sha256": "1" * 64, "model_sha256": "2" * 64,
                "capability_evidence_sha256": "3" * 64, "held_out_approved": True,
                "human_verified": True, "provenance": "observation-only-calibrated-pass"}

    def request(self, capability):
        value = BatchTests().batch()["batch"][0]
        value.update({"pass": capability["pass"], "glyph_style": "white", "wager_capability": capability,
                      "note": srv.WAGER_NOTE, "questions": srv.wager_questions()})
        return value

    def test_default_it1_never_requests_or_inherits_pot_floor_for_a_wager(self):
        capability = self.capability()
        engine = FakeEngine()
        engine.decode = Mock()
        self.assertEqual(srv.handle_predict(engine, ALIAS, json.dumps(self.request(capability)).encode()),
                         (503, {"error": "wager-capability-unavailable"}))
        engine.decode.assert_not_called()
        self.assertEqual(srv.load_wager_registry({"model": {"finetuned": {}}, "server": {"alias": ALIAS}}), {})

    def test_all_six_registered_wagers_return_distinct_proof_and_own_floor(self):
        engine = FakeEngine()
        for seat in range(1, 7):
            capability = self.capability(seat)
            engine.wager_registry[capability["pass"]] = capability
            status, value = srv.handle_predict(engine, ALIAS, json.dumps(self.request(capability)).encode())
            self.assertEqual(status, 200)
            self.assertEqual(value["pass"], capability["pass"])
            self.assertEqual(value["wager_capability"], capability)
            self.assertEqual(value["acceptance_floor"], .999)
            self.assertNotEqual(value["acceptance_floor"], engine.acceptance_floors["p3_pot"])

    def test_request_flags_numeric_booleans_wrong_hash_or_wrong_style_cannot_approve(self):
        capability = self.capability()
        cases = []
        for field, value in (("model_sha256", "4"*64), ("candidate_sha256", "5"*64),
                             ("fitted_floor", .8), ("human_verified", 1)):
            request = self.request(copy.deepcopy(capability))
            request["wager_capability"][field] = value
            cases.append(request)
        wrong_style = self.request(capability)
        wrong_style["glyph_style"] = "gold"
        cases.append(wrong_style)
        for request in cases:
            engine = FakeEngine()
            engine.wager_registry[capability["pass"]] = capability
            engine.decode = Mock()
            self.assertEqual(srv.handle_predict(engine, ALIAS, json.dumps(request).encode()),
                             (400, {"error": "wager-capability-mismatch"}))
            engine.decode.assert_not_called()

    def pinned_fixture(self, root, **metrics_override):
        base = root / "candidate"
        base.mkdir()
        model_hash = hashlib.sha256(b"SYNTHETIC-NOT-MODEL-WEIGHTS").hexdigest()
        metrics = {"fitted_floor": .999, "precision": 1.0, "coverage": .9,
                   "confident_items": 24, "positive_opportunities": 24,
                   "session_grouped": True, "calibration_separate_from_held_out": True,
                   **metrics_override}
        proof = {"schema_version": 1, "human_verification": "VERIFIED", "model_sha256": model_hash,
                 "passes": {"p6_seat_1_wager": metrics}}
        raw = json.dumps(proof).encode()
        (base / "qa.json").write_bytes(raw)
        files = {"model.safetensors": model_hash, "qa.json": hashlib.sha256(raw).hexdigest()}
        capability = self.capability()
        capability.pop("registry_version")
        capability.pop("model_alias")
        capability.update(model_sha256=model_hash, capability_evidence_sha256=files["qa.json"],
                          candidate_sha256=hashlib.sha256(json.dumps(files, sort_keys=True,
                              separators=(",", ":")).encode()).hexdigest())
        registry = {"version": 1, "model_alias": ALIAS, "passes": [capability]}
        raw = json.dumps(registry).encode()
        (base / "registry.json").write_bytes(raw)
        files["registry.json"] = hashlib.sha256(raw).hexdigest()
        return {"server": {"alias": ALIAS}, "model": {"finetuned": {
            "path": "candidate", "wager_registry": "registry.json", "files": files}}}

    def test_qualified_wager_cannot_change_question_vocabulary_or_request_player_ocr(self):
        capability = self.capability()
        engine = FakeEngine()
        engine.wager_registry[capability["pass"]] = capability
        engine.decode = Mock()
        request = self.request(capability)
        request["note"] = "Read a player name"
        self.assertEqual(srv.handle_predict(engine, ALIAS, json.dumps(request).encode()),
                         (400, {"error": "wager-template-mismatch"}))
        request = self.request(capability)
        request["questions"] = copy.deepcopy(request["questions"])
        request["questions"]["g1"]["instructions"] = "Read a player name"
        self.assertEqual(srv.handle_predict(engine, ALIAS, json.dumps(request).encode()),
                         (400, {"error": "wager-template-mismatch"}))
        engine.decode.assert_not_called()

    def test_loader_requires_pinned_model_candidate_human_and_grouped_quality_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pins = self.pinned_fixture(root)
            with patch.object(srv, "ROOT", root):
                result = srv.load_wager_registry(pins)
                self.assertEqual(list(result), ["p6_seat_1_wager"])
                self.assertEqual(result["p6_seat_1_wager"]["fitted_floor"], .999)
                self.assertEqual(result["p6_seat_1_wager"]["model_alias"], ALIAS)
                (root / "candidate/registry.json").write_bytes(b"{}")
                with self.assertRaisesRegex(ValueError, "wager-evidence-hash"):
                    srv.load_wager_registry(pins)

    def test_zero_confident_items_low_precision_coverage_or_ungrouped_data_is_failure(self):
        for override in ({"confident_items": 0}, {"precision": .989}, {"coverage": .849},
                         {"positive_opportunities": 19}, {"session_grouped": False},
                         {"calibration_separate_from_held_out": False}, {"fitted_floor": .8}):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pins = self.pinned_fixture(root, **override)
                with patch.object(srv, "ROOT", root):
                    self.assertEqual(srv.load_wager_registry(pins), {})


class SceneTests(unittest.TestCase):
    def capability(self, seat=1):
        value = WagerTests().capability(seat)
        value.update({"pass": "p7_seat_%d_scene" % seat,
                      "region": {**value["region"], "id": "seat_%d_scene" % seat}})
        return value

    def request(self, capability):
        questions = {qid: {"type": "choice", "instructions": instructions, "criteria": labels}
                     for qid, (instructions, labels) in srv.SCENE_QUESTIONS.items()}
        return body(**{"pass": capability["pass"], "note": srv.SCENE_NOTE, "layout": "slots",
                       "scene_capability": capability, "questions": questions,
                       "images_png_b64": [b64(png())]})

    def test_untrained_scene_never_decodes_and_cannot_inherit_p0_floor(self):
        engine = FakeEngine()
        engine.decode = Mock()
        self.assertEqual(srv.handle_predict(engine, ALIAS, json.dumps(self.request(self.capability())).encode()),
                         (503, {"error": "scene-capability-unavailable"}))
        engine.decode.assert_not_called()

    def test_six_registered_scene_states_preserve_exact_identity_and_closed_templates(self):
        engine = FakeEngine()
        for seat in range(1, 7):
            capability = self.capability(seat)
            engine.scene_registry[capability["pass"]] = capability
            status, value = srv.handle_predict(engine, ALIAS, json.dumps(self.request(capability)).encode())
            self.assertEqual(status, 200)
            self.assertEqual(value["scene_capability"], capability)
            self.assertEqual(value["acceptance_floor"], .999)
            self.assertEqual(set(value["answers"]), set(srv.SCENE_QUESTIONS))
        request = self.request(self.capability())
        request["questions"]["occupied"]["instructions"] = "Read a private player name"
        self.assertEqual(srv.handle_predict(engine, ALIAS, json.dumps(request).encode()),
                         (400, {"error": "scene-template-mismatch"}))
        request = self.request(self.capability())
        request["scene_capability"]["model_sha256"] = "4" * 64
        self.assertEqual(srv.handle_predict(engine, ALIAS, json.dumps(request).encode()),
                         (400, {"error": "scene-capability-mismatch"}))

    def pinned_fixture(self, root, bad_field=None):
        pins = WagerTests().pinned_fixture(root)
        ft = pins["model"]["finetuned"]
        ft["scene_registry"] = ft.pop("wager_registry")
        fields = {name: {"precision": 1.0, "coverage": .96, "recall": .96,
                         "confident_items": 24, "positive_opportunities": 24}
                  for name in srv.SCENE_QUESTIONS}
        if bad_field:
            name, key, value = bad_field
            fields[name][key] = value
        proof = {"schema_version": 1, "human_verification": "VERIFIED",
                 "model_sha256": ft["files"]["model.safetensors"], "passes": {
                     "p7_seat_1_scene": {"fitted_floor": .999, "fields": fields,
                         "session_grouped": True, "calibration_separate_from_held_out": True}}}
        raw = json.dumps(proof).encode()
        (root / "candidate/qa.json").write_bytes(raw)
        ft["files"]["qa.json"] = hashlib.sha256(raw).hexdigest()
        entry = self.capability()
        entry.pop("registry_version")
        entry.pop("model_alias")
        entry.update(model_sha256=ft["files"]["model.safetensors"],
                     capability_evidence_sha256=ft["files"]["qa.json"],
                     candidate_sha256=hashlib.sha256(json.dumps(
                         {k: v for k, v in ft["files"].items() if k != ft["scene_registry"]},
                         sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        raw = json.dumps({"version": 1, "model_alias": ALIAS, "passes": [entry]}).encode()
        (root / "candidate/registry.json").write_bytes(raw)
        ft["files"]["registry.json"] = hashlib.sha256(raw).hexdigest()
        return pins

    def test_each_scene_family_has_strict_nonzero_quality_targets_and_acting_recall(self):
        for bad in (None, ("occupied", "coverage", .949), ("dealer", "precision", .989),
                    ("status", "coverage", .849), ("badge", "confident_items", 0),
                    ("acting", "recall", .949), ("acting", "positive_opportunities", 19)):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pins = self.pinned_fixture(root, bad)
                with patch.object(srv, "ROOT", root):
                    result = srv.load_scene_registry(pins)
                self.assertEqual(list(result), [] if bad else ["p7_seat_1_scene"])


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=srv.dashboard.ROOT / ".local")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        root_patch = patch.object(srv, "REPO", str(self.root))
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.checkpoint = "models/laya-vision/finetuned/synthetic-it1"
        self.report = {"ckpt": self.checkpoint, "thresholds_per_pass": dict(FLOORS)}
        self.pins = {"model": {"finetuned": {"path": self.checkpoint, "acceptance_file": "calibration.json", "files": []}}}

    def read_report(self, report=None, raw=None, **entry):
        raw = raw if raw is not None else json.dumps(self.report if report is None else report).encode()
        ft = self.pins["model"]["finetuned"]
        ft["files"] = [{"path": "calibration.json", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), **entry}]
        with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=len(raw))), \
                patch.object(Path, "open", return_value=io.BytesIO(raw)):
            return srv.load_acceptance_floors(self.pins)

    def test_exact_nine_floors_preserve_one_point_zero_and_point_995(self):
        self.assertEqual(self.read_report(), FLOORS)
        self.assertTrue(all(type(value) is float for value in self.read_report().values()))
        self.assertEqual(self.pins["model"]["finetuned"]["acceptance_file"], "calibration.json")

    def test_missing_unknown_or_nonfinite_floors_checkpoint_and_schema_fail_closed(self):
        cases = [[], {}, {**self.report, "ckpt": "wrong-checkpoint"},
                 {**self.report, "thresholds_per_pass": {}},
                 {**self.report, "thresholds_per_pass": {**FLOORS, "p1_hero": 0.8}},
                 {**self.report, "thresholds_per_pass": {key: value for key, value in FLOORS.items() if key != "p2_board"}}]
        cases += [{**self.report, "thresholds_per_pass": {**FLOORS, "p2_board": value}}
                  for value in (None, True, "1", -1, 1.0001, float("nan"), float("inf"), 10 ** 1000)]
        for report in cases:
            with self.subTest(report=str(report)[:100]), self.assertRaises(ValueError):
                self.read_report(report)
        duplicate = json.dumps(self.report)[:-1] + ',"thresholds_per_pass":' + json.dumps(FLOORS) + "}"
        overflow = json.dumps({**self.report, "temperatures": {"choice": "placeholder"}}).replace('"placeholder"', '1e999')
        for raw in (duplicate.encode(), b"{broken-json", b"null", overflow.encode()):
            with self.assertRaises(ValueError):
                self.read_report(raw=raw)

    def test_size_digest_and_pin_metadata_fail_without_unbounded_reads(self):
        for entry in ({"size": True}, {"size": 0}, {"size": srv.MAX_ACCEPTANCE_REPORT + 1},
                      {"size": 3.0}, {"sha256": None}, {"sha256": "not-a-digest"}, {"sha256": "0" * 64}):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                self.read_report(**entry)
        raw = json.dumps(self.report).encode()
        self.read_report()
        for measured in (len(raw) + 1, srv.MAX_ACCEPTANCE_REPORT + 1):
            with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=measured)), \
                    patch.object(Path, "open") as read, self.assertRaises(ValueError):
                srv.load_acceptance_floors(self.pins)
            read.assert_not_called()
        with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=len(raw))), \
                patch.object(Path, "open", return_value=io.BytesIO(raw + b" ")), self.assertRaises(ValueError):
            srv.load_acceptance_floors(self.pins)
        for pins in ({}, {"model": {}}, {"model": {"finetuned": {}}}):
            with self.assertRaises(ValueError):
                srv.load_acceptance_floors(pins)
        self.read_report()
        ft = self.pins["model"]["finetuned"]
        ft["files"] *= 2
        with self.assertRaises(ValueError):
            srv.load_acceptance_floors(self.pins)

    def test_report_growth_read_is_capped_even_after_valid_stat(self):
        raw = json.dumps(self.report).encode()
        self.read_report()
        stream = Mock()
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=False)
        stream.read.return_value = b"x" * (srv.MAX_ACCEPTANCE_REPORT + 1)
        with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=len(raw))), \
                patch.object(Path, "open", return_value=stream), self.assertRaises(ValueError):
            srv.load_acceptance_floors(self.pins)
        stream.read.assert_called_once_with(srv.MAX_ACCEPTANCE_REPORT + 1)

    def test_checkpoint_escape_or_redirect_and_missing_file_fail_closed(self):
        self.read_report()
        ft = self.pins["model"]["finetuned"]
        for checkpoint in ("../outside", str(self.root / "outside"), None):
            ft["path"] = checkpoint
            with self.assertRaises(ValueError):
                srv.load_acceptance_floors(self.pins)
        ft["path"] = self.checkpoint
        with patch.object(Path, "stat", side_effect=FileNotFoundError("PRIVATE-PATH")), self.assertRaises(OSError):
            srv.load_acceptance_floors(self.pins)
        real_resolve = Path.resolve
        candidate = self.root / self.checkpoint / "calibration.json"

        def redirected(path, *args, **kwargs):
            return self.root / "outside.json" if path == candidate else real_resolve(path, *args, **kwargs)

        with patch.object(Path, "resolve", redirected), self.assertRaises(ValueError):
            srv.load_acceptance_floors(self.pins)

    def test_invalid_report_precedes_every_heavy_import_and_model_load(self):
        real_import = builtins.__import__
        attempted = []

        def guarded(name, *args, **kwargs):
            if name.split(".", 1)[0] in ("laya", "laya_prep", "torch", "PIL", "numpy"):
                attempted.append(name)
                raise AssertionError("heavy import before floor validation")
            return real_import(name, *args, **kwargs)

        pins = copy.deepcopy(self.pins)
        with patch.object(builtins, "__import__", side_effect=guarded), self.assertRaises(ValueError):
            srv.Engine(pins)
        self.assertEqual(attempted, [])


class IntegrationTests(unittest.TestCase):
    def test_cli_routes_explicit_auto_and_strict_profile_without_loading_or_serving(self):
        for args, expected in ((["serve"], (False, None, False, srv.dashboard.DEFAULT_PROFILE)),
                               (["serve", "--dashboard-only"], (True, None, False, srv.dashboard.DEFAULT_PROFILE)),
                               (["serve", "--dashboard-only", "--auto-attach", "--practice-config", ".local/test.json"],
                                (True, None, True, ".local/test.json")),
                               (["serve", "--live-config", ".local/test.json"], (False, ".local/test.json", False, srv.dashboard.DEFAULT_PROFILE))):
            with self.subTest(args=args), patch.object(srv, "load_pins", return_value={}), \
                    patch.object(srv, "cmd_serve", return_value=0) as serve:
                self.assertEqual(srv.main(args), 0)
                self.assertEqual(serve.call_args.args[3:], expected)
        for args in (["--auto-attach", "--live-config", ".local/test.json"],
                     ["--live-config", ".local/test.json", "--practice-config", ".local/other.json"]):
            with patch.object(srv, "load_pins") as pins, patch.object(srv, "cmd_serve") as serve, \
                    patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                srv.main(args)
            pins.assert_not_called()
            serve.assert_not_called()

    def test_dashboard_only_default_never_creates_a_supervisor_but_explicit_auto_does(self):
        pins = {"server": {"port": 18090, "alias": ALIAS}, "model": {"revision": "synthetic", "finetuned": {}}}
        for auto, profile in ((False, None), (True, None), (False, ".local/strict-selector.json")):
            with self.subTest(auto=auto, profile=profile), patch.object(srv, "BoundedHTTPServer") as http, \
                    patch.object(srv.dashboard, "AutoAttachFeed") as attach, patch.object(srv, "Engine") as engine, \
                    patch.object(srv.threading, "Thread") as thread, patch("sys.stdout", io.StringIO()):
                self.assertEqual(srv.cmd_serve(pins, None, None, dashboard_only=True, live_config=profile, auto_attach=auto), 0)
                engine.assert_not_called()
                thread.assert_not_called()
                if auto or profile:
                    self.assertEqual(attach.call_args.args[0], profile or srv.dashboard.DEFAULT_PROFILE)
                    attach.return_value.start.assert_called_once()
                    attach.return_value.stop.assert_called_once()
                else:
                    attach.assert_not_called()
                http.return_value.server_close.assert_called_once()
        with patch.object(srv, "BoundedHTTPServer") as http, self.assertRaises(ValueError):
            srv.cmd_serve(pins, None, None, live_config=".local/x.json", auto_attach=True)
        http.assert_not_called()

    def test_model_initialization_failure_withholds_attachment_without_heavy_imports(self):
        pins = {"server": {"port": 18090, "alias": ALIAS}, "model": {"revision": "synthetic", "finetuned": {}}}
        captured = {}

        def worker(**kwargs):
            captured["initialize"] = kwargs["target"]
            return Mock()

        real_service = srv.Service

        def service(*args, **kwargs):
            captured["service"] = real_service(*args, **kwargs)
            return captured["service"]

        with patch.object(srv, "BoundedHTTPServer"), patch.object(srv, "Service", side_effect=service), \
                patch.object(srv.threading, "Thread", side_effect=worker), patch.object(srv, "verify", return_value=[]), \
                patch.object(srv, "Engine", side_effect=ValueError("PRIVATE-REPORT-PATH")), patch("sys.stdout", io.StringIO()):
            srv.cmd_serve(pins, None, None)
            captured["initialize"]()
        self.assertIsNone(captured["service"].engine)
        value = captured["service"].state.snapshot()["server"]
        self.assertEqual(value["model_state"], "failed")
        self.assertFalse(value["acceptance_floors_loaded"])
        self.assertFalse(value["advice_ready"])
        self.assertNotIn("PRIVATE", json.dumps(value))

    def test_fake_ready_metadata_separates_acceptance_floors_temperature_and_quality(self):
        pins = {"server": {"port": 18090, "alias": ALIAS}, "model": {"revision": "synthetic", "finetuned": {}}}
        captured = {}
        engine = FakeEngine()
        engine.calibration = object()
        image = SimpleNamespace(new=Mock(return_value="synthetic-warmup-image"))

        def worker(**kwargs):
            captured["initialize"] = kwargs["target"]
            return Mock()

        real_service = srv.Service

        def service(*args, **kwargs):
            captured["service"] = real_service(*args, **kwargs)
            return captured["service"]

        with patch.object(srv, "BoundedHTTPServer"), patch.object(srv, "Service", side_effect=service), \
                patch.object(srv.threading, "Thread", side_effect=worker), patch.object(srv, "verify", return_value=[]), \
                patch.object(srv, "Engine", return_value=engine), patch.dict("sys.modules", {"PIL": SimpleNamespace(Image=image)}), \
                patch("sys.stdout", io.StringIO()):
            srv.cmd_serve(pins, None, None)
            captured["initialize"]()
        meta = captured["service"].meta
        self.assertFalse(meta["calibrated"])
        self.assertTrue(meta["temperature_calibration_loaded"])
        self.assertTrue(meta["acceptance_floors_loaded"])
        value = captured["service"].state.snapshot()["server"]
        self.assertEqual(value["model_state"], "ready")
        self.assertTrue(value["temperature_calibration_loaded"])
        self.assertTrue(value["acceptance_floors_loaded"])
        self.assertEqual(value["quality_gate"], "failed")
        self.assertFalse(value["advice_ready"])

    def test_public_mutation_routes_are_denied_without_socket_or_model(self):
        service = srv.Service(ALIAS)
        handler = srv.make_handler(None, ALIAS, {}, None, service)
        for route in ("/api/start", "/api/connect", "/api/stop", "/api/attach", "/api/state", "/api/replay"):
            request = handler.__new__(handler)
            request.path = route
            request._local_request = Mock(return_value=True)
            request._discard_body = Mock()
            request._send = Mock()
            handler.do_POST(request)
            request._send.assert_called_once_with(404, {"error": "not-found"})
        for route in ("/api/start", "/api/connect", "/api/stop", "/api/attach", "/api/diagnostics"):
            request = handler.__new__(handler)
            request.path = route
            request._local_request = Mock(return_value=True)
            request._send = Mock()
            handler.do_GET(request)
            request._send.assert_called_once_with(404, {"error": "not-found"})

    def test_control_origin_host_guards_reject_without_reading_payload_or_using_a_socket(self):
        handler = srv.make_handler(None, ALIAS, {}, None)
        for headers in ({"Host": "evil.example"}, {"Host": "localhost:18090", "Origin": "null"},
                        {"Host": "127.0.0.1:18090", "Origin": "https://evil.example"}, {}):
            request = handler.__new__(handler)
            request.command = "POST"
            request.path = "/api/start"
            request.server = SimpleNamespace(server_address=("127.0.0.1", 18090))
            request.headers = Message()
            for name, value in headers.items():
                request.headers[name] = value
            request._discard_body = Mock()
            request._send = Mock()
            handler.do_POST(request)
            request._send.assert_called_once_with(403, {"error": "local-origin-required"})


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = HTTPServer(("127.0.0.1", 0), srv.make_handler(FakeEngine(), ALIAS, {"calibrated": False}, None))
        cls.port = cls.httpd.server_address[1]
        cls.t = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, path, data=None, headers=None):
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            finally:
                e.close()

    def test_models_lists_alias(self):
        status, payload = self.req("/v1/models")
        self.assertEqual((status, payload["data"][0]["id"]), (200, ALIAS))

    def test_predict_and_unknown_path(self):
        status, payload = self.req("/v1/laya/predict", json.dumps(body()).encode(), {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(self.req("/v1/chat/completions", b"{}")[0], 404)
        self.assertEqual(self.req("/nope")[0], 404)

    def test_bounded_batch_route_keeps_same_local_guards(self):
        value = BatchTests().batch()
        status, payload = self.req("/v1/laya/predict-batch", json.dumps(value).encode(),
                                   {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["results"]), 2)
        self.assertEqual(self.req("/v1/laya/predict-batch", b"{}", {
            "Content-Type": "application/json", "Origin": "https://evil.example"}),
            (403, {"error": "local-origin-required"}))

    def test_replay_fixture_is_not_a_public_route(self):
        self.assertEqual(self.req("/api/replay"), (404, {"error": "not-found"}))

    def test_reference_failure_does_not_expose_file_or_exception_details(self):
        for error in (OSError("PRIVATE-PATH"), ValueError("PRIVATE-CONTENT")):
            with patch.object(srv.dashboard, "references", side_effect=error):
                self.assertEqual(self.req("/api/reference"), (503, {"error": "reference-unavailable"}))

    def test_body_cap_rejected_from_header_without_reading(self):
        import http.client

        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest("POST", "/v1/laya/predict")
        c.putheader("Content-Length", str(srv.MAX_BODY + 1))
        c.endheaders()
        r = c.getresponse()
        self.assertEqual((r.status, json.loads(r.read())), (413, {"error": "body-too-large"}))
        c.close()


class PolicyTests(unittest.TestCase):
    def test_loopback_host_and_pins(self):
        self.assertEqual(srv.HOST, "127.0.0.1")
        pins = srv.load_pins()
        self.assertEqual(pins["server"]["port"], 18090)
        self.assertEqual(pins["server"]["alias"], ALIAS)
        self.assertEqual(len(pins["model"]["revision"]), 40)

    def test_png_size(self):
        self.assertEqual(srv.png_size(png(7, 5)), (7, 5))
        with self.assertRaises(srv.RequestError):
            srv.png_size(b"\x89PNG")

    def test_reference_loader_rejects_unbounded_nonfinite_or_wrong_schema(self):
        with patch.object(Path, "stat") as stat, patch.object(Path, "read_text") as read:
            stat.return_value.st_size = srv.dashboard.MAX_RECORD + 1
            with self.assertRaises(ValueError):
                srv.dashboard.references()
            read.assert_not_called()
            stat.return_value.st_size = 64
            for content in ('{"schema_version":1,"x":NaN}', '{"schema_version":2}', '[]'):
                read.return_value = content
                with self.assertRaises(ValueError):
                    srv.dashboard.references()


if __name__ == "__main__":
    unittest.main()
