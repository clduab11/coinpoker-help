"""Source-bound CPU visual diagnostics, separate from admitted model readings."""

import copy
import hashlib
import io
import json
from pathlib import Path
import re
import threading
import time

MAX_AGE_MS = 1500
MAX_PNG_BYTES = 8 * 1024 * 1024
MAX_LOG_BYTES = 8 * 1024 * 1024
CONTEXT_AGE_MS = 5000


def _capture(frame, scope, instance_id):
    session_id, source_id, epoch = scope
    return {"service_instance_id": instance_id, "session_id": session_id,
            "capture_session_id": frame.get("capture_session_id"), "source_id": source_id,
            "native_source_id": str(frame["source_id"]) if frame.get("source_id") is not None else None, "epoch": epoch,
            "sequence": frame["frame_index"], "captured_at_ms": frame["captured_at_monotonic_ms"],
            "captured_at_unix_ms": frame["source_utc_unix_ms"], "sha256": frame["sha256"],
            "width": frame["width"], "height": frame["height"]}


def _current_region(original, latest, bounds, occluded=()):
    return _region_checks(original, latest, [bounds], occluded)[0]


def _region_checks(original, latest, regions, occluded=()):
    from PIL import Image
    if any(not isinstance(mask, (list, tuple)) or len(mask) != 4
           or any(type(x) is not int for x in mask) for mask in occluded):
        return [False] * len(regions)
    try:
        with Image.open(io.BytesIO(original)) as old, Image.open(io.BytesIO(latest)) as new:
            if old.size != new.size:
                return [False] * len(regions)
            old, new = old.convert("RGB"), new.convert("RGB")
            result = []
            for bounds in regions:
                valid = (isinstance(bounds, (list, tuple)) and len(bounds) == 4
                         and all(type(x) is int for x in bounds))
                if not valid:
                    result.append(False)
                    continue
                l, t, r, b = bounds
                result.append(0 <= l < r <= old.width and 0 <= t < b <= old.height
                    and not any(l < m[2] and r > m[0] and t < m[3] and b > m[1] for m in occluded)
                    and old.crop(bounds).tobytes() == new.crop(bounds).tobytes())
            return result
    except (OSError, ValueError, TypeError):
        return [False] * len(regions)


class NumericWorker:
    """Low-latency visible values, independent of OCR, card matching and model jobs."""
    def __init__(self, root, instance_id, archive, *, wall=time.time, monotonic=time.monotonic):
        self.root, self.instance_id, self.archive = root, instance_id, archive
        self.wall, self.monotonic = wall, monotonic
        self.lock = threading.RLock()
        self.wake, self.closed = threading.Event(), threading.Event()
        self.reader = self.thread = self.pending = self.latest = self.value = self.original = self.scope = None
        self.deadline = None
        self.invalidated = {}
        self.first_watermark = -1
        self.attempts = self.dropped = 0
        self.last_error = None
        self.last_signature = None
        self.last_timing = None

    @staticmethod
    def fields(value):
        return [value["pot"], *[row[key] for row in value["seats"] for key in ("stack", "wager")]]

    def submit(self, frame, png, scope, filename):
        frame = {**frame, "_numeric_received_at_unix_ms": int(self.wall() * 1000)}
        with self.lock:
            if self.closed.is_set():
                return
            if scope != self.scope:
                self.scope, self.value, self.original = scope, None, None
                self.invalidated, self.last_signature = {}, None
                self.first_watermark = -1
            if self.value is None:
                self.first_watermark = frame["frame_index"]
            elif self.value is not None:
                fields = self.fields(self.value)
                checks = _region_checks(self.original, png, [f.get("bounds") for f in fields], frame.get("occluded_regions", []))
                for index, unchanged in enumerate(checks):
                    if not unchanged or frame.get("readability") == "unknown":
                        self.invalidated[index] = frame["frame_index"]
            self.latest = frame, png, scope
            if self.pending is not None:
                self.dropped += 1
            self.pending = frame, png, scope, filename
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()
        self.wake.set()

    def _run(self):
        from PIL import Image
        while not self.closed.is_set():
            self.wake.wait(.2)
            self.wake.clear()
            with self.lock:
                pending, self.pending = self.pending, None
            if pending is None:
                continue
            frame, png, scope, filename = pending
            capture = _capture(frame, scope, self.instance_id)
            received_wall = frame.get("_numeric_received_at_unix_ms")
            self.attempts += 1
            started = time.perf_counter()
            started_wall = int(self.wall() * 1000)
            try:
                from laya_numeric import NumericReader
                if self.reader is None:
                    self.reader = NumericReader(self.root)
                with Image.open(io.BytesIO(png)) as image:
                    value = self.reader.read(image.convert("RGB"), capture, occluded_regions=frame.get("occluded_regions", []))
                if frame.get("readability") == "unknown":
                    for field in self.fields(value):
                        field.update(value=None, literal=None, status="unknown", reason="source-readability-unknown")
                now = int(self.wall() * 1000)
                if not 0 <= now - capture["captured_at_unix_ms"] < MAX_AGE_MS:
                    self.last_error = "numeric-expired-before-publication"
                    continue
                value.update(processing_ms=round((time.perf_counter() - started) * 1000, 2),
                             published_at_unix_ms=now, attempts=self.attempts, dropped_frames=self.dropped,
                             arrival_lag_ms=received_wall - capture["captured_at_unix_ms"] if received_wall is not None else None,
                             queue_lag_ms=started_wall - received_wall if received_wall is not None else None)
                with self.lock:
                    if scope != self.scope or self.closed.is_set():
                        continue
                    self.value, self.original = value, png
                    self.deadline = self.monotonic() + (capture["captured_at_unix_ms"] + MAX_AGE_MS - now) / 1000
                    self.last_error = None
                signature = tuple((f.get("status"), f.get("literal")) for f in self.fields(value))
                if signature != self.last_signature:
                    self.last_signature = signature
                    changes = {"pot": value["pot"], "seats": value["seats"]}
                    self.archive.record(png, capture, "visible-numeric-change", changes,
                        original=filename if frame.get("archival") is True else None,
                        crops=[f["bounds"] for f in self.fields(value) if f.get("status") == "provisional" and f.get("bounds")])
            except (OSError, ValueError, TypeError, KeyError, ImportError, RuntimeError) as error:
                self.last_error = str(error)[:120]
            finally:
                self.last_timing = {"capture": capture, "arrival_lag_ms": received_wall - capture["captured_at_unix_ms"] if received_wall is not None else None,
                    "queue_lag_ms": started_wall - received_wall if received_wall is not None else None,
                    "processing_ms": round((time.perf_counter() - started) * 1000, 2),
                    "completed_at_unix_ms": int(self.wall() * 1000), "error": self.last_error}

    def snapshot(self, state, *, occluded_regions=()):
        with self.lock:
            if self.closed.is_set():
                return None
            value, original, latest = copy.deepcopy(self.value), self.original, self.latest
            invalidated = dict(self.invalidated)
            first_watermark = self.first_watermark
            if value is None or latest is None or self.deadline is None:
                return None
            if (self.monotonic() >= self.deadline
                    or self.wall() * 1000 >= value["capture"]["captured_at_unix_ms"] + MAX_AGE_MS):
                self.value = None
                return None
        capture = value["capture"]
        current, receipt = state.get("capture") or {}, state.get("capture_session") or {}
        if (receipt.get("status") != "capturing" or not current.get("fresh_capture")
                or state.get("session_id") != capture["session_id"]
                or (state.get("server") or {}).get("instance_id") != self.instance_id
                or current.get("source_id") != capture["source_id"] or current.get("epoch") != capture["epoch"]
                or [current.get("width"), current.get("height")] != [capture["width"], capture["height"]]
                or receipt.get("session_id") != capture.get("capture_session_id")
                or not 0 <= self.wall() * 1000 - capture["captured_at_unix_ms"] < MAX_AGE_MS):
            return None
        frame, png, scope = latest
        if scope != (capture["session_id"], capture["source_id"], capture["epoch"]):
            return None
        fields = self.fields(value)
        masks = [*frame.get("occluded_regions", []), *occluded_regions]
        checks = _region_checks(original, png, [f.get("bounds") for f in fields], masks)
        for index, (field, unchanged) in enumerate(zip(fields, checks)):
            if not unchanged or frame.get("readability") == "unknown" or capture["sequence"] < max(first_watermark, invalidated.get(index, -1)):
                field.update(value=None, literal=None, status="unknown", reason="numeric-region-changed-or-occluded")
        return value

    def stop(self):
        self.closed.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join(timeout=3)


class ContextWorker:
    """CPU identity/profile lane with independent leases and immutable input bytes."""
    def __init__(self, root, instance_id, archive, *, wall=time.time, monotonic=time.monotonic):
        self.root, self.instance_id, self.archive, self.wall = root, instance_id, archive, wall
        self.lock = threading.RLock()
        self.wake, self.closed = threading.Event(), threading.Event()
        self.pending = self.latest = self.value = self.original = self.scope = None
        self.reader = self.timeline = self.thread = None
        self.dropped = self.attempts = 0
        self.last_error = None
        self.log = None
        self.log_bytes = 0
        self.log_complete = True
        self.monotonic, self.deadline = monotonic, None
        self.invalidated = {}
        self.pending_invalidations = set()

    def submit(self, frame, png, scope, filename):
        frame = {**frame, "context_requested_at_unix_ms": int(self.wall() * 1000)}
        with self.lock:
            if self.closed.is_set():
                return
            if self.scope != scope:
                self.scope, self.value, self.timeline = scope, None, None
                self.invalidated, self.pending_invalidations, self.deadline = {}, set(), None
            elif self.value is not None:
                masks = frame.get("occluded_regions", [])
                seats = self.value.get("seats", [])
                role = (self.value.get("evidence") or {}).get("role") or {}
                caption = self.value.get("table_caption") or {}
                checks = _region_checks(self.original, png,
                    [s.get("bounds") for s in seats] + [role.get("bounds"), caption.get("bounds")], masks)
                for seat, unchanged in zip(seats, checks):
                    if seat.get("identity") and not unchanged:
                        self.invalidated[seat["seat"]] = frame["frame_index"]
                        self.pending_invalidations.add(seat["seat"])
                        seat.update(occupancy="unknown", identity=None, stats=None,
                                    continuity="uncertain", status="unknown", reason="source-region-changed")
                if not checks[-2]:
                    self.invalidated["role"] = frame["frame_index"]
                    self.value.update(role="uncertain", hero_seat=None)
                if caption.get("bounds") and not checks[-1]:
                    self.invalidated["caption"] = frame["frame_index"]
                    self.value["table_context_id"] = None
            self.latest = (frame, png, scope)
            if self.pending is not None:
                self.dropped += 1
            self.pending = (frame, png, scope, filename)
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()
        self.wake.set()

    def _run(self):
        from PIL import Image
        while not self.closed.is_set():
            self.wake.wait(.2)
            self.wake.clear()
            with self.lock:
                pending, self.pending = self.pending, None
            if pending is None:
                continue
            frame, png, scope, filename = pending
            started = time.perf_counter()
            attempt_started = int(self.wall() * 1000)
            self.attempts += 1
            capture = _capture(frame, scope, self.instance_id)
            value = None
            try:
                from laya_context import ContextReader, ContextTimeline
                if self.reader is None:
                    self.reader = ContextReader(self.root)
                with Image.open(io.BytesIO(png)) as image:
                    result = self.reader.read(image.convert("RGB"), capture,
                                              occluded_regions=frame.get("occluded_regions", []))
                popup_original = None
                if hasattr(self.reader, "read_popup"):
                    for popup, popup_png in frame.get("_popup_inputs", []):
                        popup_capture = {**capture, "parent_capture": copy.deepcopy(capture),
                            "popup_window": copy.deepcopy(popup.get("window")), "popup_index": popup["popup_index"],
                            "non_atomic": True, "captured_at_unix_ms": popup["source_utc_unix_ms"],
                            "captured_at_ms": popup["captured_at_monotonic_ms"], "sha256": popup["sha256"],
                            "width": popup["width"], "height": popup["height"]}
                        with Image.open(io.BytesIO(popup_png)) as image:
                            profile = self.reader.read_popup(image.convert("RGB"), popup_capture,
                                                             result.get("seats", []))
                        if profile:
                            if result.get("profile"):
                                result["profile"] = None
                                result["profile_rejection"] = "multiple-profile-panels"
                                popup_original = None
                                break
                            result["profile"], popup_original = profile, popup_png
                with self.lock:
                    if scope != self.scope or self.closed.is_set():
                        continue
                    if not 0 <= int(self.wall() * 1000) - capture["captured_at_unix_ms"] < CONTEXT_AGE_MS:
                        self.last_error = "context-expired-before-publication"
                        continue
                    if self.timeline is None:
                        self.timeline = ContextTimeline()
                    profile = result.get("profile")
                    latest_frame, latest_png, _ = self.latest
                    masks = list(latest_frame.get("occluded_regions", []))
                    if isinstance(profile, dict) and popup_original is None and profile.get("bounds"):
                        masks.append(profile["bounds"])
                    if self.pending_invalidations and hasattr(self.timeline, "invalidate_fields"):
                        self.timeline.invalidate_fields(list(self.pending_invalidations))
                    self.pending_invalidations.clear()
                    seats = result.get("seats", [])
                    role = (result.get("evidence") or {}).get("role") or {}
                    caption = result.get("table_caption") or {}
                    checks = _region_checks(png, latest_png,
                        [s.get("bounds") for s in seats] + [role.get("bounds"), caption.get("bounds")], masks)
                    for seat, unchanged in zip(seats, checks):
                        if (capture["sequence"] <= self.invalidated.get(seat["seat"], -1)
                                or not unchanged):
                            seat.update(occupancy="unknown", identity=None, continuity="uncertain",
                                        status="unknown", stats=None, reason="source-region-changed-or-occluded")
                    if (capture["sequence"] <= self.invalidated.get("role", -1)
                            or not checks[-2]):
                        result.update(role="uncertain", hero_seat=None)
                    if (capture["sequence"] <= self.invalidated.get("caption", -1)
                            or caption.get("bounds") and not checks[-1]):
                        result["table_context_id"] = None
                    if profile:
                        current_profile = False
                        if popup_original is None:
                            # The mask covers underlying table fields, not visible popup text.
                            current_profile = _current_region(png, latest_png, profile.get("bounds"))
                        else:
                            hwnd = ((profile.get("capture") or {}).get("popup_window") or {}).get("hwnd")
                            for latest_popup, latest_popup_png in latest_frame.get("_popup_inputs", []):
                                if hwnd and (latest_popup.get("window") or {}).get("hwnd") == hwnd:
                                    current_profile = _current_region(popup_original, latest_popup_png, profile.get("bounds"))
                        if not current_profile:
                            result["profile"] = None
                            result["profile_rejection"] = "panel-changed-before-import"
                    value = self.timeline.observe(result)
                    value.update(schema_version=1, capture=capture,
                                 expires_at_unix_ms=capture["captured_at_unix_ms"] + CONTEXT_AGE_MS,
                                 requested_at_unix_ms=frame["context_requested_at_unix_ms"],
                                 attempt_started_at_unix_ms=attempt_started,
                                 completed_at_unix_ms=int(self.wall() * 1000),
                                 provisional=True, human_reviewed=False, quality_approved=False,
                                 processing_ms=round((time.perf_counter() - started) * 1000, 2),
                                 attempts=self.attempts, dropped_frames=self.dropped)
                # Never hold the feed-facing worker lock across storage or PNG encoding.
                if popup_original is not None and result.get("profile"):
                    profile = result["profile"]
                    self.archive.record(popup_original, profile["capture"], "profile-panel",
                        {"owner": profile.get("owner"), "metrics": profile.get("metrics")}, crops=[profile["bounds"]])
                profile = value.get("profile")
                if (popup_original is None and isinstance(profile, dict) and profile.get("owner")
                        and profile.get("status") == "provisional"
                        and any(s.get("stats", {}).get("capture") == capture
                                for s in value.get("seats", []) if isinstance(s.get("stats"), dict))):
                    # Each newly imported receipt needs immutable pixels, even when its values did not change.
                    self.archive.record(png, capture, "profile-observation",
                        {k: copy.deepcopy(profile.get(k)) for k in
                         ("owner", "seat", "occupant_epoch", "table_context_id", "metrics", "revision")},
                        original=filename if frame.get("archival") is True else None,
                        crops=[profile["bounds"]])
                changes = value.get("eventchanges", [])
                if changes:
                    bounds = [s["bounds"] for s in value.get("seats", []) if s.get("bounds")]
                    profile = value.get("profile")
                    if (isinstance(profile, dict) and profile.get("bounds")
                            and not (profile.get("capture") or {}).get("parent_capture")):
                        bounds.append(profile["bounds"])
                    event = self.archive.record(png, capture, "table-context", changes,
                        original=filename if frame.get("archival") is True else None, crops=bounds)
                    if event:
                        value["last_event_id"] = event["event_id"]
                with self.lock:
                    if scope != self.scope or self.closed.is_set():
                        continue
                    if self.invalidated.get("role", -1) >= capture["sequence"]:
                        value.update(role="uncertain", hero_seat=None)
                    if self.invalidated.get("caption", -1) >= capture["sequence"]:
                        value["table_context_id"] = None
                    for seat in value.get("seats", []):
                        stats = seat.get("stats")
                        if stats and (stats.get("capture") or {}).get("sha256") in self.archive.paths:
                            stats["evidence_id"] = stats["capture"]["sha256"]
                        if self.invalidated.get(seat["seat"], -1) >= capture["sequence"]:
                            seat.update(occupancy="unknown", identity=None, stats=None, continuity="uncertain", status="unknown")
                    self.value, self.original = value, png
                    self.deadline = self.monotonic() + max(0, (capture["captured_at_unix_ms"] + CONTEXT_AGE_MS - self.wall() * 1000) / 1000)
                    self.last_error = None
            except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError) as error:
                self.last_error = str(error)[:160]
            finally:
                self._log_attempt(capture, frame["context_requested_at_unix_ms"], attempt_started, value)
        if self.log is not None:
            self.log.close()

    def _log_attempt(self, capture, requested, started, value):
        record = {"schema_version": 1, "event": "context_attempt", "capture": capture,
                  "requested_at_unix_ms": requested, "attempt_started_at_unix_ms": started,
                  "completed_at_unix_ms": int(self.wall() * 1000), "error": self.last_error,
                  "role": (value or {}).get("role", "uncertain"),
                  "seats": [{k: seat.get(k) for k in ("seat", "occupancy", "identity", "occupant_epoch", "continuity", "status", "reason")}
                            for seat in (value or {}).get("seats", [])],
                  "profile": (value or {}).get("profile"), "dropped_frames": self.dropped}
        try:
            line = json.dumps(record, allow_nan=False, separators=(",", ":")).encode() + b"\n"
            if not self.log_complete or self.log_bytes + len(line) > MAX_LOG_BYTES:
                self.log_complete = False
                return
            if self.log is None:
                path = self.archive._private(self.archive.directory / "context.jsonl")
                path.parent.mkdir(parents=True, exist_ok=True)
                self.log = path.open("xb")
            self.log.write(line)
            self.log.flush()
            self.log_bytes += len(line)
        except (OSError, ValueError):
            self.log_complete = False

    def snapshot(self, state):
        with self.lock:
            if self.value is None or self.latest is None:
                return None
            value, original = copy.deepcopy(self.value), self.original
            frame, png, scope = self.latest
        capture = value["capture"]
        with self.lock:
            if self.deadline is None:
                self.deadline = self.monotonic() + max(0, (capture["captured_at_unix_ms"] + CONTEXT_AGE_MS - self.wall() * 1000) / 1000)
            expired = self.monotonic() >= self.deadline or int(self.wall() * 1000) >= capture["captured_at_unix_ms"] + CONTEXT_AGE_MS
            if expired:
                if self.value is not None and self.value["capture"] == capture:
                    self.value = None
                return None
        current, receipt = state.get("capture") or {}, state.get("capture_session") or {}
        if (receipt.get("status") != "capturing" or not current.get("fresh_capture")
                or current.get("source_id") != capture["source_id"] or current.get("epoch") != capture["epoch"]
                or state.get("session_id") != capture["session_id"]
                or (state.get("server") or {}).get("instance_id") != self.instance_id
                or [current.get("width"), current.get("height")] != [capture["width"], capture["height"]]
                or not 0 <= int(self.wall() * 1000) - capture["captured_at_unix_ms"] < CONTEXT_AGE_MS
                or scope != (capture["session_id"], capture["source_id"], capture["epoch"])):
            return None
        masks = list(frame.get("occluded_regions", []))
        profile = value.get("profile")
        if (isinstance(profile, dict) and not (profile.get("capture") or {}).get("parent_capture")
                and _current_region(original, png, profile.get("bounds"))):
            masks.append(profile["bounds"])
        seats = value.get("seats", [])
        role = (value.get("evidence") or {}).get("role") or {}
        checks = _region_checks(original, png, [s.get("bounds") for s in seats] + [role.get("bounds")], masks)
        for seat, unchanged in zip(seats, checks):
            if not unchanged:
                seat.update(occupancy="unknown", identity=None, continuity="uncertain", stats=None,
                            status="unknown", reason="identity-region-changed-or-occluded")
        if not checks[-1]:
            value.update(role="uncertain", hero_seat=None)
        value["events"] = self.archive.public_event_snapshot(capture["session_id"])
        value["event_evidence"] = self.archive.snapshot()
        value.setdefault("evidence", {}).update(complete=value["event_evidence"]["complete"],
                                                log_complete=self.log_complete)
        value["occluded_regions"] = masks
        return value

    def roster_for_frame(self, capture, png, masks):
        with self.lock:
            value, original = copy.deepcopy(self.value), self.original
            if self.deadline is not None and self.monotonic() >= self.deadline:
                return None
        if value is None or original is None or not 0 <= self.wall() * 1000 - value["capture"]["captured_at_unix_ms"] < CONTEXT_AGE_MS:
            return None
        previous = value["capture"]
        if (any(previous.get(key) != capture.get(key) for key in
                ("service_instance_id", "session_id", "source_id", "epoch", "width", "height"))
                or previous["sequence"] > capture["sequence"]):
            return None
        role = (value.get("evidence") or {}).get("role") or {}
        checks = _region_checks(original, png, [s.get("bounds") for s in value.get("seats", [])] + [role.get("bounds")], masks)
        for row, visible in zip(value.get("seats", []), checks):
            row["identity_capture"] = copy.deepcopy(previous)
            row["capture"] = copy.deepcopy(capture)
            if not visible:
                row.update(identity=None, stats=None, continuity="uncertain", status="unknown")
        if not checks[-1]:
            value.update(role="uncertain", hero_seat=None)
        value["capture"] = copy.deepcopy(capture)
        value["evidence"] = {"role": {**role, "capture": copy.deepcopy(capture), "origin_capture": copy.deepcopy(previous)}} if checks[-1] else {}
        return value

    def stop(self):
        self.closed.set()
        self.wake.set()
        if self.reader is not None and hasattr(self.reader, "close"):
            try:
                self.reader.close()
            except (OSError, ValueError, RuntimeError):
                self.last_error = "context-close-failed"
        if self.thread is not None:
            self.thread.join(timeout=3)
            if self.thread.is_alive():
                self.last_error = "context-shutdown-pending"


class VisualWorker:
    def __init__(self, root, instance_id, *, wall=time.time, monotonic=time.monotonic):
        self.root, self.instance_id, self.wall = Path(root).resolve(), instance_id, wall
        self.lock = threading.Lock()
        self.wake, self.closed = threading.Event(), threading.Event()
        self.pending = self.value = self.scope = self.last_frame = None
        self.dropped = 0
        self.board = self.actions = self.timeline = None
        self.log = None
        self.log_bytes = 0
        self.last_error = None
        self.thread = None
        from laya_evidence import EventEvidence
        self.archive = EventEvidence(self.root, instance_id)
        self.context = ContextWorker(self.root, instance_id, self.archive, wall=wall)
        self.numeric = NumericWorker(self.root, instance_id, self.archive, wall=wall, monotonic=monotonic)
        self.last_visual_signature = None
        self.latest_pixels = self.value_pixels = None
        self.monotonic, self.deadline, self.expired = monotonic, None, False
        self.last_ticket = self.processed_ticket = self.board_scope = None
        self.board_cache = None
        self.board_last_seen = [None] * 5
        self.board_invalidated = {}
        self.board_generation = 0
        self.revealed = None
        self.last_revealed_signature = None

    def submit(self, row, session_id, source_id, epoch):
        frame = row.get("frame")
        if not isinstance(frame, dict) or not source_id or type(epoch) is not int or epoch <= 0:
            return
        captured, sequence = frame.get("source_utc_unix_ms"), frame.get("frame_index")
        now = int(self.wall() * 1000)
        if (type(captured) is not int or not 0 <= now - captured < MAX_AGE_MS
                or type(sequence) is not int or sequence <= 0
                or not re.fullmatch(r"[a-f0-9]{64}", str(frame.get("sha256", "")))
                or type(frame.get("png_bytes")) is not int or not 0 < frame["png_bytes"] <= MAX_PNG_BYTES
                or not re.fullmatch(r"frame-[0-9]{10}\.png|live-frame-[01]\.png", str(frame.get("filename", "")))
                or type(frame.get("captured_at_monotonic_ms")) is not int
                or any(type(frame.get(k)) is not int or not 1 <= frame[k] <= 4096 for k in ("width", "height"))):
            return
        directory = Path(row.get("capture_directory", ""))
        from laya_capture import private_path
        directory = private_path(directory, root=self.root)
        if (directory.parent != self.root / ".local/captures"
                or not re.fullmatch(r"utc-[0-9]+-[0-9]{9}-practice", directory.name)):
            return
        filename = private_path(directory / frame["filename"], root=self.root)
        # Pin validated bytes now, before either async lane can race slot reuse.
        try:
            if filename.stat().st_size != frame["png_bytes"]:
                return
            png = filename.read_bytes()
            if len(png) != frame["png_bytes"] or hashlib.sha256(png).hexdigest() != frame["sha256"]:
                return
        except OSError:
            return
        frame = copy.deepcopy(frame)
        frame["capture_session_id"] = row.get("capture_session_id")
        frame["_popup_inputs"] = []
        for popup in frame.get("popup_frames", [])[:4]:
            if (not isinstance(popup, dict) or popup.get("parent_frame_index") != sequence
                    or popup.get("non_atomic") is not True
                    or type(popup.get("popup_index")) is not int or not 0 <= popup["popup_index"] < 4
                    or not re.fullmatch(r"live-popup-[01]-[0-3]\.png", str(popup.get("filename", "")))
                    or not re.fullmatch(r"[a-f0-9]{64}", str(popup.get("sha256", "")))
                    or type(popup.get("png_bytes")) is not int or not 0 < popup["png_bytes"] <= MAX_PNG_BYTES
                    or type(popup.get("captured_at_monotonic_ms")) is not int
                    or type(popup.get("source_utc_unix_ms")) is not int
                    or not 0 <= now - popup["source_utc_unix_ms"] < MAX_AGE_MS
                    or any(type(popup.get(k)) is not int or not 1 <= popup[k] <= 4096 for k in ("width", "height"))):
                continue
            try:
                popup_path = private_path(directory / popup["filename"], root=self.root)
                if popup_path.stat().st_size != popup["png_bytes"]:
                    continue
                popup_png = popup_path.read_bytes()
                if len(popup_png) == popup["png_bytes"] and hashlib.sha256(popup_png).hexdigest() == popup["sha256"]:
                    frame["_popup_inputs"].append((popup, popup_png))
            except OSError:
                continue
        scope = session_id, source_id, epoch
        with self.lock:
            ticket = (sequence, captured, frame["captured_at_monotonic_ms"])
            if self.scope == scope and self.last_ticket is not None and any(
                    new <= old for new, old in zip(ticket, self.last_ticket)):
                return
            if self.scope != scope:
                self.value = None
                self.scope, self.last_frame = scope, None
                self.board_last_seen, self.board_invalidated = [None] * 5, {}
                self.deadline, self.expired = None, False
            elif self.value is not None and self.value_pixels is not None:
                slots = self.value.get("board_slots", [])
                checks = _region_checks(self.value_pixels, png, [s.get("bounds") for s in slots],
                                        frame.get("occluded_regions", []))
                for slot, unchanged in zip(slots, checks):
                    if not unchanged or frame.get("readability") == "unknown":
                        self.board_invalidated[slot["slot"]] = self.value["sequence"]
            self.last_frame = sequence
            self.last_ticket = ticket
            self.latest_pixels = (frame, png)
            if self.pending is not None:
                self.dropped += 1
            self.pending = (frame, filename, scope, png)
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()
        self.wake.set()
        self.numeric.submit(frame, png, scope, filename)
        self.context.submit(frame, png, scope, filename)

    def _load(self):
        from laya_board import BoardTemplateRecognizer
        from laya_actions import ActionReader, ActionTimeline, CropTemplates
        board = BoardTemplateRecognizer.load(
            self.root / ".local/laya/dataset/exemplars.json",
            self.root / ".local/captures/20261009T170508Z-laya-train/derived/exemplars.npz",
            extra_bank_path=self.root / ".local/laya/board-pixel-bank-20261014.json"
                if (self.root / ".local/laya/board-pixel-bank-20261014.json").is_file() else None,
            evidence_root=self.root)
        self.regions = json.loads((self.root / "crates/ingest/assets/laya/regions.json").read_bytes())
        bank = CropTemplates.from_draft_review(
            self.root / ".local/laya/datasets/observing-20261010-v2-staging/human-review-20261010/labels.draft.json",
            self.root)
        self.board, self.actions, self.timeline = board, ActionReader(bank), ActionTimeline()
        from laya_showdown import RevealedCardReader
        self.revealed = RevealedCardReader(self.board, self.regions)

    def prepare(self):
        """Check actual CPU assets before choosing the independent-board schedule."""
        if self.closed.is_set():
            return False
        try:
            if self.board is None:
                self._load()
            if self.numeric.reader is None:
                try:
                    from laya_numeric import NumericReader
                    self.numeric.reader = NumericReader(self.root)
                except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError) as error:
                    self.numeric.last_error = str(error)[:120]
            return True
        except (OSError, ValueError, KeyError, TypeError, ImportError):
            return False

    def process(self, frame, filename, scope, png=None):
        from PIL import Image
        started = time.perf_counter()
        if self.board is None:
            self._load()
        if png is None:
            if filename.stat().st_size != frame["png_bytes"]:
                raise ValueError("frame-size-changed")
            png = filename.read_bytes()
        if len(png) != frame["png_bytes"] or hashlib.sha256(png).hexdigest() != frame["sha256"]:
            raise ValueError("frame-hash-changed")
        with Image.open(io.BytesIO(png)) as original:
            if list(original.size) != [frame["width"], frame["height"]]:
                raise ValueError("frame-geometry-changed")
            image = original.convert("RGB")
        if not 0 <= int(self.wall() * 1000) - frame["source_utc_unix_ms"] < MAX_AGE_MS:
            raise ValueError("frame-expired")
        session_id, source_id, epoch = scope
        capture = {**_capture(frame, scope, self.instance_id),
                   "source_process_created_at_100ns": frame.get("source_process_created_at_100ns"),
                   "generation": frame.get("generation"), "archival": frame.get("archival") is True,
                   "pixel_source": frame.get("pixel_source")}
        cache_key = frame["sha256"], image.size, json.dumps(self.regions, sort_keys=True)
        board_scope = (*scope, capture["capture_session_id"], capture["native_source_id"],
                       capture["source_process_created_at_100ns"], image.size, cache_key[2])
        ticket = (capture["sequence"], capture["captured_at_unix_ms"], capture["captured_at_ms"])
        with self.lock:
            if self.board_scope != board_scope:
                self.board_scope, self.processed_ticket = board_scope, None
                self.board_last_seen, self.board_invalidated = [None] * 5, {}
                self.board_generation += 1
            elif self.processed_ticket is not None and any(new <= old for new, old in zip(ticket, self.processed_ticket)):
                raise ValueError("replayed-frame-receipt")
            self.processed_ticket = ticket
        # Cache computation only. Identical PNGs with genuinely new original tickets
        # still receive their own clocks; replays cannot renew or confirm anything.
        if self.board_cache is None or self.board_cache[0] != cache_key:
            self.board_cache = cache_key, copy.deepcopy(self.board.recognize_frame(image, self.regions))
        board = copy.deepcopy(self.board_cache[1])
        board["source"] = "cpu-board-template"
        board["crop_generation"] = {"width": image.width, "height": image.height,
                                    "regions_sha256": hashlib.sha256(cache_key[2].encode()).hexdigest()}
        actions = self.actions.read(image, capture)
        masks = frame.get("occluded_regions", [])
        revealed = None
        if self.revealed is not None:
            roster = self.context.roster_for_frame(capture, png, masks)
            revealed = self.revealed.read(image, capture, occluded_regions=masks, roster=roster,
                                         table_context_id=(roster or {}).get("table_context_id"))
        board_slots = []
        for index in range(5):
            raw = (board.get("slots") or [])[index] if index < len(board.get("slots") or []) else {}
            crops = board.get("crop_bounds") or []
            bounds = raw.get("evidence_bounds", crops[index] if index < len(crops) else None)
            card = raw.get("card")
            status = "provisional" if isinstance(card, str) and re.fullmatch(r"[23456789TJQKA][shdc]", card) else "unknown"
            if status == "unknown" and raw.get("status") == "empty" and (raw.get("empty_surface") or {}).get("supported"):
                status = "empty"
            reason = raw.get("reason", "unmatched-card-ink")
            slot_capture = {**capture, "bounds": bounds, "crop_sha256": raw.get("evidence_pixel_sha256"),
                            "expires_at_unix_ms": capture["captured_at_unix_ms"] + MAX_AGE_MS}
            board_slots.append({"slot": index + 1, "card": card if status == "provisional" else None,
                                "status": status, "capture": slot_capture, "bounds": bounds, "reason": reason})
        checks = _region_checks(png, png, [s["bounds"] for s in board_slots], masks)
        for slot, readable in zip(board_slots, checks):
            if not readable or frame.get("readability") == "unknown":
                slot.update(card=None, status="occluded" if self._covered(slot["bounds"], masks) else "unknown",
                            reason="source-region-unreadable")
        duplicate = {s["card"] for s in board_slots if s["card"] and sum(
            other["card"] == s["card"] for other in board_slots) > 1}
        for slot in board_slots:
            if slot["card"] in duplicate:
                slot.update(card=None, status="unknown", reason="duplicate-card")
        if board.get("slots"):
            self._project_board(board, board_slots)
        if masks:
            for seat in actions.get("seats", []):
                for family in ("badge", "visible_wager"):
                    if (isinstance(seat.get(family), dict)
                            and not _current_region(png, png, seat[family].get("crop_bounds"), masks)):
                        seat[family].update(status="unknown", value=None, reason="client-popup-occlusion")
                        seat[family].pop("absence_evidence", None)
        timeline = self.timeline.observe(actions, now_ms=frame["captured_at_monotonic_ms"])
        # Sightings are retained as diagnostics, never promoted to betting order.
        sightings = [{"sequence": event["occurrence"], "seat": event["seat"], "action": event["action"],
                      "captured_at_ms": event["capture"]["captured_at_ms"],
                      "street": event["street"], "order_status": event["order_status"]}
                     for event in list(self.timeline.events)[-30:]
                     if (event["capture"]["session_id"], event["capture"]["source_id"], event["capture"]["epoch"]) == scope]
        with self.lock:
            changed = any(slot["card"] and old and slot["card"] != old["card"]
                          for slot, old in zip(board_slots, self.board_last_seen))
            if changed or board.get("empty_board_supported"):
                # A contradiction retires the old board, not a guessed hand/phase.
                if any(self.board_last_seen):
                    self.board_generation += 1
                self.board_last_seen = [None] * 5
            for index, slot in enumerate(board_slots):
                if slot["status"] == "provisional":
                    self.board_last_seen[index] = copy.deepcopy(slot)
                if ticket[0] > self.board_invalidated.get(index + 1, 0):
                    self.board_invalidated.pop(index + 1, None)
            board["board_generation"] = self.board_generation
            board["last_seen"] = self._last_seen_board()
        return {"schema_version": 1, "provisional": True, "quality_approved": False,
                "human_reviewed": False, "service_instance_id": self.instance_id,
                "session_id": session_id, "source_id": source_id, "epoch": epoch,
                "sequence": frame["frame_index"], "captured_at_unix_ms": frame["source_utc_unix_ms"],
                "captured_at_ms": frame["captured_at_monotonic_ms"],
                "expires_at_unix_ms": frame["source_utc_unix_ms"] + MAX_AGE_MS,
                "sha256": frame["sha256"], "width": frame["width"], "height": frame["height"],
                "archival": frame.get("archival") is True, "capture": capture,
                "board_slots": board_slots, "board": board, "actions": actions, "revealed_cards": revealed,
                "sightings": sightings, "gaps": timeline["gaps"], "dropped_frames": self.dropped,
                "processing_ms": round((time.perf_counter() - started) * 1000, 2)}

    def _project_board(self, board, slots):
        from laya_board import assemble_board
        cards, reason = assemble_board([{"state": "card_candidate" if s["status"] == "provisional" else
                                        "empty_candidate" if s["status"] == "empty" else "unknown",
                                        "card": s["card"]} for s in slots])
        board.update(candidate_cards=cards, reason=reason, empty_board_supported=cards == [],
                     stage={3: "flop", 4: "turn", 5: "river"}.get(len(cards)) if cards else None)
        for raw, slot in zip(board.get("slots", []), slots):
            raw.update(card=slot["card"], status=slot["status"], capture=copy.deepcopy(slot["capture"]),
                       source_current_reason=slot["reason"])

    def _covered(self, bounds, masks):
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 4 or any(type(x) is not int for x in bounds):
            return False
        return any(isinstance(m, (list, tuple)) and len(m) == 4 and all(type(x) is int for x in m)
                   and bounds[0] < m[2] and bounds[2] > m[0] and bounds[1] < m[3] and bounds[3] > m[1] for m in masks)

    def _last_seen_board(self):
        if not any(self.board_last_seen):
            return None
        slots = [dict(copy.deepcopy(s), status="last_seen", reason="aged-original-board") if s else
                 {"slot": index + 1, "card": None, "status": "unknown", "capture": None}
                 for index, s in enumerate(self.board_last_seen)]
        cards = [s["card"] for s in slots]
        count = next((i for i, card in enumerate(cards) if card is None), 5)
        candidate = cards[:count] if count in (3, 4, 5) and not any(cards[count:]) and len(set(cards[:count])) == count else None
        return {"status": "last_seen", "source": "cpu-board-template", "provisional": True,
                "quality_approved": False, "human_reviewed": False, "board_generation": self.board_generation,
                "hand_boundary": "unknown", "candidate_cards": candidate, "board_slots": slots}

    def _run(self):
        while not self.closed.is_set():
            self.wake.wait(0.2)
            self.wake.clear()
            with self.lock:
                pending, self.pending = self.pending, None
            if pending is None:
                continue
            frame, filename, scope, png = pending
            try:
                value = self.process(frame, filename, scope, png)
            except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
                value = None
                self.last_error = type(error).__name__
            if self.closed.is_set():
                continue
            with self.lock:
                if scope == self.scope and value is not None:
                    self.value = value
                    self.value_pixels = png
                    remaining = max(0, value["expires_at_unix_ms"] - int(self.wall() * 1000)) / 1000
                    self.deadline, self.expired = self.monotonic() + remaining, False
            if value is not None:
                signature = json.dumps([(value.get("board") or {}).get("candidate_cards"),
                    [(s.get("sequence"), s.get("seat"), s.get("action")) for s in value.get("sightings", [])]], sort_keys=True)
                if signature != self.last_visual_signature:
                    self.last_visual_signature = signature
                    current_sightings = [s for s in value.get("sightings", [])
                        if (s.get("capture") or {}).get("sequence") == value["sequence"]
                        and (s.get("capture") or {}).get("source_id") == value["source_id"]]
                    self.archive.record(png, _capture(frame, scope, self.instance_id), "visual-sighting",
                        {"board": value.get("board"), "sightings": current_sightings},
                        original=filename if frame.get("archival") is True else None)
                revealed = value.get("revealed_cards")
                if isinstance(revealed, dict):
                    exposed = [s for s in revealed.get("seats", []) if s.get("visible_face_count") or s.get("cards")]
                    signature = json.dumps([(s["seat"], s.get("cards"), s.get("visible_face_count"), s.get("identity"), s.get("occupant_epoch"))
                                            for s in exposed], sort_keys=True)
                    if signature != self.last_revealed_signature:
                        self.last_revealed_signature = signature
                        if exposed:
                            event = self.archive.record(png, value["capture"], "visible-seat-cards",
                                {"phase": revealed.get("phase", "unknown"), "seats": exposed},
                                original=filename if frame.get("archival") is True else None,
                                crops=[r["bounds"] for s in exposed for r in s.get("readings", []) if r.get("bounds")])
                            if event:
                                revealed["evidence_id"] = event["evidence_id"]
            if value is not None and frame.get("archival") is True:
                # The native archival prefix is bounded; the log shares that lifetime.
                try:
                    if self.log is None:
                        self.log = (filename.parent / "visual.jsonl").open("xb")
                    line = json.dumps(value, allow_nan=False, separators=(",", ":")).encode() + b"\n"
                    if self.log_bytes + len(line) <= MAX_LOG_BYTES:
                        self.log.write(line)
                        self.log.flush()
                        self.log_bytes += len(line)
                except (OSError, ValueError):
                    pass
        if self.log is not None:
            self.log.close()

    def snapshot(self, state, *, occluded_regions=()):
        with self.lock:
            value = copy.deepcopy(self.value)
            original, latest = self.value_pixels, self.latest_pixels
            invalidated = dict(self.board_invalidated)
            history = self._last_seen_board()
            expired = self.expired or (self.deadline is not None and self.monotonic() >= self.deadline)
        if value is None:
            return None
        capture, receipt = state.get("capture") or {}, state.get("capture_session") or {}
        if (receipt.get("status") != "capturing"
                or (state.get("server") or {}).get("instance_id") != self.instance_id
                or capture.get("source_id") != value["source_id"] or capture.get("epoch") != value["epoch"]
                or [capture.get("width"), capture.get("height")] != [value["width"], value["height"]]
                or state.get("session_id") != value["session_id"]
                or (receipt.get("session_id") is not None and value.get("capture", {}).get("capture_session_id") is not None
                    and receipt["session_id"] != value["capture"]["capture_session_id"])):
            return None
        expired = expired or not 0 <= int(self.wall() * 1000) - value["captured_at_unix_ms"] < MAX_AGE_MS
        if expired:
            with self.lock:
                if self.value is not None and self.value.get("sequence") == value["sequence"]:
                    self.expired = True
        stale = expired or not capture.get("fresh_capture")
        if stale and history is None:
            return None
        slots = value.get("board_slots", [])
        board = value.get("board") or {}
        board["last_seen"] = history
        checks = [not stale] * len(slots)
        masks = list(occluded_regions)
        if original is not None and latest is not None:
            frame, png = latest
            source = value.get("capture") or {}
            if (source.get("native_source_id") != (str(frame["source_id"]) if frame.get("source_id") is not None else None)
                    or source.get("source_process_created_at_100ns") != frame.get("source_process_created_at_100ns")
                    or source.get("capture_session_id") != frame.get("capture_session_id")):
                return None
            masks = [*frame.get("occluded_regions", []), *occluded_regions]
            fields = [seat[family] for seat in (value.get("actions") or {}).get("seats", [])
                      for family in ("badge", "visible_wager") if isinstance(seat.get(family), dict)]
            regions = _region_checks(original, png, [s.get("bounds") for s in slots] + [f.get("crop_bounds") for f in fields], masks)
            checks = [not stale and frame.get("readability") != "unknown" and unchanged
                      for unchanged in regions[:len(slots)]]
            for field, unchanged in zip(fields, regions[len(slots):]):
                if stale or not unchanged:
                    field.update(value=None, status="unknown", reason="region-changed-or-occluded")
                    field.pop("absence_evidence", None)
            revealed = value.get("revealed_cards")
            if isinstance(revealed, dict):
                for seat in revealed.get("seats", []):
                    readings = seat.get("readings", [])
                    visible = _region_checks(original, png, [r.get("bounds") for r in readings], masks)
                    for reading, unchanged in zip(readings, visible):
                        if stale or not unchanged:
                            reading.update(card=None, status="unknown", reason="revealed-region-changed-or-occluded")
                    seat["cards"] = [r["card"] for r in readings if r.get("card")]
                    if stale or len(seat["cards"]) < 2:
                        seat.update(status="unknown", reason="incomplete-current-revealed-pair")
                    if stale:
                        seat["visible_face_count"] = 0
                if stale:
                    revealed.update(phase="unknown", phase_evidence=None)
        elif masks and slots:
            checks = _region_checks(original, original, [s.get("bounds") for s in slots], masks)
        for slot, unchanged in zip(slots, checks):
            if not unchanged:
                with self.lock:
                    if self.value is not None and self.value.get("sequence") == value["sequence"]:
                        self.board_invalidated[slot["slot"]] = value["sequence"]
            if stale or not unchanged or value["sequence"] <= invalidated.get(slot["slot"], 0):
                covered = self._covered(slot.get("bounds"), masks)
                slot.update(card=None, status="occluded" if covered else "unknown",
                            reason="source-frame-expired" if stale else "source-region-changed-or-occluded")
        if slots:
            self._project_board(board, slots)
        value["current_uncertain"] = stale
        return value

    def mask_snapshot(self, snapshot, context):
        """Suppress only covered API regions; do not change source leases/history."""
        masks = (context or {}).get("occluded_regions", [])
        observation = snapshot.get("partial_observation")
        if not masks or not observation:
            return
        from laya_prep import box_px
        regions = getattr(self, "regions", {}).get("regions", {})
        width, height = (snapshot.get("capture") or {}).get("width"), (snapshot.get("capture") or {}).get("height")
        if not regions or type(width) is not int or type(height) is not int:
            return
        statuses = observation.get("field_statuses", {})

        def covered(key):
            roi = regions.get(key)
            if not roi:
                return False
            l, t, r, b = box_px(roi, width, height)
            return any(l < m[2] and r > m[0] and t < m[3] and b > m[1] for m in masks)

        def unavailable(path):
            statuses[path] = {"status": "unavailable", "reason": "occluded"}
            snapshot.get("field_statuses", {})[path] = dict(statuses[path])

        if covered("pot"):
            observation.update(pot_size=None, pot_size_text=None)
            unavailable("pot_size")
        for index in range(5):
            if covered("board_slot_" + str(index + 1)):
                observation["board_slots"][index] = None
                observation["board_count"] = None
                unavailable("board_slots." + str(index + 1))
                unavailable("board")
                unavailable("board_count")
        for seat in observation.get("seats", []):
            number = seat["seat"]
            if covered("seat_" + str(number) + "_stack"):
                seat.update(displayed_stack=None, displayed_stack_text=None)
                unavailable("seats." + str(number) + ".displayed_stack")

    def stop(self):
        self.closed.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join(timeout=3)
        self.context.stop()
        self.numeric.stop()
        if ((self.thread is None or not self.thread.is_alive())
                and (self.context.thread is None or not self.context.thread.is_alive())
                and (self.numeric.thread is None or not self.numeric.thread.is_alive())):
            self.archive.close()
