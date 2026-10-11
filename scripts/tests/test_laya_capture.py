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

    def test_confirmation_requires_fresh_exact_identity_and_literal_seated_assertion(self):
        self.assertEqual(self.confirm()[0], window())
        self.assertEqual(self.confirm(values=[listing(), listing(window(width=900))])[0].width, 900)
        with self.assertRaisesRegex(ValueError, "exact-source"):
            self.confirm(answers=["yes"])
        with patch.object(capture.uuid, "uuid4", return_value=Mock(hex="b" * 32)):
            with self.assertRaisesRegex(ValueError, "seated-assertion"):
                self.confirm(answers=["CAPTURE 42 0x123 " + "b" * 12, "ready"])
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

    def test_non_object_receipts_fail_closed_without_breaking_public_state(self):
        path, status = self.session()
        for value in ([], None, 1, "private text", True):
            capture.write_json(path / "status.json", value)
            self.assertEqual(capture.public_snapshot(root=self.root)["stop_reason"], "receipt-invalid")
            capture.write_json(path / "status.json", status)
            capture.write_json(path / "markers/bad.json", value)
            self.assertEqual(capture.public_snapshot(root=self.root)["stop_reason"], "receipt-invalid")
            (path / "markers/bad.json").unlink()

    def test_stop_only_sets_named_session_sentinel(self):
        path, _ = self.session()
        capture.stop_session(SESSION, root=self.root)
        capture.stop_session(SESSION, root=self.root)
        self.assertTrue((path / "STOP").exists())
        with self.assertRaises(ValueError):
            capture.stop_session("b" * 32, root=self.root)
        self.assertFalse((path.parent / ("b" * 32)).exists())

    def run_supervisor(self, *, max_seconds=1, max_frames=1200, row=None, interrupt=False, sentinel=False,
                       exit_code=None, timeout=False):
        clock = [0.0]
        child = Mock()
        child.poll.return_value = exit_code
        child.wait.return_value = 0
        if timeout:
            child.wait.side_effect = [subprocess.TimeoutExpired("synthetic", 2), -9]
        def start(command, **kwargs):
            if row is not None:
                kwargs["stdout"].write((json.dumps(row) + "\n").encode())
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
                                     output=lambda _: None)
        path = capture.session_path(capture.read_json(self.root / capture.BASE / "current.json")["session_id"], root=self.root)
        return code, process, child, path, capture.read_json(path / "status.json")

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
