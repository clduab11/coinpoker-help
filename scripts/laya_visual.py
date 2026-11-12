"""Source-bound CPU visual diagnostics, separate from admitted model readings."""

import copy
import hashlib
import io
import json
from pathlib import Path
import re
import threading
import time
import uuid
from collections import deque

from laya_prep import box_px, load_regions

MAX_AGE_MS = 1500
MAX_PNG_BYTES = 8 * 1024 * 1024
MAX_LOG_BYTES = 8 * 1024 * 1024
CONTEXT_AGE_MS = 5000


class _LaneProjection(dict):
    def __init__(self, value, deadline):
        super().__init__(value)
        self.deadline = deadline


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
        self.busy = threading.Event()
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
            self.busy.set()
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
                    if (scope != self.scope or self.closed.is_set() or capture["sequence"] < self.first_watermark
                            or self.monotonic() >= frame.get("_visual_deadline", float("inf"))):
                        continue
                    self.value, self.original = value, png
                    self.deadline = min(frame.get("_visual_deadline", float("inf")),
                        self.monotonic() + (capture["captured_at_unix_ms"] + MAX_AGE_MS - now) / 1000)
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
                self.busy.clear()

    def snapshot(self, state, *, occluded_regions=()):
        with self.lock:
            if self.closed.is_set():
                return None
            value, original, latest = copy.deepcopy(self.value), self.original, self.latest
            deadline = self.deadline
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
        return _LaneProjection(value, deadline)

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
        self.busy = threading.Event()
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
        self.first_watermark = -1

    def submit(self, frame, png, scope, filename):
        frame = {**frame, "context_requested_at_unix_ms": int(self.wall() * 1000)}
        with self.lock:
            if self.closed.is_set():
                return
            if self.scope != scope:
                self.scope, self.value, self.timeline = scope, None, None
                self.invalidated, self.pending_invalidations, self.deadline = {}, set(), None
                self.first_watermark = -1
            if self.value is None:
                self.first_watermark = frame["frame_index"]
            else:
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
            self.busy.set()
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
                    if (scope != self.scope or self.closed.is_set() or capture["sequence"] < self.first_watermark
                            or self.monotonic() >= frame.get("_context_deadline", float("inf"))):
                        continue
                    if not 0 <= int(self.wall() * 1000) - capture["captured_at_unix_ms"] < CONTEXT_AGE_MS:
                        self.last_error = "context-expired-before-publication"
                        continue
                    staged_timeline = copy.deepcopy(self.timeline) if self.timeline is not None else ContextTimeline()
                    profile = result.get("profile")
                    latest_frame, latest_png, _ = self.latest
                    masks = list(latest_frame.get("occluded_regions", []))
                    if isinstance(profile, dict) and popup_original is None and profile.get("bounds"):
                        masks.append(profile["bounds"])
                    pending_invalidations = {key: self.invalidated.get(key, -1) for key in self.pending_invalidations}
                    if pending_invalidations and hasattr(staged_timeline, "invalidate_fields"):
                        staged_timeline.invalidate_fields(list(pending_invalidations))
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
                    value = staged_timeline.observe(result)
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
                    if (scope != self.scope or self.closed.is_set() or capture["sequence"] < self.first_watermark
                            or self.monotonic() >= frame.get("_context_deadline", float("inf"))
                            or not 0 <= self.wall() * 1000 - capture["captured_at_unix_ms"] < CONTEXT_AGE_MS):
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
                    self.timeline = staged_timeline
                    self.pending_invalidations.difference_update(key for key, version in pending_invalidations.items()
                        if self.invalidated.get(key, -1) == version)
                    self.value, self.original = value, png
                    self.deadline = min(frame.get("_context_deadline", float("inf")),
                        self.monotonic() + max(0, (capture["captured_at_unix_ms"] + CONTEXT_AGE_MS - self.wall() * 1000) / 1000))
                    self.last_error = None
            except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError) as error:
                self.last_error = str(error)[:160]
            finally:
                self._log_attempt(capture, frame["context_requested_at_unix_ms"], attempt_started, value)
                self.busy.clear()
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
            if not self.log_complete or self.log_bytes + len(line) > getattr(self, "log_limit", MAX_LOG_BYTES):
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
            if self.deadline is None:
                self.deadline = self.monotonic() + max(0, (capture["captured_at_unix_ms"] + CONTEXT_AGE_MS - self.wall() * 1000) / 1000)
            deadline = self.deadline
            expired = self.monotonic() >= deadline or int(self.wall() * 1000) >= capture["captured_at_unix_ms"] + CONTEXT_AGE_MS
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
        return _LaneProjection(value, deadline)

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
        if self.thread is not None:
            self.thread.join(timeout=3)
            if self.thread.is_alive():
                self.last_error = "context-shutdown-pending"
                return False
        if self.reader is not None and hasattr(self.reader, "close"):
            try:
                self.reader.close()
            except (OSError, ValueError, RuntimeError):
                self.last_error = "context-close-failed"
                return False
        return True


class VisualLanes:
    def __init__(self, root, instance_id, *, wall=time.time, monotonic=time.monotonic):
        self.root, self.instance_id, self.wall = Path(root).resolve(), instance_id, wall
        self.lock = threading.Lock()
        self.wake, self.closed = threading.Event(), threading.Event()
        self.busy = threading.Event()
        self.pending = self.value = self.scope = self.last_frame = None
        self.dropped = 0
        self.board = self.actions = self.timeline = None
        self.log = None
        self.log_bytes = 0
        self.log_complete = True
        self.last_error = None
        self.thread = None
        from laya_evidence import EventEvidence
        self.archive = EventEvidence(self.root, instance_id)
        self.context = ContextWorker(self.root, instance_id, self.archive, wall=wall, monotonic=monotonic)
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
        self.first_watermark = -1

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
        from laya_capture import _canonical, private_path
        directory = private_path(directory, root=self.root)
        canonical_directory = _canonical(directory)
        if (canonical_directory.parent != _canonical(self.root / ".local/captures")
                or not re.fullmatch(r"utc-[0-9]+-[0-9]{9}-practice", canonical_directory.name)):
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
        self.submit_pinned(frame, filename, scope, png)

    def submit_pinned(self, frame, filename, scope, png):
        frame = {**frame, "_lane_managed": True}
        sequence, captured = frame["frame_index"], frame["source_utc_unix_ms"]
        with self.lock:
            if self.closed.is_set():
                return
            ticket = (sequence, captured, frame["captured_at_monotonic_ms"])
            if self.scope == scope and self.last_ticket is not None and any(
                    new <= old for new, old in zip(ticket, self.last_ticket)):
                return
            if self.scope != scope:
                self.value = None
                self.scope, self.last_frame = scope, None
                self.board_last_seen, self.board_invalidated = [None] * 5, {}
                self.deadline, self.expired = None, False
                self.first_watermark = -1
            if self.value is None:
                self.first_watermark = sequence
            elif self.value_pixels is not None:
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
        from laya_prep import load_regions
        board = BoardTemplateRecognizer.load(
            self.root / ".local/laya/dataset/exemplars.json",
            self.root / ".local/captures/20261009T170508Z-laya-train/derived/exemplars.npz",
            extra_bank_path=self.root / ".local/laya/board-pixel-bank-20261014.json"
                if (self.root / ".local/laya/board-pixel-bank-20261014.json").is_file() else None,
            evidence_root=self.root)
        self.regions = load_regions(self.root)
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
            if self.board_scope == board_scope and self.processed_ticket is not None and any(new <= old for new, old in zip(ticket, self.processed_ticket)):
                raise ValueError("replayed-frame-receipt")
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
        with self.lock:
            if frame.get("_lane_managed") and (self.closed.is_set() or scope != self.scope
                    or capture["sequence"] < self.first_watermark
                    or self.monotonic() >= frame.get("_visual_deadline", float("inf"))):
                raise ValueError("superseded-or-expired-visual-work")
            staged_timeline = copy.deepcopy(self.timeline)
        timeline = staged_timeline.observe(actions, now_ms=frame["captured_at_monotonic_ms"])
        # Sightings are retained as diagnostics, never promoted to betting order.
        sightings = [{"sequence": event["occurrence"], "seat": event["seat"], "action": event["action"],
                      "captured_at_ms": event["capture"]["captured_at_ms"],
                      "street": event["street"], "order_status": event["order_status"]}
                      for event in list(staged_timeline.events)[-30:]
                      if (event["capture"]["session_id"], event["capture"]["source_id"], event["capture"]["epoch"]) == scope]
        stage = board_scope, ticket, staged_timeline, board_slots
        with self.lock:
            if frame.get("_lane_managed") and (self.closed.is_set() or scope != self.scope
                    or capture["sequence"] < self.first_watermark
                    or self.monotonic() >= frame.get("_visual_deadline", float("inf"))):
                raise ValueError("superseded-or-expired-visual-work")
            if not frame.get("_lane_managed"):
                self._commit_board(board, stage)
        value = {"schema_version": 1, "provisional": True, "quality_approved": False,
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
        if frame.get("_lane_managed"):
            value["_visual_commit"] = stage
        return value

    def _commit_board(self, board, stage):
        # Caller owns the lane lock; managed work commits with its public value.
        board_scope, ticket, staged_timeline, board_slots = stage
        if self.board_scope != board_scope:
            self.board_scope, self.processed_ticket = board_scope, None
            self.board_last_seen, self.board_invalidated = [None] * 5, {}
            self.board_generation += 1
        elif self.processed_ticket is not None and any(new <= old for new, old in zip(ticket, self.processed_ticket)):
            raise ValueError("replayed-frame-receipt")
        self.processed_ticket, self.timeline = ticket, staged_timeline
        changed = any(slot["card"] and old and slot["card"] != old["card"]
                      for slot, old in zip(board_slots, self.board_last_seen))
        if changed or board.get("empty_board_supported"):
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
            self.busy.set()
            try:
                value = self.process(frame, filename, scope, png)
            except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError) as error:
                value = None
                self.last_error = type(error).__name__
            if self.closed.is_set():
                self.busy.clear()
                continue
            with self.lock:
                if (scope == self.scope and not self.closed.is_set() and value is not None
                        and frame["frame_index"] >= self.first_watermark
                        and self.monotonic() < frame.get("_visual_deadline", float("inf"))
                        and 0 <= self.wall() * 1000 - frame["source_utc_unix_ms"] < MAX_AGE_MS):
                    stage = value.pop("_visual_commit", None)
                    try:
                        if stage is not None:
                            self._commit_board(value["board"], stage)
                    except ValueError as error:
                        self.last_error, value = str(error), None
                    if value is not None:
                        self.value = value
                        self.value_pixels = png
                        remaining = max(0, value["expires_at_unix_ms"] - int(self.wall() * 1000)) / 1000
                        self.deadline, self.expired = min(frame.get("_visual_deadline", float("inf")),
                            self.monotonic() + remaining), False
                else:
                    value = None
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
                    line = json.dumps(value, allow_nan=False, separators=(",", ":")).encode() + b"\n"
                    if self.log_complete and self.log_bytes + len(line) <= getattr(self, "log_limit", MAX_LOG_BYTES):
                        if self.log is None:
                            self.archive.directory.mkdir(parents=True, exist_ok=True)
                            self.log = (self.archive.directory / "visual.jsonl").open("xb")
                        self.log.write(line)
                        self.log.flush()
                        self.log_bytes += len(line)
                    else:
                        self.log_complete = False
                except (OSError, ValueError):
                    self.log_complete = False
            self.busy.clear()
        if self.log is not None:
            self.log.close()

    def snapshot(self, state, *, occluded_regions=()):
        with self.lock:
            value = copy.deepcopy(self.value)
            deadline = self.deadline
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
        return _LaneProjection(value, deadline)

    def mask_snapshot(self, snapshot, context):
        """Suppress only covered API regions; do not change source leases/history."""
        masks = (context or {}).get("occluded_regions", [])
        fields = (context or {}).get("covered_fields", ())
        observation = snapshot.get("partial_observation")
        if not (masks or fields) or not observation:
            return
        regions = getattr(self, "regions", {}).get("regions", {})
        width, height = (snapshot.get("capture") or {}).get("width"), (snapshot.get("capture") or {}).get("height")
        if not regions or type(width) is not int or type(height) is not int:
            return
        statuses = observation.get("field_statuses", {})

        def covered(key):
            if key in fields:
                return True
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

    def revoke(self):
        # Close every lane before any join, including a blocked recognizer/store.
        self.closed.set()
        self.wake.set()
        self.context.closed.set()
        self.context.wake.set()
        self.numeric.closed.set()
        self.numeric.wake.set()

    def stop(self):
        self.revoke()
        if self.thread is not None:
            self.thread.join(timeout=3)
        self.context.stop()
        self.numeric.stop()
        if ((self.thread is None or not self.thread.is_alive())
                and (self.context.thread is None or not self.context.thread.is_alive())
                and (self.numeric.thread is None or not self.numeric.thread.is_alive())):
            self.archive.close()


_mask_native_snapshot = VisualLanes.mask_snapshot


class _VisualProjection(dict):
    """DTO plus a non-serialized completion stamp for the ordered feed fence."""
    def __init__(self, value, binding, token, serial, leases):
        super().__init__(value)
        self.binding, self.token, self.serial = binding, token, serial
        self.leases = leases


class _VisualArchiveView:
    """Serve only the active runtime index, including a final read-completion fence."""
    def __init__(self, owner):
        self.owner = owner

    def read(self, evidence_id):
        with self.owner.lock:
            engine, token = self.owner.engine, self.owner.token
            if engine is None or token is None or token.is_set():
                return None
            engine.archive_readers += 1
            engine.archive_readers_done.clear()
        try:
            png = engine.archive.read(evidence_id)
            with self.owner.lock:
                return png if self.owner.engine is engine and self.owner.token is token and not token.is_set() else None
        finally:
            with self.owner.lock:
                engine.archive_readers -= 1
                if not engine.archive_readers:
                    engine.archive_readers_done.set()
            self.owner.wake.set()

    def snapshot(self):
        with self.owner.lock:
            engine, token = self.owner.engine, self.owner.token
        value = (engine.archive if engine is not None else self.owner._empty_archive).snapshot()
        with self.owner.lock:
            return value if self.owner.engine is engine and token is self.owner.token else self.owner._empty_archive.snapshot()

    def event_snapshot(self):
        with self.owner.lock:
            engine, token = self.owner.engine, self.owner.token
        events = engine.archive.event_snapshot() if engine is not None else []
        with self.owner.lock:
            return events if self.owner.engine is engine and token is self.owner.token and token is not None and not token.is_set() else []


class VisualWorker:
    """Bounded transport boundary around the three independent recognition lanes.

    Only this pump reads mailbox paths or builds pixel-dependent projections.
    Retired engines have isolated archives: their late files/logs are uncommitted
    diagnostics, never indexed or served by a replacement engine. Python cannot
    cancel a blocked reader; at most one retiring engine is retained, and further
    work stays in the single replaceable slot until that engine actually exits.
    """
    def __init__(self, root, instance_id, *, wall=time.time, monotonic=time.monotonic):
        self.root, self.instance_id = Path(root).resolve(), instance_id
        try:
            self.region_manifest = load_regions(self.root)
        except (OSError, ValueError):
            self.region_manifest = {}
        self.wall, self.monotonic = wall, monotonic
        self.lock = threading.Lock()
        self.wake, self.closed = threading.Event(), threading.Event()
        self.thread = self.pending = self.engine = self.retiring = None
        self.binding = self.token = None
        self.serial = self.validated = 0
        self.executing = False
        self.cache, self.leases = {}, {}
        self.expired_captures = {}
        self.last_seen = None
        self.last_projection = None
        self.counts, self.stages = {}, deque(maxlen=100)
        self.retirement_reason = None
        self.last_error = None
        self._fingerprint = None
        self._cleanup_started = False
        self.shutdown_complete = threading.Event()
        self.regions, self.mask_regions, self.mask_fields = self.region_manifest, [], set()
        self.mask_mapping_incomplete = False
        self.used_budget = {"bytes": 0, "frames": 0, "log_bytes": 0, "context_log_bytes": 0, "visual_log_bytes": 0}
        self.storage_incomplete = {"archive": False, "context_log": False, "visual_log": False}
        self.namespace_history = deque(maxlen=32)
        self.namespace_overflow = 0
        from laya_evidence import EventEvidence
        self._empty_archive = EventEvidence(self.root, instance_id)
        self._archive_view = _VisualArchiveView(self)

    @property
    def archive(self):
        return self._archive_view

    def _drop(self, reason):
        self.counts[reason] = self.counts.get(reason, 0) + 1

    def _retire(self, reason):
        if self.token is not None:
            self.token.set()
        if self.engine is not None:
            self.engine.revoke()
            if len(self.namespace_history) == self.namespace_history.maxlen:
                self.namespace_overflow += 1
            self.namespace_history.append(self._namespace(self.engine, "retired-uncommitted", reason))
            self.retiring, self.engine = self.engine, None
        self.cache, self.leases = {}, {}
        self.expired_captures = {}
        self._fingerprint = None
        self.validated = 0
        self.retirement_reason = reason

    def revoke(self, reason="retired-binding"):
        with self.lock:
            self._retire(reason)
            self.token = self.pending = None
            if reason != "native-capture-unavailable":
                self.binding = None
                self.last_seen = self.last_projection = None
                self.regions, self.mask_regions, self.mask_fields = self.region_manifest, [], set()
                self.mask_mapping_incomplete = False
                self.namespace_history.clear()
                self.namespace_overflow = 0
        self.wake.set()

    @staticmethod
    def _metadata(row, session_id, source_id, epoch, now):
        frame = row.get("frame")
        if (not isinstance(frame, dict) or not source_id or not session_id
                or type(epoch) is not int or epoch <= 0
                or not isinstance(row.get("capture_session_id"), str) or not 0 < len(row["capture_session_id"]) <= 128):
            return None
        captured, sequence = frame.get("source_utc_unix_ms"), frame.get("frame_index")
        if (type(captured) is not int or not 0 <= now - captured < MAX_AGE_MS
                or type(sequence) is not int or not 0 < sequence < 2 ** 53
                or any(type(frame.get(k)) is not int or not 0 < frame[k] < 2 ** 64
                       for k in ("source_id", "source_process_created_at_100ns"))
                or not isinstance(row.get("capture_directory"), str) or len(row["capture_directory"]) > 4096
                or not isinstance(frame.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", frame["sha256"])
                or type(frame.get("png_bytes")) is not int or not 0 < frame["png_bytes"] <= MAX_PNG_BYTES
                or not re.fullmatch(r"frame-[0-9]{10}\.png|live-frame-[01]\.png", str(frame.get("filename", "")))
                or type(frame.get("captured_at_monotonic_ms")) is not int or frame["captured_at_monotonic_ms"] < 0
                or any(type(frame.get(k)) is not int or not 1 <= frame[k] <= 4096 for k in ("width", "height"))
                or not isinstance(frame.get("popup_frames", []), list) or len(frame.get("popup_frames", [])) > 4
                or not isinstance(frame.get("occluded_regions", []), list) or len(frame.get("occluded_regions", [])) > 64):
            return None
        return (session_id, row.get("capture_session_id"), source_id, epoch,
                frame.get("source_id"), frame.get("source_process_created_at_100ns"), frame["width"], frame["height"])

    def submit(self, row, session_id, source_id, epoch):
        now, received = int(self.wall() * 1000), self.monotonic()
        row = row if isinstance(row, dict) else {}
        copied = {"frame": copy.deepcopy(row.get("frame")), "capture_directory": row.get("capture_directory"),
                  "capture_session_id": row.get("capture_session_id")}
        binding = self._metadata(copied, session_id, source_id, epoch, now)
        with self.lock:
            if self.closed.is_set():
                return
            if binding is None:
                # Unvalidated metadata is not proof that the pixels were unchanged.
                self._retire("unvalidated-metadata")
                self.pending = None
                captured = (copied["frame"] or {}).get("source_utc_unix_ms") if isinstance(copied["frame"], dict) else None
                self._drop("expired" if type(captured) is int and now - captured >= MAX_AGE_MS else "invalid-metadata")
                return
            frame = copied["frame"]
            ticket = (frame["frame_index"], frame["source_utc_unix_ms"], frame["captured_at_monotonic_ms"])
            if binding == self.binding and hasattr(self, "ticket") and any(n <= o for n, o in zip(ticket, self.ticket)):
                self._retire("replayed-metadata")
                self.pending = None
                self._drop("invalid-metadata")
                return
            if binding != self.binding:
                self._retire("binding-replaced")
                self.binding, self.token, self.last_seen = binding, threading.Event(), None
                self.last_projection = None
                self.regions, self.mask_regions, self.mask_fields = self.region_manifest, [], set()
                self.mask_mapping_incomplete = False
                self.namespace_history.clear()
                self.namespace_overflow = 0
            elif self.pending is not None or self.executing:
                self._drop("superseded")
                self._retire("superseded-continuity")
                self.token = threading.Event()
            elif self.token is None or self.token.is_set():
                self.token = threading.Event()
            self.ticket = ticket
            masks = frame.get("occluded_regions", [])
            if all(isinstance(m, list) and len(m) == 4 and all(type(v) is int for v in m)
                   and 0 <= m[0] < m[2] <= frame["width"] and 0 <= m[1] < m[3] <= frame["height"] for m in masks):
                self.mask_regions = self._merge_masks(self.mask_regions, masks, frame["width"], frame["height"])
            self.serial += 1
            copied["frame"]["_visual_deadline"] = received + (captured_remaining := MAX_AGE_MS - (now - ticket[1])) / 1000
            copied["frame"]["_context_deadline"] = received + (captured_remaining + CONTEXT_AGE_MS - MAX_AGE_MS) / 1000
            self.pending = (copied, binding, self.token, self.serial, received)
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name="visual-ingress", daemon=True)
                self.thread.start()
        self.wake.set()

    def _pin(self, row):
        from laya_capture import _canonical, private_path
        from PIL import Image
        directory = private_path(Path(row["capture_directory"]), root=self.root)
        canonical_directory = _canonical(directory)
        if (canonical_directory.parent != _canonical(self.root / ".local/captures")
                or not re.fullmatch(r"utc-[0-9]+-[0-9]{9}-practice", canonical_directory.name)):
            raise ValueError("invalid-capture-path")
        frame = row["frame"]
        def read(metadata):
            path = private_path(directory / metadata["filename"], root=self.root)
            if path.parent != directory:
                raise ValueError("invalid-capture-path")
            # One bounded read from the original slot, never a later reopen downstream.
            if path.stat().st_size != metadata["png_bytes"]:
                raise ValueError("slot-overwritten/hash-mismatch")
            with path.open("rb") as stream:
                png = stream.read(metadata["png_bytes"] + 1)
            if len(png) != metadata["png_bytes"] or hashlib.sha256(png).hexdigest() != metadata["sha256"]:
                raise ValueError("slot-overwritten/hash-mismatch")
            with Image.open(io.BytesIO(png)) as image:
                if image.size != (metadata["width"], metadata["height"]):
                    raise ValueError("frame-geometry-changed")
                image.load()
            return path, png
        filename, png = read(frame)
        frame["capture_session_id"] = row.get("capture_session_id")
        # A mailbox is never an immutable archival original, regardless of flags.
        if frame["filename"].startswith("live-"):
            frame["archival"] = False
        frame["_popup_inputs"] = []
        for popup in frame.get("popup_frames", []):
            if (not isinstance(popup, dict) or popup.get("parent_frame_index") != frame["frame_index"]
                    or popup.get("non_atomic") is not True
                    or type(popup.get("popup_index")) is not int or not 0 <= popup["popup_index"] < 4
                    or not re.fullmatch(r"live-popup-[01]-[0-3]\.png", str(popup.get("filename", "")))
                    or not re.fullmatch(r"[a-f0-9]{64}", str(popup.get("sha256", "")))
                    or type(popup.get("png_bytes")) is not int or not 0 < popup["png_bytes"] <= MAX_PNG_BYTES
                    or any(type(popup.get(k)) is not int or popup[k] < 0 for k in
                           ("source_utc_unix_ms", "captured_at_monotonic_ms"))
                    or not 0 <= self.wall() * 1000 - popup["source_utc_unix_ms"] < MAX_AGE_MS
                    or any(type(popup.get(k)) is not int or not 1 <= popup[k] <= 4096 for k in ("width", "height"))):
                raise ValueError("invalid-popup-metadata")
            _, popup_png = read(popup)
            frame["_popup_inputs"].append((popup, popup_png))
        if self.monotonic() >= frame["_visual_deadline"] or not 0 <= self.wall() * 1000 - frame["source_utc_unix_ms"] < MAX_AGE_MS:
            raise ValueError("expired")
        return frame, filename, png

    @staticmethod
    def _alive(engine):
        return getattr(engine, "archive_readers", 0) > 0 or any(worker.thread is not None and worker.thread.is_alive()
                   for worker in (engine, engine.numeric, engine.context))

    def _merge_masks(self, old, new, width, height):
        masks = [list(m) for m in old]
        masks.extend(list(m) for m in new if list(m) not in masks)
        if len(masks) <= 64:
            return masks
        regions = self.regions.get("regions", {})
        if not regions:
            # Do not invent coverage when the ROI catalog itself is unavailable.
            self.mask_mapping_incomplete = True
            return masks[-64:]
        keys = ["pot", *("board_slot_" + str(i) for i in range(1, 6)),
                *("seat_" + str(i) + "_stack" for i in range(1, 7))]
        for key in keys:
            if key not in regions:
                continue
            l, t, r, b = box_px(regions[key], width, height)
            if any(l < m[2] and r > m[0] and t < m[3] and b > m[1] for m in masks):
                self.mask_fields.add(key)
        return []

    def _dispose(self, engine):
        # Readers can own OS subprocesses. Dispose them before releasing the
        # retirement slot, never as a final-reference side effect under lock.
        try:
            if engine.context.stop() is False:
                raise RuntimeError("reader-close-failed")
            engine.context.reader = None
            engine.archive.close()
        except (OSError, ValueError, RuntimeError):
            with self.lock:
                self.last_error = "visual-retirement-close-failed"
            return False
        with self.lock:
            self.storage_incomplete["archive"] |= not engine.archive.complete
            self.storage_incomplete["context_log"] |= not engine.context.log_complete
            self.storage_incomplete["visual_log"] |= not engine.log_complete
            for key, value in (("bytes", engine.archive.bytes), ("frames", len(engine.archive.receipts)),
                               ("log_bytes", engine.archive.log_bytes), ("context_log_bytes", engine.context.log_bytes),
                               ("visual_log_bytes", engine.log_bytes)):
                self.used_budget[key] += value
            for namespace in self.namespace_history:
                if namespace["namespace_id"] == engine.archive.directory.name:
                    namespace["workers_drained"] = True
        return True

    def _namespace(self, engine, status, reason=None):
        binding = self.binding
        return {"namespace_id": engine.archive.directory.name, "status": status,
            "admitted_evidence": False, "semantics": "diagnostic-attempts-only; retirement freezes observed prefixes; late writes excluded",
            "scope": {"service_instance_id": self.instance_id, "session_id": binding[0],
                "capture_session_id": binding[1], "source_id": binding[2], "epoch": binding[3],
                "width": binding[6], "height": binding[7]},
            "sequence": engine.last_frame, "retirement_reason": reason,
            "workers_drained": False, "frozen_prefix": status == "retired-uncommitted",
            "visual_log": {"path": str((engine.archive.directory / "visual.jsonl").relative_to(self.root)),
                "bytes": engine.log_bytes, "complete": engine.log_complete},
            "context_log": {"path": str((engine.archive.directory / "context.jsonl").relative_to(self.root)),
                "bytes": engine.context.log_bytes, "complete": engine.context.log_complete},
            "archive": {"frames": len(engine.archive.receipts), "bytes": engine.archive.bytes,
                "log_bytes": engine.archive.log_bytes, "complete": engine.archive.complete}}

    def _state(self, binding):
        session, owner, source, epoch, _, _, width, height = binding
        return {"session_id": session, "server": {"instance_id": self.instance_id},
                "capture_session": {"session_id": owner, "status": "capturing"},
                "capture": {"fresh_capture": True, "source_id": source, "epoch": epoch, "width": width, "height": height}}

    def _project(self, engine, binding, token, serial):
        fingerprint = (id(engine.value), id(engine.context.value), id(engine.numeric.value),
                       id(engine.latest_pixels), id(engine.archive.public))
        if fingerprint == self._fingerprint:
            return False
        state = self._state(binding)
        context = engine.context.snapshot(state)
        masks = (context or {}).get("occluded_regions", [])
        cache = {"table_context": context, "visual_observation": engine.snapshot(state, occluded_regions=masks),
                 "numeric_observation": engine.numeric.snapshot(state, occluded_regions=masks),
                 "event_evidence": engine.archive.snapshot(),
                 "numeric_diagnostics": {"attempts": engine.numeric.attempts, "dropped_frames": engine.numeric.dropped,
                    "error": engine.numeric.last_error, "last_timing": copy.deepcopy(engine.numeric.last_timing)},
                 "context_diagnostics": {"attempts": engine.context.attempts, "dropped_frames": engine.context.dropped,
                    "error": engine.context.last_error, "log_complete": engine.context.log_complete,
                    "log_bytes": engine.context.log_bytes, "log_path": str((engine.archive.directory / "context.jsonl").relative_to(self.root))}}
        leases = {key: getattr(cache[key], "deadline", None)
                  for key in ("table_context", "visual_observation", "numeric_observation")}
        with self.lock:
            if not token.is_set() and self.engine is engine and serial == self.serial and serial == self.validated:
                self.cache, self.leases = cache, leases
                self._fingerprint = fingerprint
                self.regions = getattr(engine, "regions", None) or self.region_manifest
                if context is not None and context.get("capture", {}).get("sequence") == engine.last_frame:
                    self.mask_regions = copy.deepcopy(masks)
                    self.mask_fields.clear()
                    self.mask_mapping_incomplete = False
                else:
                    self.mask_regions = self._merge_masks(self.mask_regions, masks, binding[6], binding[7])
                board = (cache.get("visual_observation") or {}).get("board") or {}
                if board.get("last_seen"):
                    self.last_seen = copy.deepcopy(board["last_seen"])
                    self.last_projection = cache["visual_observation"]
                return True
        return False

    def _run(self):
        while not self.closed.is_set():
            self.wake.wait(.05)
            self.wake.clear()
            with self.lock:
                retired = self.retiring
            if retired is not None:
                if self._alive(retired):
                    continue
                if not self._dispose(retired):
                    continue
                with self.lock:
                    if self.retiring is retired:
                        self.retiring = None
            with self.lock:
                pending, self.pending = self.pending, None
                self.executing = pending is not None
            if pending is not None:
                row, binding, token, serial, received = pending
                started = self.monotonic()
                try:
                    frame, filename, png = self._pin(row)
                    with self.lock:
                        if token.is_set() or serial != self.serial:
                            self._drop("retired-binding" if token.is_set() else "superseded")
                            continue
                        engine = self.engine
                    if engine is None:
                        candidate = VisualLanes(self.root, self.instance_id, wall=self.wall, monotonic=self.monotonic)
                        candidate.archive.directory = candidate.archive.directory / ("uncommitted-" + uuid.uuid4().hex)
                        candidate.archive_readers = 0
                        candidate.archive_readers_done = threading.Event()
                        candidate.archive_readers_done.set()
                        candidate.archive.max_bytes -= self.used_budget["bytes"]
                        candidate.archive.max_frames -= self.used_budget["frames"]
                        candidate.archive.max_log_bytes -= self.used_budget["log_bytes"]
                        candidate.context.log_limit = max(0, MAX_LOG_BYTES - self.used_budget["context_log_bytes"])
                        candidate.log_limit = max(0, MAX_LOG_BYTES - self.used_budget["visual_log_bytes"])
                        if self.storage_incomplete["archive"]:
                            candidate.archive.complete, candidate.archive.reason = False, "service-archive-incomplete"
                        candidate.context.log_complete = not self.storage_incomplete["context_log"]
                        candidate.log_complete = not self.storage_incomplete["visual_log"]
                        candidate.archive._cache_status()
                        with self.lock:
                            if token.is_set() or serial != self.serial:
                                candidate.revoke()
                                self._drop("retired-binding")
                                continue
                            self.engine = engine = candidate
                    # All comparisons and lane-facing locks are behind this boundary.
                    engine.submit_pinned(frame, filename, (binding[0], binding[2], binding[3]), png)
                    with self.lock:
                        if not token.is_set() and serial == self.serial:
                            self.validated = serial
                except Exception as error:
                    with self.lock:
                        reason = str(error) if str(error) in ("slot-overwritten/hash-mismatch", "expired") else "visual-worker-error"
                        self._drop(reason)
                        self.last_error = type(error).__name__ + ":" + reason
                        if self.token is token:
                            self._retire(reason)
                finally:
                    with self.lock:
                        self.executing = False
                        self.stages.append({"sequence": row["frame"]["frame_index"],
                            "queue_ms": round(max(0, started - received) * 1000, 3),
                            "ingress_ms": round(max(0, self.monotonic() - started) * 1000, 3)})
            with self.lock:
                engine, binding, token, serial = self.engine, self.binding, self.token, self.serial
            if engine is not None and token is not None and not token.is_set():
                started = self.monotonic()
                projected = False
                try:
                    projected = self._project(engine, binding, token, serial)
                except Exception as error:
                    with self.lock:
                        self.last_error = type(error).__name__ + ":projection"
                        self._drop("visual-worker-error")
                        if self.engine is engine:
                            self._retire("projection-failed")
                finally:
                    with self.lock:
                        if projected:
                            self.stages.append({"stage": "projection", "sequence": self.ticket[0],
                                "duration_ms": round(max(0, self.monotonic() - started) * 1000, 3)})

    def diagnostics(self):
        with self.lock:
            namespaces = copy.deepcopy(list(self.namespace_history))
            if self.engine is not None:
                namespaces.append(self._namespace(self.engine, "active"))
            return {"schema_version": 1, "drops": dict(self.counts), "stages": list(self.stages), "pending": int(self.pending is not None),
                    "executing": self.executing, "retirement_reason": self.retirement_reason,
                    "error": self.last_error,
                    "shutdown_pending": self.closed.is_set() and not self.shutdown_complete.is_set(),
                    "shutdown_complete": self.shutdown_complete.is_set(), "retirement_pending": self.retiring is not None,
                    "retired_archive_usage": dict(self.used_budget),
                    "storage_incomplete": dict(self.storage_incomplete),
                    "mask_mapping_incomplete": self.mask_mapping_incomplete,
                    "namespaces": namespaces, "namespace_overflow_count": self.namespace_overflow,
                    "archive_semantics": "active-runtime-index-only; retired uncommitted directories are inaccessible"}

    def cached_snapshot(self, state):
        with self.lock:
            binding, token, serial, validated = self.binding, self.token, self.serial, self.validated
            cache, leases = self.cache, self.leases
            previous = self.last_projection
        result = {"table_context": None, "visual_observation": None, "numeric_observation": None,
                  "event_evidence": self._empty_archive.snapshot()}
        if binding is not None and token is not None and not token.is_set():
            current, receipt = state.get("capture") or {}, state.get("capture_session") or {}
            expected = self._state(binding)
            if (state.get("session_id") == binding[0] and receipt.get("session_id") == binding[1]
                    and receipt.get("status") == "capturing" and current.get("fresh_capture")
                    and (state.get("server") or {}).get("instance_id") == self.instance_id
                    and all(current.get(k) == expected["capture"][k] for k in ("source_id", "epoch", "width", "height"))
                    and serial == validated):
                result.update(copy.deepcopy(cache))
                for key, age in (("table_context", CONTEXT_AGE_MS), ("visual_observation", MAX_AGE_MS), ("numeric_observation", MAX_AGE_MS)):
                    value = result.get(key)
                    capture = (value or {}).get("capture") or value or {}
                    if value is not None:
                        identity = tuple(capture.get(k) for k in ("sequence", "captured_at_ms", "captured_at_unix_ms", "sha256"))
                        expired = (leases.get(key) is None or self.monotonic() >= leases[key]
                            or not 0 <= self.wall() * 1000 - capture.get("captured_at_unix_ms", 0) < age)
                        with self.lock:
                            if token is self.token and serial == self.serial:
                                if expired and self._capture_identity(self.cache.get(key)) == identity:
                                    self.expired_captures[key] = identity
                                expired = expired or self.expired_captures.get(key) == identity
                        if expired:
                            result[key] = None
            if (result["visual_observation"] is None and previous is not None
                    and state.get("session_id") == binding[0] and receipt.get("session_id") == binding[1]
                    and receipt.get("status") == "capturing"
                    and current.get("source_id") == binding[2] and current.get("epoch") == binding[3]):
                # Historical sightings remain explicitly separate from current
                # cards while validation, recognition, or the original lease fails.
                result["visual_observation"] = self._withhold_visual(copy.deepcopy(previous))
        result["visual_diagnostics"] = self.diagnostics()
        # Final token/sequence check after copying, without any pixel/cache lock.
        with self.lock:
            if token is not self.token or token is not None and token.is_set() or serial != self.serial:
                for key in ("table_context", "visual_observation", "numeric_observation"):
                    result[key] = None
                result["event_evidence"] = self._empty_archive.snapshot()
                for key in ("numeric_diagnostics", "context_diagnostics"):
                    result.pop(key, None)
                result["visual_diagnostics"]["namespaces"] = []
        return _VisualProjection(result, binding, token, serial, leases)

    @staticmethod
    def _capture_identity(value):
        if value is None:
            return None
        capture = value.get("capture") or value
        return tuple(capture.get(k) for k in ("sequence", "captured_at_ms", "captured_at_unix_ms", "sha256"))

    @staticmethod
    def _withhold_visual(visual):
        if visual is None:
            return None
        visual["current_uncertain"] = True
        for slot in visual.get("board_slots", []):
            slot.update(card=None, status="unknown", reason="visual-validation-pending-or-expired")
        board = visual.get("board") or {}
        board.update(candidate_cards=None, stage=None, empty_board_supported=False)
        for slot in board.get("slots", []):
            slot.update(card=None, status="unknown")
        visual.update(actions=None, revealed_cards=None, sightings=[])
        return visual

    def fence_snapshot(self, snapshot, projection):
        """Final metadata-only gate, ordered with feed submit/retirement."""
        with self.lock:
            binding, token, serial = self.binding, self.token, self.serial
            current = (isinstance(projection, _VisualProjection) and projection.binding == binding
                and projection.token is token and token is not None and not token.is_set()
                and projection.serial == serial)
        capture, receipt = snapshot.get("capture") or {}, snapshot.get("capture_session") or {}
        same_scope = (binding is not None and snapshot.get("session_id") == binding[0]
            and receipt.get("session_id") == binding[1] and receipt.get("status") == "capturing"
            and (snapshot.get("server") or {}).get("instance_id") == self.instance_id
            and (capture.get("source_id"), capture.get("epoch"), capture.get("width"), capture.get("height"))
                == (binding[2], binding[3], binding[6], binding[7]))
        if not current or not same_scope or not capture.get("fresh_capture"):
            visual = snapshot.get("visual_observation")
            original = (visual or {}).get("capture") or {}
            historical = (same_scope and isinstance(projection, _VisualProjection) and projection.binding == binding
                and (original.get("session_id"), original.get("capture_session_id"), original.get("source_id"),
                     original.get("epoch")) == (binding[0], binding[1], binding[2], binding[3]))
            snapshot.update(table_context=None, numeric_observation=None,
                visual_observation=self._withhold_visual(visual) if historical else None,
                event_evidence=self._empty_archive.snapshot())
            for key in ("numeric_diagnostics", "context_diagnostics"):
                snapshot.pop(key, None)
            if isinstance(snapshot.get("visual_diagnostics"), dict):
                snapshot["visual_diagnostics"]["namespaces"] = []
            return
        for key, age in (("table_context", CONTEXT_AGE_MS), ("visual_observation", MAX_AGE_MS), ("numeric_observation", MAX_AGE_MS)):
            value = snapshot.get(key)
            source = (value or {}).get("capture") or value or {}
            if value is None:
                continue
            identity = tuple(source.get(k) for k in ("sequence", "captured_at_ms", "captured_at_unix_ms", "sha256"))
            expired = (projection.leases.get(key) is None or self.monotonic() >= projection.leases[key]
                or not 0 <= self.wall() * 1000 - source.get("captured_at_unix_ms", 0) < age)
            with self.lock:
                if serial == self.serial and token is self.token:
                    if expired and self._capture_identity(self.cache.get(key)) == identity:
                        self.expired_captures[key] = identity
                    expired = expired or self.expired_captures.get(key) == identity
            if expired:
                snapshot[key] = self._withhold_visual(value) if key == "visual_observation" else None
        with self.lock:
            retired = token is not self.token or token.is_set() or serial != self.serial
            replaced = binding != self.binding
        if retired:
            snapshot.update(table_context=None, numeric_observation=None,
                visual_observation=None if replaced else self._withhold_visual(snapshot.get("visual_observation")),
                event_evidence=self._empty_archive.snapshot())
            for key in ("numeric_diagnostics", "context_diagnostics"):
                snapshot.pop(key, None)
            if isinstance(snapshot.get("visual_diagnostics"), dict):
                snapshot["visual_diagnostics"]["namespaces"] = []

    def mask_snapshot(self, snapshot, context):
        with self.lock:
            binding = self.binding
            masks = copy.deepcopy(self.mask_regions)
            fields = set(self.mask_fields)
        current, receipt = snapshot.get("capture") or {}, snapshot.get("capture_session") or {}
        if (binding is None or snapshot.get("session_id") != binding[0] or receipt.get("session_id") != binding[1]
                or current.get("source_id") != binding[2] or current.get("epoch") != binding[3]
                or [current.get("width"), current.get("height")] != [binding[6], binding[7]]):
            return
        _mask_native_snapshot(self, snapshot, {"occluded_regions": masks, "covered_fields": fields})

    def stop(self):
        self.closed.set()
        self.revoke("stopped")
        self.wake.set()
        if self.thread is not None:
            self.thread.join(timeout=.1)
        # No timeout is represented as termination or archive closure.
        def finish():
            if self.thread is not None:
                self.thread.join()
            retired = self.retiring
            if retired is not None:
                for worker in (retired, retired.context, retired.numeric):
                    if worker.thread is not None:
                        worker.thread.join()
                retired.archive_readers_done.wait()
                if not self._dispose(retired):
                    return
                with self.lock:
                    if self.retiring is retired:
                        self.retiring = None
            self.shutdown_complete.set()
        with self.lock:
            if self._cleanup_started:
                return
            self._cleanup_started = True
        threading.Thread(target=finish, name="visual-retirement", daemon=True).start()
