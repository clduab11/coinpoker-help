#!/usr/bin/env python3
"""One-shot manual capture/diagnostic CLI. No model imports or auto-attach.

list prints metadata only. start requires --pid and --hwnd plus fresh interactive
confirmation and the exact assertion 'I am seated and ready'. stop/mark require
the printed opaque session ID. Markers are drafts, never accepted corrections.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import sys
import time
import uuid
import urllib.request

import laya_attach as attach

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(".local/laya/manual-capture")
# Retained only to recognize existing receipts; new sessions do not assert seating.
ASSERTION = "I am seated and ready"
INFERENCE_ASSERTION = "USE INSTALLED IT1 FOR THIS SESSION"
AUTOMATIC_ASSERTION = "AUTHORIZE BOUNDED AUTOMATIC OBSERVATION"
SUSTAINED_ASSERTION = "AUTHORIZE SUSTAINED SAME-SOURCE OBSERVATION"
AUTOMATIC_POLICIES = {"automatic-bounded", "automatic-sustained"}
SOURCE_POLICIES = {"manual", *AUTOMATIC_POLICIES}
MODES = {"capture-only", "inference-enabled"}
MAX_SECONDS = 600
MAX_FRAMES = 1200
TARGET = 20
MAX_RECORD = 16 * 1024
MAX_LOG = 20 * 1024 * 1024
MAX_FEED_RECORD = 256 * 1024
MAX_BYTES = 1024 * 1024 * 1024
MAX_COUNTER = 2**53 - 1
EVIDENCE_REASONS = {"duration-limit", "frame-limit", "disk-limit"}
FEED_EVENTS = {"configuration", "status", "capture_health", "partial_observation", "observation",
               "observation_invalidated", "partial_observation_invalidated", "perception_diagnostics",
               "history", "table", "clear", "discarded", "visual_frame"}
REASONS = {"operator-stop", "duration-limit", "frame-limit", "disk-limit", "recorder-failure",
           "source-unavailable", "source-changed", "capture-failed", "child-exited", "child-failed",
           "native-stalled", "receipt-invalid", "log-limit", "supervisor-error", "status-stale",
            "child-stop-unconfirmed", "inference-failed", "publication-failed", "model-not-ready", "feed-failed",
            "table-activity-unconfirmed", "automatic-discovery-timeout"}
STATUSES = {"idle", "capturing", "stopped", "failed", "interrupted"}


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def now_ms():
    return time.time_ns() // 1_000_000


def private_path(relative, *, root=ROOT):
    root = Path(root).resolve()
    path = root / relative
    if not path.is_absolute() or not path.is_relative_to(root / ".local"):
        raise ValueError("private-path-required")
    for part in (path, *path.parents):
        if part.exists() and (part.is_symlink() or getattr(part, "is_junction", lambda: False)()):
            raise ValueError("redirected-private-path")
    if path.resolve() != path:
        raise ValueError("redirected-private-path")
    return path


def session_path(session_id, *, root=ROOT):
    if not isinstance(session_id, str) or not re.fullmatch(r"[0-9a-f]{32}", session_id):
        raise ValueError("invalid-session-id")
    return private_path(BASE / session_id, root=root)


def read_json(path, maximum=MAX_RECORD):
    # CPython's ordinary Windows file open excludes FILE_SHARE_DELETE. Frequent
    # dashboard readers can therefore prevent atomic receipt publication. Read
    # a stable file handle while allowing the publisher to replace its pathname.
    for attempt in range(3):
        try:
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes
                import msvcrt
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                create = kernel.CreateFileW
                create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
                create.restype = wintypes.HANDLE
                close = kernel.CloseHandle
                close.argtypes, close.restype = [wintypes.HANDLE], wintypes.BOOL
                handle = create(str(path), 0x80000000, 7, None, 3, 0x80, None)
                if handle == wintypes.HANDLE(-1).value:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
                except Exception:
                    close(handle)
                    raise
                with os.fdopen(descriptor, "rb") as stream:
                    raw = stream.read(maximum + 1)
            else:
                with path.open("rb") as stream:
                    raw = stream.read(maximum + 1)
            break
        except (PermissionError, FileNotFoundError):
            if attempt == 2:
                raise
            time.sleep(0.01)
    if len(raw) > maximum:
        raise ValueError("receipt-too-large")
    value = attach._json(raw, "window-list-invalid")
    if not isinstance(value, dict):
        raise ValueError("receipt-object-required")
    return value


def write_json(path, value, *, exclusive=False):
    raw = (json.dumps(value, allow_nan=False, ensure_ascii=True, sort_keys=True) + "\n").encode()
    target = path if exclusive else path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with target.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if not exclusive:
        # Windows readers/antivirus can briefly deny atomic rename. This retries
        # publication only, never capture, inference or session startup.
        try:
            for attempt in range(5):
                try:
                    if os.name == "nt" and path.exists():
                        import ctypes
                        from ctypes import wintypes
                        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                        replace = kernel.ReplaceFileW
                        replace.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                            wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID]
                        replace.restype = wintypes.BOOL
                        if not replace(str(path), str(target), None, 0, None, None):
                            raise ctypes.WinError(ctypes.get_last_error())
                    else:
                        os.replace(target, path)
                    break
                except OSError as error:
                    if (attempt == 4 or not target.exists() or not
                            (isinstance(error, PermissionError) or getattr(error, "winerror", None) in (32, 33, 1175))):
                        raise
                    threading.Event().wait(0.01)
        finally:
            target.unlink(missing_ok=True)


def confirm_source(pid, hwnd, *, root=ROOT, input_fn=input, output=print, mode="capture-only"):
    if mode not in MODES:
        raise ValueError("invalid-mode")
    started = time.monotonic()
    chosen = attach.select_exact(attach.list_windows(root=root), pid, hwnd)
    challenge = "CAPTURE %d %s %s" % (chosen.process_id, chosen.hwnd, uuid.uuid4().hex[:12])
    output("Exact source (private metadata): " + json.dumps(chosen.private_record(), ensure_ascii=True))
    output("Mode: %s. Source confirmation does not establish recognition accuracy or hero identity." % mode)
    if input_fn("Type %s to confirm this exact window: " % challenge) != challenge:
        raise ValueError("exact-source-confirmation-required")
    current = attach.select_exact(attach.list_windows(root=root), pid, hwnd)
    if time.monotonic() - started > 30:
        raise ValueError("confirmation-expired")
    if not attach.same_exact_source(chosen, current):
        raise ValueError("source-changed-new-approval-required")
    return current, now_ms()


def inference_service():
    """Status only, explicitly invoked by inference mode; never loads a model."""
    # No redirects/proxies: another service cannot stand in for the canonical one.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open("http://127.0.0.1:18090/api/state", timeout=2) as response:
        raw = response.read(128 * 1024 + 1)
    if len(raw) > 128 * 1024:
        raise ValueError("invalid-service-status")
    value = attach._json(raw, "invalid-service-status")
    server = value.get("server") if isinstance(value, dict) else None
    if (not isinstance(server, dict) or server.get("inference_enabled") is not True
            or server.get("manual_feed_version") != 1 or server.get("alias") != "coinpoker-laya-vision"
            or not isinstance(server.get("instance_id"), str)
            or not re.fullmatch(r"[0-9a-f]{32}", server["instance_id"])):
        raise ValueError("approved-inference-service-required")
    return server


def approve_inference(*, input_fn=input, output=print):
    output("Model selection: installed pinned it1. Experimental analysis requires complete, current inputs.")
    if input_fn("Type '%s': " % INFERENCE_ASSERTION) != INFERENCE_ASSERTION:
        raise ValueError("inference-approval-required")
    deadline = time.monotonic() + 120
    output("Waiting at most 120s for the separately enabled model; NO source selected or capture budget started. Ctrl+C cancels.")
    while True:
        server = inference_service()
        if server.get("model_state") == "ready" and server.get("acceptance_floors_loaded") is True:
            return {"inference_assertion": INFERENCE_ASSERTION, "service_instance_id": server["instance_id"]}
        if server.get("model_state") != "loading" or time.monotonic() >= deadline:
            raise ValueError("model-not-ready")
        time.sleep(0.2)


def experimental_session_approved(session_id, instance_id, *, root=ROOT):
    """Additional private opt-in only; ordinary feed authorization is still required."""
    try:
        path = session_path(session_id, root=root)
        approval = read_json(path / "approval.json")
        current = public_snapshot(root=root, session_id=session_id)
        return (approval.get("experimental_bet_action") is True
                and current.get("experimental_bet_action") is True
                and current.get("status") == "capturing"
                and approval.get("source_policy") == "automatic-bounded"
                and approval.get("automatic_assertion") == AUTOMATIC_ASSERTION
                and approval.get("mode") == "inference-enabled"
                and approval.get("inference_assertion") == INFERENCE_ASSERTION
                and approval.get("service_instance_id") == instance_id)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _markers(path):
    rows = []
    directory = path / "markers"
    if not directory.exists():
        return rows
    if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)():
        raise ValueError("redirected-markers")
    for file in directory.glob("*.json"):
        if len(rows) >= 1000 or file.is_symlink():
            raise ValueError("marker-bound")
        rows.append(read_json(file))
    return rows


def opportunity_count(path):
    ids, hashes = set(), set()
    for marker in _markers(path):
        if (marker.get("kind") != "opportunity" or marker.get("labels") != "DRAFT"
                or marker.get("human_review") != "PENDING"):
            continue
        identity, digest = marker.get("opportunity_id"), marker.get("sha256")
        if (not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity)
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("invalid-marker")
        if identity not in ids and digest not in hashes:
            ids.add(identity)
            hashes.add(digest)
    return len(ids)


def default_snapshot():
    return {"mode": "capture-only", "status": "idle", "stop_reason": None,
            "source_policy": "manual", "activity_state": "idle",
            "session_id": None, "elapsed_ms": 0, "max_duration_ms": MAX_SECONDS * 1000,
            "max_frames": MAX_FRAMES, "remaining_ms": MAX_SECONDS * 1000,
            "recorded_frames": 0, "recorded_bytes": 0, "capture_failures": 0,
            "gap_count": 0, "max_gap_ms": None, "estimated_missed_samples": 0,
            "distinct_opportunities": 0, "target_opportunities": TARGET, "opportunity_deficit": TARGET,
            "labels": "DRAFT", "human_review": "PENDING", "suggestions_enabled": False,
            "inference_enabled": False, "experimental_bet_action": False,
            "updated_at_unix_ms": None}


def evidence_snapshot(value):
    fields = {"status", "stop_reason", "elapsed_ms", "max_duration_ms", "max_frames",
              "max_bytes", "recorded_frames", "recorded_bytes"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("invalid-evidence")
    for key, maximum in (("max_duration_ms", MAX_SECONDS * 1000), ("max_frames", MAX_FRAMES),
                         ("max_bytes", MAX_BYTES)):
        if type(value[key]) is not int or not 1 <= value[key] <= maximum:
            raise ValueError("invalid-evidence")
    if value["max_bytes"] != MAX_BYTES:
        raise ValueError("invalid-evidence")
    for key, limit in (("elapsed_ms", "max_duration_ms"), ("recorded_frames", "max_frames"),
                       ("recorded_bytes", "max_bytes")):
        if type(value[key]) is not int or not 0 <= value[key] <= value[limit]:
            raise ValueError("invalid-evidence")
    reason = value["stop_reason"]
    if value["status"] == "active":
        if reason is not None or any(value[key] >= value[limit] for key, limit in
                (("elapsed_ms", "max_duration_ms"), ("recorded_frames", "max_frames"), ("recorded_bytes", "max_bytes"))):
            raise ValueError("invalid-evidence")
    elif value["status"] != "ended" or reason not in EVIDENCE_REASONS:
        raise ValueError("invalid-evidence")
    elif (reason == "duration-limit" and value["elapsed_ms"] != value["max_duration_ms"]
          or reason == "frame-limit" and value["recorded_frames"] != value["max_frames"]):
        raise ValueError("invalid-evidence")
    return dict(value)


def public_snapshot(*, root=ROOT, session_id=None, current_ms=None):
    """Public projection. Paths, HWNDs, titles, PNGs and draft prose stay private."""
    result = default_snapshot()
    try:
        if session_id is None:
            pointer = private_path(BASE / "current.json", root=root)
            if not pointer.exists():
                return result
            session_id = read_json(pointer)["session_id"]
        path = session_path(session_id, root=root)
        value = read_json(path / "status.json")
        if value.get("mode") not in MODES or value.get("status") not in STATUSES:
            raise ValueError("invalid-status")
        inference = value["mode"] == "inference-enabled"
        if value.get("inference_enabled") is not inference:
            raise ValueError("invalid-status")
        result.update(session_id=session_id, status=value["status"], mode=value["mode"], inference_enabled=inference)
        policy = value.get("source_policy", "manual")
        sustained = policy == "automatic-sustained"
        activity = value["activity_state"] if policy in AUTOMATIC_POLICIES else value.get("activity_state", "active")
        if policy not in SOURCE_POLICIES or activity not in {"idle", "verifying", "active"}:
            raise ValueError("invalid-status")
        experiment = value.get("experimental_bet_action", False)
        if type(experiment) is not bool or experiment and (not inference or policy != "automatic-bounded"):
            raise ValueError("invalid-status")
        result.update(source_policy=policy, activity_state=activity, experimental_bet_action=experiment)
        if sustained:
            if (not inference or experiment or type(value.get("receipt_version")) is not int
                    or value["receipt_version"] != 2 or any(key not in value or value[key] is not None
                    for key in ("max_duration_ms", "max_frames", "remaining_ms"))
                    or value.get("experimental_bet_action") is not False
                    or value["status"] in {"idle", "capturing"} and value.get("stop_reason") is not None
                    or value["status"] in {"stopped", "failed", "interrupted"} and value.get("stop_reason") is None):
                raise ValueError("invalid-status")
            evidence = evidence_snapshot(value.get("evidence"))
            if any(value.get(key) != evidence[key] for key in ("recorded_frames", "recorded_bytes")):
                raise ValueError("invalid-status")
            result.update(receipt_version=2, evidence=evidence, max_duration_ms=None, max_frames=None, remaining_ms=None)
        bounds = [("elapsed_ms", MAX_COUNTER if sustained else 650_000)]
        if not sustained:
            bounds.extend((("max_duration_ms", 600_000), ("max_frames", 1200)))
        for key, maximum in (*bounds, ("recorded_frames", 1200),
                             ("recorded_bytes", 1_073_741_824), ("capture_failures", 10_000),
                             ("gap_count", 1200),
                             ("estimated_missed_samples", 10_000), ("updated_at_unix_ms", 10**15)):
            item = value.get(key)
            if type(item) is not int or not 0 <= item <= maximum:
                raise ValueError("invalid-status")
            result[key] = item
        gap = value.get("max_gap_ms")
        if gap is not None and (type(gap) is not int or not 0 <= gap <= (MAX_COUNTER if sustained else 650_000)):
            raise ValueError("invalid-status")
        result["max_gap_ms"] = gap
        if not sustained and (not result["max_duration_ms"] or not result["max_frames"]):
            raise ValueError("invalid-status")
        reason = value.get("stop_reason")
        if reason is not None and reason not in REASONS:
            raise ValueError("invalid-status")
        result["stop_reason"] = reason
        current_ms = now_ms() if current_ms is None else current_ms
        age = current_ms - result["updated_at_unix_ms"]
        # Sustained anti-replay compares the owner's monotonic sample, not UTC
        # interpolation: Windows monotonic ticks can be coarser than wall time.
        if result["status"] == "capturing":
            if age < 0 or age > 3000:
                result.update(status="interrupted", stop_reason="status-stale")
            elif not sustained:
                result["elapsed_ms"] += age
        if not sustained:
            result["remaining_ms"] = max(0, result["max_duration_ms"] - result["elapsed_ms"])
        failure = private_path(path / "failure.json", root=root)
        if failure.exists():
            failure_reason = read_json(failure).get("reason")
            if failure_reason not in {"feed-failed", "model-not-ready"}:
                raise ValueError("invalid-failure")
            result.update(status="failed", stop_reason=failure_reason)
        if result["status"] == "capturing":
            if private_path(path / "STOP", root=root).exists():
                result.update(status="stopped", stop_reason="operator-stop")
            elif not sustained and not result["remaining_ms"]:
                result.update(status="stopped", stop_reason="duration-limit")
            elif not sustained and result["recorded_frames"] >= result["max_frames"]:
                result.update(status="stopped", stop_reason="frame-limit")
        count = opportunity_count(path)
        result.update(distinct_opportunities=count, opportunity_deficit=max(0, TARGET - count))
        if result["status"] != "capturing":
            result["activity_state"] = "idle"
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        result = default_snapshot()
        result.update(status="failed", stop_reason="receipt-invalid", remaining_ms=0)
    return result


def _native_record(row, status):
    sustained = status.get("source_policy") == "automatic-sustained"
    if (not isinstance(row, dict) or row.get("event") != "manual_capture"
            or type(row.get("version")) is not int or row["version"] != (2 if sustained else 1)
            or row.get("mode") != status["mode"]):
        raise ValueError("invalid-native-receipt")
    if row.get("source_policy", "manual") != status.get("source_policy", "manual"):
        raise ValueError("invalid-native-policy")
    activity = row["activity_state"] if status.get("source_policy") in AUTOMATIC_POLICIES else row.get("activity_state", "active")
    if activity not in {"idle", "verifying", "active"}:
        raise ValueError("invalid-native-activity")
    status["activity_state"] = activity
    recording = row["recording"]
    maximum_frames = status["evidence"]["max_frames"] if sustained else status["max_frames"]
    for key, maximum in (("recorded_frames", maximum_frames), ("recorded_bytes", MAX_BYTES)):
        item = recording[key]
        if type(item) is not int or not status[key] <= item <= maximum:
            raise ValueError("invalid-native-counter")
        status[key] = item
    if sustained:
        previous = status["evidence"]
        elapsed = row.get("elapsed_ms")
        if (type(elapsed) is not int or not status.get("_native_elapsed_ms", 0) <= elapsed <= MAX_COUNTER
                or "recording_end_reason" not in row):
            raise ValueError("invalid-native-evidence")
        status["_native_elapsed_ms"] = elapsed
        ended = row["recording_end_reason"]
        recording_elapsed = (previous["elapsed_ms"] if previous["status"] == "ended"
                             or row.get("stop_reason") is not None and ended is None
                             else min(elapsed, previous["max_duration_ms"]))
        evidence = evidence_snapshot({**previous,
            "status": "ended" if ended is not None else "active",
            "stop_reason": ended, "elapsed_ms": recording_elapsed,
            "recorded_frames": status["recorded_frames"], "recorded_bytes": status["recorded_bytes"]})
        if (evidence["elapsed_ms"] < previous["elapsed_ms"]
                or previous["status"] == "ended" and evidence != previous):
            raise ValueError("invalid-native-evidence")
        status["evidence"] = evidence
    failures = row.get("capture_failures")
    if type(failures) is not int or not 0 <= failures <= 10_000:
        raise ValueError("invalid-native-counter")
    status["capture_failures"] = failures
    reason = row.get("stop_reason")
    if reason is not None and reason not in REASONS:
        raise ValueError("invalid-native-reason")
    return reason


class _PipeReader:
    """Bound live transport independently of its optional diagnostic file."""

    def __init__(self, stream):
        if not callable(getattr(stream, "read", None)):
            raise ValueError("invalid-pipe")
        self.stream = stream
        self.buffer = bytearray()
        self.available = threading.Condition()
        self.eof, self.failed = threading.Event(), threading.Event()
        self.failure_reason = None
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            while True:
                block = self.stream.read(64 * 1024)
                if not isinstance(block, bytes) or len(block) > 64 * 1024:
                    self.failure_reason = "invalid-pipe-block"
                    raise ValueError("invalid-pipe-block")
                if not block:
                    self.eof.set()
                    return
                with self.available:
                    # Raw pipe reads may be tiny fragments of one JSON record.
                    # Bound unread bytes, not the number of OS read completions.
                    if not self.available.wait_for(
                            lambda: len(self.buffer) + len(block) <= 1024 * 1024, timeout=0.2):
                        self.failure_reason = "pipe-backlog"
                        raise ValueError("pipe-backlog")
                    self.buffer.extend(block)
        except (OSError, ValueError, TypeError):
            self.failure_reason = self.failure_reason or "pipe-read-failed"
            self.failed.set()

    def read(self):
        with self.available:
            block = bytes(self.buffer)
            self.buffer.clear()
            self.available.notify()
            return block

    def finish(self):
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            self.failure_reason = self.failure_reason or "pipe-stop-unconfirmed"
            self.failed.set()
        self.stream.close()


def _write_capped(stream, block):
    prefix = block[:max(0, MAX_LOG - stream.tell())]
    if prefix:
        stream.write(prefix)
        stream.flush()
    return len(prefix) == len(block)


def supervise(source, *, confirmed_at_unix_ms, root=ROOT, max_seconds=MAX_SECONDS, max_frames=MAX_FRAMES,
               output=print, mode="capture-only", inference_approval=None, source_policy="manual",
               automatic_assertion=None, stop_event=None, on_session=None, startup_deadline=None, on_record=None):
    if mode not in MODES:
        raise ValueError("invalid-mode")
    inference = mode == "inference-enabled"
    sustained = source_policy == "automatic-sustained"
    cpu_visual_board = inference_approval.get("cpu_visual_board", False) if isinstance(inference_approval, dict) else False
    if type(cpu_visual_board) is not bool or cpu_visual_board and (not inference or not sustained):
        raise ValueError("invalid-cpu-visual-board-schedule")
    experiment = inference_approval.get("experimental_bet_action", False) if isinstance(inference_approval, dict) else False
    if type(experiment) is not bool or experiment and (not inference or source_policy != "automatic-bounded"):
        raise ValueError("experimental-bet-action-approval-required")
    if (source_policy not in SOURCE_POLICIES
            or source_policy in AUTOMATIC_POLICIES and (not inference or automatic_assertion !=
                (SUSTAINED_ASSERTION if sustained else AUTOMATIC_ASSERTION))
            or source_policy == "manual" and automatic_assertion is not None):
        raise ValueError("automatic-approval-required")
    if sustained and not callable(on_record):
        raise ValueError("sustained-feed-required")
    if inference:
        if (not isinstance(inference_approval, dict)
                or inference_approval.get("inference_assertion") != INFERENCE_ASSERTION):
            raise ValueError("inference-approval-required")
        server = inference_service()
        if (server.get("model_state") != "ready" or server.get("acceptance_floors_loaded") is not True
                or server["instance_id"] != inference_approval.get("service_instance_id")):
            raise ValueError("model-not-ready")
        if experiment and server.get("experimental_bet_action") is not True:
            raise ValueError("experimental-bet-action-service-approval-required")
    elif inference_approval is not None:
        raise ValueError("capture-only-refuses-inference")
    if startup_deadline is not None and time.monotonic() >= startup_deadline:
        raise ValueError("automatic-discovery-timeout")
    if (type(max_seconds) is not int or not 1 <= max_seconds <= MAX_SECONDS
            or type(max_frames) is not int or not 1 <= max_frames <= MAX_FRAMES):
        raise ValueError("initial-session-bounds-exceeded")
    if type(confirmed_at_unix_ms) is not int or not 0 <= now_ms() - confirmed_at_unix_ms <= 30_000:
        raise ValueError("confirmation-expired")
    binary = attach.resolve_binary(root)
    base = private_path(BASE, root=root)
    base.mkdir(parents=True, exist_ok=True)
    # Stale lock requires operator investigation, never automatic cleanup/rearm.
    lock = base / "active.lock"
    with lock.open("xb") as stream:
        stream.write(b"manual capture in progress; do not auto-rearm\n")
    child, pipes = None, []
    diagnostics_complete = True
    session_id = uuid.uuid4().hex
    path = session_path(session_id, root=root)
    status = default_snapshot()
    status.update(session_id=session_id, status="capturing", mode=mode, inference_enabled=inference,
                  experimental_bet_action=experiment,
                   source_policy=source_policy, activity_state="verifying" if source_policy in AUTOMATIC_POLICIES else "active",
                   max_duration_ms=max_seconds * 1000,
                   max_frames=max_frames, updated_at_unix_ms=now_ms())
    if sustained:
        status.update(receipt_version=2, max_duration_ms=None, max_frames=None, remaining_ms=None,
                      evidence={"status": "active", "stop_reason": None, "elapsed_ms": 0,
                                "max_duration_ms": max_seconds * 1000, "max_frames": max_frames,
                                "max_bytes": MAX_BYTES, "recorded_frames": 0, "recorded_bytes": 0})
    command = [str(binary), "--manual-inference" if inference else "--capture-only", "--approval-file", str(path / "approval.json")]
    if experiment:
        command.insert(2, "--experimental-bet-action")
    started_utc, started = utc(), time.monotonic()
    reason, exit_code, forced, last_native = None, None, False, started
    capture_directory, latest, seen_indices = None, None, set()
    pending, read_offset, native_terminal, progress_second = b"", 0, False, -1

    def consume(block):
        nonlocal pending, native_terminal, reason, capture_directory, latest, last_native
        pending += block
        feed_rows = []
        receipt_progress = False
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            if len(line) > (MAX_FEED_RECORD if inference else MAX_RECORD):
                raise ValueError("invalid-native-receipt")
            row = attach._json(line, "window-list-invalid")
            if inference and isinstance(row, dict) and row.get("schema_version") == 2 and row.get("event") in FEED_EVENTS:
                if sustained:
                    feed_rows.append(row)
                continue
            terminal = _native_record(row, status)
            receipt_progress = True
            if terminal is not None:
                native_terminal = True
                if reason in (None, "child-exited", "child-failed"):
                    reason = terminal
            capture_directory, latest = row.get("capture_directory"), row.get("latest_frame")
            if isinstance(latest, dict) and latest.get("frame_index") not in seen_indices:
                seen_indices.add(latest["frame_index"])
                gap, lost = latest.get("previous_saved_gap_ms"), latest.get("estimated_missed_samples")
                if type(lost) is not int or not 0 <= lost <= 10_000:
                    raise ValueError("invalid-gap-receipt")
                if gap is not None:
                    if type(gap) is not int or not 0 <= gap <= 650_000:
                        raise ValueError("invalid-gap-receipt")
                    status["max_gap_ms"] = max(status["max_gap_ms"] or 0, gap)
                status["gap_count"] += int(lost > 0)
                status["estimated_missed_samples"] += lost
            last_native = time.monotonic()
        if len(pending) > (MAX_FEED_RECORD if inference else MAX_RECORD):
            raise ValueError("invalid-native-receipt")
        if sustained and receipt_progress:
            # Publish verified producer progress before consumer callbacks can wait on inference/feed locks.
            write_json(path / "status.json", {**status, "capture_directory": capture_directory, "latest_frame": latest})
        for row in feed_rows:
            if reason is None and not on_record(session_id, row):
                reason = public_snapshot(root=root, session_id=session_id).get("stop_reason") or "feed-failed"

    try:
        path.mkdir()
        (path / "markers").mkdir()
        approval = {"version": 2 if sustained else 1, "mode": mode,
                     "confirmed_at_unix_ms": confirmed_at_unix_ms, "max_seconds": max_seconds,
                     "max_frames": max_frames, "source": source.private_record()}
        if source_policy in AUTOMATIC_POLICIES:
            approval.update(source_policy=source_policy, automatic_assertion=automatic_assertion)
        else:
            approval["operator_assertion"] = None
        if inference:
            approval.update(inference_assertion=INFERENCE_ASSERTION,
                            service_instance_id=inference_approval["service_instance_id"],
                            experimental_bet_action=experiment)
            if cpu_visual_board:
                approval["cpu_visual_board"] = True
        write_json(path / "approval.json", approval, exclusive=True)
        write_json(path / "status.json", status)
        write_json(base / "current.json", {"session_id": session_id})
        if on_session is not None:
            on_session(session_id)
        if stop_event is not None and stop_event.is_set():
            raise KeyboardInterrupt
        if startup_deadline is not None and time.monotonic() >= startup_deadline:
            reason = "automatic-discovery-timeout"
            raise KeyboardInterrupt
        output("Session: %s. Stop: Ctrl+C or python scripts/laya_capture.py stop --session %s" % (session_id, session_id))
        output("%s: %ds or %d saved frames; target20 distinct DRAFT opportunities." % (
            "Evidence budget only; observation lasts until this source ends" if sustained else "Session budget",
            max_seconds, max_frames))
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("COINPOKER_")}
        with (path / "stdout.jsonl").open("xb") as stdout, (path / "stderr.txt").open("xb") as stderr:
            child = subprocess.Popen(command, cwd=Path(root).resolve(), env=env, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.PIPE if sustained else stdout,
                                      stderr=subprocess.PIPE if sustained else stderr, shell=False,
                                      **({"bufsize": 0} if sustained else {}))
            if sustained:
                pipes.append(_PipeReader(child.stdout))
                pipes.append(_PipeReader(child.stderr))
            with (path / "stdout.jsonl").open("rb") as reader:
                while True:
                    elapsed = time.monotonic() - started
                    if stop_event is not None and stop_event.is_set():
                        reason = "operator-stop"
                        break
                    status.update(elapsed_ms=int((time.monotonic() - started) * 1000), updated_at_unix_ms=now_ms())
                    if (path / "stdout.jsonl").stat().st_size > MAX_LOG or (path / "stderr.txt").stat().st_size > MAX_LOG:
                        reason = "log-limit"
                    if sustained:
                        block = pipes[0].read()
                        diagnostics_complete &= _write_capped(stdout, block)
                        diagnostics_complete &= _write_capped(stderr, pipes[1].read())
                        write_json(path / "status.json", {**status, "capture_directory": capture_directory,
                                                         "latest_frame": latest})
                        consume(block)
                        if any(pipe.failed.is_set() for pipe in pipes):
                            reason = "feed-failed"
                    else:
                        consume(reader.read(256 * 1024))
                        read_offset = reader.tell()
                    write_json(path / "status.json", {**status, "capture_directory": capture_directory,
                                                       "latest_frame": latest})
                    if int(elapsed) != progress_second:
                        progress_second = int(elapsed)
                        output("%s: %.1f/%ds; saved %d/%d; estimated missed samples %d." % (
                            mode, elapsed, max_seconds, status["recorded_frames"], max_frames, status["estimated_missed_samples"]))
                    exit_code = child.poll()
                    if exit_code is not None:
                        reason = reason or ("child-exited" if exit_code == 0 else "child-failed")
                        break
                    if reason is None and (path / "STOP").exists():
                        reason = public_snapshot(root=root, session_id=session_id)["stop_reason"] or "operator-stop"
                    if not sustained and elapsed >= max_seconds:
                        reason = "duration-limit"
                    if not sustained and status["recorded_frames"] >= max_frames:
                        reason = "frame-limit"
                    if time.monotonic() - last_native > 5:
                        reason = "native-stalled"
                    if reason:
                        break
                    time.sleep(0.1 if sustained else min(0.1, max(0, max_seconds - elapsed)))
    except KeyboardInterrupt:
        reason = reason or "operator-stop"
    except (OSError, ValueError, KeyError, TypeError):
        reason = "supervisor-error"
    finally:
        # Publish terminal state before waiting/terminating: late native completions
        # cannot refill the Monitor while the owned child winds down.
        try:
            if (path / "approval.json").is_file():
                stop_session(session_id, root=root)
                status.update(status="stopped" if reason in {"operator-stop", "duration-limit", "frame-limit"} else "failed",
                              activity_state="idle", stop_reason=reason or "supervisor-error", updated_at_unix_ms=now_ms())
                write_json(path / "status.json", {**status, "capture_directory": capture_directory, "latest_frame": latest})
        except (OSError, ValueError):
            # Receipt failure must never skip termination of the owned child.
            reason = "supervisor-error"
        if child is not None and native_terminal and child.poll() is None:
            try:
                exit_code = child.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
        if child is not None and child.poll() is None:
            # This exact owned child only. Never restart it or touch a model/listener.
            forced = True
            try:
                child.terminate()
                try:
                    exit_code = child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    exit_code = child.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                reason = "child-stop-unconfirmed"
        elif child is not None:
            exit_code = child.poll()
        if child is not None and reason != "child-stop-unconfirmed":
            try:
                if sustained:
                    if len(pipes) != 2:
                        raise ValueError("pipe-failed")
                    deadline = time.monotonic() + 2
                    with (path / "stdout.jsonl").open("ab") as out_log, (path / "stderr.log").open("ab") as err_log:
                        while True:
                            blocks = [pipe.read() for pipe in pipes]
                            for log, block in zip((out_log, err_log), blocks):
                                diagnostics_complete &= _write_capped(log, block)
                            consume(blocks[0])
                            threads = [pipe.thread for pipe in pipes if hasattr(pipe, "thread")]
                            if all(not thread.is_alive() for thread in threads):
                                # Drain any final block enqueued between read and EOF.
                                blocks = [pipe.read() for pipe in pipes]
                                for log, block in zip((out_log, err_log), blocks):
                                    diagnostics_complete &= _write_capped(log, block)
                                consume(blocks[0])
                                break
                            if time.monotonic() >= deadline:
                                for pipe in pipes:
                                    pipe.failure_reason = getattr(pipe, "failure_reason", None) or "pipe-stop-unconfirmed"
                                    pipe.failed.set()
                                break
                            for thread in threads:
                                thread.join(timeout=0.01)
                    for pipe in pipes:
                        pipe.finish()
                    if any(pipe.failed.is_set() for pipe in pipes):
                        diagnostics_complete = False
                        raise ValueError("pipe-failed")
                else:
                    if (path / "stdout.jsonl").stat().st_size > MAX_LOG:
                        raise ValueError("log-limit")
                    with (path / "stdout.jsonl").open("rb") as reader:
                        reader.seek(read_offset)
                        for block in iter(lambda: reader.read(256 * 1024), b""):
                            consume(block)
                if pending:
                    raise ValueError("partial-native-tail")
            except (OSError, ValueError, KeyError, TypeError):
                if reason != "feed-failed":
                    reason = "receipt-invalid"
        reason = reason or "supervisor-error"
        status.update(status="stopped" if reason in {"operator-stop", "duration-limit", "frame-limit"} else "failed",
                      activity_state="idle", stop_reason=reason,
                      elapsed_ms=int((time.monotonic() - started) * 1000), updated_at_unix_ms=now_ms())
        try:
            if path.exists():
                write_json(path / "status.json", {**status, "capture_directory": capture_directory, "latest_frame": latest})
                write_json(path / "run.json", {"command": command, "cwd": str(Path(root).resolve()),
                           "started_utc": started_utc, "ended_utc": utc(), "exit_code": exit_code,
                           "stdout": "stdout.jsonl", "stderr": "stderr.txt", "forced_stop": forced,
                            "stop_reason": reason, "receipt_complete": native_terminal and not pending and not forced,
                            "diagnostics_complete": diagnostics_complete,
                            "transport_failures": {name: pipe.failure_reason for name, pipe in zip(("stdout", "stderr"), pipes)
                                                   if getattr(pipe, "failure_reason", None) is not None},
                            "loss_note": "Sampling is not complete action history. Forced stop may leave an unacknowledged PNG or manifest tail."}, exclusive=True)
        finally:
            if reason != "child-stop-unconfirmed":
                lock.unlink()
    summary = public_snapshot(root=root, session_id=session_id)
    write_json(path / "summary.json", summary, exclusive=True)
    output(json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] == "stopped" else 1


def stop_session(session_id, *, root=ROOT):
    path = session_path(session_id, root=root)
    if not (path / "approval.json").is_file():
        raise ValueError("unknown-session")
    with private_path(path / "STOP", root=root).open("ab") as stream:
        stream.flush()
        os.fsync(stream.fileno())


def fail_session(session_id, reason, *, root=ROOT):
    if reason not in {"feed-failed", "model-not-ready"}:
        raise ValueError("invalid-failure")
    path = session_path(session_id, root=root)
    write_json(path / "failure.json", {"reason": reason})
    stop_session(session_id, root=root)


class AutomaticStart:
    """One explicitly armed metadata search and one same-source supervised session."""

    def __init__(self, service, *, profile=attach.DEFAULT_PROFILE, root=ROOT, continuous_observation=False):
        if type(continuous_observation) is not bool or continuous_observation and getattr(service, "experimental_bet_action", False):
            raise ValueError("invalid-continuous-observation")
        self.service, self.profile, self.root = service, profile, Path(root).resolve()
        self.continuous_observation = continuous_observation
        self.closed = threading.Event()
        self.lock = threading.RLock()
        self.thread = None
        self.session_id = None
        self.status, self.reason = "waiting-model", None

    def snapshot(self, current=None):
        with self.lock:
            status, reason = self.status, self.reason
            if self.session_id is not None:
                if current is None or current.get("session_id") not in {None, self.session_id}:
                    current = public_snapshot(root=self.root, session_id=self.session_id)
                status = current["activity_state"] if current["status"] == "capturing" else current["status"]
                reason = current["stop_reason"]
            return {"enabled": True, "status": status, "stop_reason": reason}

    def _bind(self, session_id):
        with self.lock:
            self.session_id = session_id

    def _run(self):
        # Metadata waiting is finite. The independent source-capture budget
        # includes activity verification and independently admitted readout.
        deadline = time.monotonic() + 600
        try:
            while not self.closed.is_set() and time.monotonic() < deadline:
                with self.service.state.lock:
                    model = self.service.state.model["model_state"]
                if model in {"disabled", "failed"}:
                    self.reason = "model-not-ready"
                    raise ValueError("model-not-ready")
                if model != "ready":
                    self.closed.wait(0.2)
                    continue
                self.status = "searching"
                listing = attach.list_windows(root=self.root)
                result = attach.PracticeAttachment(self.profile, root=self.root, require_profile=True).select(listing)
                if time.monotonic() >= deadline:
                    self.reason = "automatic-discovery-timeout"
                    break
                if result.code == "practice-target-absent":
                    self.closed.wait(1)
                    continue
                if not result.ok:
                    self.reason = result.code
                    raise ValueError("automatic-source-blocked")
                source = attach.select_exact(listing, result.config["pid"], result.config["window_hwnd"])
                if self.closed.is_set():
                    break
                self.status = "verifying"
                visual = getattr(self.service.manual_feed, "visual", None)
                prepare_visual = getattr(visual, "prepare", None)
                cpu_visual_board = bool(self.continuous_observation and callable(prepare_visual) and prepare_visual() is True)
                supervise(source, confirmed_at_unix_ms=now_ms(), root=self.root,
                           mode="inference-enabled", source_policy="automatic-sustained" if self.continuous_observation else "automatic-bounded",
                           automatic_assertion=SUSTAINED_ASSERTION if self.continuous_observation else AUTOMATIC_ASSERTION,
                           inference_approval={"inference_assertion": INFERENCE_ASSERTION,
                                               "service_instance_id": self.service.instance_id,
                                                "experimental_bet_action": getattr(self.service, "experimental_bet_action", False),
                                                "cpu_visual_board": cpu_visual_board},
                           stop_event=self.closed, on_session=self._bind,
                           startup_deadline=deadline,
                           on_record=self.service.manual_feed.ingest_live if self.continuous_observation else None,
                          output=lambda _: None)
                current = public_snapshot(root=self.root, session_id=self.session_id)
                self.status, self.reason = current["status"], current["stop_reason"]
                return  # No rearm after an idle probe, replacement or any stop.
            self.status = "stopped"
            self.reason = "operator-stop" if self.closed.is_set() else "automatic-discovery-timeout"
        except (OSError, ValueError, KeyError, TypeError):
            self.status = "failed"
            self.reason = self.reason or "automatic-startup-failed"

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def stop(self):
        self.closed.set()
        try:
            if self.session_id is not None:
                stop_session(self.session_id, root=self.root)
        except (OSError, ValueError):
            self.reason = "automatic-startup-failed"
        finally:
            if self.thread is not None:
                self.thread.join(timeout=8)


def mark_session(session_id, opportunity_id, kind, frame_index, note="", *, root=ROOT):
    if (not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", opportunity_id) or kind not in {"opportunity", "incorrect", "missing"}
            or type(frame_index) is not int or frame_index < 1 or len(note) > 240
            or any(ord(char) < 32 for char in note)):
        raise ValueError("invalid-manual-marker")
    path = session_path(session_id, root=root)
    if len(_markers(path)) >= 1000:
        raise ValueError("marker-bound")
    status = read_json(path / "status.json")
    directory = private_path(Path(status["capture_directory"]), root=root)
    capture_root = Path(root).resolve() / ".local/captures"
    if directory.parent != capture_root or not re.fullmatch(r"utc-[0-9]+-[0-9]{9}-practice", directory.name):
        raise ValueError("invalid-capture-receipt")
    manifest = private_path(directory / "manifest.jsonl", root=root)
    receipt = None
    with manifest.open("rb") as stream:
        for index in range(MAX_FRAMES + 1):
            line = stream.readline(MAX_RECORD + 1)
            if not line:
                break
            if index == MAX_FRAMES or len(line) > MAX_RECORD or not line.endswith(b"\n"):
                raise ValueError("incomplete-manifest")
            row = attach._json(line, "window-list-invalid")
            if row.get("event") == "frame" and row.get("frame_index") == frame_index:
                receipt = row
    if receipt is None:
        raise ValueError("frame-not-acknowledged")
    png = private_path(directory / ("frame-%010d.png" % frame_index), root=root)
    if png.stat().st_size != receipt["png_bytes"] or png.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("frame-integrity-failed")
    digest = hashlib.sha256()
    with png.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != receipt["sha256"]:
        raise ValueError("frame-integrity-failed")
    marker = {"version": 1, "session_id": session_id, "opportunity_id": opportunity_id,
              "kind": kind, "frame_index": frame_index, "sha256": receipt["sha256"],
              "source_utc_unix_ms": receipt["source_utc_unix_ms"], "marked_utc": utc(),
              "labels": "DRAFT", "human_review": "PENDING", "accepted_correction": False,
              "note": note, "distinctness_basis": "operator-assertion-not-verified"}
    write_json(path / "markers" / (opportunity_id + "." + kind + ".json"), marker, exclusive=True)
    return marker


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="metadata only; no capture")
    start = commands.add_parser("start", help="interactive one-shot source and optional inference approval")
    start.add_argument("--mode", choices=sorted(MODES), default="capture-only")
    start.add_argument("--pid", type=int, required=True)
    start.add_argument("--hwnd", required=True)
    start.add_argument("--max-seconds", type=int, default=MAX_SECONDS, choices=range(1, MAX_SECONDS + 1), metavar="1..600")
    start.add_argument("--max-frames", type=int, default=MAX_FRAMES, choices=range(1, MAX_FRAMES + 1), metavar="1..1200")
    for command in ("stop", "status", "mark"):
        child = commands.add_parser(command)
        child.add_argument("--session", required=True)
        if command == "mark":
            child.add_argument("--opportunity-id", required=True, help="one stable ID per distinct opportunity, never per repeated frame")
            child.add_argument("--kind", choices=("opportunity", "incorrect", "missing"), required=True)
            child.add_argument("--frame-index", type=int, required=True)
            child.add_argument("--note", default="")
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            for window in attach.list_windows().windows:
                if window.exe_name.lower() == "coinpoker.exe":
                    print(json.dumps(window.private_record(), ensure_ascii=True))
        elif args.command == "start":
            consent = approve_inference() if args.mode == "inference-enabled" else None
            source, confirmed = confirm_source(args.pid, args.hwnd, mode=args.mode)
            return supervise(source, confirmed_at_unix_ms=confirmed, max_seconds=args.max_seconds,
                             max_frames=args.max_frames, mode=args.mode, inference_approval=consent)
        elif args.command == "stop":
            stop_session(args.session)
            print("Stop sentinel set for this session only; no rearm.")
        elif args.command == "status":
            print(json.dumps(public_snapshot(session_id=args.session)))
        else:
            mark_session(args.session, args.opportunity_id, args.kind, args.frame_index, args.note)
            print("Private DRAFT marker saved; not an accepted correction or verified opportunity.")
        return 0
    except KeyboardInterrupt:
        print("Manual diagnostic cancelled; no automatic restart.", file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError, TypeError, EOFError):
        print("Manual capture command refused or failed; no automatic retry or replacement.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
