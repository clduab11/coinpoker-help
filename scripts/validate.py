#!/usr/bin/env python3
"""Run Windows-first automated checks with separate local evidence."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


def validate_workflow_workflows(root):
    """Parse every GitHub Actions workflow and require a `jobs` key and a trigger.

    PyYAML follows YAML 1.1, so an unquoted `on:` mapping key resolves to the
    boolean True on load. Accept that spelled trigger as equivalent to "on"
    rather than reporting a false negative.
    """
    files = sorted([p for p in (root / ".github" / "workflows").glob("*") if p.suffix in (".yml", ".yaml")])
    if not files:
        return 127, "no workflow files found under .github/workflows"
    lines = []
    failures = 0
    blocked = False
    try:
        import yaml
    except ImportError:
        return 127, "PyYAML is not importable; workflow YAML validation is SKIPPED/blocked"
    for path in files:
        name = path.relative_to(root).as_posix()
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as error:  # noqa: BLE001 - surface any parser failure as a failure
            lines.append(f"INVALID {name}: {error}")
            failures += 1
            continue
        if not isinstance(document, dict):
            lines.append(f"INVALID {name}: top level is not a mapping")
            failures += 1
            continue
        trigger_keys = [key for key in document if key == "on" or key is True]
        if len(trigger_keys) != 1:
            lines.append(f"INVALID {name}: missing a trigger (`on:`) key")
            failures += 1
        if "jobs" not in document or not isinstance(document.get("jobs"), dict) or not document.get("jobs"):
            lines.append(f"INVALID {name}: missing a non-empty `jobs` mapping")
            failures += 1
        if trigger_keys and "jobs" in document:
            lines.append(f"OK {name}: jobs + trigger {trigger_keys[0]!r} present")
    if blocked:
        return 127, "\n".join(lines)
    return (1 if failures else 0), "\n".join(lines)


def blocked_record(name, reason):
    """Record an explicitly skipped check so the gap is visible in the report.

    Advisory records carry `exit_code: 127` for visibility but are excluded from
    the final exit computation: an unavailable optional tool (PowerShell, PyYAML)
    is not a failing check. Only genuine failures decide the exit code.
    """
    return {"check": name, "command": [], "exit_code": 127, "status": "blocked", "advisory": True, "reason": reason}


def powershell_syntax_command(executable, script):
    """Parse a script without executing it or interpolating its path into code."""
    parser = (
        "$tokens = $null; $parseErrors = $null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        "$args[0], [ref]$tokens, [ref]$parseErrors) | Out-Null; "
        "if ($parseErrors.Count -gt 0) { "
        "foreach ($item in $parseErrors) { [Console]::Error.WriteLine($item.ToString()) }; "
        "exit 1 }"
    )
    return [executable, "-NoProfile", "-NonInteractive", "-CommandWithArgs", parser, str(script)]


def run_command(root, out, name, command):
    print("RUN", name, ":", " ".join(command), flush=True)
    start = time.monotonic()
    timeout = 900 if name == "test" else 240
    try:
        process = subprocess.run(command, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        output, code = process.stdout, process.returncode
    except subprocess.TimeoutExpired:
        output, code = f"TIMED OUT after {timeout} seconds; not silently retried", 124
    except OSError as error:
        output, code = str(error), 127
    (out / (name + ".log")).write_text(output, encoding="utf-8")
    passed = sum(int(n) for n in re.findall(r"test result: ok\. (\d+) passed", output)) if name == "test" else None
    result = {"check": name, "command": command, "exit_code": code, "seconds": round(time.monotonic() - start, 3), "rust_tests_passed": passed}
    print(json.dumps(result), flush=True)
    if code:
        print(output, flush=True)
    return result


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / ".local" / "validation"
    out.mkdir(parents=True, exist_ok=True)
    commands = [
        ("fmt", ["cargo", "fmt", "--all", "--", "--check"]),
        ("check", ["cargo", "check", "--workspace", "--all-targets", "--all-features", "--locked"]),
        ("test", ["cargo", "test", "--workspace", "--all-targets", "--all-features", "--locked"]),
        ("clippy", ["cargo", "clippy", "--workspace", "--all-targets", "--all-features", "--locked", "--", "-D", "warnings"]),
    ]
    powershell = shutil.which("pwsh")
    powershell_files = sorted(root.glob("*.ps1")) + sorted((root / "scripts").glob("*.ps1"))
    if powershell:
        commands += [
            (p.stem + "-syntax", powershell_syntax_command(powershell, p))
            for p in powershell_files
        ]
    commands += [
        ("python-tests", [sys.executable, "-m", "unittest", "discover", "-s", "scripts/tests", "-v"]),
        ("synthetic-evaluation", ["cargo", "run", "--locked", "--bin", "coinpoker", "--", "--evaluate", "fixtures/synthetic/manifest.json"]),
    ]
    results = []
    for name, command in commands:
        results.append(run_command(root, out, name, command))

    workflow_code, workflow_output = validate_workflow_workflows(root)
    (out / "workflow-yaml.log").write_text(workflow_output + "\n", encoding="utf-8")
    print("RUN workflow-yaml", flush=True)
    if workflow_code == 127:
        results.append(blocked_record("workflow-yaml", workflow_output))
        print(json.dumps(results[-1]), flush=True)
    else:
        results.append({"check": "workflow-yaml", "command": [], "exit_code": workflow_code, "status": "failed" if workflow_code else "passed"})
        print(json.dumps(results[-1]), flush=True)
        if workflow_code:
            print(workflow_output, flush=True)

    if not powershell:
        results.append(blocked_record("powershell-syntax", "PowerShell 7 (pwsh) not found on PATH; script parsing skipped"))
        print(json.dumps(results[-1]), flush=True)

    report = {
        "format": 1,
        "checks": results,
        "powershell_available": bool(powershell),
        "physical_windows_acceptance": False,
    }
    advisory = [r["check"] for r in results if r.get("advisory")]
    failed = [r["check"] for r in results if r["exit_code"] != 0 and not r.get("advisory")]
    if advisory:
        print("ADVISORY (skipped, not counted as failure): " + ", ".join(advisory), flush=True)
    if failed:
        print("FAILED: " + ", ".join(failed), flush=True)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Report: .local/validation/report.json")
    return int(bool(failed))


if __name__ == "__main__":
    sys.exit(main())
