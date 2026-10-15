"""Stdlib-only tests for scripts/laya-server.py (no torch, laya, PIL or numpy needed)."""

import base64
import contextlib
import copy
import hashlib
import builtins
import copy
from email.message import Message
import hashlib
import importlib.util
import io
import json
import math
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


class ReadoutBatchTests(unittest.TestCase):
    def batch(self, seat=1, board=False):
        source = next(p for p in json.loads((srv.ROOT / "crates/ingest/assets/laya/question-set.json")
                                           .read_text(encoding="utf-8"))["passes"] if p["id"] == "p0_full")
        ids = {"screen_kind", "ev_table_layout", "ev_readable"} | (
            {"ev_board_area", "game_phase"} if board else {"ev_pot"})
        questions = {}
        for q in source["questions"]:
            if q["id"] not in ids:
                continue
            questions[q["id"]] = {"type": q["type"], "instructions": q["instructions"]}
            if q["type"] == "choice":
                questions[q["id"]]["criteria"] = ([[key, q["criteria"][key]] for key in q["option_order"]]
                                                   if isinstance(q["criteria"], dict) else q["criteria"])
        core = body(layout="full", images_png_b64=[b64(png())], note=source["note"],
                    questions=questions, **{"pass": "p0_full"})
        if board:
            slots = body(images_png_b64=[b64(png())]*5, questions={
                "board_1_rank": {"type": "choice", "instructions": "Rank?", "criteria": ["A", "K"]}})
            requests = [core, slots]
        else:
            stacks = BatchTests().batch(seats=(seat, seat+1))["batch"]
            pot = {**stacks[0], "pass": "p3_pot", "glyph_style": "white"}
            requests = [core, pot, *stacks]
        return {"model": ALIAS, "batch_kind": "readout", "batch": requests}

    def handle(self, engine, value, log=None):
        return srv.handle_predict_batch(engine, ALIAS, json.dumps(value).encode(), log)

    def test_exact_pairs_and_board_keep_single_pass_answers_floors_and_segments(self):
        for value in ([self.batch(seat) for seat in (1, 3, 5)] + [self.batch(board=True)]):
            engine, logged = FakeEngine(), []
            for request in value["batch"]:
                request["acceptance_floor"] = 0
            status, result = self.handle(engine, value, logged.append)
            self.assertEqual(status, 200)
            self.assertEqual(len(engine.batch_calls), 1)
            self.assertEqual(len(result["results"]), len(value["batch"]))
            for request, payload in zip(value["batch"], result["results"]):
                code, serial = srv.handle_predict(FakeEngine(), ALIAS, json.dumps(request).encode())
                self.assertEqual(code, 200)
                self.assertEqual({key: v for key, v in payload.items() if key not in ("timing_ms", "timing_shared_batch")},
                                 {key: v for key, v in serial.items() if key != "timing_ms"})
                self.assertEqual(payload["timing_ms"], result["timing_ms"])
                self.assertIs(payload["timing_shared_batch"], True)
            self.assertEqual(len(logged), len(result["results"]))
            self.assertIsNone(logged[0]["segments"])
            self.assertNotIn(b64(png()), json.dumps(logged))
            self.assertEqual(set(result["results"][0]["answers"]), set(value["batch"][0]["questions"]))
            self.assertTrue({"act_fold", "act_call", "act_raise", "hero_seat_index", "action_on_hero"}
                            .isdisjoint(result["results"][0]["answers"]))

    def test_missing_gate_extra_control_wrong_note_and_changed_original_specs_never_decode(self):
        for board in (False, True):
            cases = []
            original = self.batch(board=board)
            for qid in original["batch"][0]["questions"]:
                value = copy.deepcopy(original)
                value["batch"][0]["questions"].pop(qid)
                cases.append(value)
            for qid in ("act_fold", "act_call", "act_raise", "hero_seat_index", "action_on_hero",
                        "ev_pot" if board else "ev_board_area"):
                value = copy.deepcopy(original)
                value["batch"][0]["questions"][qid] = {"type": "noul", "instructions": "Extra control?"}
                cases.append(value)
            for qid in original["batch"][0]["questions"]:
                value = copy.deepcopy(original)
                value["batch"][0]["questions"][qid]["instructions"] += " Changed."
                cases.append(value)
            value = copy.deepcopy(original)
            value["batch"][0]["questions"]["screen_kind"]["criteria"].reverse()
            cases.append(value)
            value = copy.deepcopy(original)
            value["batch"][0]["questions"]["screen_kind"]["criteria"][0][1] += " Changed."
            cases.append(value)
            value = copy.deepcopy(original)
            value["batch"][0]["note"] += " Changed."
            cases.append(value)
            value = copy.deepcopy(original)
            value["batch"][0]["questions"]["screen_kind"] = {"type": "noul", "instructions": "Changed type"}
            cases.append(value)
            value = copy.deepcopy(original)
            value["batch"][0]["questions"]["ev_readable"]["criteria"] = ["no", "yes"]
            cases.append(value)
            for value in cases:
                engine = FakeEngine()
                engine.decode = Mock()
                self.assertEqual(self.handle(engine, value), (400, {"error": "readout-core-template-mismatch"}))
                engine.decode.assert_not_called()

    def test_missing_original_template_fails_closed_and_ordinary_full_core_still_allowed(self):
        engine = FakeEngine()
        engine.decode = Mock()
        with patch.object(srv, "readout_core_template", side_effect=KeyError("missing")):
            self.assertEqual(self.handle(engine, self.batch()), (503, {"error": "readout-core-template-unavailable"}))
        engine.decode.assert_not_called()
        original = self.batch()["batch"][0]
        source = next(p for p in json.loads((srv.ROOT / "crates/ingest/assets/laya/question-set.json")
                                           .read_text(encoding="utf-8"))["passes"] if p["id"] == "p0_full")
        original["questions"] = {q["id"]: {key: q[key] for key in ("type", "instructions", "criteria") if key in q}
                                 for q in source["questions"]}
        status, result = srv.handle_predict(FakeEngine(), ALIAS, json.dumps(original).encode())
        self.assertEqual(status, 200)
        self.assertEqual(len(result["answers"]), 16)
        self.assertIn("act_fold", result["answers"])

    def test_old_endpoint_without_opt_in_cannot_accept_mixed_groups(self):
        value = self.batch()
        value.pop("batch_kind")
        engine = FakeEngine()
        engine.decode = Mock()
        self.assertEqual(self.handle(engine, value), (400, {"error": "incompatible-batch"}))
        engine.decode.assert_not_called()
        self.assertEqual(BatchTests().handle(FakeEngine(), BatchTests().batch(seats=range(1, 7)))[0], 200)

    def test_incompatible_groups_layouts_types_metadata_and_unknown_kinds_never_decode(self):
        cases = [self.batch(2), self.batch(4)]
        missing = self.batch()
        missing["batch"].pop()
        cases.append(missing)
        reversed_pair = self.batch()
        reversed_pair["batch"][2:] = reversed(reversed_pair["batch"][2:])
        cases.append(reversed_pair)
        for kind in (None, True, "all", "experimental"):
            cases.append({**self.batch(), "batch_kind": kind})
        for index, field, content in ((0, "layout", "slots"), (0, "glyph_style", "white"),
                                     (1, "glyph_style", "gold"), (2, "glyph_style", "white"),
                                     (3, "pass", "p6_seat_2_wager"),
                                     (1, "questions", {"g1": {"type": "noul", "instructions": "x"}})):
            value = self.batch()
            value["batch"][index][field] = content
            cases.append(value)
        for field in ("experimental_descriptor", "wager_capability", "scene_capability"):
            value = self.batch()
            value["batch"][0][field] = {}
            cases.append(value)
        board = self.batch(board=True)
        board["batch"][1]["images_png_b64"].pop()
        cases.append(board)
        for value in cases:
            engine = FakeEngine()
            engine.decode = Mock()
            self.assertEqual(self.handle(engine, value)[0], 400)
            engine.decode.assert_not_called()

    def test_any_missing_floor_rejects_entire_battery_before_decode(self):
        for value in (self.batch(), self.batch(board=True)):
            for request in value["batch"]:
                engine = FakeEngine()
                engine.acceptance_floors.pop(request["pass"])
                engine.decode = Mock()
                self.assertEqual(self.handle(engine, value), (503, {"error": "acceptance-floor-unavailable"}))
                engine.decode.assert_not_called()

    def test_pixel_budget_covers_every_board_slot_before_decode(self):
        value = self.batch(board=True)
        header = srv.PNG_SIG + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 4000, 1000)
        value["batch"][1]["images_png_b64"] = [b64(header)]*5
        engine = FakeEngine()
        engine.decode = Mock()
        self.assertEqual(self.handle(engine, value), (400, {"error": "image-too-large"}))
        engine.decode.assert_not_called()

    def test_empty_or_overflow_numeric_crops_leave_core_but_no_numeric_answers(self):
        for engine in (FakeEngine(n=0), FakeEngine(overflow=True)):
            status, result = self.handle(engine, self.batch())
            self.assertEqual(status, 200)
            self.assertEqual(len(engine.batch_calls[0]), 1)
            self.assertTrue(result["results"][0]["answers"])
            self.assertTrue(all(not result["answers"] for result in result["results"][1:]))
            self.assertTrue(all("segments" in result for result in result["results"][1:]))
            self.assertNotIn("amount", json.dumps(result))

    def test_original_40_question_cap_and_25_image_limit_remain_fail_closed(self):
        value = self.batch()
        engine = FakeEngine(n=8)
        status, result = self.handle(engine, value)
        self.assertEqual(status, 200)
        self.assertEqual(sum(len(images) for images, _, _ in engine.batch_calls[0]), 25)
        self.assertEqual(sum(len(p["answers"]) for p in result["results"]), 28)
        self.assertEqual(srv.MAX_READOUT_QUESTIONS, 40)
        value["batch"][0]["questions"] = {"q%d" % i: {"type": "noul", "instructions": "Visible?"} for i in range(17)}
        engine = FakeEngine()
        engine.decode = Mock()
        self.assertEqual(self.handle(engine, value), (400, {"error": "batch-too-large"}))
        engine.decode.assert_not_called()
        engine = FakeEngine(n=9)
        self.assertEqual(self.handle(engine, self.batch()), (400, {"error": "batch-too-large"}))
        self.assertEqual(engine.batch_calls, [])

    def test_readout_keeps_shared_gpu_lock(self):
        engine = FakeEngine()
        service = srv.Service(ALIAS, engine=engine)
        with service.inference:
            self.assertEqual(service.predict(json.dumps(self.batch()).encode(), batch=True),
                             (503, {"error": "inference-busy"}))
        self.assertEqual(engine.batch_calls, [])


class EnginePrefixTests(unittest.TestCase):
    def setUp(self):
        self.processor = SimpleNamespace(tokenizer={"padding": []})
        self.processor.image_processor = type("Idefics3ImageProcessorPil", (), {})()
        self.prep = SimpleNamespace(on_gpu=False, split_edge=0)
        self.engine = srv.Engine.__new__(srv.Engine)
        self.engine.agent = SimpleNamespace(processor=self.processor, prep=self.prep)
        self.engine._prefix_processors = None
        self.vlm = SimpleNamespace(processor_readout=Mock(return_value="terminator"),
                                   vlm_prefix=Mock(side_effect=lambda processor, images, prep: {"images": images}))
        modules = patch.dict("sys.modules", {"laya": SimpleNamespace(vlm=self.vlm)})
        modules.start()
        self.addCleanup(modules.stop)

    def test_single_prefix_delegates_unchanged_to_original_processor(self):
        images = [object(), object(), object()]
        self.assertIs(self.engine._prefix(images)["images"], images)
        self.vlm.vlm_prefix.assert_called_once_with(self.processor, images, self.prep)

    def test_parallel_original_prefixes_use_four_isolated_processors_and_preserve_order(self):
        barrier = threading.Barrier(4)
        seen = {}
        def prefix(processor, images, prep):
            index = images[0]
            if index < 4:
                barrier.wait(timeout=2)
                seen[index] = processor
            self.assertIs(prep, self.prep)
            return {"images": images}
        self.vlm.vlm_prefix.side_effect = prefix
        samples = [([i], "note", {}) for i in range(6)]
        self.assertEqual(self.engine._prefixes(samples), [{"images": [i]} for i in range(6)])
        self.assertEqual(len({id(p) for p in seen.values()}), 4)
        self.assertEqual(len({id(p.tokenizer) for p in seen.values()}), 4)
        self.assertTrue(all(p is not self.processor and p.tokenizer is not self.processor.tokenizer for p in seen.values()))
        cached = self.engine._prefix_processors
        self.vlm.vlm_prefix.side_effect = lambda processor, images, prep: {"images": images}
        self.engine._prefixes(samples)
        self.assertIs(self.engine._prefix_processors, cached)
        self.assertEqual(self.vlm.vlm_prefix.call_count, 12)

    def test_empty_gpu_tiled_unknown_and_mask_processors_keep_serial_upstream_path(self):
        for case in ("empty", "gpu", "tiles", "unknown", "mask"):
            self.prep.on_gpu = case == "gpu"
            self.prep.split_edge = 2048 if case == "tiles" else 0
            self.processor.image_processor = (object() if case == "unknown" else type("Idefics3ImageProcessorPil", (), {})())
            self.vlm.processor_readout.return_value = "mask" if case == "mask" else "terminator"
            samples = [] if case == "empty" else [([object()], "", {})]*2
            self.assertEqual(self.engine._prefixes(samples), [{"images": sample[0]} for sample in samples])
            if samples:
                self.vlm.vlm_prefix.assert_called_with(self.processor, samples[0][0], self.prep)
        self.assertIsNone(self.engine._prefix_processors)

    def test_failed_prefix_waits_for_other_running_workers_before_returning(self):
        running, release, finished, returned = (threading.Event() for _ in range(4))
        errors = []
        def prefix(processor, images, prep):
            if images == ["bad"]:
                self.assertTrue(running.wait(2))
                raise ValueError("bad-prefix")
            running.set()
            release.wait(2)
            finished.set()
            return {"images": images}
        def invoke():
            try:
                self.engine._prefixes([(["bad"], "", {}), (["wait"], "", {})])
            except ValueError as error:
                errors.append(str(error))
            finally:
                returned.set()
        self.vlm.vlm_prefix.side_effect = prefix
        caller = threading.Thread(target=invoke)
        caller.start()
        try:
            self.assertTrue(running.wait(2))
            self.assertFalse(returned.wait(.03))
        finally:
            release.set()
            caller.join(2)
        self.assertFalse(caller.is_alive())
        self.assertTrue(finished.is_set())
        self.assertEqual(errors, ["bad-prefix"])


class EngineBatchTests(unittest.TestCase):
    """Exercise tensor routing and wire equivalence, not GPU speed or numeric parity."""

    def setUp(self):
        test = self
        self.inference_active = False
        self.downloads = 0
        self.preprocessed, self.built, self.encoded, self.forwarded = [], [], [], []
        self.moves = []

        class Tensor(list):
            def __getitem__(self, key):
                value = super().__getitem__(key)
                return Tensor(value) if isinstance(key, slice) else value

            def to(self, *args):
                test.moves.append(args)
                return self

            def float(self):
                return self

            def cpu(self):
                return self

            def numpy(self):
                test.downloads += 1
                return list(self)

            def repeat(self, count, rows, columns):
                test.assertEqual((rows, columns), (1, 1))
                return Tensor(list(self)*count)

        class Vector(list):
            def __truediv__(self, value):
                return Vector(item/value for item in self)

            def __sub__(self, value):
                return Vector(item-value for item in self)

            def max(self):
                return max(self)

            def sum(self):
                return sum(self)

            def argmax(self):
                return self.index(max(self))

        @contextlib.contextmanager
        def inference_mode():
            self.assertFalse(self.inference_active)
            self.inference_active = True
            self.downloads = 0
            try:
                yield
            finally:
                self.inference_active = False

        def prefix(processor, images, prep):
            self.assertTrue(self.inference_active)
            self.preprocessed.append(images)
            return {"ids": [99] + [64]*len(images), "n_images": len(images),
                    "raw_images": None, "pixel_values": Tensor(images),
                    "pixel_attention_mask": Tensor([True]*len(images))}

        def build(processor, state, internal, max_len, head_max_len, prefix):
            self.assertEqual(set(state), {"note"})
            self.assertIsNone(prefix["pixel_values"])
            self.assertIsNone(prefix["pixel_attention_mask"])
            self.assertIsNone(prefix["raw_images"])
            self.assertEqual((max_len, head_max_len), (1024, 256))
            self.built.append((state, internal, prefix))
            count = len(internal["crit"]) if internal["t"] == "choice" else 2
            return {**prefix, "ids": self.ids(state["note"], internal, prefix["n_images"]),
                    "markers": list(range(count if internal["ins"] != "invalid" else 0)),
                    "option_span": (1, count+1),
                    "truncation": {"instructions": True} if internal["ins"] == "truncate" else None}

        def collate(chunk, pad_id, with_pixels):
            self.assertEqual(pad_id, 0)
            self.assertFalse(with_pixels)
            self.assertTrue(all(row["pixel_values"] is None for row in chunk))
            return {key: Tensor(chunk) for key in ("input_ids", "attention_mask", "marker_pos",
                    "marker_mask", "qtype", "option_span")}

        def encode(pixels, masks):
            self.assertTrue(self.inference_active)
            self.assertEqual(list(masks), [True]*len(pixels))
            self.encoded.append(list(pixels))
            return Tensor(pixels)

        def forward(rows, *args, image_hidden_states, option_span):
            self.assertTrue(self.inference_active)
            self.assertEqual(self.downloads, 0)
            self.assertEqual(list(option_span), list(rows))
            result, offset, row_images = [], 0, []
            for row in rows:
                images = image_hidden_states[offset:offset+row["n_images"]]
                offset += row["n_images"]
                row_images.append(list(images))
                seed = sum(images) + sum(row["ids"]) + row["qtype"]
                result.append([(seed+index*3) % 11 for index in range(len(row["markers"]))])
            self.assertEqual(offset, len(image_hidden_states))
            self.forwarded.append(row_images)
            # No action/value/provenance may be accessed by the wire-only path.
            return Tensor(result), object()

        self.torch = SimpleNamespace(inference_mode=inference_mode, cuda=SimpleNamespace(synchronize=Mock()),
                                    cat=lambda parts: Tensor(value for part in parts for value in part))
        numpy = SimpleNamespace(float64="float64", asarray=lambda values, dtype: Vector(values),
                                exp=lambda values: Vector(math.exp(value) for value in values))
        self.vlm = SimpleNamespace(vlm_prefix=Mock(side_effect=prefix), build_vlm_inputs=Mock(side_effect=build),
            collate_vlm=collate, checkpoint_identity=lambda agent: "synthetic-checkpoint",
            resolve_temperature=lambda temperature, calibration: {0: 2.5} if calibration else {},
            render_options=lambda q: list(q["crit"]) if q["t"] == "choice" else ["false", "true"],
            QTYPES={"choice": 0, "noul": 2}, truncation_answer=lambda report, q: report,
            confidence_from_probs=lambda p, k: 1+sum(v*math.log(v) for v in p)/math.log(k))
        self.engine = srv.Engine.__new__(srv.Engine)
        self.engine.batch_size = 3
        self.engine.calibration = Mock()
        self.engine.agent = SimpleNamespace(
            processor=SimpleNamespace(tokenizer=SimpleNamespace(pad_token_id=0)), prep=object(),
            cfg={"max_len": 1024, "head_max_len": 256}, device="cuda", _torch_dtype=lambda: "bf16",
            _to_internal=self.internal, _checkpoint_temperature=lambda qtype, count: 4.0,
            model=Mock(side_effect=forward), predict=Mock(return_value={"answers": {}}))
        self.engine.agent.model.encode_images = Mock(side_effect=encode)
        modules = patch.dict("sys.modules", {"numpy": numpy, "torch": self.torch,
                                             "laya": SimpleNamespace(vlm=self.vlm)})
        modules.start()
        self.addCleanup(modules.stop)

    @staticmethod
    def internal(question):
        criteria = question.get("criteria")
        if isinstance(criteria, list):
            criteria = {key: None for key in criteria}
        return {"t": question["type"], "ins": question["instructions"], "crit": criteria}

    @staticmethod
    def ids(note, internal, count):
        return [99] + [64]*count + [ord(c) for c in json.dumps([note, internal], ensure_ascii=False)]

    def reference(self, samples):
        results = []
        for images, note, questions in samples:
            answers = {}
            for qid, q in questions.items():
                internal = self.internal(q)
                count = len(internal["crit"]) if q["type"] == "choice" else 2
                seed = sum(images) + sum(self.ids(note, internal, len(images))) + (0 if q["type"] == "choice" else 2)
                scale = 2.5 if self.engine.calibration and q["type"] == "choice" else 4.0
                scores = [(seed+i*3) % 11 / scale for i in range(count)]
                values = [math.exp(score-max(scores)) for score in scores]
                probs = [value/sum(values) for value in values]
                if q["type"] == "choice":
                    labels = list(internal["crit"])
                    answers[qid] = {"type": "choice", "choice": labels[probs.index(max(probs))],
                        "probabilities": dict(zip(labels, [round(p, 4) for p in probs])),
                        "confidence": round(1+sum(p*math.log(p) for p in probs)/math.log(count), 4)}
                else:
                    answers[qid] = {"type": "noul", "noul": round(probs[1], 4),
                                    "confidence": round(max(probs[1], 1-probs[1]), 4)}
                if q["instructions"] == "truncate":
                    answers[qid]["truncated"] = {"instructions": True}
            results.append({"answers": answers})
        return results

    def test_mixed_requests_preserve_scalar_batch_shapes_ragged_images_and_question_order(self):
        core = {"same": {"type": "choice", "instructions": "screen", "criteria": {"B": "beta", "A": "alpha"}},
                "evidence": {"type": "noul", "instructions": "visible"}}
        glyphs = {"same": {"type": "choice", "instructions": "character", "criteria": ["9", "2", "0"]},
                  "cut": {"type": "choice", "instructions": "truncate", "criteria": ["A", "K"]}}
        samples = [([11], "core", core), ([13, 17, 19], "digits", glyphs), ([23, 29, 31], "digits", glyphs)]
        before = copy.deepcopy(samples)
        self.assertEqual(self.engine.predict_many(samples), self.reference(samples))
        self.assertEqual(samples, before)
        self.assertEqual(self.preprocessed, [sample[0] for sample in samples])
        self.assertEqual(self.encoded, [[11], [13, 17, 19], [23, 29, 31]])
        self.assertEqual(self.forwarded, [[[11], [11]], [[13, 17, 19], [13, 17, 19]], [[23, 29, 31], [23, 29, 31]]])
        self.assertEqual(len(self.built), 4)  # repeated text only; all seven images still encoded
        self.assertEqual(self.downloads, 3)
        self.assertIn(("cuda", "bf16"), self.moves)
        self.engine.calibration.check.assert_called_once_with("synthetic-checkpoint")
        self.torch.cuda.synchronize.assert_called_once_with()
        self.assertFalse(self.inference_active)

    def test_note_prefix_and_option_order_prevent_text_reuse_and_no_cache_crosses_calls(self):
        question = {"type": "choice", "instructions": "rank", "criteria": {"A": "ace", "K": "king"}}
        samples = [([1], "a", {"q": question}), ([2], "b", {"q": question}),
                   ([3, 4], "a", {"q": question}),
                   ([5], "a", {"q": {**question, "criteria": {"K": "king", "A": "ace"}}})]
        for _ in range(2):
            self.assertEqual(self.engine.predict_batch(samples), self.reference(samples))
        self.assertEqual(len(self.built), 8)
        self.assertEqual(len(self.preprocessed), 8)

    def test_single_small_request_uses_wire_only_batch_path_and_checkpoint_temperatures(self):
        self.engine.calibration = None
        samples = [([3], "core", body()["questions"])]
        self.assertEqual(self.engine.predict(*samples[0]), self.reference(samples)[0])
        self.engine.agent.predict.assert_not_called()
        self.assertEqual(len(self.encoded), 1)
        self.assertEqual(len(self.forwarded), 1)

    def test_large_single_request_keeps_upstream_prefix_policy_under_inference_mode(self):
        self.engine.batch_size = 1
        def predict(*args, **kwargs):
            self.assertTrue(self.inference_active)
            return {"answers": {}}
        self.engine.agent.predict.side_effect = predict
        questions = body()["questions"]
        self.assertEqual(self.engine.predict([1], "core", questions), {"answers": {}})
        self.engine.agent.predict.assert_called_once_with({"images": [1], "note": "core"}, questions,
            n_permutations=1, batch_size=1, calibration=self.engine.calibration)
        self.assertEqual(self.encoded, [])
        self.assertFalse(self.inference_active)

    def test_large_batched_state_retains_upstream_scalar_prefix_cache_policy(self):
        self.engine.batch_size = 1
        questions = body()["questions"]
        self.assertEqual(self.engine.predict_many([([1], "core", questions), ([2], "core", questions)]),
                         [{"answers": {}}, {"answers": {}}])
        self.assertEqual(self.engine.agent.predict.call_count, 2)
        self.assertEqual(self.encoded, [])
        self.assertEqual(self.forwarded, [])

    def test_many_images_in_one_state_are_not_split_into_different_vision_batches(self):
        self.engine.batch_size = 2
        samples = [([1, 2, 3, 4, 5], "board", body()["questions"])]
        self.assertEqual(self.engine.predict_many(samples), self.reference(samples))
        self.assertEqual(self.encoded, [[1, 2, 3, 4, 5]])
        self.assertEqual(self.forwarded, [[[1, 2, 3, 4, 5], [1, 2, 3, 4, 5]]])

    def test_empty_batch_and_bad_marker_count_do_not_run_model(self):
        self.assertEqual(self.engine.predict_many([]), [])
        for question in ({"type": "choice", "instructions": "invalid", "criteria": ["A", "K"]},
                         {"type": "score", "instructions": "unsupported", "criteria": ["A", "K"]}):
            with self.assertRaisesRegex(ValueError, "batch-question-invalid"):
                self.engine.predict_many([([1], "core", {"q": question})])
        self.assertEqual(self.encoded, [])
        self.assertEqual(self.forwarded, [])
        self.assertFalse(self.inference_active)


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
        model = b"SYNTHETIC-NOT-MODEL-WEIGHTS"
        model_hash = hashlib.sha256(model).hexdigest()
        (base / "model.safetensors").write_bytes(model)
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
            "path": "candidate", "wager_registry": "registry.json", "files": [
                {"path": name, "size": (base / name).stat().st_size, "sha256": digest}
                for name, digest in files.items()]}}}

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
                with self.assertRaisesRegex(ValueError, "wager-evidence-(hash|path)"):
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
        files = srv.pinned_file_entries(ft)
        fields = {name: {"precision": 1.0, "coverage": .96, "recall": .96,
                         "confident_items": 24, "positive_opportunities": 24}
                  for name in srv.SCENE_QUESTIONS}
        if bad_field:
            name, key, value = bad_field
            fields[name][key] = value
        proof = {"schema_version": 1, "human_verification": "VERIFIED",
                  "model_sha256": files["model.safetensors"]["sha256"], "passes": {
                     "p7_seat_1_scene": {"fitted_floor": .999, "fields": fields,
                         "session_grouped": True, "calibration_separate_from_held_out": True}}}
        raw = json.dumps(proof).encode()
        (root / "candidate/qa.json").write_bytes(raw)
        files["qa.json"].update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        entry = self.capability()
        entry.pop("registry_version")
        entry.pop("model_alias")
        entry.update(model_sha256=files["model.safetensors"]["sha256"],
                      capability_evidence_sha256=files["qa.json"]["sha256"],
                      candidate_sha256=hashlib.sha256(json.dumps(
                          {k: v["sha256"] for k, v in files.items() if k != ft["scene_registry"]},
                         sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        raw = json.dumps({"version": 1, "model_alias": ALIAS, "passes": [entry]}).encode()
        (root / "candidate/registry.json").write_bytes(raw)
        files["registry.json"].update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
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


class RegistryPinTests(unittest.TestCase):
    def test_shipped_list_format_keeps_registry_hash_identity_and_acceptance_floors(self):
        for kind, fixture in (("wager", WagerTests()), ("scene", SceneTests())):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pins = fixture.pinned_fixture(root)
                ft = pins["model"]["finetuned"]
                ft["acceptance_file"] = "calibration.json"
                report = json.dumps({"ckpt": "candidate", "thresholds_per_pass": FLOORS}).encode()
                (root / "candidate/calibration.json").write_bytes(report)
                ft["files"].append({"path": "calibration.json", "size": len(report),
                                    "sha256": hashlib.sha256(report).hexdigest()})
                entries = srv.pinned_file_entries(ft)
                registry_path = root / "candidate" / ft[kind + "_registry"]
                registry = json.loads(registry_path.read_bytes())
                registry["passes"][0]["candidate_sha256"] = hashlib.sha256(json.dumps(
                    {key: entry["sha256"] for key, entry in entries.items() if key != registry_path.name},
                    sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                raw = json.dumps(registry).encode()
                registry_path.write_bytes(raw)
                entries[registry_path.name].update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                with patch.object(srv, "ROOT", root), patch.object(srv, "REPO", str(root)):
                    self.assertEqual(srv.load_acceptance_floors(pins), FLOORS)
                    result = srv.load_seat_registry(pins, kind)
                    self.assertEqual(len(result), 1)
                    self.assertEqual(next(iter(result.values()))["fitted_floor"], .999)
                    self.assertEqual(srv.load_acceptance_floors(pins), FLOORS)
                self.assertIsInstance(ft["files"], list)

    def test_duplicate_unsafe_missing_size_or_non_digest_pin_entries_fail_closed(self):
        entry = {"path": "qa.json", "size": 100, "sha256": "a"*64}
        cases = [{"qa.json": "a"*64}, [entry, entry], [None],
                 [{**entry, "path": "../qa.json"}], [{**entry, "path": "C:\\qa.json"}],
                 [{**entry, "size": True}], [{**entry, "size": 0}], [{**entry, "sha256": "not-a-digest"}],
                 [{key: value for key, value in entry.items() if key != "size"}]]
        for files in cases:
            with self.subTest(files=files), self.assertRaisesRegex(ValueError, "fine-tuned-files-invalid"):
                srv.pinned_file_entries({"files": files})


class ExperimentalTests(unittest.TestCase):
    def engine(self, **kwargs):
        engine = FakeEngine(**kwargs)
        engine.experimental_metadata = {"model_sha256": srv.EXPERIMENTAL_MODEL_SHA256,
            "temperature_calibration_sha256": "1" * 64,
            "donor_pass": "p5_seat_1_stack", "inherited_cutoff": .8}
        return engine

    def request(self, seat=1, kind="wager"):
        pid = "%s_seat_%d_%s" % ("p6" if kind == "wager" else "p7", seat, kind)
        value = body(**{"pass": pid, "experimental_descriptor": srv.experimental_descriptor(pid),
                        "images_png_b64": [b64(png())]})
        if kind == "wager":
            value.update(layout="glyphs", glyph_style="white", note=srv.EXPERIMENTAL_WAGER_NOTE,
                         questions=copy.deepcopy(srv.wager_questions()))
        else:
            value.update(layout="slots", note=srv.SCENE_NOTE,
                questions={qid: {"type": "choice", "instructions": instructions, "criteria": list(labels)}
                           for qid, (instructions, labels) in srv.SCENE_QUESTIONS.items()})
        return value

    def handle(self, engine, request, authorized=lambda: True, log=None):
        return srv.handle_predict(engine, ALIAS, json.dumps(request).encode(), log,
                                  experimental_authorized=authorized)

    def test_all_twelve_descriptors_are_unvalidated_with_null_target_floors_and_no_actions(self):
        for kind in ("wager", "scene"):
            for seat in range(1, 7):
                with self.subTest(kind=kind, seat=seat):
                    request, logged = self.request(seat, kind), []
                    request.update(acceptance_floor=0, trained_candidate=True, human_verified=True)
                    status, payload = self.handle(self.engine(), request, log=logged.append)
                    self.assertEqual(status, 200)
                    self.assertIsNone(payload["acceptance_floor"])
                    self.assertEqual(payload["experimental_descriptor"], request["experimental_descriptor"])
                    self.assertEqual(payload["experimental_diagnostics"], {
                        "diagnostic_only": True, "training": "unvalidated", "geometry_status": "DRAFT",
                        "human_review": "PENDING", "donor_pass": "p5_seat_1_stack" if kind == "wager" else None,
                        "inherited_cutoff": .8 if kind == "wager" else None})
                    self.assertNotIn("action", payload["answers"][next(iter(payload["answers"]))])
                    for key in ("wager_capability", "scene_capability", "quality_approved", "verified_fields",
                                "state", "advice", "provenance", "trained_candidate", "human_verified"):
                        self.assertNotIn(key, payload)
                    self.assertEqual(logged[0]["experimental_diagnostics"], payload["experimental_diagnostics"])
                    self.assertTrue(all(answer["effective_fitted_floor"] is None
                                        for answer in logged[0]["answers"].values()))

    def test_no_service_opt_in_or_approved_binding_means_no_decode(self):
        for enabled, binding, approved in ((False, ("a"*32, "b"*32), True),
                                           (True, None, True), (True, ("a"*32, "b"*32), False)):
            engine = self.engine()
            engine.decode = Mock()
            service = srv.Service(ALIAS, engine=engine, experimental_bet_action=enabled)
            service.manual_feed = SimpleNamespace(root=Path("."), authorizes=lambda *_: True)
            with patch.object(srv.manual_capture, "experimental_session_approved", return_value=approved):
                result = service.predict(json.dumps(self.request()).encode(), session_binding=binding)
            self.assertEqual(result, (403, {"error": "experimental-session-required"}))
            engine.decode.assert_not_called()
        engine = self.engine()
        engine.decode = Mock()
        service = srv.Service(ALIAS, engine=engine, experimental_bet_action=True)
        service.manual_feed = SimpleNamespace(root=Path("."), authorizes=lambda *_: False)
        self.assertEqual(service.predict(json.dumps(self.request()).encode(), session_binding=("a"*32, "b"*32)),
                         (409, {"error": "manual-session-ended"}))
        engine.decode.assert_not_called()

    def test_real_passive_feed_authorization_keeps_experiment_out_of_current_readings(self):
        from scripts.tests.test_manual_inference import ManualFeedTests, INSTANCE, SESSION
        fixture = ManualFeedTests()
        fixture.setUp()
        try:
            path = fixture.automatic_session()
            approval = srv.manual_capture.read_json(path / "approval.json")
            status = srv.manual_capture.read_json(path / "status.json")
            fixture.append_automatic(path, fixture.health())
            engine = self.engine()
            service = srv.Service(ALIAS, engine=engine, experimental_bet_action=True)
            service.instance_id = INSTANCE
            service.state, service.manual_feed = fixture.state, fixture.feed
            request = json.dumps(self.request()).encode()
            self.assertEqual(service.predict(request, session_binding=(SESSION, INSTANCE)),
                             (403, {"error": "experimental-session-required"}))
            self.assertEqual(engine.calls, [])
            srv.manual_capture.write_json(path / "approval.json", {**approval, "experimental_bet_action": True})
            srv.manual_capture.write_json(path / "status.json", {**status, "experimental_bet_action": True})
            code, payload = service.predict(request, session_binding=(SESSION, INSTANCE))
            self.assertEqual(code, 200)
            self.assertIsNone(payload["acceptance_floor"])
            snapshot = service.manual_feed.snapshot()
            self.assertIsNone(snapshot["partial_observation"])
            self.assertIsNone(snapshot["observation"])
            self.assertIsNone(snapshot["advice"])
            self.assertEqual(snapshot["history"]["events"], [])
            self.assertFalse(snapshot["server"]["advice_ready"])
            srv.manual_capture.stop_session(SESSION, root=fixture.root)
            self.assertEqual(service.predict(request, session_binding=(SESSION, INSTANCE)),
                             (409, {"error": "manual-session-ended"}))
            self.assertEqual(len(engine.calls), 1)
        finally:
            fixture.doCleanups()

    def test_explicit_body_or_environment_flags_cannot_authorize_an_experiment(self):
        engine = self.engine()
        engine.decode = Mock()
        request = self.request()
        request["experimental_bet_action"] = True
        with patch.dict(srv.os.environ, {"COINPOKER_EXPERIMENTAL_BET_ACTION": "1"}):
            self.assertEqual(srv.handle_predict(engine, ALIAS, json.dumps(request).encode()),
                             (403, {"error": "experimental-session-required"}))
            self.assertFalse(srv.Service(ALIAS, engine=engine).experimental_bet_action)
        engine.decode.assert_not_called()

    def test_exact_descriptor_templates_and_option_order_are_required_before_decode(self):
        cases = []
        for field, value in (("training", "trained"), ("diagnostic_only", 1), ("human_review", "VERIFIED")):
            request = self.request()
            request["experimental_descriptor"][field] = value
            cases.append(request)
        request = self.request()
        request["experimental_descriptor"]["region"]["bounds"][0] += 1
        cases.append(request)
        for kind in ("wager", "scene"):
            request = self.request(kind=kind)
            request["wager_capability"] = WagerTests().capability()
            cases.append(request)
            request = self.request(kind=kind)
            request["note"] = "PRIVATE-NAME-OCR"
            cases.append(request)
            request = self.request(kind=kind)
            key = next(iter(request["questions"]))
            request["questions"][key]["instructions"] = "Read player identity"
            cases.append(request)
        request = self.request()
        request["questions"]["g1"]["criteria"] = dict(reversed(list(request["questions"]["g1"]["criteria"].items())))
        cases.append(request)
        request = self.request()
        request["glyph_style"] = "gold"
        cases.append(request)
        request = self.request(kind="scene")
        request["questions"]["badge"]["criteria"].reverse()
        cases.append(request)
        for request in cases:
            engine = self.engine()
            engine.decode = Mock()
            status, _ = self.handle(engine, request)
            self.assertEqual(status, 400)
            engine.decode.assert_not_called()

    def test_empty_and_overflow_glyphs_are_unknown_not_zero_without_prediction(self):
        for engine in (self.engine(n=0), self.engine(overflow=True)):
            status, payload = self.handle(engine, self.request())
            self.assertEqual(status, 200)
            self.assertEqual(payload["answers"], {})
            self.assertEqual(engine.calls, [])
            self.assertIsNone(payload["acceptance_floor"])
            self.assertNotIn("amount", payload)

    def test_revocation_during_decode_or_prediction_discards_candidate_without_renewal(self):
        for stage in ("decode", "predict"):
            permitted, engine = [True], self.engine()
            original = getattr(engine, stage)
            def revoke(*args):
                result = original(*args)
                permitted[0] = False
                return result
            setattr(engine, stage, revoke)
            self.assertEqual(self.handle(engine, self.request(), lambda: permitted[0]),
                             (409, {"error": "manual-session-ended"}))
            self.assertEqual(len(engine.calls), int(stage == "predict"))

    def test_bad_or_private_model_answers_never_escape_closed_diagnostics(self):
        for bad in ({"choice": "PRIVATE-NAME"}, {"probabilities": {"PRIVATE-NAME": 1}},
                    {"confidence": "PRIVATE-NAME"}, {"type": "noul", "noul": .99}):
            engine = self.engine()
            predict = engine.predict
            def invalid(*args):
                result = predict(*args)
                result["answers"]["occupied"].update(bad)
                return result
            engine.predict = invalid
            status, payload = self.handle(engine, self.request(kind="scene"))
            self.assertEqual(status, 200)
            self.assertNotIn("occupied", payload["answers"])
            self.assertNotIn("PRIVATE", json.dumps(payload))

    def test_candidate_metadata_missing_wrong_model_or_lower_cutoff_never_decodes(self):
        for override in (None, {"model_sha256": "2"*64}, {"inherited_cutoff": .7999},
                         {"inherited_cutoff": True}, {"donor_pass": "p0_full"},
                         {"temperature_calibration_sha256": "not-pinned"}):
            engine = self.engine()
            engine.experimental_metadata = None if override is None else {**engine.experimental_metadata, **override}
            engine.decode = Mock()
            self.assertEqual(self.handle(engine, self.request()),
                             (503, {"error": "experimental-candidate-unavailable"}))
            engine.decode.assert_not_called()
        engine = self.engine()
        engine.experimental_metadata["inherited_cutoff"] = .95
        status, payload = self.handle(engine, self.request())
        self.assertEqual(status, 200)
        self.assertEqual(payload["experimental_diagnostics"]["inherited_cutoff"], .95)

    def test_generic_p6_p7_names_and_batches_do_not_gain_experimental_permission(self):
        for pid in ("p6_to_call", "p7_hero_stack", "p1_hero"):
            request, engine = self.request(), self.engine()
            request["pass"] = pid
            engine.decode = Mock()
            self.assertEqual(self.handle(engine, request)[0], 400)
            engine.decode.assert_not_called()
        batch = {"model": ALIAS, "batch": [self.request()]}
        self.assertEqual(srv.handle_predict_batch(self.engine(), ALIAS, json.dumps(batch).encode())[0], 400)

    def test_launcher_and_server_cli_require_explicit_bounded_model_approval(self):
        for args in (["--experimental-bet-action"], ["--enable-inference", "--experimental-bet-action"],
                     ["verify", "--enable-inference", "--automatic-inference", "--experimental-bet-action"]):
            with patch.object(srv, "load_pins") as pins, patch.object(srv, "cmd_serve") as serve, \
                    patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                srv.main(args)
            pins.assert_not_called()
            serve.assert_not_called()
        with patch.object(srv, "load_pins", return_value={}), patch.object(srv, "cmd_serve", return_value=0) as serve:
            srv.main(["serve", "--enable-inference", "--automatic-inference", "--experimental-bet-action"])
        self.assertIs(serve.call_args.kwargs["experimental_bet_action"], True)
        launcher = (SCRIPTS / "start-vlm.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$ExperimentalBetAction", launcher)
        self.assertIn("if ($ExperimentalBetAction -and -not $AutomaticInference)", launcher)
        self.assertIn("if ($ExperimentalBetAction) { $serverArgs += '--experimental-bet-action' }", launcher)

    def test_automatic_startup_forwards_only_explicit_service_consent_to_source_approval(self):
        from scripts.tests.test_laya_capture import listing
        capture = srv.manual_capture
        selected = capture.attach.AttachResult("ready", (("pid", 42), ("window_hwnd", "0x123")))
        for flag in (False, True):
            service = srv.Service(ALIAS, experimental_bet_action=flag)
            service.state.set_model("ready", floors_loaded=True)
            startup = capture.AutomaticStart(service)
            with patch.object(capture.attach, "list_windows", return_value=listing()), \
                    patch.object(capture.attach.PracticeAttachment, "select", return_value=selected), \
                    patch.object(capture, "supervise", return_value=0) as child, \
                    patch.object(capture, "public_snapshot", return_value={"status": "stopped", "stop_reason": "duration-limit"}):
                startup._run()
            child.assert_called_once()
            self.assertIs(child.call_args.kwargs["inference_approval"]["experimental_bet_action"], flag)
            self.assertEqual(child.call_args.kwargs["source_policy"], "automatic-bounded")

    def test_missing_invalid_or_raised_donor_floor_cannot_be_hidden_by_experimental_metadata(self):
        for floor in (None, True, "0.8", float("nan"), .95):
            engine = self.engine()
            engine.acceptance_floors["p5_seat_1_stack"] = floor
            engine.decode = Mock()
            self.assertEqual(self.handle(engine, self.request()),
                             (503, {"error": "experimental-candidate-unavailable"}))
            engine.decode.assert_not_called()
        engine = self.engine()
        engine.acceptance_floors.pop("p2_board")
        engine.decode = Mock()
        self.assertEqual(self.handle(engine, self.request(kind="scene")),
                         (503, {"error": "experimental-candidate-unavailable"}))
        engine.decode.assert_not_called()

    def test_metadata_verifies_pinned_existing_it1_temperature_and_donor_before_heavy_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / srv.EXPERIMENTAL_CHECKPOINT
            base.mkdir(parents=True)
            ft = {"path": srv.EXPERIMENTAL_CHECKPOINT, "acceptance_file": "calibration.json",
                  "calibration_file": "laya-calibration.json", "files": [{"path": "model.safetensors",
                      "size": 804696880, "sha256": srv.EXPERIMENTAL_MODEL_SHA256}]}
            pins = {"model": {"finetuned": ft}}
            def write(name, value):
                raw = json.dumps(value).encode()
                (base / name).write_bytes(raw)
                entry = {"path": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                existing = next((item for item in ft["files"] if item["path"] == name), None)
                existing.update(entry) if existing else ft["files"].append(entry)
            temperatures = {"temperatures": {"choice": 3.7963288600952434},
                            "checkpoint": {"ckpt": srv.EXPERIMENTAL_CHECKPOINT}}
            for floor in (.8, .95, .79):
                floors = {**FLOORS, "p5_seat_1_stack": floor}
                write("calibration.json", {"ckpt": srv.EXPERIMENTAL_CHECKPOINT, "thresholds_per_pass": floors})
                write("laya-calibration.json", temperatures)
                with patch.object(srv, "ROOT", root), patch.object(srv, "REPO", str(root)):
                    metadata = srv.load_experimental_metadata(pins, floors)
                self.assertEqual(metadata["inherited_cutoff"], max(.8, floor))
                self.assertEqual(metadata["donor_pass"], "p5_seat_1_stack")
                self.assertNotIn("fitted_floor", metadata)
            floors = FLOORS
            write("calibration.json", {"ckpt": srv.EXPERIMENTAL_CHECKPOINT, "thresholds_per_pass": floors})
            for value in (None, {}, {"temperatures": {"choice": 0}, "checkpoint": temperatures["checkpoint"]},
                          {"temperatures": {"choice": "trained"}, "checkpoint": temperatures["checkpoint"]},
                          {**temperatures, "checkpoint": {"ckpt": "different-model"}}):
                write("laya-calibration.json", value)
                with patch.object(srv, "ROOT", root), patch.object(srv, "REPO", str(root)), \
                        self.assertRaisesRegex(ValueError, "experimental-temperature-unavailable"):
                    srv.load_experimental_metadata(pins, floors)
            write("laya-calibration.json", temperatures)
            (base / "laya-calibration.json").write_bytes(b"tampered temperature")
            with patch.object(srv, "ROOT", root), patch.object(srv, "REPO", str(root)), self.assertRaises(ValueError):
                srv.load_experimental_metadata(pins, floors)
            ft["files"][0]["sha256"] = "2" * 64
            with patch.object(srv, "ROOT", root), patch.object(srv, "REPO", str(root)), self.assertRaises(ValueError):
                srv.load_experimental_metadata(pins, floors)


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


class CaptureControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = srv.Service(ALIAS)
        self.service.manual_feed = SimpleNamespace(root=self.root)
        self.sid = "a" * 32
        self.path = srv.manual_capture.session_path(self.sid, root=self.root)
        self.path.mkdir(parents=True)
        self.approval = {"mode": "capture-only", "service_instance_id": None}
        srv.manual_capture.write_json(self.path / "approval.json", self.approval)
        self.snapshot = {"status": "capturing", "session_id": self.sid}
        self.patch = patch.object(srv.manual_capture, "public_snapshot", return_value=self.snapshot)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def body(self, **changes):
        return json.dumps({"session_id": self.sid, "service_instance_id": self.service.instance_id, **changes}).encode()

    def request(self, body=None, *, origin=None, method="POST", content_type="application/json", route="/api/capture/stop"):
        handler = srv.make_handler(None, ALIAS, {}, None, self.service)
        request = handler.__new__(handler)
        request.path, request.command = route, method
        request.server = SimpleNamespace(server_address=("127.0.0.1", 12345))
        request.headers = Message()
        request.headers["Host"] = "127.0.0.1:12345"
        if origin is not None:
            request.headers["Origin"] = origin
        body = self.body() if body is None else body
        request.headers["Content-Length"] = str(len(body))
        request.headers["Content-Type"] = content_type
        request.rfile, request._send = io.BytesIO(body), Mock()
        getattr(handler, "do_" + method)(request)
        return request._send.call_args.args

    def test_explicit_stop_works_without_model_or_gpu_and_invalidates_current_data(self):
        self.service.state.capture.update(fresh_capture=True, epoch=1)
        control = self.service.capture_controls(self.snapshot)
        self.assertTrue(control["enabled"])
        self.assertTrue(control["can_stop"])
        self.assertFalse(control["can_start"])
        with patch.object(srv, "Engine") as engine:
            self.assertEqual(self.request(), (200, {"ok": True}))
        engine.assert_not_called()
        self.assertTrue((self.path / "STOP").is_file())
        self.assertFalse(self.service.state.snapshot()["capture"]["fresh_capture"])
        self.assertIsNone(self.service.engine)

    def test_stop_requires_current_session_and_service_not_an_arbitrary_receipt(self):
        for body in (self.body(session_id="b" * 32), self.body(service_instance_id="c" * 32)):
            self.assertEqual(self.request(body), (409, {"error": "capture-session-unavailable"}))
            self.assertFalse((self.path / "STOP").exists())
        self.snapshot["status"] = "stopped"
        self.assertEqual(self.request()[0], 409)
        self.assertFalse((self.path / "STOP").exists())
        self.snapshot["status"] = "capturing"
        self.service.shutting_down.set()
        self.assertEqual(self.request()[0], 409)
        self.assertFalse((self.path / "STOP").exists())

    def test_inference_stop_is_bound_to_its_service(self):
        self.approval.update(mode="inference-enabled", service_instance_id="d" * 32)
        srv.manual_capture.write_json(self.path / "approval.json", self.approval)
        self.assertEqual(self.request()[0], 409)
        self.assertFalse((self.path / "STOP").exists())
        self.approval["service_instance_id"] = self.service.instance_id
        srv.manual_capture.write_json(self.path / "approval.json", self.approval)
        self.assertEqual(self.request(), (200, {"ok": True}))

    def test_get_cross_origin_bad_json_and_oversized_stop_never_mutate(self):
        self.assertEqual(self.request(method="GET")[0], 404)
        self.assertEqual(self.request(origin="https://unrelated.invalid")[0], 403)
        self.assertEqual(self.request(content_type="text/plain")[0], 415)
        self.assertEqual(self.request(b" " * 513)[0], 413)
        for body in (b"{", b"null", b"[]", b'{"session_id":NaN}',
                     b'{"session_id":"a","session_id":"b","service_instance_id":"c"}',
                     self.body(path="../another-session"), self.body(session_id="../another-session"),
                     self.body(service_instance_id=True)):
            self.assertEqual(self.request(body), (400, {"error": "invalid-request"}))
        self.assertFalse((self.path / "STOP").exists())

    def configure_manual(self):
        self.service.engine = object()
        self.service.inference_enabled = True
        self.service.state.set_model("ready")
        self.snapshot.update(status="failed")
        previous = SimpleNamespace(profile=".local/practice-table.json", root=self.root,
            continuous_observation=True, thread=None, session_id=self.sid, closed=threading.Event())
        self.service.automatic_startup = previous
        return previous

    def start_body(self, **changes):
        return json.dumps({"service_instance_id": self.service.instance_id,
            "control_id": self.service.capture_control_id, **changes}).encode()

    def test_start_rearms_only_explicitly_without_reloading_model(self):
        previous = self.configure_manual()
        engine = self.service.engine
        starter = SimpleNamespace(thread=SimpleNamespace(is_alive=lambda: True), closed=threading.Event(), session_id=None, start=Mock())
        old_body = self.start_body()
        with patch.object(srv.manual_capture, "AutomaticStart", return_value=starter) as factory, patch.object(srv, "Engine") as load:
            result = self.request(old_body, route="/api/capture/start")
            self.assertEqual(result, (202, {"ok": True, "control_id": self.service.capture_control_id}))
            self.assertNotEqual(json.loads(old_body)["control_id"], self.service.capture_control_id)
            self.assertEqual(self.request(old_body, route="/api/capture/start")[0], 409)
            self.assertEqual(self.request(self.start_body(), route="/api/capture/start")[0], 409)
        factory.assert_called_once_with(self.service, profile=previous.profile, root=self.root, continuous_observation=True)
        starter.start.assert_called_once()
        load.assert_not_called()
        self.assertIs(self.service.engine, engine)

    def test_start_rejects_unconfigured_loading_active_stale_or_invalid_requests(self):
        self.configure_manual()
        cases = [b"{", b"null", b"[]", b'{"control_id":NaN}',
            b'{"control_id":"a","control_id":"b","service_instance_id":"c"}',
            self.start_body(control_id=True), self.start_body(path="../other")]
        with patch.object(srv.manual_capture, "AutomaticStart") as factory:
            for body in cases:
                self.assertEqual(self.request(body, route="/api/capture/start"), (400, {"error": "invalid-request"}))
            self.assertEqual(self.request(self.start_body(service_instance_id="f" * 32), route="/api/capture/start")[0], 409)
            self.assertEqual(self.request(self.start_body(control_id="f" * 32), route="/api/capture/start")[0], 409)
            self.snapshot["status"] = "capturing"
            self.assertEqual(self.request(self.start_body(), route="/api/capture/start")[0], 409)
            self.snapshot["status"] = "failed"
            self.service.state.set_model("loading")
            self.assertEqual(self.request(self.start_body(), route="/api/capture/start")[0], 409)
            self.service.state.set_model("ready")
            self.service.automatic_startup = None
            self.assertEqual(self.request(self.start_body(), route="/api/capture/start")[0], 409)
            self.assertEqual(self.request(self.start_body(), route="/api/capture/start", origin="https://unrelated.invalid")[0], 403)
            self.assertEqual(self.request(b" " * 513, route="/api/capture/start")[0], 413)
            self.assertEqual(self.request(self.start_body(), route="/api/capture/start", method="GET")[0], 404)
        factory.assert_not_called()

    def test_stop_cancels_pending_discovery_only_for_the_current_control_token(self):
        previous = self.configure_manual()
        previous.session_id = None
        previous.thread = SimpleNamespace(is_alive=lambda: True)
        body = self.body(session_id=None, control_id=self.service.capture_control_id)
        self.assertEqual(self.request(self.body(session_id=None, control_id="e" * 32))[0], 409)
        self.assertFalse(previous.closed.is_set())
        self.assertEqual(self.request(body), (200, {"ok": True}))
        self.assertTrue(previous.closed.is_set())
        self.assertEqual(self.service.capture_controls(self.snapshot)["status"], "stopping")
        self.assertFalse(self.service.capture_controls(self.snapshot)["can_start"])

    def test_stop_racing_source_bind_stops_the_new_bound_session_without_new_model(self):
        previous = self.configure_manual()
        previous.session_id = self.sid
        previous.thread = SimpleNamespace(is_alive=lambda: True)
        self.snapshot["status"] = "capturing"
        self.assertEqual(self.request(self.body(session_id=None, control_id=self.service.capture_control_id)), (200, {"ok": True}))
        self.assertTrue(previous.closed.is_set())
        self.assertTrue((self.path / "STOP").is_file())

    def test_pending_stop_does_not_require_delayed_capture_receipt_to_be_published(self):
        previous = self.configure_manual()
        previous.thread = SimpleNamespace(is_alive=lambda: True)
        self.assertEqual(self.snapshot["status"], "failed")
        self.assertEqual(self.request(self.body(session_id=None, control_id=self.service.capture_control_id)), (200, {"ok": True}))
        self.assertTrue(previous.closed.is_set())
        self.assertTrue((self.path / "STOP").is_file())


class IntegrationTests(unittest.TestCase):
    def test_manual_start_configures_source_without_arming_on_server_boot(self):
        pins = {"server": {"port": 18090, "alias": ALIAS}, "model": {"revision": "synthetic", "finetuned": {}}}
        with patch.object(srv, "BoundedHTTPServer"), patch.object(srv.threading, "Thread"), \
                patch.object(srv.dashboard, "ManualSessionFeed"), \
                patch.object(srv.manual_capture, "AutomaticStart") as automatic, \
                patch.object(srv, "Engine") as engine, patch("sys.stdout", io.StringIO()):
            self.assertEqual(srv.cmd_serve(pins, None, None, dashboard_only=False, enable_inference=True,
                automatic_inference=True, continuous_observation=True, manual_start=True), 0)
        automatic.assert_called_once()
        automatic.return_value.start.assert_not_called()
        self.assertEqual(automatic.return_value.status, "stopped")
        self.assertEqual(automatic.return_value.reason, "operator-start-required")
        engine.assert_not_called()

    def test_manual_start_cli_requires_source_configuration_and_forwards_explicit_intent(self):
        with patch.object(srv, "load_pins", return_value={}), patch.object(srv, "cmd_serve", return_value=0) as serve:
            self.assertEqual(srv.main(["serve", "--enable-inference", "--automatic-inference", "--continuous-observation", "--manual-start"]), 0)
        self.assertTrue(serve.call_args.kwargs["manual_start"])
        for args in (["serve", "--manual-start"], ["serve", "--enable-inference", "--manual-start"]):
            with patch.object(srv, "load_pins") as pins, patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                srv.main(args)
            pins.assert_not_called()

    def test_status_refresh_reads_capture_metadata_without_arming_or_inference(self):
        service = srv.Service(ALIAS)
        handler = srv.make_handler(None, ALIAS, {}, None, service)
        request = handler.__new__(handler)
        request.path = "/api/state"
        request._local_request = Mock(return_value=True)
        request._send = Mock()
        metadata = srv.manual_capture.default_snapshot()
        with patch.object(srv.manual_capture, "public_snapshot", return_value=metadata), \
                patch.object(srv.manual_capture, "supervise") as start, \
                patch.object(srv.manual_capture.attach, "list_windows") as discover, \
                patch.object(srv, "Engine") as engine:
            handler.do_GET(request)
            handler.do_GET(request)
        start.assert_not_called()
        discover.assert_not_called()
        engine.assert_not_called()
        self.assertEqual(request._send.call_args.args[0], 200)
        snapshot = request._send.call_args.args[1]
        self.assertEqual(snapshot["capture_session"], metadata)
        self.assertFalse(snapshot["server"]["inference_enabled"])
        self.assertIsNone(snapshot["advice"])

    def test_explicit_inference_mode_is_reported_during_loading_without_engine(self):
        service = srv.Service(ALIAS)
        service.inference_enabled = True
        service.state.set_model("loading")
        handler = srv.make_handler(None, ALIAS, {}, None, service)
        request = handler.__new__(handler)
        request.path = "/api/state"
        request._local_request = Mock(return_value=True)
        request._send = Mock()
        with patch.object(srv.manual_capture, "public_snapshot", return_value=srv.manual_capture.default_snapshot()):
            handler.do_GET(request)
        state = request._send.call_args.args[1]
        self.assertTrue(state["server"]["inference_enabled"])
        self.assertEqual(state["server"]["model_state"], "loading")
        self.assertFalse(state["capture_session"]["inference_enabled"])
        self.assertIsNone(service.engine)

    def test_cli_requires_inference_opt_in_and_rejects_automatic_capture(self):
        for args, expected in ((["serve"], (True, None, False, srv.dashboard.DEFAULT_PROFILE, False)),
                               (["serve", "--dashboard-only"], (True, None, False, srv.dashboard.DEFAULT_PROFILE, False)),
                               (["serve", "--enable-inference"], (False, None, False, srv.dashboard.DEFAULT_PROFILE, True))):
            with self.subTest(args=args), patch.object(srv, "load_pins", return_value={}), \
                    patch.object(srv, "cmd_serve", return_value=0) as serve:
                self.assertEqual(srv.main(args), 0)
                self.assertEqual(serve.call_args.args[3:], expected + (False,))
        for args in (["--auto-attach"], ["--live-config", ".local/test.json"],
                     ["--practice-config", ".local/other.json"], ["--dashboard-only", "--enable-inference"]):
            with patch.object(srv, "load_pins") as pins, patch.object(srv, "cmd_serve") as serve, \
                    patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                srv.main(args)
            pins.assert_not_called()
            serve.assert_not_called()

    def test_dashboard_default_never_creates_supervisor_or_model(self):
        pins = {"server": {"port": 18090, "alias": ALIAS}, "model": {"revision": "synthetic", "finetuned": {}}}
        for auto, profile in ((False, None), (True, None), (False, ".local/strict-selector.json")):
            with self.subTest(auto=auto, profile=profile), patch.object(srv, "BoundedHTTPServer") as http, \
                    patch.object(srv.dashboard, "AutoAttachFeed") as attach, patch.object(srv, "Engine") as engine, \
                    patch.object(srv.threading, "Thread") as thread, patch("sys.stdout", io.StringIO()):
                if auto or profile:
                    with self.assertRaises(ValueError):
                        srv.cmd_serve(pins, None, None, live_config=profile, auto_attach=auto)
                    http.assert_not_called()
                else:
                    self.assertEqual(srv.cmd_serve(pins, None, None), 0)
                    http.return_value.server_close.assert_called_once()
                engine.assert_not_called()
                thread.assert_not_called()
                attach.assert_not_called()
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

        with patch.object(srv, "BoundedHTTPServer") as http, patch.object(srv, "Service", side_effect=service), \
                patch.object(srv.threading, "Thread", side_effect=worker), patch.object(srv, "verify", return_value=[]), \
                patch.object(srv, "Engine", side_effect=ValueError("PRIVATE-REPORT-PATH")), patch("sys.stdout", io.StringIO()):
            http.return_value.serve_forever.side_effect = lambda: captured["initialize"]()
            srv.cmd_serve(pins, None, None, dashboard_only=False, enable_inference=True)
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

        with patch.object(srv, "BoundedHTTPServer") as http, patch.object(srv, "Service", side_effect=service), \
                patch.object(srv.threading, "Thread", side_effect=worker), patch.object(srv, "verify", return_value=[]), \
                patch.object(srv, "Engine", return_value=engine), patch.dict("sys.modules", {"PIL": SimpleNamespace(Image=image)}), \
                patch("sys.stdout", io.StringIO()):
            http.return_value.serve_forever.side_effect = lambda: captured["initialize"]()
            srv.cmd_serve(pins, None, None, dashboard_only=False, enable_inference=True)
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

    def test_unknown_control_routes_remain_unimplemented_without_socket_or_model(self):
        service = srv.Service(ALIAS)
        handler = srv.make_handler(None, ALIAS, {}, None, service)
        for route in ("/api/start", "/api/connect", "/api/stop", "/api/attach", "/api/state", "/api/replay", "/api/capture/mark"):
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

    def test_opt_in_readout_uses_existing_batch_route_and_independent_outputs(self):
        value = ReadoutBatchTests().batch()
        status, payload = self.req("/v1/laya/predict-batch", json.dumps(value).encode(),
                                   {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual([r["pass"] for r in payload["results"]], [r["pass"] for r in value["batch"]])
        self.assertIn("noul", payload["results"][0]["answers"]["ev_pot"])
        self.assertTrue(all(r["timing_shared_batch"] for r in payload["results"]))

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
