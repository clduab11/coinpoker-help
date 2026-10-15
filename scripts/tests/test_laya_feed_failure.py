"""Finite feed regression tests; no live service, capture, OCR or model work."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.tests.test_laya_dashboard import dashboard


INSTANCE = "1a8007a16a2741c592dae7c954db9cf2"
SESSION = "fe530937b2d741d3bb8819bc36373f00"
IDENTITY = {"exe_name": "CoinPoker.exe", "process_id": 22484, "hwnd": "0x14a055a"}
LOAD_INSTANCE = "cb5790573654499080a6c5a81ffaaeef"
LOAD_SESSION = "874ab7187bba4bf490d7dc2eb5304f64"
LOAD_OBSERVED = 1792006801954


def failed_boundary_frame():
    """Exact typed row 1499, with only the checkout-specific directory normalized."""
    return {"activity_state": "verifying", "capture_directory": str(
        dashboard.ROOT / ".local/captures/utc-1792003095-224479100-practice"),
        "event": "visual_frame", "experimental_bet_action": False,
        "frame": {"archival": True, "captured_at_monotonic_ms": 283530,
            "filename": "frame-0000000502.png", "frame_index": 502, "height": 705,
            "occluded_regions": [], "owned_popups": [], "pixel_source": "visible_desktop_pixels",
            "png_bytes": 760852, "popup_frames": [], "readability": "full",
            "sha256": "24635de7b89c18f73ba3d7df8b9502082d62b1abea74a4388ed6416bd285cb57",
            "source_id": 3235148086084101343, "source_process_created_at_100ns": 134364766616945609,
            "source_utc_unix_ms": 1792003378753, "width": 927},
        "identity": dict(IDENTITY), "mode": "inference-enabled", "schema_version": 2,
        "service_instance_id": INSTANCE, "source_policy": "automatic-sustained"}


class FeedFailureTests(unittest.TestCase):
    def setUp(self):
        self.utc = 1792003378840
        self.state = dashboard.DashboardState("synthetic", wall=lambda: self.utc / 1000,
                                              monotonic=lambda: self.utc / 1000)
        self.state.set_model("ready")
        self.state.begin_stream()
        from laya_visual import VisualWorker
        self.visual_type = VisualWorker
        visual = patch("laya_visual.VisualWorker", return_value=Mock())
        self.visual = visual.start().return_value
        self.addCleanup(visual.stop)
        temporary = tempfile.TemporaryDirectory(prefix="feed-failure-", dir=dashboard.ROOT / ".local")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.feed = dashboard.ManualSessionFeed(self.state, INSTANCE, root=self.root)
        self.feed.session_id, self.feed.stream_id = SESSION, self.state.session_id
        self.feed.source_policy = "automatic-sustained"
        self.feed.identity = (IDENTITY["exe_name"].lower(), IDENTITY["process_id"], IDENTITY["hwnd"])
        self.feed.path = self.root / ".local/laya/manual-capture" / SESSION
        self.feed.path.mkdir(parents=True)
        self.current = {**dashboard.manual_capture.default_snapshot(), "session_id": SESSION,
            "status": "capturing", "mode": "inference-enabled", "inference_enabled": True,
            "receipt_version": 2, "source_policy": "automatic-sustained", "activity_state": "verifying",
            "updated_at_unix_ms": self.utc, "elapsed_ms": 283617, "max_duration_ms": None,
            "max_frames": None, "remaining_ms": None,
            "evidence": {"status": "active", "stop_reason": None, "max_duration_ms": 600_000,
                "max_frames": 1200, "max_bytes": 1024 * 1024 * 1024,
                "recorded_frames": 502, "recorded_bytes": 385642990, "elapsed_ms": 283617}}
        self.feed.evidence_budget = (600_000, 1200, 1024 * 1024 * 1024)
        self.feed.evidence_last = copy.deepcopy(self.current["evidence"])
        self.feed.receipt_deadline = self.utc / 1000 + 3
        self.visual.context.snapshot.return_value = None
        self.visual.snapshot.return_value = None
        self.visual.numeric.snapshot.return_value = None
        self.visual.archive.directory = self.root / ".local/laya/events/offline"
        for name, options in (("public_snapshot", {"side_effect": lambda **_: copy.deepcopy(self.current)}),
                              ("fail_session", {"side_effect": self.fail_session}),
                              ("stop_session", {})):
            guard = patch.object(dashboard.manual_capture, name, **options)
            mock = guard.start()
            self.addCleanup(guard.stop)
            if name == "fail_session":
                self.fail_capture = mock

    def fail_session(self, sid, reason, *, root):
        self.assertEqual((sid, root), (self.feed.session_id, self.root))
        self.current.update(status="failed", stop_reason=reason, activity_state="idle")

    def receipt_load_gap(self):
        """Failed consumer watermark plus a genuinely newer archived native receipt.

        The native frame-19 sample is real; its availability in the public owner
        snapshot at the historical failure was not recorded and is not asserted.
        """
        self.feed.instance_id, self.feed.session_id = LOAD_INSTANCE, LOAD_SESSION
        self.feed.path = self.root / ".local/laya/manual-capture" / LOAD_SESSION
        self.feed.path.mkdir(parents=True, exist_ok=True)
        self.feed.receipt_updated, self.feed.receipt_elapsed = 1792006798687, 9858
        self.feed.receipt_deadline = self.feed.receipt_updated / 1000 + 3
        self.feed.evidence_last = {**self.current["evidence"], "elapsed_ms": 9298,
                                  "recorded_frames": 14, "recorded_bytes": 10609906}
        self.current.update(session_id=LOAD_SESSION, updated_at_unix_ms=1792006801456, elapsed_ms=12541,
                            recorded_frames=19, recorded_bytes=14369812)
        self.current["evidence"].update(elapsed_ms=12541, recorded_frames=19, recorded_bytes=14369812)
        self.utc = LOAD_OBSERVED - 991  # Exact ledger arrival of health 16.
        self.feed._ingest_row(self.health(generation=3, frame_count=16, recorded_frames=16,
            recorded_bytes=12114429, captured_at_ms=10393, captured_at_unix_ms=1792006799309,
            emitted_at_unix_ms=1792006799491, service_instance_id=LOAD_INSTANCE), self.current)
        self.utc = LOAD_OBSERVED

    def test_load_gap_adopts_only_new_original_receipt_before_cached_expiry(self):
        self.receipt_load_gap()
        old_deadline = self.feed.receipt_deadline
        self.assertGreater(self.state.monotonic(), old_deadline)
        self.assertTrue(self.feed._valid(self.current), self.feed.validation_reason)
        self.assertEqual((self.feed.receipt_updated, self.feed.receipt_elapsed), (1792006801456, 12541))
        self.assertAlmostEqual(self.feed.receipt_deadline - self.state.monotonic(), 2.502, places=6)
        self.assertAlmostEqual(self.feed.receipt_deadline, 1792006801456 / 1000 + 3, places=6)
        self.assertEqual(self.state.capture["frames"], 16)
        self.assertFalse(self.state.capture["fresh_capture"], "receipt progress does not freshen source pixels")
        self.assertIsNone(self.state.partial_observation)

    def test_snapshot_and_poll_do_not_retire_new_owner_progress_after_consumer_gap(self):
        self.receipt_load_gap()
        stream = self.feed.stream_id
        self.feed.snapshot()
        self.feed.poll()
        self.assertEqual(self.feed.stream_id, stream)
        self.assertIsNone(self.feed.failure_reason)
        self.fail_capture.assert_not_called()
        self.visual.submit.assert_not_called()

    def test_expired_same_sample_and_nonadvancing_clocks_cannot_renew(self):
        self.receipt_load_gap()
        old = self.feed.receipt_deadline, self.feed.receipt_updated, self.feed.receipt_elapsed
        for updated, elapsed in ((1792006798687, 9858),
                                 (1792006801456, 9858),
                                 (1792006798687, 12541)):
            with self.subTest(updated=updated, elapsed=elapsed):
                candidate = {**self.current, "updated_at_unix_ms": updated, "elapsed_ms": elapsed}
                self.assertFalse(self.feed._valid(candidate))
                self.assertEqual(self.feed.validation_reason, "owner-receipt-expired")
                self.assertEqual((self.feed.receipt_deadline, self.feed.receipt_updated, self.feed.receipt_elapsed), old)

    def test_timestamp_only_rewrites_within_lease_do_not_extend_it(self):
        self.receipt_load_gap()
        old = self.feed.receipt_deadline
        self.utc = self.feed.receipt_updated + 2000
        self.current.update(updated_at_unix_ms=self.utc, elapsed_ms=self.feed.receipt_elapsed)
        self.assertTrue(self.feed._valid(self.current))
        self.assertLessEqual(self.feed.receipt_deadline, old)
        self.utc += 1001
        self.current["updated_at_unix_ms"] = self.utc
        self.assertFalse(self.feed._valid(self.current))
        self.assertEqual(self.feed.validation_reason, "owner-receipt-expired")

    def test_original_new_sample_already_expired_or_future_is_rejected(self):
        self.receipt_load_gap()
        old = self.feed.receipt_deadline
        for updated, reason in ((LOAD_OBSERVED - 3001, "owner-receipt-expired"),
                                (LOAD_OBSERVED - 3000, "owner-receipt-expired"),
                                (LOAD_OBSERVED + 1, "owner-receipt-future")):
            with self.subTest(updated=updated):
                self.assertFalse(self.feed._valid({**self.current, "updated_at_unix_ms": updated}))
                self.assertEqual(self.feed.validation_reason, reason)
                self.assertEqual(self.feed.receipt_deadline, old)

    def test_new_receipt_keeps_only_its_remaining_original_lease(self):
        self.receipt_load_gap()
        self.current["updated_at_unix_ms"] = LOAD_OBSERVED - 2999
        self.assertTrue(self.feed._valid(self.current))
        self.assertAlmostEqual(self.feed.receipt_deadline - self.state.monotonic(), .001, places=6)
        self.utc += 2
        self.assertFalse(self.feed._valid(self.current))

    def test_new_receipt_cannot_bypass_regressions_or_owner_budget_bindings(self):
        self.receipt_load_gap()
        old = self.feed.receipt_deadline, self.feed.receipt_updated, self.feed.receipt_elapsed
        cases = ({"updated_at_unix_ms": 1792006798686}, {"elapsed_ms": 9857},
                 {"session_id": "b" * 32}, {"source_policy": "automatic-bounded"},
                 {"mode": "capture-only", "inference_enabled": False},
                 {"status": "stopped", "stop_reason": "operator-stop"}, {"activity_state": "idle"},
                 {"evidence": {**self.current["evidence"], "max_frames": 1199}},
                 {"evidence": {**self.current["evidence"], "recorded_frames": 13}},
                 {"evidence": {**self.current["evidence"], "recorded_bytes": 10609905}},
                 {"evidence": {**self.current["evidence"], "elapsed_ms": 9297}})
        for extra in cases:
            with self.subTest(extra=extra):
                self.assertFalse(self.feed._valid({**self.current, **extra}))
                self.assertEqual((self.feed.receipt_deadline, self.feed.receipt_updated, self.feed.receipt_elapsed), old)
        with patch.dict(self.state.model, model_state="unavailable"):
            self.assertFalse(self.feed._valid(self.current))
        self.assertEqual((self.feed.receipt_deadline, self.feed.receipt_updated, self.feed.receipt_elapsed), old)

    def test_fresh_receipt_with_altered_source_still_tombstones_stream(self):
        self.receipt_load_gap()
        wrong = self.health(service_instance_id=LOAD_INSTANCE, identity={**IDENTITY, "hwnd": "0x123"})
        self.assertFalse(self.feed.ingest_live(LOAD_SESSION, wrong))
        self.assertEqual(self.feed.failure_reason["message"], "manual-feed-source-mismatch")
        self.assertIsNone(self.feed.stream_id)

    def test_actual_expiry_tombstone_cannot_be_revived_by_later_new_sample(self):
        self.receipt_load_gap()
        fresh = copy.deepcopy(self.current)
        self.current.update(updated_at_unix_ms=self.feed.receipt_updated, elapsed_ms=self.feed.receipt_elapsed)
        self.feed.snapshot()
        self.assertIsNone(self.feed.stream_id)
        self.current = fresh
        self.assertFalse(self.feed.authorizes(LOAD_SESSION, LOAD_INSTANCE))
        self.assertIsNone(self.feed.stream_id)
        self.assertTrue(self.fail_capture.called)

    def test_frozen_wall_clock_and_elapsed_progress_do_not_rearm_same_utc(self):
        self.receipt_load_gap()
        self.current["updated_at_unix_ms"] = self.feed.receipt_updated
        with patch.object(self.state, "wall", return_value=self.feed.receipt_updated / 1000):
            self.assertFalse(self.feed._valid(self.current))
        self.assertEqual(self.feed.validation_reason, "owner-receipt-expired")

    def test_malformed_candidate_clocks_cannot_renew_original_lease(self):
        self.receipt_load_gap()
        old = self.feed.receipt_deadline
        for key in ("updated_at_unix_ms", "elapsed_ms"):
            for value in (None, True, "12541", 12541.0, -1, 2**53):
                with self.subTest(key=key, value=value):
                    self.assertFalse(self.feed._valid({**self.current, key: value}))
                    self.assertEqual(self.feed.validation_reason, "owner-receipt-time-invalid")
                    self.assertEqual(self.feed.receipt_deadline, old)

    def test_candidate_expiring_during_validation_is_not_adopted(self):
        self.receipt_load_gap()
        old = self.feed.receipt_deadline, self.feed.receipt_updated, self.feed.receipt_elapsed
        with patch.object(self.state, "monotonic", side_effect=[LOAD_OBSERVED / 1000,
                                                               self.current["updated_at_unix_ms"] / 1000 + 3]):
            self.assertFalse(self.feed._valid(self.current))
        self.assertEqual(self.feed.validation_reason, "owner-receipt-expired")
        self.assertEqual((self.feed.receipt_deadline, self.feed.receipt_updated, self.feed.receipt_elapsed), old)

    def test_receipt_progress_does_not_extend_independent_source_heartbeat(self):
        self.receipt_load_gap()
        self.assertTrue(self.feed._valid(self.current))
        self.utc += 1510  # Health 16 was ingested 2501 ms ago; owner sample is only 2008 ms old.
        snapshot = self.feed.snapshot()
        self.assertIsNotNone(self.feed.stream_id)
        self.assertEqual(snapshot["capture"]["state"], "unavailable")
        self.assertFalse(snapshot["capture"]["fresh_capture"])
        self.assertIsNone(snapshot["capture"]["epoch"])
        self.assertIsNone(snapshot["partial_observation"])
        self.fail_capture.assert_not_called()

    def test_failure_diagnostic_distinguishes_candidate_from_cached_receipt(self):
        self.receipt_load_gap()
        self.current["updated_at_unix_ms"] = LOAD_OBSERVED - 3001
        snapshot = self.feed.snapshot()
        failure = snapshot["capture_session"]["failure_reason"]
        self.assertEqual((failure["message"], failure["type"]), ("owner-receipt-expired", None))
        self.assertEqual((failure["receipt_updated_at_unix_ms"], failure["receipt_elapsed_ms"]),
                         (1792006798687, 9858))
        self.assertEqual((failure["candidate_updated_at_unix_ms"], failure["candidate_elapsed_ms"]),
                         (LOAD_OBSERVED - 3001, 12541))
        self.assertLess(len(json.dumps(failure).encode()), 4096)

    @unittest.skipUnless(os.environ.get("LAYA_FEED_PRIVATE_REPLAY_PROOF") == "1",
                         "explicit finite saved-feed metadata replay")
    def test_archived_new_failure_and_native_progress_match_load_gap_fixture(self):
        directory = dashboard.ROOT / ".local/laya/manual-capture" / LOAD_SESSION
        failure = dashboard.manual_capture.read_json(directory / "feed-failure.json", maximum=4096)
        self.assertEqual((failure["message"], failure["stage"], failure["type"]),
                         ("owner-receipt-expired", "receipt", None))
        self.assertEqual((failure["observed_at_unix_ms"], failure["receipt_updated_at_unix_ms"],
                          failure["receipt_elapsed_ms"], failure["last_health"]["frames"]),
                         (LOAD_OBSERVED, 1792006798687, 9858, 16))
        native = None
        with (directory / "stdout.jsonl").open("rb") as stream:
            for index in range(1000):
                raw = stream.readline(dashboard.MAX_RECORD + 1)
                if not raw:
                    break
                self.assertLessEqual(len(raw), dashboard.MAX_RECORD)
                self.assertTrue(raw.endswith(b"\n"))
                row = json.loads(raw, parse_constant=dashboard._reject_constant)
                if row.get("event") == "manual_capture" and row.get("stop_reason") is None:
                    native = row
            else:
                self.fail("saved new-session row limit")
        self.assertEqual((native["updated_at_unix_ms"], native["elapsed_ms"], native["recording"]["recorded_frames"],
                          native["recording"]["recorded_bytes"]), (1792006801456, 12541, 19, 14369812))
        self.receipt_load_gap()
        self.assertTrue(self.feed._valid(self.current))
        print("saved load-gap: cached_age_ms=3267, new_native_candidate_age_ms=498, frames=19; published candidate at failure unknown")

    def health(self, **extra):
        return {"schema_version": 2, "event": "capture_health", "generation": 136, "epoch": 1,
            "identity": dict(IDENTITY), "fresh_capture": True, "frame_count": 501,
            "emitted_at_unix_ms": 1792003378323, "captured_at_unix_ms": 1792003378220,
            "captured_at_ms": 282997, "frame_width": 927, "frame_height": 705,
            "recorded_bytes": 384881594, "recorded_frames": 501, "recording_complete": True,
            "recording_enabled": True, "recording_status": "active", "service_instance_id": INSTANCE,
            "source_policy": "automatic-sustained", "activity_state": "verifying", **extra}

    def test_exact_502_row_and_prior_health_remain_accepted(self):
        self.assertTrue(self.feed.ingest_live(SESSION, self.health()))
        self.assertTrue(self.feed.ingest_live(SESSION, failed_boundary_frame()))
        submitted, stream, source, epoch = self.visual.submit.call_args.args
        self.assertEqual(submitted["frame"], failed_boundary_frame()["frame"])
        self.assertEqual((stream, source, epoch), (self.state.session_id, self.state.target, 1))
        self.assertEqual(submitted["capture_session_id"], SESSION)
        self.assertIsNone(self.feed.failure_reason)
        self.fail_capture.assert_not_called()

    def test_injected_submit_exception_records_exact_cause_and_original_metadata(self):
        self.assertTrue(self.feed.ingest_live(SESSION, self.health()))
        self.visual.submit.side_effect = TypeError("int() argument must be a string, not 'dict'")
        self.assertFalse(self.feed.ingest_live(SESSION, failed_boundary_frame()))
        failure = self.feed.snapshot()["capture_session"]["failure_reason"]
        self.assertEqual((failure["type"], failure["message"], failure["stage"]),
                         ("TypeError", "int() argument must be a string, not 'dict'", "live"))
        self.assertEqual((failure["frame_index"], failure["width"], failure["height"]), (502, 927, 705))
        self.assertEqual((failure["captured_at_ms"], failure["captured_at_unix_ms"]),
                         (283530, 1792003378753))
        self.assertEqual(failure["last_health"]["frames"], 501)
        self.assertEqual((failure["service_instance_id"], failure["capture_session_id"], failure["source_id"]),
                         (INSTANCE, SESSION, self.state.target))
        self.assertIsNone(self.feed.stream_id)
        self.assertTrue(self.feed.failed)
        saved = self.feed.path / "feed-failure.json"
        self.assertLess(saved.stat().st_size, 4096)
        self.assertEqual(json.loads(saved.read_bytes()), failure)
        self.assertFalse(self.feed.ingest_live(SESSION, self.health(frame_count=503)))
        self.assertEqual(self.feed.failure_reason, failure)

    def test_unknown_and_mixed_feed_records_still_stop(self):
        for row in ({"schema_version": 2, "event": "unknown_event"}, [],
                    {"schema_version": 2.0, "event": "capture_health"},
                    {"event": "manual_capture", "version": True, "mode": "inference-enabled"},
                    {"schema_version": 2, "event": []}):
            with self.subTest(row=row):
                self.current.update(status="capturing", stop_reason=None, activity_state="verifying")
                self.feed.stream_id, self.feed.failed, self.feed.failure_reason = self.state.session_id, False, None
                self.assertFalse(self.feed.ingest_live(SESSION, row))
                self.assertIsNone(self.feed.stream_id)
                self.assertIn(self.feed.failure_reason["type"], ("ValueError", "TypeError", "AttributeError"))

    def test_wrong_source_still_stops_without_exposing_identity(self):
        row = self.health(identity={**IDENTITY, "exe_name": "PRIVATE-PLAYER.exe", "hwnd": "0x123"})
        self.assertFalse(self.feed.ingest_live(SESSION, row))
        failure = self.feed.snapshot()["capture_session"]["failure_reason"]
        self.assertEqual((failure["type"], failure["message"]),
                         ("ValueError", "manual-feed-source-mismatch"))
        self.assertNotIn("PRIVATE-PLAYER", json.dumps(failure))
        self.assertNotIn("0x123", json.dumps(failure))

    def test_bad_epoch_never_becomes_fresh_health(self):
        for epoch in (-1, True, "1", None, 2**53):
            with self.subTest(epoch=epoch):
                self.feed._ingest_row(self.health(epoch=epoch), self.current)
                self.assertFalse(self.state.capture["fresh_capture"])
                self.assertIsNone(self.state.capture["epoch"])

    def test_bad_dimensions_never_become_fresh_health(self):
        for dimensions in ((0, 705), (927, None), (True, 705), ("927", 705), (16385, 705)):
            with self.subTest(dimensions=dimensions):
                self.feed._ingest_row(self.health(frame_width=dimensions[0], frame_height=dimensions[1]), self.current)
                self.assertFalse(self.state.capture["fresh_capture"])
                self.assertIsNone(self.state.capture["epoch"])

    def test_malformed_frame_counts_never_become_fresh_health(self):
        for count in (-1, True, "501", None, 2**53):
            with self.subTest(count=count):
                self.feed._ingest_row(self.health(frame_count=count), self.current)
                self.assertFalse(self.state.capture["fresh_capture"])
                self.assertIsNone(self.state.capture["epoch"])

    def test_malformed_recording_counts_remain_incomplete(self):
        for counts in ((True, 384881594), (502, 384881594), (501, -1), (20001, 384881594)):
            with self.subTest(counts=counts):
                self.feed._ingest_row(self.health(recorded_frames=counts[0], recorded_bytes=counts[1]), self.current)
                self.assertEqual(self.state.capture["recording_status"], "io_failure")
                self.assertFalse(self.state.capture["recording_complete"])

    def test_failure_redacts_names_paths_payloads_but_keeps_technical_message(self):
        cases = ((ValueError("invalid literal for int() with base 10: 'PRIVATE-PLAYER'"),
                  "invalid literal for int() with base 10: '<redacted>'"),
                 (TypeError("'NoneType' object is not subscriptable"), "'NoneType' object is not subscriptable"),
                 (KeyError("frame_count"), "'frame_count'"),
                 (FileNotFoundError(2, "No such file or directory", "C:\\Users\\PRIVATE-PLAYER\\capture.png"),
                  "[Errno 2] No such file or directory"),
                 (ValueError("invalid frame C:\\Users\\PRIVATE-PLAYER\\capture.png"), "invalid frame <private-path>"))
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                self.feed.failure_reason = None
                self.feed._failure(error, "live", failed_boundary_frame(), persist=False)
                self.assertEqual(self.feed.failure_reason["message"], expected)
                self.assertNotIn("PRIVATE-PLAYER", json.dumps(self.feed.failure_reason))
        self.feed.failure_reason = None
        self.feed._failure(ValueError("invalid {'player': 'PRIVATE-PLAYER'}" + "x" * 2000), "live", persist=False)
        self.assertLessEqual(len(self.feed.failure_reason["message"]), 320)
        self.assertNotIn("PRIVATE-PLAYER", json.dumps(self.feed.failure_reason))
        self.feed.failure_reason = None
        self.feed._failure(ValueError("invalid literal for int(): 'PRIVATE\nPLAYER'"), "live", persist=False)
        self.assertEqual(self.feed.failure_reason["message"], "invalid literal for int(): '<redacted>'")

    def test_failure_diagnostic_io_or_perception_cap_never_prevents_stop(self):
        self.state.diagnostics.complete = self.state.readouts.complete = False
        self.visual.submit.side_effect = ValueError("invalid-source-metadata")
        with patch.object(dashboard.manual_capture, "write_json", side_effect=OSError("disk full")):
            self.assertFalse(self.feed.ingest_live(SESSION, failed_boundary_frame()))
        self.assertIsNone(self.feed.stream_id)
        self.assertEqual(self.feed.failure_reason["message"], "invalid-source-metadata")
        self.assertTrue(self.fail_capture.called)

    def test_snapshot_does_not_write_failure_or_stop_and_preserves_receipt_cause(self):
        self.utc += 3001
        with patch.object(dashboard.manual_capture, "write_json") as write:
            snapshot = self.feed.snapshot()
            write.assert_not_called()
            self.fail_capture.assert_not_called()
        failure = snapshot["capture_session"]["failure_reason"]
        self.assertEqual((failure["type"], failure["message"], failure["stage"]),
                         (None, "owner-receipt-expired", "receipt"))
        self.feed.poll()
        self.assertTrue(self.fail_capture.called)
        self.assertIsNone(self.feed.stream_id)
        self.assertEqual(json.loads((self.feed.path / "feed-failure.json").read_bytes()), failure)

    def test_replaced_session_does_not_leak_predecessor_failure(self):
        self.feed._failure(ValueError("manual-feed-source-mismatch"), "live", persist=False)
        self.current.update(session_id="a" * 32, status="stopped", stop_reason="operator-stop", activity_state="idle")
        self.assertIsNone(self.feed.snapshot()["capture_session"]["failure_reason"])
        self.feed.poll()
        self.assertIsNone(self.feed.failure_reason)

    def test_poll_buffers_fragment_and_rejects_invalid_completed_tail(self):
        self.feed.source_policy = "manual"
        self.feed.deadline = self.utc / 1000 + 600
        self.current.update(source_policy="manual", max_duration_ms=600_000, max_frames=1200, remaining_ms=600_000)
        filename = self.feed.path / "stdout.jsonl"
        raw = json.dumps({**self.health(), "source_policy": "manual"}).encode()
        filename.write_bytes(raw)
        self.feed.poll()
        self.assertEqual(self.feed.pending, raw)
        self.assertEqual(self.state.capture["frames"], 0)
        with filename.open("ab") as stream:
            stream.write(b"\n{not-json}\n")
        self.feed.poll()
        self.assertEqual(self.state.capture["frames"], 501)
        self.assertEqual(self.feed.failure_reason["type"], "JSONDecodeError")
        self.assertEqual(self.feed.failure_reason["event"], "unknown")
        self.assertIsNone(self.feed.stream_id)

    def test_poll_backlog_and_record_size_limits_still_fail_closed(self):
        for raw, reason in ((b"x" * (1024 * 1024 + 1), "manual-feed-backlog"),
                            (b"x" * (dashboard.MAX_RECORD + 1), "manual-feed-size")):
            with self.subTest(reason=reason):
                self.feed.source_policy = "manual"
                self.feed.deadline = self.utc / 1000 + 600
                self.feed.offset, self.feed.pending, self.feed.failure_reason = 0, b"", None
                self.feed.stream_id = self.state.session_id
                self.current.update(status="capturing", stop_reason=None, activity_state="verifying",
                    source_policy="manual", max_duration_ms=600_000, max_frames=1200, remaining_ms=600_000)
                (self.feed.path / "stdout.jsonl").write_bytes(raw)
                self.feed.poll()
                if self.feed.stream_id is not None:
                    self.feed.poll()
                self.assertIsNone(self.feed.stream_id)
                self.assertEqual(self.feed.failure_reason["message"], reason)

    @unittest.skipUnless(os.environ.get("LAYA_FEED_PRIVATE_REPLAY_PROOF") == "1",
                         "explicit finite saved-feed replay")
    def test_saved_failed_session_typed_rows(self):
        filename = dashboard.ROOT / ".local/laya/manual-capture" / SESSION / "stdout.jsonl"
        self.assertLessEqual(filename.stat().st_size, dashboard.manual_capture.MAX_LOG)
        self.current["evidence"].update(recorded_frames=0, recorded_bytes=0, elapsed_ms=0)
        self.current.update(recorded_frames=0, recorded_bytes=0, elapsed_ms=0)
        self.feed.evidence_last = copy.deepcopy(self.current["evidence"])
        self.feed.receipt_updated = self.feed.receipt_elapsed = self.feed.receipt_deadline = None
        self.utc = 1792003095237
        count = 0
        with filename.open("rb") as stream:
            for line_number in range(1, 10_001):
                raw = stream.readline(dashboard.MAX_RECORD + 1)
                if not raw:
                    break
                self.assertLessEqual(len(raw), dashboard.MAX_RECORD)
                self.assertTrue(raw.endswith(b"\n"), "incomplete saved JSONL tail")
                row = json.loads(raw, parse_constant=dashboard._reject_constant)
                if row.get("event") == "manual_capture":
                    dashboard.manual_capture._native_record(row, self.current)
                    self.current.update(updated_at_unix_ms=row["updated_at_unix_ms"], elapsed_ms=row["elapsed_ms"])
                    continue  # Supervision receipts are not sent to the sustained live feed.
                self.utc = max(self.utc,
                               row.get("emitted_at_unix_ms", (row.get("frame") or {}).get("source_utc_unix_ms", 0)))
                with self.subTest(line=line_number, event=row.get("event")):
                    self.assertTrue(self.feed.ingest_live(SESSION, row), self.feed.failure_reason)
                    self.assertIsNotNone(self.feed.stream_id)
                    self.state.snapshot()
                count += 1
            else:
                self.fail("saved replay row limit")
        self.assertEqual(self.state.capture["frames"], 505)
        print("finite saved feed: typed_rows=%d, final_health_frames=%d" %
              (count, self.state.capture["frames"]))

    @unittest.skipUnless(os.environ.get("LAYA_FEED_PRIVATE_REPLAY_PROOF") == "1",
                         "explicit finite saved-feed replay")
    def test_saved_visual_submit_without_recognition_or_threads(self):
        import laya_visual
        directory = dashboard.ROOT / ".local/captures/utc-1792003095-224479100-practice"
        manifest = {}
        with (directory / "manifest.jsonl").open("rb") as stream:
            for index in range(1202):
                raw = stream.readline(dashboard.manual_capture.MAX_RECORD + 1)
                if not raw:
                    break
                self.assertLessEqual(len(raw), dashboard.manual_capture.MAX_RECORD)
                self.assertTrue(raw.endswith(b"\n"))
                record = json.loads(raw, parse_constant=dashboard._reject_constant)
                if record.get("event") == "frame":
                    self.assertNotIn(record["frame_index"], manifest)
                    manifest[record["frame_index"]] = record
            else:
                self.fail("saved manifest row limit")
        self.assertEqual(len(manifest), 505)
        latest = None
        with (directory / "visual.jsonl").open("rb") as stream:
            for raw in stream:
                self.assertLessEqual(len(raw), dashboard.MAX_RECORD)
                latest = json.loads(raw, parse_constant=dashboard._reject_constant)
        self.assertIsNotNone(latest)
        worker = self.visual_type(dashboard.ROOT, INSTANCE, wall=lambda: self.utc / 1000)
        scope = latest["session_id"], latest["source_id"], latest["epoch"]
        worker.scope = scope
        worker.value = latest
        worker.value_pixels = (directory / ("frame-%010d.png" % latest["sequence"])).read_bytes()
        self.feed.visual, self.feed.stream_id = worker, scope[0]
        self.state.session_id = scope[0]
        self.state.version = (136, 1)
        count = 0
        filename = dashboard.ROOT / ".local/laya/manual-capture" / SESSION / "stdout.jsonl"
        with patch.object(laya_visual.threading, "Thread") as thread, filename.open("rb") as stream:
            for raw in stream:
                self.assertLessEqual(len(raw), dashboard.MAX_RECORD)
                row = json.loads(raw, parse_constant=dashboard._reject_constant)
                if row.get("event") != "visual_frame" or row["frame"]["frame_index"] < 499:
                    continue
                frame = row["frame"]
                for key in ("frame_index", "source_id", "source_process_created_at_100ns", "sha256", "png_bytes",
                            "width", "height", "captured_at_monotonic_ms", "source_utc_unix_ms", "occluded_regions"):
                    self.assertEqual(frame[key], manifest[frame["frame_index"]][key])
                if frame["frame_index"] == 502:
                    self.assertEqual(row, failed_boundary_frame())
                self.utc = row["frame"]["source_utc_unix_ms"] + 100
                self.feed._ingest_row(row, {"activity_state": "verifying"})
                self.assertEqual(worker.last_frame, frame["frame_index"])
                count += 1
            self.assertEqual(count, 7)
            self.assertEqual(worker.last_frame, 505)
            self.assertGreaterEqual(thread.call_count, 2)
            self.assertLessEqual(thread.call_count, 4)
        print("finite saved submit: visual_rows=%d, final_frame=%d, no recognition/threads" %
              (count, worker.last_frame))


if __name__ == "__main__":
    unittest.main()
