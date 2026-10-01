"""Integration checks for the validation runner's PowerShell parser gate."""

import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "validate", Path(__file__).resolve().parents[1] / "validate.py"
)
validate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate)


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
