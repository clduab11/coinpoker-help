"""Mocked metadata/children and synthetic private files only. Never real HWNDs."""

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import laya_attach as attach
import laya_capture as capture

SESSION = "a" * 32


def window(**overrides):
    return attach.WindowMetadata(**{"process_id": 42, "hwnd": "0x123", "exe_name": "CoinPoker.exe",
        "title": "PRIVATE SYNTHETIC TITLE", "on_screen": True, "width": 800, "height": 600, **overrides})


def listing(value=None):
    return attach.WindowListing(windows=(value or window(),))


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="manual-capture-fixture-", dir=SCRIPTS.parent / ".local")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / "target/debug/coinpoker.exe"
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b"synthetic nonexecutable")
        for owner, name in ((attach, "list_windows"), (capture.subprocess, "Popen")):
            guard = patch.object(owner, name, side_effect=AssertionError("Real source or child forbidden"))
            guard.start()
            self.addCleanup(guard.stop)

    def session(self, **overrides):
        path = capture.session_path(SESSION, root=self.root)
        path.mkdir(parents=True)
        (path / "markers").mkdir()
        capture.write_json(path / "approval.json", {}, exclusive=True)
        value = capture.default_snapshot()
        value.update(status="capturing", session_id=SESSION, updated_at_unix_ms=10_000, **overrides)
        capture.write_json(path / "status.json", value)
        capture.write_json(path.parent / "current.json", {"session_id": SESSION})
        return path, value

    def confirm(self, values=None, answers=None, times=(0, 0)):
        answers = iter(answers) if answers is not None else None
        def reply(prompt):
            if answers is not None:
                return next(answers)
            return prompt.removeprefix("Type ").split(" to confirm")[0] if "to confirm" in prompt else capture.ASSERTION
        with patch.object(attach, "list_windows", side_effect=values or [listing(), listing()]), \
                patch.object(capture.time, "monotonic", side_effect=times):
            return capture.confirm_source(42, "0x123", root=self.root, input_fn=reply, output=lambda _: None)

    def test_confirmation_requires_fresh_exact_identity_but_no_seating_assertion(self):
        self.assertEqual(self.confirm()[0], window())
        self.assertEqual(self.confirm(values=[listing(), listing(window(width=900))])[0].width, 900)
        with self.assertRaisesRegex(ValueError, "exact-source"):
            self.confirm(answers=["yes"])
        with patch.object(capture.uuid, "uuid4", return_value=Mock(hex="b" * 32)):
            self.assertEqual(self.confirm(answers=["CAPTURE 42 0x123 " + "b" * 12])[0], window())
        for value in (window(title="different"), window(process_id=43), window(hwnd="0x124")):
            with self.assertRaises(ValueError):
                self.confirm(values=[listing(), listing(value)])
        with self.assertRaisesRegex(ValueError, "expired"):
            self.confirm(times=(0, 30.001))

    def test_cli_rejection_never_starts_a_child_or_model(self):
        with patch.object(capture, "confirm_source", side_effect=ValueError("confirmation-required")), \
                patch.object(capture, "supervise") as start, patch("sys.stderr", io.StringIO()):
            self.assertEqual(capture.main(["start", "--pid", "42", "--hwnd", "0x123"]), 2)
        start.assert_not_called()
        self.assertFalse((self.root / capture.BASE).exists())

    def test_private_paths_reject_escape_and_public_source_leaks(self):
        for session in ("../escape", "C:\\secret", "a" * 33, "A" * 32, ""):
            with self.assertRaises(ValueError):
                capture.session_path(session, root=self.root)
        with self.assertRaises(ValueError):
            capture.private_path(self.root / "elsewhere.json", root=self.root)
        self.session(title="PRIVATE SECRET", hwnd="0x123", source=window().private_record())
        safe = capture.public_snapshot(root=self.root, current_ms=10_500)
        self.assertEqual(safe["elapsed_ms"], 500)
        self.assertFalse(safe["inference_enabled"])
        self.assertNotIn("PRIVATE", json.dumps(safe))
        self.assertNotIn("hwnd", json.dumps(safe))
        self.assertNotIn(str(self.root), json.dumps(safe))

    def test_default_public_state_is_idle_without_files_or_enumeration(self):
        self.assertEqual(capture.public_snapshot(root=self.root), capture.default_snapshot())
        self.assertFalse((self.root / ".local").exists())

    def test_stale_and_future_status_fail_closed_without_rearming_or_writes(self):
        path, value = self.session()
        original = (path / "status.json").read_bytes()
        for now in (9999, 13_001):
            safe = capture.public_snapshot(root=self.root, current_ms=now)
            self.assertEqual((safe["status"], safe["stop_reason"]), ("interrupted", "status-stale"))
        self.assertEqual((path / "status.json").read_bytes(), original)
        value["recorded_frames"] = 1201
        capture.write_json(path / "status.json", value)
        self.assertEqual(capture.public_snapshot(root=self.root)["stop_reason"], "receipt-invalid")

    def test_automatic_receipt_capture_running_is_independent_of_activity_and_history(self):
        path, status = self.session(mode="inference-enabled", inference_enabled=True,
                                    source_policy="automatic-bounded", activity_state="verifying",
                                    elapsed_ms=30_100, recorded_frames=80)
        snapshot = capture.public_snapshot(root=self.root, current_ms=10_500)
        self.assertEqual((snapshot["status"], snapshot["activity_state"]), ("capturing", "verifying"))
        self.assertEqual((snapshot["max_duration_ms"], snapshot["max_frames"]), (600_000, 1200))
        self.assertEqual(snapshot["remaining_ms"], 569_400)
        self.assertFalse(snapshot["suggestions_enabled"])
        self.assertNotIn("hero_seated", snapshot)
        self.assertNotIn("history", snapshot)
        capture.stop_session(SESSION, root=self.root)
        stopped = capture.public_snapshot(root=self.root, current_ms=10_500)
        self.assertEqual((stopped["status"], stopped["activity_state"]), ("stopped", "idle"))
        self.assertEqual(capture.read_json(path / "status.json"), status, "public projection remains read-only")

    def test_automatic_supervisor_uses_full_source_budget_without_activity_timeout(self):
        clock, writer, published = [0.0], {}, []
        child = Mock()
        child.poll.return_value = None
        child.wait.return_value = 0
        write_json = capture.write_json
        def progress():
            frames = 1 + int(clock[0] / 10)
            row = {"event": "manual_capture", "version": 1, "mode": "inference-enabled",
                   "source_policy": "automatic-bounded", "activity_state": "verifying",
                   "recording": {"recorded_frames": frames, "recorded_bytes": frames * 500},
                   "capture_failures": 0, "latest_frame": None, "stop_reason": None}
            writer["stdout"].write((json.dumps(row) + "\n").encode())
            writer["stdout"].flush()
        def start(command, **kwargs):
            writer.update(kwargs)
            progress()
            return child
        def sleep(_):
            clock[0] += 10
            progress()
        def publish(path, value, **kwargs):
            if path.name == "status.json":
                published.append(dict(value))
            return write_json(path, value, **kwargs)
        with patch.object(capture.subprocess, "Popen", side_effect=start) as process, \
                patch.object(capture, "inference_service", return_value={"instance_id": "b" * 32,
                    "model_state": "ready", "acceptance_floors_loaded": True}), \
                patch.object(capture.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(capture.time, "sleep", side_effect=sleep), \
                patch.object(capture, "now_ms", side_effect=lambda: 10_000 + int(clock[0] * 1000)), \
                patch.object(capture, "write_json", side_effect=publish):
            result = capture.supervise(window(), root=self.root, confirmed_at_unix_ms=capture.now_ms(),
                mode="inference-enabled", source_policy="automatic-bounded", automatic_assertion=capture.AUTOMATIC_ASSERTION,
                inference_approval={"inference_assertion": capture.INFERENCE_ASSERTION, "service_instance_id": "b" * 32},
                output=lambda _: None)
        self.assertEqual(result, 0)
        process.assert_called_once()
        running = [status for status in published if status["status"] == "capturing"]
        self.assertTrue(any(status["elapsed_ms"] > 30_000 for status in running))
        self.assertTrue(all(status["activity_state"] == "verifying" for status in running))
        final = published[-1]
        self.assertEqual((final["elapsed_ms"], final["stop_reason"], final["activity_state"]),
                         (600_000, "duration-limit", "idle"))
        self.assertEqual((final["max_duration_ms"], final["max_frames"]), (600_000, 1200))
        self.assertNotIn("table-activity-unconfirmed", [status["stop_reason"] for status in published])

    def test_non_object_receipts_fail_closed_without_breaking_public_state(self):
        path, status = self.session()
        for value in ([], None, 1, "private text", True):
            capture.write_json(path / "status.json", value)
            self.assertEqual(capture.public_snapshot(root=self.root)["stop_reason"], "receipt-invalid")
            capture.write_json(path / "status.json", status)
            capture.write_json(path / "markers/bad.json", value)
            self.assertEqual(capture.public_snapshot(root=self.root)["stop_reason"], "receipt-invalid")
            (path / "markers/bad.json").unlink()

    def sustained(self, **overrides):
        return self.session(mode="inference-enabled", inference_enabled=True,
            source_policy="automatic-sustained", activity_state="verifying", receipt_version=2,
            max_duration_ms=None, max_frames=None, remaining_ms=None,
            evidence={"status": "active", "stop_reason": None, "elapsed_ms": 0,
                      "max_duration_ms": 600_000, "max_frames": 1200, "max_bytes": capture.MAX_BYTES,
                      "recorded_frames": 0, "recorded_bytes": 0}, **overrides)

    def test_sustained_receipt_outlives_evidence_budget_without_extending_freshness(self):
        path, value = self.sustained(elapsed_ms=2_700_000, recorded_frames=1200, recorded_bytes=600_000)
        value["evidence"].update(status="ended", stop_reason="frame-limit", elapsed_ms=599_000,
                                 recorded_frames=1200, recorded_bytes=600_000)
        capture.write_json(path / "status.json", value)
        current = capture.public_snapshot(root=self.root, current_ms=10_500)
        self.assertEqual((current["status"], current["elapsed_ms"]), ("capturing", 2_700_000))
        self.assertIsNone(current["remaining_ms"])
        self.assertEqual(current["evidence"], value["evidence"])
        self.assertNotIn("hwnd", json.dumps(current))
        stale = capture.public_snapshot(root=self.root, current_ms=13_001)
        self.assertEqual((stale["status"], stale["stop_reason"]), ("interrupted", "status-stale"))
        capture.stop_session(SESSION, root=self.root)
        self.assertEqual(capture.public_snapshot(root=self.root, current_ms=10_500)["stop_reason"], "operator-stop")

    def test_sustained_receipt_discriminator_and_evidence_are_strict(self):
        path, value = self.sustained()
        for overrides in ({"receipt_version": 1}, {"receipt_version": True}, {"remaining_ms": 600_000},
                          {"max_frames": 1200}, {"experimental_bet_action": True},
                          {"recorded_frames": 1}, {"evidence": None}, {"stop_reason": "source-changed"},
                          {"status": "stopped", "stop_reason": None}):
            capture.write_json(path / "status.json", {**value, **overrides})
            self.assertEqual(capture.public_snapshot(root=self.root, current_ms=10_000)["stop_reason"], "receipt-invalid")
        value.pop("experimental_bet_action")
        capture.write_json(path / "status.json", value)
        self.assertEqual(capture.public_snapshot(root=self.root, current_ms=10_000)["stop_reason"], "receipt-invalid")

    def test_sustained_native_evidence_freezes_but_acquisition_progress_continues(self):
        _, status = self.sustained()
        row = {"event": "manual_capture", "version": 2, "mode": "inference-enabled",
               "source_policy": "automatic-sustained", "activity_state": "verifying",
               "recording": {"recorded_frames": 1200, "recorded_bytes": 600_000},
               "recording_end_reason": "frame-limit", "elapsed_ms": 599_000,
               "capture_failures": 0, "stop_reason": None}
        self.assertIsNone(capture._native_record(row, status))
        evidence = dict(status["evidence"])
        self.assertIsNone(capture._native_record({**row, "elapsed_ms": 2_700_000}, status))
        self.assertEqual(status["evidence"], evidence)
        with self.assertRaises(ValueError):
            capture._native_record({**row, "elapsed_ms": 2_700_001,
                "recording": {"recorded_frames": 1200, "recorded_bytes": 600_001}}, status)

    def test_sustained_requires_distinct_consent_and_live_sink_before_files_or_child(self):
        with patch.object(capture, "inference_service") as service:
            for assertion, sink in ((capture.AUTOMATIC_ASSERTION, lambda *_: True),
                                    (capture.SUSTAINED_ASSERTION, None)):
                with self.assertRaises(ValueError):
                    capture.supervise(window(), root=self.root, confirmed_at_unix_ms=10_000,
                        mode="inference-enabled", source_policy="automatic-sustained",
                        automatic_assertion=assertion, on_record=sink)
            service.assert_not_called()
        self.assertFalse((self.root / capture.BASE).exists())

    def test_pipe_transport_and_diagnostic_log_are_independently_bounded(self):
        reader = capture._PipeReader(io.BytesIO(b"synthetic live record\n"))
        reader.finish()
        self.assertEqual(reader.read(), b"synthetic live record\n")
        self.assertTrue(reader.eof.is_set())
        self.assertFalse(reader.failed.is_set())
        log = io.BytesIO()
        with patch.object(capture, "MAX_LOG", 20):
            self.assertTrue(capture._write_capped(log, b"a" * 10))
            self.assertFalse(capture._write_capped(log, b"b" * 30))
            self.assertFalse(capture._write_capped(log, b"c"))
        self.assertEqual(log.getvalue(), b"a" * 10 + b"b" * 10)
        backlog = capture._PipeReader(io.BytesIO(b"x" * (17 * 64 * 1024)))
        backlog.thread.join(timeout=1)
        self.assertTrue(backlog.failed.is_set())
        self.assertEqual(backlog.failure_reason, "pipe-backlog")
        self.assertEqual(len(backlog.read()), 1024 * 1024)
        backlog.finish()

    def test_pipe_capacity_counts_bytes_not_arbitrary_read_fragments(self):
        data = (json.dumps({"schema_version": 2, "event": "status", "state": "verifying"}) + "\n").encode() * 32
        class FragmentedPipe(io.BytesIO):
            def read(self, size):
                return super().read(min(size, 1))
        reader = capture._PipeReader(FragmentedPipe(data))
        self.addCleanup(reader.finish)
        reader.thread.join(timeout=1)
        self.assertFalse(reader.thread.is_alive())
        self.assertFalse(reader.failed.is_set(), "a small valid burst must not overflow on its seventeenth fragment")
        self.assertTrue(reader.eof.is_set())
        self.assertEqual(reader.read(), data)

    def test_pipe_rejects_read_errors_and_invalid_blocks(self):
        for result in (OSError("synthetic read failure"), None, "text", b"x" * (64 * 1024 + 1)):
            with self.subTest(result=type(result).__name__):
                stream = Mock()
                stream.read.side_effect = [result]
                reader = capture._PipeReader(stream)
                reader.thread.join(timeout=1)
                reader.finish()
                self.assertTrue(reader.failed.is_set())
                self.assertEqual(reader.failure_reason, "pipe-read-failed" if isinstance(result, OSError) else "invalid-pipe-block")
                self.assertFalse(reader.eof.is_set())
                self.assertEqual(reader.read(), b"")

    def test_pipe_drain_releases_byte_backpressure_without_waiting_for_eof(self):
        ready, release = capture.threading.Event(), capture.threading.Event()
        calls = [0]
        def read(_):
            calls[0] += 1
            if calls[0] <= 16:
                return b"a" * (64 * 1024)
            if calls[0] == 17:
                ready.set()
                return b"tail\n"
            release.wait(timeout=1)
            return b""
        reader = capture._PipeReader(Mock(read=read))
        try:
            self.assertTrue(ready.wait(timeout=1))
            self.assertFalse(reader.eof.is_set())
            self.assertEqual(reader.read(), b"a" * (1024 * 1024))
            release.set()
            reader.thread.join(timeout=1)
            self.assertFalse(reader.failed.is_set())
            self.assertTrue(reader.eof.is_set())
            self.assertEqual(reader.read(), b"tail\n")
        finally:
            release.set()
            reader.finish()

    def test_sustained_supervisor_runs_45_minutes_and_only_caps_evidence_and_logs(self):
        clock, published, admitted = [0.0], [], []
        child = Mock(stdout="stdout", stderr="stderr")
        child.poll.side_effect = lambda: 0 if clock[0] >= 2700 else None
        child.wait.return_value = 0
        class Pipe:
            def __init__(self, stream):
                self.stdout = stream == "stdout"
                self.failed = capture.threading.Event()
                self.end_reads = 0
            def read(self):
                if not self.stdout:
                    if clock[0] >= 2700:
                        self.end_reads += 1
                        return b"main diagnostic\n" if self.end_reads == 1 else b"tail diagnostic\n" if self.end_reads == 2 else b""
                    return b""
                frames = min(4, int(clock[0] / 100))
                row = {"event": "manual_capture", "version": 2, "mode": "inference-enabled",
                       "source_policy": "automatic-sustained", "activity_state": "verifying",
                       "elapsed_ms": int(clock[0] * 1000), "recording_end_reason": "frame-limit" if frames == 4 else None,
                       "recording": {"recorded_frames": frames, "recorded_bytes": frames * 500},
                       "capture_failures": 0, "latest_frame": None,
                       "stop_reason": "operator-stop" if clock[0] >= 2700 else None}
                feed = {"schema_version": 2, "event": "status", "state": "verifying"}
                return (json.dumps(row) + "\n" + json.dumps(feed) + "\n").encode()
            def finish(self):
                pass
        write_json = capture.write_json
        def save(path, value, **kwargs):
            if path.name == "status.json":
                published.append(json.loads(json.dumps(value)))
            return write_json(path, value, **kwargs)
        def sleep(_):
            clock[0] += 100
        def admit(session_id, row):
            current = capture.public_snapshot(root=self.root, session_id=session_id)
            self.assertEqual(current["recorded_frames"], min(4, int(clock[0] / 100)),
                             "native progress must be published before a callback can wait on consumer locks")
            self.assertEqual(current["updated_at_unix_ms"], capture.now_ms())
            admitted.append((session_id, row))
            return True
        with patch.object(capture.subprocess, "Popen", return_value=child) as process, \
                patch.object(capture, "_PipeReader", Pipe), patch.object(capture, "write_json", side_effect=save), \
                patch.object(capture, "MAX_LOG", 64), \
                patch.object(capture, "inference_service", return_value={"instance_id": "b" * 32,
                    "model_state": "ready", "acceptance_floors_loaded": True}), \
                patch.object(capture.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(capture.time, "sleep", side_effect=sleep), \
                patch.object(capture, "now_ms", side_effect=lambda: 10_000 + int(clock[0] * 1000)):
            code = capture.supervise(window(), root=self.root, confirmed_at_unix_ms=capture.now_ms(), max_frames=4,
                mode="inference-enabled", source_policy="automatic-sustained", automatic_assertion=capture.SUSTAINED_ASSERTION,
                inference_approval={"inference_assertion": capture.INFERENCE_ASSERTION, "service_instance_id": "b" * 32},
                on_record=admit, output=lambda _: None)
        self.assertEqual(code, 0)
        self.assertEqual((published[-1]["elapsed_ms"], published[-1]["stop_reason"]), (2_700_000, "operator-stop"))
        self.assertTrue(any(row["status"] == "capturing" and row["elapsed_ms"] > 600_000 for row in published))
        self.assertEqual(published[-1]["evidence"]["elapsed_ms"], 400_000)
        self.assertEqual(published[-1]["recorded_frames"], 4)
        process.assert_called_once()
        self.assertEqual(process.call_args.kwargs["stdout"], capture.subprocess.PIPE)
        child.terminate.assert_not_called()
        self.assertEqual(len(admitted), 27, "terminal/tail rows cannot enter live admission")
        session = next((self.root / capture.BASE).glob("[a-f0-9]" * 32))
        self.assertTrue((session / "stderr.log").read_bytes().endswith(b"tail diagnostic\n"))
        self.assertEqual((session / "stdout.jsonl").stat().st_size, 64)
        self.assertFalse((session / "stdout.jsonl").read_bytes().endswith(b"\n"))
        receipt = capture.read_json(session / "run.json")
        self.assertFalse(receipt["diagnostics_complete"])
        self.assertTrue(receipt["receipt_complete"], "a clipped diagnostic file is not a clipped live receipt")
        self.assertEqual(receipt["transport_failures"], {})

    def test_sustained_log_cap_never_hides_invalid_live_records_or_pipe_failures(self):
        cases = (b"{]\n", b"[]\n", b'{"schema_version":3,"event":"status"}\n',
                 b'{"schema_version":2', b"x" * (capture.MAX_FEED_RECORD + 1),
                 b"x" * (capture.MAX_FEED_RECORD + 1) + b"\n", None)
        for index, invalid in enumerate(cases):
            with self.subTest(case=index):
                clock, admitted = [0], []
                row = {"event": "manual_capture", "version": 2, "mode": "inference-enabled",
                       "source_policy": "automatic-sustained", "activity_state": "verifying",
                       "elapsed_ms": 0, "recording_end_reason": None,
                       "recording": {"recorded_frames": 0, "recorded_bytes": 0},
                       "capture_failures": 0, "latest_frame": None, "stop_reason": None}
                feed = {"schema_version": 2, "event": "status", "state": "verifying"}
                class Pipe:
                    def __init__(self, stream):
                        self.chunks = iter([(json.dumps(row) + "\n" + json.dumps(feed) + "\n").encode(), invalid]
                                           if stream == "stdout" else [])
                        self.failed = capture.threading.Event()
                        self.failure_reason = None
                    def read(self):
                        block = next(self.chunks, b"")
                        if block is None:
                            self.failed.set()
                            self.failure_reason = "pipe-backlog"
                            return b""
                        return block
                    def finish(self):
                        pass
                child = Mock(stdout="stdout", stderr="stderr")
                child.poll.side_effect = lambda: 0 if clock[0] else None
                def sleep(_):
                    clock[0] += 1
                with patch.object(capture.subprocess, "Popen", return_value=child) as process, \
                        patch.object(capture, "_PipeReader", Pipe), patch.object(capture, "MAX_LOG", 16), \
                        patch.object(capture, "inference_service", return_value={"instance_id": "b" * 32,
                            "model_state": "ready", "acceptance_floors_loaded": True}), \
                        patch.object(capture.time, "monotonic", side_effect=lambda: clock[0]), \
                        patch.object(capture.time, "sleep", side_effect=sleep), \
                        patch.object(capture, "now_ms", side_effect=lambda: 10_000 + clock[0] * 1000):
                    result = capture.supervise(window(), root=self.root, confirmed_at_unix_ms=capture.now_ms(),
                        mode="inference-enabled", source_policy="automatic-sustained", automatic_assertion=capture.SUSTAINED_ASSERTION,
                        inference_approval={"inference_assertion": capture.INFERENCE_ASSERTION, "service_instance_id": "b" * 32},
                        on_record=lambda *args: admitted.append(args) or True, output=lambda _: None)
                self.assertEqual(result, 1)
                process.assert_called_once()
                self.assertEqual(len(admitted), 1)
                session_id = capture.read_json(self.root / capture.BASE / "current.json")["session_id"]
                session = capture.session_path(session_id, root=self.root)
                self.assertEqual(capture.read_json(session / "status.json")["status"], "failed")
                self.assertEqual((session / "stdout.jsonl").stat().st_size, 16)
                receipt = capture.read_json(session / "run.json")
                self.assertFalse(receipt["diagnostics_complete"])
                self.assertEqual(receipt["transport_failures"], {"stdout": "pipe-backlog"} if invalid is None else {})
                if invalid is None:
                    self.assertEqual(receipt["stop_reason"], "feed-failed")

    def test_stop_only_sets_named_session_sentinel(self):
        path, _ = self.session()
        capture.stop_session(SESSION, root=self.root)
        capture.stop_session(SESSION, root=self.root)
        self.assertTrue((path / "STOP").exists())
        with self.assertRaises(ValueError):
            capture.stop_session("b" * 32, root=self.root)
        self.assertFalse((path.parent / ("b" * 32)).exists())

    def run_supervisor(self, *, max_seconds=1, max_frames=1200, row=None, interrupt=False, sentinel=False,
                         exit_code=None, timeout=False, mode="capture-only", inference_approval=None,
                         source_policy="manual", automatic_assertion=None):
        clock = [0.0]
        child = Mock()
        child.poll.return_value = exit_code
        child.wait.return_value = 0
        if timeout:
            child.wait.side_effect = [subprocess.TimeoutExpired("synthetic", 2), -9]
        def start(command, **kwargs):
            if row is not None:
                for item in row if isinstance(row, list) else [row]:
                    kwargs["stdout"].write((json.dumps(item) + "\n").encode())
                kwargs["stdout"].flush()
            if sentinel:
                Path(command[-1]).with_name("STOP").touch()
            return child
        def sleep(seconds):
            if interrupt:
                raise KeyboardInterrupt()
            clock[0] += max(seconds, 0.000001)
        with patch.object(capture.subprocess, "Popen", side_effect=start) as process, \
                patch.object(capture.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(capture.time, "sleep", side_effect=sleep), \
                patch.object(capture, "now_ms", side_effect=lambda: 10_000 + int(clock[0] * 1000)):
            code = capture.supervise(window(), confirmed_at_unix_ms=capture.now_ms(), root=self.root, max_seconds=max_seconds, max_frames=max_frames,
                                     output=lambda _: None, mode=mode, inference_approval=inference_approval,
                                     source_policy=source_policy, automatic_assertion=automatic_assertion)
        path = capture.session_path(capture.read_json(self.root / capture.BASE / "current.json")["session_id"], root=self.root)
        return code, process, child, path, capture.read_json(path / "status.json")

    def test_experimental_flag_requires_exact_boolean_approval_and_service_agreement(self):
        for flag, service_flag in ((False, False), (False, True), (True, True)):
            with self.subTest(flag=flag, service=service_flag):
                consent = {"inference_assertion": capture.INFERENCE_ASSERTION,
                           "service_instance_id": "b"*32, "experimental_bet_action": flag}
                with patch.object(capture, "inference_service", return_value={"instance_id": "b"*32,
                        "model_state": "ready", "acceptance_floors_loaded": True,
                        "experimental_bet_action": service_flag}):
                    code, process, _, path, status = self.run_supervisor(mode="inference-enabled",
                        source_policy="automatic-bounded", automatic_assertion=capture.AUTOMATIC_ASSERTION,
                        inference_approval=consent)
                self.assertEqual(code, 0)
                command = process.call_args.args[0]
                self.assertEqual("--experimental-bet-action" in command, flag)
                self.assertEqual(command[-1], str(path / "approval.json"))
                self.assertIs(capture.read_json(path / "approval.json")["experimental_bet_action"], flag)
                self.assertIs(status["experimental_bet_action"], flag)
                self.assertEqual((status["max_duration_ms"], status["max_frames"]), (1000, 1200))
                self.assertFalse(status["suggestions_enabled"])

    def test_experimental_mismatch_manual_or_capture_only_refuses_before_child_or_files(self):
        for flag, mode, policy, service_flag in ((True, "inference-enabled", "automatic-bounded", False),
                (True, "inference-enabled", "manual", True), (True, "capture-only", "manual", True),
                (1, "inference-enabled", "automatic-bounded", True),
                ("true", "inference-enabled", "automatic-bounded", True)):
            consent = {"inference_assertion": capture.INFERENCE_ASSERTION,
                       "service_instance_id": "b"*32, "experimental_bet_action": flag}
            with patch.object(capture, "inference_service", return_value={"instance_id": "b"*32,
                    "model_state": "ready", "acceptance_floors_loaded": True,
                    "experimental_bet_action": service_flag}), patch.object(capture.subprocess, "Popen") as child:
                with self.assertRaisesRegex(ValueError, "experimental-bet-action"):
                    capture.supervise(window(), confirmed_at_unix_ms=capture.now_ms(), root=self.root,
                        mode=mode, inference_approval=consent, source_policy=policy,
                        automatic_assertion=capture.AUTOMATIC_ASSERTION if policy == "automatic-bounded" else None)
            child.assert_not_called()
            self.assertFalse((self.root / capture.BASE).exists())

    def test_ambient_experiment_flags_never_activate_default_capture(self):
        with patch.dict(capture.os.environ, {"COINPOKER_EXPERIMENTAL_BET_ACTION": "1"}):
            _, process, _, path, status = self.run_supervisor()
        self.assertNotIn("--experimental-bet-action", process.call_args.args[0])
        self.assertNotIn("COINPOKER_EXPERIMENTAL_BET_ACTION", process.call_args.kwargs["env"])
        self.assertFalse(status["experimental_bet_action"])
        self.assertNotIn("experimental_bet_action", capture.read_json(path / "approval.json"))

    def test_experimental_private_authorization_cannot_be_fabricated_from_status_alone(self):
        path, status = self.session(mode="inference-enabled", inference_enabled=True,
                                    source_policy="automatic-bounded", activity_state="verifying",
                                    experimental_bet_action=True)
        approval = {"experimental_bet_action": True, "source_policy": "automatic-bounded",
                    "automatic_assertion": capture.AUTOMATIC_ASSERTION, "mode": "inference-enabled",
                    "inference_assertion": capture.INFERENCE_ASSERTION, "service_instance_id": "b"*32}
        with patch.object(capture, "now_ms", return_value=10_000):
            self.assertFalse(capture.experimental_session_approved(SESSION, "b"*32, root=self.root))
            capture.write_json(path / "approval.json", approval)
            self.assertTrue(capture.experimental_session_approved(SESSION, "b"*32, root=self.root))
            self.assertFalse(capture.experimental_session_approved(SESSION, "c"*32, root=self.root))
            for key, value in (("experimental_bet_action", 1), ("source_policy", "manual"),
                               ("automatic_assertion", None), ("mode", "capture-only")):
                capture.write_json(path / "approval.json", {**approval, key: value})
                self.assertFalse(capture.experimental_session_approved(SESSION, "b"*32, root=self.root))
            capture.write_json(path / "approval.json", approval)
            capture.stop_session(SESSION, root=self.root)
            self.assertFalse(capture.experimental_session_approved(SESSION, "b"*32, root=self.root))
        for value in (1, "true", None):
            capture.write_json(path / "status.json", {**status, "experimental_bet_action": value})
            self.assertEqual(capture.public_snapshot(root=self.root, current_ms=10_000)["stop_reason"], "receipt-invalid")

    def test_time_budget_terminates_only_one_child_and_never_replaces_or_rearms(self):
        code, process, child, path, status = self.run_supervisor()
        self.assertEqual(code, 0)
        self.assertEqual(status["stop_reason"], "duration-limit")
        self.assertEqual(status["recorded_frames"], 0)
        process.assert_called_once()
        child.terminate.assert_called_once()
        self.assertNotIn("--vlm", " ".join(process.call_args.args[0]))
        self.assertIn("--capture-only", process.call_args.args[0])
        self.assertEqual(process.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertFalse((path.parent / "active.lock").exists())
        receipt = capture.read_json(path / "run.json")
        for field in ("started_utc", "ended_utc", "exit_code", "stdout", "stderr", "command"):
            self.assertIn(field, receipt)
        self.assertTrue(receipt["forced_stop"])
        self.assertEqual(capture.public_snapshot(root=self.root)["opportunity_deficit"], 20)

    def test_frame_budget_stops_before_time_and_logs_gaps(self):
        row = {"event": "manual_capture", "version": 1, "mode": "capture-only",
               "recording": {"recorded_frames": 1, "recorded_bytes": 600}, "capture_failures": 2,
               "capture_directory": "private", "stop_reason": None,
               "latest_frame": {"frame_index": 5, "previous_saved_gap_ms": 2000, "estimated_missed_samples": 3}}
        code, process, child, _, status = self.run_supervisor(row=row, max_frames=1)
        self.assertEqual((code, status["stop_reason"], status["elapsed_ms"]), (0, "frame-limit", 0))
        self.assertEqual((status["gap_count"], status["max_gap_ms"], status["estimated_missed_samples"]), (1, 2000, 3))
        process.assert_called_once()
        child.terminate.assert_called_once()

    def test_ctrl_c_and_stop_sentinel_terminate_without_restart(self):
        for kwargs in ({"interrupt": True}, {"sentinel": True}, {"sentinel": True, "timeout": True}):
            code, process, child, _, status = self.run_supervisor(**kwargs)
            self.assertEqual((code, status["stop_reason"]), (0, "operator-stop"))
            child.terminate.assert_called_once()
            process.assert_called_once()
            if kwargs.get("timeout"):
                child.kill.assert_called_once()

    def test_child_failure_no_retry_and_stale_lock_no_rearm(self):
        code, process, _, path, status = self.run_supervisor(exit_code=7)
        self.assertEqual((code, status["stop_reason"]), (1, "child-failed"))
        self.assertFalse(capture.read_json(path / "run.json")["receipt_complete"])
        process.assert_called_once()
        (path.parent / "active.lock").write_text("synthetic stale lock", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            capture.supervise(window(), confirmed_at_unix_ms=capture.now_ms(), root=self.root)

    def test_malformed_native_receipt_is_not_a_restart_trigger(self):
        code, process, child, path, status = self.run_supervisor(row={"event": "observation", "secret": "PRIVATE"})
        self.assertEqual((code, status["stop_reason"]), (1, "receipt-invalid"))
        child.terminate.assert_called_once()
        process.assert_called_once()
        self.assertIn("PRIVATE", (path / "stdout.jsonl").read_text(encoding="utf-8"))
        self.assertNotIn("PRIVATE", json.dumps(capture.public_snapshot(root=self.root)))

    def test_last_native_receipt_after_exit_is_drained_without_new_process(self):
        child, output = Mock(), {}
        emitted = [False]
        row = {"event": "manual_capture", "version": 1, "mode": "capture-only",
               "recording": {"recorded_frames": 1, "recorded_bytes": 500}, "capture_failures": 0,
               "capture_directory": "PRIVATE DIRECTORY", "latest_frame": None, "stop_reason": "frame-limit"}
        def poll():
            if not emitted[0]:
                emitted[0] = True
                output["stdout"].write((json.dumps(row) + "\n").encode())
                output["stdout"].flush()
            return 0
        def start(command, **kwargs):
            output.update(kwargs)
            return child
        child.poll.side_effect = poll
        with patch.object(capture.subprocess, "Popen", side_effect=start) as process:
            self.assertEqual(capture.supervise(window(), confirmed_at_unix_ms=capture.now_ms(), root=self.root, max_frames=1, output=lambda _: None), 0)
        safe = capture.public_snapshot(root=self.root)
        self.assertEqual((safe["recorded_frames"], safe["stop_reason"]), (1, "frame-limit"))
        child.terminate.assert_not_called()
        process.assert_called_once()

    def test_unconfirmed_child_stop_keeps_lock_and_reports_failure(self):
        child = Mock()
        child.poll.return_value = None
        child.terminate.side_effect = OSError("synthetic permission failure")
        def start(command, **kwargs):
            Path(command[-1]).with_name("STOP").touch()
            return child
        with patch.object(capture.subprocess, "Popen", side_effect=start) as process:
            self.assertEqual(capture.supervise(window(), confirmed_at_unix_ms=capture.now_ms(), root=self.root, output=lambda _: None), 1)
        self.assertTrue((self.root / capture.BASE / "active.lock").exists())
        self.assertEqual(capture.public_snapshot(root=self.root)["stop_reason"], "child-stop-unconfirmed")
        process.assert_called_once()

    def test_bounds_are_not_relaxed_by_command_line(self):
        for seconds, frames in ((0, 1200), (601, 1200), (600, 1201), (True, 100), (600, 0)):
            with self.assertRaises(ValueError):
                capture.supervise(window(), confirmed_at_unix_ms=capture.now_ms(), root=self.root, max_seconds=seconds, max_frames=frames)
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            capture.main(["start", "--pid", "42", "--hwnd", "0x123", "--enable-inference"])

    def test_expired_confirmation_cannot_be_renewed_when_spawning(self):
        for timestamp in (capture.now_ms() - 30_001, capture.now_ms() + 10_000, True):
            with self.assertRaisesRegex(ValueError, "confirmation-expired"):
                capture.supervise(window(), confirmed_at_unix_ms=timestamp, root=self.root)
        self.assertFalse((self.root / capture.BASE).exists())

    def evidence(self):
        directory = self.root / ".local/captures/utc-123-000000000-practice"
        directory.mkdir(parents=True)
        rows = []
        for index, pixels in ((1, b"synthetic PNG A"), (2, b"synthetic PNG A"), (3, b"synthetic PNG B")):
            (directory / ("frame-%010d.png" % index)).write_bytes(pixels)
            rows.append({"event": "frame", "frame_index": index, "source_utc_unix_ms": 1000 + index,
                         "sha256": hashlib.sha256(pixels).hexdigest(), "png_bytes": len(pixels)})
        (directory / "manifest.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        path, _ = self.session(capture_directory=str(directory))
        return path, directory

    def test_markers_bind_hash_utc_and_deduplicate_frames_and_opportunity_ids(self):
        path, directory = self.evidence()
        marker = capture.mark_session(SESSION, "hand1-turn1", "opportunity", 1, root=self.root)
        self.assertFalse(marker["accepted_correction"])
        self.assertEqual((marker["labels"], marker["human_review"]), ("DRAFT", "PENDING"))
        capture.mark_session(SESSION, "alias-for-same-pixels", "opportunity", 2, root=self.root)
        self.assertEqual(capture.opportunity_count(path), 1)
        with self.assertRaises(FileExistsError):
            capture.mark_session(SESSION, "hand1-turn1", "opportunity", 3, root=self.root)
        capture.mark_session(SESSION, "hand1-turn1", "incorrect", 1, "manual draft, no correction accepted", root=self.root)
        capture.mark_session(SESSION, "hand1-turn2", "missing", 3, root=self.root)
        self.assertEqual(capture.opportunity_count(path), 1)
        capture.mark_session(SESSION, "hand1-turn2", "opportunity", 3, root=self.root)
        self.assertEqual(capture.public_snapshot(root=self.root, current_ms=10_000)["opportunity_deficit"], 18)
        (directory / "frame-0000000003.png").write_bytes(b"corrupted")
        with self.assertRaisesRegex(ValueError, "integrity"):
            capture.mark_session(SESSION, "changed", "incorrect", 3, root=self.root)

    def test_markers_never_accept_unacknowledged_or_invalid_frame(self):
        path, _ = self.evidence()
        for opportunity, kind, frame in (("../escape", "missing", 1), ("valid", "accepted", 1), ("valid", "missing", 99)):
            with self.assertRaises(ValueError):
                capture.mark_session(SESSION, opportunity, kind, frame, root=self.root)
        self.assertEqual(list((path / "markers").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
