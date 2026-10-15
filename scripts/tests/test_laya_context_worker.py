import copy
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from laya_evidence import EventEvidence
from laya_visual import ContextWorker, VisualWorker, _current_region


class ContextWorkerTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive = EventEvidence(self.temp.name, "instance")
        self.addCleanup(self.archive.close)
        self.worker = ContextWorker(Path(self.temp.name), "instance", self.archive, wall=lambda: 10)
        self.addCleanup(self.worker.stop)
        self.image = Image.new("RGB", (20, 30), "navy")
        self.png = self.encode(self.image)
        self.capture = {"service_instance_id": "instance", "session_id": "feed", "source_id": "source",
            "capture_session_id": "owner", "epoch": 1, "sequence": 1, "captured_at_unix_ms": 9500,
            "captured_at_ms": 200, "sha256": hashlib.sha256(self.png).hexdigest(), "width": 20, "height": 30}
        self.scope = ("feed", "source", 1)
        self.worker.scope = self.scope
        self.worker.latest = ({"occluded_regions": []}, self.png, self.scope)
        self.worker.original = self.png
        self.worker.value = {"capture": self.capture, "expires_at_unix_ms": 14500,
            "role": "observing", "hero_seat": None,
            "evidence": {"role": {"bounds": [10, 20, 20, 30]}},
            "seats": [{"seat": 1, "bounds": [0, 0, 10, 10], "occupancy": "occupied",
                       "identity": "player", "continuity": "confirmed", "occupant_epoch": 1,
                       "stats": {"capture": copy.deepcopy(self.capture), "captured_at_unix_ms": 9500}}]}
        self.state = {"session_id": "feed", "server": {"instance_id": "instance"},
            "capture_session": {"status": "capturing"}, "capture": {"fresh_capture": True,
                "source_id": "source", "epoch": 1, "width": 20, "height": 30}}

    @staticmethod
    def encode(image):
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def test_stationary_popup_never_proves_visible_underlying_pixels(self):
        self.assertTrue(_current_region(self.png, self.png, [0, 0, 10, 10]))
        self.assertFalse(_current_region(self.png, self.png, [0, 0, 10, 10], [[0, 0, 2, 2]]))

    def test_region_change_detaches_identity_and_stats_without_vacancy(self):
        changed = self.image.copy()
        changed.putpixel((1, 1), (200, 10, 20))
        self.worker.latest = ({"occluded_regions": []}, self.encode(changed), self.scope)
        value = self.worker.snapshot(self.state)
        self.assertEqual(value["seats"][0]["occupancy"], "unknown")
        self.assertIsNone(value["seats"][0]["stats"])
        self.assertEqual(value["role"], "observing")
        self.assertEqual(value["capture"]["sequence"], 1)

    def test_original_timestamp_is_not_renewed_by_snapshot(self):
        for _ in range(3):
            value = self.worker.snapshot(self.state)
            self.assertEqual(value["capture"]["captured_at_unix_ms"], 9500)
            self.assertEqual(value["seats"][0]["stats"]["captured_at_unix_ms"], 9500)
        self.worker.wall = lambda: 14.5
        self.assertIsNone(self.worker.snapshot(self.state))

    def test_source_service_geometry_or_session_change_abstains(self):
        for key, change in (("capture", {"epoch": 2}), ("capture", {"width": 21}),
                            ("server", {"instance_id": "other"}),
                            ("capture_session", {"status": "failed"})):
            state = copy.deepcopy(self.state)
            state[key].update(change)
            self.assertIsNone(self.worker.snapshot(state))

    def test_intermediate_change_cannot_restore_old_identity(self):
        self.worker.thread = Mock(is_alive=Mock(return_value=False))
        changed = self.image.copy()
        changed.putpixel((1, 1), (200, 10, 20))
        self.worker.submit({"frame_index": 2}, self.encode(changed), self.scope, Path("unused"))
        self.worker.submit({"frame_index": 3}, self.png, self.scope, Path("unused"))
        value = self.worker.snapshot(self.state)
        self.assertIsNone(value["seats"][0]["identity"])
        self.assertIsNone(value["seats"][0]["stats"])
        self.assertIn(1, self.worker.pending_invalidations)

    def test_wall_clock_rollback_cannot_restore_expired_receipt(self):
        clock = [100]
        self.worker.monotonic = lambda: clock[0]
        self.assertIsNotNone(self.worker.snapshot(self.state))
        clock[0] = 106
        self.assertIsNone(self.worker.snapshot(self.state))
        self.worker.wall = lambda: 10
        clock[0] = 107
        self.assertIsNone(self.worker.snapshot(self.state))

    def test_revealed_card_roster_requires_current_name_pixels_and_keeps_identity_origin(self):
        capture = {**self.capture, "sequence": 2, "captured_at_unix_ms": 9900, "captured_at_ms": 600}
        roster = self.worker.roster_for_frame(capture, self.png, [])
        self.assertEqual(roster["capture"], capture)
        self.assertEqual(roster["seats"][0]["identity"], "player")
        self.assertEqual(roster["seats"][0]["capture"], capture)
        self.assertEqual(roster["seats"][0]["identity_capture"], self.capture)
        self.assertEqual(roster["evidence"]["role"]["capture"], capture)
        self.assertEqual(roster["evidence"]["role"]["origin_capture"], self.capture)
        changed = self.image.copy()
        changed.putpixel((1, 1), (20, 50, 100))
        rejected = self.worker.roster_for_frame(capture, self.encode(changed), [])
        self.assertIsNone(rejected["seats"][0]["identity"])
        self.assertEqual(rejected["seats"][0]["continuity"], "uncertain")
        self.assertIsNone(self.worker.roster_for_frame({**capture, "source_id": "other"}, self.png, []))
        self.worker.deadline = self.worker.monotonic() - 1
        self.assertIsNone(self.worker.roster_for_frame(capture, self.png, []))

    def test_occlusion_masks_real_partial_projection_not_full_observation(self):
        visual = VisualWorker(Path(self.temp.name), "other", wall=lambda: 10)
        self.addCleanup(visual.stop)
        visual.regions = {"regions": {"pot": [.4, .3, .6, .4]}}
        from laya_prep import box_px
        box = list(box_px([.4, .3, .6, .4], 939, 714))
        state = {"observation": None, "capture": {"width": 939, "height": 714},
                 "partial_observation": {"pot_size": 100, "pot_size_text": "1.00",
                     "board_slots": [None] * 5, "seats": [], "field_statuses": {}},
                 "field_statuses": {}}
        visual.mask_snapshot(state, {"occluded_regions": [box]})
        self.assertIsNone(state["partial_observation"]["pot_size"])
        self.assertEqual(state["field_statuses"]["pot_size"]["reason"], "occluded")

    def test_submit_pins_original_bytes_before_reused_mailbox_filename_changes(self):
        visual = VisualWorker(Path(self.temp.name), "other", wall=lambda: 10)
        self.addCleanup(visual.stop)
        visual.thread = Mock(is_alive=Mock(return_value=False))
        visual.context.thread = Mock(is_alive=Mock(return_value=False))
        directory = Path(self.temp.name) / ".local/captures/utc-1-000000001-practice"
        directory.mkdir(parents=True)
        path = directory / "live-frame-0.png"
        path.write_bytes(self.png)
        frame = {"event": "live_frame", "archival": False, "frame_index": 1,
                 "source_id": 17, "captured_at_monotonic_ms": 200, "source_utc_unix_ms": 9950,
                 "filename": path.name, "sha256": hashlib.sha256(self.png).hexdigest(),
                 "png_bytes": len(self.png), "width": 20, "height": 30}
        visual.submit({"frame": frame, "capture_directory": str(directory)}, "feed", "source", 1)
        queued_frame, filename, scope, pinned = visual.pending
        path.write_bytes(b"overwritten mailbox")
        self.assertEqual(pinned, self.png)
        visual.regions = {}
        visual.board = Mock()
        visual.board.recognize_frame.return_value = {"candidate_cards": [], "crop_bounds": []}
        visual.actions = Mock()
        visual.actions.read.side_effect = lambda image, capture: {
            "capture": capture, "seats": [{"seat": seat} for seat in range(1, 7)]}
        visual.timeline = Mock(events=[])
        visual.timeline.observe.return_value = {"gaps": []}
        visual._load = Mock()
        result = visual.process(queued_frame, filename, scope, pinned)
        self.assertEqual(result["sha256"], hashlib.sha256(self.png).hexdigest())
        with self.assertRaises(ValueError):
            visual.process(queued_frame, filename, scope)

    def test_unchanged_profile_values_still_pin_each_new_import_receipt(self):
        done = threading.Event()

        class Reader:
            def __init__(self, root):
                pass

            def read(self, image, capture, occluded_regions=()):
                return {"capture": capture, "table_context_id": "a" * 32,
                    "role": "observing", "hero_seat": None,
                    "evidence": {"role": {"bounds": [10, 20, 20, 30]}},
                    "profile": {"owner": "player", "seat": 1, "occupant_epoch": 1,
                        "status": "provisional", "source": "client_profile_tooltip", "capture": capture,
                        "bounds": [10, 10, 20, 20], "metrics": {}, "revision": "same-values"},
                    "seats": [{"seat": 1, "identity": "player", "occupancy": "occupied", "bounds": [0, 0, 10, 10]}]}

        class Timeline:
            def observe(self, result):
                value = copy.deepcopy(result)
                value["seats"][0].update(stats=copy.deepcopy(value["profile"]), continuity="confirmed", occupant_epoch=1)
                value["eventchanges"] = []
                return value

        worker = ContextWorker(Path(self.temp.name), "instance", self.archive, wall=lambda: 10)
        self.addCleanup(worker.stop)
        worker._log_attempt = lambda *args: done.set()
        module = SimpleNamespace(ContextReader=Reader, ContextTimeline=Timeline)
        with patch.dict(sys.modules, {"laya_context": module}):
            for sequence in (1, 2):
                done.clear()
                frame = {"frame_index": sequence, "source_id": 7, "captured_at_monotonic_ms": 200 + sequence,
                    "source_utc_unix_ms": 9500 + sequence, "sha256": hashlib.sha256(self.png).hexdigest(),
                    "width": 20, "height": 30, "archival": False}
                worker.submit(frame, self.png, self.scope, Path("mutable-mailbox.png"))
                self.assertTrue(done.wait(3), "finite context publication timed out")
                self.assertIsNone(worker.last_error)
            worker.stop()
        events = self.archive.event_snapshot()
        self.assertEqual([e["kind"] for e in events], ["profile-observation", "profile-observation"])
        self.assertEqual([e["capture"]["sequence"] for e in events], [1, 2])
        self.assertEqual(self.archive.snapshot()["frames"], 2)
        self.assertEqual(self.archive.read(events[1]["evidence_id"]), self.png)


if __name__ == "__main__":
    unittest.main()
