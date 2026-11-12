"""Bounded, stdlib-only private build identities. No model loading or discovery."""

import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import tempfile
import time

MAX_IDENTITY = 256 * 1024
MAX_SOURCE = 4 * 1024 * 1024
MAX_FILES = 512
MAX_SOURCE_TOTAL = 16 * 1024 * 1024
SOURCE_FILES = (
    "Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "bin/Cargo.toml",
    "bin/main.rs", "bin/manual_capture.rs", "bin/manual_inference.rs",
    "crates/ingest/Cargo.toml", "crates/ingest/src/lib.rs",
    "scripts/laya-server.py", "scripts/laya_capture.py", "scripts/laya_provenance.py",
    "scripts/laya_attach.py", "scripts/laya_dashboard.py", "scripts/laya_visual.py",
    "scripts/laya_server_validation.py", "scripts/laya_prep.py", "scripts/laya_board.py",
    "scripts/laya_numeric.py", "scripts/laya_context.py", "scripts/laya_actions.py",
    "scripts/laya_evidence.py", "scripts/laya_showdown.py", "scripts/laya_ocr.ps1",
    "scripts/start-vlm.ps1", "scripts/laya-pins.json",
    "scripts/dashboard/index.html", "scripts/dashboard/app.js", "scripts/dashboard/styles.css",
    "scripts/dashboard/reference.json",
    "crates/ingest/assets/laya/question-set.json", "crates/ingest/assets/laya/regions.json",
)
CPU_FILES = (
    ".local/laya/dataset/exemplars.json",
    ".local/captures/20261009T170508Z-laya-train/derived/exemplars.npz",
    ".local/laya/board-pixel-bank-20261014.json",
    ".local/laya/datasets/observing-20261010-v2-staging/human-review-20261010/labels.draft.json",
)
PACKAGES = ("laya", "torch", "torchvision", "transformers", "safetensors",
            "huggingface_hub", "numpy", "pillow", "PyYAML")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def file_identity(path, *, maximum=MAX_SOURCE):
    path = Path(path).absolute()
    result = {"path": str(path), "state": "unknown", "sha256": None}
    try:
        # Refuse redirects and nonregular files before opening (including FIFOs).
        if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)()
               for p in (path, *path.parents)):
            result["reason"] = "redirected"
            return result
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            result["reason"] = "not-regular-or-size-bound"
            return result
        h, size = hashlib.sha256(), 0
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(min(1024 * 1024, maximum + 1 - size)), b""):
                size += len(block)
                if size > maximum:
                    break
                h.update(block)
            after = os.fstat(stream.fileno())
        final = path.stat()
        # On Windows stat(path).ctime is creation time while fstat(handle).ctime
        # can be change time. Compare like-for-like rather than rejecting every file.
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if (size > maximum or size != before.st_size or identity(before) != identity(after)
                or identity(after) != identity(final) or before.st_ctime_ns != final.st_ctime_ns):
            result["reason"] = "changed-during-read"
            return result
        result.update(state="known", sha256=h.hexdigest(), size_bytes=size,
                      mtime_ns=after.st_mtime_ns)
    except (OSError, ValueError, RuntimeError):
        result["reason"] = "unavailable"
    return result


def _git(root, args, maximum):
    # File-backed stdout bounds memory even when git produces unexpectedly large output.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(["git", "--no-optional-locks", "-C", str(root), *args],
                                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                                timeout=3, shell=False)
        output.seek(0)
        raw = output.read(maximum + 1)
    return result.returncode, raw


def git_identity(root):
    result = {"sha": None, "dirty": None, "state": "unknown"}
    try:
        # A synthetic root must not inherit the enclosing checkout's identity.
        if not (Path(root) / ".git").exists():
            return result
        code, raw = _git(root, ["rev-parse", "--verify", "HEAD"], 128)
        sha = raw.decode("ascii").strip()
        if code or not re.fullmatch(r"[0-9a-f]{40,64}", sha):
            return result
        result["sha"] = sha
        code, raw = _git(root, ["status", "--porcelain=v1", "--untracked-files=normal"], 64 * 1024)
        if code == 0:
            result.update(dirty=bool(raw), state="known")
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        pass
    return result


def runtime_identity():
    packages = {}
    for name in PACKAGES:
        try:
            dist = metadata.distribution(name)
            entry = {"version": dist.version, "state": "known"}
            if name == "laya":
                # Never retain a direct_url URL: it may contain credentials.
                directory = getattr(dist, "_path", None)
                direct = {}
                if directory is not None:
                    path = Path(directory) / "direct_url.json"
                    if file_identity(path)["state"] == "known":
                        with path.open("rb") as stream:
                            direct = json.loads(stream.read(MAX_SOURCE + 1))
                vcs = direct.get("vcs_info") if isinstance(direct, dict) else None
                commit = vcs.get("commit_id") if isinstance(vcs, dict) else None
                entry["vcs_commit"] = commit if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40,64}", commit) else None
            packages[name] = entry
        except (OSError, ValueError, TypeError, metadata.PackageNotFoundError):
            packages[name] = {"version": None, "state": "unknown"}
    # Resolve the process-owned interpreter, not arbitrary redirected evidence.
    try:
        executable = Path(sys.executable).resolve(strict=True)
    except (OSError, RuntimeError):
        executable = Path(sys.executable)
    python = {"version": platform.python_version(), "implementation": platform.python_implementation(),
              "executable": file_identity(executable, maximum=128 * 1024 * 1024),
              "prefix": sys.prefix, "base_prefix": sys.base_prefix}
    return {"python": python, "packages": packages,
            "complete": python["executable"]["state"] == "known"
                and all(row["state"] == "known" for row in packages.values())
                and packages["laya"].get("vcs_commit") is not None}


def build_identity(root, *, executable=None):
    root = Path(root).resolve()
    names = set(SOURCE_FILES)
    # Only runtime source roots. Never walk .local, models, graphs, PDFs or tests.
    for pattern in ("bin/*.rs", "crates/*/Cargo.toml", "crates/*/src/**/*.rs"):
        for path in root.glob(pattern):
            if path.name.endswith("_tests.rs") or "tests" in path.relative_to(root).parts:
                continue
            names.add(path.relative_to(root).as_posix())
            if len(names) > MAX_FILES:
                break
    files, remaining = {}, MAX_SOURCE_TOTAL
    for name in sorted(names)[:MAX_FILES]:
        files[name] = file_identity(root / name, maximum=min(MAX_SOURCE, remaining))
        remaining -= files[name].get("size_bytes", 0)
    result = {"git": git_identity(root), "files": files, "manifest_sha256": digest(files),
              "coverage": "explicit Python/browser/config files and bounded native runtime source roots",
              "native_build_link": "unknown; executable hash is not proof it was built from these sources",
              "runtime": runtime_identity(), "complete": len(names) <= MAX_FILES
              and all(row["state"] == "known" for row in files.values())}
    if executable is not None:
        result["executable"] = file_identity(executable, maximum=256 * 1024 * 1024)
        result["complete"] &= result["executable"]["state"] == "known"
    result["complete"] &= result["git"]["state"] == "known"
    result["complete"] &= result["runtime"]["python"]["executable"]["state"] == "known"
    return result


def model_identity(pins, root, snapshot, verified_files=()):
    """Pins are expectations only; actual digests come exclusively from verify()."""
    verified = {str(Path(row["path"]).absolute()): row for row in verified_files}
    model = pins.get("model", {})
    ft = model.get("finetuned") or {}
    files, bounded = [], True
    for kind, base, entries in (("base", Path(snapshot), model.get("files", [])),
                                ("checkpoint", Path(root) / ft.get("path", ""), ft.get("files", []))):
        bounded &= len(entries) <= MAX_FILES
        for entry in entries[:MAX_FILES]:
            path = str((base / entry["path"]).absolute())
            files.append({"kind": kind, "path": path, "expected_sha256": entry.get("sha256"),
                          "expected_size_bytes": entry.get("size"),
                          "actual": verified.get(path, {"state": "unknown", "sha256": None})})
    calibration = {}
    for key in ("calibration_file", "acceptance_file"):
        path = str((Path(root) / ft.get("path", "") / ft[key]).absolute()) if ft.get(key) else None
        calibration[key] = next((row for row in files if row["kind"] == "checkpoint" and row["path"] == path),
                                {"state": "unknown", "sha256": None})
    return {"repository": model.get("repository"), "revision": model.get("revision"),
            "checkpoint": ft.get("path"), "calibration_file": ft.get("calibration_file"),
            "acceptance_file": ft.get("acceptance_file"), "calibration": calibration, "files": files,
            "complete": bool(files) and bounded and all(row["actual"].get("state") == "verified"
                and row["actual"].get("sha256") == row["expected_sha256"]
                and row["actual"].get("size_bytes") == row["expected_size_bytes"] for row in files)
                and all(row.get("actual", {}).get("state") == "verified" for row in calibration.values())}


def service_identity(root, instance_id, pins, snapshot, *, argv, options):
    runtime = pins.get("runtime", {})
    return {"version": 1, "instance_id": instance_id, "pid": os.getpid(),
            "started_at_unix_ms": time.time_ns() // 1_000_000,
            "argv": list(argv), "options": options, "build": build_identity(root),
            "runtime_expected": {"python": runtime.get("python"), "packages": runtime.get("packages"),
                                 "laya": {key: runtime.get("laya", {}).get(key)
                                          for key in ("commit", "package_version")}},
            "pins_sha256": digest(pins), "model": model_identity(pins, root, snapshot),
            "complete": False}


def admission_identity(root, executable, approval, *, service=None, selector=None):
    build = build_identity(root, executable=executable)
    cpu = {name: file_identity(Path(root) / name, maximum=64 * 1024 * 1024) for name in CPU_FILES}
    selection = (file_identity(Path(root) / selector, maximum=16 * 1024) if selector is not None
                 else {"kind": "exact-manual-source", "state": "known", "sha256": digest(approval["source"])})
    if selector is None and approval.get("source_policy", "manual") != "manual":
        selection = {"state": "unknown", "sha256": None, "reason": "selector-not-supplied"}
    inference = approval["mode"] == "inference-enabled"
    matched = isinstance(service, dict) and service.get("instance_id") == approval.get("service_instance_id")
    return {"version": 1, "admitted_at_unix_ms": time.time_ns() // 1_000_000,
            "build": build, "selector": selection, "cpu_assets": cpu,
            "service": service if matched else {"instance_id": approval.get("service_instance_id"), "state": "unknown"},
            "complete": bool(build["complete"] and selection["state"] == "known"
                             and (not inference or matched and service.get("complete") is True
                                  and all(row["state"] == "known" for row in cpu.values())))}


class DiagnosticCounter:
    """Constant-space archival loss evidence; intervals use supervisor receipt time."""

    def __init__(self):
        self.value = {"bytes_seen": 0, "bytes_archived": 0, "bytes_dropped": 0,
                      "bytes_unaccounted": 0, "accounting_complete": True, "write_failed": False,
                      "truncated": False, "first_dropped_at_unix_ms": None,
                      "last_dropped_at_unix_ms": None,
                      "loss_interval_basis": "archival observation-time envelope, not producer timestamps"}

    def account(self, seen, archived):
        value = dict(self.value)
        value["bytes_seen"] += seen
        value["bytes_archived"] += archived
        dropped = seen - archived
        value["bytes_dropped"] += dropped
        if dropped:
            now = time.time_ns() // 1_000_000
            value["truncated"] = True
            if value["first_dropped_at_unix_ms"] is None:
                value["first_dropped_at_unix_ms"] = now
            value["last_dropped_at_unix_ms"] = now
        self.value.update(value)

    def fail_write(self, attempted):
        self.value.update(accounting_complete=False, write_failed=True,
                          bytes_unaccounted=self.value["bytes_unaccounted"] + attempted)
