"""Hermetic validation receipts, workflow YAML, and PowerShell parser checks."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "validate", Path(__file__).resolve().parents[1] / "validate.py"
)
validate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate)


class ValidationTests(unittest.TestCase):
    def test_python_test_receipt_reports_actual_counts_and_skips(self):
        code = """
import unittest
class SyntheticTests(unittest.TestCase):
    def test_pass(self):
        pass
    @unittest.skip('explicit synthetic opt-in')
    def test_skip(self):
        pass
unittest.main(verbosity=2)
"""
        with tempfile.TemporaryDirectory() as directory, patch("builtins.print"):
            root = Path(directory)
            result = validate.run_command(root, root, "python-tests", [sys.executable, "-B", "-c", code])
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(result["python_tests"]["run"], 2)
            self.assertEqual(result["python_tests"]["skipped"], 1)
            self.assertEqual(len(result["python_tests"]["skip_details"]), 1)
            self.assertIn("explicit synthetic opt-in", result["python_tests"]["skip_details"][0][1])

    def test_missing_python_summary_is_unknown_not_zero_coverage(self):
        with tempfile.TemporaryDirectory() as directory, patch("builtins.print"):
            root = Path(directory)
            result = validate.run_command(root, root, "python-tests",
                [sys.executable, "-B", "-c", "raise SystemExit(1)"])
            self.assertEqual(result["exit_code"], 1)
            self.assertIsNone(result["python_tests"]["run"])
            self.assertIsNone(result["python_tests"]["skipped"])

    def test_invoking_interpreter_output_directory_and_advisory_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / "receipts/s1"
            commands = []

            def run_command(command_root, command_out, name, command):
                self.assertEqual(command_root, root)
                self.assertEqual(command_out, out)
                commands.append((name, command))
                return {"check": name, "command": command, "exit_code": 0}

            with patch.object(validate, "__file__", str(root / "scripts/validate.py")), \
                    patch.object(validate.shutil, "which", return_value=None), \
                    patch.object(validate, "run_command", side_effect=run_command), \
                    patch.object(validate, "validate_workflow_workflows", return_value=(127, "parser unavailable")), \
                    patch("builtins.print"):
                self.assertEqual(validate.main(["--output-dir", "receipts/s1"]), 0)
            self.assertEqual(dict(commands)["python-tests"][:3], [sys.executable, "-B", "-m"])
            report = json.loads((out / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["python"], {"executable": sys.executable, "version": sys.version})
            self.assertFalse(report["physical_windows_acceptance"])
            blocked = [record for record in report["checks"] if record.get("advisory")]
            self.assertEqual({record["check"] for record in blocked}, {"workflow-yaml", "powershell-syntax"})
            self.assertTrue(all(record["exit_code"] == 127 for record in blocked))
            self.assertFalse((root / ".local").exists())

    def test_workflow_validation_accepts_trigger_and_rejects_bad_yaml_or_structure(self):
        documents = [
            ("on: [push]\njobs:\n  quality:\n    runs-on: ubuntu-latest\n", 0),
            ("name: no trigger\njobs: {}\n", 1),
            ("[unterminated", 1),
            ("- not-a-mapping\n", 1),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflows = root / ".github/workflows"
            workflows.mkdir(parents=True)
            for document, expected in documents:
                with self.subTest(document=document):
                    (workflows / "ci.yml").write_text(document, encoding="utf-8")
                    self.assertEqual(validate.validate_workflow_workflows(root)[0], expected)

    def test_missing_yaml_dependency_is_explicitly_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflows = root / ".github/workflows"
            workflows.mkdir(parents=True)
            (workflows / "ci.yml").write_text("on: [push]\njobs: {}\n", encoding="utf-8")
            with patch.dict(sys.modules, {"yaml": None}):
                code, output = validate.validate_workflow_workflows(root)
            self.assertEqual(code, 127)
            self.assertIn("SKIPPED/blocked", output)


class PowerShellSyntaxTests(unittest.TestCase):
    def test_parser_accepts_valid_script_and_rejects_invalid_script(self):
        executable = shutil.which("pwsh")
        if not executable:
            self.skipTest("PowerShell 7 is unavailable on this host")
        with tempfile.TemporaryDirectory() as directory:
            script_dir = Path(directory) / "directory with spaces"
            script_dir.mkdir()
            script = script_dir / "test.ps1"
            script.write_text("param([string]$Name)\nWrite-Output $Name\n", encoding="utf-8")
            valid = subprocess.run(
                validate.powershell_syntax_command(executable, script),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
            script.write_text("if ($true) {\n", encoding="utf-8")
            invalid = subprocess.run(
                validate.powershell_syntax_command(executable, script),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(invalid.returncode, 0)


if __name__ == "__main__":
    unittest.main()
