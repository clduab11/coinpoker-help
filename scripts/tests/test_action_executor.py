"""Offline dry-run tests for scripts/action-executor.ps1 (no CoinPoker needed).

The executor is driven against a crafted decision stream under -DryRun
-SkipGeometry: clicks are planned and logged, nothing touches the OS input
queue, and exit codes / refusal paths are asserted. Skipped when no pwsh is
installed.
"""

import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR = ROOT / "scripts" / "action-executor.ps1"
PWSH = shutil.which("pwsh") or shutil.which("powershell")

TABLE_HWND = "0x1234"
TABLE_PID = 4242


def now_ms():
    return int(time.time() * 1000)


def decision(action, amount=0, *, hwnd=TABLE_HWND, pid=TABLE_PID, key=None,
             expires_in=5000, generation=1):
    return {
        "schema_version": 2,
        "event": "decision",
        "action": action,
        "amount": amount,
        "ev": 0.12,
        "pot_odds": 0.25,
        "equity": 0.61,
        "opponent": "unknown",
        "confidence": 0.0,
        "observation": {
            "identity": {"exe_name": "CoinPoker.exe", "process_id": pid, "hwnd": hwnd},
            "generation": generation,
            "epoch": 1,
            "captured_at_ms": 1_000 + generation,
        },
        "captured_at_unix_ms": now_ms() - 200,
        "valid_for_ms": expires_in + 200,
        "emitted_at_unix_ms": now_ms() - 200,
        "expires_at_unix_ms": now_ms() + expires_in,
    }


def partial(pot, *, hwnd=TABLE_HWND, pid=TABLE_PID, generation=1):
    return {
        "schema_version": 2,
        "event": "partial_observation",
        "pot_size": pot,
        "verified_fields": ["pot_size"],
        "observation": {
            "identity": {"exe_name": "CoinPoker.exe", "process_id": pid, "hwnd": hwnd},
            "generation": generation,
            "epoch": 1,
            "captured_at_ms": 1_000 + generation,
        },
        "captured_at_unix_ms": now_ms(),
        "valid_for_ms": 5_000,
        "emitted_at_unix_ms": now_ms(),
        "expires_at_unix_ms": now_ms() + 5_000,
    }


class ExecutorHarness(unittest.TestCase):
    def setUp(self):
        if PWSH is None:
            self.skipTest("pwsh not installed")
        self.temp = tempfile.TemporaryDirectory(prefix="executor-dry-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.jsonl = self.directory / "live.jsonl"
        self.jsonl.write_text("", encoding="utf-8")
        self.log = self.directory / "live.jsonl.executor.log"

    def run_executor(self, steps, args=(), timeout=60):
        """steps: list of (delay_seconds, record) appended after launch."""
        command = [
            PWSH, "-NoProfile", "-File", str(EXECUTOR),
            "-Jsonl", str(self.jsonl), "-DryRun", "-SkipGeometry",
            "-PollMs", "40", "-MinDelayMs", "10", "-MaxDelayMs", "30",
            "-MinLeaseMs", "200", "-VerifyMs", "900", "-EofGraceMs", "1500",
            *args,
        ]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def writer():
            with self.jsonl.open("a", encoding="utf-8") as stream:
                for delay, record in steps:
                    stream.write(json.dumps(record) + "\n")
                    stream.flush()
                    time.sleep(delay)

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        finally:
            thread.join(timeout=5)
        text = self.log.read_text(encoding="utf-8") if self.log.exists() else ""
        return process.returncode, text, stdout.decode(errors="replace") + stderr.decode(errors="replace")

    def assert_in(self, needle, text):
        self.assertIn(needle, text, f"expected {needle!r} in executor log:\n{text}")

    def test_plans_one_click_per_decision_with_identity_amount_and_verifies(self):
        code, log, _ = self.run_executor([
            (0.15, decision("raise", 750, generation=1)),
            (0.15, partial(300, generation=2)),
            (0.15, decision("check", generation=3)),
            (0.15, partial(400, generation=4)),
        ])
        self.assertEqual(code, 0, log)
        self.assertEqual(log.count("dry-click action="), 2, log)
        self.assert_in("dry-click action=raise amount=750 hwnd=0x1234 pid=4242", log)
        self.assert_in("point=746,581", log)
        self.assert_in("dry-click action=check amount=0 hwnd=0x1234", log)
        self.assertEqual(log.count("action-verified"), 2, log)
        self.assertNotIn("action-unverified", log)

    def test_duplicate_decision_key_never_clicks_twice(self):
        first = decision("call", generation=1)
        code, log, _ = self.run_executor([
            (0.15, first),
            (0.15, partial(100, generation=2)),
            (0.1, first),          # identical observation key
            (0.15, partial(200, generation=3)),
        ])
        self.assertEqual(code, 0, log)
        self.assertEqual(log.count("dry-click action="), 1, log)

    def test_stale_lease_is_skipped(self):
        expired = decision("fold", expires_in=-500)
        code, log, _ = self.run_executor([(0.15, expired)])
        self.assertEqual(code, 0, log)
        self.assert_in("lease-expired action=fold", log)
        self.assertNotIn("dry-click", log)

    def test_identity_pin_mismatch_refuses_the_click(self):
        code, log, _ = self.run_executor(
            [(0.15, decision("call")), (0.15, partial(100, generation=2))],
            args=["-Hwnd", "0xdeadbeef"],
        )
        self.assertEqual(code, 0, log)
        self.assert_in("identity-mismatch", log)
        self.assertNotIn("dry-click", log)

    def test_missing_read_back_aborts_fail_closed(self):
        code, log, _ = self.run_executor([(0.15, decision("call"))])
        self.assertEqual(code, 2, log)
        self.assert_in("action-unverified action=call", log)
        self.assert_in("abort-on-unverified", log)

    def test_stop_file_stops_before_any_click(self):
        stop = self.directory / "live.jsonl.stop"
        stop.write_text("stop\n", encoding="utf-8")
        code, log, _ = self.run_executor([(0.2, decision("call"))])
        self.assertEqual(code, 0, log)
        self.assert_in("stop-file-present", log)
        self.assertNotIn("dry-click", log)


if __name__ == "__main__":
    unittest.main()
