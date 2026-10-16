"""Finite capture-failure copy, never private native window diagnostics."""
import json
import shutil
import subprocess
import unittest

from scripts.tests import test_companion_ui as companion
from scripts.tests import test_laya_dashboard_stage2 as stage2


CHECKS = r"""
const message = nodes.get('monitor-stop').textContent;
for (const text of input.contains || []) assert(message.includes(text), `${text}: ${message}`);
for (const text of input.absent || []) assert(!message.includes(text), `${text}: ${message}`);
assert(![...nodes.values()].some(node => node.textContent.includes('PRIVATE_NATIVE_DETAIL')));
if (input.terminal) assert(!visible());
"""


@unittest.skipUnless(shutil.which("node"), "Node required for synthetic DOM contracts")
class CaptureFailureUiTests(unittest.TestCase):
    def check(self, code=None, *, previous=False, startup=False, status="stopped", stop_reason="capture-failed", contains=(), absent=()):
        fixture = companion.CompanionUiTests()
        fixture.setUp()
        fixture.manual_session(status=status, stop_reason=stop_reason if status == "stopped" else None,
                               capture_failure_code=code)
        value = fixture.snapshot
        value["capture_session"]["capture_failure"] = {
            "code": code, "detail": "PRIVATE_NATIVE_DETAIL hwnd=123 pid=456 class=window rect=[1,2,3,4]"}
        if previous:
            value["capture_session"]["updated_at_unix_ms"] -= 86_400_000
        if startup:
            value["capture_session"]["source_policy"] = "automatic-bounded"
            value["automatic_startup"] = {"enabled": True, "status": "failed",
                "last_session_id": value["capture_session"]["session_id"], "stop_reason": "capture-failed"}
        payload = {"scenario": "capture-failure-copy", "snapshot": value,
            "app": str(stage2.dashboard.ROOT / "scripts/dashboard/app.js"),
            "html": str(stage2.dashboard.ROOT / "scripts/dashboard/index.html"),
            "contains": list(contains), "absent": list(absent), "terminal": status == "stopped"}
        script = stage2.NODE_UI.replace("console.log(`offline UI", CHECKS + "\nconsole.log(`offline UI")
        script = script.replace("JSON.parse(fs.readFileSync(0, 'utf8'))", json.dumps(payload))
        result = subprocess.run(["node", "-"], input=script, capture_output=True,
                                text=True, encoding="utf-8", timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_current_overlap_explains_recovery_without_private_metadata(self):
        self.check("foreign-overlap", contains=("Uncover the table",), absent=("hwnd=", "pid=", "rect="))

    def test_automatic_failure_does_not_overwrite_overlap_explanation(self):
        self.check("foreign-overlap", startup=True, contains=("Automatic observation failed", "Uncover the table"))

    def test_popup_and_visibility_failures_have_fixed_explanations(self):
        self.check("popup-overlap", contains=("popup",))
        self.check("center-mismatch", contains=("visibility",))

    def test_previous_overlap_is_historical_not_a_current_recovery_instruction(self):
        self.check("foreign-overlap", previous=True, contains=("Previous", "overlap"), absent=("Uncover the table",))

    def test_missing_unknown_or_malformed_codes_keep_generic_copy(self):
        for code in (None, "PRIVATE_NATIVE_DETAIL", {"code": "foreign-overlap"}):
            with self.subTest(code=code):
                self.check(code, contains=("capture-failed",), absent=("Uncover the table",))

    def test_historical_failure_does_not_override_a_capturing_session(self):
        self.check("foreign-overlap", status="capturing", absent=("Uncover the table", "capture failure"))

    def test_retained_diagnostic_does_not_replace_an_operator_stop(self):
        self.check("foreign-overlap", stop_reason="operator-stop", contains=("operator-stop", "Last capture diagnostic", "overlap"),
                   absent=("Uncover the table",))


if __name__ == "__main__":
    unittest.main()
