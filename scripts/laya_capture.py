#!/usr/bin/env python3
"""One-shot manual capture-only CLI. No model imports, HTTP controls or auto-attach.

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
import sys
import time
import uuid

import laya_attach as attach

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(".local/laya/manual-capture")
ASSERTION = "I am seated and ready"
MAX_SECONDS = 600
MAX_FRAMES = 1200
TARGET = 20
MAX_RECORD = 16 * 1024
MAX_LOG = 20 * 1024 * 1024
REASONS = {"operator-stop", "duration-limit", "frame-limit", "disk-limit", "recorder-failure",
           "source-unavailable", "source-changed", "capture-failed", "child-exited", "child-failed",
           "native-stalled", "receipt-invalid", "log-limit", "supervisor-error", "status-stale",
           "child-stop-unconfirmed"}
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
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
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
        os.replace(target, path)


def confirm_source(pid, hwnd, *, root=ROOT, input_fn=input, output=print):
    started = time.monotonic()
    chosen = attach.select_exact(attach.list_windows(root=root), pid, hwnd)
    challenge = "CAPTURE %d %s %s" % (chosen.process_id, chosen.hwnd, uuid.uuid4().hex[:12])
    output("Exact source (private metadata): " + json.dumps(chosen.private_record(), ensure_ascii=True))
    output("Capture ONLY. Suggestions OFF; R17 strict; Gate F historical FAIL; labels DRAFT; human PENDING.")
    output("No inference, recognition acceptance, game input or provider-policy approval is granted.")
    if input_fn("Type %s to confirm this exact window: " % challenge) != challenge:
        raise ValueError("exact-source-confirmation-required")
    if input_fn("Type 'I am seated and ready': ") != ASSERTION:
        raise ValueError("seated-assertion-required")
    current = attach.select_exact(attach.list_windows(root=root), pid, hwnd)
    if time.monotonic() - started > 30:
        raise ValueError("confirmation-expired")
    if not attach.same_exact_source(chosen, current):
        raise ValueError("source-changed-new-approval-required")
    return current, now_ms()


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
            "session_id": None, "elapsed_ms": 0, "max_duration_ms": MAX_SECONDS * 1000,
            "max_frames": MAX_FRAMES, "remaining_ms": MAX_SECONDS * 1000,
            "recorded_frames": 0, "recorded_bytes": 0, "capture_failures": 0,
            "gap_count": 0, "max_gap_ms": None, "estimated_missed_samples": 0,
            "distinct_opportunities": 0, "target_opportunities": TARGET, "opportunity_deficit": TARGET,
            "labels": "DRAFT", "human_review": "PENDING", "suggestions_enabled": False,
            "inference_enabled": False,
            "updated_at_unix_ms": None}


def public_snapshot(*, root=ROOT, session_id=None, current_ms=None):
    """Read-only allowlist. Paths, HWNDs, titles, PNGs and draft prose never escape."""
    result = default_snapshot()
    try:
        if session_id is None:
            pointer = private_path(BASE / "current.json", root=root)
            if not pointer.exists():
                return result
            session_id = read_json(pointer)["session_id"]
        path = session_path(session_id, root=root)
        value = read_json(path / "status.json")
        if value.get("mode") != "capture-only" or value.get("status") not in STATUSES:
            raise ValueError("invalid-status")
        result.update(session_id=session_id, status=value["status"])
        for key, maximum in (("elapsed_ms", 650_000), ("max_duration_ms", 600_000),
                             ("max_frames", 1200), ("recorded_frames", 1200),
                             ("recorded_bytes", 1_073_741_824), ("capture_failures", 10_000),
                             ("gap_count", 1200),
                             ("estimated_missed_samples", 10_000), ("updated_at_unix_ms", 10**15)):
            item = value.get(key)
            if type(item) is not int or not 0 <= item <= maximum:
                raise ValueError("invalid-status")
            result[key] = item
        gap = value.get("max_gap_ms")
        if gap is not None and (type(gap) is not int or not 0 <= gap <= 650_000):
            raise ValueError("invalid-status")
        result["max_gap_ms"] = gap
        if not result["max_duration_ms"] or not result["max_frames"]:
            raise ValueError("invalid-status")
        reason = value.get("stop_reason")
        if reason is not None and reason not in REASONS:
            raise ValueError("invalid-status")
        result["stop_reason"] = reason
        current_ms = now_ms() if current_ms is None else current_ms
        age = current_ms - result["updated_at_unix_ms"]
        if result["status"] == "capturing":
            if age < 0 or age > 3000:
                result.update(status="interrupted", stop_reason="status-stale")
            else:
                result["elapsed_ms"] += age
        result["remaining_ms"] = max(0, result["max_duration_ms"] - result["elapsed_ms"])
        count = opportunity_count(path)
        result.update(distinct_opportunities=count, opportunity_deficit=max(0, TARGET - count))
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        result = default_snapshot()
        result.update(status="failed", stop_reason="receipt-invalid", remaining_ms=0)
    return result


def _native_record(row, status):
    if (not isinstance(row, dict) or row.get("event") != "manual_capture"
            or row.get("version") != 1 or row.get("mode") != "capture-only"):
        raise ValueError("invalid-native-receipt")
    recording = row["recording"]
    for key, maximum in (("recorded_frames", status["max_frames"]), ("recorded_bytes", 1_073_741_824)):
        item = recording[key]
        if type(item) is not int or not status[key] <= item <= maximum:
            raise ValueError("invalid-native-counter")
        status[key] = item
    failures = row.get("capture_failures")
    if type(failures) is not int or not 0 <= failures <= 10_000:
        raise ValueError("invalid-native-counter")
    status["capture_failures"] = failures
    reason = row.get("stop_reason")
    if reason is not None and reason not in REASONS:
        raise ValueError("invalid-native-reason")
    return reason


def supervise(source, *, confirmed_at_unix_ms, root=ROOT, max_seconds=MAX_SECONDS, max_frames=MAX_FRAMES, output=print):
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
    child = None
    session_id = uuid.uuid4().hex
    path = session_path(session_id, root=root)
    status = default_snapshot()
    status.update(session_id=session_id, status="capturing", max_duration_ms=max_seconds * 1000,
                  max_frames=max_frames, updated_at_unix_ms=now_ms())
    command = [str(binary), "--capture-only", "--approval-file", str(path / "approval.json")]
    started_utc, started = utc(), time.monotonic()
    reason, exit_code, forced, last_native = None, None, False, started
    capture_directory, latest, seen_indices = None, None, set()
    pending, read_offset, native_terminal, progress_second = b"", 0, False, -1

    def consume(block):
        nonlocal pending, native_terminal, reason, capture_directory, latest, last_native
        pending += block
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            if len(line) > MAX_RECORD:
                raise ValueError("invalid-native-receipt")
            row = attach._json(line, "window-list-invalid")
            terminal = _native_record(row, status)
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
        if len(pending) > MAX_RECORD:
            raise ValueError("invalid-native-receipt")

    try:
        path.mkdir()
        (path / "markers").mkdir()
        approval = {"version": 1, "mode": "capture-only", "operator_assertion": ASSERTION,
                    "confirmed_at_unix_ms": confirmed_at_unix_ms, "max_seconds": max_seconds,
                    "max_frames": max_frames, "source": source.private_record()}
        write_json(path / "approval.json", approval, exclusive=True)
        write_json(path / "status.json", status)
        write_json(base / "current.json", {"session_id": session_id})
        output("Session: %s. Stop: Ctrl+C or python scripts/laya_capture.py stop --session %s" % (session_id, session_id))
        output("Budget: %ds or %d saved frames, whichever first; target20 distinct manual DRAFT opportunities." % (max_seconds, max_frames))
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("COINPOKER_")}
        with (path / "stdout.jsonl").open("xb") as stdout, (path / "stderr.txt").open("xb") as stderr:
            child = subprocess.Popen(command, cwd=Path(root).resolve(), env=env, stdin=subprocess.DEVNULL,
                                     stdout=stdout, stderr=stderr, shell=False)
            with (path / "stdout.jsonl").open("rb") as reader:
                while True:
                    elapsed = time.monotonic() - started
                    status.update(elapsed_ms=int(elapsed * 1000), updated_at_unix_ms=now_ms())
                    if (path / "stdout.jsonl").stat().st_size > MAX_LOG or (path / "stderr.txt").stat().st_size > MAX_LOG:
                        reason = "log-limit"
                    consume(reader.read(256 * 1024))
                    read_offset = reader.tell()
                    write_json(path / "status.json", {**status, "capture_directory": capture_directory,
                                                       "latest_frame": latest})
                    if int(elapsed) != progress_second:
                        progress_second = int(elapsed)
                        output("Capture-only: %.1f/%ds; saved %d/%d; estimated missed samples %d." % (
                            elapsed, max_seconds, status["recorded_frames"], max_frames, status["estimated_missed_samples"]))
                    exit_code = child.poll()
                    if exit_code is not None:
                        reason = reason or ("child-exited" if exit_code == 0 else "child-failed")
                        break
                    if (path / "STOP").exists():
                        reason = "operator-stop"
                    if elapsed >= max_seconds:
                        reason = "duration-limit"
                    if status["recorded_frames"] >= max_frames:
                        reason = "frame-limit"
                    if time.monotonic() - last_native > 5:
                        reason = "native-stalled"
                    if reason:
                        break
                    time.sleep(min(0.1, max(0, max_seconds - elapsed)))
    except KeyboardInterrupt:
        reason = "operator-stop"
    except (OSError, ValueError, KeyError, TypeError):
        reason = "supervisor-error"
    finally:
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
                if (path / "stdout.jsonl").stat().st_size > MAX_LOG:
                    raise ValueError("log-limit")
                with (path / "stdout.jsonl").open("rb") as reader:
                    reader.seek(read_offset)
                    for block in iter(lambda: reader.read(256 * 1024), b""):
                        consume(block)
                if pending:
                    raise ValueError("partial-native-tail")
            except (OSError, ValueError, KeyError, TypeError):
                reason = "receipt-invalid"
        reason = reason or "supervisor-error"
        status.update(status="stopped" if reason in {"operator-stop", "duration-limit", "frame-limit"} else "failed",
                      stop_reason=reason, elapsed_ms=int((time.monotonic() - started) * 1000), updated_at_unix_ms=now_ms())
        if path.exists():
            write_json(path / "status.json", {**status, "capture_directory": capture_directory, "latest_frame": latest})
            write_json(path / "run.json", {"command": command, "cwd": str(Path(root).resolve()),
                       "started_utc": started_utc, "ended_utc": utc(), "exit_code": exit_code,
                       "stdout": "stdout.jsonl", "stderr": "stderr.txt", "forced_stop": forced,
                       "stop_reason": reason, "receipt_complete": native_terminal and not pending and not forced,
                       "loss_note": "Sampling is not complete action history. Forced stop may leave an unacknowledged PNG or manifest tail."}, exclusive=True)
        if reason != "child-stop-unconfirmed":
            lock.unlink()
    summary = public_snapshot(root=root, session_id=session_id)
    output(json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] == "stopped" else 1


def stop_session(session_id, *, root=ROOT):
    path = session_path(session_id, root=root)
    if not (path / "approval.json").is_file():
        raise ValueError("unknown-session")
    with private_path(path / "STOP", root=root).open("ab") as stream:
        stream.flush()
        os.fsync(stream.fileno())


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
    start = commands.add_parser("start", help="interactive one-shot capture-only approval")
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
            source, confirmed = confirm_source(args.pid, args.hwnd)
            return supervise(source, confirmed_at_unix_ms=confirmed, max_seconds=args.max_seconds, max_frames=args.max_frames)
        elif args.command == "stop":
            stop_session(args.session)
            print("Stop sentinel set for this session only; no rearm.")
        elif args.command == "status":
            print(json.dumps(public_snapshot(session_id=args.session)))
        else:
            mark_session(args.session, args.opportunity_id, args.kind, args.frame_index, args.note)
            print("Private DRAFT marker saved; not an accepted correction or verified opportunity.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, EOFError):
        print("Manual capture command refused or failed; no automatic retry or replacement.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
