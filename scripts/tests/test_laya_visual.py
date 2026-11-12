"""Synthetic source-clock/hash/lifecycle checks; no real source or GPU."""
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
from laya_visual import VisualWorker, VisualLanes, _capture


class VisualIngressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.worker = VisualWorker(self.root, "instance", wall=lambda: 10, monotonic=lambda: 50)
        def finish():
            self.worker.stop()
            self.assertTrue(self.worker.shutdown_complete.wait(4), "synthetic workers did not exit")
        self.addCleanup(finish)
        from PIL import Image
        buffer = io.BytesIO()
        Image.new("RGB", (16, 24), "black").save(buffer, format="PNG")
        self.png = buffer.getvalue()
        directory = self.root / ".local/captures/utc-123-123456789-practice"
        directory.mkdir(parents=True)
        self.path = directory / "live-frame-0.png"
        self.path.write_bytes(self.png)
        self.row = {"capture_directory": str(directory), "capture_session_id": "owner", "frame": {
            "frame_index": 1, "filename": self.path.name, "width": 16, "height": 24,
            "sha256": hashlib.sha256(self.png).hexdigest(), "png_bytes": len(self.png),
            "source_utc_unix_ms": 9500, "captured_at_monotonic_ms": 40,
            "source_id": 7, "source_process_created_at_100ns": 9, "popup_frames": []}}
        self.state = {"session_id": "session", "server": {"instance_id": "instance"},
            "capture_session": {"session_id": "owner", "status": "capturing"},
            "capture": {"fresh_capture": True, "source_id": "source", "epoch": 1, "width": 16, "height": 24}}
        self.published = threading.Event()
        self.ingressed = threading.Event()
        self.archived = threading.Event()
        self.engines = []
        self.expected = 1
        self.process_hook = None

    def receipt(self, sequence, **changes):
        row = copy.deepcopy(self.row)
        row["frame"].update(frame_index=sequence, source_utc_unix_ms=9500 + sequence,
                            captured_at_monotonic_ms=40 + sequence, **changes)
        return row

    def lanes(self, *args, **kwargs):
        engine = VisualLanes(*args, **kwargs)
        engine.regions = {}
        def process(frame, filename, scope, png):
            capture = {**_capture(frame, scope, "instance"), "source_process_created_at_100ns": 9}
            if self.process_hook:
                self.process_hook(engine, frame)
            engine.board_last_seen = [{"slot": 1, "card": "Ah", "capture": capture}, None, None, None, None]
            return {"capture": capture, "sequence": capture["sequence"], "session_id": scope[0],
                "source_id": scope[1], "epoch": scope[2], "width": 16, "height": 24,
                "captured_at_unix_ms": capture["captured_at_unix_ms"],
                "expires_at_unix_ms": capture["captured_at_unix_ms"] + 1500,
                "board_slots": [], "board": {"last_seen": {"status": "last_seen", "sequence": capture["sequence"]}},
                "sightings": [], "actions": {}}
        engine.process = process
        def numeric(image, capture, **kwargs):
            return {"capture": capture, "expires_at_unix_ms": capture["captured_at_unix_ms"] + 1500,
                "pot": {"capture": capture, "literal": "1.00", "value": 100, "status": "provisional", "bounds": [0, 0, 2, 2]},
                "seats": []}
        engine.numeric.reader = SimpleNamespace(read=numeric)
        engine.context.reader = SimpleNamespace(read=lambda image, capture, **kwargs: {
            "capture": capture, "role": "observing", "seats": [], "table_context_id": "synthetic",
            "evidence": {"role": {"bounds": [0, 0, 2, 2]}}})
        engine.context.timeline = SimpleNamespace(observe=lambda result: {**copy.deepcopy(result), "eventchanges": []})
        record = engine.archive.record
        def archive(*args, **kwargs):
            result = record(*args, **kwargs)
            if args[2] == "visible-numeric-change" and args[1]["sequence"] == self.expected:
                self.archived.set()
            return result
        engine.archive.record = archive
        self.engines.append(engine)
        return engine

    def fixture_lanes(self):
        guard = patch("laya_visual.VisualLanes", side_effect=self.lanes)
        guard.start()
        self.addCleanup(guard.stop)
        project = self.worker._project
        def observe(*args):
            self.ingressed.set()
            result = project(*args)
            numeric = self.worker.cache.get("numeric_observation") or {}
            visual = self.worker.cache.get("visual_observation") or {}
            if numeric.get("capture", {}).get("sequence") == self.expected and visual.get("sequence") == self.expected:
                self.published.set()
            return result
        guard = patch.object(self.worker, "_project", side_effect=observe)
        guard.start()
        self.addCleanup(guard.stop)

    def submit(self, row=None):
        self.worker.submit(row or self.row, "session", "source", 1)

    def test_submit_returns_while_original_read_is_blocked(self):
        entered, release, returned = threading.Event(), threading.Event(), threading.Event()
        original = Path.open
        def read(path, *args, **kwargs):
            if path == self.path and args and args[0] == "rb":
                entered.set()
                release.wait(3)
            return original(path, *args, **kwargs)
        def submit():
            self.worker.submit(self.row, "session", "source", 1)
            returned.set()
        with patch.object(Path, "open", read):
            thread = threading.Thread(target=submit)
            thread.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(returned.wait(.3), "feed callback blocked on PNG read")
            finally:
                release.set()
                thread.join(3)

    def test_cached_snapshot_never_decodes_or_compares_pixels(self):
        state = {"session_id": "session", "server": {"instance_id": "instance"},
            "capture_session": {"session_id": "owner", "status": "capturing"},
            "capture": {"fresh_capture": True, "source_id": "source", "epoch": 1, "width": 16, "height": 24}}
        with patch("laya_visual._region_checks", side_effect=AssertionError("HTTP pixel comparison")):
            value = self.worker.cached_snapshot(state)
        self.assertIsNone(value["visual_observation"])

    def test_retirement_is_explicit_and_precedes_join(self):
        self.worker.revoke("test-retirement")
        self.assertIsNone(self.worker.pending)
        self.assertEqual(self.worker.diagnostics()["retirement_reason"], "test-retirement")

    def test_flood_has_one_executing_one_replaceable_pending_and_pins_only_latest(self):
        self.fixture_lanes()
        entered, release = threading.Event(), threading.Event()
        pin = self.worker._pin
        def blocked(row):
            entered.set()
            release.wait(3)
            return pin(row)
        with patch.object(self.worker, "_pin", side_effect=blocked):
            self.submit()
            self.assertTrue(entered.wait(1))
            try:
                for sequence in range(2, 301):
                    self.submit(self.receipt(sequence))
                self.assertEqual(self.worker.diagnostics()["pending"], 1)
                self.assertTrue(self.worker.diagnostics()["executing"])
                self.assertEqual(self.worker.pending[0]["frame"]["frame_index"], 300)
                self.assertEqual(self.worker.diagnostics()["drops"]["superseded"], 299)
                self.expected = 300
            finally:
                release.set()
            self.assertTrue(self.published.wait(3))
        self.assertEqual(len(self.engines), 1)
        self.assertEqual(self.worker.cached_snapshot(self.state)["numeric_observation"]["capture"]["sequence"], 300)

    def test_slot_overwrite_after_enqueue_is_visual_drop_not_an_admission(self):
        entered, release, dropped = threading.Event(), threading.Event(), threading.Event()
        pin, drop = self.worker._pin, self.worker._drop
        def blocked(row):
            entered.set()
            release.wait(3)
            return pin(row)
        def observe(reason):
            drop(reason)
            if reason == "slot-overwritten/hash-mismatch":
                dropped.set()
        with patch.object(self.worker, "_pin", side_effect=blocked), patch.object(self.worker, "_drop", side_effect=observe):
            self.submit()
            self.assertTrue(entered.wait(1))
            self.path.write_bytes(b"overwritten")
            release.set()
            self.assertTrue(dropped.wait(2))
        self.assertIsNone(self.worker.cached_snapshot(self.state)["numeric_observation"])
        self.assertIsNone(self.worker.engine)

    def test_pinned_table_and_popup_bytes_are_immutable_and_downstream_never_reopens_live_slots(self):
        self.fixture_lanes()
        from PIL import Image
        buffer = io.BytesIO()
        Image.new("RGB", (16, 24), "green").save(buffer, format="PNG")
        popup_png = buffer.getvalue()
        popup_path = self.path.parent / "live-popup-0-0.png"
        popup_path.write_bytes(popup_png)
        self.row["frame"]["archival"] = True  # A live slot can never be borrowed as an archival original.
        self.row["frame"]["popup_frames"] = [{"popup_index": 0, "parent_frame_index": 1,
            "non_atomic": True, "filename": popup_path.name, "width": 16, "height": 24,
            "sha256": hashlib.sha256(popup_png).hexdigest(), "png_bytes": len(popup_png),
            "source_utc_unix_ms": 9501, "captured_at_monotonic_ms": 41, "bounds": [0, 0, 16, 24]}]
        pinned, release = threading.Event(), threading.Event()
        pin = self.worker._pin
        def blocked(row):
            result = pin(row)
            pinned.set()
            release.wait(4)
            return result
        with patch.object(self.worker, "_pin", side_effect=blocked):
            self.submit()
            self.assertTrue(pinned.wait(2))
            self.path.write_bytes(popup_png)
            popup_path.write_bytes(self.png)
            self.row["frame"]["sha256"] = "f" * 64
            original = Path.open
            def no_reopen(path, *args, **kwargs):
                if path in (self.path, popup_path):
                    raise AssertionError("downstream reopened rotating original")
                return original(path, *args, **kwargs)
            with patch.object(Path, "open", no_reopen):
                release.set()
                self.assertTrue(self.published.wait(3))
                self.assertTrue(self.archived.wait(3))
                frame = self.engines[0].context.latest[0]
                self.assertEqual(frame["_popup_inputs"][0][1], popup_png)
                self.assertFalse(frame["archival"])
                self.assertEqual(self.worker.archive.read(hashlib.sha256(self.png).hexdigest()), self.png,
                                 self.engines[0].archive.snapshot())

    def test_first_inflight_A_B_A_cannot_publish_old_history_or_spawn_retired_engines(self):
        self.fixture_lanes()
        entered, release, retired = threading.Event(), threading.Event(), threading.Event()
        pin_entered, pin_release = threading.Event(), threading.Event()
        def recognition(engine, frame):
            if frame["frame_index"] == 1:
                entered.set()
                release.wait(4)
                engine.last_visual_signature = "retired-signature"
        self.process_hook = recognition
        self.submit()
        self.assertTrue(entered.wait(2))
        self.assertTrue(self.ingressed.wait(2))
        old = self.engines[0]
        pin = self.worker._pin
        def blocked_pin(row):
            if row["frame"]["frame_index"] == 2:
                pin_entered.set()
                pin_release.wait(4)
            return pin(row)
        retire = self.worker._retire
        def observe(reason):
            retire(reason)
            if old.closed.is_set():
                retired.set()
        with patch.object(self.worker, "_retire", side_effect=observe), patch.object(self.worker, "_pin", side_effect=blocked_pin):
            try:
                self.submit(self.receipt(2, readability="unknown"))
                self.assertTrue(pin_entered.wait(2))
                self.submit(self.receipt(3))
                self.assertTrue(retired.wait(2))
                for sequence in range(4, 30):
                    replacement = self.receipt(sequence)
                    replacement["capture_session_id"] = "owner-" + str(sequence)
                    self.submit(replacement)
                self.assertEqual(len(self.engines), 1)
                self.assertTrue(old.numeric.closed.is_set())
                self.assertTrue(old.context.closed.is_set())
                self.assertIsNone(self.worker.cached_snapshot(self.state)["numeric_observation"])
                self.expected = 29
            finally:
                pin_release.set()
                release.set()
            self.assertTrue(self.published.wait(3))
        self.assertEqual(len(self.engines), 2)
        self.assertNotEqual(self.engines[0].archive.directory, self.engines[1].archive.directory)
        self.assertNotEqual(self.engines[1].last_visual_signature, "retired-signature")
        self.assertTrue(all(event["capture"]["capture_session_id"] == "owner-29"
                            for event in self.worker.archive.event_snapshot()))

    def test_slow_context_does_not_retire_or_delay_numeric_lane(self):
        self.fixture_lanes()
        entered, release = threading.Event(), threading.Event()
        factory = self.lanes
        def context_factory(*args, **kwargs):
            engine = factory(*args, **kwargs)
            read = engine.context.reader.read
            def blocked(image, capture, **options):
                if capture["sequence"] == 1:
                    entered.set()
                    release.wait(4)
                return read(image, capture, **options)
            engine.context.reader.read = blocked
            return engine
        with patch("laya_visual.VisualLanes", side_effect=context_factory):
            self.submit()
            self.assertTrue(entered.wait(2))
            self.assertTrue(self.published.wait(2))
            self.expected = 2
            self.published.clear()
            try:
                self.submit(self.receipt(2))
                self.assertTrue(self.published.wait(2), "numeric waited for independent context OCR")
                self.assertEqual(len(self.engines), 1)
                self.assertFalse(self.engines[0].closed.is_set())
                self.assertEqual(self.worker.cached_snapshot(self.state)["numeric_observation"]["capture"]["sequence"], 2)
            finally:
                release.set()

    def test_parallel_cached_snapshots_remain_responsive_while_projection_is_blocked(self):
        self.fixture_lanes()
        self.submit()
        self.assertTrue(self.published.wait(3))
        entered, release = threading.Event(), threading.Event()
        original = self.worker.engine.numeric.snapshot
        def blocked(*args, **kwargs):
            entered.set()
            release.wait(3)
            return original(*args, **kwargs)
        with patch.object(self.worker.engine.numeric, "snapshot", side_effect=blocked):
            # An actual result change triggers projection; polls/clock updates do not.
            self.worker.engine.numeric.value = copy.deepcopy(self.worker.engine.numeric.value)
            self.worker.wake.set()
            self.assertTrue(entered.wait(2))
            try:
                completed = [threading.Event() for _ in range(8)]
                threads = [threading.Thread(target=lambda event=event: (self.worker.cached_snapshot(self.state), event.set()))
                           for event in completed]
                for thread in threads:
                    thread.start()
                self.assertTrue(all(event.wait(.3) for event in completed))
                for thread in threads:
                    thread.join(1)
            finally:
                release.set()

    def test_original_monotonic_lease_and_no_projection_per_http_poll(self):
        self.fixture_lanes()
        self.submit()
        self.assertTrue(self.published.wait(3))
        import laya_visual
        compare, caller = laya_visual._region_checks, threading.get_ident()
        def no_poll_comparison(*args, **kwargs):
            if threading.get_ident() == caller:
                raise AssertionError("poll reprojected")
            return compare(*args, **kwargs)
        with patch("laya_visual._region_checks", side_effect=no_poll_comparison):
            for _ in range(20):
                self.assertEqual(self.worker.cached_snapshot(self.state)["numeric_observation"]["capture"]["captured_at_unix_ms"], 9500)
            self.worker.monotonic = lambda: 51
            value = self.worker.cached_snapshot(self.state)
            self.assertIsNone(value["numeric_observation"])
            self.assertTrue(value["visual_observation"]["current_uncertain"])
            self.worker.monotonic = lambda: 50
            self.assertIsNone(self.worker.cached_snapshot(self.state)["numeric_observation"], "clock rollback restored expired value")

    def test_slow_retired_storage_cannot_publish_into_new_index_or_serve_old_bytes(self):
        self.fixture_lanes()
        entered, release = threading.Event(), threading.Event()
        original_factory = self.lanes
        def factory(*args, **kwargs):
            engine = original_factory(*args, **kwargs)
            record = engine.archive.record
            if len(self.engines) == 1:
                def blocked(*args, **kwargs):
                    entered.set()
                    release.wait(4)
                    return record(*args, **kwargs)
                engine.archive.record = blocked
            return engine
        with patch("laya_visual.VisualLanes", side_effect=factory):
            self.submit()
            self.assertTrue(entered.wait(2))
            old = self.engines[0]
            try:
                self.worker.revoke("owner-ended")
                replacement = self.receipt(2)
                replacement["capture_session_id"] = "new-owner"
                self.expected = 2
                self.published.clear()
                self.submit(replacement)
                self.assertEqual(self.worker.archive.event_snapshot(), [])
                self.assertIsNone(self.worker.archive.read(self.row["frame"]["sha256"]))
                self.assertEqual(len(self.engines), 1)
            finally:
                release.set()
            self.assertTrue(self.published.wait(3))
            self.assertTrue(old.closed.is_set())
            self.assertEqual(len(self.engines), 2)
            self.assertTrue(all(event["capture"]["capture_session_id"] == "new-owner"
                                for event in self.worker.archive.event_snapshot()))

    def test_injected_worker_error_is_bounded_visual_diagnostic(self):
        dropped = threading.Event()
        drop = self.worker._drop
        def observe(reason):
            drop(reason)
            dropped.set()
        with patch.object(self.worker, "_pin", side_effect=RuntimeError("synthetic failure")), \
                patch.object(self.worker, "_drop", side_effect=observe):
            self.submit()
            self.assertTrue(dropped.wait(2))
        self.assertEqual(self.worker.diagnostics()["drops"], {"visual-worker-error": 1})
        self.assertLessEqual(len(self.worker.diagnostics()["stages"]), 100)

    def test_known_masks_survive_pending_pixels_and_transient_retirement_without_blanking_uncovered_fields(self):
        from laya_prep import box_px
        self.row["frame"].update(width=900, height=686)
        self.state["capture"].update(width=900, height=686)
        self.worker.binding = self.worker._metadata(self.row, "session", "source", 1, 10000)
        self.worker.regions = {"regions": {"pot": [0, 0, .5, .5], "seat_1_stack": [.5, .5, 1, 1]}}
        entered, release = threading.Event(), threading.Event()
        pin = self.worker._pin
        def blocked(row):
            entered.set()
            release.wait(3)
            return pin(row)
        def native():
            return {**copy.deepcopy(self.state), "field_statuses": {}, "partial_observation": {
                "pot_size": 100, "pot_size_text": "1.00", "board_slots": [None] * 5,
                "seats": [{"seat": 1, "displayed_stack": 200}], "field_statuses": {}}}
        self.row["frame"]["occluded_regions"] = [list(box_px([0, 0, .5, .5], 900, 686))]
        with patch.object(self.worker, "_pin", side_effect=blocked):
            self.submit()
            self.assertTrue(entered.wait(1))
            try:
                for retired in (False, True):
                    if retired:
                        self.worker.revoke("native-capture-unavailable")
                    snapshot = native()
                    self.worker.mask_snapshot(snapshot, None)
                    self.assertIsNone(snapshot["partial_observation"]["pot_size"])
                    self.assertEqual(snapshot["partial_observation"]["seats"][0]["displayed_stack"], 200)
            finally:
                release.set()

    def test_mask_history_overflow_never_occludes_an_uncovered_native_stack(self):
        self.row["frame"].update(width=900, height=686)
        self.state["capture"].update(width=900, height=686)
        self.worker.binding = self.worker._metadata(self.row, "session", "source", 1, 10000)
        self.worker.regions = {"regions": {"pot": [0, 0, .5, .5], "seat_1_stack": [.5, .5, 1, 1]}}
        entered, release = threading.Event(), threading.Event()
        pin = self.worker._pin
        def blocked(row):
            entered.set()
            release.wait(3)
            return pin(row)
        with patch.object(self.worker, "_pin", side_effect=blocked):
            self.submit()
            self.assertTrue(entered.wait(1))
            try:
                for sequence in range(2, 67):
                    self.submit(self.receipt(sequence, occluded_regions=[[sequence, 100, sequence + 1, 101]]))
                snapshot = {**copy.deepcopy(self.state), "field_statuses": {}, "partial_observation": {
                    "pot_size": 100, "pot_size_text": "1.00", "board_slots": [None] * 5,
                    "seats": [{"seat": 1, "displayed_stack": 200}], "field_statuses": {}}}
                self.worker.mask_snapshot(snapshot, None)
                self.assertIsNone(snapshot["partial_observation"]["pot_size"])
                self.assertEqual(snapshot["partial_observation"]["seats"][0]["displayed_stack"], 200,
                                 "mask-history overflow invented a full-image popup")
                self.assertLessEqual(len(self.worker.mask_regions), 64)
            finally:
                release.set()

    def test_projection_pairs_detached_numeric_dto_with_its_own_original_deadline(self):
        self.fixture_lanes()
        self.submit()
        self.assertTrue(self.published.wait(3))
        self.assertTrue(self.archived.wait(3))
        engine = self.engines[0]
        read_entered, release_read, copied, release_copy, committed, release_commit = (threading.Event() for _ in range(6))
        numeric_published = threading.Event()
        read, snapshot, project = engine.numeric.reader.read, engine.numeric.snapshot, self.worker._project
        monotonic = engine.numeric.monotonic
        def publication_clock():
            if (engine.numeric.value or {}).get("capture", {}).get("sequence") == 2:
                numeric_published.set()
            return monotonic()
        def blocked_read(image, capture, **kwargs):
            if capture["sequence"] == 2:
                read_entered.set()
                release_read.wait(3)
            return read(image, capture, **kwargs)
        def detached(*args, **kwargs):
            value = snapshot(*args, **kwargs)
            if value and value["capture"]["sequence"] == 1 and self.worker.validated == 2:
                copied.set()
                release_copy.wait(3)
            return value
        def observe(*args):
            result = project(*args)
            if self.worker.validated == 2 and (self.worker.cache.get("numeric_observation") or {}).get("capture", {}).get("sequence") == 1:
                committed.set()
                release_commit.wait(3)
            return result
        self.expected = 2
        self.archived.clear()
        replacement = self.receipt(2)
        replacement["frame"].update(source_utc_unix_ms=9800, captured_at_monotonic_ms=340)
        with patch.object(engine.numeric.reader, "read", side_effect=blocked_read), \
                patch.object(engine.numeric, "snapshot", side_effect=detached), \
                patch.object(engine.numeric, "monotonic", side_effect=publication_clock), \
                patch.object(self.worker, "_project", side_effect=observe):
            self.submit(replacement)
            try:
                self.assertTrue(read_entered.wait(2))
                self.assertTrue(copied.wait(2))
                release_read.set()
                self.assertTrue(numeric_published.wait(2))
                with engine.numeric.lock:
                    self.assertGreater(engine.numeric.deadline, 51.1)
                release_copy.set()
                self.assertTrue(committed.wait(2))
                self.worker.monotonic = lambda: 51.1
                self.assertIsNone(self.worker.cached_snapshot(self.state)["numeric_observation"],
                                  "old capture borrowed newer result's later monotonic deadline")
            finally:
                release_read.set()
                release_copy.set()
                release_commit.set()

    def test_blocked_archive_read_is_a_retirement_user_and_has_final_token_fence(self):
        self.fixture_lanes()
        self.submit()
        self.assertTrue(self.published.wait(3))
        engine = self.engines[0]
        entered, release = threading.Event(), threading.Event()
        outputs = []
        def blocked(_):
            entered.set()
            release.wait(4)
            return self.png
        with patch.object(engine.archive, "read", side_effect=blocked):
            thread = threading.Thread(target=lambda: outputs.append(self.worker.archive.read(self.row["frame"]["sha256"])))
            thread.start()
            self.assertTrue(entered.wait(2))
            try:
                self.worker.revoke("owner-ended")
                self.submit(self.receipt(2))
                self.assertEqual(len(self.engines), 1)
                self.worker.stop()
                self.assertFalse(self.worker.shutdown_complete.is_set())
                self.assertEqual(engine.archive_readers, 1)
            finally:
                release.set()
                thread.join(3)
        self.assertEqual(outputs, [None])
        self.assertTrue(self.worker.shutdown_complete.wait(3))

    def test_reader_disposal_is_off_publication_lock_and_blocks_replacement_until_closed(self):
        self.fixture_lanes()
        self.submit()
        self.assertTrue(self.published.wait(3))
        entered, release = threading.Event(), threading.Event()
        def close():
            self.assertTrue(self.worker.lock.acquire(blocking=False))
            self.worker.lock.release()
            entered.set()
            release.wait(4)
        self.engines[0].context.reader.close = close
        self.worker.revoke("owner-ended")
        self.expected = 2
        self.published.clear()
        self.submit(self.receipt(2))
        self.assertTrue(entered.wait(2))
        try:
            self.worker.cached_snapshot(self.state)
            self.assertEqual(len(self.engines), 1)
            self.assertIsNotNone(self.worker.retiring)
        finally:
            release.set()
        self.assertTrue(self.published.wait(3))
        self.assertEqual(len(self.engines), 2)
        self.assertGreater(self.worker.diagnostics()["retired_archive_usage"]["frames"], 0)
        self.assertLess(self.engines[1].archive.max_frames, 512)

    def test_archive_budget_exhaustion_survives_namespace_replacement_without_stopping_values(self):
        self.fixture_lanes()
        self.worker.used_budget["frames"] = 512
        self.submit()
        self.assertTrue(self.published.wait(3))
        for engine in self.engines:
            self.assertEqual(engine.archive.max_frames, 0)
            self.assertFalse(engine.archive.complete)
        self.worker.revoke("owner-ended")
        self.expected = 2
        self.published.clear()
        self.submit(self.receipt(2))
        self.assertTrue(self.published.wait(3))
        self.assertEqual(self.engines[1].archive.max_frames, 0)
        self.assertEqual(self.worker.cached_snapshot(self.state)["numeric_observation"]["pot"]["value"], 100)

    def test_exhausted_all_archive_log_budgets_do_not_create_empty_namespace_files(self):
        self.fixture_lanes()
        self.worker.used_budget.update(frames=512, bytes=256 * 1024 * 1024,
            log_bytes=16 * 1024 * 1024, context_log_bytes=8 * 1024 * 1024, visual_log_bytes=8 * 1024 * 1024)
        self.row["frame"].update(filename="frame-0000000001.png", archival=True)
        (self.path.parent / self.row["frame"]["filename"]).write_bytes(self.png)
        self.submit()
        self.assertTrue(self.published.wait(3))
        self.worker.stop()
        self.assertTrue(self.worker.shutdown_complete.wait(3))
        self.assertFalse(self.engines[0].archive.directory.exists())

    def test_partial_storage_failure_latches_survive_namespace_replacement_without_blocking_values(self):
        self.fixture_lanes()
        self.submit()
        self.assertTrue(self.published.wait(3))
        self.assertTrue(self.archived.wait(3))
        old = self.engines[0]
        old.archive.complete, old.archive.reason = False, "synthetic-partial-write"
        old.archive._cache_status()
        old.context.log_complete = old.log_complete = False
        self.worker.revoke("native-capture-unavailable")
        self.expected = 2
        self.published.clear()
        self.submit(self.receipt(2))
        self.assertTrue(self.published.wait(3))
        current = self.engines[1]
        self.assertFalse(current.archive.complete, "new namespace rearmed a failed service archive")
        self.assertFalse(current.context.log_complete)
        self.assertFalse(current.log_complete)
        self.assertEqual(self.worker.cached_snapshot(self.state)["numeric_observation"]["pot"]["value"], 100)

    def test_delayed_old_cache_cannot_overwrite_new_ticket_expiry_or_leak_old_diagnostics(self):
        binding = self.worker._metadata(self.row, "session", "source", 1, 10000)
        def cached(sequence):
            return {"numeric_observation": {"capture": {"sequence": sequence, "captured_at_ms": 40 + sequence,
                "captured_at_unix_ms": 9500 + sequence, "sha256": str(sequence) * 64}},
                "numeric_diagnostics": {"last_timing": {"capture": {"sequence": sequence}}},
                "context_diagnostics": {"log_path": "old-diagnostic"}}
        self.worker.binding, self.worker.token = binding, threading.Event()
        self.worker.serial = self.worker.validated = 1
        self.worker.cache = old_cache = cached(1)
        self.worker.leases = {"numeric_observation": 51}
        entered, release = threading.Event(), threading.Event()
        results = []
        deepcopy = copy.deepcopy
        def blocked(value, *args, **kwargs):
            if value is old_cache and threading.current_thread().name == "old-snapshot":
                entered.set()
                release.wait(3)
            return deepcopy(value, *args, **kwargs)
        with patch("laya_visual.copy.deepcopy", side_effect=blocked):
            thread = threading.Thread(name="old-snapshot", target=lambda: results.append(self.worker.cached_snapshot(self.state)))
            thread.start()
            self.assertTrue(entered.wait(2))
            try:
                with self.worker.lock:
                    self.worker.serial = self.worker.validated = 2
                    self.worker.cache = cached(2)
                self.worker.monotonic = lambda: 51
                self.assertIsNone(self.worker.cached_snapshot(self.state)["numeric_observation"])
            finally:
                release.set()
                thread.join(3)
        self.worker.monotonic = lambda: 50
        self.assertIsNone(self.worker.cached_snapshot(self.state)["numeric_observation"])
        self.assertNotIn("numeric_diagnostics", results[0])
        self.assertNotIn("context_diagnostics", results[0])
        self.assertEqual(results[0]["visual_diagnostics"]["namespaces"], [])

    def test_final_feed_gate_rechecks_revision_after_cached_dto_was_returned(self):
        self.fixture_lanes()
        self.submit()
        self.assertTrue(self.published.wait(3))
        projection = self.worker.cached_snapshot(self.state)
        self.assertIsNotNone(projection["numeric_observation"])
        entered, release = threading.Event(), threading.Event()
        pin = self.worker._pin
        def blocked(row):
            entered.set()
            release.wait(3)
            return pin(row)
        with patch.object(self.worker, "_pin", side_effect=blocked):
            self.submit(self.receipt(2))
            self.assertTrue(entered.wait(2))
            try:
                snapshot = {**copy.deepcopy(self.state), **projection}
                self.worker.fence_snapshot(snapshot, projection)
                self.assertIsNone(snapshot["numeric_observation"])
                self.assertIsNone(snapshot["table_context"])
                self.assertTrue(snapshot["visual_observation"]["current_uncertain"])
                self.assertNotIn("context_diagnostics", snapshot)
            finally:
                release.set()

    def test_final_feed_gate_drops_last_seen_after_native_process_binding_replacement(self):
        self.fixture_lanes()
        self.submit()
        self.assertTrue(self.published.wait(3))
        projection = self.worker.cached_snapshot(self.state)
        old_binding = projection.binding
        replacement = self.receipt(2, source_process_created_at_100ns=10)
        self.submit(replacement)
        self.assertNotEqual(self.worker.binding, old_binding)
        snapshot = {**copy.deepcopy(self.state), **projection}
        self.worker.fence_snapshot(snapshot, projection)
        self.assertIsNone(snapshot["visual_observation"], "old binding's board last_seen leaked into replacement")

    def test_final_feed_gate_rechecks_original_visual_lease_after_dto_copy(self):
        self.fixture_lanes()
        self.submit()
        self.assertTrue(self.published.wait(3))
        projection = self.worker.cached_snapshot(self.state)
        self.worker.monotonic = lambda: 51
        snapshot = {**copy.deepcopy(self.state), **projection}
        self.worker.fence_snapshot(snapshot, projection)
        self.assertIsNone(snapshot["numeric_observation"])
        self.assertTrue(snapshot["visual_observation"]["current_uncertain"])
        self.worker.monotonic = lambda: 50
        self.assertIsNone(self.worker.cached_snapshot(self.state)["numeric_observation"])

    def test_same_ticket_cache_replacement_cannot_bypass_a_newer_expiry_latch(self):
        self.worker.binding = self.worker._metadata(self.row, "session", "source", 1, 10000)
        self.worker.token = threading.Event()
        self.worker.serial = self.worker.validated = 1
        self.worker.cache = {"numeric_observation": {"capture": {"sequence": 1, "captured_at_ms": 40,
            "captured_at_unix_ms": 9500, "sha256": "d" * 64}}}
        self.worker.leases = {"numeric_observation": 51}
        old_projection = self.worker.cached_snapshot(self.state)
        with self.worker.lock:
            self.worker.cache = copy.deepcopy(self.worker.cache)  # Another lane completed, same numeric ticket.
        self.worker.monotonic = lambda: 51
        self.assertIsNone(self.worker.cached_snapshot(self.state)["numeric_observation"])
        self.worker.monotonic = lambda: 50
        snapshot = {**copy.deepcopy(self.state), **old_projection}
        self.worker.fence_snapshot(snapshot, old_projection)
        self.assertIsNone(snapshot["numeric_observation"], "old cache identity bypassed newer same-ticket expiry")
        with self.worker.lock:
            self.worker.expired_captures = {}
        self.worker.monotonic = lambda: 51
        snapshot = {**copy.deepcopy(self.state), **old_projection}
        self.worker.fence_snapshot(snapshot, old_projection)
        self.worker.monotonic = lambda: 50
        self.assertIsNone(self.worker.cached_snapshot(self.state)["numeric_observation"],
                          "expiry observed through old copy did not tombstone the still-current original")

    def test_namespace_history_is_bounded_scoped_and_frozen_before_retired_late_io(self):
        self.fixture_lanes()
        self.submit()
        self.assertTrue(self.published.wait(3))
        first_id = self.engines[0].archive.directory.name
        for sequence in range(2, 36):
            self.worker.revoke("native-capture-unavailable")
            self.expected = sequence
            self.published.clear()
            self.submit(self.receipt(sequence))
            self.assertTrue(self.published.wait(3))
        diagnostic = self.worker.diagnostics()
        self.assertEqual(len(diagnostic["namespaces"]), 33)
        self.assertEqual(diagnostic["namespace_overflow_count"], 2)
        self.assertNotIn(first_id, [item["namespace_id"] for item in diagnostic["namespaces"]])
        for item in diagnostic["namespaces"][:-1]:
            self.assertTrue(item["frozen_prefix"])
            self.assertTrue(item["workers_drained"])
            self.assertFalse(item["admitted_evidence"])
            self.assertEqual(item["scope"]["capture_session_id"], "owner")
        replacement = self.receipt(36)
        replacement["capture_session_id"] = "new-owner"
        self.expected = 36
        self.published.clear()
        self.submit(replacement)
        self.assertTrue(self.published.wait(3))
        diagnostic = self.worker.diagnostics()
        self.assertEqual(len(diagnostic["namespaces"]), 1)
        self.assertEqual(diagnostic["namespaces"][0]["scope"]["capture_session_id"], "new-owner")


class VisualTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.worker = VisualLanes(self.root, "instance", wall=lambda: 10)
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

    def test_post_gate_supersession_cannot_mutate_real_process_timeline_or_board_history(self):
        path, frame = self.evidence()
        png = path.read_bytes()
        self.board_reader()
        scope = ("session", "source", 1)
        self.worker.scope, self.worker.first_watermark = scope, 1
        entered, release = threading.Event(), threading.Event()
        errors = []
        def observe(*args, **kwargs):
            entered.set()
            release.wait(3)
            return {"gaps": []}
        self.worker.timeline.observe.side_effect = observe
        def process():
            try:
                self.worker.process({**frame, "_lane_managed": True}, path, scope, png)
            except ValueError as error:
                errors.append(str(error))
        thread = threading.Thread(target=process)
        thread.start()
        self.assertTrue(entered.wait(2))
        try:
            fake = Mock(is_alive=Mock(return_value=False))
            with patch("laya_visual.threading.Thread", return_value=fake):
                self.worker.submit_pinned(self.next_frame(frame, 2), path, scope, png)
                self.worker.submit_pinned(self.next_frame(frame, 3), path, scope, png)
        finally:
            release.set()
            thread.join(3)
        self.assertEqual(errors, ["superseded-or-expired-visual-work"])
        self.assertIsNone(self.worker.processed_ticket)
        self.assertIsNone(self.worker.board_scope)
        self.assertTrue(all(value is None for value in self.worker.board_last_seen))
        self.assertEqual(self.worker.timeline.observe.call_count, 0)

    def test_managed_process_history_commits_with_value_not_before_outer_publication(self):
        path, frame = self.evidence()
        frame["archival"] = False
        png = path.read_bytes()
        self.board_reader()
        scope = ("session", "source", 1)
        computed, release, published = threading.Event(), threading.Event(), threading.Event()
        process = self.worker.process
        def paused(frame, *args):
            value = process(frame, *args)
            if frame["frame_index"] == 1:
                computed.set()
                release.wait(3)
            return value
        def archive(png, capture, *args, **kwargs):
            if capture["sequence"] == 3:
                published.set()
            return {"event_id": capture["sequence"]}
        with patch.object(self.worker, "process", side_effect=paused), \
                patch.object(self.worker.numeric, "submit"), patch.object(self.worker.context, "submit"), \
                patch.object(self.worker.archive, "record", side_effect=archive):
            self.worker.submit_pinned(frame, path, scope, png)
            self.assertTrue(computed.wait(2))
            try:
                self.assertIsNone(self.worker.value)
                self.assertIsNone(self.worker.processed_ticket)
                self.assertIsNone(self.worker.board_scope)
                self.assertEqual(self.worker.timeline.observe.call_count, 0)
                self.worker.submit_pinned(self.next_frame(frame, 2), path, scope, png)
                self.worker.submit_pinned(self.next_frame(frame, 3), path, scope, png)
            finally:
                release.set()
            self.assertTrue(published.wait(3))
        self.worker.stop()
        self.assertEqual(self.worker.value["sequence"], 3)
        self.assertEqual(self.worker.processed_ticket[0], 3)
        self.assertEqual(self.worker.timeline.observe.call_count, 1)

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
