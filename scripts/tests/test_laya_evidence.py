import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from laya_evidence import EventEvidence


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        buffer = io.BytesIO()
        Image.new("RGB", (20, 30), "navy").save(buffer, format="PNG")
        self.png = buffer.getvalue()
        self.capture = {"service_instance_id": "instance", "session_id": "session",
            "source_id": "source", "epoch": 1, "sequence": 1, "captured_at_unix_ms": 10,
            "sha256": hashlib.sha256(self.png).hexdigest(), "width": 20, "height": 30}
        self.archive = EventEvidence(self.root, "instance")
        self.addCleanup(self.archive.close)

    def test_original_and_crop_survive_mailbox_overwrite(self):
        event = self.archive.record(self.png, self.capture, "tooltip", [], crops=[[1, 2, 9, 10]])
        self.assertEqual(self.archive.read(event["evidence_id"]), self.png)
        crop = event["crops"][0]
        self.assertEqual(hashlib.sha256(self.archive.read(crop["sha256"])).hexdigest(), crop["sha256"])
        self.assertEqual(event["capture"]["captured_at_unix_ms"], 10)
        self.assertIsNone(self.archive.read("../original.png"))

    def test_same_bytes_keep_distinct_capture_identities(self):
        a = self.archive.record(self.png, self.capture, "occupancy", [])
        b = self.archive.record(self.png, {**self.capture, "sequence": 2}, "role", [])
        self.assertEqual(a["evidence_id"], b["evidence_id"])
        self.assertNotEqual(a["event_id"], b["event_id"])
        self.assertEqual(self.archive.snapshot()["frames"], 2)
        self.assertEqual(self.archive.snapshot()["bytes"], len(self.png))

    def test_independent_popup_original_consumes_separate_frame_budget(self):
        self.archive.record(self.png, self.capture, "role", [])
        self.archive.record(self.png, {**self.capture, "popup_index": 0}, "profile", [])
        self.assertEqual(self.archive.snapshot()["frames"], 2)

    def test_budget_failure_is_distinct_from_capture(self):
        self.archive.max_frames = 1
        self.assertIsNotNone(self.archive.record(self.png, self.capture, "role", []))
        self.assertIsNone(self.archive.record(self.png, {**self.capture, "sequence": 2}, "role", []))
        self.assertFalse(self.archive.snapshot()["complete"])
        self.assertEqual(self.archive.snapshot()["reason"], "frame-limit")

    def test_tamper_and_archival_reuse(self):
        path = self.root / ".local/captures/original.png"
        path.parent.mkdir(parents=True)
        path.write_bytes(self.png)
        event = self.archive.record(self.png, self.capture, "board", [], original=path)
        self.assertEqual(self.archive.snapshot()["bytes"], 0)
        path.write_bytes(b"changed")
        self.assertIsNone(self.archive.read(event["evidence_id"]))

    def test_invalid_capture_hash_never_writes_event(self):
        self.assertIsNone(self.archive.record(self.png, {**self.capture, "sha256": "0" * 64}, "role", []))
        self.assertEqual(self.archive.snapshot()["count"], 0)

    def test_public_numeric_events_do_not_repeat_verbose_glyph_proofs_per_poll(self):
        def field():
            return {"literal": "0.07", "value": 7, "status": "provisional", "capture": self.capture,
                    "bounds": [0, 0, 2, 2], "crop_sha256": "b" * 64,
                    "glyph_provenance": "private-detailed-proof-" * 50}
        changes = {"pot": field(), "seats": [{"seat": i, "stack": field(), "wager": field()} for i in range(1, 7)]}
        for sequence in range(1, 25):
            self.assertIsNotNone(self.archive.record(self.png, {**self.capture, "sequence": sequence}, "visible-numeric-change", changes))
        public = self.archive.public_event_snapshot("session")
        self.assertEqual(len(public), 20)
        self.assertEqual(public[-1]["capture"]["sequence"], 24)
        self.assertEqual(len(public[-1]["changes"]), 13)
        self.assertLess(len(json.dumps(public).encode()), 64 * 1024)
        self.assertNotIn("glyph_provenance", json.dumps(public))
        self.assertIn("glyph_provenance", json.dumps(self.archive.event_snapshot()[-1]))


if __name__ == "__main__":
    unittest.main()
