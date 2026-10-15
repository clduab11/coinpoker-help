"""Synthetic source-clock/hash/lifecycle checks; no real source or GPU."""
import copy
import hashlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from laya_visual import VisualWorker


class VisualTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.worker = VisualWorker(self.root, "instance", wall=lambda: 10)
        self.addCleanup(self.worker.stop)

    def evidence(self):
        from PIL import Image
        buffer = io.BytesIO()
        Image.new("RGB", (16, 24), "black").save(buffer, format="PNG")
        png = buffer.getvalue()
        path = self.root / "original.png"
        path.write_bytes(png)
        return path, {"frame_index": 1, "filename": "original.png", "width": 16, "height": 24,
            "sha256": hashlib.sha256(png).hexdigest(), "png_bytes": len(png),
            "source_utc_unix_ms": 9500, "captured_at_monotonic_ms": 40, "archival": True}

    def reader(self):
        self.worker.board = SimpleNamespace(recognize_frame=Mock(return_value={"candidate_cards": None}))
        self.worker.regions = {}
        self.worker.actions = SimpleNamespace(read=Mock(side_effect=lambda image, capture: {"capture": capture}))
        self.worker.timeline = SimpleNamespace(events=[], observe=Mock(return_value={"gaps": []}))

    def state(self):
        return {"session_id": "session", "server": {"instance_id": "instance"},
            "capture_session": {"status": "capturing"}, "capture": {"fresh_capture": True,
            "source_id": "source", "epoch": 1, "width": 16, "height": 24}}

    def board_reader(self, cards=("9h", "4c", "Ah"), unknown=()):
        self.reader()
        self.worker.board_cache = None
        bounds = [[index * 3, 0, (index + 1) * 3, 24] for index in range(5)]
        slots = [{"slot": index + 1, "card": cards[index] if index < len(cards) else None,
                  "state": "unknown" if index in unknown else "card_candidate" if index < len(cards) else "empty_candidate",
                  "status": "unknown" if index in unknown else "provisional" if index < len(cards) else "empty",
                  "empty_surface": {"supported": index not in unknown and index >= len(cards)},
                  "evidence_bounds": box, "reason": "synthetic-logic-only"}
                 for index, box in enumerate(bounds)]
        self.worker.board.recognize_frame.return_value = {
            "candidate_cards": list(cards) if not unknown else None, "slots": slots, "crop_bounds": bounds}

    def publish(self, frame, path, png=None):
        result = self.worker.process(frame, path, ("session", "source", 1), png)
        self.worker.value = result
        self.worker.value_pixels = png if png is not None else path.read_bytes()
        self.worker.latest_pixels = frame, self.worker.value_pixels
        return result

    def next_frame(self, frame, sequence=2, **overrides):
        return {**frame, "frame_index": sequence, "source_utc_unix_ms": 9500 + sequence * 100,
                "captured_at_monotonic_ms": 40 + sequence * 100, **overrides}

    def test_no_worker_thread_without_frames(self):
        self.assertIsNone(self.worker.thread)
        self.assertIsNone(self.worker.snapshot(self.state()))

    def test_original_pixels_hash_and_clocks_are_preserved(self):
        path, frame = self.evidence()
        self.reader()
        result = self.worker.process(frame, path, ("session", "source", 1))
        self.assertEqual(result["sha256"], frame["sha256"])
        self.assertEqual(result["captured_at_unix_ms"], 9500)
        self.assertEqual(result["captured_at_ms"], 40)
        self.assertEqual(result["expires_at_unix_ms"], 11000)
        self.assertFalse(result["quality_approved"])
        self.assertFalse(result["human_reviewed"])
        self.worker.value = result
        self.assertIsNotNone(self.worker.snapshot(self.state()))

    def test_changed_hash_size_and_dimensions_abstain(self):
        path, frame = self.evidence()
        self.reader()
        for overrides in ({"sha256": "0" * 64}, {"png_bytes": frame["png_bytes"] + 1}, {"width": 17}):
            with self.assertRaises(ValueError):
                self.worker.process({**frame, **overrides}, path, ("session", "source", 1))
        self.worker.board.recognize_frame.assert_not_called()

    def test_stale_or_future_frames_never_run_recognizers(self):
        path, frame = self.evidence()
        self.reader()
        for captured in (8500, 10001):
            with self.assertRaisesRegex(ValueError, "frame-expired"):
                self.worker.process({**frame, "source_utc_unix_ms": captured}, path, ("session", "source", 1))
        self.worker.board.recognize_frame.assert_not_called()

    def test_receipt_source_service_geometry_and_epoch_invalidations(self):
        path, frame = self.evidence()
        self.reader()
        self.worker.value = self.worker.process(frame, path, ("session", "source", 1))
        for category, overrides in (("capture", {"fresh_capture": False}), ("capture", {"source_id": "other"}),
            ("capture", {"epoch": 2}), ("capture", {"width": 17}),
            ("capture_session", {"status": "ended"}), ("server", {"instance_id": "other"})):
            state = self.state()
            state[category].update(overrides)
            self.assertIsNone(self.worker.snapshot(state))
        self.worker.wall = lambda: 11
        self.assertIsNone(self.worker.snapshot(self.state()))

    def test_bad_mailbox_metadata_never_starts_a_worker(self):
        row = {"frame": {"source_utc_unix_ms": 9500, "frame_index": 1}}
        self.worker.submit(row, "session", "source", 1)
        self.assertIsNone(self.worker.thread)
        self.assertIsNone(self.worker.pending)

    def test_slot_dto_has_full_original_capture_and_no_native_floor_dependency(self):
        path, frame = self.evidence()
        frame.update(source_id=4030215874350685307, capture_session_id="capture", generation=None,
                     source_process_created_at_100ns=134364617596088162, pixel_source="visible_desktop_pixels")
        self.board_reader()
        result = self.publish(frame, path)
        state = self.state()
        state.update(observation=None, partial_observation=None,
                     inference={"reason": "below-floor", "floor": 1.0})
        state["capture"]["generation"] = 85
        snapshot = self.worker.snapshot(state)
        self.assertEqual(snapshot["board"]["candidate_cards"], ["9h", "4c", "Ah"])
        for slot in snapshot["board_slots"][:3]:
            receipt = slot["capture"]
            self.assertEqual(receipt["captured_at_unix_ms"], 9500)
            self.assertEqual(receipt["captured_at_ms"], 40)
            self.assertEqual(receipt["native_source_id"], "4030215874350685307")
            self.assertEqual(receipt["capture_session_id"], "capture")
            self.assertEqual(receipt["service_instance_id"], "instance")
            self.assertEqual(receipt["sha256"], result["sha256"])
            self.assertEqual(receipt["bounds"], slot["bounds"])
            self.assertIsNone(receipt["generation"])
        self.assertFalse(snapshot["quality_approved"])
        self.assertFalse(snapshot["human_reviewed"])

    def test_turn_or_river_animation_does_not_blank_source_current_flop(self):
        from PIL import Image
        path, frame = self.evidence()
        self.board_reader()
        self.publish(frame, path)
        for index in (3, 4):
            image = Image.open(path).convert("RGB")
            image.putpixel((index * 3, 1), (200, 200, 200))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            self.worker.latest_pixels = self.next_frame(frame), buffer.getvalue()
            value = self.worker.snapshot(self.state())
            self.assertEqual([s["card"] for s in value["board_slots"][:3]], ["9h", "4c", "Ah"])
            self.assertEqual(value["board_slots"][index]["status"], "unknown")
            self.assertIsNone(value["board"]["candidate_cards"])
            self.assertEqual(value["board"]["last_seen"]["candidate_cards"], ["9h", "4c", "Ah"])

    def test_partial_recognition_keeps_flop_when_turn_unmatched(self):
        path, frame = self.evidence()
        self.board_reader(unknown=(3,))
        value = self.publish(frame, path)
        self.assertEqual([s["card"] for s in value["board_slots"]], ["9h", "4c", "Ah", None, None])
        self.assertIsNone(value["board"]["candidate_cards"])
        self.assertEqual(value["board"]["last_seen"]["candidate_cards"], ["9h", "4c", "Ah"])

    def test_masked_slot_is_not_vacant_or_new_hand_and_keeps_aged_card(self):
        path, frame = self.evidence()
        self.board_reader(("9h", "4c", "Ah", "2d", "2c"))
        first = self.publish(frame, path)
        overlay = [9, 0, 12, 24]
        value = self.worker.snapshot(self.state(), occluded_regions=[overlay])
        self.assertEqual([s["card"] for s in value["board_slots"]], ["9h", "4c", "Ah", None, "2c"])
        self.assertEqual(value["board_slots"][3]["status"], "occluded")
        self.assertFalse(value["board"]["empty_board_supported"])
        aged = value["board"]["last_seen"]["board_slots"][3]
        self.assertEqual(aged["card"], "2d")
        self.assertEqual(aged["status"], "last_seen")
        self.assertEqual(aged["capture"], first["board_slots"][3]["capture"])
        self.board_reader(())
        frame = self.next_frame(frame, occluded_regions=[overlay])
        value = self.publish(frame, path)
        self.assertFalse(value["board"]["empty_board_supported"])
        self.assertEqual(value["board"]["last_seen"]["candidate_cards"], ["9h", "4c", "Ah", "2d", "2c"])

    def test_expired_and_missing_producer_preserve_original_last_seen_without_renewal(self):
        path, frame = self.evidence()
        self.board_reader()
        first = self.publish(frame, path)
        self.worker.wall = lambda: 12
        value = self.worker.snapshot(self.state())
        self.assertIsNotNone(value)
        self.assertEqual(value["expires_at_unix_ms"], 11000)
        self.assertTrue(value["current_uncertain"])
        self.assertTrue(all(s["status"] == "unknown" for s in value["board_slots"]))
        self.assertEqual(value["board"]["last_seen"]["board_slots"][0]["capture"], first["board_slots"][0]["capture"])
        self.worker.wall = lambda: 10
        self.assertTrue(self.worker.snapshot(self.state())["current_uncertain"])
        state = self.state()
        state["capture"]["fresh_capture"] = False
        self.assertEqual(self.worker.snapshot(state)["board"]["last_seen"]["candidate_cards"], ["9h", "4c", "Ah"])

    def test_monotonic_expiry_does_not_restore_cards_after_clock_rollback(self):
        path, frame = self.evidence()
        self.board_reader()
        self.publish(frame, path)
        self.worker.monotonic = lambda: 101
        self.worker.deadline = 100
        self.assertTrue(self.worker.snapshot(self.state())["current_uncertain"])
        self.worker.monotonic = lambda: 99
        self.assertTrue(self.worker.snapshot(self.state())["current_uncertain"])

    def test_compute_cache_rebinds_only_validated_new_original_receipts(self):
        path, frame = self.evidence()
        self.board_reader()
        first = self.publish(frame, path)
        next_frame = self.next_frame(frame)
        second = self.publish(next_frame, path)
        self.assertEqual(self.worker.board.recognize_frame.call_count, 1)
        self.assertEqual(self.worker.actions.read.call_count, 2)
        self.assertEqual(self.worker.timeline.observe.call_count, 2)
        self.assertEqual(second["sha256"], first["sha256"])
        self.assertEqual(second["board_slots"][0]["capture"]["sequence"], 2)
        self.assertEqual(second["board_slots"][0]["capture"]["captured_at_unix_ms"], 9700)
        self.assertEqual(second["expires_at_unix_ms"], 11200)
        history = copy.deepcopy(self.worker.board_last_seen)
        for replay in (next_frame, {**next_frame, "frame_index": 3},
                       {**next_frame, "frame_index": 3, "source_utc_unix_ms": 9800}):
            with self.assertRaisesRegex(ValueError, "replayed-frame-receipt"):
                self.worker.process(replay, path, ("session", "source", 1))
        self.assertEqual(self.worker.board_last_seen, history)
        self.assertEqual(self.worker.timeline.observe.call_count, 2)

    def test_unreadable_or_unknown_slots_do_not_clear_previous_board(self):
        path, frame = self.evidence()
        self.board_reader(("9h", "4c", "Ah", "2d"))
        first = self.publish(frame, path)
        self.board_reader((), unknown=range(5))
        value = self.publish(self.next_frame(frame), path)
        self.assertFalse(value["board"]["empty_board_supported"])
        self.assertEqual(value["board"]["board_generation"], first["board"]["board_generation"])
        self.assertEqual(value["board"]["last_seen"]["candidate_cards"], ["9h", "4c", "Ah", "2d"])
        self.board_reader(())
        self.worker.board_cache = None
        value = self.publish(self.next_frame(frame, 3, readability="unknown"), path)
        self.assertFalse(value["board"]["empty_board_supported"])
        self.assertEqual(value["board"]["last_seen"]["candidate_cards"], ["9h", "4c", "Ah", "2d"])

    def test_supported_empty_or_contradiction_retires_only_board_evidence(self):
        path, frame = self.evidence()
        self.board_reader(("9h", "4c", "Ah", "2d"))
        first = self.publish(frame, path)
        self.board_reader(())
        self.worker.board_cache = None
        value = self.publish(self.next_frame(frame), path)
        self.assertEqual(value["board"]["candidate_cards"], [])
        self.assertTrue(value["board"]["empty_board_supported"])
        self.assertIsNone(value["board"]["stage"])
        self.assertIsNone(value["board"]["last_seen"])
        self.assertGreater(value["board"]["board_generation"], first["board"]["board_generation"])
        self.board_reader(("9h", "4c", "Ah", "2d"))
        self.worker.board_cache = None
        self.publish(self.next_frame(frame, 3), path)
        self.board_reader(("Td", "8d", "As"), unknown=(3, 4))
        self.worker.board_cache = None
        value = self.publish(self.next_frame(frame, 4), path)
        self.assertEqual(value["board"]["last_seen"]["candidate_cards"], ["Td", "8d", "As"])
        self.assertEqual(value["board"]["last_seen"]["hand_boundary"], "unknown")

    def test_last_seen_is_fenced_by_native_source_session_and_geometry(self):
        path, frame = self.evidence()
        frame.update(source_id=17, capture_session_id="capture-a", source_process_created_at_100ns=1)
        self.board_reader()
        self.publish(frame, path)
        for override in ({"source_id": 18}, {"capture_session_id": "capture-b"},
                         {"source_process_created_at_100ns": 2}):
            self.worker.latest_pixels = self.next_frame(frame, **override), path.read_bytes()
            self.assertIsNone(self.worker.snapshot(self.state()))
        self.worker.latest_pixels = frame, path.read_bytes()
        state = self.state()
        state["capture"]["width"] = 939
        self.assertIsNone(self.worker.snapshot(state))

    def test_source_face_witness_not_unused_crop_margin(self):
        from PIL import Image
        path, frame = self.evidence()
        self.board_reader()
        raw = self.worker.board.recognize_frame.return_value
        raw["slots"][0]["evidence_bounds"] = [1, 1, 2, 23]
        self.publish(frame, path)
        image = Image.open(path).convert("RGB")
        image.putpixel((0, 0), (200, 200, 200))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        self.worker.latest_pixels = self.next_frame(frame), buffer.getvalue()
        value = self.worker.snapshot(self.state())
        self.assertEqual(value["board_slots"][0]["card"], "9h")
        self.assertEqual(value["board_slots"][0]["capture"]["captured_at_unix_ms"], 9500)

    def test_intermediate_changed_or_masked_slot_cannot_restore_old_current_card(self):
        from PIL import Image
        path, frame = self.evidence()
        self.board_reader()
        self.publish(frame, path)
        directory = self.root / ".local/captures/utc-1-000000001-practice"
        directory.mkdir(parents=True)
        path = directory / "live-frame-0.png"
        original = self.worker.value_pixels
        image = Image.open(io.BytesIO(original)).convert("RGB")
        image.putpixel((0, 1), (200, 200, 200))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        png = buffer.getvalue()
        path.write_bytes(png)
        changed = self.next_frame(frame, filename=path.name, sha256=hashlib.sha256(png).hexdigest(), png_bytes=len(png))
        self.worker.scope, self.worker.last_ticket = ("session", "source", 1), (1, 9500, 40)
        self.worker.thread = Mock(is_alive=Mock(return_value=False))
        self.worker.context.thread = Mock(is_alive=Mock(return_value=False))
        self.worker.submit({"frame": changed, "capture_directory": str(directory)}, "session", "source", 1)
        path.write_bytes(original)
        restored = self.next_frame(frame, 3, filename=path.name)
        self.worker.submit({"frame": restored, "capture_directory": str(directory)}, "session", "source", 1)
        value = self.worker.snapshot(self.state())
        self.assertIsNone(value["board_slots"][0]["card"])
        self.assertEqual(value["board_slots"][1]["card"], "4c")
        self.assertEqual(value["board"]["last_seen"]["board_slots"][0]["card"], "9h")

    def test_snapshot_mask_removal_requires_a_new_original_not_poll_reconfirmation(self):
        path, frame = self.evidence()
        self.board_reader()
        first = self.publish(frame, path)
        value = self.worker.snapshot(self.state(), occluded_regions=[[0, 0, 3, 24]])
        self.assertEqual(value["board_slots"][0]["status"], "occluded")
        value = self.worker.snapshot(self.state())
        self.assertIsNone(value["board_slots"][0]["card"])
        self.assertEqual(value["board_slots"][1]["card"], "4c")
        self.assertEqual(value["board"]["last_seen"]["board_slots"][0]["capture"], first["board_slots"][0]["capture"])
        self.publish(self.next_frame(frame), path)
        self.assertEqual(self.worker.snapshot(self.state())["board_slots"][0]["card"], "9h")

    def test_native_partial_mask_keeps_uncovered_board_slots(self):
        from laya_prep import box_px
        regions = {f"board_slot_{k}": [.31 + (k - 1) * .077, .36, .386 + (k - 1) * .077, .5]
                   for k in range(1, 6)}
        self.worker.regions = {"regions": regions}
        bounds = list(box_px(regions["board_slot_4"], 890, 678))
        bounds[0], bounds[2] = bounds[0] + 1, bounds[2] - 1
        state = {"capture": {"width": 890, "height": 678}, "field_statuses": {},
                 "partial_observation": {"board_slots": ["9h", "4c", "Ah", "2d", "2c"],
                                         "board_count": 5, "field_statuses": {}}}
        self.worker.mask_snapshot(state, {"occluded_regions": [bounds]})
        self.assertEqual(state["partial_observation"]["board_slots"], ["9h", "4c", "Ah", None, "2c"])
        self.assertIsNone(state["partial_observation"]["board_count"])
        self.assertEqual(state["field_statuses"]["board_slots.4"], {"status": "unavailable", "reason": "occluded"})
        self.assertNotIn("board_slots.1", state["field_statuses"])


if __name__ == "__main__":
    unittest.main()
