"""Synthetic lifecycle/transport tests. No real HWND, model load or inference."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.tests import test_laya_capture as capture_tests
from scripts.tests import test_laya_dashboard_stage2 as stage2
from scripts.tests import test_laya_server as server_tests

capture, dashboard, srv = capture_tests.capture, stage2.dashboard, server_tests.srv
INSTANCE, SESSION = "b" * 32, "a" * 32
REAL_POPEN = capture.subprocess.Popen


class InferenceConsentTests(unittest.TestCase):
    @unittest.skipUnless(capture.os.name == "nt", "Windows shared-delete receipt contract")
    def test_receipt_reader_does_not_block_atomic_replacement_and_reads_one_version(self):
        with tempfile.TemporaryDirectory(prefix="receipt-sharing-contract-", dir=dashboard.ROOT / ".local") as temporary:
            path = Path(temporary) / "receipt.json"
            capture.write_json(path, {"version": "original"})
            fdopen = capture.os.fdopen
            class Reader:
                def __init__(self, descriptor, mode):
                    self.stream = fdopen(descriptor, mode)
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    self.stream.close()
                def read(self, maximum):
                    capture.write_json(path, {"version": "replacement"})
                    return self.stream.read(maximum)
            with patch.object(capture.os, "fdopen", side_effect=Reader):
                self.assertEqual(capture.read_json(path), {"version": "original"})
            self.assertEqual(capture.read_json(path), {"version": "replacement"})

    def test_missing_consent_refuses_before_status_source_or_child(self):
        with patch.object(capture, "inference_service") as status, patch.object(capture.subprocess, "Popen") as child:
            with self.assertRaisesRegex(ValueError, "inference-approval"):
                capture.supervise(capture_tests.window(), confirmed_at_unix_ms=capture.now_ms(), mode="inference-enabled")
        status.assert_not_called()
        child.assert_not_called()

    def test_capture_only_does_not_even_probe_model(self):
        fixture = capture_tests.CaptureTests()
        fixture.setUp()
        try:
            with patch.object(capture, "inference_service", side_effect=AssertionError("model probe forbidden")), \
                    patch.object(srv, "Engine", side_effect=AssertionError("model load forbidden")):
                code, process, _, _, status = fixture.run_supervisor()
            self.assertEqual(code, 0)
            self.assertFalse(status["inference_enabled"])
            self.assertIn("--capture-only", process.call_args.args[0])
        finally:
            fixture.doCleanups()

    def test_terminal_receipt_write_failure_cannot_skip_owned_child_termination(self):
        fixture = capture_tests.CaptureTests()
        fixture.setUp()
        try:
            with patch.object(capture, "stop_session", side_effect=OSError("synthetic disk failure")):
                code, process, child, path, status = fixture.run_supervisor()
            self.assertEqual((code, status["stop_reason"]), (1, "supervisor-error"))
            child.terminate.assert_called_once()
            process.assert_called_once()
            self.assertFalse((path.parent / "active.lock").exists())
        finally:
            fixture.doCleanups()

    def test_native_terminal_reason_is_not_overwritten_by_stop_acknowledgement(self):
        fixture = capture_tests.CaptureTests()
        fixture.setUp()
        try:
            row = {"event": "manual_capture", "version": 1, "mode": "capture-only",
                   "recording": {"recorded_frames": 1, "recorded_bytes": 500}, "capture_failures": 0,
                   "capture_directory": "PRIVATE", "latest_frame": None, "stop_reason": "frame-limit"}
            code, _, _, _, status = fixture.run_supervisor(row=row, max_frames=1, sentinel=True)
            self.assertEqual((code, status["stop_reason"]), (0, "frame-limit"))
        finally:
            fixture.doCleanups()

    def test_inference_consent_loading_cancellation_has_no_source_or_budget(self):
        for answer in ("yes", capture.INFERENCE_ASSERTION):
            with patch.object(capture, "inference_service", return_value={"model_state": "loading"}) as status, \
                    patch.object(capture.time, "sleep", side_effect=KeyboardInterrupt()), \
                    patch.object(capture, "confirm_source") as source, patch.object(capture.subprocess, "Popen") as child:
                with self.assertRaises(KeyboardInterrupt if answer == capture.INFERENCE_ASSERTION else ValueError):
                    capture.approve_inference(input_fn=lambda _: answer, output=lambda _: None)
            source.assert_not_called()
            child.assert_not_called()
            self.assertEqual(status.call_count, int(answer == capture.INFERENCE_ASSERTION))

    def test_inference_supervisor_owns_one_child_and_accepts_typed_progress(self):
        fixture = capture_tests.CaptureTests()
        fixture.setUp()
        consent = {"inference_assertion": capture.INFERENCE_ASSERTION, "service_instance_id": INSTANCE}
        try:
            rows = [{"schema_version": 2, "event": "configuration", "identity_configured": True},
                    {"event": "manual_capture", "version": 1, "mode": "inference-enabled",
                     "recording": {"recorded_frames": 1, "recorded_bytes": 500}, "capture_failures": 0,
                     "capture_directory": "PRIVATE", "latest_frame": None, "stop_reason": "frame-limit"}]
            with patch.object(capture, "inference_service", return_value={"instance_id": INSTANCE,
                    "model_state": "ready", "acceptance_floors_loaded": True}):
                code, process, _, path, status = fixture.run_supervisor(mode="inference-enabled",
                    inference_approval=consent, row=rows, max_frames=1, exit_code=0)
            self.assertEqual((code, status["recorded_frames"], status["stop_reason"]), (0, 1, "frame-limit"))
            process.assert_called_once()
            self.assertEqual(process.call_args.args[0][1], "--manual-inference")
            self.assertEqual(capture.read_json(path / "approval.json")["inference_assertion"], capture.INFERENCE_ASSERTION)
            self.assertEqual(capture.read_json(path / "approval.json")["source"], capture_tests.window().private_record())
            self.assertEqual(len((path / "stdout.jsonl").read_bytes().splitlines()), 2)
        finally:
            fixture.doCleanups()

    def test_ready_wait_precedes_fresh_source_confirmation(self):
        calls = []
        def consent():
            calls.append("inference-consent-and-readiness")
            return {"inference_assertion": capture.INFERENCE_ASSERTION, "service_instance_id": INSTANCE}
        def source(*args, **kwargs):
            calls.append("fresh-source-confirmation")
            return capture_tests.window(), capture.now_ms()
        with patch.object(capture, "approve_inference", side_effect=consent), \
                patch.object(capture, "confirm_source", side_effect=source), \
                patch.object(capture, "supervise", return_value=0) as start:
            self.assertEqual(capture.main(["start", "--pid", "42", "--hwnd", "0x123", "--mode", "inference-enabled"]), 0)
        self.assertEqual(calls, ["inference-consent-and-readiness", "fresh-source-confirmation"])
        self.assertEqual(start.call_args.kwargs["inference_approval"]["service_instance_id"], INSTANCE)

    def test_replaced_service_or_loading_refuses_before_capture(self):
        for extra in ({"instance_id": "c" * 32}, {"model_state": "loading"}, {"acceptance_floors_loaded": False}):
            value = {"instance_id": INSTANCE, "model_state": "ready", "acceptance_floors_loaded": True, **extra}
            with patch.object(capture, "inference_service", return_value=value), patch.object(capture.subprocess, "Popen") as child:
                with self.assertRaisesRegex(ValueError, "model-not-ready"):
                    capture.supervise(capture_tests.window(), confirmed_at_unix_ms=capture.now_ms(), mode="inference-enabled",
                                      inference_approval={"inference_assertion": capture.INFERENCE_ASSERTION, "service_instance_id": INSTANCE})
            child.assert_not_called()

    def test_service_stop_during_initialization_never_publishes_ready_or_warms(self):
        pins = {"server": {"port": 18090, "alias": server_tests.ALIAS}, "model": {"revision": "synthetic", "finetuned": {}}}
        captured = {}
        service = srv.Service(server_tests.ALIAS)
        def worker(**kwargs):
            captured["initialize"] = kwargs["target"]
            return Mock()
        def verify(_):
            service.shutting_down.set()
            return []
        with patch.object(srv, "BoundedHTTPServer") as http, patch.object(srv, "Service", return_value=service), \
                patch.object(srv.threading, "Thread", side_effect=worker), patch.object(srv, "verify", side_effect=verify), \
                patch.object(srv, "Engine") as engine, patch("sys.stdout", io.StringIO()):
            http.return_value.serve_forever.side_effect = lambda: captured["initialize"]()
            srv.cmd_serve(pins, None, None, dashboard_only=False, enable_inference=True)
        engine.assert_not_called()
        self.assertIsNone(service.engine)
        self.assertNotEqual(service.state.model["model_state"], "ready")


class ManualFeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="manual-feed-contract-", dir=dashboard.ROOT / ".local")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        fixture = stage2.PartialTests()
        fixture.setUp()
        self.clock, self.fixture = fixture.clock, fixture
        self.state = dashboard.DashboardState("synthetic", monotonic=self.clock.mono, wall=self.clock.wall)
        self.state.set_model("ready", floors_loaded=True)
        self.feed = dashboard.ManualSessionFeed(self.state, INSTANCE, root=self.root)
        self.addCleanup(self.feed.stop)
        self.now_patch = patch.object(capture, "now_ms", side_effect=lambda: int(self.clock.wall() * 1000))
        self.now_patch.start()
        self.addCleanup(self.now_patch.stop)
        for module, name in ((capture.attach, "list_windows"), (capture.subprocess, "Popen"), (srv, "Engine")):
            guard = patch.object(module, name, side_effect=AssertionError("real runtime forbidden"))
            guard.start()
            self.addCleanup(guard.stop)

    def session(self, sid=SESSION, **overrides):
        path = capture.session_path(sid, root=self.root)
        path.mkdir(parents=True)
        (path / "markers").mkdir()
        approval = {"version": 1, "mode": "inference-enabled", "operator_assertion": None,
                    "inference_assertion": capture.INFERENCE_ASSERTION, "service_instance_id": INSTANCE,
                    "confirmed_at_unix_ms": capture.now_ms(), "max_seconds": 600, "max_frames": 1200,
                    "source": stage2.IDENTITY}
        status = {**capture.default_snapshot(), "session_id": sid, "mode": "inference-enabled",
                  "inference_enabled": True, "status": "capturing", "updated_at_unix_ms": capture.now_ms(), **overrides}
        capture.write_json(path / "approval.json", approval)
        capture.write_json(path / "status.json", status)
        capture.write_json(path.parent / "current.json", {"session_id": sid})
        (path / "stdout.jsonl").touch()
        return path

    def append(self, path, *rows):
        with (path / "stdout.jsonl").open("ab") as stream:
            for row in rows:
                stream.write((json.dumps({"service_instance_id": INSTANCE, **row}) + "\n").encode())

    def automatic_session(self, **overrides):
        path = self.session(source_policy="automatic-bounded", activity_state="verifying", **overrides)
        approval = capture.read_json(path / "approval.json")
        approval.pop("operator_assertion")
        approval.update(source_policy="automatic-bounded", automatic_assertion=capture.AUTOMATIC_ASSERTION)
        capture.write_json(path / "approval.json", approval)
        return path

    def sustained_session(self):
        evidence = {"status": "active", "stop_reason": None, "elapsed_ms": 0, "max_duration_ms": 600_000,
                    "max_frames": 1200, "max_bytes": capture.MAX_BYTES, "recorded_frames": 0, "recorded_bytes": 0}
        path = self.session(source_policy="automatic-sustained", activity_state="verifying", receipt_version=2,
                            max_duration_ms=None, max_frames=None, remaining_ms=None, evidence=evidence)
        approval = capture.read_json(path / "approval.json")
        approval.pop("operator_assertion")
        approval.update(version=2, source_policy="automatic-sustained", automatic_assertion=capture.SUSTAINED_ASSERTION,
                        experimental_bet_action=False)
        capture.write_json(path / "approval.json", approval)
        return path

    def live_row(self, row):
        return {"service_instance_id": INSTANCE, "source_policy": "automatic-sustained", "activity_state": "verifying", **row}

    def live_reading(self, generation=1, **overrides):
        self.assertTrue(self.feed.ingest_live(SESSION, self.live_row(self.health(generation))))
        self.assertTrue(self.feed.ingest_live(SESSION, self.live_row(self.fixture.record(generation=generation, **overrides))))
        return self.feed.snapshot()

    def test_sustained_pipe_can_publish_after_recording_ends_but_readings_still_expire(self):
        path = self.sustained_session()
        value = self.live_reading()
        self.assertIsNotNone(value["partial_observation"])
        status = capture.read_json(path / "status.json")
        # The same owner must keep supplying fresh heartbeats throughout the run.
        for elapsed in range(2000, 2_700_001, 2000):
            self.clock.value += 2
            status.update(elapsed_ms=elapsed, updated_at_unix_ms=capture.now_ms())
            status["evidence"]["elapsed_ms"] = min(elapsed, 590_000)
            if elapsed >= 590_000:
                status.update(recorded_frames=1200, recorded_bytes=500_000)
                status["evidence"].update(status="ended", stop_reason="frame-limit",
                                         recorded_frames=1200, recorded_bytes=500_000)
            capture.write_json(path / "status.json", status)
            self.assertTrue(self.feed.authorizes(SESSION, INSTANCE))
        current = self.live_reading(2, role="uncertain", hero_seated=None)
        self.assertEqual(current["capture_session"]["status"], "capturing")
        self.assertEqual(current["partial_observation"]["pot_size"], 12345)
        self.assertIn(current["partial_observation"]["role"], (None, "uncertain"))
        self.assertIsNone(current["advice"])
        self.assertTrue(self.feed.authorizes(SESSION, INSTANCE))
        self.clock.value += 1.1
        self.assertIsNone(self.feed.snapshot()["partial_observation"])
        self.assertEqual((path / "stdout.jsonl").stat().st_size, 0, "live input does not grow a disk feed")

    def test_sustained_disk_feed_and_bounded_consent_cannot_supply_live_readings(self):
        path = self.sustained_session()
        self.append(path, self.live_row(self.health()), self.live_row(self.fixture.record()))
        self.feed.poll()
        self.assertIsNone(self.feed.snapshot()["partial_observation"])
        approval = capture.read_json(path / "approval.json")
        approval["automatic_assertion"] = capture.AUTOMATIC_ASSERTION
        capture.write_json(path / "approval.json", approval)
        fresh_feed = dashboard.ManualSessionFeed(self.state, INSTANCE, root=self.root)
        self.addCleanup(fresh_feed.stop)
        self.assertFalse(fresh_feed.ingest_live(SESSION, self.live_row(self.health())))
        self.assertIsNone(fresh_feed.stream_id)

    def test_sustained_terminal_or_stale_receipt_cannot_be_resurrected(self):
        path = self.sustained_session()
        self.live_reading()
        status = capture.read_json(path / "status.json")
        self.clock.value += 3.1
        self.assertIsNone(self.feed.snapshot()["partial_observation"])
        capture.write_json(path / "status.json", {**status, "updated_at_unix_ms": capture.now_ms()})
        self.assertFalse(self.feed.ingest_live(SESSION, self.live_row(self.health(2))))
        self.assertTrue((path / "STOP").exists())
        self.assertFalse(self.feed.authorizes(SESSION, INSTANCE))

    def test_sustained_wall_clock_freeze_cannot_renew_monotonic_owner_lease(self):
        self.sustained_session()
        self.live_reading()
        wall, stamp = self.clock.wall(), capture.now_ms()
        with patch.object(capture, "now_ms", return_value=stamp), patch.object(self.state, "wall", return_value=wall):
            self.clock.value += 2
            self.assertTrue(self.feed.authorizes(SESSION, INSTANCE))
            self.clock.value += 1.001
            self.assertFalse(self.feed.authorizes(SESSION, INSTANCE))
        self.assertIsNone(self.feed.stream_id)

    def test_sustained_quantized_owner_clock_does_not_regress_a_projected_wall_clock(self):
        path = self.sustained_session()
        self.live_reading()
        self.clock.value += 0.016
        self.assertTrue(self.feed.authorizes(SESSION, INSTANCE))
        self.clock.value += 0.001
        status = capture.read_json(path / "status.json")
        # Windows monotonic samples can advance in coarser ticks than wall time.
        status.update(elapsed_ms=15, updated_at_unix_ms=capture.now_ms())
        capture.write_json(path / "status.json", status)
        self.assertTrue(self.feed.authorizes(SESSION, INSTANCE))

    def test_sustained_regressed_observation_elapsed_is_not_a_new_owner(self):
        path = self.sustained_session()
        self.live_reading()
        status = capture.read_json(path / "status.json")
        status.update(elapsed_ms=1000)
        capture.write_json(path / "status.json", status)
        self.assertTrue(self.feed.authorizes(SESSION, INSTANCE))
        capture.write_json(path / "status.json", {**status, "elapsed_ms": 500})
        self.assertFalse(self.feed.authorizes(SESSION, INSTANCE))
        self.assertIsNone(self.feed.stream_id)

    def test_sustained_evidence_rollback_or_reopening_fails_closed(self):
        path = self.sustained_session()
        self.live_reading()
        status = capture.read_json(path / "status.json")
        status.update(recorded_frames=1200, recorded_bytes=500_000)
        status["evidence"].update(status="ended", stop_reason="frame-limit", elapsed_ms=590_000,
                                 recorded_frames=1200, recorded_bytes=500_000)
        capture.write_json(path / "status.json", status)
        self.assertTrue(self.feed.authorizes(SESSION, INSTANCE))
        status.update(recorded_frames=1199)
        status["evidence"].update(status="active", stop_reason=None, recorded_frames=1199)
        capture.write_json(path / "status.json", status)
        self.assertFalse(self.feed.ingest_live(SESSION, self.live_row(self.health(2))))
        self.assertIsNone(self.feed.snapshot()["partial_observation"])

    def test_sustained_source_mismatch_stops_inference_and_drops_late_results(self):
        path = self.sustained_session()
        self.live_reading()
        row = self.live_row(self.health(2, identity={**stage2.IDENTITY, "hwnd": "0x999"}))
        self.assertFalse(self.feed.ingest_live(SESSION, row))
        self.assertEqual(capture.public_snapshot(root=self.root)["stop_reason"], "feed-failed")
        self.assertIsNone(self.feed.snapshot()["partial_observation"])
        self.assertFalse(self.feed.ingest_live(SESSION, self.live_row(self.fixture.record(generation=3))))
        self.assertTrue((path / "STOP").exists())

    def test_sustained_shutdown_tombstones_feed_before_waiting_for_its_thread(self):
        path = self.sustained_session()
        self.live_reading()
        thread = Mock()
        thread.join.side_effect = lambda **_: self.assertIsNone(self.feed.stream_id)
        self.feed.thread = thread
        self.feed.stop()
        self.assertTrue((path / "STOP").exists())
        self.assertIsNone(self.state.snapshot()["partial_observation"])
        self.assertFalse(self.feed.ingest_live(SESSION, self.live_row(self.fixture.record(generation=2))))

    def append_automatic(self, path, *rows, activity="verifying"):
        self.append(path, *({"source_policy": "automatic-bounded", "activity_state": activity, **row} for row in rows))

    def health(self, generation=1, epoch=1, **extra):
        return {"schema_version": 2, "event": "capture_health", "generation": generation, "epoch": epoch,
                "identity": stage2.IDENTITY, "fresh_capture": True, "frame_count": 7,
                "emitted_at_unix_ms": capture.now_ms(), "captured_at_unix_ms": capture.now_ms(),
                "frame_width": 800, "frame_height": 613, **extra}

    def reading(self, path, **extra):
        record = self.fixture.record(**extra)
        record["pot_size_text"] = "123.45"
        self.append(path, self.health(), record)
        self.feed.poll()
        return self.feed.snapshot()

    def test_approved_typed_partial_reaches_actual_dashboard_projection_and_renderer(self):
        path = self.session()
        value = self.reading(path)
        self.assertEqual(value["partial_observation"]["pot_size_text"], "123.45")
        self.assertIsNone(value["partial_observation"]["seats"][2]["displayed_stack"])
        self.assertIsNone(value["partial_observation"]["hero_seated"])
        self.assertIsNone(value["advice"])
        self.assertTrue((path / "ledger.jsonl").is_file())
        # Real app.js renderer, not a replacement view or HTTP injection.
        from scripts.tests.test_companion_ui import CompanionUiTests
        ui = CompanionUiTests()
        ui.snapshot = value
        ui.snapshot["server"]["inference_enabled"] = True
        ui.snapshot["partial_observation"]["pot_size_text"] = None
        ui.snapshot["partial_observation"].update(game_phase="preflop", board_count=0)
        def node_only(command, *args, **kwargs):
            if command[0] != "node":
                raise AssertionError("only synthetic Node renderer allowed")
            return REAL_POPEN(command, *args, **kwargs)
        with patch.object(capture.subprocess, "Popen", side_effect=node_only):
            ui.run_ui("phase-independent")

    def test_missing_approval_or_foreign_service_does_not_attach(self):
        path = self.session()
        approval = capture.read_json(path / "approval.json")
        approval["service_instance_id"] = "c" * 32
        capture.write_json(path / "approval.json", approval)
        value = self.reading(path)
        self.assertIsNone(value["partial_observation"])
        self.assertEqual(value["capture"]["state"], "blocked")
        approval["service_instance_id"] = INSTANCE
        capture.write_json(path / "approval.json", approval)
        self.feed.poll()
        self.assertIsNone(self.feed.stream_id)  # consumed attempt, never rearm

    def test_capture_only_receipt_never_becomes_an_inference_feed(self):
        path = self.session(mode="capture-only", inference_enabled=False)
        self.assertIsNone(self.reading(path)["partial_observation"])
        self.assertIsNone(self.feed.stream_id)

    def test_stop_clears_before_supervisor_ack_and_late_output_cannot_repopulate(self):
        path = self.session()
        self.assertIsNotNone(self.reading(path)["partial_observation"])
        capture.stop_session(SESSION, root=self.root)
        value = self.feed.snapshot()
        self.assertIsNone(value["partial_observation"])
        self.append(path, self.health(2), self.fixture.record(generation=2))
        self.feed.poll()
        self.assertIsNone(self.state.snapshot()["partial_observation"])

    def test_terminal_receipt_precedes_late_results_in_same_block(self):
        path = self.session()
        self.reading(path)
        self.append(path, {"event": "manual_capture", "version": 1, "mode": "inference-enabled", "stop_reason": "inference-failed"},
                    self.health(2), self.fixture.record(generation=2))
        self.feed.poll()
        self.assertIsNone(self.state.snapshot()["partial_observation"])
        self.assertEqual(self.state.message, "inference-failed")

    def test_replacement_retires_original_and_mismatched_source_fails_closed(self):
        path = self.session()
        self.reading(path)
        other = self.session("c" * 32)
        self.feed.poll()
        self.assertIsNone(self.state.snapshot()["partial_observation"])
        self.append(other, self.health(identity={**stage2.IDENTITY, "hwnd": "0x999"}))
        self.feed.poll()
        self.assertEqual(capture.public_snapshot(root=self.root)["stop_reason"], "feed-failed")
        capture.write_json(path.parent / "current.json", {"session_id": SESSION})
        self.feed.poll()
        self.assertIsNone(self.feed.stream_id)

    def test_original_expiry_and_session_duration_cannot_be_renewed(self):
        path = self.session()
        value = self.reading(path)
        expiry = value["partial_observation"]["expires_at_unix_ms"]
        self.clock.value += 0.5
        self.assertEqual(self.state.snapshot()["partial_observation"]["expires_at_unix_ms"], expiry)
        self.clock.value += 0.6
        self.assertIsNone(self.state.snapshot()["partial_observation"])
        self.clock.value += 600
        status = capture.read_json(path / "status.json")
        status.update(elapsed_ms=0, updated_at_unix_ms=capture.now_ms())
        capture.write_json(path / "status.json", status)
        self.feed.poll()
        self.assertIsNone(self.feed.stream_id)

    def test_count_limit_and_stale_status_invalidate_without_polling_refresh_rearm(self):
        for change in ({"recorded_frames": 1200}, {"updated_at_unix_ms": capture.now_ms() - 3001}):
            sid = "a" * 32 if "recorded_frames" in change else "d" * 32
            path = self.session(sid)
            self.reading(path)
            status = capture.read_json(path / "status.json")
            capture.write_json(path / "status.json", {**status, **change})
            self.assertIsNone(self.feed.snapshot()["partial_observation"])
            self.feed.poll()
            self.assertIsNone(self.feed.stream_id)

    def test_resize_invalidates_geometry_without_new_stream_or_budget(self):
        path = self.session()
        self.reading(path)
        stream, deadline = self.feed.stream_id, self.feed.deadline
        self.append(path, self.health(2, 2, frame_width=900))
        self.feed.poll()
        self.assertEqual((self.feed.stream_id, self.feed.deadline), (stream, deadline))
        self.assertIsNone(self.state.snapshot()["partial_observation"])

    def test_backlog_and_malformed_feed_remain_visible_and_stop_collection(self):
        for sid, raw in (("a" * 32, b"x" * (1024 * 1024 + 1)), ("d" * 32, b"{not-json}\n")):
            path = self.session(sid)
            self.reading(path)
            with (path / "stdout.jsonl").open("ab") as stream:
                stream.write(raw)
            self.feed.poll()
            self.assertTrue((path / "STOP").exists())
            self.assertEqual(capture.public_snapshot(root=self.root)["stop_reason"], "feed-failed")
            self.assertIsNone(self.state.snapshot()["partial_observation"])

    def test_refresh_does_not_start_feed_or_native_child(self):
        path = self.session()
        self.append(path, self.health(), self.fixture.record())
        for _ in range(4):
            self.assertIsNone(self.feed.snapshot()["partial_observation"])
        self.assertIsNone(self.feed.stream_id)
        self.assertEqual(self.feed.offset, 0)

    def test_model_loss_fails_closed_and_stops_the_existing_session(self):
        path = self.session()
        self.reading(path)
        self.state.set_model("failed", "predict-failed")
        self.assertIsNone(self.feed.snapshot()["partial_observation"])
        self.feed.poll()
        self.assertTrue((path / "STOP").exists())
        self.assertEqual(capture.public_snapshot(root=self.root)["stop_reason"], "model-not-ready")

    def test_receipt_failure_is_not_mislabeled_as_an_operator_stop(self):
        path = self.session()
        self.reading(path)
        failed = {**capture.default_snapshot(), "status": "failed", "stop_reason": "receipt-invalid"}
        with patch.object(capture, "public_snapshot", return_value=failed):
            self.feed.snapshot()
        self.feed.poll()
        current = capture.public_snapshot(root=self.root)
        self.assertEqual((current["status"], current["stop_reason"]), ("failed", "feed-failed"))
        self.assertTrue((path / "STOP").exists())

    def test_stale_snapshot_recovery_and_shutdown_cannot_leave_hidden_collection(self):
        path = self.session()
        self.reading(path)
        self.clock.value += 3.1
        self.assertIsNone(self.feed.snapshot()["partial_observation"])
        status = capture.read_json(path / "status.json")
        capture.write_json(path / "status.json", {**status, "updated_at_unix_ms": capture.now_ms()})
        self.assertFalse((path / "STOP").exists())  # GET remains read-only.
        self.feed.poll()
        self.assertTrue((path / "STOP").exists())
        self.assertIsNone(self.feed.stream_id)
        second = self.session("c" * 32)
        self.reading(second)
        self.clock.value += 3.1
        self.feed.snapshot()
        self.feed.stop()
        self.assertTrue((second / "STOP").exists())

    def test_bound_prediction_refuses_foreign_stopped_and_late_results(self):
        path = self.session()
        service = srv.Service(server_tests.ALIAS, engine=object())
        service.state, service.manual_feed = self.state, self.feed
        with patch.object(srv, "handle_predict", return_value=(200, {"answers": {}})) as handler:
            self.assertEqual(service.predict(b"{}", session_binding=(SESSION, "c" * 32))[0], 409)
            handler.assert_not_called()
            self.assertEqual(service.predict(b"{}", session_binding=(SESSION, INSTANCE))[0], 200)
            self.assertEqual(handler.call_count, 1)
            capture.stop_session(SESSION, root=self.root)
            self.assertEqual(service.predict(b"{}", session_binding=(SESSION, INSTANCE))[0], 409)
            self.assertEqual(handler.call_count, 1)
        next_sid = "c" * 32
        self.session(next_sid)
        def slow(*args):
            capture.stop_session(next_sid, root=self.root)
            return 200, {"answers": {"private-late-answer": 1}}
        with patch.object(srv, "handle_predict", side_effect=slow) as handler:
            self.assertEqual(service.predict(b"{}", session_binding=(next_sid, INSTANCE)), (409, {"error": "manual-session-ended"}))
            handler.assert_called_once()
        self.assertIsNone(self.feed.stream_id)

    def test_partial_malformed_field_does_not_erase_other_admissible_fields(self):
        path = self.session()
        cards = self.fixture.record()["board_slots"]
        cards[0] = {"rank": "not-a-card", "suit": "hearts"}
        value = self.reading(path, board_slots=cards)["partial_observation"]
        self.assertIsNone(value["board_slots"][0])
        self.assertIsNotNone(value["board_slots"][2])
        self.assertEqual(value["pot_size"], 12345)
        self.assertEqual(value["seats"][0]["displayed_stack"], 100)

    def test_automatic_consent_allows_independent_readout_before_activity_not_hero_or_history(self):
        path = self.automatic_session()
        self.append_automatic(path, self.health(reason="activity-verifying"),
                              self.fixture.record(hero_seated=True, role="your_turn", action_required=True,
                                                  pot_size_text="123.45", hero_seat=4, hero_chips=50000))
        self.feed.poll()
        self.assertTrue(self.feed.authorizes(SESSION, INSTANCE))
        snapshot = self.feed.snapshot()
        reading = snapshot["partial_observation"]
        self.assertEqual(reading["pot_size"], 12345)
        self.assertEqual(reading["seats"][0]["displayed_stack"], 100)
        self.assertEqual(reading["seats"][3]["displayed_stack"], 0)
        self.assertEqual(reading["board_slots"][0], {"rank": "A", "suit": "hearts"})
        self.assertIsNone(reading["board_slots"][1])
        self.assertEqual(reading["role"], "uncertain")
        self.assertIsNone(reading["hero_seated"])
        self.assertIsNone(reading["hero_seat"])
        self.assertIsNone(snapshot["observation"])
        self.assertIsNone(snapshot["advice"])
        self.assertEqual(snapshot["capture_session"]["activity_state"], "verifying")
        self.assertEqual(snapshot["capture_session"]["status"], "capturing")
        self.assertTrue(snapshot["capture"]["fresh_capture"])
        self.assertEqual(snapshot["history"], {"state": "unavailable", "events": [], "counts": {}, "gaps": 0,
                                              "ledger": {"enabled": True, "complete": True}})
        from scripts.tests.test_companion_ui import CompanionUiTests
        ui = CompanionUiTests()
        ui.snapshot = snapshot
        ui.snapshot["server"]["inference_enabled"] = True
        def node_only(command, *args, **kwargs):
            if command[0] != "node":
                raise AssertionError("only synthetic Node renderer allowed")
            return REAL_POPEN(command, *args, **kwargs)
        with patch.object(capture.subprocess, "Popen", side_effect=node_only):
            ui.run_ui("automatic-preactivity")
        status = capture.read_json(path / "status.json")
        capture.write_json(path / "status.json", {**status, "activity_state": "active"})
        self.append_automatic(path, self.health(2), self.fixture.record(generation=2), activity="active")
        self.feed.poll()
        self.assertIsNotNone(self.state.snapshot()["partial_observation"])
        self.assertIsNone(self.state.snapshot()["partial_observation"]["hero_seated"])

    def test_automatic_full_observation_and_history_need_active_row_and_receipt(self):
        path = self.automatic_session()
        source = self.fixture.record()
        self.append_automatic(path, self.health(), source)
        self.feed.poll()
        before = self.state.snapshot()["partial_observation"]
        full = {**self.fixture.record(generation=2), "event": "observation", "game_phase": "preflop",
                "hero_cards": [], "board": [], "verified_fields": ["pot_size"]}
        history = {"schema_version": 2, "event": "history", "summary": {
            "counts": {"folds": 1, "checks": 0, "calls": 0, "bets": 0, "raises": 0},
            "events": [{"event": "action", "action": {"kind": "fold", "seat": 2}}]}}
        for activity in ("verifying", "active"):
            self.append_automatic(path, full, history, {"schema_version": 2, "event": "table"}, activity=activity)
            self.feed.poll()
            snapshot = self.state.snapshot()
            self.assertEqual(snapshot["partial_observation"], before)
            self.assertIsNone(snapshot["observation"])
            self.assertEqual(snapshot["history"]["state"], "unavailable")
            self.assertEqual(snapshot["history"]["events"], [])
            self.assertEqual(snapshot["history"]["counts"], {})
            self.assertEqual(snapshot["history"]["gaps"], 0)
        status = capture.read_json(path / "status.json")
        capture.write_json(path / "status.json", {**status, "activity_state": "active"})
        self.append_automatic(path, full, history)
        self.feed.poll()
        self.assertIsNone(self.state.snapshot()["observation"])
        self.assertEqual(self.state.snapshot()["history"]["events"], [])
        self.append_automatic(path, self.health(2), full, history, activity="active")
        self.feed.poll()
        snapshot = self.feed.snapshot()
        self.assertIsNotNone(snapshot["observation"])
        self.assertEqual(snapshot["history"]["state"], "partial")
        self.assertEqual(snapshot["history"]["counts"]["observed_actions"], 1)
        self.assertIsNone(snapshot["advice"])
        capture.stop_session(SESSION, root=self.root)
        stopped = self.feed.snapshot()
        self.assertIsNone(stopped["observation"])
        self.assertIsNone(stopped["partial_observation"])
        self.assertEqual(stopped["capture_session"]["activity_state"], "idle")
        self.assertEqual(stopped["history"], snapshot["history"], "already qualified saved history survives stop")

    def test_preactivity_active_header_cannot_upgrade_readout_without_active_receipt(self):
        path = self.automatic_session()
        self.append_automatic(path, self.health(), self.fixture.record(hero_seated=False, role="observing"), activity="active")
        self.feed.poll()
        snapshot = self.feed.snapshot()
        self.assertEqual(snapshot["partial_observation"]["pot_size"], 12345)
        self.assertEqual(snapshot["partial_observation"]["role"], "uncertain")
        self.assertIsNone(snapshot["partial_observation"]["hero_seated"])
        self.assertEqual(snapshot["capture_session"]["activity_state"], "verifying")
        self.assertEqual(snapshot["history"]["state"], "unavailable")

    def test_preactivity_diagnostics_keep_independent_fields_and_source_bound_reasons(self):
        path = self.automatic_session()
        source = self.fixture.record(pot_size=None)
        self.append_automatic(path, self.health(), source)
        self.feed.poll()
        before = self.state.snapshot()["partial_observation"]
        deadline = self.state.partial_deadline
        diagnostics = {**source, "event": "perception_diagnostics", "frame_width": 800, "frame_height": 613,
                       "passes": [], "source_current": True, "admission": "source_current", "fields": [
                           {"field": "pot_size", "status": "rejected", "reason": "below-floor",
                            "admission_status": "rejected", "admission_reason": "below-floor"}]}
        self.append_automatic(path, diagnostics)
        self.feed.poll()
        snapshot = self.feed.snapshot()
        self.assertEqual(self.state.diagnostics.count, 1)
        self.assertEqual(snapshot["partial_observation"]["seats"], before["seats"])
        self.assertIsNone(snapshot["partial_observation"]["pot_size"])
        self.assertEqual(snapshot["field_statuses"]["pot_size"]["reason"], "below-floor")
        self.assertEqual(self.state.partial_deadline, deadline)
        self.assertIsNone(snapshot["observation"])
        self.assertEqual(snapshot["history"]["state"], "unavailable")

    def test_preactivity_status_and_capture_health_do_not_clear_or_renew_partial(self):
        path = self.automatic_session()
        self.append_automatic(path, self.health(), self.fixture.record())
        self.feed.poll()
        before = self.state.snapshot()["partial_observation"]
        deadline = self.state.partial_deadline
        self.clock.value += .2
        self.append_automatic(path, {"schema_version": 2, "event": "status", "state": "verifying",
                                     "reason": "activity-verifying"}, self.health(2, reason="activity-verifying"))
        self.feed.poll()
        after = self.feed.snapshot()["partial_observation"]
        self.assertEqual(after["pot_size"], before["pot_size"])
        self.assertEqual(after["board_slots"], before["board_slots"])
        self.assertEqual(after["expires_at_unix_ms"], before["expires_at_unix_ms"])
        self.assertEqual(self.state.partial_deadline, deadline)
        self.assertEqual(self.feed.snapshot()["capture_session"]["activity_state"], "verifying")
        self.clock.value += .801
        self.assertIsNone(self.feed.snapshot()["partial_observation"])
        self.append_automatic(path, self.health(3), self.fixture.record())
        self.feed.poll()
        self.assertIsNone(self.state.snapshot()["partial_observation"])

    def test_preactivity_replacement_and_scoped_invalidation_do_not_create_history(self):
        path = self.automatic_session()
        old = self.fixture.record(verified_fields=["pot_size", "seats.1.displayed_stack", "board_slots.1"])
        self.append_automatic(path, self.health(), old)
        self.feed.poll()
        new = self.fixture.record(generation=2, pot_size=None,
                                  verified_fields=["seats.2.displayed_stack", "board_slots.3"])
        self.append_automatic(path, self.health(2), new, self.fixture.scoped_invalidation(old))
        self.feed.poll()
        reading = self.feed.snapshot()["partial_observation"]
        self.assertIsNone(reading["pot_size"])
        self.assertIsNone(reading["seats"][0]["displayed_stack"])
        self.assertEqual(reading["seats"][1]["displayed_stack"], 200)
        self.assertIsNone(reading["board_slots"][0])
        self.assertIsNotNone(reading["board_slots"][2])
        self.append_automatic(path, self.fixture.scoped_invalidation(new), new)
        self.feed.poll()
        snapshot = self.state.snapshot()
        self.assertIsNone(snapshot["partial_observation"])
        self.assertEqual(snapshot["field_statuses"]["seats.2.displayed_stack"]["reason"], "stale")
        self.assertEqual(snapshot["history"]["state"], "unavailable")
        self.assertEqual(snapshot["history"]["gaps"], 0)

    def test_preactivity_keeps_capability_schema_floors_and_independent_rejections(self):
        path = self.automatic_session()
        record = self.fixture.record()
        record["capabilities"][5]["acceptance_floor"] = .79
        record["board_slots"][0] = {"rank": "PRIVATE", "suit": "hearts"}
        self.append_automatic(path, self.health(), record)
        self.feed.poll()
        reading = self.feed.snapshot()["partial_observation"]
        self.assertIsNone(reading["pot_size"])
        self.assertIsNone(reading["board_slots"][0])
        self.assertIsNotNone(reading["board_slots"][2])
        self.assertEqual(reading["seats"][0]["displayed_stack"], 100)
        self.append_automatic(path, self.health(2), self.fixture.record(generation=2,
                              verified_fields=["pot_size", "PRIVATE"]))
        self.feed.poll()
        reading = self.feed.snapshot()["partial_observation"]
        self.assertIsNone(reading["pot_size"])
        self.assertTrue(all(seat["displayed_stack"] is None for seat in reading["seats"]))

    def test_preactivity_stop_and_source_loss_clear_and_late_fields_cannot_refill(self):
        for index, loss in enumerate(("stop", "health", "status", "source", "epoch")):
            with self.subTest(loss=loss):
                sid = str(index + 1) * 32
                path = self.automatic_session(sid=sid)
                self.append_automatic(path, self.health(), self.fixture.record())
                self.feed.poll()
                self.assertIsNotNone(self.feed.snapshot()["partial_observation"])
                if loss == "stop":
                    capture.stop_session(sid, root=self.root)
                    self.assertIsNone(self.feed.snapshot()["partial_observation"])
                elif loss == "health":
                    self.append_automatic(path, self.health(2, fresh_capture=False, reason="activity-verifying"))
                elif loss == "status":
                    self.append_automatic(path, {"schema_version": 2, "event": "status", "state": "unavailable",
                                                 "reason": "source-unavailable"})
                elif loss == "source":
                    self.append_automatic(path, self.health(2, identity={**stage2.IDENTITY, "hwnd": "0x999"}))
                else:
                    self.append_automatic(path, self.health(2, 2))
                self.append_automatic(path, self.fixture.record())
                self.feed.poll()
                snapshot = self.feed.snapshot()
                self.assertIsNone(snapshot["partial_observation"])
                self.assertIsNone(snapshot["observation"])
                self.assertIsNone(snapshot["advice"])
                self.assertEqual(snapshot["history"]["events"], [])
                self.assertEqual(snapshot["history"]["gaps"], 0)

    def test_preactivity_envelope_service_policy_and_activity_remain_fail_closed(self):
        for index, extra in enumerate(({"service_instance_id": "c" * 32}, {"source_policy": "manual"},
                                       {"activity_state": None}, {"activity_state": "PRIVATE"})):
            with self.subTest(extra=extra):
                path = self.automatic_session(sid=str(index + 1) * 32)
                self.append_automatic(path, self.health(), self.fixture.record())
                self.feed.poll()
                self.assertIsNotNone(self.feed.snapshot()["partial_observation"])
                self.append_automatic(path, self.fixture.record(generation=2, **extra))
                self.feed.poll()
                self.assertIsNone(self.feed.stream_id)
                self.assertIsNone(self.feed.snapshot()["partial_observation"])
                self.assertEqual(capture.public_snapshot(root=self.root)["stop_reason"], "feed-failed")

    def test_preactivity_recommendations_never_gain_advice_or_history(self):
        for index, event in enumerate(("decision", "recommendation")):
            with self.subTest(event=event):
                path = self.automatic_session(sid=str(index + 1) * 32)
                self.append_automatic(path, self.health(), self.fixture.record())
                self.feed.poll()
                before = self.state.snapshot()["partial_observation"]
                record = {"schema_version": 2, "event": event, "source_policy": "automatic-bounded",
                          "activity_state": "verifying", "quality_approved": True, "action": "call"}
                self.state.ingest(record)
                self.assertEqual(self.state.snapshot()["partial_observation"], before)
                self.assertIsNone(self.state.snapshot()["advice"])
                self.assertFalse(self.state.snapshot()["server"]["advice_ready"])
                self.assertEqual(self.state.snapshot()["history"]["state"], "unavailable")
                self.append_automatic(path, record)
                self.feed.poll()
                self.assertIsNone(self.feed.stream_id, "non-feed recommendation fails closed")
                self.assertIsNone(self.feed.snapshot()["partial_observation"])

    def test_automatic_receipt_must_not_fabricate_a_seated_assertion(self):
        path = self.session(source_policy="automatic-bounded", activity_state="verifying")
        approval = capture.read_json(path / "approval.json")
        approval.update(source_policy="automatic-bounded", automatic_assertion=capture.AUTOMATIC_ASSERTION,
                        operator_assertion=capture.ASSERTION)
        capture.write_json(path / "approval.json", approval)
        self.feed.poll()
        self.assertIsNone(self.feed.stream_id)

    def test_missing_automatic_activity_is_never_promoted_to_active(self):
        path = self.session(source_policy="automatic-bounded", activity_state="verifying")
        status = capture.read_json(path / "status.json")
        status.pop("activity_state")
        capture.write_json(path / "status.json", status)
        self.assertEqual(capture.public_snapshot(root=self.root)["status"], "failed")
        native = {"version": 1, "event": "manual_capture", "mode": "inference-enabled",
                  "source_policy": "automatic-bounded"}
        with self.assertRaises(KeyError):
            capture._native_record(native, status)


class AutomaticStartupTests(unittest.TestCase):
    def setUp(self):
        self.service = srv.Service(server_tests.ALIAS)
        self.service.instance_id = INSTANCE
        self.service.state.set_model("ready", floors_loaded=True)
        self.auto = capture.AutomaticStart(self.service)

    def test_automatic_flag_requires_separate_model_opt_in(self):
        with patch.object(srv, "load_pins") as pins, patch.object(srv, "cmd_serve") as serve, \
                patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                srv.main(["serve", "--automatic-inference"])
        pins.assert_not_called()
        serve.assert_not_called()
        with patch.object(srv, "load_pins", return_value={}), patch.object(srv, "cmd_serve", return_value=0) as serve:
            self.assertEqual(srv.main(["serve", "--enable-inference", "--automatic-inference"]), 0)
        self.assertEqual(serve.call_args.args[-2:], (True, True))

    def test_continuous_flag_requires_both_opt_ins_and_refuses_experiments(self):
        for args in (["--continuous-observation"], ["--enable-inference", "--continuous-observation"],
                     ["--automatic-inference", "--continuous-observation"],
                     ["verify", "--enable-inference", "--automatic-inference", "--continuous-observation"],
                     ["--enable-inference", "--automatic-inference", "--continuous-observation", "--experimental-bet-action"]):
            with patch.object(srv, "load_pins") as pins, patch.object(srv, "cmd_serve") as start, \
                    patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                srv.main(args)
            pins.assert_not_called()
            start.assert_not_called()
        with patch.object(srv, "load_pins", return_value={}), patch.object(srv, "cmd_serve", return_value=0) as start:
            self.assertEqual(srv.main(["--enable-inference", "--automatic-inference", "--continuous-observation"]), 0)
        self.assertIs(start.call_args.kwargs["continuous_observation"], True)
        launcher = (dashboard.ROOT / "scripts/start-vlm.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$ContinuousObservation", launcher)
        self.assertIn("if ($ContinuousObservation) { $serverArgs += '--continuous-observation' }", launcher)

    def test_launcher_error_sink_is_byte_bounded_and_requires_private_continuous_mode(self):
        stream = io.BytesIO()
        log = srv.BoundedErrorLog(stream)
        with patch.object(capture, "MAX_LOG", 20):
            self.assertEqual(log.write("diagnostic\n"), 11)
            self.assertEqual(log.write("more\n" * 100), 500)
            log.flush()
        self.assertEqual(len(stream.getvalue()), 20)
        self.assertFalse(log.isatty())
        for args in (["--stderr-log", "unapproved.txt"],
                     ["--enable-inference", "--automatic-inference", "--continuous-observation", "--stderr-log", "unapproved.txt"]):
            with patch.object(srv, "load_pins") as pins, patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                srv.main(args)
            pins.assert_not_called()

    def test_service_closes_feed_admission_before_waiting_on_capture_owner(self):
        service = srv.Service(server_tests.ALIAS)
        feed, owner = Mock(), Mock()
        owner.stop.side_effect = lambda: self.assertTrue(feed.stop.called and service.shutting_down.is_set())
        pins = {"model": {"revision": "synthetic"},
                "server": {"alias": server_tests.ALIAS, "port": 18090, "host": "127.0.0.1"}}
        with patch.object(srv, "BoundedHTTPServer") as http, patch.object(srv, "Service", return_value=service), \
                patch.object(srv.dashboard, "ManualSessionFeed", return_value=feed), \
                patch.object(srv.manual_capture, "AutomaticStart", return_value=owner), \
                patch.object(srv.threading, "Thread", return_value=Mock()), patch("sys.stdout", io.StringIO()):
            self.assertEqual(srv.cmd_serve(pins, None, None, dashboard_only=False, enable_inference=True,
                                           automatic_inference=True, continuous_observation=True), 0)
        owner.stop.assert_called_once()
        http.return_value.server_close.assert_called_once()

    def test_loading_cancel_and_browser_snapshot_never_discover_or_capture(self):
        self.service.state.set_model("loading")
        with patch.object(capture.attach, "list_windows") as discover, patch.object(capture, "supervise") as run, \
                patch.object(self.auto.closed, "wait", side_effect=lambda _: self.auto.closed.set()):
            self.assertEqual(self.auto.snapshot()["status"], "waiting-model")
            self.auto._run()
        discover.assert_not_called()
        run.assert_not_called()
        self.assertEqual(self.auto.snapshot()["status"], "stopped")

    def test_unique_metadata_launches_exactly_one_bounded_probe_without_seating(self):
        listing = capture_tests.attach.WindowListing(windows=(capture_tests.window(),))
        result = capture_tests.attach.AttachResult("ready", (("pid", 42), ("window_hwnd", "0x123")))
        with patch.object(capture.attach, "list_windows", return_value=listing), \
                patch.object(capture.attach.PracticeAttachment, "select", return_value=result), \
                patch.object(capture, "supervise", return_value=0) as run, \
                patch.object(capture, "public_snapshot", return_value={"status": "stopped", "stop_reason": "table-activity-unconfirmed"}), \
                patch.object(capture, "confirm_source", side_effect=AssertionError("no seated assertion in automatic policy")):
            self.auto._run()
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], capture_tests.window())
        self.assertEqual(run.call_args.kwargs["source_policy"], "automatic-bounded")
        self.assertEqual(run.call_args.kwargs["automatic_assertion"], capture.AUTOMATIC_ASSERTION)
        self.assertEqual(self.auto.reason, "table-activity-unconfirmed")

    def test_absent_wait_is_metadata_only_and_ambiguity_is_terminal(self):
        for reason in ("practice-target-absent", "practice-target-ambiguous"):
            auto = capture.AutomaticStart(self.service)
            with patch.object(capture.attach, "list_windows", return_value=capture_tests.attach.WindowListing()), \
                    patch.object(capture.attach.PracticeAttachment, "select", return_value=capture_tests.attach.AttachResult(reason)), \
                    patch.object(capture, "supervise") as run, \
                    patch.object(auto.closed, "wait", side_effect=lambda _: auto.closed.set()):
                auto._run()
            run.assert_not_called()
            self.assertEqual(auto.status, "failed" if reason.endswith("ambiguous") else "stopped")

    def test_search_timeout_never_creates_a_capture_session(self):
        with patch.object(capture.time, "monotonic", side_effect=[0, 600]), \
                patch.object(capture.attach, "list_windows") as discover, patch.object(capture, "supervise") as run:
            self.auto._run()
        discover.assert_not_called()
        run.assert_not_called()
        self.assertEqual(self.auto.reason, "automatic-discovery-timeout")

    def test_slow_metadata_cannot_arm_after_original_search_deadline(self):
        listing = capture_tests.attach.WindowListing(windows=(capture_tests.window(),))
        result = capture_tests.attach.AttachResult("ready", (("pid", 42), ("window_hwnd", "0x123")))
        with patch.object(capture.time, "monotonic", side_effect=[0, 599, 601]), \
                patch.object(capture.attach, "list_windows", return_value=listing), \
                patch.object(capture.attach.PracticeAttachment, "select", return_value=result), \
                patch.object(capture, "supervise") as run:
            self.auto._run()
        run.assert_not_called()
        self.assertEqual(self.auto.reason, "automatic-discovery-timeout")

    def test_missing_explicit_profile_cannot_fall_back_to_an_nlh_window(self):
        with tempfile.TemporaryDirectory(prefix="automatic-profile-contract-", dir=dashboard.ROOT / ".local") as root:
            auto = capture.AutomaticStart(self.service, profile=".local/missing-explicit.json", root=Path(root))
            listing = capture_tests.attach.WindowListing(windows=(capture_tests.window(title="NLH100"),))
            with patch.object(capture.attach, "list_windows", return_value=listing), patch.object(capture, "supervise") as run:
                auto._run()
            run.assert_not_called()
            self.assertEqual(auto.reason, "practice-profile-invalid")

    def test_startup_uses_same_authoritative_receipt_as_capture_projection(self):
        self.auto.session_id = SESSION
        current = {**capture.default_snapshot(), "session_id": SESSION, "status": "capturing", "activity_state": "verifying"}
        with patch.object(capture, "public_snapshot", side_effect=AssertionError("duplicate mutable receipt read")):
            self.assertEqual(self.auto.snapshot(current)["status"], "verifying")
            failed = {**capture.default_snapshot(), "status": "failed", "stop_reason": "receipt-invalid"}
            self.assertEqual(self.auto.snapshot(failed)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
