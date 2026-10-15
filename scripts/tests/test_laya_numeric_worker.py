import copy
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from laya_evidence import EventEvidence
from laya_visual import NumericWorker


class NumericWorkerTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = EventEvidence(self.root, "instance")
        self.addCleanup(self.archive.close)
        self.wall, self.mono = [10], [50]
        self.worker = NumericWorker(self.root, "instance", self.archive,
            wall=lambda: self.wall[0], monotonic=lambda: self.mono[0])
        self.addCleanup(self.worker.stop)
        self.image = Image.new("RGB", (20, 30), "navy")
        self.png = self.encode(self.image)
        self.capture = {"service_instance_id": "instance", "session_id": "feed", "capture_session_id": "owner",
            "source_id": "source", "native_source_id": "1", "epoch": 1, "sequence": 1,
            "captured_at_ms": 200, "captured_at_unix_ms": 9500, "sha256": hashlib.sha256(self.png).hexdigest(),
            "width": 20, "height": 30}
        self.scope = ("feed", "source", 1)
        self.worker.scope = self.scope
        self.worker.original = self.png
        self.worker.latest = ({"frame_index": 1, "occluded_regions": []}, self.png, self.scope)
        self.worker.deadline = 51
        self.worker.value = self.result(self.capture)
        self.state = {"session_id": "feed", "server": {"instance_id": "instance"},
            "capture_session": {"session_id": "owner", "status": "capturing"},
            "capture": {"fresh_capture": True, "source_id": "source", "epoch": 1, "width": 20, "height": 30}}

    @staticmethod
    def encode(image):
        data = io.BytesIO()
        image.save(data, format="PNG")
        return data.getvalue()

    @staticmethod
    def result(capture):
        def field(literal, value, bounds):
            return {"status": "provisional", "literal": literal, "value": value,
                    "capture": copy.deepcopy(capture), "bounds": bounds}
        return {"schema_version": 1, "source": "cpu-visible-numeric", "provisional": True,
            "quality_approved": False, "capture": copy.deepcopy(capture),
            "expires_at_unix_ms": capture["captured_at_unix_ms"] + 1500,
            "pot": field("0.07", 7, [10, 10, 15, 15]),
            "seats": [{"seat": seat, "stack": field("1.23", 123, [0, 0, 5, 5]),
                       "wager": field("0.02", 2, [0, 10, 5, 15])} for seat in range(1, 7)]}

    def test_pot_pixel_change_does_not_invalidate_other_seats_or_renew_capture(self):
        changed = self.image.copy()
        changed.putpixel((11, 11), (50, 100, 200))
        self.worker.latest = ({"frame_index": 2, "occluded_regions": []}, self.encode(changed), self.scope)
        value = self.worker.snapshot(self.state)
        self.assertIsNone(value["pot"]["value"])
        self.assertEqual(value["seats"][0]["stack"]["literal"], "1.23")
        self.assertEqual(value["seats"][0]["wager"]["literal"], "0.02")
        self.assertEqual(value["capture"]["captured_at_unix_ms"], 9500)

    def test_popup_covers_only_its_regions_and_never_creates_zero(self):
        value = self.worker.snapshot(self.state, occluded_regions=[[10, 10, 15, 15]])
        self.assertEqual(value["pot"]["status"], "unknown")
        self.assertIsNone(value["pot"]["literal"])
        self.assertEqual(value["seats"][5]["stack"]["value"], 123)

    def test_latest_unknown_readability_immediately_withdraws_same_pixel_values(self):
        self.worker.thread = Mock(is_alive=Mock(return_value=False))
        self.worker.submit({"frame_index": 2, "readability": "unknown"}, self.png, self.scope, self.root / "mailbox.png")
        value = self.worker.snapshot(self.state)
        self.assertTrue(all(field["value"] is None for field in self.worker.fields(value)))
        self.worker.submit({"frame_index": 3, "readability": "full"}, self.png, self.scope, self.root / "mailbox.png")
        self.assertIsNone(self.worker.snapshot(self.state)["pot"]["value"])

    def test_identity_source_owner_and_geometry_boundaries_abstain(self):
        for key, changes in (("server", {"instance_id": "other"}), ("capture", {"width": 21}),
                             ("capture", {"source_id": "other"}), ("capture", {"epoch": 2}),
                             ("capture_session", {"session_id": "other"}), ("capture_session", {"status": "failed"})):
            state = copy.deepcopy(self.state)
            state[key].update(changes)
            self.assertIsNone(self.worker.snapshot(state))

    def test_monotonic_expiry_survives_wall_clock_rollback(self):
        self.assertIsNotNone(self.worker.snapshot(self.state))
        self.mono[0] = 51
        self.assertIsNone(self.worker.snapshot(self.state))
        self.wall[0] = 9.6
        self.assertIsNone(self.worker.snapshot(self.state))

    def test_wall_expiry_is_tombstoned_even_before_monotonic_deadline(self):
        self.wall[0] = 11
        self.assertIsNone(self.worker.snapshot(self.state))
        self.wall[0] = 10
        self.assertIsNone(self.worker.snapshot(self.state))

    def test_intermediate_changed_pixels_cannot_revive_old_pot(self):
        self.worker.thread = Mock(is_alive=Mock(return_value=False))
        changed = self.image.copy()
        changed.putpixel((11, 11), (50, 100, 200))
        self.worker.submit({"frame_index": 2}, self.encode(changed), self.scope, self.root / "mailbox.png")
        self.worker.submit({"frame_index": 3}, self.png, self.scope, self.root / "mailbox.png")
        self.assertIsNone(self.worker.snapshot(self.state)["pot"]["value"])
        current = {**self.capture, "sequence": 3, "captured_at_unix_ms": 9900}
        self.worker.value = self.result(current)
        self.worker.original = self.png
        self.assertEqual(self.worker.snapshot(self.state)["pot"]["value"], 7)

    def test_inflight_prechange_result_cannot_restore_after_latest_pixels_return(self):
        self.worker.thread = Mock(is_alive=Mock(return_value=False))
        changed = self.image.copy()
        changed.putpixel((11, 11), (50, 100, 200))
        self.worker.submit({"frame_index": 3}, self.encode(changed), self.scope, self.root / "mailbox.png")
        self.worker.submit({"frame_index": 4}, self.png, self.scope, self.root / "mailbox.png")
        older = {**self.capture, "sequence": 2, "captured_at_unix_ms": 9700}
        self.worker.value = self.result(older)
        self.worker.original = self.png
        self.assertIsNone(self.worker.snapshot(self.state)["pot"]["value"])
        fresh = {**self.capture, "sequence": 4, "captured_at_unix_ms": 9900}
        self.worker.value = self.result(fresh)
        self.assertEqual(self.worker.snapshot(self.state)["pot"]["value"], 7)

    def test_first_inflight_read_is_not_exempt_from_intermediate_capture_changes(self):
        self.worker.value = None
        self.worker.thread = Mock(is_alive=Mock(return_value=False))
        changed = self.image.copy()
        changed.putpixel((11, 11), (50, 100, 200))
        self.worker.submit({"frame_index": 2}, self.encode(changed), self.scope, self.root / "mailbox.png")
        self.worker.submit({"frame_index": 3}, self.png, self.scope, self.root / "mailbox.png")
        self.worker.value = self.result(self.capture)
        self.assertIsNone(self.worker.snapshot(self.state)["pot"]["value"])

    def test_independent_numeric_publication_pins_original_without_model_or_ocr(self):
        self.worker.value = None
        frame = {"frame_index": 1, "source_id": 1, "capture_session_id": "owner",
            "captured_at_monotonic_ms": 200, "source_utc_unix_ms": 9500,
            "sha256": hashlib.sha256(self.png).hexdigest(), "width": 20, "height": 30, "archival": False}
        self.worker.pending = frame, self.png, self.scope, self.root / "mutable-mailbox.png"
        self.worker.wake.set()

        class Reader:
            def __init__(self, root):
                pass

            def read(self, image, capture, occluded_regions=()):
                return NumericWorkerTests.result(capture)

        record = self.archive.record
        def finish(*args, **kwargs):
            event = record(*args, **kwargs)
            self.worker.closed.set()
            return event

        with patch.dict(sys.modules, {"laya_numeric": SimpleNamespace(NumericReader=Reader)}), \
                patch.object(self.archive, "record", side_effect=finish):
            self.worker._run()
        value = self.worker.value
        self.assertEqual(value["pot"]["literal"], "0.07")
        self.assertEqual(value["seats"][0]["wager"]["literal"], "0.02")
        event = self.archive.event_snapshot()[0]
        self.assertEqual(event["kind"], "visible-numeric-change")
        self.assertEqual(event["capture"]["sequence"], 1)
        self.assertEqual(self.archive.read(event["evidence_id"]), self.png)


if __name__ == "__main__":
    unittest.main()
