"""Stdlib-only tests for scripts/laya-server.py (no torch, laya, PIL or numpy needed)."""

import base64
import importlib.util
import json
import struct
import threading
import unittest
import urllib.error
import urllib.request
import zlib
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("laya_server", SCRIPTS / "laya-server.py")
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)

ALIAS = "coinpoker-laya-vision"


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
        self.calls = []
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
        self.assertEqual(set(payload), {"model", "pass", "answers", "timing_ms"})
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
